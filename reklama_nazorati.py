"""
Reklama Nazorat Tizimi - Upstash Redis versiya
Har kuni 09:30 va 15:00 da screenshot tekshirish
Ma'lumotlar Upstash Redis da saqlanadi (deploy da o'chmaydi)
"""

import os
import json
import asyncio
import logging
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

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
from upstash_redis import Redis

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
    logger.error("❌ GROUP_ID yoki ADMIN_ID noto'g'ri formatda!")

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"

UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
if not UPSTASH_URL or not UPSTASH_TOKEN:
    logger.error("❌ UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN topilmadi!")

redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# Scheduler global saqlansin (GC bo‘lib ketmasin)
SCHEDULER: AsyncIOScheduler | None = None

# =================== REDIS YORDAMCHI FUNKSIYALAR ===================

def _to_obj(val):
    """Upstashdan kelgan qiymatni Python obyektga aylantirish"""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="ignore")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val

def redis_get(key: str):
    try:
        return _to_obj(redis.get(key))
    except Exception as e:
        logger.error(f"Redis get xato ({key}): {e}")
        return None

def redis_set(key: str, value) -> bool:
    try:
        redis.set(key, json.dumps(value, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Redis set xato ({key}): {e}")
        return False

def get_all_user_ids() -> list[str]:
    try:
        val = redis.get("user_ids")
        obj = _to_obj(val)
        return obj if isinstance(obj, list) else []
    except Exception as e:
        logger.error(f"user_ids o'qishda xato: {e}")
        return []

def add_user_id(user_id: str):
    # ⚠️ Bu joy race condition bo‘lishi mumkin (bir paytning o‘zida 2 user)
    # Ammo amaliyotda kam. Xohlasangiz keyin set (SADD/SMEMBERS)ga o‘tkazamiz.
    ids = get_all_user_ids()
    if user_id not in ids:
        ids.append(user_id)
        redis_set("user_ids", ids)

# =================== ADMIN TEKSHIRUVI ===================

def is_admin_in_group(message: Message) -> bool:
    return (
        message.from_user
        and message.from_user.id == ADMIN_ID
        and message.chat.id == GROUP_ID
        and ADMIN_ID != 0
        and GROUP_ID != 0
    )

# =================== FOYDALANUVCHI BOSHQARUVI ===================

def register_user_in_db(user) -> bool:
    """
    Foydalanuvchini bazaga qo'shish/yangilash
    Returns: True - yangi, False - mavjud
    """
    user_id = str(user.id)
    today = today_str()
    key = f"user:{user_id}"

    existing = redis_get(key)

    if existing is None or not isinstance(existing, dict):
        redis_set(key, {
            "fullname": user.full_name,
            "username": user.username or "mavjud_emas",
            "registered_at": today,
            "status": "active",
            "last_seen": today
        })
        add_user_id(user_id)
        logger.info(f"✅ Yangi foydalanuvchi: {user.full_name} (ID: {user_id})")
        return True

    # MUHIM: qaytgan userni ham active qilamiz
    existing["fullname"] = user.full_name
    existing["username"] = user.username or "mavjud_emas"
    existing["last_seen"] = today
    existing["status"] = "active"
    existing.pop("left_date", None)
    redis_set(key, existing)
    return False

def get_user(user_id: str):
    obj = redis_get(f"user:{user_id}")
    return obj if isinstance(obj, dict) else None

def set_user_status(user_id: str, status: str):
    user = get_user(user_id)
    if user:
        user["status"] = status
        if status == "left":
            user["left_date"] = today_str()
        redis_set(f"user:{user_id}", user)

def get_screenshot_count(user_id: str) -> int:
    today = today_str()
    data = redis_get(f"screenshot:{user_id}")
    if not isinstance(data, dict):
        return 0
    if data.get("date") != today:
        return 0
    return int(data.get("count", 0) or 0)

def increment_screenshot(user_id: str) -> int:
    today = today_str()
    key = f"screenshot:{user_id}"
    data = redis_get(key)

    if not isinstance(data, dict) or data.get("date") != today:
        redis_set(key, {"date": today, "count": 1})
        return 1

    new_count = int(data.get("count", 0) or 0) + 1
    redis_set(key, {"date": today, "count": new_count})
    return new_count

# =================== RO'YXATDAN O'TKAZISH ===================

@router.message(Command("start_register"))
async def start_registration_process(message: Message):
    if not is_admin_in_group(message):
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ MEN SHU YERDAMAN (Tasdiqlash)", callback_data="register_me")]
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
    is_new = register_user_in_db(user)
    await callback.answer(
        "✅ Siz ro'yxatga olindingiz! Rahmat." if is_new else "✅ Ma'lumotlar yangilandi! Rahmat.",
        show_alert=is_new
    )

# =================== AVTOMATIK TUTIB OLISH ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    register_user_in_db(user)
    logger.info(f"👋 Guruhga qo'shildi: {user.full_name}")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    user = event.new_chat_member.user
    set_user_status(str(user.id), "left")
    logger.info(f"👋 Guruhdan chiqdi: {user.full_name}")

@router.message(F.chat.id == GROUP_ID)
async def capture_any_activity(message: Message):
    """Guruhdagi har qanday aktiv userni bazada yangilab borish"""
    if not message.from_user or message.from_user.is_bot:
        return
    register_user_in_db(message.from_user)

# =================== SCREENSHOT QABUL QILISH ===================

async def _handle_screenshot(message: Message, user):
    user_id = str(user.id)
    register_user_in_db(user)
    count = increment_screenshot(user_id)

    if count == 1:
        emoji, status = "📸", "Birinchi screenshot qabul qilindi!"
    elif count == 2:
        emoji, status = "✅", "Ajoyib! Kunlik rejangiz bajarildi!"
    else:
        emoji, status = "🎉", f"Zo'r! {count}-screenshot qabul qilindi!"

    response_text = (
        f"{emoji} <b>Qabul qilindi!</b>\n"
        f"👤 {user.full_name}\n"
        f"📊 Bugungi natija: <b>{count}/2 screenshot</b>\n"
        f"💬 {status}"
    )

    with contextlib.suppress(Exception):
        await message.reply(response_text, parse_mode="HTML")

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    user = message.from_user
    if not user or user.is_bot:
        return
    await _handle_screenshot(message, user)

@router.message(F.chat.id == GROUP_ID, F.document)
async def document_received(message: Message):
    """Screenshotni file qilib yuborishsa ham hisoblansin"""
    user = message.from_user
    if not user or user.is_bot:
        return
    doc = message.document
    if not doc or not doc.mime_type:
        return
    if doc.mime_type.startswith("image/"):
        await _handle_screenshot(message, user)

# =================== NAZORAT HISOBOTI ===================

def _mention_html(user_id: str, fullname: str) -> str:
    # Telegram HTML mention
    safe_name = fullname.replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'

async def _send_long_html(bot: Bot, chat_id: int, text: str):
    """4096 limitdan oshmasligi uchun bo‘lib yuborish"""
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
        logger.error("❌ GROUP_ID sozlanmagan!")
        return

    user_ids = get_all_user_ids()
    total_users = 0
    debtors = []
    completed = 0

    for user_id in user_ids:
        user_info = get_user(user_id)
        if not user_info or user_info.get("status") != "active":
            continue

        total_users += 1
        count = get_screenshot_count(user_id)

        if count < 2:
            debtors.append({
                "id": user_id,
                "name": user_info.get("fullname", "Noma'lum"),
                "username": user_info.get("username", "mavjud_emas"),
                "count": count
            })
        else:
            completed += 1

    current_time = now_tz().strftime("%H:%M")

    if total_users == 0:
        logger.warning("⚠️ Bazada faol foydalanuvchilar yo'q!")
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ Reklama nazorat bazasida faol user yo'q!\n/start_register buyrug'ini yuboring."
                )
        return

    # Keyingi tekshiruv matni
    h = now_tz().hour
    m = now_tz().minute
    if h < 9 or (h == 9 and m < 30):
        next_check = "Bugun 09:30 da"
    elif h < 15:
        next_check = "Bugun 15:00 da"
    else:
        next_check = "Ertaga 09:30 da"

    if debtors:
        header = (
            f"🚨 <b>NAZORAT HISOBOTI ({current_time})</b>\n\n"
            f"👥 Faol xodimlar: {total_users} ta\n"
            f"✅ Bajarganlar: {completed} ta\n"
            f"❌ Bajarmaganlar: {len(debtors)} ta\n"
            f"📊 Bajarilish: {int(completed / total_users * 100)}%\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "👇 <b>REKLAMA PLANINI BAJARMAGAN XODIMLAR:</b>\n\n"
        )

        lines = []
        for idx, u in enumerate(debtors, 1):
            mention = _mention_html(u["id"], u["name"])
            uname = f" (@{u['username']})" if u["username"] != "mavjud_emas" else ""
            lines.append(
                f"{idx}. <b>{mention}</b>{uname}\n"
                f"   📸 Bugun: <b>{u['count']}/2</b> ❌\n"
            )

        footer = (
            "\n➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "❗️ <b>OGOHLANTIRISH!</b>\n"
            "Zudlik bilan reklama tarqatib, screenshot yuboring!\n\n"
            f"📌 Reklama manbasi:\n{CHANNEL_LINK}\n\n"
            f"⏰ Keyingi tekshiruv: {next_check}"
        )

        big_text = header + "\n".join(lines) + footer

        try:
            await _send_long_html(bot, GROUP_ID, big_text)
            logger.info(f"✅ Ogohlantirish yuborildi: {len(debtors)} ta qarzdor")
        except TelegramForbiddenError:
            logger.error("❌ Botga guruhda yozish taqiqlangan!")
        except TelegramBadRequest as e:
            logger.error(f"❌ Xabar yuborishda xato: {e}")
        except Exception as e:
            logger.error(f"❌ Noma'lum xato: {e}")
    else:
        success_text = (
            f"🏆 <b>AJOYIB NATIJA! ({current_time})</b>\n\n"
            "✅ <b>BARCHA XODIMLAR REJANI BAJARDI!</b>\n\n"
            f"👥 Faol xodimlar: {total_users} ta\n"
            "📸 Hamma 2/2 screenshot yubordi\n"
            "📊 Bajarilish: 100%\n\n"
            "👏 Hamma jamoaga rahmat!\n"
            "💪 Shu tarzda davom eting!"
        )
        with contextlib.suppress(Exception):
            await bot.send_message(GROUP_ID, success_text, parse_mode="HTML")

    # Admin uchun qisqa statistika
    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin statistika - {current_time}</b>\n\n"
                f"👥 Jami faol: {total_users}\n"
                f"✅ Bajargan: {completed}\n"
                f"❌ Bajarmagan: {len(debtors)}\n"
                f"📈 Foiz: {int(completed / total_users * 100)}%",
                parse_mode="HTML"
            )

