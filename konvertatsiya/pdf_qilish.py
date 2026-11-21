"""
📄 PDF qilish — rasm (bir nechta/albom), Word, Excel, PowerPoint, TXT va PDF fayllarni
bitta PDF ga birlashtirish YOKI har birini alohida PDF qilish.

Oqim:
  fayllar yuboriladi (albom ham bo'ladi; bitta holat xabari yangilanib turadi)
  -> [✅ Tayyor]
     1 ta fayl  -> nom so'raladi (yoki o'tkazib yuboriladi) -> PDF
     2+ fayl    -> [📄 Bitta PDF] (nom so'raladi) yoki [🗂 Alohida PDFlar]
  Natija: 1 ta fayl, 2..10 ta — albom, 10 dan ko'p — ZIP.

Albom bir vaqtda bir nechta xabar bo'lib keladi: state filtri handler'dan OLDIN
tekshiriladi, shu uchun handler ichida user-lock ostida holat qayta tekshiriladi.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from dataclasses import asdict
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import common, imaging, office, pdftools
from .common import (EXPIRED_TEXT, MAX_FILE_MB, MB, ConvertError, Item, Output,
                     PRIVATE)
from .keyboards import btn, kb_cancel, kb_done, kb_menu
from .names import clean_stem, now_stamp
from .registry import Tool, register

logger = logging.getLogger(__name__)

router = Router(name="konv_pdf_qilish")
router.message.filter(PRIVATE)

MAX_ITEMS = 20
MAX_TOTAL_MB = 60
DEBOUNCE = 1.2
PROGRESS_EVERY = 2.0
_sem = asyncio.Semaphore(2)
ICON = {"image": "🖼", "pdf": "📕", "office": "📝"}


class PQ(StatesGroup):
    collecting = State()
    mode = State()
    name = State()


def esc(s) -> str:
    return html.escape(str(s), quote=False)


# ───────── tugmalar / matnlar ─────────

def kb_collect(n: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"✅ Tayyor ({n})", "konv:pq:done")],
        [btn("🧹 Tozalash", "konv:pq:clear")],
        [btn("⬅️ Ortga", "konv:menu"), btn("❌ Bekor qilish", "konv:cancel")],
    ])


def kb_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("📄 Bitta PDF", "konv:pq:mode:one")],
        [btn("🗂 Alohida PDFlar", "konv:pq:mode:sep")],
        [btn("⬅️ Fayllarga qaytish", "konv:pq:back"), btn("❌ Bekor qilish", "konv:cancel")],
    ])


def kb_name() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("⏭ O'tkazib yuborish", "konv:pq:skip")],
        [btn("⬅️ Ortga", "konv:pq:back"), btn("❌ Bekor qilish", "konv:cancel")],
    ])


def prompt_text() -> str:
    office_line = ("• Word, Excel, PowerPoint, TXT\n" if office.available()
                   else "• <i>Word/Excel hozircha o'chiq (serverda LibreOffice yo'q)</i>\n")
    return ("📄 <b>PDF qilish</b>\n\n"
            "Quyidagilarni yuboring (bir nechta yoki albom ham bo'ladi):\n"
            "• Rasm (JPG, PNG, WEBP…) — «fayl» sifatida yuborsangiz sifat saqlanadi\n"
            f"{office_line}"
            "• PDF (birlashtirish uchun)\n\n"
            f"Eng ko'pi {MAX_ITEMS} ta, har biri {MAX_FILE_MB} MB gacha.\n"
            "Tugagach ✅ <b>Tayyor</b> tugmasini bosing.")


def status_text(items: list[Item], rejected: list[str]) -> str:
    lines = [f"📥 <b>{len(items)} ta fayl qabul qilindi</b>", ""]
    for i, it in enumerate(items[:10], 1):
        nm = esc((it.name or "rasm")[:35])
        lines.append(f"{i}. {ICON[it.kind]} {nm}")
    if len(items) > 10:
        lines.append(f"… va yana {len(items) - 10} ta")
    if rejected:
        lines += ["", "⚠️ <b>Qabul qilinmadi:</b>"] + [f"• {esc(r)}" for r in rejected[-5:]]
    lines += ["", f"Yana yuboring yoki ✅ <b>Tayyor</b> bosing (jami ko'pi bilan {MAX_ITEMS} ta)."]
    return "\n".join(lines)


# ───────── fayl turini aniqlash ─────────

def classify(m: Message) -> tuple[Item | None, str | None]:
    if m.photo:
        p = m.photo[-1]
        return Item(p.file_id, None, p.file_size, "image", m.message_id), None
    d = m.document
    if not d:
        return None, "Fayl emas"
    name = d.file_name or ""
    low, mime = name.lower(), (d.mime_type or "").lower()
    label = name[:30] or "fayl"
    if mime in imaging.IMAGE_MIMES or low.endswith(imaging.IMAGE_EXTS):
        kind = "image"
    elif mime == "application/pdf" or low.endswith(".pdf"):
        kind = "pdf"
    elif low.endswith(office.OFFICE_EXTS):
        kind = "office"
        if not office.available():
            return None, f"{label} — Word/Excel bu serverda yoqilmagan"
    else:
        return None, f"{label} — format qo'llab-quvvatlanmaydi"
    if d.file_size and d.file_size > MAX_FILE_MB * MB:
        return None, f"{label} — {MAX_FILE_MB} MB dan katta"
    return Item(d.file_id, name or None, d.file_size, kind, m.message_id), None


def _items(data: dict) -> list[Item]:
    """Fayllar yuborilish tartibida (xabar ID bo'yicha): albom xabarlari bir vaqtda
    kelib, handlerlar tartibsiz ishlashi mumkin — tartibni message_id saqlaydi."""
    return sorted((Item(**d) for d in data.get("items", [])), key=lambda it: it.mid)


# ───────── kirish ─────────

@router.callback_query(F.data == "konv:pick:pdf_qilish")
async def pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    common.cancel_timer(uid)
    async with common.user_lock(uid):
        await state.clear()
        await state.set_state(PQ.collecting)
        await state.update_data(items=[], rejected=[], ts=time.time(), status_id=None)
    await common.edit_or_send(cb, prompt_text(), kb_cancel())


# ───────── fayllarni yig'ish ─────────

@router.message(PQ.collecting, F.photo | F.document)
async def on_file(m: Message, state: FSMContext, bot: Bot):
    uid = m.from_user.id
    item, why = classify(m)
    async with common.user_lock(uid):
        if await state.get_state() != PQ.collecting.state:
            return
        data = await state.get_data()
        if common.stale(data):
            await state.clear()
            await m.answer(EXPIRED_TEXT, reply_markup=kb_menu())
            return
        items, rejected = data.get("items", []), data.get("rejected", [])
        total = sum(i.get("size") or 0 for i in items) + ((item.size or 0) if item else 0)
        if item and len(items) >= MAX_ITEMS:
            item, why = None, f"limit: ko'pi bilan {MAX_ITEMS} ta fayl"
        elif item and total > MAX_TOTAL_MB * MB:
            item, why = None, f"jami hajm {MAX_TOTAL_MB} MB dan oshadi"
        if item:
            items.append(asdict(item))
        else:
            rejected.append(why or "noma'lum")
        await state.update_data(items=items, rejected=rejected[-10:], ts=time.time())
    common.set_timer(uid, asyncio.create_task(_status_later(bot, state, m.chat.id, uid)))


@router.message(PQ.collecting, common.not_cmd)
async def on_other(m: Message):
    await m.answer("Rasm yoki fayl yuboring (Word, Excel, PowerPoint, PDF), "
                   "tugagach ✅ Tayyor tugmasini bosing.")


async def _status_later(bot: Bot, state: FSMContext, chat_id: int, uid: int):
    await asyncio.sleep(DEBOUNCE)                       # albom xabarlari yig'ilguncha
    await asyncio.shield(_render_status(bot, state, chat_id, uid))


async def _render_status(bot: Bot, state: FSMContext, chat_id: int, uid: int):
    async with common.user_lock(uid):
        if await state.get_state() != PQ.collecting.state:
            return
        data = await state.get_data()
        items = _items(data)
        await common.delete_msg(bot, chat_id, data.get("status_id"))
        try:
            msg = await bot.send_message(chat_id, status_text(items, data.get("rejected", [])),
                                         reply_markup=kb_collect(len(items)))
        except Exception:
            logger.exception("status yuborilmadi")
            return
        await state.update_data(status_id=msg.message_id)


@router.callback_query(PQ.collecting, F.data == "konv:pq:clear")
async def clear_files(cb: CallbackQuery, state: FSMContext, bot: Bot):
    uid = cb.from_user.id
    common.cancel_timer(uid)
    async with common.user_lock(uid):
        if await state.get_state() != PQ.collecting.state:
            await cb.answer()
            return
        await state.update_data(items=[], rejected=[], ts=time.time(), status_id=None)
    await cb.answer("Tozalandi")
    await common.edit_or_send(cb, prompt_text(), kb_cancel())


# ───────── Tayyor -> rejim ─────────

@router.callback_query(PQ.collecting, F.data == "konv:pq:done")
async def on_done(cb: CallbackQuery, state: FSMContext, bot: Bot):
    uid = cb.from_user.id
    common.cancel_timer(uid)
    async with common.user_lock(uid):
        if await state.get_state() != PQ.collecting.state:
            await cb.answer()
            return
        data = await state.get_data()
        if common.stale(data):
            await state.clear()
            await cb.answer()
            await common.edit_or_send(cb, EXPIRED_TEXT, kb_menu())
            return
        items = _items(data)
        if not items:
            await cb.answer("Avval fayl yuboring", show_alert=True)
            return
        if len(items) == 1 and items[0].kind == "pdf":
            await cb.answer("Bitta PDF ni qayta PDF qilish shart emas. "
                            "Bo'lish uchun menyudan «PDFni bo'lish» ni tanlang.", show_alert=True)
            return
        await cb.answer()
        await state.update_data(ts=time.time(), status_id=cb.message.message_id)
        if len(items) == 1:
            await state.set_state(PQ.name)
            await _ask_name(cb, items)
        else:
            await state.set_state(PQ.mode)
            await common.edit_or_send(
                cb, f"📦 <b>{len(items)} ta fayl.</b> Qanday PDF qilamiz?\n\n"
                    "📄 <b>Bitta PDF</b> — hammasi tartib bilan birlashtiriladi\n"
                    "🗂 <b>Alohida PDFlar</b> — har bir fayl o'z PDF si bo'ladi", kb_mode())


async def _ask_name(cb: CallbackQuery, items: list[Item]):
    d = default_stem(items)
    await common.edit_or_send(
        cb, "✏️ <b>PDF fayl nomini yozing</b>\n"
            f"yoki o'tkazib yuboring (nom: <code>{esc(d)}.pdf</code>).", kb_name())


@router.callback_query(PQ.mode, F.data == "konv:pq:mode:one")
async def mode_one(cb: CallbackQuery, state: FSMContext):
    async with common.user_lock(cb.from_user.id):
        if await state.get_state() != PQ.mode.state:
            await cb.answer()
            return
        items = _items(await state.get_data())
        await state.set_state(PQ.name)
        await state.update_data(ts=time.time())
    await cb.answer()
    await _ask_name(cb, items)


@router.callback_query(PQ.mode, F.data == "konv:pq:mode:sep")
async def mode_sep(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await _take(cb.from_user.id, state, PQ.mode)
    await cb.answer()
    if data is None:
        await common.edit_or_send(cb, EXPIRED_TEXT, kb_menu())
        return
    await common.strip_kb(bot, cb.message.chat.id, cb.message.message_id)
    await _run(bot, cb.from_user.id, _items(data), "sep", None)


@router.callback_query(StateFilter(PQ.mode, PQ.name), F.data == "konv:pq:back")
async def back(cb: CallbackQuery, state: FSMContext):
    async with common.user_lock(cb.from_user.id):
        cur = await state.get_state()
        if cur not in (PQ.mode.state, PQ.name.state):
            await cb.answer()
            return
        await state.set_state(PQ.collecting)
        data = await state.get_data()
        await state.update_data(ts=time.time(), status_id=cb.message.message_id)
    await cb.answer()
    items = _items(data)
    await common.edit_or_send(cb, status_text(items, []), kb_collect(len(items)))


# ───────── nom ─────────

@router.message(PQ.name, F.text, common.not_cmd)
async def on_name(m: Message, state: FSMContext, bot: Bot):
    data = await _take(m.from_user.id, state, PQ.name)
    if data is None:
        return
    await _finish_merged(bot, m.from_user.id, m.chat.id, data, m.text)


@router.callback_query(PQ.name, F.data == "konv:pq:skip")
async def on_skip(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await _take(cb.from_user.id, state, PQ.name)
    await cb.answer()
    if data is None:
        return
    await common.strip_kb(bot, cb.message.chat.id, cb.message.message_id)
    await _finish_merged(bot, cb.from_user.id, cb.message.chat.id, data, None)


@router.message(PQ.name)
@router.message(PQ.mode)
async def on_wrong(m: Message):
    await m.answer("Iltimos, matn yozing yoki tugmalardan birini bosing.")


async def _finish_merged(bot: Bot, uid: int, chat_id: int, data: dict, raw: str | None):
    items = _items(data)
    stem = clean_stem(raw, ".pdf", default_stem(items))
    await _run(bot, uid, items, "one", stem, chat_id=chat_id)


async def _take(uid: int, state: FSMContext, expected: State) -> dict | None:
    """Holatni atomik 'olib' tozalaydi: ikki marta bosish/yuborish ikkinchi ishni boshlamaydi."""
    async with common.user_lock(uid):
        if await state.get_state() != expected.state:
            return None
        data = await state.get_data()
        await state.clear()
        if common.stale(data):
            return None
        return data


# ───────── konvertatsiya ─────────

def default_stem(items: list[Item]) -> str:
    if len(items) == 1 and items[0].name:
        return clean_stem(Path(items[0].name).stem, ".pdf", f"hujjat_{now_stamp()}")
    return (f"rasm_{now_stamp()}" if len(items) == 1 and items[0].kind == "image"
            else f"hujjat_{now_stamp()}")


async def _to_pdf(bot: Bot, it: Item) -> bytes:
    blob = await common.download(bot, it.file_id)
    if it.kind == "pdf":
        return blob
    if it.kind == "image":
        return await asyncio.to_thread(imaging.images_to_pdf, [blob])
    return await office.office_to_pdf(blob, it.name)


def _label(it: Item, i: int) -> str:
    return it.name or f"rasm {i}"


async def _run(bot: Bot, uid: int, items: list[Item], mode: str, stem: str | None,
               chat_id: int | None = None):
    chat_id = chat_id or uid
    wait = await bot.send_message(chat_id, f"⏳ Tayyorlanmoqda… (0/{len(items)})")
    last = 0.0
    try:
        async with _sem:
            pdfs: list[bytes | None] = []
            failed: list[str] = []
            for i, it in enumerate(items, 1):
                if time.monotonic() - last >= PROGRESS_EVERY:
                    last = time.monotonic()
                    with contextlib.suppress(Exception):
                        await wait.edit_text(f"⏳ Tayyorlanmoqda… ({i - 1}/{len(items)})")
                try:
                    pdfs.append(await _to_pdf(bot, it))
                except ConvertError as e:
                    if mode == "one":
                        raise ConvertError(f"{_label(it, i)}: {e}")
                    pdfs.append(None)
                    failed.append(f"{_label(it, i)} — {e}")
            if mode == "one":
                outs = [Output(f"{stem}.pdf", await asyncio.to_thread(pdftools.merge, pdfs))]
            else:
                stamp = now_stamp()
                outs = []
                for i, (it, pdf) in enumerate(zip(items, pdfs), 1):
                    if pdf is None:
                        continue
                    base = Path(it.name).stem if it.name else f"rasm_{stamp}_{i}"
                    outs.append(Output(f"{clean_stem(base, '.pdf', f'fayl_{i}')}.pdf", pdf))
                if not outs:
                    raise ConvertError(failed[0] if failed else "Natija bo'sh.")
        note = ("\n⚠️ O'tkazib bo'lmadi:\n" + "\n".join(f"• {esc(f)}" for f in failed[:5])) if failed else ""
        await common.deliver(bot, chat_id, outs, zip_stem=f"pdflar_{now_stamp()}", note=note.strip("\n"))
    except ConvertError as e:
        await bot.send_message(chat_id, f"❌ {esc(e)}", reply_markup=kb_done())
    except Exception:
        logger.exception("PDF qilishda kutilmagan xato")
        await bot.send_message(chat_id, "❌ Kutilmagan xato. Birozdan so'ng qayta urinib ko'ring.",
                               reply_markup=kb_done())
    finally:
        await common.delete_msg(bot, chat_id, wait.message_id)


register(Tool(key="pdf_qilish", button="📄 PDF qilish (rasm, Word, Excel…)",
              router=router, order=10))
