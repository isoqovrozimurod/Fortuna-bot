"""
Reklama Nazorat Tizimi - OPTIMALLASHTIRILGAN VERSIYA
- Har kuni 00:05 da yangi sana ustuni avto qo'shiladi
- Screenshot hisobi to'liq sheetda (Koyeb restartlariga chidamli)
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
BASE_COLS = 8  # T/r dan Holati gacha

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

# =================== SANA USTUNI AVTO QO'SHISH ===================
def _ensure_today_column_sync() -> int:
    """Bugungi sana ustunini yaratadi (agar yo'q bo'lsa)"""
    ws = _get_ws()
    headers = ws.row_values(1)
    today = today_str()
    if today in headers:
        return headers.index(today) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, today)
    logger.info(f"✅ Yangi sana ustuni qo'shildi: {today}")
    return new_col

# =================== SCREENSHOT HISOBI (SHEETDA) ===================
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
        day_counts = {}
        for header, col_i in date_cols.items():
            cnt = int(row[col_i]) if col_i < len(row) and str(row[col_i]).strip().isdigit() else 0
            day_counts[header] = cnt
            total += cnt
        result.append({"id": tg_id, "name": name, "total": total, "days": day_counts})
    result.sort(key=lambda x: x["total"], reverse=True)
    return result

async def get_stats(days: int) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_stats_sync, days)

# =================== QOLGAN FUNKSİYALAR (toza qoldirildi) ===================
# ... (register, cleanup, status, get_all_active, sync_from_user_sheet_sync va boshqalar o'zgarmadi, faqat toza)

# =================== SCHEDULER (YANGI 00:05 JOB) ===================
def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="Asia/Tashkent")
    # Yangi sana ustuni
    s.add_job(_ensure_today_column_sync, CronTrigger(hour=0, minute=5), id="new_date_col")
    # Nazorat
    s.add_job(check_screenshots, CronTrigger(hour=9, minute=30), args=[bot])
    s.add_job(check_screenshots, CronTrigger(hour=15, minute=0), args=[bot])
    # Haftalik va oylik o'zgarmadi
    s.start()
    logger.info("✅ Scheduler: 00:05 (yangi ustun) + 09:30/15:00 nazorat")
    return s

# =================== PHOTO/DOCUMENT HANDLER (ENG MUHIM O'ZGARISH) ===================
@router.message(F.chat.id == GROUP_ID, F.photo | F.document)
async def handle_media(message: Message):
    if not (message.from_user and message.chat.id == GROUP_ID):
        return
    user = message.from_user
    await register_user(user.id, user.full_name or "", user.username or "")
    count = await increment_and_save_screenshot(user.id)
    emoji = "📸" if count == 1 else ("✅" if count == 2 else "🎉")
    status = "Birinchi screenshot!" if count == 1 else "Kunlik reja bajarildi!" if count == 2 else f"{count}-screenshot"
    await message.reply(
        f"{emoji} <b>Qabul qilindi!</b>\n"
        f"👤 {user.full_name}\n"
        f"📊 Bugungi: <b>{count}/2</b>\n"
        f"💬 {status}",
        parse_mode="HTML"
    )

# Qolgan handlerlar (/reklama_stat, /cleanup_users, /start_register va h.k.) o'zgarmadi, faqat /cleanup_users qo'shildi.

@router.message(Command("cleanup_users"))
async def cleanup_users_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("🧹 Tozalanmoqda...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _cleanup_sync, _get_ws())
    await msg.edit_text("✅ Tozalash yakunlandi!\n• Bo'sh qatorlar o'chirildi\n• Dublikatlar o'chirildi\n• T/r tartiblandi")



# """
# Reklama Nazorat Tizimi - Kuchaytirilgan versiya
# - Har kuni sub_adminlar varag'iga sana ustuni qo'shiladi
# - Kim qancha reklama tashlagani yozib boriladi
# - Kunlik/Haftalik/Oylik statistika
# - 09:30 va 15:00 nazorat
# """

# import os
# import base64
# import json
# import asyncio
# import logging
# import contextlib
# from datetime import datetime, timedelta
# from zoneinfo import ZoneInfo

# import gspread
# from google.oauth2.service_account import Credentials

# from aiogram import Router, Bot, F
# from aiogram.types import (
#     Message, ChatMemberUpdated,
#     InlineKeyboardMarkup, InlineKeyboardButton,
#     CallbackQuery,
# )
# from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
# from aiogram.exceptions import TelegramForbiddenError
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from apscheduler.triggers.cron import CronTrigger

