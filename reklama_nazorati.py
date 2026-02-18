"""
Reklama Nazorat Tizimi - Upstash Redis versiya
Har kuni 09:30 va 15:00 da screenshot tekshirish
Ma'lumotlar Upstash Redis da saqlanadi (deploy da o'chmaydi)
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from upstash_redis import Redis

# =================== SOZLAMALAR ===================

router = Router()
logger = logging.getLogger(__name__)

try:
    GROUP_ID = int(os.getenv("GROUP_ID", "0"))
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (ValueError, TypeError):
    GROUP_ID = 0
    ADMIN_ID = 0
    logger.error("❌ GROUP_ID yoki ADMIN_ID noto'g'ri formatda!")

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"

# Redis ulanish
redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

# =================== REDIS YORDAMCHI FUNKSIYALAR ===================

def get_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def redis_get(key: str):
    """Redis dan JSON o'qish"""
    try:
        val = redis.get(key)
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        return json.loads(val)
    except Exception as e:
        logger.error(f"Redis get xato ({key}): {e}")
        return None


def redis_set(key: str, value) -> bool:
    """Redis ga JSON saqlash"""
    try:
        redis.set(key, json.dumps(value, ensure_ascii=False))
        return True
    except Exception as e:
        logger.error(f"Redis set xato ({key}): {e}")
        return False


def get_all_user_ids() -> list:
    """Barcha user IDlarini olish"""
    try:
        val = redis.get("user_ids")
        if val is None:
            return []
        if isinstance(val, list):
            return val
        return json.loads(val)
    except Exception as e:
        logger.error(f"user_ids o'qishda xato: {e}")
        return []


def add_user_id(user_id: str):
    """User IDni ro'yxatga qo'shish"""
    ids = get_all_user_ids()
    if user_id not in ids:
        ids.append(user_id)
        redis.set("user_ids", json.dumps(ids))


# =================== FOYDALANUVCHI BOSHQARUVI ===================

def register_user_in_db(user) -> bool:
    """
    Foydalanuvchini bazaga qo'shish/yangilash
    Returns: True - yangi, False - mavjud
    """
    user_id = str(user.id)
    today = get_today()
    key = f"user:{user_id}"

    existing = redis_get(key)

    if existing is None:
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
    else:
        existing["fullname"] = user.full_name
        existing["username"] = user.username or "mavjud_emas"
        existing["last_seen"] = today
        redis_set(key, existing)
        return False


def get_user(user_id: str):
    return redis_get(f"user:{user_id}")


def set_user_status(user_id: str, status: str):
    user = get_user(user_id)
    if user:
        user["status"] = status
        if status == "left":
            user["left_date"] = get_today()
        redis_set(f"user:{user_id}", user)


def get_screenshot_count(user_id: str) -> int:
    today = get_today()
    data = redis_get(f"screenshot:{user_id}")
    if data is None:
        return 0
    if data.get("date") != today:
        return 0
    return data.get("count", 0)


def increment_screenshot(user_id: str) -> int:
    today = get_today()
    key = f"screenshot:{user_id}"
    data = redis_get(key)

    if data is None or data.get("date") != today:
        redis_set(key, {"date": today, "count": 1})
        return 1

    new_count = data["count"] + 1
    redis_set(key, {"date": today, "count": new_count})
    return new_count


# =================== ADMIN TEKSHIRUVI ===================

