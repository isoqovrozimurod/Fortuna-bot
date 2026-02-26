"""
Reklama Nazorat Tizimi - Google Sheets versiyasi
Har kuni 09:30 va 15:00 da screenshot tekshirish
Sub-adminlar ma'lumotlari Google Sheets "Sub-adminlar" varag'ida saqlanadi
"""

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
    Message,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# =================== SOZLAMALAR ===================

router = Router()
logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Tashkent")

def now_tz() -> datetime:
    return datetime.now(TZ)

def today_str() -> str:
    return now_tz().strftime("%Y-%m-%d")

try:
    GROUP_ID = int(os.getenv("GROUP_ID", "0"))
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (ValueError, TypeError):
    GROUP_ID = 0
    ADMIN_ID = 0

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "Sub-adminlar"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCHEDULER: AsyncIOScheduler | None = None

# Screenshot kunlik hisob — xotirada saqlanadi (restart da tozalanadi, lekin yetarli)
_screenshots: dict[int, dict] = {}  # {user_id: {"date": "2026-02-26", "count": 2}}


# =================== SHEETS =====================

_gc: gspread.Client | None = None

def get_sheets_client() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def get_subadmin_sheet() -> gspread.Worksheet:
    gc = get_sheets_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SUBADMIN_SHEET)
    if not ws.row_values(1):
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism", "Familiya",
                        "Telefon raqami", "Qo'shilgan sana", "Holati"])
    return ws


def _find_row(user_id: int) -> int | None:
    """Foydalanuvchi qatorini topadi (1-based), yo'q bo'lsa None"""
    ws = get_subadmin_sheet()
    ids = ws.col_values(2)  # Telegram ID ustuni
    for i, val in enumerate(ids, start=1):
        if str(val) == str(user_id):
            return i
    return None


def _register_user_sync(user_id: int, full_name: str, username: str) -> bool:
    """True = yangi, False = mavjud edi"""
    ws = get_subadmin_sheet()
    row_idx = None
    ids = ws.col_values(2)
    for i, val in enumerate(ids, start=1):
        if str(val) == str(user_id):
            row_idx = i
            break

    parts = (full_name or "").split(" ", 1)
    ism = parts[0]
    familiya = parts[1] if len(parts) > 1 else ""
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")

    if row_idx is None:
        # Yangi qator
        all_rows = ws.get_all_values()
        tr = len(all_rows)  # sarlavha + mavjud qatorlar
        ws.append_row([str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"])
        return True
    else:
        # Mavjud — username va ismni yangilaymiz
        ws.update_cell(row_idx, 3, uname)
        ws.update_cell(row_idx, 4, ism)
        ws.update_cell(row_idx, 5, familiya)
        ws.update_cell(row_idx, 8, "Faol")
        return False


def _set_status_sync(user_id: int, status: str):
    row_idx = _find_row(user_id)
    if row_idx:
        ws = get_subadmin_sheet()
        ws.update_cell(row_idx, 8, status)


def _get_all_active_sync() -> list[dict]:
    ws = get_subadmin_sheet()
    records = ws.get_all_records()
    result = []
    for r in records:
        if str(r.get("Holati", "")).strip() == "Faol":
            result.append({
                "id": str(r.get("Telegram ID", "")),
                "name": f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip(),
                "username": str(r.get("Username", "")),
            })
    return result


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _register_user_sync, user_id, full_name, username)


async def set_status(user_id: int, status: str):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _set_status_sync, user_id, status)


async def get_all_active() -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_all_active_sync)


# =================== SCREENSHOT HISOB ===================

def get_screenshot_count(user_id: int) -> int:
    data = _screenshots.get(user_id)
    if not data or data.get("date") != today_str():
        return 0
    return data.get("count", 0)


def increment_screenshot(user_id: int) -> int:
    today = today_str()
    data = _screenshots.get(user_id, {})
    if data.get("date") != today:
        _screenshots[user_id] = {"date": today, "count": 1}
        return 1
    data["count"] = data.get("count", 0) + 1
    _screenshots[user_id] = data
    return data["count"]


# =================== ADMIN TEKSHIRUVI ===================

def is_admin_in_group(message: Message) -> bool:
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.id == GROUP_ID
        and ADMIN_ID != 0
        and GROUP_ID != 0
    )


# =================== RO'YXATDAN O'TKAZISH ===================