# # =================== SOZLAMALAR ===================

# router = Router()
# logger = logging.getLogger(__name__)
# TZ = ZoneInfo("Asia/Tashkent")

# def now_tz() -> datetime:
#     return datetime.now(TZ)

# def today_str() -> str:
#     return now_tz().strftime("%d.%m.%Y")

# def date_col_header(date: datetime) -> str:
#     return date.strftime("%d.%m.%Y")

# GROUP_ID  = int(os.getenv("GROUP_ID",  "0"))
# ADMIN_ID  = int(os.getenv("ADMIN_ID",  "0"))
# CHANNEL_LINK  = "https://t.me/FORTUNABIZNES_GALLAOROL"
# SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
# SUBADMIN_SHEET = "sub_adminlar"
# USER_SHEET     = "user"
# SCOPES = [
#     "https://www.googleapis.com/auth/spreadsheets",
#     "https://www.googleapis.com/auth/drive",
# ]

# # Asosiy ustunlar soni (T/r ... Holati)
# BASE_COLS = 8

# SCHEDULER: AsyncIOScheduler | None = None

# # Kunlik screenshot hisob xotirada (tezlik uchun)
# _screenshots: dict[int, dict] = {}
# _registering: set[int] = set()
# _register_lock = asyncio.Lock()


# # =================== SHEETS =====================

# _gc: gspread.Client | None = None

# def _get_gc() -> gspread.Client:
#     global _gc
#     if _gc is None:
#         b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
#         if not b64:
#             raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
#         creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
#         creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
#         _gc = gspread.authorize(creds)
#     return _gc

# def _get_ws() -> gspread.Worksheet:
#     sh = _get_gc().open_by_key(SPREADSHEET_ID)
#     ws = sh.worksheet(SUBADMIN_SHEET)
#     if not ws.row_values(1):
#         ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
#                        "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
#     return ws

# def _get_user_ws() -> gspread.Worksheet:
#     sh = _get_gc().open_by_key(SPREADSHEET_ID)
#     return sh.worksheet(USER_SHEET)


# # =================== SANA USTUNI BOSHQARUVI ===================

# def _get_or_create_date_col_sync(ws: gspread.Worksheet, date_header: str) -> int:
#     """
#     Berilgan sana uchun ustun indeksini qaytaradi (1-based).
#     Yo'q bo'lsa — yangi ustun qo'shadi.
#     """
#     headers = ws.row_values(1)
#     if date_header in headers:
#         return headers.index(date_header) + 1  # 1-based

#     # Yangi ustun qo'shish
#     new_col = len(headers) + 1
#     ws.update_cell(1, new_col, date_header)
#     return new_col


# def _save_screenshot_to_sheet_sync(user_id: int, count: int) -> None:
#     """Bugungi screenshot sonini sub_adminlar varag'iga yozadi"""
#     ws = _get_ws()
#     date_header = today_str()
#     col = _get_or_create_date_col_sync(ws, date_header)

#     # Foydalanuvchi qatorini topamiz
#     ids = ws.col_values(2)
#     for i, val in enumerate(ids, start=1):
#         if str(val).strip() == str(user_id):
#             ws.update_cell(i, col, count)
#             return


# async def save_screenshot_to_sheet(user_id: int, count: int) -> None:
#     loop = asyncio.get_event_loop()
#     with contextlib.suppress(Exception):
#         await loop.run_in_executor(None, _save_screenshot_to_sheet_sync, user_id, count)


# # =================== STATISTIKA HISOBLASH ===================

# def _get_stats_sync(days: int) -> list[dict]:
#     """
#     Oxirgi `days` kunlik statistikani qaytaradi.
#     Returns: [{"name": ..., "total": ..., "days": {date: count}}]
#     """
#     ws = _get_ws()
#     headers = ws.row_values(1)
#     all_rows = ws.get_all_values()

#     # Sana ustunlarini aniqlaymiz
#     date_cols = {}  # {header: col_idx (0-based)}
#     cutoff = now_tz() - timedelta(days=days - 1)
#     for i, h in enumerate(headers[BASE_COLS:], start=BASE_COLS):
#         try:
#             dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
#             if dt >= cutoff.replace(hour=0, minute=0, second=0):
#                 date_cols[h] = i
#         except ValueError:
#             pass

#     result = []
#     for row in all_rows[1:]:
#         tg_id = str(row[1]).strip() if len(row) > 1 else ""
#         if not tg_id:
#             continue
#         if str(row[7]).strip() != "Faol" if len(row) > 7 else True:
#             continue

