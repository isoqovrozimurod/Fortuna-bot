"""
Reklama Nazorat Tizimi
- sub_adminlar varag'i ASOSIY MANBA (qo'lda kiritilganlar ham hisoblanadi)
- Har kuni yangi ustun: 01.03.2026, 02.03.2026 ...
- Cache xotira faqat tezlashtirish uchun
- 09:30 va 15:00 nazorat — Sheets dan o'qiydi
- Haftalik (dushanba) va oylik (1-chi) avtomatik statistika
"""

import os
import base64
import json
import asyncio
import logging
import contextlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

from aiogram import Router, Bot, F
from aiogram.types import (
    Message, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ===================== SOZLAMALAR =====================

router = Router()
logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")


def now_tz() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now_tz().strftime("%d.%m.%Y")


GROUP_ID       = int(os.getenv("GROUP_ID", "0"))
ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_LINK   = "https://t.me/FORTUNABIZNES_GALLAOROL"
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "sub_adminlar"
USER_SHEET     = "user"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
BASE_COLS = 8  # T/r, Telegram ID, Username, Ism, Familiya, Telefon, Sana, Holati

SCHEDULER: AsyncIOScheduler | None = None

# Cache: {user_id: {"date": "01.03.2026", "count": 2}}
_cache: dict[int, dict] = {}
_registering: set[int] = set()
_reg_lock = asyncio.Lock()


# ===================== SHEETS =====================

_gc: gspread.Client | None = None


def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def _ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SUBADMIN_SHEET)
    if not ws.row_values(1):
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
                       "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
    return ws


def _user_ws() -> gspread.Worksheet:
    return _get_gc().open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ===================== SANA USTUNI =====================

def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    headers = ws.row_values(1)
    if date_str in headers:
        return headers.index(date_str) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, date_str)
    return new_col


def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    for i, v in enumerate(ws.col_values(2), start=1):
        if str(v).strip() == str(user_id):
            return i
    return None


# ===================== SCREENSHOT YOZISH =====================

def _write_count_sync(user_id: int, count: int) -> None:
    try:
        sheet = _ws()
        date_col = _get_date_col(sheet, today_str())
        row = _find_row(sheet, user_id)
        if row:
            sheet.update_cell(row, date_col, count)
        else:
            logger.warning(f"Screenshot yozish: {user_id} sub_adminlar da topilmadi")
    except Exception as e:
        logger.error(f"Screenshot yozishda xato: {e}")


async def _write_count(user_id: int, count: int) -> None:
    await asyncio.get_event_loop().run_in_executor(
        None, _write_count_sync, user_id, count
    )


# ===================== SHEETS DAN O'QISH =====================

def _read_today_sync() -> dict[int, int]:
    """
    Bugungi ustundan barcha xodimlarning screenshot sonini qaytaradi.
    {user_id: count} — qo'lda kiritilganlar ham shu yerda.
    """
    try:
        sheet = _ws()
        headers = sheet.row_values(1)
        today = today_str()

        if today not in headers:
            return {}

        col_i = headers.index(today)  # 0-based
        result: dict[int, int] = {}

        for row in sheet.get_all_values()[1:]:
            if len(row) <= 1 or not str(row[1]).strip():
                continue
            holati = str(row[7]).strip() if len(row) > 7 else ""
            if holati == "Chiqib ketdi":
                continue
            try:
                uid = int(str(row[1]).strip())
            except ValueError:
                continue
            val = str(row[col_i]).strip() if col_i < len(row) else ""
            result[uid] = int(val) if val.isdigit() else 0

        return result
    except Exception as e:
        logger.error(f"Sheets o'qishda xato: {e}")
        return {}


async def _read_today() -> dict[int, int]:
    return await asyncio.get_event_loop().run_in_executor(None, _read_today_sync)


def _get_count(uid: int, sheet_counts: dict[int, int]) -> int:
    """Cache va Sheets dan maksimalini oladi."""
    from_cache = 0
    data = _cache.get(uid)
    if data and data.get("date") == today_str():
        from_cache = data.get("count", 0)
    from_sheet = sheet_counts.get(uid, 0)
    return max(from_cache, from_sheet)


