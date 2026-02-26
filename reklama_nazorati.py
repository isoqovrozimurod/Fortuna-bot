"""
Reklama Nazorat Tizimi - Google Sheets versiyasi
Guruhga har qanday xabar yuborganda → Sub-adminlarga ro'yxatga oladi
Rasm/fayl = screenshot hisoblanadi
Har kuni 09:30 va 15:00 da tekshirish
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
    return now_tz().strftime("%Y-%m-%d")

GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "Sub-adminlar"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCHEDULER: AsyncIOScheduler | None = None

# Kunlik screenshot hisob — xotirada (restart da tozalanadi)
_screenshots: dict[int, dict] = {}


# =================== SHEETS =====================

_gc: gspread.Client | None = None


def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def _get_ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SUBADMIN_SHEET)
    # Sarlavha yo'q bo'lsa qo'shamiz
    if not ws.row_values(1):
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
                       "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
    return ws


# =================== FOYDALANUVCHI OPERATSIYALARI =====================

def _find_row_sync(user_id: int) -> int | None:
    ws = _get_ws()
    for i, val in enumerate(ws.col_values(2), start=1):
        if str(val).strip() == str(user_id):
            return i
    return None


def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    """True = yangi qo'shildi, False = mavjud yangilandi"""
    ws = _get_ws()
    row_idx = _find_row_sync(user_id)

    parts = (full_name or "").split(" ", 1)
    ism = parts[0]
    familiya = parts[1] if len(parts) > 1 else ""
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")

    if row_idx is not None:
        # Mavjud — ma'lumotlarni yangilaymiz (ID o'zgarmaydi)
        ws.update_cell(row_idx, 3, uname)
        ws.update_cell(row_idx, 4, ism)
        ws.update_cell(row_idx, 5, familiya)
        ws.update_cell(row_idx, 8, "Faol")
        return False

    # Yangi foydalanuvchi
    # 1. Avval bo'sh qatorlarni o'chirib T/r tartiblaymiz
    _cleanup_sync(ws)

    # 2. T/r: eng katta mavjud raqam + 1
    all_vals = ws.get_all_values()
    valid_ids = [r[1].strip() for r in all_vals[1:] if len(r) > 1 and r[1].strip()]
    tr = len(valid_ids) + 1

    ws.append_row([str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"],
                  value_input_option="RAW")
    return True


def _cleanup_sync(ws: gspread.Worksheet) -> None:
    """Bo'sh qatorlarni o'chiradi, T/r ni tartiblab qayta yozadi"""
    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return

    valid_rows = [
        row for row in all_rows[1:]
        if len(row) > 1 and str(row[1]).strip()
    ]
    if not valid_rows:
        return

    for i, row in enumerate(valid_rows, start=1):
        while len(row) < 8:
            row.append("")
        row[0] = str(i)

    total = len(all_rows)
    count = len(valid_rows)

    ws.update(f"A2:H{count + 1}", valid_rows, value_input_option="RAW")

    if total > count + 1:
        ws.update(f"A{count + 2}:H{total}",
                  [[""] * 8] * (total - count - 1),
                  value_input_option="RAW")


def _set_status_sync(user_id: int, status: str) -> None:
    row_idx = _find_row_sync(user_id)
    if row_idx:
        _get_ws().update_cell(row_idx, 8, status)


def _get_all_active_sync() -> list[dict]:
    ws = _get_ws()
    result = []
    for r in ws.get_all_records():
        if str(r.get("Holati", "")).strip() == "Faol" and str(r.get("Telegram ID", "")).strip():
            result.append({
                "id": str(r.get("Telegram ID", "")),
                "name": f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip(),
                "username": str(r.get("Username", "")),
            })
    return result


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _register_sync, user_id, full_name, username)


async def set_status(user_id: int, status: str) -> None:
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


# =================== GURUH HANDLERLARI ===================

