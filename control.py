from __future__ import annotations

import os
import re
import json
import base64
import asyncio
import logging
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

logger = logging.getLogger(__name__)
router = Router()

TZ = ZoneInfo("Asia/Tashkent")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))   # asosiy Fortuna guruhi — qattiq (sozlanmaydigan) rejim

SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
GROUPS_SHEET   = "guruhlar"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

GROUP_HEADERS = [
    "T/r", "Chat ID", "Guruh nomi", "Turi",
    "Birinchi admin sana", "Holati", "Oxirgi tekshirilgan",
    "Link sozlamasi", "Izoh",
]

# Havola sozlamasi variantlari (faqat TASHQI guruhlar uchun)
MODE_WARN   = "ogohlantirib_ochirish"
MODE_SILENT = "jim_ochirish"
MODE_ALLOW  = "ruxsat"
LINK_MODES  = {MODE_WARN, MODE_SILENT, MODE_ALLOW}
DEFAULT_MODE = MODE_SILENT   # tashqi guruhlar uchun xavfsiz standart holat

_gc: gspread.Client | None = None
_mode_cache: dict[int, str] = {}   # {chat_id: mode} — har xabarda Sheets o'qimaslik uchun


# ─── Sheets ulanish ──────────────────────────────────────────────────────

def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


def _groups_ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(GROUPS_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=GROUPS_SHEET, rows="200", cols="20")
        ws.append_row(GROUP_HEADERS)
        return ws


def _find_group_row(ws: gspread.Worksheet, chat_id: int) -> int | None:
    """Chat ID ustunida qidiradi. Sheets raqamni float saqlashi mumkinligini hisobga oladi."""
    for i, v in enumerate(ws.col_values(2), start=1):
        try:
            if int(float(str(v).strip())) == chat_id:
                return i
        except (ValueError, TypeError):
            continue
    return None


# ─── Guruhlar registri: yozish/o'qish ───────────────────────────────────

def _upsert_group_sync(chat_id: int, title: str, chat_type: str, is_admin: bool) -> None:
    """Guruhni ro'yxatga qo'shadi yoki holatini yangilaydi."""
    ws     = _groups_ws()
    row    = _find_group_row(ws, chat_id)
    now    = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    holati = "Faol" if is_admin else "Faol emas"

    if row:
        ws.update_cell(row, 3, title or "")
        ws.update_cell(row, 6, holati)
        ws.update_cell(row, 7, now)
        if is_admin and not str(ws.cell(row, 5).value or "").strip():
            ws.update_cell(row, 5, now)   # birinchi marta admin bo'lgan sana
    else:
        all_vals = ws.get_all_values()
        next_num = len(all_vals)  # sarlavha qatori hisobga olinib, keyingi raqam
        ws.append_row([
            str(next_num), str(chat_id), title or "", chat_type,
            now if is_admin else "", holati, now,
            DEFAULT_MODE, "",
        ])


def _load_all_groups_sync() -> list[dict]:
    ws       = _groups_ws()
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return []
    result = []
    for i, row in enumerate(all_vals[1:], start=2):
        if len(row) < 2 or not str(row[1]).strip():
            continue
        try:
            chat_id = int(float(str(row[1]).strip()))
        except ValueError:
            continue
        result.append({
            "row_idx": i,
            "chat_id": chat_id,
            "title":   row[2] if len(row) > 2 else "",
            "holati":  row[5] if len(row) > 5 else "",
        })
    return result


def _apply_status_updates_sync(updates: list[tuple[int, bool]]) -> None:
    ws  = _groups_ws()
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    for row_idx, is_admin in updates:
        ws.update_cell(row_idx, 6, "Faol" if is_admin else "Faol emas")
        ws.update_cell(row_idx, 7, now)


def _get_link_mode_sync(chat_id: int) -> str | None:
    ws  = _groups_ws()
    row = _find_group_row(ws, chat_id)
    if not row:
        return None
    val = ws.cell(row, 8).value
    return str(val).strip() if val else None


def _set_link_mode_sync(chat_id: int, mode: str, title: str = "") -> None:
    ws  = _groups_ws()
    row = _find_group_row(ws, chat_id)
    if row:
        ws.update_cell(row, 8, mode)
        if title and not str(ws.cell(row, 3).value or "").strip():
            ws.update_cell(row, 3, title)
    else:
        now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
        all_vals = ws.get_all_values()
        next_num = len(all_vals)
        ws.append_row([str(next_num), str(chat_id), title, "", "", "Noma'lum", now, mode, ""])


