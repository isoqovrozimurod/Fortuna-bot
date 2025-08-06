from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import FSInputFile
from aiogram.enums import ParseMode
from pathlib import Path

router = Router()

def promo_caption() -> str:
    return (
        "🚗 <b>Avtomashina garov asosida kredit:</b>\n\n"
        "- 2000-yildan yuqori mashinalar garovga olinadi\n"
        "- So'ngi 5 yilda ishlab chiqarilgan Avtomashinalar uchun hozirgi foiz stavkasidan 6% chegirma mavjud\n"
        "- Garov mashina egasining nomida bo‘lishi shart\n"
        "  (yoki ishonchnomada sotish va garovga qo'yish huquqi bo‘lishi kerak)\n"
        "- Kredit muddati: 12 – 36 oy\n"
        "- Kredit summasi: 3 – 300 mln so'mgacha\n"
        "- Hujjatlar: pasport (turmush o'rtog'i pasporti va garovga qo‘yishga roziligi haqida ariza),\n"
        "  nikoh guvohnomasi, texpasport, avtomobil"
    )

def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_auto")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

@router.callback_query(F.data == "garov")
async def garov_info(callback: CallbackQuery):
    img_path = Path(__file__).resolve().parent / "temp" / "fortuna_rek.jpg"

    if img_path.is_file():
        photo = FSInputFile(img_path)
        await callback.message.answer_photo(
            photo=photo,
            caption=promo_caption(),
            reply_markup=main_menu_markup(),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.answer("🖼 Rasm topilmadi.", reply_markup=main_menu_markup())
