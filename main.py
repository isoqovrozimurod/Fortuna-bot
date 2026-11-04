
import os
import sys
import uuid
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

from upstash_redis.asyncio import Redis

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
from control import router as control_router, setup_control_scheduler
from chanel import router as chanel_router, SubscriptionMiddleware
from kredit import router as kredit_admin_router
from hamkor import router as hamkor_router
from avto_drive import router as avto_drive_router
from taxi_bandlik import router as taxi_bandlik_router
from oila import router as oila_router
from filial import router as filial_router
from reklama_nazorati import router as reklama_router, setup_scheduler
from broadcast import router as broadcast_router
from download import router as download_router
from scoring import router as scoring_router
from personal_message import router as personal_message_router
from post.handlers import router as post_router
from post.scheduler import setup_scheduler as setup_post_scheduler
from phone_gate import router as phone_gate_router, PhoneGateMiddleware


# =================== LOGGING ===================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("FortunaBot")


# =================== HTTP SERVER ===================

async def _handle_root(request: web.Request) -> web.Response:
    return web.Response(
        text="Fortuna-bot is running",
        content_type="text/plain",
    )


async def start_http_server() -> web.AppRunner:
    port = int(os.getenv("PORT", "8000"))

    app = web.Application()
    app.router.add_get("/", _handle_root)
    app.router.add_get("/healthz", _handle_root)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port,
    )

    await site.start()

    logger.info("HTTP server started on 0.0.0.0:%s", port)

    return runner


# =================== REDIS ===================

def build_redis() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

    if not url or not token:
        raise RuntimeError(
            "UPSTASH_REDIS_REST_URL va UPSTASH_REDIS_REST_TOKEN kerak"
        )

    return Redis(
        url=url,
        token=token,
    )


# Lockni olish:
# True  - lock olindi
# False - lock boshqa instansiyada band
# None  - Redis bilan bog'lanishda xato

async def acquire_lock(
    redis: Redis,
    key: str,
    value: str,
    ttl: int,
):
    try:
        result = await redis.set(
            key,
            value,
            ex=ttl,
            nx=True,
        )

        return bool(result)

    except Exception as e:
        logger.error("Redis lock olishda xato: %s", e)
        return None


# Lockni faqat o'z egasi yangilashi mumkin.
# GET + SET o'rniga atomar Lua skripti ishlatiladi.

REFRESH_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], ARGV[2])
end

return 0
"""


async def refresh_lock(
    redis: Redis,
    key: str,
    value: str,
    ttl: int,
) -> bool:
    result = await redis.eval(
        REFRESH_LOCK_SCRIPT,
        1,
        key,
        value,
        ttl,
    )

    return bool(result)


# Lockni faqat o'z egasi o'chirishi mumkin.

RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end

return 0
"""


async def release_lock(
    redis: Redis,
    key: str,
    value: str,
):
    try:
        await redis.eval(
            RELEASE_LOCK_SCRIPT,
            1,
            key,
            value,
        )

        logger.info("Redis lock bo'shatildi: %s", key)

    except Exception as e:
        logger.warning(
            "Redis lockni bo'shatishda xato: %s",
            e,
        )


# Lockni avtomatik yangilash.

