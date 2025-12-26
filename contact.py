from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

router = Router()

# Lokatsiya koordinatalari (aniq manzil uchun)
LATITUDE = 40.024357
LONGITUDE = 67.589176

# Kontakt matni
CONTACT_TEXT = (
    "Ish vaqti dushanbadan jumagacha 09:00 dan 18:00 gacha\n"
    "📍Manzil: G'allaorol tumani, G'.G'ulom MFY Mustaqillik ko'chasi 28-uy\n"
    "🔎Mo'ljal: 1-son Sport maktabi yonida\n"
    "☎️+998551510040\n"
    "📱+998992510040      24/7⏳\n"
    "☎️+998724321500\n"
    "📱+998953754540      24/7⏳\n"
    "@Gallaorol_FB"
)

# Ortga tugmasi
back_markup = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="back_to_menu")]
    ]
)

# Callback orqali tugma bosilganda
@router.callback_query(F.data == "contact")
async def show_contact(callback: CallbackQuery, bot: Bot):
    await bot.send_location(
        chat_id=callback.from_user.id,
        latitude=LATITUDE,
        longitude=LONGITUDE,
    )

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=CONTACT_TEXT,
        reply_markup=back_markup
    )

# /manzil komandasi orqali
@router.message(Command("manzil"))
async def cmd_manzil(message: Message, bot: Bot):
    await bot.send_location(
        chat_id=message.chat.id,
        latitude=LATITUDE,
        longitude=LONGITUDE,
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=CONTACT_TEXT,
        reply_markup=back_markup
    )