def is_group_msg(message: Message) -> bool:
    return (
        message.from_user is not None
        and not message.from_user.is_bot
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


def is_admin_in_group(message: Message) -> bool:
    return is_group_msg(message) and message.from_user.id == ADMIN_ID


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    if user.is_bot:
        return
    try:
        await register_user(user.id, user.full_name or "", user.username or "")
        logger.info(f"Guruhga qo'shildi va ro'yxatga olindi: {user.full_name}")
    except Exception as e:
        logger.error(f"Qo'shilganda xato: {e}")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    if user.is_bot:
        return
    try:
        await set_status(user.id, "Chiqib ketdi")
    except Exception as e:
        logger.error(f"Chiqib ketganda xato: {e}")


@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    """Guruhga rasm tashlanganda — screenshot hisoblanadi + ro'yxatga olinadi"""
    if not is_group_msg(message):
        return
    user = message.from_user
    try:
        await register_user(user.id, user.full_name or "", user.username or "")
    except Exception as e:
        logger.error(f"Ro'yxatga olishda xato: {e}")
        return

    count = increment_screenshot(user.id)
    emoji = "📸" if count == 1 else ("✅" if count == 2 else "🎉")
    status = (
        "Birinchi screenshot qabul qilindi!"
        if count == 1 else
        "Ajoyib! Kunlik rejangiz bajarildi!"
        if count == 2 else
        f"{count}-screenshot qabul qilindi!"
    )
    with contextlib.suppress(Exception):
        await message.reply(
            f"{emoji} <b>Qabul qilindi!</b>\n"
            f"👤 {user.full_name}\n"
            f"📊 Bugungi natija: <b>{count}/2</b>\n"
            f"💬 {status}",
            parse_mode="HTML"
        )


@router.message(F.chat.id == GROUP_ID, F.document)
async def document_received(message: Message):
    """Rasm fayl sifatida yuborilsa ham hisoblanadi"""
    if not is_group_msg(message):
        return
    doc = message.document
    if not doc or not doc.mime_type or not doc.mime_type.startswith("image/"):
        # Rasm emas — faqat ro'yxatga olamiz
        try:
            await register_user(
                message.from_user.id,
                message.from_user.full_name or "",
                message.from_user.username or ""
            )
        except Exception:
            pass
        return

    # Rasm fayli — screenshot hisoblaymiz
    user = message.from_user
    try:
        await register_user(user.id, user.full_name or "", user.username or "")
    except Exception as e:
        logger.error(f"Ro'yxatga olishda xato: {e}")
        return

    count = increment_screenshot(user.id)
    emoji = "📸" if count == 1 else ("✅" if count == 2 else "🎉")
    with contextlib.suppress(Exception):
        await message.reply(
            f"{emoji} <b>Qabul qilindi!</b>\n"
            f"👤 {user.full_name}\n"
            f"📊 Bugungi natija: <b>{count}/2</b>",
            parse_mode="HTML"
        )


@router.message(F.chat.id == GROUP_ID, ~F.photo, ~F.document)
async def any_message_received(message: Message):
    """Matn yoki boshqa xabar — faqat ro'yxatga olamiz"""
    if not is_group_msg(message):
        return
    try:
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or ""
        )
    except Exception as e:
        logger.warning(f"Ro'yxatga olishda xato: {e}")


# =================== RO'YXATDAN O'TKAZISH (qo'lda) ===================

@router.message(Command("start_register"))
async def start_registration_process(message: Message):
    if not is_admin_in_group(message):
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ MEN SHU YERDAMAN",
            callback_data="register_me"
        )]
    ])
    await message.bot.send_message(
        GROUP_ID,
        "📢 <b>DIQQAT, GURUH A'ZOLARI!</b>\n\n"
        "Barcha xodimlar quyidagi tugmani bosishi SHART!\n\n"
        "⚠️ Kim tugmani bosmasa hisobotda ko'rinmaydi.\n\n"
        "👇 <b>Hoziroq bosing:</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    user = callback.from_user
    try:
        is_new = await register_user(user.id, user.full_name or "", user.username or "")
        await callback.answer(
            "✅ Ro'yxatga olindingiz!" if is_new else "✅ Ma'lumotlar yangilandi!",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Ro'yxatdan o'tkazishda xato: {e}")
        await callback.answer("❌ Xato, qayta urinib ko'ring.", show_alert=True)


# =================== NAZORAT HISOBOTI ===================

def _mention(user_id: str, name: str) -> str:
    safe = name.replace("<", "").replace(">", "")
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
        logger.error("GROUP_ID sozlanmagan!")
        return

    try:
        active = await get_all_active()
    except Exception as e:
        logger.error(f"Active userlarni olishda xato: {e}")
        return

    if not active:
        logger.warning("Bazada faol xodimlar yo'q!")
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ Sub-adminlar bazasida faol xodim yo'q!\n"
                    "Guruhga /start_register yuboring.",
                )
        return

    debtors, completed = [], 0
    for u in active:
        try:
            uid = int(u["id"])
        except (ValueError, TypeError):
            continue
        cnt = get_screenshot_count(uid)
        if cnt >= 2:
            completed += 1
        else:
            debtors.append({**u, "count": cnt})

    total = len(active)
    time_str = now_tz().strftime("%H:%M")
    h, m = now_tz().hour, now_tz().minute
    next_check = (
        "Bugun 09:30" if h < 9 or (h == 9 and m < 30)
        else "Bugun 15:00" if h < 15
        else "Ertaga 09:30"
    )

    if debtors:
        lines = []
        for i, u in enumerate(debtors, 1):
            uname = f" ({u['username']})" if u.get("username") else ""
            lines.append(
                f"{i}. {_mention(u['id'], u['name'])}{uname}\n"
                f"   📸 Bugun: <b>{u['count']}/2</b> ❌\n"
            )
        text = (
            f"🚨 <b>NAZORAT HISOBOTI ({time_str})</b>\n\n"
            f"👥 Faol xodimlar: {total}\n"
            f"✅ Bajarganlar: {completed}\n"
            f"❌ Bajarmaganlar: {len(debtors)}\n"
            f"📊 Bajarilish: {int(completed / total * 100)}%\n\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            "👇 <b>BAJARMAGAN XODIMLAR:</b>\n\n"
            + "\n".join(lines)
            + f"\n➖➖➖➖➖➖➖➖➖➖\n"
            f"❗ Zudlik bilan reklama tarqatib screenshot yuboring!\n"
            f"📌 {CHANNEL_LINK}\n"
            f"⏰ Keyingi tekshiruv: {next_check}"
        )
        try:
            await _send_long(bot, GROUP_ID, text)
        except TelegramForbiddenError:
            logger.error("Botga guruhda yozish taqiqlangan!")
        except Exception as e:
            logger.error(f"Hisobot yuborishda xato: {e}")
    else:
        with contextlib.suppress(Exception):
            await bot.send_message(
                GROUP_ID,
                f"🏆 <b>AJOYIB! ({time_str})</b>\n\n"
                "✅ Barcha xodimlar rejani bajardi!\n\n"
                f"👥 {total} ta xodim — barchasi 2/2 screenshot yubordi\n"
                "👏 Rahmat!",
                parse_mode="HTML"
            )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin — {time_str}</b>\n\n"
                f"👥 Faol: {total}\n"
                f"✅ Bajargan: {completed}\n"
                f"❌ Bajarmagan: {len(debtors)}\n"
                f"📈 {int(completed / total * 100)}%",
                parse_mode="HTML"
            )


