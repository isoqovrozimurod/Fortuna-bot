from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router()

@router.callback_query(F.data == "ish_haqi")
async def ish_haqi_info(callback: CallbackQuery):
    text = (
        "💼 <b>Ish haqi asosida kredit:</b>\n\n"
        "- Rasmiy daromadga ega shaxslarga\n"
        "- Kredit muddati: 12 – 36 oy\n"
        "- Kredit summasi: 3 - 40 mln so'mgacha\n"
        "- Kafil asosida: 20 - 40 mln so'mgacha\n"
        "- Talab qilinadi: pasport, ish haqi plastik kartasi,\n"
        "  (harbiylar uchun ish joyidan ish haqi ma’lumotnomasi)"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_salary")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

    try:
        # Agar xabarda rasm (photo) bo'lsa, caption (taglavha)ni tahrirlaydi
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
        else:
            # Agar faqat matn bo'lsa, textni tahrirlaydi
            await callback.message.edit_text(text=text, reply_markup=markup)
    except Exception as e:
        # Kutilmagan xatolik bo'lsa, yangi xabar sifatida yuboradi
        await callback.message.answer(text=text, reply_markup=markup)
        print(f"Xatolik yuz berdi: {e}")