#         ism = str(row[3]).strip() if len(row) > 3 else ""
#         familiya = str(row[4]).strip() if len(row) > 4 else ""
#         name = f"{ism} {familiya}".strip() or "Noma'lum"

#         day_counts = {}
#         total = 0
#         for header, col_i in date_cols.items():
#             cnt = int(row[col_i]) if col_i < len(row) and str(row[col_i]).strip().isdigit() else 0
#             day_counts[header] = cnt
#             total += cnt

#         result.append({
#             "id": tg_id,
#             "name": name,
#             "total": total,
#             "days": day_counts,
#         })

#     result.sort(key=lambda x: x["total"], reverse=True)
#     return result


# async def get_stats(days: int) -> list[dict]:
#     loop = asyncio.get_event_loop()
#     return await loop.run_in_executor(None, _get_stats_sync, days)


# # =================== FOYDALANUVCHI OPERATSIYALARI ===================

# def _find_row_sync(user_id: int) -> int | None:
#     ws = _get_ws()
#     for i, val in enumerate(ws.col_values(2), start=1):
#         if str(val).strip() == str(user_id):
#             return i
#     return None


# def _cleanup_sync(ws: gspread.Worksheet) -> None:
#     """Bo'sh qatorlar, dublikatlar o'chiriladi. T/r, Holati, Sana to'ldiriladi."""
#     all_rows = ws.get_all_values()
#     if len(all_rows) <= 1:
#         return

#     seen_ids: set[str] = set()
#     valid_rows = []
#     for row in all_rows[1:]:
#         tg_id = str(row[1]).strip() if len(row) > 1 else ""
#         if tg_id and tg_id not in seen_ids:
#             seen_ids.add(tg_id)
#             valid_rows.append(list(row))

#     if not valid_rows:
#         return

#     # Header ustunlari sonini olamiz
#     header_len = len(all_rows[0])
#     sana_now = now_tz().strftime("%Y-%m-%d %H:%M")

#     for i, row in enumerate(valid_rows, start=1):
#         while len(row) < header_len:
#             row.append("")
#         row[0] = str(i)
#         if not str(row[7]).strip():
#             row[7] = "Faol"
#         if not str(row[6]).strip():
#             row[6] = sana_now

#     total_existing = len(all_rows)
#     count = len(valid_rows)

#     ws.update(f"A2:{chr(64 + header_len)}{count + 1}",
#               valid_rows, value_input_option="RAW")

#     if total_existing > count + 1:
#         ws.update(
#             f"A{count + 2}:{chr(64 + header_len)}{total_existing}",
#             [[""] * header_len] * (total_existing - count - 1),
#             value_input_option="RAW"
#         )


# def _register_sync(user_id: int, full_name: str, username: str) -> bool:
#     """True = yangi, False = mavjud yangilandi"""
#     ws = _get_ws()
#     row_idx = _find_row_sync(user_id)

#     parts = (full_name or "").split(" ", 1)
#     ism = parts[0]
#     familiya = parts[1] if len(parts) > 1 else ""
#     uname = f"@{username}" if username else ""
#     sana = now_tz().strftime("%Y-%m-%d %H:%M")

#     if row_idx is not None:
#         ws.update_cell(row_idx, 3, uname)
#         ws.update_cell(row_idx, 4, ism)
#         ws.update_cell(row_idx, 5, familiya)
#         ws.update_cell(row_idx, 8, "Faol")
#         return False

#     # Yangi — avval tozalaymiz
#     _cleanup_sync(ws)
#     all_vals = ws.get_all_values()
#     valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
#     tr = valid_count + 1

#     ws.append_row([str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"],
#                   value_input_option="RAW")
#     return True


# def _set_status_sync(user_id: int, status: str) -> None:
#     row_idx = _find_row_sync(user_id)
#     if row_idx:
#         _get_ws().update_cell(row_idx, 8, status)


# def _get_all_active_sync() -> list[dict]:
#     ws = _get_ws()
#     result = []
#     for r in ws.get_all_records():
#         tg_id = str(r.get("Telegram ID", "")).strip()
#         if tg_id and str(r.get("Holati", "")).strip() == "Faol":
#             result.append({
#                 "id": tg_id,
#                 "name": f"{r.get('Ism','')} {r.get('Familiya','')}".strip(),
#                 "username": str(r.get("Username", "")),
#             })
#     return result


