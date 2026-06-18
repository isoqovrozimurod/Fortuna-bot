from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode
import os
import random

router = Router()

# Media papkasi
MEDIA_DIR = os.path.join("temp", "avto_garov")

@router.callback_query(F.data == "garov")
async def garov_info(callback: CallbackQuery, bot: Bot):
    text = (
        "🚗 <b>Avtomashina garov asosida kredit:</b>\n\n"
        "- 2000-yildan yuqori mashinalar garovga olinadi\n"
        "- So'ngi 5 yilda ishlab chiqarilgan Avtomashinalar uchun hozirgi foiz stavkasidan 6% chegirma mavjud\n"
        "- Garov mashina egasining nomida bo‘lishi shart (yoki ishonchnomada sotish va garovga qo'yish huquqi bo‘lishi kerak)\n"
        "- Kredit muddati: 12 – 36 oy\n"
        "- Kredit summasi: 3 – 300 mln so'mgacha\n\n"
        "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
        "• Pasport (turmush o'rtog'ining garovga qo'yishga roziligi haqida ariza),\n"
        "• Texpasport\n" 
        "• Avtomobil"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_auto")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

    # Papkadagi media fayllarni olish
    media_files = [
        os.path.join(MEDIA_DIR, file)
        for file in os.listdir(MEDIA_DIR)
        if file.lower().endswith(
            (".mp4", ".png", ".jpg", ".jpeg")
        )
    ]

    if not os.path.exists(MEDIA_DIR):
        await callback.answer()
        await callback.message.answer("❌ Media papka topilmadi.")
        return

    # Random fayl tanlash
    selected_file = random.choice(media_files)
    media = FSInputFile(selected_file)

    try:
        # Video bo'lsa
        if selected_file.lower().endswith(".mp4"):
            await callback.message.answer_video(
                video=media,
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )

        # Rasm bo'lsa
        else:
            await callback.message.answer_photo(
                photo=media,
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )

        # Eski xabarni o'chirish
        try:
            await callback.message.delete()
        except Exception:
            pass

    except Exception as e:
        await callback.message.answer(
            f"❌ Media yuborishda xatolik:\n{e}"
        )
