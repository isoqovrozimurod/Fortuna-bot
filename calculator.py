"""
Kredit kalkulyatori — foydalanuvchilar uchun.
Pillow bilan jadval chiziladi (matplotlib dan 3-5x tezroq).
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import re
import uuid
from datetime import datetime
from functools import partial
from typing import List

from PIL import Image, ImageDraw, ImageFont

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile,
)

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


# ── FSM ────────────────────────────────────────────────────────

class CalcFSM(StatesGroup):
    year  = State()   # faqat calc_auto uchun
    sum   = State()
    month = State()


# ── Konfiguratsiya ─────────────────────────────────────────────

CFG = {
    "calc_pension": {
        "name": "Pensiya krediti", "rate": 49,
        "min": 3_000_000, "max": 30_000_000, "mmin": 12, "mmax": 24,
    },
    "calc_salary": {
        "name": "Ish haqi krediti", "rate": 49,
        "min": 3_000_000, "max": 40_000_000, "mmin": 12, "mmax": 36,
    },
    "calc_auto": {
        "name": "Avto garov krediti", "rate": 54,
        "min": 3_000_000, "max": 300_000_000, "mmin": 12, "mmax": 36,
    },
    "calc_biznes": {
        "name": "Biznes uchun mikroqarz", "rate": 54,
        "min": 10_000_000, "max": 50_000_000, "mmin": 12, "mmax": 24,
    },
    "calc_hamkor": {
        "name": "Hamkor krediti", "rate": 56,
        "min": 3_000_000, "max": 20_000_000, "mmin": 12, "mmax": 12,
        "grace_days": 30,
    },
    "calc_avto_drive": {
        "name": "Avto-Drive mikroqarzi", "rate": 59,
        "min": 500_000, "max": 5_000_000, "mmin": 1, "mmax": 12,
    },
    "calc_taxi_bandlik": {
        "name": "Taxi-Bandlik mikroqarzi", "rate": 56,
        "min": 3_000_000, "max": 10_000_000, "mmin": 12, "mmax": 12,
    },
}

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Kredit turlari", callback_data="credit_types")
    ]]
)

fmt = lambda n: f"{round(n):,}".replace(",", " ")


# ── Jadval hisoblash ───────────────────────────────────────────

def ann_table(pr: float, rate: float, m: int, grace_days: int = 0) -> List[List]:
    r   = rate / 12 / 100
    pay = pr * r / (1 - (1 + r) ** -m) if r else pr / m
    bal = pr
    rows = [["Boshlanish", 0, 0, 0, pr]]
    for i in range(1, m + 1):
        interest  = bal * r
        principal = pay - interest
        if i == 1 and grace_days >= 30:
            actual_interest = 0
            actual_payment  = principal
        else:
            actual_interest = interest
            actual_payment  = pay
        bal -= principal
        rows.append([f"{i}-oy", actual_interest, principal, actual_payment, max(0.0, bal)])
    return rows


def diff_table(pr: float, rate: float, m: int, grace_days: int = 0) -> List[List]:
    r         = rate / 12 / 100
    principal = pr / m
    bal       = pr
    rows = [["Boshlanish", 0, 0, 0, pr]]
    for i in range(1, m + 1):
        interest = 0.0 if (i == 1 and grace_days >= 30) else bal * r
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
            f  = font_bold if ri in (0, n_rows - 1) or ci == 3 else font
            s  = str(cell)
            tw = draw.textlength(s, font=f)
            tx = x + (cw - tw) / 2
            ty = y + (ROW_H - FS) / 2 - 1
            draw.text((tx, ty), s, fill="#111111", font=f)
            x += cw

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


async def draw_png(rows: List[List], title: str, kredit_summa: float) -> BufferedInputFile:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None, partial(_draw_png_sync, rows, title, kredit_summa)
    )
    return BufferedInputFile(data, filename=f"{uuid.uuid4()}.png")


# ── Natija yuborish ────────────────────────────────────────────

async def _send_results(msg: types.Message, bot: Bot, cfg: dict,
                         summa: float, months: int, rate: float, grace_days: int):
    ann_rows  = ann_table(summa, rate, months, grace_days)
    diff_rows = diff_table(summa, rate, months, grace_days)
    label     = f"{cfg['name']} – {months} oy"

    ann_img  = await draw_png(ann_rows,  f"{label} | Annuitet",     summa)
    diff_img = await draw_png(diff_rows, f"{label} | Differensial", summa)

    await bot.send_photo(
        msg.chat.id, ann_img,
        caption="📄 <b>Annuitet jadval\n@Gallaorol_FBbot</b>",
        parse_mode=ParseMode.HTML,
    )
    await bot.send_photo(
        msg.chat.id, diff_img,
        caption="📄 <b>Differensial jadval\n@Gallaorol_FBbot</b>",
        parse_mode=ParseMode.HTML,
    )
    await msg.answer("✅ Hisob-kitob tayyor!", reply_markup=BACK_KB)


# ── Handlerlar ─────────────────────────────────────────────────

@router.callback_query(F.data.in_(CFG.keys()))
async def ask_year_or_sum(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    cfg = CFG[cb.data]
    await state.update_data(code=cb.data)

    if cb.data == "calc_auto":
        await cb.message.answer(
            "🚘 So'nggi 5 yilda ishlab chiqarilgan avtomashinalar uchun "
            "hozirgi foiz stavkadan 6% chegirma mavjud.\n\n"
            "<b>Avtomobil ishlab chiqarilgan yilini kiriting:👇</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=BACK_KB,
        )
        await state.set_state(CalcFSM.year)
    else:
        await cb.message.answer(
            f"💳 <b>{cfg['name']}</b>\n"
            f"Kredit summasini kiriting:\n({fmt(cfg['min'])} – {fmt(cfg['max'])}) so'm",
            parse_mode=ParseMode.HTML,
            reply_markup=BACK_KB,
        )
        await state.set_state(CalcFSM.sum)


@router.message(CalcFSM.year)
async def ask_sum_after_year(msg: types.Message, state: FSMContext):
    yil_text = re.sub(r"\D", "", msg.text or "")
    if not yil_text:
        return await msg.answer("❗ Yilni raqam bilan kiriting (masalan, 2022).")
    yil = int(yil_text)
    hozirgi_yil = datetime.now().year
    if yil < 2000 or yil > hozirgi_yil:
        return await msg.answer(f"❗ Yil 2000 – {hozirgi_yil} oralig'ida bo'lishi kerak.")
    await state.update_data(rate=48 if (hozirgi_yil - yil) <= 5 else CFG["calc_auto"]["rate"])
    data = await state.get_data()
    cfg  = CFG[data["code"]]
    await msg.answer(
        f"Kredit summasini kiriting:\n({fmt(cfg['min'])} – {fmt(cfg['max'])}) so'm",
        reply_markup=BACK_KB,
    )
    await state.set_state(CalcFSM.sum)


@router.message(CalcFSM.sum)
async def ask_months(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    cfg  = CFG[data["code"]]
    summa_text = re.sub(r"\D", "", msg.text or "")
    if not summa_text:
        return await msg.answer("❗ Faqat raqam kiriting.")
    summa = float(summa_text)
    if not cfg["min"] <= summa <= cfg["max"]:
        return await msg.answer(f"❗ {fmt(cfg['min'])} – {fmt(cfg['max'])} oralig'ida.")
    await state.update_data(summa=summa)

    if cfg["mmin"] == cfg["mmax"]:
        # Yagona muddat — to'g'ridan natijaga
        await state.update_data(months=cfg["mmin"])
        await _finish(msg, msg.bot, state)
    else:
        await state.set_state(CalcFSM.month)
        await msg.answer(
            f"📆 Muddatni kiriting ({cfg['mmin']} – {cfg['mmax']}) oy:",
            reply_markup=BACK_KB,
        )


@router.message(CalcFSM.month)
async def result(msg: types.Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    cfg  = CFG[data["code"]]

    # Agar months allaqachon o'rnatilgan bo'lsa (mmin==mmax holati)
    if "months" in data and cfg["mmin"] == cfg["mmax"]:
        await _finish(msg, bot, state)
        return

    oy_text = re.sub(r"\D", "", msg.text or "")
    if not oy_text:
        return await msg.answer("❗ Muddatni butun oyda kiriting.")
    months = int(oy_text)
    if not cfg["mmin"] <= months <= cfg["mmax"]:
        return await msg.answer(f"❗ {cfg['mmin']} – {cfg['mmax']} oy oralig'ida.")
    await state.update_data(months=months)
    await _finish(msg, bot, state)


async def _finish(msg: types.Message, bot: Bot, state: FSMContext):
    data       = await state.get_data()
    cfg        = CFG[data["code"]]
    summa      = data["summa"]
    months     = data["months"]
    rate       = data.get("rate", cfg["rate"])
    grace_days = cfg.get("grace_days", 0)
    await state.clear()

    wait_msg = await msg.answer("⏳ Jadval tayyorlanmoqda...")
    await _send_results(msg, bot, cfg, summa, months, rate, grace_days)
    with contextlib.suppress(Exception):
        await wait_msg.delete()
