from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

router = Router()

# /product komandasi uchun
@router.message(Command("kredit_turlari"))
async def cmd_product(message: Message, bot: Bot):
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "💸 Kreditni quyidagi shaxslar olishlari mumkin:\n\n"
            "✅ Nafaqadagilar\n"
            "💼 Rasmiy daromadga ega shaxslar\n"
            "🚗 Avtomashina egalari"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Pensiya", callback_data="pensiya")],
                [InlineKeyboardButton(text="💼 Ish haqi", callback_data="ish_haqi")],
                [InlineKeyboardButton(text="🚗 Avtomashina garov", callback_data="garov")],
                [InlineKeyboardButton(text="⬅️ Ortga", callback_data="back_to_menu")]
            ]
        )
    )

# Kredit turlari tugmasi bosilganda
@router.callback_query(F.data == "credit_types")
async def show_credit_types(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    await bot.send_message(
        chat_id=callback.from_user.id,
        text=(
            "💸 Kreditni quyidagi shaxslar olishlari mumkin:\n\n"
            "✅ Nafaqadagilar\n"
            "💼 Rasmiy daromadga ega shaxslar\n"
            "🚗 Avtomashina egalari"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Pensiya", callback_data="pensiya")],
                [InlineKeyboardButton(text="💼 Ish haqi", callback_data="ish_haqi")],
                [InlineKeyboardButton(text="🚗 Avtomashina garov", callback_data="garov")],
                [InlineKeyboardButton(text="⬅️ Ortga", callback_data="back_to_menu")]
            ]
        )
    )
