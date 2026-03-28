from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

router = Router()

LATITUDE  = 40.024361
LONGITUDE = 67.589167

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

back_markup = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Ortga")]],
    resize_keyboard=True,
)


async def _send_contact(chat_id: int, bot: Bot) -> None:
    await bot.send_location(chat_id=chat_id, latitude=LATITUDE, longitude=LONGITUDE)
    await bot.send_message(chat_id=chat_id, text=CONTACT_TEXT, reply_markup=back_markup)


@router.callback_query(F.data == "contact")
async def show_contact(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    await _send_contact(callback.from_user.id, bot)


@router.message(Command("manzil"))
async def cmd_manzil(message: Message, bot: Bot):
    await _send_contact(message.chat.id, bot)
