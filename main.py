import os
import sys
import asyncio
import logging
from contextlib import suppress

from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError
from aiogram.client.session.aiohttp import AiohttpSession

# MUHIM O'ZGARISH: Sinxron o'rniga asinxron kutubxona ishlatiladi
from upstash_redis.asyncio import Redis

# Routerlar (Sening o'zgarishsiz routerlaring)
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
from filial import router as filial_router
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
    app.router.add_get("/healthz", _handle_root)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"HTTP server started on 0.0.0.0:{port}")
    return runner


# =================== UPSTASH LOCK (ASINXRON) ===================
def build_redis() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise RuntimeError("UPSTASH_REDIS_REST_URL va UPSTASH_REDIS_REST_TOKEN kerak")
    return Redis(url=url, token=token)

async def acquire_lock(redis: Redis, key: str, value: str, ttl: int) -> bool:
    try:
        # Await qo'shildi, loopni bloklamaydi
        result = await redis.set(key, value, ex=ttl, nx=True)
        return bool(result)
    except Exception as e:
        logger.error(f"Lock olishda xato: {e}")
        return False

async def refresh_lock_loop(redis: Redis, key: str, value: str, ttl: int):
    interval = max(5, ttl // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            cur = await redis.get(key)
            if isinstance(cur, bytes):
                cur = cur.decode()
            if str(cur) != value:
                raise RuntimeError(f"Lock boshqanikiga o'tdi yoki yo'qoldi: {cur} != {value}")
            await redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.error(f"Lock refresh xato: {e}")
            # Xato bo'lsa instansiyani o'ldiramiz, platforma toza holatda qayta ko'taradi
            sys.exit(1) 


# =================== DISPATCHER ===================
def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

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
    dp.include_router(filial_router)
    dp.include_router(reklama_router)

    return dp


# =================== MAIN ===================
async def main():
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN yo'q!")
        sys.exit(1)

    http_runner = await start_http_server()

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=AiohttpSession(timeout=60)
    )
    await bot.delete_webhook(drop_pending_updates=True)
    
    dp = setup_dispatcher()
    await set_bot_commands(bot)

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
        logger.error(f"Upstash Redis ulanishida xato: {e}")
        # Redis bo'lmasa instansiya ishlay olmaydi, abadiy kutish emas, xato bilan chiqamiz.
        sys.exit(1)

    # 1. Takeover mexanizmi (Active Waiting)
    logger.info("Lock tekshirilmoqda...")
    got_lock = await acquire_lock(redis, lock_key, lock_value, ttl=60)
    
    while not got_lock:
        logger.warning("Lock band. Bu instance HTTP server sifatida ishlaydi. 15s dan keyin lock'ni qayta tekshiramiz...")
        await asyncio.sleep(15)
        got_lock = await acquire_lock(redis, lock_key, lock_value, ttl=60)

    logger.info("Lock olindi. Polling shu instanceda ishlaydi.")

    lock_task = asyncio.create_task(
        refresh_lock_loop(redis, lock_key, lock_value, ttl=60)
    )

    scheduler = None
    with suppress(Exception):
        scheduler = setup_scheduler(bot)

    me = await bot.get_me()
    logger.info(f"Bot ishga tushdi: @{me.username}")

    try:
        # 2. Aiogram o'zi network errorlarni hal qiladi, while True kerak emas
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
        )
    except TelegramConflictError:
        logger.critical("Konflikt! Lock mexanizmi ishlamadi, boshqa bot instansiyasi polling qilyapti. O'chirilmoqda...")
        sys.exit(1)
    finally:
        lock_task.cancel()
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
        logger.info("Tizim to'xtatildi")
    except Exception as e:
        logger.exception(f"Fatal xato: {e}")