async def get_group_mode(chat_id: int) -> str:
    """Guruhning havola sozlamasini qaytaradi — keshdan, bo'lmasa Sheets'dan o'qiydi."""
    if chat_id in _mode_cache:
        return _mode_cache[chat_id]
    loop = asyncio.get_running_loop()
    mode = await loop.run_in_executor(None, _get_link_mode_sync, chat_id)
    mode = mode if mode in LINK_MODES else DEFAULT_MODE
    _mode_cache[chat_id] = mode
    return mode


# ─── 1) Bot statusi kuzatuvi (my_chat_member) ───────────────────────────

@router.my_chat_member()
async def on_bot_membership_change(update: ChatMemberUpdated) -> None:
    """
    Botning O'ZI biror guruhga qo'shilganda/admin qilinganda/
    olib tashlanganda ishga tushadi. Bu 'chat_member' (boshqa
    a'zolar haqida) EMAS — alohida update turi.
    """
    chat = update.chat
    if chat.type not in ("group", "supergroup"):
        return

    new_status = update.new_chat_member.status
    is_admin   = new_status in ("administrator", "creator")

    loop = asyncio.get_running_loop()
    with contextlib.suppress(Exception):
        await loop.run_in_executor(
            None, _upsert_group_sync, chat.id, chat.title or "Noma'lum", chat.type, is_admin
        )


# ─── 2) Kunlik qayta tekshiruv ───────────────────────────────────────────

async def daily_recheck_groups(bot: Bot) -> None:
    """
    Ro'yxatdagi har bir guruhda bot HALI HAM admin ekanligini
    qayta tekshiradi (ba'zan Telegram my_chat_member yubormay
    qolishi yoki bot o'chiq vaqtda status o'zgarishi mumkin).
    """
    loop  = asyncio.get_running_loop()
    rows  = await loop.run_in_executor(None, _load_all_groups_sync)
    updates: list[tuple[int, bool]] = []

    for r in rows:
        try:
            member   = await bot.get_chat_member(r["chat_id"], bot.id)
            is_admin = member.status in ("administrator", "creator")
        except Exception:
            is_admin = False   # guruhdan chiqarilgan/bloklangan/topilmadi — Faol emas
        updates.append((r["row_idx"], is_admin))

    if updates:
        await loop.run_in_executor(None, _apply_status_updates_sync, updates)
    logger.info(f"Guruhlar qayta tekshirildi: {len(updates)} ta")


