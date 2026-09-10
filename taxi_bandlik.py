from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode
import os
import random

router = Router()

MEDIA_DIR = os.path.join("temp", "taxi_bandlik")


@router.callback_query(F.data == "taxi_bandlik")
async def taxi_bandlik_info(callback: CallbackQuery, bot: Bot):
    text = (
        "🚖 <b>Taxi-Bandlik mikroqarzi:</b>\n\n"
        "– Taksi faoliyati bilan shug'ullanuvchi shaxslarga\n"
        "– Kredit summasi: 15 000 000 so'mgacha\n"
        "– Kredit muddati: 12 oy\n\n"

        "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
        "• Shaxsni tasdiqlovchi hujjat (pasport, ID karta)\n"
        "• Texpasport (qarz oluvchi nomida bo'lgan mashina)\n"
        "• Sug'urta polisi\n"
        "• Bandlik guvohnomasi\n"
        "• Taksichilik faoliyati uchun berilgan litsenziya\n"
        "• Onlayn taksi ilovalaridagi tushum va buyurtmalar "
        "(Yandex Taxi, Best Taxi va h.k.)\n\n"
        
        "<b>Murojaat uchun:</b>\n"
        "📱 +998 99 251 00 40\n"
        "📱 +998 95 375 45 40\n\n"
        
        "🤖 <b>Telegram bot:</b> @fortunakredit_bot"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📊 Kredit hisoblash",
            callback_data="calc_taxi_bandlik"
        )],
        [InlineKeyboardButton(
            text="⬅️ Ortga",
            callback_data="credit_types"
        )]
    ])

    # Telegram tugmasidagi loadingni darhol yopamiz
    await callback.answer()

    # Media papkasini tekshirish
    if not os.path.exists(MEDIA_DIR):
        await callback.message.answer(
            f"❌ Media papka topilmadi.\n\n📁 {MEDIA_DIR}"
        )
        return

    # Ruxsat etilgan formatlar
    video_extensions = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
    photo_extensions = (".png", ".jpg", ".jpeg", ".webp")
    allowed_extensions = video_extensions + photo_extensions

    # Media fayllarni olish
    media_files = [
        os.path.join(MEDIA_DIR, file)
        for file in os.listdir(MEDIA_DIR)
        if file.lower().endswith(allowed_extensions)
    ]

    if not media_files:
        await callback.message.answer(
            "❌ Taxi-Bandlik uchun media fayl topilmadi."
        )
        return

    # Tasodifiy media tanlash
    selected_file = random.choice(media_files)
    media = FSInputFile(selected_file)
    extension = os.path.splitext(selected_file)[1].lower()

    try:
        # Video yuborish
        if extension in video_extensions:
            await callback.message.answer_video(
                video=media,
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )

        # Rasm yuborish
        elif extension in photo_extensions:
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
            "❌ Media yuborishda xatolik:\n\n"
            f"<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )
