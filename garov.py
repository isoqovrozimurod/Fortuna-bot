from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
import os

router = Router()

@router.callback_query(F.data == "garov")
async def garov_info(callback: CallbackQuery):
    text = (
        "🚗 <b>Avtomashina garov asosida kredit:</b>\n\n"
        "- 2000-yildan yuqori mashinalar garovga olinadi\n"
        "- So'ngi 5 yilda ishlab chiqarilgan Avtomashinalar uchun hozirgi foiz stavkasidan 6% chegirma mavjud\n"
        "- Garov mashina egasining nomida bo‘lishi shart\n"
        "  (yoki ishonchnomada sotish va garovga qo'yish huquqi bo‘lishi kerak)\n"
        "- Kredit muddati: 12 – 36 oy\n"
        "- Kredit summasi: 3 – 300 mln so'mgacha\n"
        "- Hujjatlar: pasport (turmush o'rtog'i pasporti va garovga qo'yishga roziligi haqida ariza),\n"
        "  nikoh guvohnomasi, texpasport, avtomobil"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_auto")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

    photo_path = "temp/fortuna_rek.jpg"
    if os.path.exists(photo_path):
        with open(photo_path, "rb") as image:
            photo = InputFile(image)
            await callback.message.answer_photo(photo=photo, caption=text, reply_markup=markup)
    else:
        await callback.message.answer("🖼 Rasm topilmadi.", reply_markup=markup)
