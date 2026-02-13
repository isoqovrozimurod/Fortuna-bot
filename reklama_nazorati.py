"""
Reklama Nazorat Tizimi - Optimallashtirilgan versiya
Har kuni 09:30 va 15:00 da screenshot tekshirish
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from aiogram import Router, Bot, F
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Router va Logger
router = Router()
logger = logging.getLogger(__name__)

# Sozlamalar
try:
    GROUP_ID = int(os.getenv("GROUP_ID", "0"))
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except (ValueError, TypeError):
    GROUP_ID = 0
    ADMIN_ID = 0
    logger.error("❌ GROUP_ID yoki ADMIN_ID noto'g'ri formatda!")

CHANNEL_LINK = "https://t.me/FORTUNABIZNES_GALLAOROL"
DATA_FILE = Path("reklama_data.json")

# =================== YORDAMCHI FUNKSIYALAR ===================

def load_data() -> dict:
    """Ma'lumotlarni o'qish (xavfsiz)"""
    if not DATA_FILE.exists():
        return {"users": {}, "screenshots": {}, "stats": {"total_checks": 0}}
    
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # Eski formatni yangilash
            if "stats" not in data:
                data["stats"] = {"total_checks": 0}
            return data
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Ma'lumotlarni o'qishda xato: {e}")
        # Backup yaratish
        if DATA_FILE.exists():
            backup_file = Path(f"reklama_data_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            DATA_FILE.rename(backup_file)
            logger.info(f"Backup yaratildi: {backup_file}")
        return {"users": {}, "screenshots": {}, "stats": {"total_checks": 0}}


def save_data(data: dict) -> bool:
    """Ma'lumotlarni saqlash (xavfsiz)"""
    try:
        # Temp faylga yozish (atomic write)
        temp_file = DATA_FILE.with_suffix('.tmp')
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Temp faylni asosiy faylga o'zgartirish
        temp_file.replace(DATA_FILE)
        return True
    except IOError as e:
        logger.error(f"Ma'lumotlarni saqlashda xato: {e}")
        return False


def get_today() -> str:
    """Bugungi sana (YYYY-MM-DD)"""
    return datetime.now().strftime("%Y-%m-%d")


def register_user_in_db(user) -> bool:
    """
    Foydalanuvchini bazaga qo'shish/yangilash
    Returns: True - yangi, False - mavjud
    """
    data = load_data()
    user_id = str(user.id)
    
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "fullname": user.full_name,
            "username": user.username or "mavjud_emas",
            "registered_at": get_today(),
            "status": "active",
            "last_seen": get_today()
        }
        save_data(data)
        logger.info(f"✅ Yangi foydalanuvchi: {user.full_name} (ID: {user_id})")
        return True
    else:
        # Ma'lumotlarni yangilash
        data["users"][user_id]["fullname"] = user.full_name
        data["users"][user_id]["username"] = user.username or "mavjud_emas"
        data["users"][user_id]["last_seen"] = get_today()
        save_data(data)
        return False


# =================== RO'YXATDAN O'TKAZISH ===================

@router.message(F.text == "/start_register")
async def start_registration_process(message: Message):
    """Admin buyrug'i: Barchani ro'yxatdan o'tishga chaqirish (faqat guruhda)"""
    
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
    
    await message.bot.send_message(GROUP_ID, text, reply_markup=keyboard)
    
    # Admin buyrug'ini o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # Statni yangilash
    data = load_data()
    data["stats"]["last_registration"] = {
        "date": get_today(),
        "time": datetime.now().strftime("%H:%M"),
        "admin_id": message.from_user.id
    }
    save_data(data)


@router.callback_query(F.data == "register_me")
async def process_registration(callback: CallbackQuery):
    """Tugmani bosganda ro'yxatga olish"""
    user = callback.from_user
    is_new = register_user_in_db(user)
    
    if is_new:
        await callback.answer("✅ Siz ro'yxatga olindingiz! Rahmat.", show_alert=True)
    else:
        await callback.answer("✅ Ma'lumotlar yangilandi! Rahmat.", show_alert=False)