def setup_control_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    main.py da chaqiriladi:
        from control import setup_control_scheduler
        group_scheduler = setup_control_scheduler(bot)
    Kun almashganda (00:10 — reklama_nazorati'ning 00:00 vazifasidan
    keyin, ular bir vaqtda Sheets'ga yozmasligi uchun) ishga tushadi.
    """
    sched = AsyncIOScheduler(timezone="Asia/Tashkent")
    sched.add_job(
        lambda: asyncio.ensure_future(daily_recheck_groups(bot)),
        CronTrigger(hour=0, minute=10, timezone="Asia/Tashkent"),
        id="group_daily_recheck", replace_existing=True,
    )
    sched.start()
    logger.info("Control scheduler ishga tushdi (har kuni 00:10)")
    return sched


# ─── 3) .apk fayllarni aniqlash va o'chirish (BARCHA guruhlarda) ────────

def _is_apk(message: Message) -> bool:
    doc = message.document
    if not doc:
        return False
    name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()
    return name.endswith(".apk") or mime == "application/vnd.android.package-archive"


def _safe_name(name: str) -> str:
    return (name or "Noma'lum").replace("<", "").replace(">", "").strip() or "Noma'lum"


def _mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{_safe_name(name)}</a>'


@router.message(F.chat.type.in_({"group", "supergroup"}), F.func(_is_apk))
async def check_apk(message: Message, bot: Bot) -> None:
    """
    .apk fayl aniqlansa — o'chiradi va Asosiy Adminga (ADMIN_ID)
    shaxsiy xabar yuboradi. Guruh siyosatidan qat'i nazar ishlaydi
    (jumladan asosiy Fortuna guruhida ham) — virusga qarshi chora
    har doim universal bo'lishi kerak.
    """
    doc      = message.document
    filename = doc.file_name or "(nomsiz fayl)"
    sender   = message.from_user
    chat     = message.chat
    sent_at  = message.date.astimezone(TZ).strftime("%d.%m.%Y %H:%M:%S")

    deleted = False
    with contextlib.suppress(Exception):
        await bot.delete_message(chat.id, message.message_id)
        deleted = True

    deleted_at = datetime.now(TZ).strftime("%d.%m.%Y %H:%M:%S")

    if sender:
        who = _mention(sender.id, sender.full_name)
        who += f" (@{sender.username})" if sender.username else ""
    else:
        who = "Noma'lum foydalanuvchi"

    group_ref = f"{chat.title}"
    if chat.username:
        group_ref += f" (@{chat.username})"

    status_line = (
        "🗑 <b>O'chirildi.</b>" if deleted else
        "⚠️ <b>O'chirib bo'lmadi</b> — botda ushbu guruhda admin huquqi yo'q."
    )

    text = (
        "🚨 <b>.APK FAYL ANIQLANDI!</b>\n\n"
        f"👥 <b>Guruh:</b> {group_ref}\n"
        f"🆔 <code>{chat.id}</code>\n\n"
        f"👤 <b>Kim yubordi:</b> {who}\n"
        f"📄 <b>Fayl nomi:</b> <code>{_safe_name(filename)}</code>\n"
        f"🕐 <b>Yuborilgan vaqt:</b> {sent_at}\n"
        f"🕐 <b>Aniqlangan/o'chirilgan vaqt:</b> {deleted_at}\n\n"
        f"{status_line}"
    )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(ADMIN_ID, text, parse_mode="HTML")

    logger.warning(f".apk aniqlandi: {filename} — guruh {chat.id} — yuboruvchi {sender.id if sender else '?'}")


# ─── 4a) Havola nazorati — ASOSIY Fortuna guruhi (qattiq, sozlanmaydi) ──
# Eski control.py xatti-harakati aynan shu yerda saqlab qolindi:
# oddiy a'zolarning havolasi HAR DOIM, jim, ogohlantirmasdan o'chiriladi.
# Faqat GROUP_ID ga tegishli — boshqa hech qanday guruhga ta'sir qilmaydi.

_LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.IGNORECASE)


def _has_link(message: Message) -> bool:
    entities = list(message.entities or []) + list(message.caption_entities or [])
    if any(e.type in ("url", "text_link") for e in entities):
        return True
    text = message.text or message.caption or ""
    return bool(_LINK_RE.search(text))


def _is_main_group_with_link(message: Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    if not GROUP_ID or message.chat.id != GROUP_ID:
        return False
    if message.from_user is None or message.from_user.is_bot:
        return False
    return _has_link(message)


@router.message(F.func(_is_main_group_with_link))
async def moderate_main_group_links(message: Message, bot: Bot) -> None:
    """Asosiy guruh — qattiq rejim: adminlar mustasno, qolganlarining havolasi jim o'chiriladi."""
    with contextlib.suppress(Exception):
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ("administrator", "creator"):
            return
    with contextlib.suppress(Exception):
        await message.delete()


# ─── 4b) Havola (reklama) nazorati — TASHQI guruhlar, sozlanadi ────────

def _is_foreign_group_with_link(message: Message) -> bool:
    """Asosiy Fortuna guruhi bundan mustasno — u yuqorida 4a bo'limida qattiq rejimda boshqariladi."""
    if message.chat.type not in ("group", "supergroup"):
        return False
    if GROUP_ID and message.chat.id == GROUP_ID:
        return False
    if message.from_user is None or message.from_user.is_bot:
        return False
    return _has_link(message)


@router.message(F.func(_is_foreign_group_with_link))
async def moderate_links(message: Message, bot: Bot) -> None:
    # Guruh adminlarining havolalarini o'chirmaymiz
    with contextlib.suppress(Exception):
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ("administrator", "creator"):
            return

    mode = await get_group_mode(message.chat.id)
    if mode == MODE_ALLOW:
        return

    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.warning(f"Havola o'chirishda xato ({message.chat.id}): {e}")
        return

    if mode == MODE_WARN:
        name = _safe_name(message.from_user.full_name)
        with contextlib.suppress(Exception):
            warn = await bot.send_message(
                message.chat.id,
                f"⚠️ {name}, ushbu guruhda havola (reklama) tarqatish taqiqlangan. Xabar o'chirildi.",
            )
            await asyncio.sleep(8)
            with contextlib.suppress(Exception):
                await warn.delete()


# ─── 5) Guruh adminlari uchun sozlama buyrug'i (faqat tashqi guruhlar) ──

def _mode_label(mode: str) -> str:
    return {
        MODE_WARN:   "🗑️ O'chirish + ogohlantirish",
        MODE_SILENT: "🔇 Jim o'chirish",
        MODE_ALLOW:  "✅ Ruxsat berish",
    }.get(mode, mode)


def _mode_kb(current: str) -> InlineKeyboardMarkup:
    rows = []
    for key in (MODE_WARN, MODE_SILENT, MODE_ALLOW):
        mark = "✅ " if key == current else "▫️ "
        rows.append([InlineKeyboardButton(text=f"{mark}{_mode_label(key)}", callback_data=f"lm_set_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("link_sozlama"))
async def cmd_link_sozlama(message: Message, bot: Bot) -> None:
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("ℹ️ Bu buyruq faqat guruhda ishlaydi.")
        return
    if GROUP_ID and message.chat.id == GROUP_ID:
        await message.answer(
            "ℹ️ Bu guruhda havola nazorati qattiq (sozlanmaydigan) rejimda ishlaydi."
        )
        return

    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in ("administrator", "creator"):
            await message.answer("⛔ Bu buyruq faqat guruh adminlari uchun.")
            return
    except Exception:
        return

    mode = await get_group_mode(message.chat.id)
    with contextlib.suppress(Exception):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _set_link_mode_sync, message.chat.id, mode, message.chat.title or "")

    await message.answer(
        "🔗 <b>Havola (reklama) nazorati sozlamasi</b>\n\n"
        "Guruhga tashlangan havolalar bilan bot nima qilsin?\n\n"
        f"Joriy holat: <b>{_mode_label(mode)}</b>",
        reply_markup=_mode_kb(mode), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("lm_set_"))
async def cb_link_mode_set(call: CallbackQuery, bot: Bot) -> None:
    mode = call.data[len("lm_set_"):]
    if mode not in LINK_MODES:
        return
    try:
        member = await bot.get_chat_member(call.message.chat.id, call.from_user.id)
        if member.status not in ("administrator", "creator"):
            await call.answer("⛔ Faqat adminlar uchun", show_alert=True)
            return
    except Exception:
        await call.answer("❌ Xato yuz berdi", show_alert=True)
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, _set_link_mode_sync, call.message.chat.id, mode, call.message.chat.title or ""
    )
    _mode_cache[call.message.chat.id] = mode

    await call.answer("✅ Saqlandi")
    with contextlib.suppress(Exception):
        await call.message.edit_text(
            "🔗 <b>Havola (reklama) nazorati sozlamasi</b>\n\n"
            f"Joriy holat: <b>{_mode_label(mode)}</b>",
            reply_markup=_mode_kb(mode), parse_mode="HTML",
        )


# ─── 6) Admin uchun ko'rish/qo'lda tekshirish buyruqlari ────────────────

@router.message(Command("guruhlar"))
async def cmd_guruhlar_list(message: Message) -> None:
    """Bot admin qilingan guruhlar ro'yxati (ADMIN_ID uchun)."""
    if message.from_user.id != ADMIN_ID:
        return
    loop  = asyncio.get_running_loop()
    rows  = await loop.run_in_executor(None, _load_all_groups_sync)
    if not rows:
        await message.answer("📭 Hozircha ro'yxatga olingan guruh yo'q.")
        return

    lines = ["👥 <b>Bot qo'shilgan guruhlar:</b>\n"]
    for r in rows[:40]:
        icon  = "🟢" if r["holati"] == "Faol" else "🔴"
        title = r["title"] or "Noma'lum"
        lines.append(f"{icon} {title} — <code>{r['chat_id']}</code>")
    if len(rows) > 40:
        qolgan = len(rows) - 40
        lines.append(f"\n… va yana {qolgan} ta (to'liq ro'yxat Sheets'da)")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("guruhlar_tekshir"))
async def cmd_guruhlar_tekshir(message: Message, bot: Bot) -> None:
    """Kunlik qayta tekshiruvni qo'lda ishga tushirish (ADMIN_ID uchun)."""
    if message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("🔍 Guruhlar tekshirilmoqda...")
    await daily_recheck_groups(bot)
    with contextlib.suppress(Exception):
        await msg.edit_text("✅ Tekshiruv yakunlandi. Natijalar Sheets'da yangilandi.\n/guruhlar orqali ko'ring.")