def is_admin_in_group(message: Message) -> bool:
    return (
        message.from_user.id == ADMIN_ID and
        message.chat.id == GROUP_ID and
        ADMIN_ID != 0 and
        GROUP_ID != 0
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

    try:
        await message.delete()
    except:
        pass


@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    user = callback.from_user
    is_new = register_user_in_db(user)

    if is_new:
        await callback.answer("✅ Siz ro'yxatga olindingiz! Rahmat.", show_alert=True)
    else:
        await callback.answer("✅ Ma'lumotlar yangilandi! Rahmat.", show_alert=False)


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


@router.message(F.chat.id == GROUP_ID, ~F.photo)
async def capture_text_messages(message: Message):
    """Guruhda yozgan har kimni sezdirmasdan ro'yxatga olish"""
    if message.from_user and not message.from_user.is_bot:
        register_user_in_db(message.from_user)


# =================== SCREENSHOT QABUL QILISH ===================

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    user = message.from_user
    if user.is_bot:
        return

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

    try:
        await message.reply(response_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Javob yuborishda xato: {e}")


# =================== NAZORAT HISOBOTI ===================

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
                "name": user_info["fullname"],
                "username": user_info["username"],
                "count": count
            })
        else:
            completed += 1

    current_time = datetime.now().strftime("%H:%M")

    if total_users == 0:
        logger.warning("⚠️ Bazada foydalanuvchilar yo'q!")
        if ADMIN_ID:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ Reklama nazorat bazasida hech kim yo'q!\n"
                    "/start_register buyrug'ini yuboring."
                )
            except:
                pass
        return

    if debtors:
        current_hour = datetime.now().hour
        current_minute = datetime.now().minute
        if current_hour < 9 or (current_hour == 9 and current_minute < 30):
            next_check = "Bugun 09:30 da"
        elif current_hour < 15:
            next_check = "Bugun 15:00 da"
        else:
            next_check = "Ertaga 09:30 da"

        text = (
            f"🚨 <b>NAZORAT HISOBOTI ({current_time})</b>\n\n"
            f"👥 Faol xodimlar: {total_users} ta\n"
            f"✅ Bajarganlar: {completed} ta\n"
            f"❌ Bajarmaganlar: {len(debtors)} ta\n"
            f"📊 Bajarilish: {int(completed / total_users * 100)}%\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "👇 <b>REKLAMA PLANINI BAJARMAGAN XODIMLAR:</b>\n\n"
        )

        for idx, user in enumerate(debtors, 1):
            mention = f"@{user['username']}" if user['username'] != "mavjud_emas" else user['name']
            text += f"{idx}. <b>{user['name']}</b> ({mention})\n   📸 Bugun: {user['count']}/2 ❌\n\n"

        text += (
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "❗️ <b>OGOHLANTIRISH!</b>\n"
            "Zudlik bilan reklama tarqatib, screenshot yuboring!\n\n"
            f"📌 Reklama manbasi:\n{CHANNEL_LINK}\n\n"
            f"⏰ Keyingi tekshiruv: {next_check}"
        )

        try:
            await bot.send_message(GROUP_ID, text, parse_mode="HTML")
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
        try:
            await bot.send_message(GROUP_ID, success_text, parse_mode="HTML")
            logger.info(f"✅ Muvaffaqiyat xabari: {total_users} ta xodim")
        except Exception as e:
            logger.error(f"❌ Xabar yuborishda xato: {e}")

    # Admin uchun qisqa statistika
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin statistika - {current_time}</b>\n\n"
                f"👥 Jami faol: {total_users}\n"
                f"✅ Bajargan: {completed}\n"
                f"❌ Bajarmagan: {len(debtors)}\n"
                f"📈 Foiz: {int(completed / total_users * 100)}%",
                parse_mode="HTML"
            )
        except:
            pass


# =================== SCHEDULER ===================

def setup_scheduler(bot: Bot):
    if GROUP_ID == 0:
        logger.error("❌ GROUP_ID sozlanmagan! Scheduler ishga tushmaydi.")
        return None

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    scheduler.add_job(
        check_screenshots,
        CronTrigger(hour=9, minute=30),
        args=[bot],
        id="morning_check",
        replace_existing=True
    )

    scheduler.add_job(
        check_screenshots,
        CronTrigger(hour=15, minute=0),
        args=[bot],
        id="afternoon_check",
        replace_existing=True
    )

    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi (09:30, 15:00 tekshiruv)")
    return scheduler


