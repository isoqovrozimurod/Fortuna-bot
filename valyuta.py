"""
/valyuta — banklar bo'yicha USD kurslari (aniq.uz).

Jadval Pillow bilan chiziladi (matplotlib dan 3-5x tezroq va
event loop ni bloklamaydi) — calculator.py va kredit.py bilan
bir xil arxitektura.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import io
import logging
import re
from functools import partial
from html.parser import HTMLParser

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)
router = Router()

ANIQ_URL = "https://aniq.uz/uz/valyuta-kurslari"

# ── Font (Railway/Linux muhitida mavjud yo'llar) ───────────────────────
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


TARGET_BANKS = [
    "Agrobank",
    "Mikrokreditbank",
    "Xalq banki",
    "Hamkorbank",
    "Aloqabank",
    "Trastbank",
    "Asaka bank",
    "Turon bank",
    "Ipoteka bank",
    "NBU",
    "Kapitalbank",
]

ALIASES = {
    "agro bank":        "Agrobank",
    "agrobank":         "Agrobank",
    "mikrokreditbank":  "Mikrokreditbank",
    "xalq banki":       "Xalq banki",
    "xalq bank":        "Xalq banki",
    "hamkorbank":       "Hamkorbank",
    "aloqa bank":       "Aloqabank",
    "aloqabank":        "Aloqabank",
    "trastbank":        "Trastbank",
    "asaka bank":       "Asaka bank",
    "asakabank":        "Asaka bank",
    "turon bank":       "Turon bank",
    "turonbank":        "Turon bank",
    "ipoteka bank":     "Ipoteka bank",
    "ipotekabank":      "Ipoteka bank",
    "nbu":              "NBU",
    "kapitalbank":      "Kapitalbank",
}


# ── HTML parser ────────────────────────────────────────────────────────

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = True
            self._buf = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell:
            self._row.append(re.sub(r"\s+", " ", self._buf).strip())
            self._cell = False
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = []

    def handle_data(self, data):
        if self._cell:
            self._buf += data


def _parse_number(text: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", text)
    return int(cleaned) if cleaned else None


def _parse_banks(html: str) -> list[tuple[str, int, int]]:
    parser = TableParser()
    parser.feed(html)

    result = []
    seen = set()
    # Jadval strukturasi: ['#', 'Bank nomi', 'Sotib olish ...', 'Sotish ...']
    for row in parser.rows:
        if len(row) < 4:
            continue
        if not row[0].strip().isdigit():
            continue
        bank_name = row[1].strip()
        canonical = ALIASES.get(bank_name.lower())
        if not canonical or canonical in seen:
            continue
        buy  = _parse_number(row[2])
        sell = _parse_number(row[3])
        if buy and sell:
            seen.add(canonical)
            result.append((canonical, buy, sell))

    order = {b: i for i, b in enumerate(TARGET_BANKS)}
    result.sort(key=lambda x: order.get(x[0], 99))
    return result


# ── Pillow jadval ──────────────────────────────────────────────────────

def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _draw_table_sync(banks: list[tuple[str, int, int]], today: str) -> bytes:
    HEADERS = ["Bank nomi", "Sotib olish (so'm)", "Sotish (so'm)"]
    COL_W   = [230, 210, 200]
    ROW_H   = 34
    FS      = 15
    PAD     = 18
    TITLE_H = 34
    WARN_H  = 46

    font       = _load_font(_FONT_PATHS, FS)
    font_bold  = _load_font(_FONT_BOLD_PATHS, FS)
    font_title = _load_font(_FONT_BOLD_PATHS, 18)
    font_warn  = _load_font(_FONT_BOLD_PATHS, 12)

    body = [HEADERS] + [
        [b, _fmt(buy), _fmt(sell)] for b, buy, sell in banks
    ]

    n_rows = len(body)
    W = sum(COL_W) + PAD * 2
    H = ROW_H * n_rows + PAD * 2 + TITLE_H + WARN_H

    img  = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    # Sarlavha — markazda
    title = f"Banklar bo'yicha USD kurslari ({today})"
    tw    = draw.textlength(title, font=font_title)
    draw.text(((W - tw) / 2, PAD), title, fill="#003366", font=font_title)

    # Ogohlantirish — qizil, markazda
    warn_lines = [
        "⚠ Eslatma! Bizda faqat Milliy valyuta (so'm) orqali xizmat ko'rsatiladi!",
        "Ma'lumotlar 09:00 dan keyin yangilanadi",
    ]
    wy = PAD + TITLE_H
    for line in warn_lines:
        lw = draw.textlength(line, font=font_warn)
        draw.text(((W - lw) / 2, wy), line, fill="#CC0000", font=font_warn)
        wy += 18

    y0 = PAD + TITLE_H + WARN_H

    for ri, row in enumerate(body):
        y = y0 + ri * ROW_H
        x = PAD
        for ci, (cell, cw) in enumerate(zip(row, COL_W)):
            if ri == 0:
                bg = "#A9D0F5"          # sarlavha qatori
            elif ri % 2 == 0:
                bg = "#F4F4F4"          # oraliq qator
            else:
                bg = "#FFFFFF"

            draw.rectangle([x, y, x + cw - 1, y + ROW_H - 1],
                           fill=bg, outline="#BBBBBB", width=1)

            f  = font_bold if ri == 0 else font
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


async def _draw_table(banks, today: str) -> BufferedInputFile:
    """Rasm chizishni executor da bajaradi — event loop bloklanmaydi."""
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, partial(_draw_table_sync, banks, today))
    return BufferedInputFile(data, filename="valyuta.png")


# ── Kesh ───────────────────────────────────────────────────────────────
# Kurslar kuniga bir marta (09:00 dan keyin) yangilanadi — shuning uchun
# tayyor rasmni kun davomida qayta ishlatamiz. Bu ham aniq.uz ga
# keraksiz so'rovlarni, ham qayta chizishni oldini oladi.

_cache: dict = {"date": "", "file_id": None}


@router.message(Command("valyuta"))
async def valyuta_handler(msg: types.Message):
    today = datetime.date.today().strftime("%d.%m.%Y")

    # Keshdagi tayyor rasm (file_id) bo'lsa — darhol yuboramiz
    if _cache["date"] == today and _cache["file_id"]:
        try:
            await msg.answer_photo(photo=_cache["file_id"])
            return
        except Exception as e:
            logger.warning(f"Keshlangan file_id ishlamadi, qayta chizamiz: {e}")
            _cache["file_id"] = None

    wait_msg = await msg.answer("⏳ Kurslar yuklanmoqda...")

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.get(ANIQ_URL, timeout=timeout) as resp:
                html = await resp.text()
    except Exception as e:
        logger.error(f"aniq.uz dan kurs olishda xato: {e}")
        with contextlib.suppress(Exception):
            await wait_msg.edit_text(
                "❌ Kurslarni olishda xatolik yuz berdi.\n"
                "Iltimos, birozdan so'ng qayta urinib ko'ring."
            )
        return

    banks = _parse_banks(html)

    if not banks:
        logger.warning("aniq.uz: banklar ro'yxati bo'sh (sayt tuzilishi o'zgargan bo'lishi mumkin)")
        with contextlib.suppress(Exception):
            await wait_msg.edit_text("⚠️ Banklar bo'yicha ma'lumot topilmadi.")
        return

    try:
        photo = await _draw_table(banks, today)
        sent  = await msg.answer_photo(photo=photo)
        # Keyingi so'rovlar uchun file_id ni keshlaymiz
        if sent.photo:
            _cache["date"]    = today
            _cache["file_id"] = sent.photo[-1].file_id
    except Exception as e:
        logger.error(f"Valyuta jadvalini chizishda xato: {e}")
        with contextlib.suppress(Exception):
            await wait_msg.edit_text("❌ Jadvalni tayyorlashda xatolik yuz berdi.")
        return

    with contextlib.suppress(Exception):
        await wait_msg.delete()