# =================== AVTOMATIK TUTIB OLISH ===================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def user_joined(event: ChatMemberUpdated):
    """Yangi kirganlarni avtomatik ilib olish"""
    if event.chat.id != GROUP_ID:
        return
    
    user = event.new_chat_member.user
    is_new = register_user_in_db(user)
    
    if is_new:
        logger.info(f"👋 Guruhga qo'shildi: {user.full_name}")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def user_left(event: ChatMemberUpdated):
    """Chiqib ketganlarni nofaol qilish"""
    if event.chat.id != GROUP_ID:
        return
    
    user = event.new_chat_member.user
    data = load_data()
    user_id = str(user.id)
    
    if user_id in data["users"]:
        data["users"][user_id]["status"] = "left"
        data["users"][user_id]["left_date"] = get_today()
        save_data(data)
        logger.info(f"👋 Guruhdan chiqdi: {user.full_name}")


@router.message(F.chat.id == GROUP_ID, ~F.photo)
async def capture_text_messages(message: Message):
    """Har qanday yozgan odamni sezdirmasdan ro'yxatga olish"""
    if message.from_user and not message.from_user.is_bot:
        register_user_in_db(message.from_user)


# =================== SCREENSHOT QABUL QILISH ===================

@router.message(F.chat.id == GROUP_ID, F.photo)
async def photo_received(message: Message):
    """Screenshot qabul qilish va hisoblash"""
    user = message.from_user
    
    # Bot'larni ignore qilish
    if user.is_bot:
        return
    
    user_id = str(user.id)
    today = get_today()
    
    # 1. Ro'yxatga olish
    register_user_in_db(user)
    data = load_data()

    # 2. Screenshot hisoblash
    if user_id not in data["screenshots"]:
        data["screenshots"][user_id] = {"date": today, "count": 0}

    # Sana o'zgargan bo'lsa reset
    if data["screenshots"][user_id]["date"] != today:
        data["screenshots"][user_id] = {"date": today, "count": 0}
    
    data["screenshots"][user_id]["count"] += 1
    count = data["screenshots"][user_id]["count"]
    
    save_data(data)
    
    # 3. Javob qaytarish
    if count == 1:
        emoji = "📸"
        status = "Birinchi screenshot qabul qilindi!"
    elif count == 2:
        emoji = "✅"
        status = "Ajoyib! Kunlik rejangiz bajarildi!"
    else:
        emoji = "🎉"
        status = f"Zo'r! {count}-screenshot qabul qilindi!"
    
    response_text = (
        f"{emoji} <b>Qabul qilindi!</b>\n"
        f"👤 {user.full_name}\n"
        f"📊 Bugungi natija: <b>{count}/2 screenshot</b>\n"
        f"💬 {status}"
    )
    
    try:
        await message.reply(response_text)
    except Exception as e:
        logger.error(f"Javob yuborishda xato: {e}")


# =================== NAZORAT (09:30 va 15:00) ===================

