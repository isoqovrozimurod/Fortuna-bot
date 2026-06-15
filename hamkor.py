from pathlib import Path
import os
import random
from aiogram.enums import ParseMode
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

router = Router()

# Media papkasi
MEDIA_DIR = os.path.join("temp", "hamkor")

@router.callback_query(F.data == "hamkor")
async def hamkor_info(callback: CallbackQuery, bot: Bot):
    """Hamkor krediti haqida ma'lumot"""
    await callback.answer()
    text = (
        "🤝 <b>Hamkor krediti:</b>\n\n"
        "- Tashkilotimizdan birinchi marta kredit olayotgan Budjet tashkilotlari xodimlari uchun\n"
        "- Dastlabki 30 kun foizsiz"
        "- Kredit muddati: 12 oy\n"
        "- Kredit summasi: 3 - 20 mln so'mgacha\n"
        "📋 <b>Talab qilinadi:</b> Pasport va ish haqi bank plastik kartasi\n"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_hamkor")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])
    
    # Eski xabarni o'chirish
    try:
        await callback.message.delete()
    except:
        pass
    
    # Papkadagi media fayllarni olish
    media_files = [
        os.path.join(MEDIA_DIR, file)
        for file in os.listdir(MEDIA_DIR)
        if file.lower().endswith(
            (".mp4", ".png", ".jpg", ".jpeg")
        )
    ]

    if not media_files:
        await callback.message.answer(
            "❌ Media fayllar topilmadi."
        )
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

except Exception as e:
    await callback.message.answer(
        f"❌ Media yuborishda xatolik: {e}"
    )
