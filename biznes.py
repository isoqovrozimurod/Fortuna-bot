from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    FSInputFile
)
from aiogram.enums import ParseMode
import os

router = Router()

# Video joylashuvi
VIDEO_PATH = os.path.join("temp", "biznes_uchun.mp4")


@router.callback_query(F.data == "biznes")
async def biznes_info(callback: CallbackQuery):
    text = (
        "🏢 <b>Biznes uchun mikroqarz:</b>\n\n"
        "- Tadbirkorlik faoliyati bilan shug‘ullanuvchilar uchun\n"
        "- Kredit muddati: 12 – 24 oy\n"
        "- Kredit summasi: 10 – 50 mln so‘mgacha\n"
        "- Kafil asosida: 30 – 50 mln so‘mgacha\n"
        "- Talab qilinadi:\n"
        "  • Pasport\n"
        "  • Plastik karta\n"
        "  • STIR (INN)\n"
        "  • Biznes faoliyatini tasdiqlovchi hujjatlar"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_biznes")],
            [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
        ]
    )

    # Video mavjudligini tekshirish (Railway uchun muhim)
    if not os.path.exists(VIDEO_PATH):
        await callback.message.answer(
            "❌ Video topilmadi. Iltimos, administrator bilan bog‘laning."
        )
        return

    video = FSInputFile(VIDEO_PATH)

    await callback.message.answer_video(
        video=video,
        caption=text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML
    )

    # Eski xabarni o‘chiramiz
    try:
        await callback.message.delete()
    except:
        pass
