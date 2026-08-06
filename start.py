from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
)

from broadcast import save_user

logger = logging.getLogger(__name__)
router = Router()

TEMP_DIR    = Path(__file__).resolve().parent / "temp"
PROMO_IMAGE = TEMP_DIR / "fortuna.jpg"

# Birinchi muvaffaqiyatli yuklashdan keyin Telegram qaytargan file_id
# shu yerda keshlanadi. Bot qayta ishga tushganda (deploy/restart)
# tozalanadi — shundan keyingi BIRINCHI /start yana to'liq yuklaydi,
# undan keyingisi tez ishlaydi.
_cached_file_id: str | None = None


def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Kredit turlari", callback_data="credit_types"),
            InlineKeyboardButton(text="📞 Bog'lanish",     callback_data="contact"),
        ],
        [InlineKeyboardButton(text="📍 Filiallar", callback_data="branches")],
    ])


def promo_caption() -> str:
    return (
        "<b>✅FORTUNA BIZNES ENDI G'ALLAOROLDA</b>\n\n"
        "💸SIZGA PUL KERAKMI? MUAMMOSIZ, 2 SOATDA NAQD PULDA KREDIT OLING\n\n"
        "🌐 FORTUNA BIZNES mikromoliya tashkiloti G'ALLAOROL filiali har doim "
        "sizga yordam berishga tayyor\n"
        "🗄Naqt pul ko'rinishidagi mikroqarzlar\n"
        "💎\"Fortuna Biznes\" mikromoliya tashkiloti G'ALLAOROL filiali bilan "
        "moliyaviy muammolaringizni tez va oson xal qiling\n\n"
        "☎️+998551510040\n"
        "📱+998992510040      24/7⏳\n"
        "☎️+998724321500\n"
        "📱+998953754540      24/7⏳\n"
        "@Gallaorol_FB\n\n"
        "Ish vaqti dushanbadan jumagacha 09:00 dan 18:00 gacha\n"
        "📍Manzil: G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy\n"
        "🔎Mo'ljal: 1-Son Sport maktabi yonida\n"
    )


async def send_promo(bot: Bot, user_id: int) -> None:
    global _cached_file_id

    caption = promo_caption()
    markup  = main_menu_markup()

    if _cached_file_id:
        try:
            await bot.send_photo(
                user_id, _cached_file_id,
                caption=caption, reply_markup=markup, parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            logger.warning(f"Keshlangan file_id ishlamadi, qayta yuklaymiz: {e}")
            _cached_file_id = None

    if PROMO_IMAGE.exists():
        try:
            sent = await bot.send_photo(
                user_id, FSInputFile(PROMO_IMAGE),
                caption=caption, reply_markup=markup, parse_mode=ParseMode.HTML,
            )
            if sent.photo:
                _cached_file_id = sent.photo[-1].file_id
            return
        except Exception as e:
            logger.error(f"send_photo xato, matn bilan davom etamiz: {e}")

    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id, caption, reply_markup=markup, parse_mode=ParseMode.HTML,
        )

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    await save_user(
        user_id=user.id,
        full_name=user.full_name or "",
        username=user.username or "",
    )
    await send_promo(bot, user.id)

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
