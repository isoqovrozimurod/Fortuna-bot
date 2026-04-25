"""
/kredit — admin uchun to'lov jadvali kalkulyatori.
Pillow bilan jadval chiziladi — matplotlib dan 3-5x tezroq.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import uuid
from functools import partial
from typing import List

from PIL import Image, ImageDraw, ImageFont

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)
from dotenv import load_dotenv

load_dotenv()

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

def _load_font(paths: list, size: int):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Yordamchi ──────────────────────────────────────────────────

fmt = lambda n: f"{round(n):,}".replace(",", " ")


def parse_rate(text: str) -> float | None:
    cleaned = (text or "").strip().replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if cleaned.count(".") > 1:
        i       = cleaned.index(".")
        cleaned = cleaned[:i + 1] + cleaned[i + 1:].replace(".", "")
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


# ── Pillow jadval ──────────────────────────────────────────────

def _draw_png_sync(rows: List[List], title: str, kredit_summa: float) -> bytes:
    HEADERS = ["Sana", "Foizlar", "Asosiy qarz", "Oylik to'lov", "Qoldiq summa"]
    COL_W   = [90, 160, 160, 160, 160]
    ROW_H   = 28
    FS      = 13
    PAD     = 16
    TITLE_H = 38

    font      = _load_font(_FONT_PATHS,      FS)
    font_bold = _load_font(_FONT_BOLD_PATHS,  FS)

    # Body
    body = [HEADERS]
    for r in rows:
        body.append([r[0], *[fmt(x) for x in r[1:]]])
    jami_foiz  = sum(r[1] for r in rows[1:])
    jami_tolov = sum(r[3] for r in rows[1:])
    body.append(["Jami", fmt(jami_foiz), fmt(kredit_summa), fmt(jami_tolov), "—"])

    n_rows = len(body)
    W      = sum(COL_W) + PAD * 2
    H      = ROW_H * n_rows + PAD * 2 + TITLE_H

    img  = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    # Title
    draw.text((PAD, PAD), title, fill="#003366", font=font_bold)
    y0 = PAD + TITLE_H

    CLR = {
        "header": "#A9D0F5",
        "footer": "#A9D0F5",
        "pay":    "#e6e6e6",
        "even":   "#f4f4f4",
        "white":  "#ffffff",
    }

    for ri, row in enumerate(body):
        y = y0 + ri * ROW_H
        x = PAD
        for ci, (cell, cw) in enumerate(zip(row, COL_W)):
            if ri == 0:
                bg = CLR["header"]
            elif ri == n_rows - 1:
                bg = CLR["footer"]
            elif ci == 3:
                bg = CLR["pay"]
            elif ri % 2 == 0:
                bg = CLR["even"]
            else:
                bg = CLR["white"]

            draw.rectangle([x, y, x + cw - 1, y + ROW_H - 1],
                           fill=bg, outline="#bbbbbb", width=1)

            f     = font_bold if ri in (0, n_rows - 1) or ci == 3 else font
            s     = str(cell)
            tw    = draw.textlength(s, font=f)
            tx    = x + (cw - tw) / 2
            ty    = y + (ROW_H - FS) / 2 - 1
            draw.text((tx, ty), s, fill="#111111", font=f)
            x += cw

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


async def _draw_png(rows: List[List], title: str, summa: float) -> BufferedInputFile:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None, partial(_draw_png_sync, rows, title, summa)
    )
    return BufferedInputFile(data, filename=f"{uuid.uuid4()}.png")


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
            reply_markup=back_kb(),
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
            reply_markup=back_kb(),
        )
    data   = await state.get_data()
    summa  = data["summa"]
    months = data["month"]
    await state.clear()

    wait_msg = await msg.answer("⏳ Jadval tayyorlanmoqda...")

    label    = f"{months} oy | {rate}%"
    ann_img  = await _draw_png(
        _ann_table(summa, rate, months),
        f"Annuitet – {label}", summa,
    )
    diff_img = await _draw_png(
        _diff_table(summa, rate, months),
        f"Differensial – {label}", summa,
    )

    await bot.send_photo(
        msg.chat.id, ann_img,
        caption=f"📄 <b>Annuitet jadval</b>\n{fmt(summa)} so'm | {label}",
        parse_mode=ParseMode.HTML,
    )
    await bot.send_photo(
        msg.chat.id, diff_img,
        caption=f"📄 <b>Differensial jadval</b>\n{fmt(summa)} so'm | {label}",
        parse_mode=ParseMode.HTML,
    )

    import contextlib
    with contextlib.suppress(Exception):
        await wait_msg.delete()


@router.callback_query(F.data == "kredit_cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ Bekor qilindi.")
