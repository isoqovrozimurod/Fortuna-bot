import os
import json
import logging
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Router va Logger
router = Router()
logger = logging.getLogger(__name__)

# Sozlamalar
try:
    GROUP_ID = int(os.getenv("GROUP_ID"))
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (TypeError, ValueError):
    logger.error("❌ .env faylida GROUP_ID yoki ADMIN_ID noto'g'ri kiritilgan!")
    GROUP_ID = 0
    ADMIN_ID = 0

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
DATA_FILE = "reklama_data.json"

# =================== YORDAMCHI FUNKSIYALAR ===================

def load_data():
    """Ma'lumotlarni fayldan o'qish"""
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "screenshots": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"JSON o'qishda xatolik: {e}")
        return {"users": {}, "screenshots": {}}

def save_data(data):
    """Ma'lumotlarni faylga saqlash"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"JSON saqlashda xatolik: {e}")

def get_today():
    """Bugungi sanani olish"""
    return datetime.now().strftime("%Y-%m-%d")

# =================== HANDLERLAR (BOT REAKSIYASI) ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    """Yangi a'zo qo'shilganda"""
    if event.chat.id != GROUP_ID: return
    
    user = event.new_chat_member.user
    data = load_data()
    
    data["users"][str(user.id)] = {
        "fullname": user.full_name,
        "username": user.username or "",
        "joined_date": get_today()
    }
    save_data(data)
    logger.info(f"➕ Yangi xodim qo'shildi: {user.full_name}")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    """A'zo chiqib ketganda"""
    if event.chat.id != GROUP_ID: return
    
    user = event.new_chat_member.user
    data = load_data()
    
    if str(user.id) in data["users"]: del data["users"][str(user.id)]
    if str(user.id) in data["screenshots"]: del data["screenshots"][str(user.id)]
    
    save_data(data)
    logger.info(f"➖ Xodim chiqib ketdi: {user.full_name}")

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    """Rasm (Screenshot) qabul qilinganda"""
    user_id = str(message.from_user.id)
    data = load_data()
    today = get_today()

    # 1. Foydalanuvchini bazaga qo'shish (agar yo'q bo'lsa)
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "fullname": message.from_user.full_name,
            "username": message.from_user.username or "",
            "joined_date": today
        }

    # 2. Screenshot statistikasini yangilash
    if user_id not in data["screenshots"]:
        data["screenshots"][user_id] = {"date": today, "count": 0}

    # Agar sana o'zgargan bo'lsa, count ni 0 dan boshlaymiz
    if data["screenshots"][user_id]["date"] != today:
        data["screenshots"][user_id] = {"date": today, "count": 0}
    
    data["screenshots"][user_id]["count"] += 1
    save_data(data)
    
    current_count = data["screenshots"][user_id]["count"]
    
    # 3. GURUHGA JAVOB QAYTARISH (MUHIM QISM)
    status_emoji = "✅" if current_count >= 2 else "⚠️"
    
    await message.reply(
        f"{status_emoji} <b>Qabul qilindi!</b>\n\n"
        f"👤 Xodim: {message.from_user.full_name}\n"
        f"📊 Bugungi hisob: <b>{current_count}-screenshot</b>\n"
        f"🎯 Norma: Kuniga 2 ta"
    )

# =================== SCHEDULER (VAQT BO'YICHA TEKSHIRUV) ===================

async def check_screenshots(bot: Bot):
    """Screenshot tashlamaganlarni aniqlash va guruhga yozish"""
    data = load_data()
    today = get_today()
    warned_users = []
    
    # Kim bugun 2 tadan kam rasm tashlagan?
    for user_id, user_info in data["users"].items():
        stats = data["screenshots"].get(user_id, {})
        
        # Agar sana bugungi bo'lmasa yoki soni 2 dan kam bo'lsa
        if stats.get("date") != today or stats.get("count", 0) < 2:
            current = stats.get("count", 0) if stats.get("date") == today else 0
            user_info['current_count'] = current
            warned_users.append(user_info)

    if warned_users:
        text = (
            f"🚨 <b>DIQQAT - REKLAMA NAZORATI ({datetime.now().strftime('%H:%M')})</b>\n\n"
            "Quyidagi xodimlar bugungi reklamani to'liq bajarmagan:\n\n"
        )
        for idx, u in enumerate(warned_users, 1):
            username = f"@{u['username']}" if u['username'] else "nomalum"
            text += f"{idx}. <b>{u['fullname']}</b> ({username}) — {u['current_count']}/2 ta\n"
            
        text += (
            "\n❗️ <i>Iltimos, zudlik bilan reklamalarni tarqatib, screenshot yuboring!</i>\n"
            f"🔗 Reklama manbai: {CHANNEL_LINK}"
        )
        
        try:
            await bot.send_message(GROUP_ID, text)
            logger.info("✅ Ogohlantirish xabari yuborildi.")
        except Exception as e:
            logger.error(f"❌ Guruhga xabar yuborishda xatolik: {e}")
    else:
        try:
            await bot.send_message(GROUP_ID, "✅ <b>Barakalla!</b> Hamma xodimlar reklama rejasini bajardi! 👏")
        except:
            pass

async def reset_daily_data():
    """Yarim tunda ma'lumotlarni yangilash"""
    data = load_data()
    data["screenshots"] = {} # Faqat screenshotlarni tozalaymiz, userlar qoladi
    save_data(data)
    logger.info("🔄 Kunlik statistika tozalandi.")

def setup_scheduler(bot: Bot):
    """Scheduler ni ishga tushirish funksiyasi"""
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    # 09:00 da tekshiruv
    scheduler.add_job(check_screenshots, CronTrigger(hour=9, minute=0), args=[bot])
    
    # 15:00 da tekshiruv
    scheduler.add_job(check_screenshots, CronTrigger(hour=15, minute=0), args=[bot])
    
    # 00:00 da tozalash
    scheduler.add_job(reset_daily_data, CronTrigger(hour=0, minute=0))
    
    scheduler.start()
    logger.info("⏰ Scheduler ishga tushdi: 09:00, 15:00 va 00:00")
