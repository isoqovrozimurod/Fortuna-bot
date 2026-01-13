from pathlib import Path
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

router = Router()

# temp papka va rasm yo‘li
BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
PENSION_IMAGE = TEMP_DIR / "pensiya_v1.png"


@router.callback_query(F.data == "pensiya")
async def show_pensiya_info(callback: CallbackQuery, bot: Bot):
    text = (
        "✅ <b>Pensiya asosida kredit:</b>\n\n"
        "– Faqatgina qarilik pensiya olish huquqiga ega shaxslarga\n"
        "– Pensiya miqdori 750 000 soʻmdan kam boʻlmasligi kerak\n"
        "– Kredit muddati: 12 – 24 oy\n"
        "– Kredit summasi: 3 – 30 mln soʻmgacha\n"
        "– Kerakli hujjatlar: pasport, pensiya plastik kartasi"
    )

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_pension")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="credit_types")]
    ])

    # Oldingi tugma xabarini o‘chiramiz
    try:
        await callback.message.delete()
    except:
        pass

    # Agar rasm mavjud bo‘lsa — rasm bilan yuboradi
    if PENSION_IMAGE.exists():
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=FSInputFile(PENSION_IMAGE),
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        # Agar rasm topilmasa — faqat matn yuboradi
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
