"""
phone_gate.py — Telefon raqamini tasdiqlash (mustaqil modul).
"""
from __future__ import annotations

import os
import logging
import contextlib
import asyncio

from aiogram import Router, F, Bot, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from broadcast import save_user, user_has_phone

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PROMPT_TEXT = (
    "📱 <b>Botdan foydalanish uchun telefon raqamingizni tasdiqlang.</b>\n\n"
    "Quyidagi tugmani bosib, raqamingizni ulashing:"
)

_verified_cache: set[int] = set()
_processing_users: set[int] = set()
_processing_lock = asyncio.Lock()


def _phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="📱 Raqamni ulashish",
                request_contact=True,
            )]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _is_verified_safe(user_id: int) -> bool:
    """
    Telefon tasdiqlanganini tekshiradi.
    Sheets ishlamasa — foydalanuvchini vaqtincha bloklamaydi.
    """
    if user_id in _verified_cache:
        return True

    try:
        verified = await user_has_phone(user_id)
    except Exception as e:
        logger.error(
            f"phone_gate: tekshiruvda xato — bloklanmaydi: {e}"
        )
        return True

    if verified:
        _verified_cache.add(user_id)

    return verified


def mark_verified(user_id: int) -> None:
    """Foydalanuvchini tasdiqlangan holatda cache'ga qo'shadi."""
    _verified_cache.add(user_id)


class PhoneGateMiddleware(BaseMiddleware):
    """
    Har bir shaxsiy xabar/callback uchun telefon tasdig'ini tekshiradi.
    Guruhlar, admin va kontakt xabarining o'zi tekshirilmaydi.
    """

    async def __call__(self, handler, event, data):
        try:
            bot = data.get("bot")

            if not isinstance(event, (Message, CallbackQuery)):
                return await handler(event, data)

            user = event.from_user

            if user is None or user.is_bot:
                return await handler(event, data)

            chat = (
                event.chat
                if isinstance(event, Message)
                else event.message.chat
            )

            if chat.type != "private":
                return await handler(event, data)

            if ADMIN_ID and user.id == ADMIN_ID:
                return await handler(event, data)

            if isinstance(event, Message) and event.contact:
                return await handler(event, data)

            if await _is_verified_safe(user.id):
                return await handler(event, data)

            text = event.text or "" if isinstance(event, Message) else ""

            if isinstance(event, Message) and text.startswith("/start"):
                with contextlib.suppress(Exception):
                    await save_user(
                        user_id=user.id,
                        full_name=user.full_name or "",
                        username=user.username or "",
                    )

            if bot:
                with contextlib.suppress(Exception):
                    await bot.send_message(
                        user.id,
                        PROMPT_TEXT,
                        reply_markup=_phone_kb(),
                        parse_mode="HTML",
                    )

            if isinstance(event, CallbackQuery):
                with contextlib.suppress(Exception):
                    await event.answer()

            return

        except Exception as e:
            logger.error(
                f"phone_gate middleware xato — o'tkazib yuborildi: {e}"
            )
            return await handler(event, data)


@router.message(F.chat.type == "private", F.contact)
async def on_contact_shared(message: Message, bot: Bot) -> None:
    """Foydalanuvchi kontaktni ulashganda ishga tushadi."""
    contact = message.contact
    user = message.from_user

    if not user:
        return

    # Bir foydalanuvchining kontaktini bir vaqtning o'zida
    # ikki marta qayta ishlashga yo'l qo'ymaymiz.
    async with _processing_lock:
        if user.id in _processing_users:
            await message.answer(
                "⏳ Raqamingiz qayta ishlanmoqda. Iltimos, kuting."
            )
            return

        _processing_users.add(user.id)

    try:
        if contact.user_id and contact.user_id != user.id:
            await message.answer(
                "⚠️ Bu boshqa odamning kontakti. Iltimos, "
                "<b>faqat o'zingizning</b> raqamingizni yuboring.",
                reply_markup=_phone_kb(),
                parse_mode="HTML",
            )
            return

        # Avval Sheets'ga yozamiz.
        saved = await save_user(
            user_id=user.id,
            full_name=user.full_name or "",
            username=user.username or "",
            phone=contact.phone_number or "",
        )

        # Sheets'ga yozish muvaffaqiyatsiz bo'lsa,
        # foydalanuvchini tasdiqlangan deb belgilamaymiz.
        if not saved:
            logger.error(
                f"phone_gate: telefonni Sheets'ga yozib bo'lmadi "
                f"(user_id={user.id})"
            )

            await message.answer(
                "❌ Telefon raqamingizni saqlashda xatolik yuz berdi.\n\n"
                "Iltimos, birozdan so'ng qayta urinib ko'ring.",
                reply_markup=_phone_kb(),
                parse_mode="HTML",
            )
            return

        # Faqat Sheets muvaffaqiyatli yozilgandan keyin tasdiqlaymiz.
        mark_verified(user.id)

        await message.answer(
            "✅ <b>Raqamingiz tasdiqlandi!</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )

        # Keyingi jarayon faqat yuqoridagi yozuv muvaffaqiyatli
        # tugagandan keyin bajariladi.
        with contextlib.suppress(Exception):
            from start import send_promo
            await send_promo(bot, user.id)

    finally:
        async with _processing_lock:
            _processing_users.discard(user.id)