# =================== SCHEDULER ===================

def setup_scheduler(bot: Bot):
    global SCHEDULER
    if GROUP_ID == 0:
        logger.error("❌ GROUP_ID sozlanmagan! Scheduler ishga tushmaydi.")
        return None

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    scheduler.add_job(
        check_screenshots,
        CronTrigger(hour=9, minute=30),
        args=[bot],
        id="morning_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        check_screenshots,
        CronTrigger(hour=15, minute=0),
        args=[bot],
        id="afternoon_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    SCHEDULER = scheduler
    logger.info("✅ Scheduler ishga tushdi (09:30, 15:00 tekshiruv)")
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

    user_ids = get_all_user_ids()
    active_users = 0
    completed = 0

    for user_id in user_ids:
        user_info = get_user(user_id)
        if not user_info or user_info.get("status") != "active":
            continue
        active_users += 1
        if get_screenshot_count(user_id) >= 2:
            completed += 1

    text = (
        f"📊 <b>Statistika - {now_tz().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Faol foydalanuvchilar: {active_users}\n"
        f"✅ Bugun bajarganlar: {completed}\n"
        f"❌ Bajarmaganlar: {active_users - completed}\n"
        f"📈 Bajarilish: {int(completed / active_users * 100) if active_users > 0 else 0}%"
    )

    sent = await message.answer(text, parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()

    await asyncio.sleep(30)
    with contextlib.suppress(Exception):
        await sent.delete()

@router.message(Command("debug_reklama"))
async def debug_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        f"🔧 <b>Debug ma'lumotlar:</b>\n\n"
        f"👤 Sizning ID: <code>{message.from_user.id}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>\n\n"
        f"⚙️ Env variables:\n"
        f"ADMIN_ID: <code>{ADMIN_ID}</code>\n"
        f"GROUP_ID: <code>{GROUP_ID}</code>\n\n"
        f"{('✅ ADMIN_ID togri' if message.from_user.id == ADMIN_ID else '❌ ADMIN_ID notogri')}\n"
        f"{('✅ GROUP_ID sozlangan' if GROUP_ID != 0 else '❌ GROUP_ID sozlanmagan')}",
        parse_mode="HTML"
    )
