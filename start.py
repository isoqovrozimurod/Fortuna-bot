from __future__ import annotations

"""start.py
Bosh menyu va majburiy obuna tekshiruvi.
`/start` buyrug‘i promo xabarini beradi.
"""

import os
import contextlib
from pathlib import Path
from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

router = Router()

# -------------------- Sozlamalar --------------------
REQUIRED_CHANNELS: list[tuple[str, str]] = [
    ("@isoqovrozimurod_blog", "📢 Kanal 1"),
    ("@FB_Gallaorolfiliali", "💬 Guruh 1"),
]

# -------------------- Yordamchi funksiyalar --------------------

def subscription_markup() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=text, url=f"https://t.me/{username.lstrip('@')}")]
        for username, text in REQUIRED_CHANNELS
    ]
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def promo_caption() -> str:
    return (
        "✅FORTUNA BIZNES ENDI G'ALLAOROLDA\n\n"
        "💸SIZGA PUL KERAKMI? MUAMMOSIZ, 2 SOATDA NAQD PULDA KREDIT OLING\n\n"
        "🌐 FORTUNA BIZNES mikromoliya tashkiloti G'ALLAOROL filiali har doim sizga yordam berishga tayyor\n"
        "🗄Naqt pul ko'rinishidagi mikroqarzlar\n"
        "💎\"Fortuna Biznes\" mikromoliya tashkiloti G'ALLAOROL filiali bilan moliyaviy muammolaringizni tez va oson xal qiling\n\n"
        "📍Manzil: G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy\n"
        "🔎Mo'ljal: 1-son sport maktabi yonida\n"
        "📞+998551510040\n"
        "📞+998992510040\n"
        "📞+998724321500\n"
        "@Gallaorol_FB"
    )


def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Kredit turlari", callback_data="credit_types"),
                InlineKeyboardButton(text="📞 Bog'lanish", callback_data="contact"),
            ]
        ]
    )


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    for channel, _ in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ("member", "administrator", "creator", "owner"):
                return False
        except TelegramBadRequest:
            return False
    return True


async def send_promo(bot: Bot, chat_id: int) -> None:
    img_path = Path(__file__).resolve().parent / "temp" / "fortuna.jpg"
    if not img_path.is_file():
        await bot.send_message(chat_id, "Rasm topilmadi: fortuna.jpg")
        return

    await bot.send_photo(
        chat_id=chat_id,
        photo=FSInputFile(img_path),
        caption=promo_caption(),
        reply_markup=main_menu_markup(),
        parse_mode=ParseMode.HTML,
    )

# -------------------- /start handler --------------------

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot):
    user_id = message.from_user.id
    if not await is_user_subscribed(bot, user_id):
        await message.answer(
            "<b>Quyidagi kanallarga obuna bo'ling.</b>",
            reply_markup=subscription_markup(),
            parse_mode=ParseMode.HTML,
        )
        return

    await send_promo(bot, user_id)

# -------------------- Tekshirish --------------------

@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if await is_user_subscribed(bot, user_id):
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await send_promo(bot, user_id)
    else:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await bot.send_message(
            chat_id=user_id,
            text="<b>Quyidagi kanallarga obuna bo'ling.</b>",
            reply_markup=subscription_markup(),
            parse_mode=ParseMode.HTML,
        )

# -------------------- Ortga tugmasi --------------------

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
