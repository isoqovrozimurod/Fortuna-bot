from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode
import os
import random

router = Router()

# Media papkasi
MEDIA_DIR = os.path.join("temp", "biznes_uchun")


@router.callback_query(F.data == "biznes")
async def biznes_info(callback: CallbackQuery):
    text = (
        "🏢 <b>Biznes uchun mikroqarz:</b>\n\n"
        "- Tadbirkorlik faoliyati bilan shug‘ullanuvchilar uchun\n"
        "- Kredit muddati: 12 – 24 oy\n"
        "- Kredit summasi: 10 – 50 mln so‘mgacha\n"
        "- Kafil asosida: 30 – 50 mln so‘mgacha\n\n"
        "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
        "  • Pasport\n"
        "  • Plastik karta yoki bank hisobraqami aylanmasidan ko'chirma\n"
        "  • STIR (INN)\n"
        "  • Ijara shartnomasi\n"
        "  • Biznes faoliyatini tasdiqlovchi hujjatlar"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_biznes")],
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

        # Eski xabarni o'chirish
        try:
            await callback.message.delete()
        except Exception:
            pass

    except Exception as e:
        await callback.message.answer(
            f"❌ Media yuborishda xatolik:\n{e}"
        )
