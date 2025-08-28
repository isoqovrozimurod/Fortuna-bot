import os
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Routerlar
from start import router as start_router
from contact import router as contact_router
from kredit_turlari import router as kredit_router
from pensiya import router as pensiya_router
from ish_haqi import router as ish_haqi_router
from garov import router as garov_router
from calculator import router as calc_router
from buyruqlar import set_bot_commands
from valyuta import router as valyuta_router
from kredit import router as kredit_admin_router  # Admin uchun

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

async def main():
    if not TOKEN:
        logger.error("❌ BOT_TOKEN .env fayldan topilmadi.")
        return

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)

    dp = Dispatcher(storage=MemoryStorage())

    # Routerlarni ro‘yxatga olish
    dp.include_router(start_router)
    dp.include_router(contact_router)
    dp.include_router(kredit_router)          # kredit_turlari.py
    dp.include_router(pensiya_router)
    dp.include_router(ish_haqi_router)
    dp.include_router(garov_router)
    dp.include_router(calc_router)
    dp.include_router(valyuta_router)
    dp.include_router(kredit_admin_router)    # kredit.py (faqat admin uchun)

    await set_bot_commands(bot)

    logger.info("🤖 Bot ishga tushdi ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⛔ Bot to‘xtatildi")