# ===================== CACHE =====================

def _cache_set(user_id: int, count: int) -> None:
    _cache[user_id] = {"date": today_str(), "count": count}


def _cache_get(user_id: int) -> int:
    data = _cache.get(user_id)
    if data and data.get("date") == today_str():
        return data.get("count", 0)
    return 0


def increment_screenshot(user_id: int) -> int:
    new = _cache_get(user_id) + 1
    _cache_set(user_id, new)
    return new


# ===================== RO'YXATGA OLISH =====================

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    sheet = _ws()
    row_idx = _find_row(sheet, user_id)

    parts = (full_name or "").split(" ", 1)
    ism = parts[0]
    familiya = parts[1] if len(parts) > 1 else ""
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")

    if row_idx is not None:
        sheet.update_cell(row_idx, 3, uname)
        sheet.update_cell(row_idx, 4, ism)
        sheet.update_cell(row_idx, 5, familiya)
        cur_holat = str(sheet.cell(row_idx, 8).value or "").strip()
        if not cur_holat:
            sheet.update_cell(row_idx, 8, "Faol")
        return False

    all_vals = sheet.get_all_values()
    headers = all_vals[0] if all_vals else []
    valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
    tr = valid_count + 1

    row = [str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"]
    while len(row) < len(headers):
        row.append("")
    sheet.append_row(row, value_input_option="RAW")
    logger.info(f"Yangi sub_admin: {full_name} ({user_id})")
    return True


def _set_status_sync(user_id: int, status: str) -> None:
    sheet = _ws()
    row = _find_row(sheet, user_id)
    if row:
        sheet.update_cell(row, 8, status)


def _get_active_sync() -> list[dict]:
    result = []
    for r in _ws().get_all_records():
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        result.append({
            "id": tg_id,
            "name": f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum",
            "username": str(r.get("Username", "")),
        })
    return result


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    async with _reg_lock:
        if user_id in _registering:
            return False
        _registering.add(user_id)
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, _register_sync, user_id, full_name, username
        )
    finally:
        async with _reg_lock:
            _registering.discard(user_id)


async def set_status(user_id: int, status: str) -> None:
    await asyncio.get_event_loop().run_in_executor(None, _set_status_sync, user_id, status)


async def get_active() -> list[dict]:
    return await asyncio.get_event_loop().run_in_executor(None, _get_active_sync)


# ===================== CLEANUP =====================

def _cleanup_sync() -> None:
    sheet = _ws()
    all_rows = sheet.get_all_values()
    if len(all_rows) <= 1:
        return

    header_len = len(all_rows[0])
    seen: set[str] = set()
    valid: list[list] = []
    sana_now = now_tz().strftime("%Y-%m-%d %H:%M")

    for row in all_rows[1:]:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if not tg_id or tg_id in seen:
            continue
        seen.add(tg_id)
        r = list(row)
        while len(r) < header_len:
            r.append("")
        valid.append(r)

    if not valid:
        return

    for i, row in enumerate(valid, start=1):
        row[0] = str(i)
        if not str(row[7]).strip():
            row[7] = "Faol"
        if not str(row[6]).strip():
            row[6] = sana_now

    total = len(all_rows)
    count = len(valid)
    last = _col_letter(header_len)

    sheet.update(f"A2:{last}{count + 1}", valid, value_input_option="RAW")
    if total > count + 1:
        sheet.update(
            f"A{count + 2}:{last}{total}",
            [[""] * header_len] * (total - count - 1),
            value_input_option="RAW"
        )


async def cleanup() -> None:
    await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)


# ===================== GURUH HANDLERLARI =====================

