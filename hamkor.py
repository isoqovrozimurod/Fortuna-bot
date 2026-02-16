from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ParseMode

router = Router()

@router.callback_query(F.data == "hamkor")
async def hamkor_info(callback: CallbackQuery):
    """Hamkor krediti haqida ma'lumot"""
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
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        # Agar edit ishlamasa, yangi xabar yuboradi
        await callback.message.answer(
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML
        )
        print(f"Xatolik: {e}")