@router.message(Command("start_register"))
async def start_registration_process(message: Message):
    if not is_admin_in_group(message):
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ MEN SHU YERDAMAN (Tasdiqlash)",
            callback_data="register_me"
        )]
    ])
    text = (
        "📢 <b>DIQQAT, GURUH A'ZOLARI!</b>\n\n"
        "Bot bazasini yangilash uchun barcha xodimlar quyidagi tugmani bosishi SHART!\n\n"
        "⚠️ Kim tugmani bosmasa:\n"
        "• Screenshot nazoratidan chiqib ketadi\n"
        "• Hisobotda ko'rinmaydi\n"
        "• Avtomatik ogohlantirishlar olmaydi\n\n"
        "👇 <b>Hoziroq bosing:</b>"
    )
    await message.bot.send_message(GROUP_ID, text, reply_markup=keyboard, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    user = callback.from_user
    try:
        is_new = await register_user(user.id, user.full_name or "", user.username or "")
        await callback.answer(
            "✅ Siz ro'yxatga olindingiz! Rahmat." if is_new else "✅ Ma'lumotlar yangilandi!",
            show_alert=is_new
        )
    except Exception as e:
        logger.error(f"Ro'yxatdan o'tkazishda xato: {e}")
        await callback.answer("❌ Xato yuz berdi, qayta urinib ko'ring.", show_alert=True)


# =================== AVTOMATIK TUTIB OLISH ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    if user.is_bot:
        return
    try:
        await register_user(user.id, user.full_name or "", user.username or "")
        logger.info(f"Guruhga qo'shildi: {user.full_name}")
    except Exception as e:
        logger.error(f"Guruhga qo'shilganda xato: {e}")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    if user.is_bot:
        return
    try:
        await set_status(user.id, "Chiqib ketdi")
        logger.info(f"Guruhdan chiqdi: {user.full_name}")
    except Exception as e:
        logger.error(f"Chiqib ketganda xato: {e}")


@router.message(F.chat.id == GROUP_ID, ~F.photo, ~F.document)
async def capture_any_activity(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    try:
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or ""
        )
    except Exception as e:
        logger.warning(f"Faollik saqlashda xato: {e}")


# =================== SCREENSHOT QABUL QILISH ===================

async def _handle_screenshot(message: Message, user):
    try:
        await register_user(user.id, user.full_name or "", user.username or "")
    except Exception:
        pass

    count = increment_screenshot(user.id)

    if count == 1:
        emoji, status = "📸", "Birinchi screenshot qabul qilindi!"
    elif count == 2:
        emoji, status = "✅", "Ajoyib! Kunlik rejangiz bajarildi!"
    else:
        emoji, status = "🎉", f"Zo'r! {count}-screenshot qabul qilindi!"

    with contextlib.suppress(Exception):
        await message.reply(
            f"{emoji} <b>Qabul qilindi!</b>\n"
            f"👤 {user.full_name}\n"
            f"📊 Bugungi natija: <b>{count}/2 screenshot</b>\n"
            f"💬 {status}",
            parse_mode="HTML"
        )


@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    user = message.from_user
    if not user or user.is_bot:
        return
    await _handle_screenshot(message, user)


@router.message(F.chat.id == GROUP_ID, F.document)
async def document_received(message: Message):
    user = message.from_user
    if not user or user.is_bot:
        return
    doc = message.document
    if doc and doc.mime_type and doc.mime_type.startswith("image/"):
        await _handle_screenshot(message, user)


# =================== NAZORAT HISOBOTI ===================

def _mention_html(user_id: str, fullname: str) -> str:
    safe = fullname.replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe}</a>'


async def _send_long_html(bot: Bot, chat_id: int, text: str):
    limit = 3800
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    parts.append(text)
    for part in parts:
        if part.strip():
            await bot.send_message(chat_id, part, parse_mode="HTML")


async def check_screenshots(bot: Bot):
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan!")
        return

    try:
        active_users = await get_all_active()
    except Exception as e:
        logger.error(f"Foydalanuvchilarni olishda xato: {e}")
        return

    if not active_users:
        logger.warning("Bazada faol foydalanuvchilar yo'q!")
        return

    debtors = []
    completed = 0

    for u in active_users:
        try:
            uid = int(u["id"])
        except (ValueError, TypeError):
            continue
        count = get_screenshot_count(uid)
        if count >= 2:
            completed += 1
        else:
            debtors.append({**u, "count": count})

    total = len(active_users)
    current_time = now_tz().strftime("%H:%M")
    percent = int(completed / total * 100) if total > 0 else 0

    h, m = now_tz().hour, now_tz().minute
    if h < 9 or (h == 9 and m < 30):
        next_check = "Bugun 09:30 da"
    elif h < 15:
        next_check = "Bugun 15:00 da"
    else:
        next_check = "Ertaga 09:30 da"

    if debtors:
        header = (
            f"🚨 <b>NAZORAT HISOBOTI ({current_time})</b>\n\n"
            f"👥 Faol xodimlar: {total} ta\n"
            f"✅ Bajarganlar: {completed} ta\n"
            f"❌ Bajarmaganlar: {len(debtors)} ta\n"
            f"📊 Bajarilish: {percent}%\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "👇 <b>REKLAMA PLANINI BAJARMAGAN XODIMLAR:</b>\n\n"
        )
        lines = []
        for idx, u in enumerate(debtors, 1):
            mention = _mention_html(u["id"], u["name"])
            uname = f" ({u['username']})" if u.get("username") else ""
            lines.append(
                f"{idx}. {mention}{uname}\n"
                f"   📸 Bugun: <b>{u['count']}/2</b> ❌\n"
            )
        footer = (
            "\n➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "❗️ <b>OGOHLANTIRISH!</b>\n"
            "Zudlik bilan reklama tarqatib, screenshot yuboring!\n\n"
            f"📌 Reklama manbasi:\n{CHANNEL_LINK}\n\n"
            f"⏰ Keyingi tekshiruv: {next_check}"
        )
        try:
            await _send_long_html(bot, GROUP_ID, header + "\n".join(lines) + footer)
        except TelegramForbiddenError:
            logger.error("Botga guruhda yozish taqiqlangan!")
        except Exception as e:
            logger.error(f"Hisobot yuborishda xato: {e}")
    else:
        with contextlib.suppress(Exception):
            await bot.send_message(
                GROUP_ID,
                f"🏆 <b>AJOYIB NATIJA! ({current_time})</b>\n\n"
                "✅ <b>BARCHA XODIMLAR REJANI BAJARDI!</b>\n\n"
                f"👥 Faol xodimlar: {total} ta\n"
                "📸 Hamma 2/2 screenshot yubordi\n"
                f"📊 Bajarilish: 100%\n\n"
                "👏 Hamma jamoaga rahmat!\n"
                "💪 Shu tarzda davom eting!",
                parse_mode="HTML"
            )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin statistika - {current_time}</b>\n\n"
                f"👥 Jami faol: {total}\n"
                f"✅ Bajargan: {completed}\n"
                f"❌ Bajarmagan: {len(debtors)}\n"
                f"📈 Foiz: {percent}%",
                parse_mode="HTML"
            )