async def refresh_lock_loop(
    redis: Redis,
    key: str,
    value: str,
    ttl: int,
    stop_on_error: bool = False,
    on_lock_lost=None,
):
    interval = max(5, ttl // 2)
    retry_delay = 5

    while True:
        await asyncio.sleep(interval)

        try:
            refreshed = await refresh_lock(
                redis,
                key,
                value,
                ttl,
            )

            if not refreshed:
                logger.critical(
                    "Lock yo'qotildi yoki boshqa instansiyaga o'tdi: %s",
                    key,
                )

                if on_lock_lost:
                    on_lock_lost()

                return

            retry_delay = 5

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.error(
                "Lock yangilashda xato (%s): %s",
                key,
                e,
            )

            # Scheduler locki yangilanmasa,
            # takroriy vazifalar xavfini oldini olamiz.
            if stop_on_error:
                logger.critical(
                    "Scheduler lock yangilanmadi. Schedulerlar to'xtatiladi."
                )

                if on_lock_lost:
                    on_lock_lost()

                return

            # Polling locki uchun vaqtinchalik xatolarda
            # botni darhol to'xtatmaymiz.
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


# =================== DISPATCHER ===================

def setup_dispatcher() -> Dispatcher:
    dp = Dispatcher(
        storage=MemoryStorage(),
    )

    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.message.middleware(PhoneGateMiddleware())
    dp.callback_query.middleware(PhoneGateMiddleware())

    dp.include_router(phone_gate_router)
    dp.include_router(chanel_router)
    dp.include_router(control_router)
    dp.include_router(reklama_router)
    dp.include_router(start_router)
    dp.include_router(contact_router)
    dp.include_router(kredit_router)
    dp.include_router(pensiya_router)
    dp.include_router(ish_haqi_router)
    dp.include_router(garov_router)
    dp.include_router(biznes_router)
    dp.include_router(hamkor_router)
    dp.include_router(avto_drive_router)
    dp.include_router(taxi_bandlik_router)
    dp.include_router(oila_router)
    dp.include_router(calc_router)
    dp.include_router(valyuta_router)
    dp.include_router(vakansiya_router)
    dp.include_router(kredit_admin_router)
    dp.include_router(filial_router)
    dp.include_router(broadcast_router)
    dp.include_router(download_router)
    dp.include_router(scoring_router)
    dp.include_router(personal_message_router)
    dp.include_router(post_router)

    return dp


# =================== SCHEDULER MANAGEMENT ===================

def stop_schedulers(schedulers: list):
    for scheduler in schedulers:
        if scheduler is None:
            continue

        try:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler to'xtatildi.")

        except Exception as e:
            logger.warning(
                "Schedulerni to'xtatishda xato: %s",
                e,
            )


def start_schedulers(bot: Bot) -> list:
    schedulers = []

    # Reklama nazorati scheduleri
    try:
        scheduler = setup_scheduler(bot)

        if scheduler:
            schedulers.append(scheduler)

        logger.info("Reklama scheduleri ishga tushirildi.")

    except Exception:
        logger.exception(
            "Reklama schedulerini ishga tushirishda xato."
        )

    # Control scheduleri
    try:
        scheduler = setup_control_scheduler(bot)

        if scheduler:
            schedulers.append(scheduler)

        logger.info("Control scheduleri ishga tushirildi.")

    except Exception:
        logger.exception(
            "Control schedulerini ishga tushirishda xato."
        )

    # Post scheduleri
    try:
        scheduler = setup_post_scheduler(bot)

        if scheduler:
            scheduler.start()
            schedulers.append(scheduler)

        logger.info("Post scheduleri ishga tushirildi.")

    except Exception:
        logger.exception(
            "Post schedulerini ishga tushirishda xato."
        )

    return schedulers


# =================== MAIN ===================

async def main():
    load_dotenv()

    token = os.getenv("BOT_TOKEN")

    if not token:
        logger.critical("BOT_TOKEN topilmadi!")
        raise SystemExit(1)

    http_runner = None
    bot = None
    redis = None

    polling_lock_key = None
    polling_lock_value = None

    scheduler_lock_key = "fortuna:scheduler:lock"
    scheduler_lock_value = None

    polling_lock_task = None
    scheduler_lock_task = None

    schedulers = []

    try:
        # HTTP server
        http_runner = await start_http_server()

        # Bot
        bot = Bot(
            token=token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
            ),
            session=AiohttpSession(
                timeout=60,
            ),
        )

        # Webhookni o'chirish
        for attempt in range(3):
            try:
                await bot.delete_webhook(
                    drop_pending_updates=True,
                )

                logger.info("Webhook o'chirildi.")
                break

            except Exception as e:
                logger.warning(
                    "delete_webhook urinish %s/3: %s",
                    attempt + 1,
                    e,
                )

                if attempt < 2:
                    await asyncio.sleep(5)

                else:
                    logger.warning(
                        "Webhook o'chirilmadi. Polling davom ettiriladi."
                    )

        # Dispatcher
        dp = setup_dispatcher()

        # Telegram buyruqlari
        try:
            await set_bot_commands(bot)

        except Exception as e:
            logger.warning(
                "Buyruqlarni o'rnatishda xato: %s",
                e,
            )

        # Redis ulanishi
        try:
            redis = build_redis()
            logger.info("Redis obyekti yaratildi.")

        except Exception as e:
            logger.error(
                "Redis mavjud emas. Bot schedulerlarsiz ishlaydi: %s",
                e,
            )

        # Instansiya identifikatori
        instance_id = (
            os.getenv("KOYEB_DEPLOYMENT_ID")
            or os.getenv("RENDER_INSTANCE_ID")
            or str(os.getpid())
        )

        unique_id = uuid.uuid4().hex

        polling_lock_key = f"fortuna:polling:lock:{token[:10]}"
        polling_lock_value = f"{instance_id}:{unique_id}"

        # =================== POLLING LOCK ===================

        polling_lock_acquired = False
        redis_available = redis is not None

        if redis_available:
            logger.info("Polling lock tekshirilmoqda...")

            retry_delay = 15

            while True:
                result = await acquire_lock(
                    redis,
                    polling_lock_key,
                    polling_lock_value,
                    ttl=90,
                )

                if result is True:
                    polling_lock_acquired = True

                    logger.info(
                        "Polling lock olindi. Instansiya: %s",
                        instance_id,
                    )

                    break

                if result is None:
                    # Redis xatosi lock bandligini anglatmaydi.
                    # Pollingni Redisga bog'lab qo'ymaymiz.
                    redis_available = False

                    logger.warning(
                        "Redis vaqtincha ishlamayapti. "
                        "Polling lock tekshiruvi o'tkazib yuborildi."
                    )

                    break

                # False - lock boshqa instansiyada band.
                logger.warning(
                    "Polling lock band. %s soniyadan keyin qayta tekshiriladi.",
                    retry_delay,
                )

                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay + 5, 60)

        # Polling lock olgan bo'lsak, uni yangilab turamiz.
        if polling_lock_acquired:
            polling_lock_task = asyncio.create_task(
                refresh_lock_loop(
                    redis,
                    polling_lock_key,
                    polling_lock_value,
                    ttl=90,
                )
            )

        # =================== SCHEDULER LOCK ===================

        scheduler_lock_acquired = False

        if redis_available and polling_lock_acquired:
            scheduler_lock_value = f"{instance_id}:{unique_id}"

            logger.info("Umumiy scheduler lock tekshirilmoqda...")

            result = await acquire_lock(
                redis,
                scheduler_lock_key,
                scheduler_lock_value,
                ttl=120,
            )

            if result is True:
                scheduler_lock_acquired = True

                logger.info(
                    "Umumiy scheduler lock olindi. "
                    "Schedulerlar shu instansiyada ishlaydi."
                )

            elif result is False:
                logger.info(
                    "Umumiy scheduler lock boshqa serverda. "
                    "Bu server schedulerlarni ishga tushirmaydi."
                )

            else:
                logger.warning(
                    "Scheduler lock olishda Redis xatosi. "
                    "Schedulerlar ishga tushirilmaydi."
                )

        elif not polling_lock_acquired and redis_available:
            logger.warning(
                "Polling lock olinmagan. Schedulerlar ishga tushirilmaydi."
            )

        else:
            logger.warning(
                "Redis mavjud emas. Schedulerlar ishga tushirilmaydi."
            )

        # =================== SCHEDULERS ===================

        if scheduler_lock_acquired:
            schedulers = start_schedulers(bot)

            # Scheduler lock yo'qotilsa, barcha schedulerlar to'xtatiladi.
            def on_scheduler_lock_lost():
                stop_schedulers(schedulers)

            scheduler_lock_task = asyncio.create_task(
                refresh_lock_loop(
                    redis,
                    scheduler_lock_key,
                    scheduler_lock_value,
                    ttl=120,
                    stop_on_error=True,
                    on_lock_lost=on_scheduler_lock_lost,
                )
            )

        # =================== BOT CHECK ===================

        try:
            me = await bot.get_me()

            logger.info(
                "Bot ishga tushdi: @%s",
                me.username,
            )

        except Exception as e:
            logger.warning(
                "get_me xatosi: %s",
                e,
            )

        # =================== POLLING ===================

        logger.info("Telegram polling boshlanmoqda...")

        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "my_chat_member",
            ],
        )

    except TelegramConflictError:
        logger.critical(
            "Telegram polling konflikti! "
            "Ushbu bot tokeni bilan boshqa polling instansiyasi ishlayapti."
        )

    except asyncio.CancelledError:
        logger.info("Bot vazifasi bekor qilindi.")
        raise

    except Exception:
        logger.exception("MAIN jarayonida kutilmagan xato.")

    finally:
        logger.info("Bot to'xtatilmoqda...")

        # Lock yangilash vazifalarini to'xtatish
        for task in (
            polling_lock_task,
            scheduler_lock_task,
        ):
            if task:
                task.cancel()

                with suppress(asyncio.CancelledError):
                    await task

        # Schedulerlarni to'xtatish
        stop_schedulers(schedulers)

        # Locklarni bo'shatish
        if redis and polling_lock_acquired:
            await release_lock(
                redis,
                polling_lock_key,
                polling_lock_value,
            )

        if redis and scheduler_lock_acquired:
            await release_lock(
                redis,
                scheduler_lock_key,
                scheduler_lock_value,
            )

        # HTTP serverni yopish
        if http_runner:
            with suppress(Exception):
                await http_runner.cleanup()

        # Bot sessiyasini yopish
        if bot:
            with suppress(Exception):
                await bot.session.close()

        logger.info("Bot to'xtatildi.")


# =================== ENTRY POINT ===================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Tizim foydalanuvchi tomonidan to'xtatildi.")

    except SystemExit:
        raise

    except Exception:
        logger.exception("Fatal xato.")