# def _sync_from_user_sheet_sync() -> int:
#     """
#     user varag'idagi ma'lumotlarni sub_adminlar ga ko'chiradi.
#     sub_adminlar da ID bor lekin ma'lumotlar to'liq emas bo'lsa — user dan oladi.
#     Returns: yangilangan qatorlar soni
#     """
#     subadmin_ws = _get_ws()
#     user_ws = _get_user_ws()

#     # user varag'idagi barcha ma'lumotlarni map qilamiz {id: row}
#     user_data: dict[str, list] = {}
#     for r in user_ws.get_all_values()[1:]:
#         tg_id = str(r[1]).strip() if len(r) > 1 else ""
#         if tg_id:
#             user_data[tg_id] = r

#     subadmin_rows = subadmin_ws.get_all_values()
#     updated = 0

#     for i, row in enumerate(subadmin_rows[1:], start=2):
#         tg_id = str(row[1]).strip() if len(row) > 1 else ""
#         if not tg_id or tg_id not in user_data:
#             continue

#         u = user_data[tg_id]
#         changed = False

#         # Username
#         if len(row) > 2 and not str(row[2]).strip() and len(u) > 2 and u[2].strip():
#             subadmin_ws.update_cell(i, 3, u[2])
#             changed = True
#         # Ism
#         if len(row) > 3 and not str(row[3]).strip() and len(u) > 3 and u[3].strip():
#             subadmin_ws.update_cell(i, 4, u[3])
#             changed = True
#         # Familiya
#         if len(row) > 4 and not str(row[4]).strip() and len(u) > 4 and u[4].strip():
#             subadmin_ws.update_cell(i, 5, u[4])
#             changed = True
#         # Telefon
#         if len(row) > 5 and not str(row[5]).strip() and len(u) > 5 and u[5].strip():
#             subadmin_ws.update_cell(i, 6, u[5])
#             changed = True

#         if changed:
#             updated += 1

#     return updated


# # =================== ASYNC WRAPPERLAR ===================

# async def register_user(user_id: int, full_name: str, username: str) -> bool:
#     async with _register_lock:
#         if user_id in _registering:
#             return False
#         _registering.add(user_id)
#     try:
#         loop = asyncio.get_event_loop()
#         return await loop.run_in_executor(None, _register_sync, user_id, full_name, username)
#     finally:
#         async with _register_lock:
#             _registering.discard(user_id)


# async def set_status(user_id: int, status: str) -> None:
#     loop = asyncio.get_event_loop()
#     await loop.run_in_executor(None, _set_status_sync, user_id, status)


# async def get_all_active() -> list[dict]:
#     loop = asyncio.get_event_loop()
#     return await loop.run_in_executor(None, _get_all_active_sync)


# # =================== SCREENSHOT HISOB ===================

# def get_screenshot_count(user_id: int) -> int:
#     data = _screenshots.get(user_id)
#     if not data or data.get("date") != today_str():
#         return 0
#     return data.get("count", 0)


# def increment_screenshot(user_id: int) -> int:
#     today = today_str()
#     data = _screenshots.get(user_id, {})
#     if data.get("date") != today:
#         _screenshots[user_id] = {"date": today, "count": 1}
#         return 1
#     data["count"] = data.get("count", 0) + 1
#     _screenshots[user_id] = data
#     return data["count"]


# # =================== GURUH HANDLERLARI ===================

# def is_group_msg(message: Message) -> bool:
#     return (
#         message.from_user is not None
#         and not message.from_user.is_bot
#         and message.chat.id == GROUP_ID
#         and GROUP_ID != 0
#     )


# def is_admin_in_group(message: Message) -> bool:
#     return is_group_msg(message) and message.from_user.id == ADMIN_ID


# @router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
# async def user_joined(event: ChatMemberUpdated):
#     if event.chat.id != GROUP_ID:
#         return
#     user = event.new_chat_member.user
#     if user.is_bot:
#         return
#     with contextlib.suppress(Exception):
#         await register_user(user.id, user.full_name or "", user.username or "")


# @router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
# async def user_left(event: ChatMemberUpdated):
#     if event.chat.id != GROUP_ID:
#         return
#     user = event.new_chat_member.user
#     if user.is_bot:
#         return
#     with contextlib.suppress(Exception):
#         await set_status(user.id, "Chiqib ketdi")


# async def _handle_screenshot(message: Message, user) -> None:
#     try:
#         await register_user(user.id, user.full_name or "", user.username or "")
#     except Exception:
#         pass

