from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)

router = Router()

BASE_DIR = Path(__file__).resolve().parent
BANNER = BASE_DIR / "temp" / "banner_barchasi.jpg"


def kredit_turlari_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Pensiya",           callback_data="pensiya")],
            [InlineKeyboardButton(text="💼 Ish haqi",          callback_data="ish_haqi")],
            [InlineKeyboardButton(text="🚗 Avtomashina garov", callback_data="garov")],
            [InlineKeyboardButton(text="🏢 Biznes uchun",      callback_data="biznes")],
            [InlineKeyboardButton(text="🤝 Hamkor",            callback_data="hamkor")],
            [InlineKeyboardButton(text="🚘 Avto-Drive",        callback_data="avto_drive")],
            [InlineKeyboardButton(text="🚖 Taxi-Bandlik",      callback_data="taxi_bandlik")],
            [InlineKeyboardButton(text="⬅️ Ortga",             callback_data="back_to_menu")],
        ]
    )


def kredit_text():
    return (
        "💸 <b>Kreditni quyidagi shaxslar olishlari mumkin:</b>\n\n"
        "✅ Pensionerlar\n"
        "💼 Rasmiy daromadga ega shaxslar\n"
        "🚗 Avtomashina egalari\n"
        "🏢 Biznes egalari\n"
        "🤝 Budjet tashkiloti xodimlari (Hamkor)\n"
        "🚘 Avto-Drive (avtomobil egalariga kichik mikroqarz)\n"
        "🚖 Taxi-Bandlik (taksi haydovchilari)"
    )


@router.message(Command("kredit_turlari"))
async def cmd_product(message: Message, bot: Bot):
    if BANNER.exists():
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=FSInputFile(BANNER),
            caption=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML"
        )


@router.callback_query(F.data == "credit_types")
async def show_credit_types(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    if BANNER.exists():
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=FSInputFile(BANNER),
            caption=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML"
        )
