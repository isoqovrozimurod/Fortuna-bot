"""
Reklama Nazorat Tizimi
Har kuni soat 09:00 va 15:00 da screenshot tekshirish
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
load_dotenv()

router = Router()

# Sozlamalar
GROUP_ID = int(os.getenv("GROUP_ID"))
CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Ma'lumotlar fayli
DATA_FILE = "reklama_data.json"


# =================== MA'LUMOTLAR BAZASI ===================

def load_data():
    """Ma'lumotlarni yuklash"""
    if not os.path.exists(DATA_FILE):
        return {
            "users": {},  # user_id: {"fullname": "...", "last_check": "..."}
            "screenshots": {}  # user_id: {"date": "2026-02-12", "count": 2}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"users": {}, "screenshots": {}}


def save_data(data):
    """Ma'lumotlarni saqlash"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_today():
    """Bugungi sana"""
    return datetime.now().strftime("%Y-%m-%d")


# =================== FOYDALANUVCHILARNI KUZATISH ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    """Yangi a'zo qo'shilganda"""
    if event.chat.id != GROUP_ID:
        return

    user = event.new_chat_member.user
    data = load_data()

    # Foydalanuvchini ro'yxatga olish
    data["users"][str(user.id)] = {
        "fullname": user.full_name,
        "username": user.username or "",
        "joined_date": get_today()
    }

    save_data(data)
    print(f"✅ Yangi a'zo: {user.full_name} (ID: {user.id})")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    """A'zo chiqib ketganda"""
    if event.chat.id != GROUP_ID:
        return

    user = event.new_chat_member.user
    data = load_data()

    # Foydalanuvchini o'chirish
    if str(user.id) in data["users"]:
        del data["users"][str(user.id)]

    if str(user.id) in data["screenshots"]:
        del data["screenshots"][str(user.id)]

    save_data(data)
    print(f"❌ A'zo chiqdi: {user.full_name} (ID: {user.id})")


# =================== SCREENSHOT TEKSHIRISH ===================

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    """Rasm yuborilganda"""
    user_id = str(message.from_user.id)
    data = load_data()

    # Foydalanuvchini tekshirish
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "fullname": message.from_user.full_name,
            "username": message.from_user.username or "",
            "joined_date": get_today()
        }

    # Bugungi screenshot'larni hisoblash
    today = get_today()

    if user_id not in data["screenshots"]:
        data["screenshots"][user_id] = {"date": today, "count": 0}

    # Agar bugungi kun bo'lsa - hisoblash
    if data["screenshots"][user_id]["date"] == today:
        data["screenshots"][user_id]["count"] += 1
    else:
        # Yangi kun - qaytadan boshlash
        data["screenshots"][user_id] = {"date": today, "count": 1}

    save_data(data)

    count = data["screenshots"][user_id]["count"]
    print(f"📸 {message.from_user.full_name}: {count} ta screenshot (bugun)")


# =================== KUN BO'YI TEKSHIRISH ===================

async def check_screenshots(bot: Bot):
    """Screenshot tashlamaganlarni tekshirish"""
    data = load_data()
    today = get_today()

    # Ogohlantirishlar soni
    warned_users = []
    total_users = len(data["users"])

    # Har bir foydalanuvchini tekshirish
    for user_id, user_info in data["users"].items():
        # Screenshot ma'lumotlarini olish
        screenshots = data["screenshots"].get(user_id, {"date": "", "count": 0})

        # Agar bugun screenshot yubormagan bo'lsa yoki 2 tadan kam bo'lsa
        if screenshots.get("date") != today or screenshots.get("count", 0) < 2:
            warned_users.append({
                "id": int(user_id),
                "fullname": user_info["fullname"],
                "username": user_info.get("username", ""),
                "count": screenshots.get("count", 0) if screenshots.get("date") == today else 0
            })

    # Agar ogohlantirishlar bo'lsa
    if warned_users:
        # Bir xabar orqali barcha foydalanuvchilarni ogohlantiramiz
        warning_text = (
            "⚠️ <b>OGOHLANTIRISH - REKLAMA TARQATISH</b>\n\n"
            f"📅 Sana: {datetime.now().strftime('%d.%m.%Y')} | ⏰ Vaqt: {datetime.now().strftime('%H:%M')}\n\n"
            "Quyidagi foydalanuvchilar bugun reklama tarqatmagan yoki kamida 2 ta screenshot yuborishmagan:\n\n"
        )

        for idx, user in enumerate(warned_users, 1):
            username = f"@{user['username']}" if user['username'] else "Username yo'q"
            warning_text += (
                f"{idx}. {user['fullname']} ({username})\n"
                f"   📸 Bugun yuborilgan: {user['count']}/2 ta screenshot\n\n"
            )

        warning_text += (
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📢 <b>ESLATMA:</b>\n"
            "Har kuni kamida 2 ta screenshot yuborish MAJBURIY!\n\n"
            "📌 <b>Reklama materiallari:</b>\n"
            f"{CHANNEL_LINK}\n\n"
            "✅ Ushbu kanaldan reklama postlarini oling va boshqa gruppalar/kanallarga tarqating.\n"
            "📸 Screenshot'larni ushbu gruppaga yuboring.\n\n"
            "⏰ Keyingi tekshiruv: Bugun soat 15:00 da\n"
            "🔔 Iltimos, o'z vaqtida bajaring!"
        )

        # Gruppaga xabar yuborish
        try:
            await bot.send_message(GROUP_ID, warning_text)
            print(f"✅ Ogohlantirish yuborildi: {len(warned_users)} ta foydalanuvchi")
        except Exception as e:
            print(f"❌ Xabar yuborishda xatolik: {e}")
    else:
        # Hamma screenshot tashlagan
        success_text = (
            "✅ <b>AJOYIB!</b>\n\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y')} | ⏰ {datetime.now().strftime('%H:%M')}\n\n"
            f"Barcha foydalanuvchilar ({total_users} ta) bugun reklama tarqatgan! 🎉\n\n"
            "Davom eting! 💪"
        )

        try:
            await bot.send_message(GROUP_ID, success_text)
            print(f"✅ Hamma tekshirildi: {total_users} ta foydalanuvchi")
        except Exception as e:
            print(f"❌ Xabar yuborishda xatolik: {e}")

    # Statistika (admin uchun)
    if ADMIN_ID:
        stats_text = (
            f"📊 <b>Statistika - {datetime.now().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
            f"👥 Jami foydalanuvchilar: {total_users}\n"
            f"✅ Screenshot yuborgan: {total_users - len(warned_users)}\n"
            f"⚠️ Ogohlantirilanlar: {len(warned_users)}\n\n"
            f"📈 Bajarilish: {int((total_users - len(warned_users)) / total_users * 100) if total_users > 0 else 0}%"
        )

        try:
            await bot.send_message(ADMIN_ID, stats_text)
        except:
            pass