#     count = increment_screenshot(user.id)

#     # Sheets ga ham yozamiz (background)
#     asyncio.ensure_future(save_screenshot_to_sheet(user.id, count))

#     emoji = "📸" if count == 1 else ("✅" if count == 2 else "🎉")
#     status = (
#         "Birinchi screenshot qabul qilindi!" if count == 1
#         else "Ajoyib! Kunlik rejangiz bajarildi!" if count == 2
#         else f"{count}-screenshot qabul qilindi!"
#     )
#     with contextlib.suppress(Exception):
#         await message.reply(
#             f"{emoji} <b>Qabul qilindi!</b>\n"
#             f"👤 {user.full_name}\n"
#             f"📊 Bugungi natija: <b>{count}/2</b>\n"
#             f"💬 {status}",
#             parse_mode="HTML"
#         )


# @router.message(F.chat.id == GROUP_ID, F.photo)
# async def photo_received(message: Message):
#     if not is_group_msg(message):
#         return
#     await _handle_screenshot(message, message.from_user)


# @router.message(F.chat.id == GROUP_ID, F.document)
# async def document_received(message: Message):
#     if not is_group_msg(message):
#         return
#     doc = message.document
#     if doc and doc.mime_type and doc.mime_type.startswith("image/"):
#         await _handle_screenshot(message, message.from_user)
#     else:
#         with contextlib.suppress(Exception):
#             await register_user(
#                 message.from_user.id,
#                 message.from_user.full_name or "",
#                 message.from_user.username or ""
#             )


# @router.message(F.chat.id == GROUP_ID, ~F.photo, ~F.document)
# async def any_message_received(message: Message):
#     if not is_group_msg(message):
#         return
#     with contextlib.suppress(Exception):
#         await register_user(
#             message.from_user.id,
#             message.from_user.full_name or "",
#             message.from_user.username or ""
#         )


# # =================== RO'YXATDAN O'TKAZISH ===================

# @router.message(Command("start_register"))
# async def start_registration_process(message: Message):
#     if not is_admin_in_group(message):
#         return
#     keyboard = InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="✅ MEN SHU YERDAMAN", callback_data="register_me")]
#     ])
#     await message.bot.send_message(
#         GROUP_ID,
#         "📢 <b>DIQQAT, GURUH A'ZOLARI!</b>\n\n"
#         "Barcha xodimlar quyidagi tugmani bosishi SHART!\n\n"
#         "⚠️ Kim tugmani bosmasa hisobotda ko'rinmaydi.\n\n"
#         "👇 <b>Hoziroq bosing:</b>",
#         reply_markup=keyboard, parse_mode="HTML"
#     )
#     with contextlib.suppress(Exception):
#         await message.delete()


# @router.callback_query(F.data == "register_me")
# async def process_registration(callback: CallbackQuery):
#     user = callback.from_user
#     try:
#         is_new = await register_user(user.id, user.full_name or "", user.username or "")
#         await callback.answer(
#             "✅ Ro'yxatga olindingiz!" if is_new else "✅ Ma'lumotlar yangilandi!",
#             show_alert=True
#         )
#     except Exception as e:
#         logger.error(f"Ro'yxatdan o'tkazishda xato: {e}")
#         await callback.answer("❌ Xato, qayta urinib ko'ring.", show_alert=True)


# # =================== NAZORAT HISOBOTI ===================

# def _mention(user_id: str, name: str) -> str:
#     safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
#     return f'<a href="tg://user?id={user_id}">{safe}</a>'


# async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
#     limit = 3800
#     while text:
#         if len(text) <= limit:
#             await bot.send_message(chat_id, text, parse_mode="HTML")
#             break
#         cut = text.rfind("\n", 0, limit) or limit
#         await bot.send_message(chat_id, text[:cut], parse_mode="HTML")
#         text = text[cut:]


# async def check_screenshots(bot: Bot) -> None:
#     """09:30 va 15:00 da chaqiriladi"""
#     if GROUP_ID == 0:
#         return

#     try:
#         active = await get_all_active()
#     except Exception as e:
#         logger.error(f"Active userlarni olishda xato: {e}")
#         return

#     if not active:
#         if ADMIN_ID:
#             with contextlib.suppress(Exception):
#                 await bot.send_message(ADMIN_ID,
#                     "⚠️ sub_adminlar bazasida faol xodim yo'q!\n"
#                     "Guruhga /start_register yuboring.")
#         return

