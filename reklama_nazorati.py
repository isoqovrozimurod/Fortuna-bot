import os
import json
import logging
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
except:
    GROUP_ID = 0
    ADMIN_ID = 0

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
DATA_FILE = "reklama_data.json"

# =================== YORDAMCHI FUNKSIYALAR ===================

def load_data():
    """Ma'lumotlarni o'qish"""
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "screenshots": {}}
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
    return datetime.now().strftime("%Y-%m-%d")

def register_user_in_db(user):
    """Foydalanuvchini bazaga qo'shish/yangilash"""
    data = load_data()
    user_id = str(user.id)
    
    # Yangi foydalanuvchi yoki ma'lumoti o'zgargan bo'lsa
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "fullname": user.full_name,
            "username": user.username or "mavjud_emas",
            "registered_at": get_today(),
            "status": "active"
        }
        save_data(data)
        return True # Yangi qo'shildi
    return False # Allaqachon bor

# =================== RO'YXATDAN O'TKAZISH TIZIMI ===================

@router.message(F.text == "/start_register", F.from_user.id == ADMIN_ID)
async def start_registration_process(message: Message):
    """Admin buyrug'i: Barchani ro'yxatdan o'tishga chaqirish"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ MEN SHU YERDAMAN (Tasdiqlash)", callback_data="register_me")]
    ])
    
    text = (
        "📢 <b>DIQQAT, GURUH A'ZOLARI!</b>\n\n"
        "Bot bazasini yangilash uchun barcha xodimlar quyidagi tugmani bosishi SHART!\n"
        "Kim tugmani bosmasa, ertadan boshlab \"Ishlamayapti\" deb hisoblanadi va ogohlantirish oladi.\n\n"
        "👇 <b>Hoziroq bosing:</b>"
    )
    
    await message.answer(text, reply_markup=keyboard)
    await message.delete() # Admin buyrug'ini o'chiramiz

@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    """Tugmani bosganda ro'yxatga olish"""
    user = callback.from_user
    is_new = register_user_in_db(user)
    
    if is_new:
        await callback.answer("✅ Siz ro'yxatga olindingiz! Rahmat.", show_alert=True)
    else:
        await callback.answer("Siz allaqachon ro'yxatdasiz! 👍", show_alert=False)

# =================== AVTOMATIK TUTIB OLISH ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    """Yangi kirganlarni avtomatik ilib olish"""
    if event.chat.id != GROUP_ID: return
    register_user_in_db(event.new_chat_member.user)

@router.message(F.chat.id == GROUP_ID, ~F.photo)
async def capture_text_messages(message: Message):
    """Har qanday yozgan odamni sezdirmasdan ro'yxatga olish"""
    register_user_in_db(message.from_user)

# =================== SCREENSHOT QABUL QILISH ===================

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    """Screenshot qabul qilish va hisoblash"""
    user = message.from_user
    user_id = str(user.id)
    today = get_today()
    
    # 1. Avval ro'yxatga olamiz (ehtimol oldin yozmagandir)
    register_user_in_db(user)
    data = load_data()

    # 2. Screenshotni hisoblaymiz
    if user_id not in data["screenshots"]:
        data["screenshots"][user_id] = {"date": today, "count": 0}

    # Sana o'zgargan bo'lsa nolga tushiramiz
    if data["screenshots"][user_id]["date"] != today:
        data["screenshots"][user_id] = {"date": today, "count": 0}
    
    data["screenshots"][user_id]["count"] += 1
    save_data(data)
    
    count = data["screenshots"][user_id]["count"]
    
    # 3. JAVOB QAYTARISH
    await message.reply(
        f"✅ <b>Qabul qilindi!</b>\n"
        f"👤 {user.full_name}\n"
        f"📊 Bugungi natija: <b>{count}-screenshot</b>\n"
        f"👏 <i>Barakalla, shu tarzda davom eting!</i>"
    )

# =================== NAZORAT QILISH (09:30 va 15:00) ===================

async def check_screenshots(bot: Bot):
    """Hisobot"""
    data = load_data()
    today = get_today()
    
    total_users = 0
    debtors = [] # Qarzdorlar

    # Bazadagi har bir odamni tekshiramiz
    for user_id, user_info in data["users"].items():
        total_users += 1
        stats = data["screenshots"].get(user_id, {})
        
        # Bugun necha marta tashlagan?
        count = stats.get("count", 0) if stats.get("date") == today else 0
        
        # Agar 2 tadan kam bo'lsa
        if count < 2:
            debtors.append({
                "name": user_info["fullname"],
                "username": user_info["username"],
                "count": count
            })

    # XABAR YUBORISH
    current_time = datetime.now().strftime("%H:%M")
    
    if debtors:
        text = (
            f"🚨 <b>DIQQAT - NAZORAT ({current_time})</b>\n\n"
            f"👥 Ro'yxatdagi xodimlar: {total_users} ta\n"
            f"👇 Quyidagilar REKLAMA PLANINI bajarmadi:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
        )
        
        for idx, user in enumerate(debtors, 1):
            mention = f"@{user['username']}" if user['username'] != "mavjud_emas" else user['name']
            text += f"{idx}. <b>{user['name']}</b> ({mention}) — {user['count']}/2 ❌\n"
            
        text += (
            "\n➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "❗️ <b>OGOHLANTIRISH!</b>\n"
            "Zudlik bilan reklama tarqatib, hisobot yuboring!\n"
            f"🔗 Manba: {CHANNEL_LINK}"
        )
        try:
            await bot.send_message(GROUP_ID, text)
        except Exception as e:
            logger.error(f"Xabar yuborishda xato: {e}")
            
    else:
        # Agar hamma bajargan bo'lsa, lekin foydalanuvchilar soni 0 bo'lsa (yangi bot)
        if total_users == 0:
            return 

        success_text = (
            f"🏆 <b>NATIJA ({current_time})</b>\n\n"
            "✅ <b>QOYILMAQOM!</b>\n"
            f"Guruhdagi barcha {total_users} nafar xodim rejasini bajardi.\n\n"
            "Hammaga rahmat! 👏👏👏"
        )
        try:
            await bot.send_message(GROUP_ID, success_text)
        except:
            pass

async def reset_daily_data():
    """Yarim tunda hisoblagichni tozalash"""
    data = load_data()
    data["screenshots"] = {} 
    save_data(data)

def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    # Tekshiruv vaqtlari
    scheduler.add_job(check_screenshots, CronTrigger(hour=9, minute=30), args=[bot])
    scheduler.add_job(check_screenshots, CronTrigger(hour=15, minute=0), args=[bot])
    
    # Tozalash
    scheduler.add_job(reset_daily_data, CronTrigger(hour=0, minute=0))
    
    scheduler.start()
