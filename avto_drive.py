from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.enums import ParseMode

router = Router()

BASE_DIR = Path(__file__).resolve().parent
BANNER   = BASE_DIR / "temp" / "banner_barchasi.jpg"


@router.callback_query(F.data == "avto_drive")
async def avto_drive_info(callback: CallbackQuery, bot: Bot):
    await callback.answer()

    text = (
        "🚘 <b>Avto-Drive mikroqarzi:</b>\n\n"
        "– Shaxsiy avtomobilga ega jismoniy shaxslarga\n"
        "– Kredit summasi: 5 000 000 so'mgacha\n"
        "– Kredit muddati: 12 oy\n\n"
        "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
        "1. Shaxsni tasdiqlovchi hujjat(pasport, id karta)\n"
        "2. Texpasport (qarz oluvchi nomida bo'lgan mashina)\n"
        "3. Sug'urta polisi\n"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_avto_drive")],
            [InlineKeyboardButton(text="⬅️ Ortga",            callback_data="credit_types")],
        ]
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    if BANNER.exists():
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=FSInputFile(BANNER),
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