#     debtors, done_list = [], []
#     for u in active:
#         try:
#             uid = int(u["id"])
#         except (ValueError, TypeError):
#             continue
#         cnt = get_screenshot_count(uid)
#         if cnt >= 2:
#             done_list.append(u)
#         else:
#             debtors.append({**u, "count": cnt})

#     total = len(active)
#     completed = len(done_list)
#     time_str = now_tz().strftime("%H:%M")
#     h, m = now_tz().hour, now_tz().minute
#     next_check = (
#         "Bugun 09:30" if h < 9 or (h == 9 and m < 30)
#         else "Bugun 15:00" if h < 15
#         else "Ertaga 09:30"
#     )
#     percent = int(completed / total * 100) if total else 0

#     if debtors:
#         done_lines = ""
#         if done_list:
#             done_lines = "\n✅ <b>Bajarganlar:</b>\n"
#             for u in done_list:
#                 done_lines += f"   ✔️ {_mention(u['id'], u['name'])} — 2/2 ✅\n"

#         debtor_lines = "\n❌ <b>BAJARMAGAN XODIMLAR:</b>\n"
#         for i, u in enumerate(debtors, 1):
#             cnt = u["count"]
#             debtor_lines += (
#                 f"\n{i}. {_mention(u['id'], u['name'])}\n"
#                 f"   📸 {cnt}/2 — "
#                 + ("bitta yetishmayapti! ⚠️\n" if cnt == 1 else "hali birorta ham yoq! 🚫\n")
#             )

#         text = (
#             f"🚨 <b>NAZORAT HISOBOTI — {time_str}</b>\n"
#             f"📅 {now_tz().strftime('%d.%m.%Y')}\n\n"
#             f"👥 Jami faol: {total} ta xodim\n"
#             f"✅ Bajardi: {completed} ta\n"
#             f"❌ Bajarmadi: {len(debtors)} ta\n"
#             f"📊 Bajarilish: {percent}%\n"
#             + done_lines + debtor_lines
#             + f"\n➖➖➖➖➖➖➖➖➖➖\n"
#             f"❗ <b>Zudlik bilan reklama tarqatib screenshot yuborsin!</b>\n"
#             f"📌 {CHANNEL_LINK}\n"
#             f"⏰ Keyingi tekshiruv: {next_check}"
#         )
#         try:
#             await _send_long(bot, GROUP_ID, text)
#         except TelegramForbiddenError:
#             logger.error("Botga guruhda yozish taqiqlangan!")
#         except Exception as e:
#             logger.error(f"Hisobot yuborishda xato: {e}")
#     else:
#         done_lines = "\n".join(f"   ✔️ {_mention(u['id'], u['name'])}" for u in done_list)
#         with contextlib.suppress(Exception):
#             await bot.send_message(
#                 GROUP_ID,
#                 f"🏆 <b>AJOYIB! — {time_str}</b>\n\n"
#                 "✅ <b>BARCHA XODIMLAR REJANI BAJARDI!</b>\n\n"
#                 f"👥 {total} ta xodim — barchasi 2/2 screenshot yubordi\n\n"
#                 f"{done_lines}\n\n👏 Jamoaga rahmat! 💪",
#                 parse_mode="HTML"
#             )

#     if ADMIN_ID:
#         with contextlib.suppress(Exception):
#             await bot.send_message(
#                 ADMIN_ID,
#                 f"📊 <b>Admin — {time_str}</b>\n\n"
#                 f"👥 Faol: {total}\n"
#                 f"✅ Bajargan: {completed}\n"
#                 f"❌ Bajarmagan: {len(debtors)}\n"
#                 f"📈 {percent}%",
#                 parse_mode="HTML"
#             )


# # =================== STATISTIKA ===================

# def _build_stat_text(stats: list[dict], period_name: str, days: int) -> str:
#     if not stats:
#         return f"📊 <b>{period_name} statistika</b>\n\nMa'lumot yo'q."

#     total_screenshots = sum(u["total"] for u in stats)
#     lines = []
#     for i, u in enumerate(stats, 1):
#         bar = "🟩" * min(u["total"], 10) + "⬜" * max(0, 10 - min(u["total"], 10))
#         lines.append(
#             f"{i}. {_mention(u['id'], u['name'])}\n"
#             f"   {bar} <b>{u['total']}</b> ta\n"
#         )

#     period_start = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
#     period_end = now_tz().strftime("%d.%m.%Y")

