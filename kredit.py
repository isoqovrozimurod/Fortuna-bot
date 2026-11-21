"""
/kredit — admin uchun to'lov jadvali kalkulyatori.
Jadval Pillow bilan chiziladi (matplotlib ishlatilmaydi), float foiz stavkasi
qo'llab-quvvatlanadi. Juda uzun jadval (Telegram foto o'lcham limitidan oshsa)
PNG fayl (hujjat) sifatida yuboriladi.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import re
import uuid
from functools import lru_cache, partial
from typing import List

from PIL import Image, ImageDraw, ImageFont

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

router = Router()

# ── Font ───────────────────────────────────────────────────────

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
_FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


@lru_cache(maxsize=16)
def _load_font(bold: bool, size: int):
    for p in (_FONT_BOLD_PATHS if bold else _FONT_PATHS):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    try:                                    # Pillow >= 10.1: o'lchamli o'rnatilgan shrift
        return ImageFont.load_default(size)
    except TypeError:                       # eski Pillow: kichik bitmap shrift
        return ImageFont.load_default()


# ── Yordamchi ──────────────────────────────────────────────────

fmt = lambda n: f"{round(n):,}".replace(",", " ")


def parse_rate(text: str) -> float | None:
    """
    Foiz stavkasini parse qiladi.
    Qabul qilinadi: 49  /  17.5  /  32,4  /  17.18
    """
    cleaned = (text or "").strip().replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if cleaned.count(".") > 1:
        first   = cleaned.index(".")
        cleaned = cleaned[:first + 1] + cleaned[first + 1:].replace(".", "")
    try:
        v = float(cleaned)
        return v if 0 < v < 200 else None
    except ValueError:
        return None


def parse_int(text: str) -> int | None:
    cleaned = re.sub(r"\D", "", text or "")
    return int(cleaned) if cleaned else None


# ── Jadval hisoblash ───────────────────────────────────────────

def _ann_table(pr: float, rate: float, m: int) -> List[List]:
    r   = rate / 12 / 100
    pay = pr * r / (1 - (1 + r) ** -m) if r else pr / m
    bal = pr
    rows = [["Boshlanish", 0.0, 0.0, 0.0, pr]]
    for i in range(1, m + 1):
        interest  = bal * r
        principal = pay - interest
        bal      -= principal
        rows.append([f"{i}-oy", interest, principal, pay, max(0.0, bal)])
    return rows


def _diff_table(pr: float, rate: float, m: int) -> List[List]:
    r         = rate / 12 / 100
    principal = pr / m
    bal       = pr
    rows = [["Boshlanish", 0.0, 0.0, 0.0, pr]]
    for i in range(1, m + 1):
        interest = bal * r
        total    = principal + interest
        bal     -= principal
        rows.append([f"{i}-oy", interest, principal, total, max(0.0, bal)])
    return rows


# ── PNG generatsiya (Pillow; sinxron — executor da ishlatiladi) ─

# Telegram foto: kenglik + balandlik <= 10000, nisbat <= 20. Zaxira bilan:
PHOTO_MAX_SUM = 9500
PHOTO_MAX_RATIO = 15

_HEADERS = ["Sana", "Foizlar", "Asosiy qarz", "Oylik to'lov", "Qoldiq summa"]
_COL_W = [110, 170, 170, 170, 170]          # 1x masshtabda
_CLR = {
    "header": "#A9D0F5", "footer": "#A9D0F5", "pay": "#e6e6e6",
    "even": "#f4f4f4", "white": "#ffffff", "grid": "#cccccc",
}


def _center_text(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: str, font, fill: str):
    try:
        draw.text((cx, cy), s, fill=fill, font=font, anchor="mm")
    except (ValueError, TypeError):         # bitmap shriftda anchor yo'q
        w = draw.textlength(s, font=font)
        draw.text((cx - w / 2, cy - 5), s, fill=fill, font=font)


def _draw_png_sync(rows: List[List], title: str, kredit_summa: float) -> tuple[bytes, bool]:
    """(png_bytes, foto_sifatida_yuborsa_bo'ladimi)"""
    body = [_HEADERS]
    for r in rows:
        body.append([r[0], *[fmt(x) for x in r[1:]]])
    jami_foiz  = sum(r[1] for r in rows[1:])
    jami_tolov = sum(r[3] for r in rows[1:])
    body.append(["Jami", fmt(jami_foiz), fmt(kredit_summa), fmt(jami_tolov), "—"])

    n = len(body)
    S = 2 if n <= 70 else 1                 # kichik jadval — aniqroq (2x), katta — 1x
    col_w = [w * S for w in _COL_W]
    row_h, pad, title_h = 30 * S, 16 * S, 40 * S
    fs = 14 * S

    font, font_bold = _load_font(False, fs), _load_font(True, fs)
    font_title = _load_font(True, int(fs * 1.15))

    W = sum(col_w) + pad * 2
    H = row_h * n + pad * 2 + title_h

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    draw.text((pad, pad), title, fill="#003366", font=font_title)
    y0 = pad + title_h

    for ri, row in enumerate(body):
        y = y0 + ri * row_h
        x = pad
        edge = ri in (0, n - 1)
        for ci, (cell, cw) in enumerate(zip(row, col_w)):
            if ri == 0:
                bg = _CLR["header"]
            elif ri == n - 1:
                bg = _CLR["footer"]
            elif ci == 3:
                bg = _CLR["pay"]
            elif ri % 2 == 0:
                bg = _CLR["even"]
            else:
                bg = _CLR["white"]
            draw.rectangle([x, y, x + cw, y + row_h], fill=bg, outline=_CLR["grid"], width=1)
            _center_text(draw, x + cw / 2, y + row_h / 2, str(cell),
                         font_bold if (edge or ci == 3) else font, "#111111")
            x += cw

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    as_photo = (W + H <= PHOTO_MAX_SUM) and (max(W, H) / min(W, H) <= PHOTO_MAX_RATIO)
    return buf.getvalue(), as_photo


async def _draw_png(rows: List[List], title: str, summa: float) -> tuple[BufferedInputFile, bool]:
    """Async wrapper — event loop ni bloklamaydi."""
    loop = asyncio.get_running_loop()
    data, as_photo = await loop.run_in_executor(
        None, partial(_draw_png_sync, rows, title, summa)
    )
    return BufferedInputFile(data, filename=f"{uuid.uuid4()}.png"), as_photo


async def _send_img(bot: Bot, chat_id: int, img: tuple[BufferedInputFile, bool], caption: str):
    file, as_photo = img
    if as_photo:
        await bot.send_photo(chat_id, file, caption=caption, parse_mode=ParseMode.HTML)
    else:                                   # juda uzun jadval — fayl sifatida (siqilmaydi)
        await bot.send_document(chat_id, file, caption=caption, parse_mode=ParseMode.HTML)


# ── FSM ────────────────────────────────────────────────────────

class KreditFSM(StatesGroup):
    summa = State()
    month = State()
    rate  = State()


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="kredit_cancel")]
    ])


