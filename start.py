from __future__ import annotations

import contextlib
import re
from pathlib import Path

from aiogram import Router, Bot, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, FSInputFile,
)

from broadcast import save_user, user_has_phone

router = Router()

TEMP_DIR    = Path(__file__).resolve().parent / "temp"
PROMO_IMAGE = TEMP_DIR / "fortuna.jpg"


# ── FSM ────────────────────────────────────────────────────────

class StartFSM(StatesGroup):
    waiting_phone  = State()   # telefon tugmasi kutilmoqda
    wrong_contact  = State()   # boshqa odam raqami yuborildi


# ── Klaviaturalar ──────────────────────────────────────────────

def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Kredit turlari", callback_data="credit_types"),
            InlineKeyboardButton(text="📞 Bog'lanish",     callback_data="contact"),
        ],
        [InlineKeyboardButton(text="📍 Filiallar", callback_data="branches")],
    ])


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish",
                                  request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_kb(own_phone: str) -> InlineKeyboardMarkup:
    """Boshqa odam raqami kelganda tasdiqlash so'raladi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ Ha, {own_phone} — mening raqamim",
                callback_data=f"confirm_phone:{own_phone}",
            ),
        ],
        [InlineKeyboardButton(text="🔄 Qaytadan ulashish",
                              callback_data="retry_phone")],
    ])


# ── Promo ──────────────────────────────────────────────────────

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
    if PROMO_IMAGE.exists():
        await bot.send_photo(
            user_id, FSInputFile(PROMO_IMAGE),
            caption=promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            user_id, promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML,
        )


# ── /start ─────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: types.Message, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user

    # Ro'yxatdan o'tgan bo'lsa — darhol menyu
    if await user_has_phone(user.id):
        # Username o'zgargan bo'lishi mumkin — yangilaymiz
        await save_user(
            user_id=user.id,
            full_name=user.full_name or "",
            username=user.username or "",
        )
        await send_promo(bot, user.id)
        return

    # Yangi foydalanuvchi — ma'lumotni yozib, telefon so'raymiz
    await save_user(
        user_id=user.id,
        full_name=user.full_name or "",
        username=user.username or "",
    )
    await state.set_state(StartFSM.waiting_phone)
    await message.answer(
        "👋 <b>Xush kelibsiz!</b>\n\n"
        "Botdan foydalanish uchun telefon raqamingizni ulashing.\n\n"
        "⚠️ <i>Raqamingizni ulashmasangiz, botdan foydalana olmaysiz.</i>\n\n"
        "👇 Quyidagi tugmani bosing:",
        reply_markup=phone_kb(),
        parse_mode="HTML",
    )


# ── Telefon qabul qilish ───────────────────────────────────────

@router.message(StartFSM.waiting_phone, F.contact)
async def handle_phone(message: types.Message, bot: Bot, state: FSMContext):
    user    = message.from_user
    contact = message.contact
    phone   = contact.phone_number

    # Telefon raqami o'zinikimi yoki boshqa odamnikimi?
    if contact.user_id and contact.user_id != user.id:
        # Boshqa odamning kontakti — tasdiqlash so'raymiz
        await state.update_data(candidate_phone=phone)
        await state.set_state(StartFSM.wrong_contact)
        await message.answer(
            f"⚠️ Siz boshqa odamning kontaktini yubordingiz.\n\n"
            f"<b>{phone}</b> — bu sizning raqamingizmi?",
            reply_markup=confirm_kb(phone),
            parse_mode="HTML",
        )
        return

    # O'zining raqami — saqlaymiz
    await _register(message, bot, state, user, phone)


@router.callback_query(StartFSM.wrong_contact, F.data.startswith("confirm_phone:"))
async def cb_confirm_phone(call: types.CallbackQuery, bot: Bot, state: FSMContext):
    phone = call.data.split(":", 1)[1]
    await call.answer()
    await call.message.delete()
    await _register(call.message, bot, state, call.from_user, phone)


@router.callback_query(F.data == "retry_phone")
async def cb_retry_phone(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.delete()
    await state.set_state(StartFSM.waiting_phone)
    await call.message.answer(
        "📱 Iltimos, o'z telefon raqamingizni ulashing:",
        reply_markup=phone_kb(),
    )


async def _register(
    message: types.Message, bot: Bot, state: FSMContext,
    user: types.User, phone: str,
) -> None:
    """Foydalanuvchini Sheets ga yozib, menyuni ko'rsatadi."""
    await state.clear()

    ok = await save_user(
        user_id=user.id,
        full_name=user.full_name or "",
        username=user.username or "",
        phone=phone,
    )

    if ok:
        await message.answer(
            "✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
    else:
        # Yozishda xato bo'lsa ham foydalanuvchini to'xtatmaymiz
        await message.answer(
            "✅ Xush kelibsiz!",
            reply_markup=ReplyKeyboardRemove(),
        )

    await send_promo(bot, user.id)


# ── Telefon kutilayotganda boshqa xabar kelsa ─────────────────

@router.message(StartFSM.waiting_phone)
@router.message(StartFSM.wrong_contact)
async def waiting_phone_other(message: types.Message, state: FSMContext):
    current = await state.get_state()
    if current == StartFSM.wrong_contact:
        # Tasdiqlash kutilmoqda — tugma bosishni eslatamiz
        await message.answer(
            "⬆️ Yuqoridagi tugmalardan birini tanlang.",
        )
        return

    # Tugma bosilmay matn yuborilib qolgan
    await message.answer(
        "📱 Iltimos, <b>faqat quyidagi tugmani bosib</b> telefon raqamingizni ulashing.\n\n"
        "⚠️ Botdan to'liq foydalanish uchun telefon raqamingizni kiriting",
        reply_markup=phone_kb(),
        parse_mode="HTML",
    )


# ── Ortga ─────────────────────────────────────────────────────

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, bot: Bot):
    with contextlib.suppress(Exception):
        await callback.message.delete()
    await send_promo(bot, callback.from_user.id)