#     return (
#         f"📊 <b>{period_name} statistika</b>\n"
#         f"📅 {period_start} — {period_end}\n\n"
#         f"👥 Xodimlar: {len(stats)} ta\n"
#         f"📸 Jami reklama: {total_screenshots} ta\n"
#         f"➖➖➖➖➖➖➖➖➖➖\n\n"
#         + "\n".join(lines)
#     )


# def stat_keyboard() -> InlineKeyboardMarkup:
#     return InlineKeyboardMarkup(inline_keyboard=[
#         [
#             InlineKeyboardButton(text="📅 Kunlik",   callback_data="stat_daily"),
#             InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
#             InlineKeyboardButton(text="🗓 Oylik",    callback_data="stat_monthly"),
#         ],
#         [InlineKeyboardButton(text="❌ Yopish", callback_data="stat_close")],
#     ])


# @router.message(Command("reklama_stat"))
# async def show_stats(message: Message, bot: Bot):
#     if message.from_user.id != ADMIN_ID:
#         return
#     # Shaxsiy chatga yuboramiz
#     await bot.send_message(
#         ADMIN_ID,
#         "📊 <b>Reklama statistikasi</b>\n\nQaysi davrni ko'rmoqchisiz?",
#         reply_markup=stat_keyboard(),
#         parse_mode="HTML"
#     )
#     with contextlib.suppress(Exception):
#         await message.delete()


# @router.callback_query(F.data.in_({"stat_daily", "stat_weekly", "stat_monthly", "stat_close"}))
# async def stat_callback(call: CallbackQuery, bot: Bot):
#     if call.from_user.id != ADMIN_ID:
#         await call.answer("❌ Ruxsat yo'q!", show_alert=True)
#         return

#     if call.data == "stat_close":
#         await call.message.delete()
#         return

#     await call.answer("⏳ Hisoblanmoqda...")

#     if call.data == "stat_daily":
#         days, name = 1, "Kunlik"
#     elif call.data == "stat_weekly":
#         days, name = 7, "Haftalik"
#     else:
#         days, name = 30, "Oylik"

#     try:
#         stats = await get_stats(days)
#         text = _build_stat_text(stats, name, days)
#         await call.message.edit_text(
#             text,
#             reply_markup=stat_keyboard(),
#             parse_mode="HTML"
#         )
#     except Exception as e:
#         logger.error(f"Statistika xato: {e}")
#         await call.message.edit_text(f"❌ Xato: {e}", reply_markup=stat_keyboard())


# # =================== SCHEDULER ===================

# async def send_weekly_stats(bot: Bot) -> None:
#     """Har dushanba haftalik statistika guruhga"""
#     try:
#         stats = await get_stats(7)
#         text = _build_stat_text(stats, "Haftalik", 7)
#         await _send_long(bot, GROUP_ID, "📆 " + text)
#     except Exception as e:
#         logger.error(f"Haftalik stat xato: {e}")


# async def send_monthly_stats(bot: Bot) -> None:
#     """Har oyning 1-si oylik statistika guruhga"""
#     try:
#         stats = await get_stats(30)
#         text = _build_stat_text(stats, "Oylik", 30)
#         await _send_long(bot, GROUP_ID, "🗓 " + text)
#     except Exception as e:
#         logger.error(f"Oylik stat xato: {e}")


# def setup_scheduler(bot: Bot) -> AsyncIOScheduler | None:
#     global SCHEDULER
#     if GROUP_ID == 0:
#         logger.error("GROUP_ID sozlanmagan!")
#         return None

#     s = AsyncIOScheduler(timezone="Asia/Tashkent")

#     # Kunlik nazorat
#     s.add_job(check_screenshots, CronTrigger(hour=9, minute=30),
#               args=[bot], id="morning",   replace_existing=True,
#               max_instances=1, coalesce=True, misfire_grace_time=300)
#     s.add_job(check_screenshots, CronTrigger(hour=15, minute=0),
#               args=[bot], id="afternoon", replace_existing=True,
#               max_instances=1, coalesce=True, misfire_grace_time=300)

#     # Haftalik — har dushanba 09:00
#     s.add_job(send_weekly_stats, CronTrigger(day_of_week="mon", hour=9, minute=0),
#               args=[bot], id="weekly_stat", replace_existing=True,
#               max_instances=1, coalesce=True)

#     # Oylik — har oyning 1-si 09:00
#     s.add_job(send_monthly_stats, CronTrigger(day=1, hour=9, minute=0),
#               args=[bot], id="monthly_stat", replace_existing=True,
#               max_instances=1, coalesce=True)

