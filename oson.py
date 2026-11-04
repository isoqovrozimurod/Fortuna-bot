from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.enums import ParseMode
import os
import random

router = Router()

MEDIA_DIR = os.path.join("temp", "oson")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")

# Telegram file_id keshi: bir marta yuklangan faylni qayta yuklamaymiz
# (tarmoq timeout va sekinlikning oldini oladi)
_file_ids: dict[str, str] = {}

# Telegram caption limiti — 1024 belgi
CAPTION_LIMIT = 1024

TEXT = (
    "💳 <b>OSON mikroqarzi:</b>\n\n"
    "– Rasmiy daromadga ega bo'lmagan jismoniy shaxslarga (karta aylanmasi bo'yicha)\n"
    "– 20 yoshdan yuqori, muomilaga layoqatli shaxslarga\n"
    "– Kredit summasi: 5 000 000 so'mgacha\n"
    "– Kredit muddati: 12 oygacha\n\n"

    "📋 <b>Talab qilinadigan hujjatlar:</b>\n"
    " • Pasport\n"
    "• Bank plastik kartasi\n\n"

    "<b>Murojaat uchun:</b>\n"
    "📱 +998 99 251 00 40\n"
    "📱 +998 95 375 45 40\n\n"

    "🤖 <b>Telegram bot:</b> @fortunakredit_bot"
)

MARKUP = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Kredit hisoblash", callback_data="calc_oson")],
    [InlineKeyboardButton(text="⬅️ Ortga",            callback_data="credit_types")],
])


def _pick_media() -> str | None:
    if not os.path.isdir(MEDIA_DIR):
        return None
    files = [
        os.path.join(MEDIA_DIR, f)
        for f in os.listdir(MEDIA_DIR)
        if f.lower().endswith(VIDEO_EXT + IMAGE_EXT)
    ]
    return random.choice(files) if files else None


@router.callback_query(F.data == "oson")
async def oson_info(callback: CallbackQuery, bot: Bot):
    # Darhol javob — tugma "loading" holatida osilib qolmasin
    await callback.answer()
    chat_id = callback.from_user.id

    selected = _pick_media()

    # Media yo'q — faqat matn
    if not selected:
        await bot.send_message(chat_id, TEXT, reply_markup=MARKUP, parse_mode=ParseMode.HTML)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    ext = os.path.splitext(selected)[1].lower()
    is_video = ext in VIDEO_EXT
    media = _file_ids.get(selected) or FSInputFile(selected)

    # Matn caption'ga sig'sa — captionda; sig'masa — media alohida, matn alohida
    fits = len(TEXT) <= CAPTION_LIMIT

    try:
        if is_video:
            sent = await bot.send_video(
                chat_id, video=media,
                caption=TEXT if fits else None,
                reply_markup=MARKUP if fits else None,
                parse_mode=ParseMode.HTML,
            )
            if sent.video:
                _file_ids[selected] = sent.video.file_id
        else:
            sent = await bot.send_photo(
                chat_id, photo=media,
                caption=TEXT if fits else None,
                reply_markup=MARKUP if fits else None,
                parse_mode=ParseMode.HTML,
            )
            if sent.photo:
                _file_ids[selected] = sent.photo[-1].file_id

        if not fits:
            await bot.send_message(chat_id, TEXT, reply_markup=MARKUP, parse_mode=ParseMode.HTML)

        try:
            await callback.message.delete()
        except Exception:
            pass

    except Exception as e:
        # Media yuborilmasa ham foydalanuvchi ma'lumotsiz qolmasin
        _file_ids.pop(selected, None)
        await bot.send_message(chat_id, TEXT, reply_markup=MARKUP, parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(
                chat_id,
                "ℹ️ Media yuklanmadi, lekin ma'lumot yuqorida.",
            )
        except Exception:
            pass
