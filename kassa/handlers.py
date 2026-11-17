"""Telegram handlerlar: /kassa, /hisobot, /oy, /bekor va tugmalar (FSM)."""
from __future__ import annotations

import contextlib
import logging
import re
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from .config import FIELDS, MONTHS_UZ, STATUS_SENT, Allowed, boss_id
from .db import KassaDBError, get_db
from .keyboards import btn, kb_field, kb_menu, kb_report
from .logic import compute, fmt, fmt_date, net_income, parse_amount, parse_date, today_tz
from .render import render_report
from .sheets import schedule_sheets_sync

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(Allowed(), F.chat.type == "private")
router.callback_query.filter(Allowed())


# ───────────────────────── FSM ─────────────────────────

class KassaFSM(StatesGroup):
    sana = State()     # boshqa sana matni kutilmoqda
    boshi = State()    # kun boshiga qoldiq matni kutilmoqda
    qiymat = State()   # joriy qator summasi kutilmoqda


def active_fields(rejim: str) -> list[tuple[str, str]]:
    return [(k, lbl) for k, lbl, _, asosiy in FIELDS if rejim == "hammasi" or asosiy]


async def _strip_kb(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Eski tugmalarni olib tashlaydi (eskirgan tugma bosilmasligi uchun)."""
    if not message_id:
        return
    with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)


async def _show_menu(message: Message, state: FSMContext, sana: date) -> None:
    await state.clear()
    await state.update_data(sana=sana.isoformat())
    note = ""
    try:
        existing = await get_db().get(sana)
        if existing:
            sent = " (boshliqqa YUBORILGAN)" if existing["status"] == STATUS_SENT else ""
            note = (f"\n\n⚠️ Bu sana uchun hisobot bor{sent}, versiya {existing['versiya']}. "
                    f"Qayta kiritsangiz <b>almashtiriladi</b>.")
    except KassaDBError as e:
        await message.answer(f"⚠️ {e}")
        return
    sent_msg = await message.answer(
        f"📒 <b>Kassa hisoboti</b>\n📅 Sana: <b>{fmt_date(sana)}</b>{note}\n\nQanday kiritasiz?",
        reply_markup=kb_menu(),
    )
    await state.update_data(pmid=sent_msg.message_id)


async def _ask_field(message: Message, state: FSMContext, idx: int) -> None:
    data = await state.get_data()
    fields = active_fields(data["rejim"])
    key, label = fields[idx]
    await state.set_state(KassaFSM.qiymat)
    sent = await message.answer(
        f"<b>{idx + 1}/{len(fields)}</b> — {label}\nSummani yozing (so'mda):",
        reply_markup=kb_field(idx),
    )
    await state.update_data(idx=idx, pmid=sent.message_id)


async def _show_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    boshi = int(data["boshi"])
    vals = data["vals"]
    res = compute(boshi, vals)
    sana = date.fromisoformat(data["sana"])
    lines = [f"📒 <b>Tekshiring</b> — {fmt_date(sana)}", "", f"Kun boshiga qoldiq: <b>{fmt(boshi)}</b>"]
    if data.get("boshi_qolda"):
        lines.append(f"⚠️ <i>qo'lda o'zgartirilgan (kechagi hisobot: {fmt(data.get('prev_qoldiq', 0))})</i>")
    lines.append("")
    for key, label in active_fields(data["rejim"]):
        lines.append(f"{label}: <b>{fmt(vals.get(key, 0))}</b>")
    lines += [
        "",
        f"Jami tushum: <b>{fmt(res['jami_tushum'])}</b>",
        f"Jami chiqim: <b>{fmt(res['jami_chiqim'])}</b>",
        f"Kun oxiriga qoldiq: <b>{fmt(res['qoldiq'])}</b>",
    ]
    if res["qoldiq"] < 0:
        lines += ["", "❌ <b>Qoldiq manfiy chiqdi</b> — kassada bunday bo'lmaydi. Raqamlarni qaytadan tekshiring."]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [btn("✏️ Qaytadan kiritish", "ks:redo")], [btn("❌ Bekor qilish", "ks:cancel")]])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [btn("✅ Saqlash", "ks:save")],
            [btn("✏️ Qaytadan kiritish", "ks:redo"), btn("❌ Bekor", "ks:cancel")]])
    await state.set_state(None)
    sent = await message.answer("\n".join(lines), reply_markup=kb)
    await state.update_data(pmid=sent.message_id)


# ───────────────────────── Buyruqlar ─────────────────────────

@router.message(Command("kassa"))
async def cmd_kassa(message: Message, state: FSMContext):
    await _show_menu(message, state, today_tz())


@router.message(Command("bekor"), StateFilter(KassaFSM))
async def cmd_bekor(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Kassa kiritish bekor qilindi.")


@router.message(Command("hisobot"))
async def cmd_hisobot(message: Message, command, state: FSMContext):
    arg = (command.args or "").strip()
    sana = parse_date(arg, today_tz()) if arg else today_tz()
    if sana is None:
        await message.answer("Sanani <code>13.11.2026</code> ko'rinishida yozing.")
        return
    try:
        row = await get_db().get(sana)
    except KassaDBError as e:
        await message.answer(f"⚠️ {e}")
        return
    if not row:
        await message.answer(f"{fmt_date(sana)} sanasi uchun hisobot topilmadi. Kiritish: /kassa")
        return
    await message.answer_photo(
        BufferedInputFile(render_report(row), filename=f"kassa_{row['sana']}.png"),
        caption=f"📒 Kassa hisoboti — {fmt_date(sana)} (versiya {row['versiya']})",
        reply_markup=kb_report(row),
    )


@router.message(Command("oy"))
async def cmd_oy(message: Message, command):
    arg = (command.args or "").strip()
    today = today_tz()
    year, month = today.year, today.month
    if arg:
        m = re.fullmatch(r"(\d{1,2})(?:[./-](\d{4}))?", arg)
        if not m or not 1 <= int(m.group(1)) <= 12:
            await message.answer("Masalan: <code>/oy 11</code> yoki <code>/oy 11.2026</code>")
            return
        month = int(m.group(1))
        year = int(m.group(2)) if m.group(2) else today.year
    try:
        rows = await get_db().month(year, month)
    except KassaDBError as e:
        await message.answer(f"⚠️ {e}")
        return
    if not rows:
        await message.answer(f"{MONTHS_UZ[month - 1]} {year}: hisobot yo'q.")
        return
    lines = [f"📊 <b>{MONTHS_UZ[month - 1]} {year}</b> — kassa", ""]
    for r in rows:
        d = date.fromisoformat(r["sana"])
        lines.append(f"{d.strftime('%d.%m')} | tushum {fmt(net_income(r))} | chiqim {fmt(r['jami_chiqim'])} | qoldiq {fmt(r['qoldiq'])}")
    total_in = sum(net_income(r) for r in rows)
    total_out = sum(int(r["jami_chiqim"]) for r in rows)
    have = {date.fromisoformat(r["sana"]).day for r in rows}
    last_day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    until = min(last_day, today.day) if (year, month) == (today.year, today.month) else last_day
    missing = [str(i) for i in range(1, until + 1) if i not in have]
    lines += [
        "",
        f"Oy boshiga qoldiq: <b>{fmt(rows[0]['kun_boshiga'])}</b>",
        f"Jami tushum: <b>{fmt(total_in)}</b>",
        f"Jami chiqim: <b>{fmt(total_out)}</b>",
        f"Oy oxiriga qoldiq: <b>{fmt(rows[-1]['qoldiq'])}</b>",
    ]
    if missing:
        lines.append(f"\nℹ️ Hisobot kiritilmagan kunlar: {', '.join(missing)}")
    await message.answer("\n".join(lines))


# ───────────────────────── Tugmalar ─────────────────────────

@router.callback_query(F.data == "ks:noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "ks:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Bekor qilindi")
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text("❌ Kassa kiritish bekor qilindi.")


@router.callback_query(F.data == "ks:date")
async def cb_date(call: CallbackQuery, state: FSMContext):
    await state.set_state(KassaFSM.sana)
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    await call.message.answer("Sanani yozing, masalan: <code>13.11.2026</code> (yoki <code>kecha</code>).")


@router.message(KassaFSM.sana, F.text, ~F.text.startswith("/"))
async def msg_date(message: Message, state: FSMContext):
    sana = parse_date(message.text, today_tz())
    if sana is None:
        await message.answer("Sana tushunarsiz. Masalan: <code>13.11.2026</code>")
        return
    if sana > today_tz():
        await message.answer("Kelajak sana uchun hisobot kiritib bo'lmaydi.")
        return
    await _show_menu(message, state, sana)


@router.callback_query(F.data.startswith("ks:mode:"))
async def cb_mode(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "sana" not in data:
        await call.answer("Eskirgan tugma. /kassa ni qayta bosing.", show_alert=True)
        return
    rejim = call.data.split(":")[2]
    sana = date.fromisoformat(data["sana"])
    try:
        prev = await get_db().prev(sana)
    except KassaDBError as e:
        await call.answer(str(e)[:190], show_alert=True)
        return
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    await state.update_data(
        rejim=rejim, vals={}, idx=0, boshi_qolda=False,
        prev_qoldiq=int(prev["qoldiq"]) if prev else 0,
        prev_sana=prev["sana"] if prev else None,
        saving=False,
    )
    if prev:
        await state.update_data(boshi=int(prev["qoldiq"]))
        sent = await call.message.answer(
            f"Kun boshiga qoldiq: <b>{fmt(prev['qoldiq'])}</b>\n"
            f"<i>({fmt_date(prev['sana'])} hisobotining oxirgi qoldig'i)</i>\n\nTo'g'rimi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [btn("✅ To'g'ri", "ks:boshi:ok"), btn("✏️ O'zgartirish", "ks:boshi:edit")],
                [btn("❌ Bekor qilish", "ks:cancel")]]),
        )
        await state.update_data(pmid=sent.message_id)
    else:
        await state.set_state(KassaFSM.boshi)
        await call.message.answer(
            "Bu birinchi hisobot. <b>Kun boshiga qoldiq</b> summasini yozing (so'mda):")


@router.callback_query(F.data == "ks:boshi:ok")
async def cb_boshi_ok(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "boshi" not in data or "rejim" not in data:
        await call.answer("Eskirgan tugma. /kassa ni qayta bosing.", show_alert=True)
        return
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    await _ask_field(call.message, state, 0)


@router.callback_query(F.data == "ks:boshi:edit")
async def cb_boshi_edit(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "rejim" not in data:
        await call.answer("Eskirgan tugma. /kassa ni qayta bosing.", show_alert=True)
        return
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    await state.set_state(KassaFSM.boshi)
    await call.message.answer("Kun boshiga qoldiq summasini yozing (so'mda):")


@router.message(KassaFSM.boshi, F.text, ~F.text.startswith("/"))
async def msg_boshi(message: Message, state: FSMContext):
    n = parse_amount(message.text)
    if n is None:
        await message.answer("Faqat raqam yozing, masalan <code>646882350</code> yoki <code>646 882 350</code>.")
        return
    data = await state.get_data()
    qolda = bool(data.get("prev_sana")) and n != int(data.get("prev_qoldiq", 0))
    await state.update_data(boshi=n, boshi_qolda=qolda)
    await _ask_field(message, state, 0)


@router.message(KassaFSM.qiymat, F.text, ~F.text.startswith("/"))
async def msg_value(message: Message, state: FSMContext):
    n = parse_amount(message.text)
    if n is None:
        await message.answer("Faqat raqam yozing (kasr emas), masalan <code>90740600</code> yoki <code>90 740 600</code>. "
                             "Yo'q bo'lsa <code>0</code>.")
        return
    await _store_value(message, state, n)


async def _store_value(message: Message, state: FSMContext, n: int) -> None:
    data = await state.get_data()
    fields = active_fields(data["rejim"])
    idx = int(data["idx"])
    vals = dict(data["vals"])
    vals[fields[idx][0]] = n
    await state.update_data(vals=vals)
    await _strip_kb(message.bot, message.chat.id, data.get("pmid"))
    if idx + 1 < len(fields):
        await _ask_field(message, state, idx + 1)
    else:
        await _show_confirm(message, state)


@router.callback_query(F.data.startswith("ks:zero:"))
async def cb_zero(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[2])
    if await state.get_state() != KassaFSM.qiymat.state or int(data.get("idx", -1)) != idx:
        await call.answer("Eskirgan tugma.", show_alert=True)
        return
    await call.answer()
    await _store_value(call.message, state, 0)


@router.callback_query(F.data.startswith("ks:back:"))
async def cb_back(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[2])
    if await state.get_state() != KassaFSM.qiymat.state or int(data.get("idx", -1)) != idx:
        await call.answer("Eskirgan tugma.", show_alert=True)
        return
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    if idx == 0:
        await _show_menu(call.message, state, date.fromisoformat(data["sana"]))
    else:
        await _ask_field(call.message, state, idx - 1)


@router.callback_query(F.data == "ks:redo")
async def cb_redo(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "sana" not in data:
        await call.answer("Eskirgan tugma. /kassa ni qayta bosing.", show_alert=True)
        return
    await call.answer()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    await _show_menu(call.message, state, date.fromisoformat(data["sana"]))


@router.callback_query(F.data == "ks:save")
async def cb_save(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "vals" not in data or "boshi" not in data:
        await call.answer("Eskirgan tugma. /kassa ni qayta bosing.", show_alert=True)
        return
    if data.get("saving"):
        await call.answer("Saqlanmoqda...")
        return
    res = compute(int(data["boshi"]), data["vals"])
    if res["qoldiq"] < 0:
        await call.answer("Qoldiq manfiy — saqlab bo'lmaydi.", show_alert=True)
        return
    await state.update_data(saving=True)
    sana = date.fromisoformat(data["sana"])
    try:
        row = await get_db().save(sana, int(data["boshi"]), bool(data.get("boshi_qolda")),
                                  data["vals"], call.from_user.id)
    except KassaDBError as e:
        logger.exception("Kassa saqlashda xato")
        await state.update_data(saving=False)
        await call.answer(f"Saqlanmadi: {str(e)[:150]}", show_alert=True)
        return
    await call.answer("Saqlandi ✅")
    await state.clear()
    await _strip_kb(call.bot, call.message.chat.id, call.message.message_id)
    schedule_sheets_sync(row)
    await call.message.answer_photo(
        BufferedInputFile(render_report(row), filename=f"kassa_{row['sana']}.png"),
        caption=(f"✅ Saqlandi — {fmt_date(sana)} (versiya {row['versiya']})\n"
                 f"Hammasi to'g'ri bo'lsa, boshliqqa yuboring."),
        reply_markup=kb_report(row),
    )


@router.callback_query(F.data.startswith("ks:edit:"))
async def cb_edit(call: CallbackQuery, state: FSMContext):
    try:
        sana = date.fromisoformat(call.data.split(":", 2)[2])
    except ValueError:
        await call.answer("Xato sana.", show_alert=True)
        return
    await call.answer()
    await _show_menu(call.message, state, sana)


@router.callback_query(F.data.startswith("ks:send:"))
async def cb_send(call: CallbackQuery, state: FSMContext):
    boss = boss_id()
    if not boss:
        await call.answer("Boshliq ID sozlanmagan (KASSA_BOSS_ID).", show_alert=True)
        return
    try:
        sana = date.fromisoformat(call.data.split(":", 2)[2])
        db = get_db()
        row = await db.get(sana)
    except (ValueError, KassaDBError) as e:
        await call.answer(f"Xato: {str(e)[:150]}", show_alert=True)
        return
    if not row:
        await call.answer("Hisobot topilmadi.", show_alert=True)
        return
    if row["status"] == STATUS_SENT:
        await call.answer("Bu hisobot allaqachon yuborilgan.", show_alert=True)
        with contextlib.suppress(TelegramBadRequest):
            await call.message.edit_reply_markup(reply_markup=kb_report(row))
        return
    try:
        claimed = await db.mark_sent(sana, int(row["versiya"]))
    except KassaDBError as e:
        await call.answer(f"Xato: {str(e)[:150]}", show_alert=True)
        return
    if not claimed:
        await call.answer("Hisobot o'zgargan yoki allaqachon yuborilgan. /hisobot orqali yangilang.", show_alert=True)
        return
    caption = f"📒 Kassa hisoboti — {fmt_date(sana)}"
    if int(claimed["versiya"]) > 1:
        caption += f"\n🔄 Tuzatilgan hisobot (v{claimed['versiya']})"
    try:
        await call.bot.send_photo(
            boss,
            BufferedInputFile(render_report(claimed), filename=f"kassa_{claimed['sana']}.png"),
            caption=caption,
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        with contextlib.suppress(KassaDBError):
            await db.unmark_sent(sana, int(claimed["versiya"]))
        logger.error("Boshliqqa yuborib bo'lmadi: %s", e)
        await call.answer("Boshliqqa yuborib bo'lmadi: u botni /start qilmagan yoki to'sgan bo'lishi mumkin.", show_alert=True)
        return
    except Exception as e:
        with contextlib.suppress(KassaDBError):
            await db.unmark_sent(sana, int(claimed["versiya"]))
        logger.exception("Boshliqqa yuborishda kutilmagan xato")
        await call.answer(f"Yuborilmadi: {str(e)[:150]}", show_alert=True)
        return
    schedule_sheets_sync(claimed)
    await call.answer("Boshliqqa yuborildi ✅")
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_reply_markup(reply_markup=kb_report(claimed))