# =================== SCHEDULER ===================

def setup_scheduler(bot: Bot):
    global SCHEDULER
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan! Scheduler ishga tushmaydi.")
        return None

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(
        check_screenshots, CronTrigger(hour=9, minute=30),
        args=[bot], id="morning_check",
        replace_existing=True, max_instances=1,
        coalesce=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        check_screenshots, CronTrigger(hour=15, minute=0),
        args=[bot], id="afternoon_check",
        replace_existing=True, max_instances=1,
        coalesce=True, misfire_grace_time=300,
    )
    scheduler.start()
    SCHEDULER = scheduler
    logger.info("Scheduler ishga tushdi (09:30, 15:00)")
    return scheduler


# =================== ADMIN BUYRUQLARI ===================

@router.message(Command("reklama_tekshir"))
async def manual_check(message: Message, bot: Bot):
    if not is_admin_in_group(message):
        return
    await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    with contextlib.suppress(Exception):
        await message.delete()


@router.message(Command("reklama_stat"))
async def show_stats(message: Message):
    if not is_admin_in_group(message):
        return

    try:
        active_users = await get_all_active()
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    total = len(active_users)
    completed = sum(
        1 for u in active_users
        if get_screenshot_count(int(u["id"])) >= 2
    )

    text = (
        f"📊 <b>Statistika - {now_tz().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Faol xodimlar: {total}\n"
        f"✅ Bugun bajarganlar: {completed}\n"
        f"❌ Bajarmaganlar: {total - completed}\n"
        f"📈 Bajarilish: {int(completed / total * 100) if total > 0 else 0}%"
    )
    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(30)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("reklama_users"))
async def list_users(message: Message):
    if not is_admin_in_group(message):
        return

    try:
        active_users = await get_all_active()
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    if not active_users:
        await message.answer("❌ Faol foydalanuvchilar yo'q")
        return

    text = "👥 <b>Faol xodimlar ro'yxati:</b>\n\n"
    for u in active_users[:25]:
        try:
            count = get_screenshot_count(int(u["id"]))
        except Exception:
            count = 0
        emoji = "✅" if count >= 2 else "⚠️"
        uname = f" {u['username']}" if u.get("username") else ""
        text += (
            f"{emoji} <b>{u['name']}</b>{uname}\n"
            f"   📸 {count}/2 screenshot\n\n"
        )
    if len(active_users) > 25:
        text += f"\n<i>... va yana {len(active_users) - 25} ta xodim</i>"

    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(90)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("reklama_help"))
async def help_command(message: Message):
    if not is_admin_in_group(message):
        return

    text = (
        "📋 <b>Reklama Nazorat - Yordam</b>\n\n"
        "<b>Xodimlar uchun:</b>\n"
        "• Guruhga screenshot yuboring\n"
        "• Bot avtomatik hisoblaydi\n"
        "• Har kuni kamida 2 ta screenshot kerak\n\n"
        "<b>Admin buyruqlari (faqat guruhda):</b>\n"
        "/start_register — Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir — Qo'lda tekshirish\n"
        "/reklama_stat — Statistika\n"
        "/reklama_users — Xodimlar ro'yxati\n"
        "/reklama_help — Bu yordam\n\n"
        "<b>Avtomatik:</b>\n"
        "⏰ 09:30 — Ertalabki tekshiruv\n"
        "⏰ 15:00 — Kunduzi tekshiruv"
    )
    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(30)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("debug_reklama"))
async def debug_command(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Chat type: {message.chat.type}\n"
        f"ENV GROUP_ID: <code>{GROUP_ID}</code>\n"
        f"Match: {'✅' if message.chat.id == GROUP_ID else '❌'}",
        parse_mode="HTML"
    )
