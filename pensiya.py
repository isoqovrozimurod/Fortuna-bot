from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router()

@router.callback_query(F.data == "pensiya")
async def show_pensiya_info(callback: CallbackQuery, bot: Bot):
    text = (
        "✅ <b>Pensiya asosida kredit:</b>\n\n"
        "- Faqatgina qarilik pensiya olish huquqiga ega shaxslarga\n"
        "- Pensiya miqdori 750 ming soʻmdan kam boʻlmasligi kerak\n"
        "- Kredit muddati: 12 – 18 oy\n"
        "- Kredit summasi: 3 – 20 mln so'mgacha\n"
        "- Kerakli hujjat: pasport, pensiya plastik kartasi"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_pension")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

    # ❗️ Shunchaki yangi xabar yuboriladi (edit_text emas!)
    await bot.send_message(chat_id=callback.from_user.id, text=text, reply_markup=markup, parse_mode="HTML")
