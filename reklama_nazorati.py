"""
Reklama Nazorat Tizimi — Bot qismi
===================================
Apps Script nima qiladi (bot ga kerak EMAS):
  - 09:30 / 15:00 nazorat xabarlari
  - Haftalik / oylik statistika xabarlari
  - Kunlik yangi sana ustunini yaratish

Bot nima qiladi (bu fayl):
  - Guruhdan screenshot/rasm → Sheets ga raqam yozish
  - chat_member: qo'shilish / chiqish
  - /start_register, /reklama_tekshir, /reklama_stat, /reklama_users, /sync_subadmin
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

# ===================== SOZLAMALAR =====================

router = Router()
logger = logging.getLogger(__name__)
TZ     = ZoneInfo("Asia/Tashkent")


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
BASE_COLS = 8

# APScheduler OLIB TASHLANDI — Apps Script buni qiladi
_gc: gspread.Client | None = None
_registering: set[int] = set()
_reg_lock = asyncio.Lock()


# ===================== SHEETS =====================

def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64  = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


def _ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(SUBADMIN_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUBADMIN_SHEET, rows="100", cols="50")
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
                       "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
        return ws


def _user_ws() -> gspread.Worksheet:
    return _get_gc().open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)


def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    for i, v in enumerate(ws.col_values(2), start=1):
        if str(v).strip() == str(user_id):
            return i
    return None


def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    headers = ws.row_values(1)
    if date_str in headers:
        return headers.index(date_str) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, date_str)
    return new_col


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ===================== LOCAL KESH =====================

_local_counts: dict[int, dict] = {}


def _local_get(user_id: int) -> int:
    data = _local_counts.get(user_id)
    if data and data.get("date") == today_str():
        return data.get("count", 0)
    return 0


def _local_set(user_id: int, count: int) -> None:
    _local_counts[user_id] = {"date": today_str(), "count": count}


def _write_to_sheet_sync(user_id: int, count: int) -> None:
    try:
        sheet    = _ws()
        date_col = _get_date_col(sheet, today_str())
        row      = _find_row(sheet, user_id)
        if row:
            sheet.update_cell(row, date_col, count)
    except Exception as e:
        logger.error(f"Sheets yozishda xato ({user_id}): {e}")


# ===================== RO'YXATGA OLISH =====================

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    sheet = _ws()
    if _find_row(sheet, user_id):
        return False
    parts       = (full_name or "").split(" ", 1)
    ism         = parts[0]
    familiya    = parts[1] if len(parts) > 1 else ""
    uname       = f"@{username}" if username else ""
    sana        = now_tz().strftime("%Y-%m-%d %H:%M")
    all_vals    = sheet.get_all_values()
    headers     = all_vals[0] if all_vals else []
    valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
    tr  = valid_count + 1
    row = [str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"]
    while len(row) < len(headers):
        row.append("")
    sheet.append_row(row, value_input_option="RAW")
    logger.info(f"Yangi sub_admin: {full_name} ({user_id})")
    return True


def _set_status_sync(user_id: int, status: str) -> None:
    sheet = _ws()
    row   = _find_row(sheet, user_id)
    if row:
        sheet.update_cell(row, 8, status)


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    async with _reg_lock:
        if user_id in _registering:
            return False
        _registering.add(user_id)
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _register_sync, user_id, full_name, username)
    finally:
        async with _reg_lock:
            _registering.discard(user_id)


async def set_status(user_id: int, status: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _set_status_sync, user_id, status)


# ===================== GURUH HANDLERLARI =====================

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


@router.message(F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0), F.photo | F.document)
async def handle_media(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        with contextlib.suppress(Exception):
            await register_user(
                message.from_user.id,
                message.from_user.full_name or "",
                message.from_user.username or "",
            )
        return

    u = message.from_user
    with contextlib.suppress(Exception):
        await register_user(u.id, u.full_name or "", u.username or "")

    count = _local_get(u.id) + 1
    _local_set(u.id, count)

    asyncio.create_task(
        asyncio.get_running_loop().run_in_executor(None, _write_to_sheet_sync, u.id, count)
    )

    emoji = "📸" if count == 1 else "✅" if count == 2 else "🔥"
    text  = f"{emoji} <b>{u.full_name}</b>\n📊 Bugun: <b>{count}/2</b>"
    if count == 2:
        text += "\n\n🌟 Kunlik reja bajarildi!"
    elif count > 2:
        text += f"\n\n{count}-screenshot — zo'r!"
    with contextlib.suppress(Exception):
        await message.reply(text, parse_mode="HTML")


@router.message(F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0), ~F.photo, ~F.document)
async def handle_text(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    with contextlib.suppress(Exception):
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or "",
        )


# ===================== QO'LDA RO'YXAT =====================

@router.message(Command("start_register"))
async def cmd_start_register(message: Message):
    if not (message.chat.id == GROUP_ID and message.from_user
            and message.from_user.id == ADMIN_ID):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ RO'YXATDAN O'TISH", callback_data="reg_me")]
    ])
    await message.bot.send_message(
        GROUP_ID,
        "📢 <b>DIQQAT!</b>\n\nBarcha xodimlar quyidagi tugmani bossin.\n\n👇 <b>Bosing:</b>",
        reply_markup=kb, parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "reg_me")
async def cb_reg_me(callback: CallbackQuery):
    u = callback.from_user
    try:
        is_new = await register_user(u.id, u.full_name or "", u.username or "")
        await callback.answer(
            "✅ Ro'yxatga olindingiz!" if is_new else "✅ Allaqachon bazadasiz.",
            show_alert=True,
        )
    except Exception:
        await callback.answer("❌ Xato. Qayta urinib ko'ring.", show_alert=True)


# ===================== YORDAMCHI =====================

def _mention(uid: str, name: str) -> str:
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={uid}">{safe}</a>'


async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            break
        cut  = text.rfind("\n", 0, limit) or limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML")
        text = text[cut:]


# ===================== QOLDA NAZORAT =====================

async def check_screenshots(bot: Bot) -> None:
    if GROUP_ID == 0:
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _ws().get_all_records())
    except Exception as e:
        logger.error(f"Sheets o'qishda xato: {e}")
        return

    if not data:
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(ADMIN_ID, "⚠️ sub_adminlar da hech kim yo'q!\n/start_register yuboring.")
        return

    today     = today_str()
    time_str  = now_tz().strftime("%H:%M")
    debtors   = []
    done_list = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw    = r.get(today, 0)
        from_sheet = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            from_local = _local_get(int(tg_id))
        except ValueError:
            from_local = 0
        cnt  = max(from_sheet, from_local)
        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        (done_list if cnt >= 2 else debtors).append({"id": tg_id, "name": name, "count": cnt})

    total     = len(done_list) + len(debtors)
    completed = len(done_list)
    percent   = int(completed / total * 100) if total else 0

    if debtors:
        done_text = ""
        if done_list:
            done_text  = "\n✅ <b>Bajarganlar:</b>\n"
            done_text += "".join(f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2\n" for u in done_list)
        debtor_text = "\n❌ <b>BAJARMAGAN XODIMLAR:</b>\n"
        for i, u in enumerate(debtors, 1):
            note = "bitta yetishmayapti ⚠️" if u["count"] == 1 else "hali birorta ham yo'q 🚫"
            debtor_text += f"\n{i}. {_mention(u['id'], u['name'])}\n   📸 {u['count']}/2 — {note}\n"
        text = (
            f"🚨 <b>NAZORAT — {time_str}</b>\n📅 {today}\n\n"
            f"👥 Faol: {total} | ✅ {completed} | ❌ {len(debtors)}\n📊 {percent}%\n"
            + done_text + debtor_text
            + f"\n➖➖➖➖➖➖➖➖➖➖\n"
            f"❗ <b>Reklama tarqatib screenshot yuborsin!</b>\n📌 {CHANNEL_LINK}"
        )
        try:
            await _send_long(bot, GROUP_ID, text)
        except TelegramForbiddenError:
            logger.error("Guruhda yozish taqiqlangan!")
    else:
        done_text = "\n".join(
            f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2" for u in done_list
        )
        with contextlib.suppress(Exception):
            await bot.send_message(
                GROUP_ID,
                f"🏆 <b>AJOYIB! — {time_str}</b>\n\n✅ Barcha rejani bajardi!\n\n{done_text}\n\n👏 Rahmat!",
                parse_mode="HTML",
            )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin — {time_str}</b>\n👥 {total} | ✅ {completed} | ❌ {len(debtors)} | 📈 {percent}%",
                parse_mode="HTML",
            )


# ===================== STATISTIKA =====================

def _stats_sync(days: int) -> list[dict]:
    sheet       = _ws()
    headers     = sheet.row_values(1)
    data        = sheet.get_all_records()
    cutoff      = (now_tz() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    valid_dates = []
    for h in headers[BASE_COLS:]:
        try:
            dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
            if dt >= cutoff:
                valid_dates.append(h)
        except ValueError:
            pass
    result = []
    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        name  = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        total = sum(int(r[d]) if str(r.get(d, 0)).strip().isdigit() else 0 for d in valid_dates)
        result.append({"id": tg_id, "name": name, "total": total})
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


async def get_stats(days: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _stats_sync, days)


def _stat_text(stats: list[dict], label: str, days: int) -> str:
    if not stats:
        return f"📊 <b>{label} statistika</b>\n\nMa'lumot yo'q."
    total_all = sum(u["total"] for u in stats)
    d_start   = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end     = now_tz().strftime("%d.%m.%Y")
    lines = []
    for i, u in enumerate(stats, 1):
        filled = min(u["total"], 10)
        bar    = "🟩" * filled + "⬜" * (10 - filled)
        lines.append(f"{i}. {_mention(u['id'], u['name'])}\n   {bar} <b>{u['total']}</b> ta")
    return (
        f"📊 <b>{label} statistika</b>\n📅 {d_start} — {d_end}\n\n"
        f"👥 {len(stats)} xodim | 📸 Jami: {total_all} ta\n➖➖➖➖➖➖➖➖➖➖\n\n"
        + "\n\n".join(lines)
    )


def _stat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Kunlik",   callback_data="stat_daily"),
            InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
            InlineKeyboardButton(text="🗓 Oylik",    callback_data="stat_monthly"),
        ],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="stat_close")],
    ])


@router.message(Command("reklama_stat"))
async def cmd_stat(message: Message, bot: Bot):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    await bot.send_message(
        ADMIN_ID,
        "📊 <b>Reklama statistikasi</b>\n\nQaysi davrni ko'rmoqchisiz?",
        reply_markup=_stat_kb(), parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data.in_({"stat_daily", "stat_weekly", "stat_monthly", "stat_close"}))
async def cb_stat(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    if call.data == "stat_close":
        with contextlib.suppress(Exception):
            await call.message.delete()
        return
    await call.answer("⏳ Hisoblanmoqda...")
    days_map = {"stat_daily": (1, "Kunlik"), "stat_weekly": (7, "Haftalik"), "stat_monthly": (30, "Oylik")}
    days, label = days_map[call.data]
    try:
        stats = await get_stats(days)
        await call.message.edit_text(_stat_text(stats, label, days), reply_markup=_stat_kb(), parse_mode="HTML")
    except Exception as e:
        with contextlib.suppress(Exception):
            await call.message.edit_text(f"❌ Xato: {e}", reply_markup=_stat_kb())


# ===================== ADMIN BUYRUQLARI =====================

def _is_admin(message: Message) -> bool:
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


@router.message(Command("reklama_tekshir"))
async def cmd_check(message: Message, bot: Bot):
    if not _is_admin(message):
        return
    msg = await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    with contextlib.suppress(Exception):
        await msg.delete()
        await message.delete()


@router.message(Command("reklama_users"))
async def cmd_users(message: Message):
    if not _is_admin(message):
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _ws().get_all_records())
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return
    today = today_str()
    text  = "👥 <b>Faol xodimlar:</b>\n\n"
    count = 0
    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw = r.get(today, 0)
        cnt     = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        name    = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        emoji   = "✅" if cnt >= 2 else "⚠️" if cnt == 1 else "❌"
        text   += f"{emoji} <b>{name}</b> — 📸 {cnt}/2\n"
        count  += 1
        if count >= 30:
            break
    if count == 0:
        await message.answer("❌ Faol xodimlar yo'q")
        return
    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(60)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("sync_subadmin"))
async def cmd_sync(message: Message, bot: Bot):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    msg = await bot.send_message(ADMIN_ID, "⏳ Sinxronlanmoqda...")
    try:
        def _sync() -> int:
            subws    = _ws()
            usrws    = _user_ws()
            user_map = {
                str(r[1]).strip(): r
                for r in usrws.get_all_values()[1:]
                if len(r) > 1 and str(r[1]).strip()
            }
            updated = 0
            for i, row in enumerate(subws.get_all_values()[1:], start=2):
                tid = str(row[1]).strip() if len(row) > 1 else ""
                if not tid or tid not in user_map:
                    continue
                u       = user_map[tid]
                changed = False
                for ui, sc in [(2, 3), (3, 4), (4, 5), (5, 6)]:
                    cur = str(row[sc - 1]).strip() if len(row) > sc - 1 else ""
                    src = str(u[ui]).strip()        if len(u)   > ui      else ""
                    if not cur and src:
                        subws.update_cell(i, sc, src)
                        changed = True
                if changed:
                    updated += 1
            return updated
        loop    = asyncio.get_running_loop()
        updated = await loop.run_in_executor(None, _sync)
        await msg.edit_text(f"✅ Sinxronlash yakunlandi! {updated} ta qator yangilandi.")
    except Exception as e:
        await msg.edit_text(f"❌ Xato: {e}")
    with contextlib.suppress(Exception):
        await message.delete()


@router.message(Command("reklama_help"))
async def cmd_help(message: Message):
    if not _is_admin(message):
        return
    sent = await message.answer(
        "📋 <b>Reklama Nazorat — Yordam</b>\n\n"
        "<b>Xodimlar:</b>\n"
        "• Guruhga rasm yuboring — bot hisoblaydi\n"
        "• Har kuni kamida 2 ta rasm kerak\n\n"
        "<b>Admin buyruqlari (bot):</b>\n"
        "/start_register — Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir — Qo'lda nazorat\n"
        "/reklama_stat — Statistika\n"
        "/reklama_users — Faol xodimlar\n"
        "/sync_subadmin — User → sub_admin sinxronlash\n\n"
        "<b>Avtomatik (Apps Script):</b>\n"
        "⏰ 09:30, 15:00 — Nazorat xabari\n"
        "📆 Har dushanba 09:00 — Haftalik stat\n"
        "🗓 Har oyning 1-si 09:00 — Oylik stat\n"
        "📅 Har kuni 08:00 — Yangi kun ustuni",
        parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(40)
    with contextlib.suppress(Exception):
        await sent.delete()
