from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode
import os
import random

router = Router()

# Media papkasi
MEDIA_DIR = os.path.join("temp", "hamkor")

@router.callback_query(F.data == "oila")
async def oila_info(callback: CallbackQuery, bot: Bot):
    await callback.answer()
text = (
    "🏠 <b>Oila mikroqarzi:</b>\n\n"
    "– Chet elda ishlovchi jismoniy shaxs o'zi yoki yaqin qarindoshlariga (ota-ona yoki turmush o'rtog'i) ajratiladi\n"
    "- Kredit summasi: 10 mln so'mgacha\n"
    "- Muddati: 12 oy\n\n"
    "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
    "  • O'zi yoki yaqin qarindoshining chet elda ishlashini asoslovchi hujjatlar\n"
    "  • Qarindoshlikni tasdiqlovchi hujjatlar(Nikoh guvohnomasi yoki my.gov.uz platformasidagi hujjatlar)\n"
    "  • Karta aylanmalari yoki xalqaro pul o'tkazmalari cheklari\n"
    "  • Patent (chet elda ishlovchi bo'lsa)\n"
    "  • Boshqa zarur hujjatlar kredit mutaxassisi tomonidan ma'lum qilinadi.\n"
  )

markup = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_oila")],
    [InlineKeyboardButton(text="⬅️ Ortga",            callback_data="credit_types")],
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