# =================== SCHEDULER ===================

def setup_scheduler(bot: Bot) -> AsyncIOScheduler | None:
    global SCHEDULER
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan!")
        return None

    s = AsyncIOScheduler(timezone="Asia/Tashkent")
    s.add_job(check_screenshots, CronTrigger(hour=9, minute=30),
              args=[bot], id="morning", replace_existing=True,
              max_instances=1, coalesce=True, misfire_grace_time=300)
    s.add_job(check_screenshots, CronTrigger(hour=15, minute=0),
              args=[bot], id="afternoon", replace_existing=True,
              max_instances=1, coalesce=True, misfire_grace_time=300)
    s.start()
    SCHEDULER = s
    logger.info("Scheduler: 09:30, 15:00")
    return s


# =================== ADMIN BUYRUQLARI ===================

@router.message(Command("reklama_tekshir"))
async def manual_check(message: Message, bot: Bot):
    if not is_admin_in_group(message):
        return
    msg = await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    with contextlib.suppress(Exception):
        await msg.delete()
        await message.delete()


@router.message(Command("reklama_stat"))
async def show_stats(message: Message):
    if not is_admin_in_group(message):
        return
    try:
        active = await get_all_active()
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    total = len(active)
    completed = sum(1 for u in active if get_screenshot_count(int(u["id"])) >= 2)
    sent = await message.answer(
        f"📊 <b>Statistika — {now_tz().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Faol xodimlar: {total}\n"
        f"✅ Bugun bajarganlar: {completed}\n"
        f"❌ Bajarmaganlar: {total - completed}\n"
        f"📈 {int(completed / total * 100) if total else 0}%",
        parse_mode="HTML"
    )
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
        active = await get_all_active()
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    if not active:
        await message.answer("❌ Faol xodimlar yo'q")
        return

    text = "👥 <b>Faol xodimlar:</b>\n\n"
    for u in active[:25]:
        cnt = get_screenshot_count(int(u["id"]))
        emoji = "✅" if cnt >= 2 else "⚠️"
        uname = f" {u['username']}" if u.get("username") else ""
        text += f"{emoji} <b>{u['name']}</b>{uname} — 📸 {cnt}/2\n"

    if len(active) > 25:
        text += f"\n<i>+{len(active) - 25} ta xodim</i>"

    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(60)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("reklama_help"))
async def help_command(message: Message):
    if not is_admin_in_group(message):
        return
    sent = await message.answer(
        "📋 <b>Reklama Nazorat — Yordam</b>\n\n"
        "<b>Xodimlar:</b>\n"
        "• Guruhga rasm yuboring — bot avtomatik hisoblaydi\n"
        "• Har kuni kamida 2 ta rasm kerak\n\n"
        "<b>Admin buyruqlari (guruhda):</b>\n"
        "/start_register — Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir — Qo'lda tekshirish\n"
        "/reklama_stat — Statistika\n"
        "/reklama_users — Xodimlar ro'yxati\n\n"
        "<b>Avtomatik:</b> 09:30 va 15:00",
        parse_mode="HTML"
    )
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
        f"ENV GROUP_ID: <code>{GROUP_ID}</code>\n"
        f"Match: {'✅' if message.chat.id == GROUP_ID else '❌'}\n"
        f"Xotiradagi xodimlar: {len(_screenshots)}",
        parse_mode="HTML"
    )