async def check_screenshots(bot: Bot):
    """Hisobot va ogohlantirish"""
    if GROUP_ID == 0:
        logger.error("❌ GROUP_ID sozlanmagan, tekshiruv o'tkazilmaydi!")
        return
    
    data = load_data()
    today = get_today()
    
    total_users = 0
    debtors = []  # Qarzdorlar
    completed = 0  # Bajarganlar

    # Faqat faol foydalanuvchilarni tekshirish
    for user_id, user_info in data["users"].items():
        if user_info.get("status", "active") != "active":
            continue
        
        total_users += 1
        stats = data["screenshots"].get(user_id, {})
        
        # Bugungi screenshot soni
        count = stats.get("count", 0) if stats.get("date") == today else 0
        
        if count < 2:
            debtors.append({
                "name": user_info["fullname"],
                "username": user_info["username"],
                "count": count
            })
        else:
            completed += 1

    # Statistika yangilash
    data["stats"]["total_checks"] += 1
    data["stats"]["last_check"] = {
        "date": today,
        "time": datetime.now().strftime("%H:%M"),
        "total": total_users,
        "completed": completed,
        "debtors": len(debtors)
    }
    save_data(data)

    # XABAR YUBORISH
    current_time = datetime.now().strftime("%H:%M")
    
    if total_users == 0:
        # Hech kim ro'yxatda yo'q
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
        text = (
            f"🚨 <b>NAZORAT HISOBOTI ({current_time})</b>\n\n"
            f"👥 Faol xodimlar: {total_users} ta\n"
            f"✅ Bajarganlar: {completed} ta\n"
            f"❌ Bajarmaganlar: {len(debtors)} ta\n"
            f"📊 Bajarilish: {int(completed/total_users*100)}%\n\n"
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
            "⏰ Keyingi tekshiruv: "
        )
        
        # Keyingi tekshiruv vaqtini ko'rsatish
        current_hour = datetime.now().hour
        if current_hour < 9 or (current_hour == 9 and datetime.now().minute < 30):
            text += "Bugun 09:30 da"
        elif current_hour < 15:
            text += "Bugun 15:00 da"
        else:
            text += "Ertaga 09:30 da"
        
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
        # Hamma bajargan
        success_text = (
            f"🏆 <b>AJOYIB NATIJA! ({current_time})</b>\n\n"
            "✅ <b>BARCHA XODIMLAR REJANI BAJARDI!</b>\n\n"
            f"👥 Faol xodimlar: {total_users} ta\n"
            f"📸 Hamma 2/2 screenshot yubordi\n"
            f"📊 Bajarilish: 100%\n\n"
            "👏 Hamma jamoaga rahmat!\n"
            "💪 Shu tarzda davom eting!"
        )
        
        try:
            await bot.send_message(GROUP_ID, success_text, parse_mode="HTML")
            logger.info(f"✅ Muvaffaqiyat xabari: {total_users} ta xodim")
        except Exception as e:
            logger.error(f"❌ Xabar yuborishda xato: {e}")
    
    # Admin uchun statistika
    if ADMIN_ID and ADMIN_ID != 0:
        admin_stats = (
            f"📊 <b>Admin statistika - {current_time}</b>\n\n"
            f"👥 Jami: {total_users}\n"
            f"✅ Bajargan: {completed}\n"
            f"❌ Bajarmagan: {len(debtors)}\n"
            f"📈 Foiz: {int(completed/total_users*100)}%\n\n"
            f"🔢 Jami tekshiruvlar: {data['stats']['total_checks']}"
        )
        
        try:
            await bot.send_message(ADMIN_ID, admin_stats, parse_mode="HTML")
        except:
            pass


