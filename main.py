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
from vakansiya import router as vakansiya_router
from biznes import router as biznes_router
from control import router as control_router
from chanel import router as chanel_router
from chanel import SubscriptionMiddleware
from kredit import router as kredit_admin_router
from hamkor import router as hamkor_router
from reklama_nazorati import router as reklama_router, setup_scheduler
from keep_alive import keep_alive

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


async def main():
    if not TOKEN:
        logger.error("❌ BOT_TOKEN .env fayldan topilmadi.")
        return

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🧹 Webhook tozalandi")

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Routerlar
    dp.include_router(chanel_router)
    dp.include_router(start_router)
    dp.include_router(contact_router)
    dp.include_router(kredit_router)
    dp.include_router(pensiya_router)
    dp.include_router(ish_haqi_router)
    dp.include_router(garov_router)
    dp.include_router(biznes_router)
    dp.include_router(hamkor_router)
    dp.include_router(calc_router)
    dp.include_router(valyuta_router)
    dp.include_router(vakansiya_router)
    dp.include_router(control_router)
    dp.include_router(kredit_admin_router)
    dp.include_router(reklama_router)

    await set_bot_commands(bot)
    keep_alive()

    # Scheduler
    setup_scheduler(bot)
    logger.info("⏰ Scheduler ishga tushdi")

    logger.info("🤖 Bot ishga tushdi ✅")
    logger.info(f"📱 Bot username: {(await bot.get_me()).username}")

    try:
        await dp.start_polling(
            bot,
            # MUHIM: chat_member bo'lmasa guruhga kirish/chiqish sezilmaydi
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "my_chat_member"
            ]
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⛔ Bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Xatolik: {e}")
