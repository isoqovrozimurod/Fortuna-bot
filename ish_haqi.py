from pathlib import Path

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

router = Router()

TEMP_DIR = Path(__file__).resolve().parent / "temp" / "ish_haqi"
ISH_HAQI_IMG = TEMP_DIR / "ish_haqi_v1.png"

ISH_HAQI_TEXT = (
    "💼 <b>Ish haqi asosida kredit:</b>\n\n"
    "• Rasmiy daromadga ega shaxslarga\n"
    "• Kredit muddati: 12 – 36 oy\n"
    "• Kredit summasi: 3 – 40 mln so'mgacha\n"
    "• Kafil asosida: 20 – 40 mln so'mgacha\n"
    "• Talab qilinadi: pasport, ish haqi plastik kartasi\n"
    "  (harbiylar uchun ish joyidan ish haqi ma'lumotnomasi)"
)

ISH_HAQI_MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_salary")],
    [InlineKeyboardButton(text="⬅️ Ortga",            callback_data="credit_types")],
])


@router.callback_query(F.data == "ish_haqi")
async def ish_haqi_info(callback: CallbackQuery):
    await callback.answer()

    # Avvalgi xabarni o'chiramiz
    try:
        await callback.message.delete()
    except Exception:
        pass

    # ish_haqi_v1.png rasm bilan yangi xabar yuboramiz
    if ISH_HAQI_IMG.exists():
        await callback.message.answer_photo(
            photo=FSInputFile(str(ISH_HAQI_IMG)),
            caption=ISH_HAQI_TEXT,
            reply_markup=ISH_HAQI_MARKUP,
            parse_mode="HTML",
        )
    else:
        # Rasm yo'q bo'lsa — faqat matn
        await callback.message.answer(
            text=ISH_HAQI_TEXT,
            reply_markup=ISH_HAQI_MARKUP,
            parse_mode="HTML",
        )