async def reset_daily_data():
    """Yarim tunda tozalash"""
    data = load_data()
    
    # Eski screenshot ma'lumotlarini arxivlash
    yesterday = (datetime.now().replace(hour=0, minute=0) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    if "archive" not in data:
        data["archive"] = {}
    
    data["archive"][yesterday] = {
        "screenshots": data["screenshots"].copy(),
        "total_users": len(data["users"])
    }
    
    # Faqat oxirgi 7 kunni saqlash
    if len(data["archive"]) > 7:
        sorted_dates = sorted(data["archive"].keys())
        for old_date in sorted_dates[:-7]:
            del data["archive"][old_date]
    
    # Yangi kun uchun tozalash
    data["screenshots"] = {}
    
    save_data(data)
    logger.info(f"🔄 Kunlik ma'lumotlar tozalandi va arxivlandi ({yesterday})")


def setup_scheduler(bot: Bot):
    """Scheduler'ni sozlash"""
    if GROUP_ID == 0:
        logger.error("❌ GROUP_ID sozlanmagan! Scheduler ishga tushmaydi.")
        return None
    
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    # Tekshiruvlar
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
    
    # Tozalash
    scheduler.add_job(
        reset_daily_data,
        CronTrigger(hour=0, minute=0),
        id="daily_reset",
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi (09:30, 15:00 tekshiruv)")
    
    return scheduler


# =================== ADMIN BUYRUQLARI (FAQAT GURUHDA) ===================

def is_admin_in_group(message: Message) -> bool:
    """Admin va guruh tekshiruvi"""
    return (
        message.from_user.id == ADMIN_ID and 
        message.chat.id == GROUP_ID and
        ADMIN_ID != 0 and 
        GROUP_ID != 0
    )


@router.message(F.text == "/reklama_tekshir")
async def manual_check(message: Message, bot: Bot):
    """Qo'lda tekshirish (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return
    
    await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    
    # Admin buyrug'ini o'chirish (guruhni tozalash)
    try:
        await message.delete()
    except:
        pass


@router.message(F.text == "/reklama_stat")
async def show_stats(message: Message):
    """Statistika (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return
    
    data = load_data()
    today = get_today()
    
    active_users = sum(1 for u in data["users"].values() if u.get("status") == "active")
    completed = 0
    
    for user_id in data["users"]:
        if data["users"][user_id].get("status") != "active":
            continue
        stats = data["screenshots"].get(user_id, {})
        if stats.get("date") == today and stats.get("count", 0) >= 2:
            completed += 1
    
    text = (
        f"📊 <b>Statistika - {datetime.now().strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"👥 Faol foydalanuvchilar: {active_users}\n"
        f"✅ Bugun bajarganlar: {completed}\n"
        f"❌ Bajarmaganlar: {active_users - completed}\n"
        f"📈 Bajarilish: {int(completed/active_users*100) if active_users > 0 else 0}%\n\n"
        f"🔢 Jami tekshiruvlar: {data['stats'].get('total_checks', 0)}"
    )
    
    sent_message = await message.answer(text)
    
    # Admin buyrug'ini o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # 30 soniyadan keyin statistikani ham o'chirish (guruhni tozalash)
    await asyncio.sleep(30)
    try:
        await sent_message.delete()
    except:
        pass


@router.message(F.text == "/reklama_help")
async def help_command(message: Message):
    """Yordam (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return
    
    text = (
        "📋 <b>Reklama Nazorat - Yordam</b>\n\n"
        "<b>Foydalanuvchi uchun:</b>\n"
        "• Guruhga rasm yuboring (screenshot)\n"
        "• Bot avtomatik hisoblaydi\n"
        "• Har kuni kamida 2 ta screenshot kerak\n\n"
        "<b>Admin buyruqlari (faqat guruhda):</b>\n"
        "/start_register - Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir - Qo'lda tekshirish\n"
        "/reklama_stat - Statistika (30 soniya)\n"
        "/reklama_help - Bu yordam\n\n"
        "<b>Avtomatik:</b>\n"
        "⏰ 09:30 - Ertalabki tekshiruv\n"
        "⏰ 15:00 - Kunduzi tekshiruv\n"
        "🌙 00:00 - Ma'lumotlar arxivlanadi"
    )
    
    sent_message = await message.answer(text)
    
    # Admin buyrug'ini o'chirish
    try:
        await message.delete()
    except:
        pass
    
    # 30 soniyadan keyin yordam xabarini ham o'chirish
    await asyncio.sleep(30)
    try:
        await sent_message.delete()
    except:
        pass


@router.message(F.text == "/reklama_users")
async def list_users(message: Message):
    """Barcha foydalanuvchilar (faqat admin, faqat guruhda)"""
    if not is_admin_in_group(message):
        return
    
    data = load_data()
    today = get_today()
    
    active_users = [
        (uid, info) for uid, info in data["users"].items() 
        if info.get("status") == "active"
    ]
    
    if not active_users:
        await message.answer("❌ Faol foydalanuvchilar yo'q")
        return
    
    text = "👥 <b>Faol foydalanuvchilar ro'yxati:</b>\n\n"
    
    for user_id, user_info in active_users[:20]:  # Faqat birinchi 20 ta
        stats = data["screenshots"].get(user_id, {})
        count = stats.get("count", 0) if stats.get("date") == today else 0
        status_emoji = "✅" if count >= 2 else "⚠️"
        
        username = f"@{user_info['username']}" if user_info['username'] != "mavjud_emas" else ""
        
        text += (
            f"{status_emoji} <b>{user_info['fullname']}</b> {username}\n"
            f"   📸 {count}/2 screenshot\n\n"
        )
    
    if len(active_users) > 20:
        text += f"\n<i>... va yana {len(active_users) - 20} ta foydalanuvchi</i>"
    
    sent_message = await message.answer(text)
    
    # O'chirish
    try:
        await message.delete()
    except:
        pass
    
    await asyncio.sleep(90)
    try:
        await sent_message.delete()
    except:
        pass
