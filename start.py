from __future__ import annotations

import contextlib
from pathlib import Path

from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

router = Router()

TEMP_DIR = Path(__file__).resolve().parent / "temp"
PROMO_IMAGE = TEMP_DIR / "fortuna.jpg"


# ================= UI =================

def main_menu_markup():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Kredit turlari", callback_data="credit_types"),
                InlineKeyboardButton(text="📞 Bog'lanish", callback_data="contact"),
            ]
        ]
    )


def promo_caption():
    return (
        "<b>✅FORTUNA BIZNES ENDI G'ALLAOROLDA<b>\n\n"
        "💸SIZGA PUL KERAKMI? MUAMMOSIZ, 2 SOATDA NAQD PULDA KREDIT OLING\n\n"
        "🌐 FORTUNA BIZNES mikromoliya tashkiloti G'ALLAOROL filiali har doim sizga yordam berishga tayyor\n"
        "🗄Naqt pul ko'rinishidagi mikroqarzlar\n"
        "💎\"Fortuna Biznes\" mikromoliya tashkiloti G'ALLAOROL filiali bilan moliyaviy muammolaringizni tez va oson xal qiling\n\n"
        "☎️+998551510040\n"
        "📱+998992510040      24/7⏳\n"
        "☎️+998724321500\n"
        "📱+998953754540      24/7⏳\n"
        "@Gallaorol_FB\n\n"
        "Ish vaqti dushanbadan jumagacha 09:00 dan 18:00 gacha\n"
        "📍Manzil: G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy\n"
        "🔎Mo'ljal: 1-son Sport maktabi yonida\n"
    )


# ================= PROMO =================

async def send_promo(bot: Bot, user_id: int):
    if PROMO_IMAGE.exists():
        await bot.send_photo(
            user_id,
            FSInputFile(PROMO_IMAGE),
            caption=promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML
        )
    else:
        await bot.send_message(
            user_id,
            promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML
        )


# ================= /start =================

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    await send_promo(bot, message.from_user.id)


# ================= Ortga =================

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
