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


@router.callback_query(F.data == "taxi_bandlik")
async def taxi_bandlik_info(callback: CallbackQuery, bot: Bot):
    await callback.answer()

    text = (
        "🚖 <b>Taxi-Bandlik mikroqarzi:</b>\n\n"
        "– Taksi faoliyati bilan shug'ullanuvchi shaxslarga\n"
        "– Kredit summasi: 3 000 000 – 10 000 000 so'm\n"
        "– Kredit muddati: 12 oy\n\n"
        "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
        "• Shaxsni tasdiqlovchi hujjat(pasport, id karta)\n"
        "• Texpasport (qarz oluvchi nomida bo'lgan mashina)\n"
        "• Sug'urta polisi\n"
        "• Bandlik guvohnomasi\n"
        "• Taksichilik faoliyati uchun berilgan litsenziya\n"
        "• Onlayn taksi ilovalaridagi tushum va buyurtmalar(Yandex taxi, Best taxi va h.k.)\n"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_taxi_bandlik")],
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
