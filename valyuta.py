import datetime
import aiohttp
import io
import re
import contextlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from html.parser import HTMLParser
from aiogram import Router, types, F
from aiogram.types import BufferedInputFile

router = Router()
ANIQ_URL = "https://aniq.uz/uz/valyuta-kurslari"

TARGET_BANKS = [
    "Agrobank",
    "Mikrokreditbank",
    "Xalq banki",
    "Hamkorbank",
    "Trastbank",
    "Asaka bank",
    "Turon bank",
    "Ipoteka bank",
    "NBU",
    "Kapitalbank",
]

ALIASES = {
    "agro bank":     "Agrobank",
    "agrobank":      "Agrobank",
    "mikrokreditbank": "Mikrokreditbank",
    "xalq banki":    "Xalq banki",
    "xalq bank":     "Xalq banki",
    "hamkorbank":    "Hamkorbank",
    "trastbank":     "Trastbank",
    "asaka bank":    "Asaka bank",
    "turon bank":    "Turon bank",
    "ipoteka bank":  "Ipoteka bank",
    "nbu":           "NBU",
    "kapitalbank":   "Kapitalbank",
}


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
        buy_cell  = row[2]
        sell_cell = row[3]
        key = bank_name.lower()
        canonical = ALIASES.get(key)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        buy  = _parse_number(buy_cell)
        sell = _parse_number(sell_cell)
        if buy and sell:
            result.append((canonical, buy, sell))

    # TARGET_BANKS tartibida saralash
    order = {b: i for i, b in enumerate(TARGET_BANKS)}
    result.sort(key=lambda x: order.get(x[0], 99))
    return result


@router.message(F.text == "/valyuta")
async def valyuta_handler(msg: types.Message):
    today = datetime.date.today().strftime("%d.%m.%Y")

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.get(ANIQ_URL, timeout=timeout) as resp:
                html = await resp.text()
    except Exception as e:
        await msg.answer("❌ Kurslarni olishda xatolik yuz berdi.")
        return

    banks = _parse_banks(html)

    if not banks:
        await msg.answer("⚠️ Banklar bo'yicha ma'lumot topilmadi.")
        return

    fig, ax = plt.subplots(figsize=(8, len(banks) * 0.45 + 1.8))
    ax.axis("off")

    ax.set_title(
        f"Banklar bo'yicha USD kurslari ({today})",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.text(
        0.5, 0.97,
        "⚠ Eslatma! Bizda faqat Milliy valyuta(so'm) orqali xizmat ko'rsatiladi!\n"
        "Ma'lumotlar 9⁰⁰ dan keyin yangilanadi",
        ha="center", va="top", transform=ax.transAxes,
        fontsize=9, color="red", fontweight="bold",
    )

    columns = ["Bank nomi", "Sotib olish (so'm)", "Sotish (so'm)"]
    data = [
        [b, f"{buy:,}".replace(",", " "), f"{sell:,}".replace(",", " ")]
        for b, buy, sell in banks
    ]

    table = ax.table(
        cellText=data, colLabels=columns,
        cellLoc="center", loc="center",
        colColours=["#A9D0F5"] * 3,
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.4)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    await msg.answer_photo(
        photo=BufferedInputFile(buf.getvalue(), filename="valyuta.png")
    )