def _is_group(message: Message) -> bool:
    return (
        message.from_user is not None
        and not message.from_user.is_bot
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


def _is_admin(message: Message) -> bool:
    return _is_group(message) and message.from_user.id == ADMIN_ID


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_join(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await register_user(u.id, u.full_name or "", u.username or "")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_leave(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await set_status(u.id, "Chiqib ketdi")


@router.message(F.photo)
async def on_photo(message: Message):
    if not _is_group(message):
        return
    u = message.from_user

    with contextlib.suppress(Exception):
        await register_user(u.id, u.full_name or "", u.username or "")

    count = increment_screenshot(u.id)
    asyncio.ensure_future(_write_count(u.id, count))

    emoji = "📸" if count == 1 else "✅" if count == 2 else "🎉"
    note = (
        "Birinchi screenshot!" if count == 1
        else "Kunlik reja bajarildi!" if count == 2
        else f"{count}-screenshot!"
    )
    with contextlib.suppress(Exception):
        await message.reply(
            f"{emoji} <b>{u.full_name}</b>\n"
            f"📊 Bugun: <b>{count}/2</b> — {note}",
            parse_mode="HTML"
        )
    logger.info(f"Screenshot: {u.full_name} ({u.id}) — bugun: {count}")


@router.message(F.document)
async def on_document(message: Message):
    if not _is_group(message):
        return
    doc = message.document
    if doc and doc.mime_type and doc.mime_type.startswith("image/"):
        await on_photo(message)
    else:
        with contextlib.suppress(Exception):
            await register_user(
                message.from_user.id,
                message.from_user.full_name or "",
                message.from_user.username or ""
            )


@router.message(~F.photo, ~F.document)
async def on_text(message: Message):
    if not _is_group(message):
        return
    with contextlib.suppress(Exception):
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or ""
        )


# ===================== QO'LDA RO'YXAT =====================

@router.message(Command("start_register"))
async def cmd_start_register(message: Message):
    if not _is_admin(message):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ MEN SHU YERDAMAN", callback_data="reg_me")]
    ])
    await message.bot.send_message(
        GROUP_ID,
        "📢 <b>DIQQAT!</b>\n\nBarcha xodimlar quyidagi tugmani bossin.\n"
        "Bo'lmasa hisobotda ko'rinmaysiz.\n\n👇 <b>Bosing:</b>",
        reply_markup=kb, parse_mode="HTML"
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "reg_me")
async def cb_reg_me(callback: CallbackQuery):
    u = callback.from_user
    try:
        is_new = await register_user(u.id, u.full_name or "", u.username or "")
        await callback.answer(
            "✅ Ro'yxatga oldingiz!" if is_new else "✅ Ma'lumotlar yangilandi!",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Ro'yxatdan o'tkazishda xato: {e}")
        await callback.answer("❌ Xato. Qayta urinib ko'ring.", show_alert=True)


# ===================== MENTION =====================

def _mention(uid: str, name: str) -> str:
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={uid}">{safe}</a>'


async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            break
        cut = text.rfind("\n", 0, limit) or limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML")
        text = text[cut:]


# ===================== NAZORAT =====================

async def check_screenshots(bot: Bot) -> None:
    """
    Sheets dan bugungi ma'lumotlarni o'qib tekshiradi.
    Qo'lda kiritilgan sonlar ham hisoblanadi.
    """
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan!")
        return

    try:
        active = await get_active()
    except Exception as e:
        logger.error(f"Faol xodimlar olishda xato: {e}")
        return

    if not active:
        logger.warning("sub_adminlar da faol xodim yo'q!")
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ sub_adminlar da faol xodim yo'q!\n/start_register yuboring."
                )
        return

    # Sheets dan bugungi sonlarni o'qiymiz
    sheet_counts = await _read_today()
    logger.info(f"Sheets bugungi sonlar: {sheet_counts}")

    debtors, done_list = [], []
    for u in active:
        try:
            uid = int(u["id"])
        except (ValueError, TypeError):
            continue
        cnt = _get_count(uid, sheet_counts)
        if cnt >= 2:
            done_list.append({**u, "count": cnt})
        else:
            debtors.append({**u, "count": cnt})

    total = len(active)
    completed = len(done_list)
    time_str = now_tz().strftime("%H:%M")
    h, m = now_tz().hour, now_tz().minute
    next_check = (
        "Bugun 09:30" if h < 9 or (h == 9 and m < 30)
        else "Bugun 15:00" if h < 15
        else "Ertaga 09:30"
    )
    percent = int(completed / total * 100) if total else 0

    if debtors:
        done_text = ""
        if done_list:
            done_text = "\n✅ <b>Bajarganlar:</b>\n"
            for u in done_list:
                done_text += f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2\n"

        debtor_text = "\n❌ <b>BAJARMAGAN XODIMLAR:</b>\n"
        for i, u in enumerate(debtors, 1):
            cnt = u["count"]
            note = "bitta yetishmayapti ⚠️" if cnt == 1 else "hali birorta ham yoq 🚫"
            debtor_text += f"\n{i}. {_mention(u['id'], u['name'])}\n   📸 {cnt}/2 — {note}\n"

        text = (
            f"🚨 <b>NAZORAT — {time_str}</b>\n"
            f"📅 {now_tz().strftime('%d.%m.%Y')}\n\n"
            f"👥 Faol: {total} | ✅ {completed} | ❌ {len(debtors)}\n"
            f"📊 {percent}%\n"
            + done_text + debtor_text
            + f"\n➖➖➖➖➖➖➖➖➖➖\n"
            f"❗ <b>Reklama tarqatib screenshot yuborsin!</b>\n"
            f"📌 {CHANNEL_LINK}\n"
            f"⏰ Keyingi: {next_check}"
        )
        try:
            await _send_long(bot, GROUP_ID, text)
        except TelegramForbiddenError:
            logger.error("Guruhda yozish taqiqlangan!")
        except Exception as e:
            logger.error(f"Hisobot yuborishda xato: {e}")
    else:
        done_text = "\n".join(
            f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2"
            for u in done_list
        )
        with contextlib.suppress(Exception):
            await bot.send_message(
                GROUP_ID,
                f"🏆 <b>AJOYIB! — {time_str}</b>\n\n"
                "✅ Barcha xodimlar rejani bajardi!\n\n"
                f"{done_text}\n\n👏 Rahmat!",
                parse_mode="HTML"
            )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin — {time_str}</b>\n"
                f"👥 {total} | ✅ {completed} | ❌ {len(debtors)} | 📈 {percent}%",
                parse_mode="HTML"
            )