# =================== KUNLIK TOZALASH ===================

async def reset_daily_data():
    """Har kuni ma'lumotlarni tozalash (yarim tunda)"""
    data = load_data()

    # Screenshot ma'lumotlarini tozalash
    data["screenshots"] = {}

    save_data(data)
    print("🔄 Kunlik ma'lumotlar tozalandi")


# =================== SCHEDULER SOZLASH ===================

def setup_scheduler(bot: Bot):
    """Scheduler'ni sozlash"""
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # Soat 09:00 da tekshirish
    scheduler.add_job(
        check_screenshots,
        trigger=CronTrigger(hour=9, minute=0),
        args=[bot],
        id="morning_check",
        replace_existing=True
    )

    # Soat 15:00 da tekshirish
    scheduler.add_job(
        check_screenshots,
        trigger=CronTrigger(hour=15, minute=0),
        args=[bot],
        id="afternoon_check",
        replace_existing=True
    )

    # Yarim tunda ma'lumotlarni tozalash
    scheduler.add_job(
        reset_daily_data,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_reset",
        replace_existing=True
    )

    scheduler.start()
    print("✅ Scheduler ishga tushdi (09:00, 15:00 tekshiruv)")

    return scheduler


# =================== ADMIN BUYRUQLARI ===================

@router.message(F.text == "/tekshir", F.from_user.id == ADMIN_ID)
async def manual_check(message: Message, bot: Bot):
    """Qo'lda tekshirish (faqat admin)"""
    await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)


@router.message(F.text == "/statistika", F.from_user.id == ADMIN_ID)
async def show_stats(message: Message):
    """Statistika ko'rsatish (faqat admin)"""
    data = load_data()
    today = get_today()

    total_users = len(data["users"])
    completed = 0

    for user_id in data["users"]:
        screenshots = data["screenshots"].get(user_id, {"date": "", "count": 0})
        if screenshots.get("date") == today and screenshots.get("count", 0) >= 2:
            completed += 1

    stats_text = (
        f"📊 <b>Statistika - {datetime.now().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"✅ Vazifani bajargan: {completed}\n"
        f"⚠️ Bajarilmagan: {total_users - completed}\n\n"
        f"📈 Bajarilish: {int(completed / total_users * 100) if total_users > 0 else 0}%"
    )

    await message.answer(stats_text)


@router.message(F.text == "/foydalanuvchilar", F.from_user.id == ADMIN_ID)
async def list_users(message: Message):
    """Barcha foydalanuvchilar ro'yxati (faqat admin)"""
    data = load_data()
    today = get_today()

    if not data["users"]:
        return await message.answer("Hech kim yo'q.")

    text = "👥 <b>Foydalanuvchilar ro'yxati:</b>\n\n"

    for user_id, user_info in data["users"].items():
        screenshots = data["screenshots"].get(user_id, {"date": "", "count": 0})
        count = screenshots.get("count", 0) if screenshots.get("date") == today else 0
        status = "✅" if count >= 2 else "⚠️"

        text += (
            f"{status} {user_info['fullname']}\n"
            f"   📸 {count}/2 screenshot\n\n"
        )

    await message.answer(text)


@router.message(F.text == "/help_reklama", F.from_user.id == ADMIN_ID)
async def help_reklama(message: Message):
    """Yordam (faqat admin)"""
    help_text = (
        "📋 <b>Reklama Nazorat Tizimi - Yordam</b>\n\n"
        "<b>Admin buyruqlari:</b>\n"
        "/tekshir - Qo'lda tekshirish\n"
        "/statistika - Bugungi statistika\n"
        "/foydalanuvchilar - Barcha foydalanuvchilar\n"
        "/help_reklama - Bu yordam\n\n"
        "<b>Avtomatik tekshirish:</b>\n"
        "⏰ 09:00 - Ertalabki tekshiruv\n"
        "⏰ 15:00 - Kunduzi tekshiruv\n"
        "🌙 00:00 - Ma'lumotlar tozalanadi\n\n"
        "<b>Qoidalar:</b>\n"
        "• Har kuni kamida 2 ta screenshot\n"
        "• Screenshot bu gruppaga yuborilishi kerak\n"
        "• Reklama: {CHANNEL_LINK}"
    )

    await message.answer(help_text)