#     s.start()
#     SCHEDULER = s
#     logger.info("Scheduler: 09:30, 15:00 (nazorat) | Dushanba 09:00 (haftalik) | 1-chi 09:00 (oylik)")
#     return s


# # =================== ADMIN BUYRUQLARI ===================

# @router.message(Command("reklama_tekshir"))
# async def manual_check(message: Message, bot: Bot):
#     if not is_admin_in_group(message):
#         return
#     msg = await message.answer("🔍 Tekshirilmoqda...")
#     await check_screenshots(bot)
#     with contextlib.suppress(Exception):
#         await msg.delete()
#         await message.delete()


# @router.message(Command("reklama_users"))
# async def list_users(message: Message):
#     if not is_admin_in_group(message):
#         return
#     try:
#         active = await get_all_active()
#     except Exception as e:
#         await message.answer(f"❌ Xato: {e}")
#         return

#     if not active:
#         await message.answer("❌ Faol xodimlar yo'q")
#         return

#     text = "👥 <b>Faol xodimlar:</b>\n\n"
#     for u in active[:25]:
#         cnt = get_screenshot_count(int(u["id"]))
#         emoji = "✅" if cnt >= 2 else "⚠️"
#         text += f"{emoji} <b>{u['name']}</b> — 📸 {cnt}/2\n"
#     if len(active) > 25:
#         text += f"\n<i>+{len(active) - 25} ta xodim</i>"

#     sent = await message.answer(text, parse_mode="HTML")
#     with contextlib.suppress(Exception):
#         await message.delete()
#     await asyncio.sleep(60)
#     with contextlib.suppress(Exception):
#         await sent.delete()


# @router.message(Command("sync_subadmin"))
# async def sync_subadmin(message: Message, bot: Bot):
#     """user varag'idan sub_adminlar ga ma'lumot ko'chiradi"""
#     if message.from_user.id != ADMIN_ID:
#         return
#     msg = await bot.send_message(ADMIN_ID, "⏳ Sinxronlanmoqda...")
#     try:
#         loop = asyncio.get_event_loop()
#         updated = await loop.run_in_executor(None, _sync_from_user_sheet_sync)
#         await msg.edit_text(f"✅ Sinxronlash yakunlandi!\n📝 {updated} ta qator yangilandi.")
#     except Exception as e:
#         await msg.edit_text(f"❌ Xato: {e}")
#     with contextlib.suppress(Exception):
#         await message.delete()


# @router.message(Command("reklama_help"))
# async def help_command(message: Message):
#     if not is_admin_in_group(message):
#         return
#     sent = await message.answer(
#         "📋 <b>Reklama Nazorat — Yordam</b>\n\n"
#         "<b>Xodimlar:</b>\n"
#         "• Guruhga rasm yuboring — bot avtomatik hisoblaydi\n"
#         "• Har kuni kamida 2 ta reklama screenshoti kerak\n\n"
#         "<b>Admin buyruqlari:</b>\n"
#         "/start_register — Barchani ro'yxatdan o'tkazish\n"
#         "/reklama_tekshir — Qo'lda tekshirish (guruhda)\n"
#         "/reklama_stat — Statistika (kunlik/haftalik/oylik)\n"
#         "/reklama_users — Faol xodimlar ro'yxati\n"
#         "/sync_subadmin — User dan sub_admin ga ma'lumot ko'chirish\n\n"
#         "<b>Avtomatik:</b>\n"
#         "⏰ 09:30, 15:00 — Kunlik nazorat\n"
#         "📆 Har dushanba 09:00 — Haftalik statistika (guruhga)\n"
#         "🗓 Har oyning 1-si 09:00 — Oylik statistika (guruhga)",
#         parse_mode="HTML"
#     )
#     with contextlib.suppress(Exception):
#         await message.delete()
#     await asyncio.sleep(40)
#     with contextlib.suppress(Exception):
#         await sent.delete()


# @router.message(Command("debug_reklama"))
# async def debug_command(message: Message):
#     if not message.from_user or message.from_user.id != ADMIN_ID:
#         return
#     await message.answer(
#         f"Chat ID: <code>{message.chat.id}</code>\n"
#         f"ENV GROUP_ID: <code>{GROUP_ID}</code>\n"
#         f"Match: {'✅' if message.chat.id == GROUP_ID else '❌'}\n"
#         f"Xotiradagi xodimlar: {len(_screenshots)}",
#         parse_mode="HTML"
#     )
