from pathlib import Path
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode

router = Router()

# 📂 Banner yo'li
BASE_DIR = Path(__file__).resolve().parent
HAMKOR_BANNER = BASE_DIR / "temp" / "Hamkor_banner_v1.jpg"

@router.callback_query(F.data == "hamkor")
async def hamkor_info(callback: CallbackQuery, bot: Bot):
    """Hamkor krediti haqida ma'lumot"""
    await callback.answer()
    text = (
        "🤝 <b>Hamkor krediti:</b>\n\n"
        "- Tashkilotimizdan birinchi marta kredit olayotgan Budjet tashkilotlari xodimlari uchun\n"
        "-dastlabki 30 kun foizsiz\n"
        "- Kredit muddati: 12 oy\n"
        "- Kredit summasi: 3 - 20 mln so'mgacha\n"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_hamkor")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])
    
    # Eski xabarni o'chirish
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    # Yangi rasm bilan xabar yuborish
    if HAMKOR_BANNER.exists():
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=FSInputFile(HAMKOR_BANNER),
            caption=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
    else:
        # Agar rasm yo'q bo'lsa, faqat matn yuboradi
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
