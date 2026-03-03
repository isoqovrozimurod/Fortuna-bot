import os
import base64
import json
import asyncio
import logging
import contextlib
from datetime import datetime
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
logging.basicConfig(level=logging.INFO)
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
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
BASE_COLS = 8

_gc: gspread.Client | None = None

# ===================== GOOGLE SHEETS CORE =====================

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
    try:
        return sh.worksheet(SUBADMIN_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUBADMIN_SHEET, rows="100", cols="50")
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism", "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
        return ws

def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    headers = ws.row_values(1)
    if date_str in headers:
        return headers.index(date_str) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, date_str)
    return new_col

def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    ids = ws.col_values(2)
    for i, v in enumerate(ids, start=1):
        if str(v).strip() == str(user_id):
            return i
    return None

# ===================== MA'LUMOT YOZISH (BULLETPROOF) =====================

def _write_and_get_count_sync(user_id: int) -> int:
    """Haqiqiy vaqtda Sheetsdan o'qiydi va yangilaydi."""
    try:
        sheet = _ws()
        date_col = _get_date_col(sheet, today_str())
        row = _find_row(sheet, user_id)
        
        if not row:
            return 0
            
        # Bazadagi joriy raqamni olish
        val = sheet.cell(row, date_col).value
        current = int(val) if val and str(val).isdigit() else 0
        new_count = current + 1
        
        # Yangilash
        sheet.update_cell(row, date_col, new_count)
        return new_count
    except Exception as e:
        logger.error(f"Sheets xatosi: {e}")
        return 0

async def write_and_get_count(user_id: int) -> int:
    return await asyncio.get_event_loop().run_in_executor(
        None, _write_and_get_count_sync, user_id
    )

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    sheet = _ws()
    if _find_row(sheet, user_id):
        return False
    
    parts = (full_name or "").split(" ", 1)
    ism, fam = parts[0], (parts[1] if len(parts) > 1 else "")
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")
    
    all_vals = sheet.get_all_values()
    tr = len([r for r in all_vals if len(r) > 1 and r[1].strip()]) 
    
    row = [str(tr), str(user_id), uname, ism, fam, "", sana, "Faol"]
    sheet.append_row(row)
    return True

async def register_user(user_id: int, full_name: str, username: str):
    return await asyncio.get_event_loop().run_in_executor(None, _register_sync, user_id, full_name, username)

# ===================== HANDLERLAR =====================

def _is_group(message: Message) -> bool:
    return message.chat.id == GROUP_ID and not message.from_user.is_bot

@router.message(F.photo | F.document)
async def handle_media(message: Message):
    if not _is_group(message):
        return

    # Document bo'lsa faqat rasm ekanligini tekshirish
    if message.document and not message.document.mime_type.startswith("image/"):
        return

    u = message.from_user
    await register_user(u.id, u.full_name, u.username)
    
    # MUHIM: await bilan kutamiz, orqa fonda (ensure_future) tashlab ketmaymiz
    count = await write_and_get_count(u.id)
    
    if count > 0:
        emoji = "📸" if count == 1 else "✅" if count == 2 else "🎉"
        msg = f"{emoji} <b>{u.full_name}</b>\n📊 Bugun: <b>{count}/2</b>"
        if count == 2: msg += "\n\n🌟 Kunlik reja bajarildi!"
        await message.reply(msg, parse_mode="HTML")

@router.message(Command("start_register"))
async def cmd_start_reg(message: Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ RO'YXATDAN O'TISH", callback_data="reg_me")]])
    await message.answer("Barcha xodimlar tugmani bossin:", reply_markup=kb)

@router.callback_query(F.data == "reg_me")
async def cb_reg(callback: CallbackQuery):
    u = callback.from_user
    is_new = await register_user(u.id, u.full_name, u.username)
    text = "✅ Ro'yxatga olindingiz!" if is_new else "Siz allaqachon bazadasiz."
    await callback.answer(text, show_alert=True)

# ===================== NAZORAT & SCHEDULER =====================

async def check_screenshots(bot: Bot):
    """09:30 va 15:00 hisoboti."""
    try:
        sheet = _ws()
        data = sheet.get_all_records()
        today = today_str()
        
        debtors = []
        for r in data:
            if r.get("Holati") == "Chiqib ketdi": continue
            cnt = int(r.get(today, 0)) if str(r.get(today, 0)).isdigit() else 0
            if cnt < 2:
                name = f"{r.get('Ism', '')} {r.get('Familiya', '')}"
                debtors.append(f"❌ {name} ({cnt}/2)")
        
        report = f"📊 <b>NAZORAT - {now_tz().strftime('%H:%M')}</b>\n\n"
        if debtors:
            report += "<b>Bajarmaganlar:</b>\n" + "\n".join(debtors)
        else:
            report += "🏆 Hamma rejani bajardi!"
        
        await bot.send_message(GROUP_ID, report, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Hisobot xatosi: {e}")

def setup_scheduler(bot: Bot):
    """Asosiy main.py dan chaqiriladigan funksiya."""
    scheduler = AsyncIOScheduler(timezone=TZ)
    # Nazorat vaqtlari
    scheduler.add_job(check_screenshots, CronTrigger(hour=9, minute=30), args=[bot])
    scheduler.add_job(check_screenshots, CronTrigger(hour=15, minute=0), args=[bot])
    scheduler.start()
    logger.info("Scheduler ishga tushdi.")