# ===================== STATISTIKA =====================

def _stats_sync(days: int) -> list[dict]:
    sheet = _ws()
    headers = sheet.row_values(1)
    all_rows = sheet.get_all_values()

    cutoff = (now_tz() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    date_cols: dict[str, int] = {}
    for i, h in enumerate(headers[BASE_COLS:], start=BASE_COLS):
        try:
            dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
            if dt >= cutoff:
                date_cols[h] = i
        except ValueError:
            pass

    result = []
    for row in all_rows[1:]:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if not tg_id:
            continue
        holati = str(row[7]).strip() if len(row) > 7 else ""
        if holati == "Chiqib ketdi":
            continue

        ism = str(row[3]).strip() if len(row) > 3 else ""
        fam = str(row[4]).strip() if len(row) > 4 else ""
        name = f"{ism} {fam}".strip() or "Noma'lum"

        total = 0
        for h, col_i in date_cols.items():
            val = str(row[col_i]).strip() if col_i < len(row) else ""
            total += int(val) if val.isdigit() else 0

        result.append({"id": tg_id, "name": name, "total": total})

    result.sort(key=lambda x: x["total"], reverse=True)
    return result


async def get_stats(days: int) -> list[dict]:
    return await asyncio.get_event_loop().run_in_executor(None, _stats_sync, days)


def _stat_text(stats: list[dict], label: str, days: int) -> str:
    if not stats:
        return f"📊 <b>{label} statistika</b>\n\nMa'lumot yo'q."

    total_all = sum(u["total"] for u in stats)
    d_start = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end = now_tz().strftime("%d.%m.%Y")

    lines = []
    for i, u in enumerate(stats, 1):
        filled = min(u["total"], 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)