# ── Handlerlar ─────────────────────────────────────────────────

@router.message(F.text == "/kredit")
async def start_kredit(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await state.set_state(KreditFSM.summa)
    await msg.answer(
        "💰 Kredit summasini kiriting:\n"
        "<i>100 000 – 1 000 000 000 so'm</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )


@router.message(KreditFSM.summa)
async def get_sum(msg: types.Message, state: FSMContext):
    val = parse_int(msg.text)
    if not val:
        return await msg.answer("❗ Faqat raqam kiriting:", reply_markup=back_kb())
    if not 100_000 <= val <= 1_000_000_000:
        return await msg.answer(
            "❗ 100 000 – 1 000 000 000 so'm oralig'ida kiriting:",
            reply_markup=back_kb()
        )
    await state.update_data(summa=float(val))
    await state.set_state(KreditFSM.month)
    await msg.answer("📆 Kredit muddatini kiriting (1 – 360 oy):",
                     reply_markup=back_kb())


@router.message(KreditFSM.month)
async def get_month(msg: types.Message, state: FSMContext):
    val = parse_int(msg.text)
    if not val:
        return await msg.answer("❗ Faqat raqam kiriting:", reply_markup=back_kb())
    if not 1 <= val <= 360:
        return await msg.answer("❗ 1 – 360 oy oralig'ida kiriting:",
                                reply_markup=back_kb())
    await state.update_data(month=val)
    await state.set_state(KreditFSM.rate)
    await msg.answer(
        "📊 Yillik foiz stavkasini kiriting (%):\n"
        "<i>Masalan: 49 | 17.5 | 32,4</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )


@router.message(KreditFSM.rate)
async def get_rate_and_result(msg: types.Message, bot: Bot, state: FSMContext):
    rate = parse_rate(msg.text)
    if rate is None:
        return await msg.answer(
            "❗ Foiz stavkasini to'g'ri kiriting (masalan: 49 yoki 17.5):",
            reply_markup=back_kb()
        )

    data   = await state.get_data()
    summa  = data["summa"]
    months = data["month"]
    await state.clear()

    wait_msg = await msg.answer("⏳ Jadval tayyorlanmoqda...")
    label = f"{months} oy | {rate}%"

    try:
        ann_img, diff_img = await asyncio.gather(
            _draw_png(_ann_table(summa, rate, months), f"Annuitet – {label}", summa),
            _draw_png(_diff_table(summa, rate, months), f"Differensial – {label}", summa),
        )
        await _send_img(bot, msg.chat.id, ann_img,
                        f"📄 <b>Annuitet jadval</b>\n{fmt(summa)} so'm | {label}")
        await _send_img(bot, msg.chat.id, diff_img,
                        f"📄 <b>Differensial jadval</b>\n{fmt(summa)} so'm | {label}")
    except Exception:
        logger.exception("Kredit jadvalini chizish/yuborishda xato")
        await msg.answer("❌ Jadvalni tayyorlashda xato. Qayta urinib ko'ring: /kredit")
    finally:
        with contextlib.suppress(Exception):
            await wait_msg.delete()


@router.callback_query(F.data == "kredit_cancel")
async def cb_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ Bekor qilindi.")
