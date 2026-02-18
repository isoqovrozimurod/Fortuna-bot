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


# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("FortunaBot")


# ---------------- HTTP SERVER (Koyeb/Render health) ----------------
async def _handle_root(request: web.Request) -> web.Response:
    return web.Response(text="Fortuna-bot is running ✅", content_type="text/plain")

async def _handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK", content_type="text/plain")

async def start_http_server() -> web.AppRunner:
    port = int(os.getenv("PORT", "8000"))
    app = web.Application()
    app.router.add_get("/", _handle_root)
    app.router.add_get("/healthz", _handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info(f"🌐 HTTP server started on 0.0.0.0:{port}")
    return runner


# ---------------- UPSTASH REDIS LOCK ----------------
def build_redis() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("UPSTASH_REDIS_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("UPSTASH_REDIS_TOKEN")
    if not url or not token:
        raise RuntimeError("Upstash env yo'q: UPSTASH_REDIS_REST_URL va UPSTASH_REDIS_REST_TOKEN kerak")
    return Redis(url=url, token=token)

async def acquire_lock(redis: Redis, key: str, value: str, ttl_sec: int) -> bool:
    """
    Upstash-redis REST: set(key, value, nx=True, ex=ttl)
    True bo'lsa lock olindi.
    """
    try:
        # upstash-redis python client: redis.set(key, value, ex=ttl_sec, nx=True)
        resp = redis.set(key, value, ex=ttl_sec, nx=True)
        # resp odatda "OK" yoki True qaytaradi
        return bool(resp)
    except Exception as e:
        logger.error(f"❌ Lock olishda xato: {e}")
        return False

async def refresh_lock_loop(redis: Redis, key: str, value: str, ttl_sec: int):
    """
    Lockni ushlab turish: har ttl/2 da expire yangilaymiz.
    Agar lock bizniki bo'lmay qolsa — pollingni to'xtatamiz.
    """
    interval = max(5, ttl_sec // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            cur = redis.get(key)
            if cur != value and str(cur) != str(value):
                raise RuntimeError("Lock boshqa instancega o'tib ketdi (cur != value)")
            redis.set(key, value, ex=ttl_sec)  # nx emas, refresh
        except Exception as e:
            logger.error(f"⛔ Lock refresh to'xtadi: {e}")
            raise


# ---------------- BOT SETUP ----------------
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
    dp.include_router(reklama_router)

    return dp


async def run_polling_with_retry(bot: Bot, dp: Dispatcher):
    """
    Agar boshqa joyda ham bot token bilan polling ketayotgan bo'lsa:
    TelegramConflictError chiqadi. Biz retry qilamiz, lekin lock faqat bittada bo'ladi.
    """
    while True:
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramConflictError as e:
            logger.error(f"⚠️ TelegramConflictError (2ta polling): {e}. 15 soniyadan keyin qayta urinaman.")
            await asyncio.sleep(15)
        except TelegramNetworkError as e:
            logger.error(f"⚠️ NetworkError: {e}. 5 soniyadan keyin qayta urinaman.")
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"❌ Pollingda noma'lum xato: {e}. 10 soniyadan keyin qayta urinaman.")
            await asyncio.sleep(10)


async def main():
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN yo'q. Platforma secrets/env ga qo'ying.")
        return

    # HTTP server har doim ishlasin (platforma o'chirmasin)
    http_runner = await start_http_server()

    # Bot init
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=True)

    dp = setup_dispatcher()
    await set_bot_commands(bot)

    # Distributed lock (faqat bitta polling)
    instance_id = os.getenv("KOYEB_DEPLOYMENT_ID") or os.getenv("RENDER_INSTANCE_ID") or str(os.getpid())
    lock_key = f"fortuna:polling_lock:{token[:10]}"   # token bo'yicha unique
    lock_value = f"{instance_id}"

    scheduler = None
    lock_task = None

    try:
        redis = build_redis()
    except Exception as e:
        # Upstash bo'lmasa ham bot ishlashi mumkin, lekin 2 joyda yurib qolsa yana conflict bo'ladi.
        logger.error(f"❌ Upstash Redis sozlanmagan: {e}")
        logger.error("➡️ Xavfsiz variant: Upstash'ni sozla. Hozircha pollingni ishlatmayman.")
        # Faqat HTTP server bilan yashab turamiz:
        await asyncio.Event().wait()

    # lock TTL 60s (refresh bilan doimiy)
    got_lock = await acquire_lock(redis, lock_key, lock_value, ttl_sec=60)

    if not got_lock:
        logger.warning("🟡 Bu instance pollingni olmaydi (lock band). Faqat HTTP server ishlaydi.")
        # Hech narsa qilmaymiz, service alive bo'lib turadi
        await asyncio.Event().wait()

    logger.info("✅ Lock olindi. Polling faqat shu instanceda ishlaydi.")

    # Lock refresh background
    lock_task = asyncio.create_task(refresh_lock_loop(redis, lock_key, lock_value, ttl_sec=60))

    # Scheduler faqat polling instanceda
    with suppress(Exception):
        scheduler = setup_scheduler(bot)
        if scheduler:
            logger.info("⏰ Scheduler started (only on lock holder)")

    # Polling
    try:
        await run_polling_with_retry(bot, dp)
    finally:
        if lock_task:
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
        logger.info("⛔ Bot stopped")
    except Exception as e:
        logger.exception(f"❌ Fatal error: {e}")
