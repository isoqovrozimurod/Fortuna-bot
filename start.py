from __future__ import annotations

import json
import os
import contextlib
from pathlib import Path

from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

router = Router()

CHANNEL_FILE = "channels.json"
TEMP_DIR = Path(__file__).resolve().parent / "temp"
PROMO_IMAGE = TEMP_DIR / "fortuna.jpg"


# ================= FILE =================

def load_channels():
    if not os.path.exists(CHANNEL_FILE):
        return []
    try:
        with open(CHANNEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


# ================= UI =================

def subscription_markup(channels):
    buttons = []

    for ch in channels:
        if ch.startswith("@"):
            url = f"https://t.me/{ch[1:]}"
        else:
            url = f"https://t.me/c/{str(ch)[4:]}"
        buttons.append([InlineKeyboardButton(text=f"🔔 {ch}", url=url)])

    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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


# ================= CHECK =================

async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    channels = load_channels()
    if not channels:
        return True

    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked"):
                return False
        except TelegramBadRequest:
            return False

    return True


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
    user_id = message.from_user.id
    channels = load_channels()

    if channels and not await is_user_subscribed(bot, user_id):
        await message.answer(
            "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
            reply_markup=subscription_markup(channels)
        )
        return

    await send_promo(bot, user_id)


# ================= CHECK BUTTON =================

@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    channels = load_channels()

    if await is_user_subscribed(bot, user_id):
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await send_promo(bot, user_id)
    else:
        with contextlib.suppress(Exception):
            await callback.message.delete()
        await bot.send_message(
            user_id,
            "❗ Avval kanallarga obuna bo‘ling:",
            reply_markup=subscription_markup(channels)
        )


# ================= ORTGA =================

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
