"""
Reklama Nazorat Tizimi - TO'LIQ ISHLAYDIGAN VERSIYA
- Har kuni 00:05 da yangi sana ustuni avto qo'shiladi
- Screenshot hisobi 100% Google Sheetsda
- Kunlik/Haftalik/Oylik statistika
- 09:30 va 15:00 nazorat
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
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# =================== SOZLAMALAR ===================
router = Router()
logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")

def now_tz() -> datetime:
    return datetime.now(TZ)

def today_str() -> str:
    return now_tz().strftime("%d.%m.%Y")

GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "sub_adminlar"
USER_SHEET = "user"
BASE_COLS = 8

_gc: gspread.Client | None = None
_register_lock = asyncio.Lock()

# =================== GOOGLE SHEETS ===================
def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        _gc = gspread.authorize(creds)
    return _gc

def _get_ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SUBADMIN_SHEET)
    if not ws.row_values(1):
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism", "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
    return ws

def _get_user_ws() -> gspread.Worksheet:
    return _get_gc().open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)

# =================== SANA USTUNI AVTO ===================
def _ensure_today_column_sync() -> int:
    ws = _get_ws()
    headers = ws.row_values(1)
    today = today_str()
    if today in headers:
        return headers.index(today) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, today)
    logger.info(f"✅ Yangi sana ustuni qo'shildi: {today}")
    return new_col

# =================== SCREENSHOT HISOBI ===================
def _get_screenshot_count_sync(user_id: int) -> int:
    ws = _get_ws()
    today = today_str()
    headers = ws.row_values(1)
    try:
        col = headers.index(today) + 1
    except ValueError:
        return 0
    ids = ws.col_values(2)
    for i, val in enumerate(ids, start=1):
        if str(val).strip() == str(user_id):
            val = ws.cell(i, col).value
            return int(val) if str(val).strip().isdigit() else 0
    return 0

def _save_screenshot_sync(user_id: int, count: int) -> None:
    ws = _get_ws()
    col = _ensure_today_column_sync()
    ids = ws.col_values(2)
    for i, val in enumerate(ids, start=1):
        if str(val).strip() == str(user_id):
            ws.update_cell(i, col, count)
            logger.info(f"✅ Screenshot saqlandi: UserID={user_id} Count={count} Sana={today_str()}")
            return

async def increment_and_save_screenshot(user_id: int) -> int:
    async with _register_lock:
        count = _get_screenshot_count_sync(user_id) + 1
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _save_screenshot_sync, user_id, count)
    return count

# =================== STATISTIKA ===================
def _get_stats_sync(days: int) -> list[dict]:
    ws = _get_ws()
    headers = ws.row_values(1)
    all_rows = ws.get_all_values()
    date_cols = {}
    cutoff = now_tz() - timedelta(days=days - 1)
    for i, h in enumerate(headers[BASE_COLS:], start=BASE_COLS):
        try:
            dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
            if dt >= cutoff.replace(hour=0, minute=0, second=0):
                date_cols[h] = i
        except ValueError:
            pass
    result = []
    for row in all_rows[1:]:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if not tg_id:
            continue
        if len(row) > 7 and str(row[7]).strip() != "Faol":
            continue
        ism = str(row[3]).strip() if len(row) > 3 else ""
        familiya = str(row[4]).strip() if len(row) > 4 else ""
        name = f"{ism} {familiya}".strip() or "Noma'lum"
        total = 0
        for header, col_i in date_cols.items():
            cnt = int(row[col_i]) if col_i < len(row) and str(row[col_i]).strip().isdigit() else 0
            total += cnt
        result.append({"id": tg_id, "name": name, "total": total})
    result.sort(key=lambda x: x["total"], reverse=True)
    return result

async def get_stats(days: int) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_stats_sync, days)

# =================== FOYDALANUVCHI OPERATSIYALARI ===================
def _find_row_sync(user_id: int) -> int | None:
    ws = _get_ws()
    for i, val in enumerate(ws.col_values(2), start=1):
        if str(val).strip() == str(user_id):
            return i
    return None

def _cleanup_sync(ws: gspread.Worksheet) -> None:
    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return
    seen_ids: set[str] = set()
    valid_rows = []
    for row in all_rows[1:]:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if tg_id and tg_id not in seen_ids:
            seen_ids.add(tg_id)
            valid_rows.append(list(row))
    if not valid_rows:
        return
    header_len = len(all_rows[0])
    sana_now = now_tz().strftime("%Y-%m-%d %H:%M")
    for i, row in enumerate(valid_rows, start=1):
        while len(row) < header_len:
            row.append("")
        row[0] = str(i)
        if not str(row[7]).strip():
            row[7] = "Faol"
        if not str(row[6]).strip():
            row[6] = sana_now
    count = len(valid_rows)
    ws.update(f"A2:{chr(64 + header_len)}{count + 1}", valid_rows, value_input_option="RAW")
    total_existing = len(all_rows)
    if total_existing > count + 1:
        ws.update(f"A{count + 2}:{chr(64 + header_len)}{total_existing}", [[""] * header_len] * (total_existing - count - 1), value_input_option="RAW")

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    ws = _get_ws()
    row_idx = _find_row_sync(user_id)
    parts = (full_name or "").split(" ", 1)
    ism = parts[0]
    familiya = parts[1] if len(parts) > 1 else ""
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")
    if row_idx is not None:
        ws.update_cell(row_idx, 3, uname)
        ws.update_cell(row_idx, 4, ism)
        ws.update_cell(row_idx, 5, familiya)
        ws.update_cell(row_idx, 8, "Faol")
        return False
    _cleanup_sync(ws)
    all_vals = ws.get_all_values()
    valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
    tr = valid_count + 1
    ws.append_row([str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"], value_input_option="RAW")
    return True

def _set_status_sync(user_id: int, status: str) -> None:
    row_idx = _find_row_sync(user_id)
    if row_idx:
        _get_ws().update_cell(row_idx, 8, status)

def _get_all_active_sync() -> list[dict]:
    ws = _get_ws()
    result = []
    for r in ws.get_all_records():
        tg_id = str(r.get("Telegram ID", "")).strip()
        if tg_id and str(r.get("Holati", "")).strip() == "Faol":
            result.append({
                "id": tg_id,
                "name": f"{r.get('Ism','')} {r.get('Familiya','')}".strip(),
                "username": str(r.get("Username", "")),
            })
    return result

async def register_user(user_id: int, full_name: str, username: str) -> bool:
    async with _register_lock:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _register_sync, user_id, full_name, username)

async def set_status(user_id: int, status: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _set_status_sync, user_id, status)

async def get_all_active() -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_all_active_sync)

# =================== NAZORAT HISOBOTI ===================
def _mention(user_id: str, name: str) -> str:
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={user_id}">{safe}</a>'

async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            break
        cut = text.rfind("\n", 0, limit) or limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML")
        text = text[cut:]

async def check_screenshots(bot: Bot) -> None:
    if GROUP_ID == 0:
        return
    active = await get_all_active()
    if not active:
        return
    debtors, done_list = [], []
    for u in active:
        uid = int(u["id"])
        cnt = _get_screenshot_count_sync(uid)
        if cnt >= 2:
            done_list.append(u)
        else:
            debtors.append({**u, "count": cnt})
    total = len(active)
    completed = len(done_list)
    time_str = now_tz().strftime("%H:%M")
    percent = int(completed / total * 100) if total else 0
    if debtors:
        debtor_lines = "\n❌ <b>BAJARMAGAN XODIMLAR:</b>\n"
        for i, u in enumerate(debtors, 1):
            cnt = u["count"]
            debtor_lines += f"{i}. {_mention(u['id'], u['name'])} — {cnt}/2\n"
        text = (f"🚨 <b>NAZORAT HISOBOTI — {time_str}</b>\n"
                f"👥 Jami: {total} ta\n✅ Bajardi: {completed} ta\n❌ Bajarmadi: {len(debtors)} ta\n📊 {percent}%\n\n"
                f"{debtor_lines}\n❗ Zudlik bilan screenshot yuboring!")
        await _send_long(bot, GROUP_ID, text)
    else:
        await bot.send_message(GROUP_ID, f"🏆 <b>AJOYIB! — {time_str}</b>\n✅ BARCHA XODIMLAR 2/2 BAJARDI!", parse_mode="HTML")

# =================== SCHEDULER ===================
def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="Asia/Tashkent")
    s.add_job(_ensure_today_column_sync, CronTrigger(hour=0, minute=5), id="new_date_col")
    s.add_job(check_screenshots, CronTrigger(hour=9, minute=30), args=[bot])
    s.add_job(check_screenshots, CronTrigger(hour=15, minute=0), args=[bot])
    s.start()
    logger.info("✅ Scheduler ishga tushdi: 00:05 (yangi ustun) + 09:30/15:00 nazorat")
    return s

# =================== HANDLERLAR ===================
@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID or event.new_chat_member.user.is_bot:
        return
    await register_user(event.new_chat_member.user.id, event.new_chat_member.user.full_name or "", event.new_chat_member.user.username or "")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID or event.new_chat_member.user.is_bot:
        return
    await set_status(event.new_chat_member.user.id, "Chiqib ketdi")

@router.message(F.chat.id == GROUP_ID, F.photo | F.document)
async def handle_media(message: Message):
    if not message.from_user:
        return
    user = message.from_user
    await register_user(user.id, user.full_name or "", user.username or "")
    count = await increment_and_save_screenshot(user.id)
    emoji = "📸" if count == 1 else "✅" if count == 2 else "🎉"
    status = "Birinchi screenshot!" if count == 1 else "Kunlik reja bajarildi!" if count == 2 else f"{count}-screenshot"
    await message.reply(
        f"{emoji} <b>Qabul qilindi!</b>\n👤 {user.full_name}\n📊 Bugungi: <b>{count}/2</b>\n💬 {status}",
        parse_mode="HTML"
    )

# =================== ADMIN BUYRUQLARI ===================
@router.message(Command("start_register"))
async def start_registration_process(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ MEN SHU YERDAMAN", callback_data="register_me")]])
    await message.bot.send_message(GROUP_ID, "📢 <b>DIQQAT, GURUH A'ZOLARI!</b>\n\nBarcha xodimlar quyidagi tugmani bosishi SHART!", reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    user = callback.from_user
    is_new = await register_user(user.id, user.full_name or "", user.username or "")
    await callback.answer("✅ Ro'yxatga olindingiz!" if is_new else "✅ Ma'lumotlar yangilandi!", show_alert=True)

@router.message(Command("cleanup_users"))
async def cleanup_users_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("🧹 Tozalanmoqda...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _cleanup_sync, _get_ws())
    await msg.edit_text("✅ Tozalash yakunlandi!\n• Bo'sh qatorlar o'chirildi\n• Dublikatlar o'chirildi\n• T/r tartiblandi")

@router.message(Command("reklama_stat"))
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Kunlik", callback_data="stat_daily"),
         InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
         InlineKeyboardButton(text="🗓 Oylik", callback_data="stat_monthly")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="stat_close")]
    ])
    await message.bot.send_message(ADMIN_ID, "📊 <b>Reklama statistikasi</b>\nQaysi davrni ko'rmoqchisiz?", reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(F.data.in_({"stat_daily", "stat_weekly", "stat_monthly", "stat_close"}))
async def stat_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    if call.data == "stat_close":
        await call.message.delete()
        return
    await call.answer("⏳ Hisoblanmoqda...")
    days = 1 if call.data == "stat_daily" else 7 if call.data == "stat_weekly" else 30
    name = "Kunlik" if call.data == "stat_daily" else "Haftalik" if call.data == "stat_weekly" else "Oylik"
    stats = await get_stats(days)
    if not stats:
        text = f"📊 <b>{name} statistika</b>\n\nMa'lumot yo'q."
    else:
        total_screenshots = sum(u["total"] for u in stats)
        lines = [f"{i}. <a href='tg://user?id={u['id']}'>{u['name']}</a> — <b>{u['total']}</b> ta" for i, u in enumerate(stats, 1)]
        text = (f"📊 <b>{name} statistika</b>\n👥 Xodimlar: {len(stats)} ta\n📸 Jami: {total_screenshots} ta\n\n" + "\n".join(lines))
    await call.message.edit_text(text, reply_markup=call.message.reply_markup, parse_mode="HTML")

@router.message(Command("reklama_tekshir"))
async def manual_check(message: Message, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)

@router.message(Command("reklama_users"))
async def list_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    active = await get_all_active()
    text = "👥 <b>Faol xodimlar:</b>\n\n"
    for u in active:
        cnt = _get_screenshot_count_sync(int(u["id"]))
        text += f"{'✅' if cnt >= 2 else '⚠️'} {u['name']} — 📸 {cnt}/2\n"
    await message.answer(text, parse_mode="HTML")

@router.message(Command("reklama_help"))
async def help_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = """📋 <b>Reklama Nazorat — Yordam</b>

Xodimlar: Guruhga rasm yuboring — bot hisoblaydi (kuniga 2 ta)
Admin buyruqlari:
/start_register — Ro'yxatdan o'tkazish
/reklama_tekshir — Qo'lda nazorat
/reklama_stat — Statistika
/reklama_users — Faol xodimlar
/cleanup_users — Tozalash
/sync_subadmin — User varag'idan sinxronlash"""
    await message.answer(text, parse_mode="HTML")
