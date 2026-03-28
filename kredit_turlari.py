from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
)

router = Router()

BASE_DIR = Path(__file__).resolve().parent
BANNER   = BASE_DIR / "temp" / "banner_barchasi.jpg"

# Tugma matni → kredit.py CFG kaliti
KREDIT_MAP = {
    "✅ Pensiya":              "calc_pension",
    "💼 Ish haqi":             "calc_salary",
    "🚗 Avtomashina garov":    "calc_auto",
    "🏢 Biznes uchun":         "calc_biznes",
    "🤝 Hamkor":               "calc_hamkor",
}


def kredit_turlari_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Pensiya"),           KeyboardButton(text="💼 Ish haqi")],
            [KeyboardButton(text="🚗 Avtomashina garov"), KeyboardButton(text="🏢 Biznes uchun")],
            [KeyboardButton(text="🤝 Hamkor")],
            [KeyboardButton(text="⬅️ Ortga")],
        ],
        resize_keyboard=True,
    )


def kredit_text() -> str:
    return (
        "💸 <b>Kreditni quyidagi shaxslar olishlari mumkin:</b>\n\n"
        "✅ Pensionerlar\n"
        "💼 Rasmiy daromadga ega shaxslar\n"
        "🚗 Avtomashina egalari\n"
        "🏢 Biznes egalari\n"
        "🤝 Budjet tashkiloti xodimlari (Hamkor)"
    )


async def _send_kredit(chat_id: int, bot: Bot) -> None:
    if BANNER.exists():
        await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(BANNER),
            caption=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML",
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=kredit_text(),
            reply_markup=kredit_turlari_kb(),
            parse_mode="HTML",
        )


@router.message(Command("kredit_turlari"))
async def cmd_kredit_turlari(message: Message, bot: Bot):
    await _send_kredit(message.chat.id, bot)


@router.callback_query(F.data == "credit_types")
async def show_credit_types(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    await _send_kredit(callback.from_user.id, bot)


@router.message(F.text.in_(KREDIT_MAP.keys()))
async def handle_kredit_choice(message: Message, state: FSMContext, bot: Bot):
    from kredit import CFG, CalcFSM, fmt

    code = KREDIT_MAP[message.text]
    cfg  = CFG[code]
    await state.update_data(code=code)

    if code == "calc_auto":
        await message.answer(
            "🚘 So'nggi 5 yilda ishlab chiqarilgan avtomashinalar uchun "
            "hozirgi foiz stavkadan 6% chegirma mavjud.\n\n"
            "<b>Avtomobil ishlab chiqarilgan yilini kiriting:👇</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(CalcFSM.year)
    else:
        await message.answer(
            f"💳 <b>{cfg['name']}</b>\n"
            f"Kredit summasini kiriting:\n({fmt(cfg['min'])} – {fmt(cfg['max'])}) so'm",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(CalcFSM.sum)


@router.message(F.text == "⬅️ Ortga")
async def back_to_menu(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    # Asosiy menyuga qaytish — buyruqlar.py dagi menyu funksiyasini chaqiring
    # yoki quyidagini o'z menyungizga almashtiring:
    await message.answer("Bosh menyuga qaytildi.", reply_markup=ReplyKeyboardRemove())
