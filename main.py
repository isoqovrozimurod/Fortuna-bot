import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ChatMemberUpdated
from aiogram.filters import Command
from dotenv import load_dotenv

# Routerlar
from start import router as start_router
from contact import router as contact_router
from kredit_turlari import router as kredit_router
from pensiya import router as pensiya_router
from ish_haqi import router as ish_haqi_router
from garov import router as garov_router
from calculator import router as calc_router

# Reklama va komandalar
from reklama import setup_cron_tasks, save_chat_id, send_advertising_to_chat
from buyruqlar import set_bot_commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

async def on_bot_added_to_chat(event: ChatMemberUpdated):
    if event.new_chat_member.status in ("administrator", "member"):
        logger.info("🔔 Bot guruhga qo‘shildi yoki admin bo‘ldi.")
        save_chat_id(event.chat.id)
        logger.info(f"✅ Chat ID saqlandi: {event.chat.id}")

# /start komandasi uchun handler
async def on_start(message: types.Message):
    chat_id = message.chat.id
    save_chat_id(chat_id)
    await send_advertising_to_chat(message.bot, chat_id)
    await message.answer("Assalomu alaykum! Siz bilan bog‘landik.")

async def main():
    if not TOKEN:
        logger.error("❌ BOT_TOKEN .env fayldan topilmadi.")
        return

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)

    dp = Dispatcher(storage=MemoryStorage())

    dp.chat_member.register(on_bot_added_to_chat)

    # Start komandasi uchun handler ro'yxatga olish
    dp.message.register(on_start, Command("start"))

    # Routerlarni ro‘yxatga olish
    dp.include_router(start_router)
    dp.include_router(contact_router)
    dp.include_router(kredit_router)
    dp.include_router(pensiya_router)
    dp.include_router(ish_haqi_router)
    dp.include_router(garov_router)
    dp.include_router(calc_router)

    await set_bot_commands(bot)

    setup_cron_tasks(bot)

    logger.info("🤖 Bot ishga tushdi ✅")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⛔ Bot to‘xtatildi")