# =================== ADMIN BUYRUQLARI ===================

@router.message(Command("reklama_tekshir"))
async def manual_check(message: Message, bot: Bot):
    """Qo'lda tekshirish (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return

    await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)

    try:
        await message.delete()
    except:
        pass


@router.message(Command("reklama_stat"))
async def show_stats(message: Message):
    """Statistika (faqat admin, faqat guruhda)"""
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
        f"📊 <b>Statistika - {datetime.now().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Faol foydalanuvchilar: {active_users}\n"
        f"✅ Bugun bajarganlar: {completed}\n"
        f"❌ Bajarmaganlar: {active_users - completed}\n"
        f"📈 Bajarilish: {int(completed / active_users * 100) if active_users > 0 else 0}%"
    )

    sent = await message.answer(text, parse_mode="HTML")

    try:
        await message.delete()
    except:
        pass

    await asyncio.sleep(30)
    try:
        await sent.delete()
    except:
        pass


@router.message(Command("reklama_users"))
async def list_users(message: Message):
    """Barcha foydalanuvchilar (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return

    user_ids = get_all_user_ids()
    active = []

    for uid in user_ids:
        u = get_user(uid)
        if u and u.get("status") == "active":
            active.append((uid, u))

    if not active:
        await message.answer("❌ Faol foydalanuvchilar yo'q")
        return

    text = "👥 <b>Faol foydalanuvchilar ro'yxati:</b>\n\n"

    for user_id, user_info in active[:20]:
        count = get_screenshot_count(user_id)
        status_emoji = "✅" if count >= 2 else "⚠️"
        username = f"@{user_info['username']}" if user_info['username'] != "mavjud_emas" else ""
        text += (
            f"{status_emoji} <b>{user_info['fullname']}</b> {username}\n"
            f"   📸 {count}/2 screenshot\n\n"
        )

    if len(active) > 20:
        text += f"\n<i>... va yana {len(active) - 20} ta foydalanuvchi</i>"

    sent = await message.answer(text, parse_mode="HTML")

    try:
        await message.delete()
    except:
        pass

    await asyncio.sleep(90)
    try:
        await sent.delete()
    except:
        pass


@router.message(Command("debug_reklama"))
async def debug_command(message: Message):
    """Sozlamalarni tekshirish (faqat admin, private chatda)"""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        f"🔧 <b>Debug ma'lumotlar:</b>\n\n"
        f"👤 Sizning ID: <code>{message.from_user.id}</code>\n"
        f"💬 Chat ID: <code>{message.chat.id}</code>\n\n"
        f"⚙️ Env variables:\n"
        f"ADMIN_ID: <code>{ADMIN_ID}</code>\n"
        f"GROUP_ID: <code>{GROUP_ID}</code>\n\n"
        f"{'✅ ADMIN_ID to\'g\'ri' if message.from_user.id == ADMIN_ID else '❌ ADMIN_ID noto\'g\'ri'}\n"
        f"{'✅ GROUP_ID sozlangan' if GROUP_ID != 0 else '❌ GROUP_ID sozlanmagan'}",
        parse_mode="HTML"
    )


@router.message(Command("reklama_help"))
async def help_command(message: Message):
    """Yordam (faqat admin, faqat guruhda)"""
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
        "/reklama_stat — Statistika (30 soniya)\n"
        "/reklama_users — Foydalanuvchilar ro'yxati\n"
        "/reklama_help — Bu yordam\n\n"
        "<b>Avtomatik:</b>\n"
        "⏰ 09:30 — Ertalabki tekshiruv\n"
        "⏰ 15:00 — Kunduzi tekshiruv"
    )

    sent = await message.answer(text, parse_mode="HTML")

    try:
        await message.delete()
    except:
        pass

    await asyncio.sleep(30)
    try:
        await sent.delete()
    except:
        pass
