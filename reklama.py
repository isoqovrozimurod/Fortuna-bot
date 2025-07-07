import logging
from typing import List
from aiogram import Bot
from aiogram.types import FSInputFile
from aiocron import crontab

GROUPS_FILE = "groups.txt"
REKLAMA_IMAGE_PATH = "temp/fortuna.jpg"

# Reklama matni
REKLAMA_TEXT = """✅FORTUNA BIZNES ENDI G'ALLAOROLDA

💸SIZGA PUL KERAKMI? MUAMMOSIZ, 2 SOATDA NAQD PULDA KREDIT OLING

🌐 FORTUNA BIZNES mikromoliya tashkiloti G'ALLAOROL filiali har doim sizga yordam berishga tayyor

✅Miqdori: 3 mln dan 300 mln so'mgacha;
✅Naqd pul ko'rinishida
✅2 - 3 soat oraligʻida 
✅Muddati: 12 oydan 36 oygacha
👨‍💼Mikroqarz olish uchun avtomashina garovi orqali yoki rasmiy ish joyi bor kishilarga mikroqarz ajratiladi.

🗄Naqt pul mikroqarzlar pensionerlarga ham beriladi (3–10 mln so‘mgacha)

📍Manzil: G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy
📞 +998551510040 | +998992510040 | +998724321500
"""

# Lokatsiya koordinatalari
LATITUDE = 40.024357
LONGITUDE = 67.589176

def load_chat_ids(file_path: str) -> List[int]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return list(set(int(line.strip()) for line in f if line.strip()))
    except FileNotFoundError:
        return []

def save_chat_id(chat_id: int):
    try:
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            existing_ids = set(int(line.strip()) for line in f if line.strip())
    except FileNotFoundError:
        existing_ids = set()

    if chat_id not in existing_ids:
        with open(GROUPS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{chat_id}\n")
        logging.info(f"✅ Yangi chat_id saqlandi: {chat_id}")

async def send_advertising(bot: Bot):
    chat_ids = load_chat_ids(GROUPS_FILE)
    if not chat_ids:
        logging.info("⚠️ Chatlar topilmadi, reklama yuborilmadi.")
        return

    photo = FSInputFile(REKLAMA_IMAGE_PATH)

    for chat_id in chat_ids:
        try:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=REKLAMA_TEXT)
            # Lokatsiya ham yuborish
            await bot.send_location(chat_id=chat_id, latitude=LATITUDE, longitude=LONGITUDE)
            logging.info(f"📤 Reklama va lokatsiya yuborildi: {chat_id}")
        except Exception as e:
            logging.error(f"❌ Reklama yuborishda xatolik ({chat_id}): {e}")

def setup_cron_tasks(bot: Bot):
    # @crontab("0 8,15 * * *")  # Har kuni soat 08:00 va 15:00 da ishlaydi
    @crontab("55 14 * * *")
    async def scheduled_reklama():
        await send_advertising(bot)

# Qo'shimcha: berilgan chatga darhol reklama yuborish
async def send_advertising_to_chat(bot: Bot, chat_id: int):
    try:
        photo = FSInputFile(REKLAMA_IMAGE_PATH)
        await bot.send_photo(chat_id=chat_id, photo=photo, caption=REKLAMA_TEXT)
        await bot.send_location(chat_id=chat_id, latitude=LATITUDE, longitude=LONGITUDE)
        logging.info(f"📤 Instant reklama va lokatsiya yuborildi: {chat_id}")
    except Exception as e:
        logging.error(f"❌ Instant reklama yuborishda xatolik ({chat_id}): {e}")
