import os
import asyncio
import logging
from contextlib import suppress

from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.client.session.aiohttp import AiohttpSession

from upstash_redis import Redis

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
from chanel import router as chanel_router, SubscriptionMiddleware
from kredit import router as kredit_admin_router
from hamkor import router as hamkor_router
from reklama_nazorati import router as reklama_router, setup_scheduler

# =================== LOGGING ===================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("FortunaBot")


# =================== HTTP SERVER ===================

async def _handle_root(request: web.Request) -> web.Response:
    return web.Response(text="Fortuna-bot is running", content_type="text/plain")

async def start_http_server() -> web.AppRunner:
    port = int(os.getenv("PORT", "8000"))
    app = web.Application()
    app.router.add_get("/", _handle_root)
    #app.router.add_head("/", _handle_root)
    app.router.add_get("/healthz", _handle_root)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"HTTP server started on 0.0.0.0:{port}")
    return runner


# =================== UPSTASH LOCK ===================

def build_redis() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise RuntimeError("UPSTASH_REDIS_REST_URL va UPSTASH_REDIS_REST_TOKEN kerak")
    return Redis(url=url, token=token)

async def acquire_lock(redis: Redis, key: str, value: str, ttl: int) -> bool:
    try:
        return bool(redis.set(key, value, ex=ttl, nx=True))
    except Exception as e:
        logger.error(f"Lock olishda xato: {e}")
        return False

async def refresh_lock_loop(redis: Redis, key: str, value: str, ttl: int):
    interval = max(5, ttl // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            cur = redis.get(key)
            if isinstance(cur, bytes):
                cur = cur.decode()
            if str(cur) != value:
                raise RuntimeError(f"Lock boshqanikiga o'tdi: {cur} != {value}")
            redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.error(f"Lock refresh xato: {e}")
            raise


# =================== DISPATCHER ===================

def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Routerlar tartibi muhim
    dp.include_router(chanel_router)        # kanal tekshiruv — birinchi
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
    dp.include_router(reklama_router)       # guruh router — oxirgi

    return dp


# =================== POLLING ===================

async def run_polling(bot: Bot, dp: Dispatcher):
    while True:
        try:
            await dp.start_polling(
                bot,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "chat_member",      # guruhga kirish/chiqish uchun MUHIM
                    "my_chat_member",   # botni guruhga qo'shish/chiqarish
                ]
            )
        except TelegramConflictError as e:
            logger.error(f"TelegramConflictError: {e}. 15s...")
            await asyncio.sleep(15)
        except TelegramNetworkError as e:
            logger.error(f"NetworkError: {e}. 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"Polling xato: {e}. 10s...")
            await asyncio.sleep(10)


# =================== MAIN ===================

async def main():
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN yo'q!")
        return

    # HTTP server doim ishlaydi — Koyeb o'chirmasin
    http_runner = await start_http_server()

    # Bot
    bot = Bot(
    token=token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=AiohttpSession(timeout=60)
)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook tozalandi")

    dp = setup_dispatcher()
    await set_bot_commands(bot)

    # Distributed lock — faqat 1 ta instance polling qilsin
    instance_id = (
        os.getenv("KOYEB_DEPLOYMENT_ID")
        or os.getenv("RENDER_INSTANCE_ID")
        or str(os.getpid())
    )
    lock_key = f"fortuna:lock:{token[:10]}"
    lock_value = str(instance_id)

    try:
        redis = build_redis()
    except Exception as e:
        logger.error(f"Upstash Redis xato: {e}")
        await asyncio.Event().wait()
        return

    got_lock = await acquire_lock(redis, lock_key, lock_value, ttl=60)

    if not got_lock:
        logger.warning("Bu instance polling qilmaydi (lock band). Faqat HTTP server.")
        await asyncio.Event().wait()
        return

    logger.info("Lock olindi. Polling shu instanceda ishlaydi.")

    lock_task = asyncio.create_task(
        refresh_lock_loop(redis, lock_key, lock_value, ttl=60)
    )

    # Scheduler faqat polling instanceda
    scheduler = None
    with suppress(Exception):
        scheduler = setup_scheduler(bot)

    me = await bot.get_me()
    logger.info(f"Bot ishga tushdi: @{me.username}")

    try:
        await run_polling(bot, dp)
    finally:
        lock_task.cancel()
        with suppress(Exception):
            await lock_task
        if scheduler:
            with suppress(Exception):
                scheduler.shutdown(wait=False)
        with suppress(Exception):
            await http_runner.cleanup()
        with suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
    except Exception as e:
        logger.exception(f"Fatal xato: {e}")
