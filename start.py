from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
)

from broadcast import save_user, user_has_phone

router = Router()

TEMP_DIR = Path(__file__).resolve().parent / "temp"
PROMO_IMAGE = TEMP_DIR / "fortuna.jpg"


# ===================== FSM =====================

class StartFSM(StatesGroup):
    waiting_phone = State()


# ================= UI =================

def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Kredit turlari", callback_data="credit_types"),
                InlineKeyboardButton(text="📞 Bog'lanish", callback_data="contact"),
            ],
            [
                InlineKeyboardButton(text="📍 Filiallar", callback_data="branches"),
            ],
        ]
    )


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def promo_caption() -> str:
    return (
        "<b>✅FORTUNA BIZNES ENDI G'ALLAOROLDA</b>\n\n"
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
        "🔎Mo'ljal: 1-Son Sport maktabi yonida\n"
    )


# ================= PROMO =================

async def send_promo(bot: Bot, user_id: int) -> None:
    if PROMO_IMAGE.exists():
        await bot.send_photo(
            user_id,
            FSInputFile(PROMO_IMAGE),
            caption=promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            user_id,
            promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML,
        )


# ================= /start =================

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot, state: FSMContext):
    user = message.from_user

    # Avval foydalanuvchini ismini saqlаymiz (telefonsiz)
    asyncio.ensure_future(
        save_user(
            user_id=user.id,
            full_name=user.full_name or "",
            username=user.username or "",
        )
    )

    # Telefon raqami allaqachon bormi?
    has_phone = await user_has_phone(user.id)

    if has_phone:
        # Telefon bor — darhol menyu
        await send_promo(bot, user.id)
    else:
        # Telefon yo'q — so'raymiz
        await state.set_state(StartFSM.waiting_phone)
        await message.answer(
            "👋 Xush kelibsiz!\n\n"
            "Botdan foydalanish uchun telefon raqamingizni ulashing.\n"
            "Bu ma'lumot faqat biz bilan bog'lanish uchun ishlatiladi.",
            reply_markup=phone_request_kb(),
        )


# ================= TELEFON QABUL QILISH =================

@router.message(StartFSM.waiting_phone, F.contact)
async def handle_phone(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    phone = message.contact.phone_number

    asyncio.ensure_future(
        save_user(
            user_id=user.id,
            full_name=user.full_name or "",
            username=user.username or "",
            phone=phone,
        )
    )

    await message.answer(
        "✅ Rahmat! Ma'lumotlaringiz saqlandi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_promo(bot, user.id)



# ================= Ortga =================

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
