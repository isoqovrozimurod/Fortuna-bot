from __future__ import annotations

import os
import time
import logging
import asyncio
import contextlib

from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from broadcast import save_user, user_has_phone

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))   # admin gate'dan mustasno

PROMPT_TEXT = (
    "📱 <b>Botdan foydalanish uchun telefon raqamingizni tasdiqlang.</b>\n\n"
    "Quyidagi tugmani bosib, raqamingizni ulashing:"
)

PROMPT_COOLDOWN_SECONDS = 10   # shu vaqt ichida qayta prompt yuborilmaydi

# Bir marta tasdiqlangan foydalanuvchilar shu yerda keshlanadi.
_verified_cache: set[int] = set()

# Har bir foydalanuvchi uchun oxirgi marta prompt yuborilgan vaqt —
# ikki marta so'rashning oldini olish uchun.
_last_prompt_at: dict[int, float] = {}

# Har bir foydalanuvchi uchun alohida navbat (lock) — parallel kelgan
# ikkita update bir vaqtda tekshiruv/prompt yubormasin.
_user_locks: dict[int, asyncio.Lock] = {}


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni ulashish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


async def _is_verified_safe(user_id: int) -> bool:
    """
    Telefon tasdiqlanganini tekshiradi.
    XATO BO'LSA — bloklamaydi (True qaytaradi, ya'ni "o'tkazib yuborish").
    """
    if user_id in _verified_cache:
        return True
    try:
        verified = await user_has_phone(user_id)
    except Exception as e:
        logger.error(f"phone_gate: tekshiruvda xato — bloklanmaydi (fail-open): {e}")
        return True
    if verified:
        _verified_cache.add(user_id)
    return verified


def mark_verified(user_id: int) -> None:
    """Boshqa modullar ham (kerak bo'lsa) foydalanuvchini tasdiqlangan deb belgilashi uchun."""
    _verified_cache.add(user_id)
    _last_prompt_at.pop(user_id, None)


class PhoneGateMiddleware(BaseMiddleware):
    """
    Har bir shaxsiy xabar/callback uchun telefon tasdig'ini tekshiradi.
    Guruh xabarlariga, admin'ga va kontakt xabarining o'ziga tegmaydi.
    """

    async def __call__(self, handler, event, data):
        try:
            bot = data.get("bot")
            if not isinstance(event, (Message, CallbackQuery)):
                return await handler(event, data)

            user = event.from_user
            if user is None or user.is_bot:
                return await handler(event, data)

            chat = event.chat if isinstance(event, Message) else event.message.chat
            if chat.type != "private":
                return await handler(event, data)   # guruhlarda tekshirmaymiz

            if ADMIN_ID and user.id == ADMIN_ID:
                return await handler(event, data)   # admin mustasno

            # Kontaktning o'zi — pastdagi on_contact_shared handleriga o'tkazamiz
            if isinstance(event, Message) and event.contact:
                return await handler(event, data)

            # Kesh orqali tez yo'l — lock kerak emas
            if user.id in _verified_cache:
                return await handler(event, data)

            # ── Bu yerdan boshlab NAVBAT (lock) ichida ishlaymiz ──
            # Shu orqali bir foydalanuvchidan tez-tez (deyarli bir vaqtda)
            # kelgan ikkita update bir-birini kutadi, parallel ikkita
            # Sheets tekshiruvi/ikkita prompt yubormaydi.
            async with _get_lock(user.id):
                # Navbatda kutib turgan payt boshqa update allaqachon
                # tasdiqlagan bo'lishi mumkin — qayta tekshiramiz.
                if await _is_verified_safe(user.id):
                    return await handler(event, data)

                text = (event.text or "") if isinstance(event, Message) else ""
                if isinstance(event, Message) and text.startswith("/start"):
                    with contextlib.suppress(Exception):
                        await save_user(
                            user_id=user.id,
                            full_name=user.full_name or "",
                            username=user.username or "",
                        )

                # Sovutish vaqti — yaqinda prompt yuborilgan bo'lsa, qayta yubormaymiz
                now  = time.monotonic()
                last = _last_prompt_at.get(user.id, 0.0)
                if (now - last) >= PROMPT_COOLDOWN_SECONDS:
                    _last_prompt_at[user.id] = now
                    if bot:
                        with contextlib.suppress(Exception):
                            await bot.send_message(
                                user.id, PROMPT_TEXT,
                                reply_markup=_phone_kb(), parse_mode="HTML",
                            )

                if isinstance(event, CallbackQuery):
                    with contextlib.suppress(Exception):
                        await event.answer()
                return   # handler'ga O'TKAZMAYMIZ

        except Exception as e:
            # MUHIM: middleware'ning o'zida kutilmagan xato bo'lsa ham
            # butun botni to'xtatib qo'ymaymiz — o'tkazib yuboramiz.
            logger.error(f"phone_gate middleware xato — o'tkazib yuborildi: {e}")
            return await handler(event, data)


# MUHIM (modullararo to'qnashuv tuzatildi):
# Bu handlerga AVVAL hech qanday cheklov yo'q edi — ya'ni shaxsiy chatdagi
# HAR QANDAY kontakt xabarini ushlab qolardi. main.py da phone_gate_router
# personal_message_router dan OLDIN ulangani uchun, admin /xabar buyrug'i
# ichida "📱 Telefon kontaktidan" orqali kontakt ulashganda, o'sha kontakt
# shu yerga tushib ketardi va personal_message ning
# PersonalMsgFSM.waiting_contact handleri UMUMAN ishga tushmasdi.
# Natijada "Telefon kontaktidan" tanlash butunlay ishlamay turgan edi.
#
# Admin allaqachon telefon tekshiruvidan ozod (middleware uni o'tkazib
# yuboradi), shuning uchun uning kontaktlari bu yerda umuman
# ushlanmasligi kerak — filtrda chetlab o'tamiz.
@router.message(
    F.chat.type == "private",
    F.contact,
    F.from_user.id != ADMIN_ID,
)
async def on_contact_shared(message: Message, bot: Bot) -> None:
    """Foydalanuvchi kontaktni ulashganda ishga tushadi."""
    contact = message.contact
    user    = message.from_user

    if contact.user_id and contact.user_id != user.id:
        await message.answer(
            "⚠️ Bu boshqa odamning kontakti. Iltimos, <b>faqat o'zingizning</b> "
            "raqamingizni yuboring.",
            reply_markup=_phone_kb(), parse_mode="HTML",
        )
        return

    # Shu foydalanuvchi uchun navbatni ham egallaymiz — shu bilan
    # middleware tomondan parallel kelayotgan tekshiruv bilan
    # to'qnashmaydi (masalan, kontakt bilan bir vaqtda boshqa xabar
    # kelib qolsa).
    async with _get_lock(user.id):
        with contextlib.suppress(Exception):
            await save_user(
                user_id=user.id,
                full_name=user.full_name or "",
                username=user.username or "",
                phone=contact.phone_number or "",
            )
        # Sheets yozuvi muvaffaqiyatsiz bo'lsa ham — foydalanuvchi
        # bloklanib qolmasin, kesh orqali darhol "tasdiqlangan" deb
        # belgilaymiz (bu ham prompt-cooldown'ni tozalaydi).
        mark_verified(user.id)

    await message.answer(
        "✅ <b>Raqamingiz tasdiqlandi!</b>",
        reply_markup=ReplyKeyboardRemove(), parse_mode="HTML",
    )

    with contextlib.suppress(Exception):
        from start import send_promo
        await send_promo(bot, user.id)
