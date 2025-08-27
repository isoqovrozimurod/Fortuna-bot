# kredit.py
from __future__ import annotations

import os
import re
import io
import uuid
from typing import List

# Headless muhit (Railway) uchun
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

# --- ENV ---
load_dotenv()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0  # noto‘g‘ri bo‘lsa 0 qilib qo‘yamiz

router = Router()

# === FSM holatlari ===
class KreditFSM(StatesGroup):
    summa = State()
    month = State()
    rate = State()

fmt = lambda n: f"{round(n):,}".replace(",", " ")

def only_number(text: str, allow_float: bool = False) -> str:
    """
    Matndan faqat raqamlarni ajratib oladi.
    allow_float=True bo‘lsa bitta nuqtaga ruxsat beradi.
    """
    if allow_float:
        # faqat bitta nuqta qoldiramiz
        cleaned = re.sub(r"[^0-9.]", "", text or "")
        # ortiqcha nuqtalarni olib tashlaymiz (faqat birinchisini qoldiramiz)
        if cleaned.count(".") > 1:
            first = cleaned.find(".")
            cleaned = cleaned[:first + 1] + cleaned[first + 1:].replace(".", "")
        return cleaned
    return re.sub(r"\D", "", text or "")

# === Annuitet jadvali ===
def ann_table(pr: float, rate: float, m: int) -> List[List]:
    r = rate / 12 / 100
    pay = pr * r / (1 - (1 + r) ** -m)
    bal = pr
    rows = [["Boshlanish", 0.0, 0.0, 0.0, pr]]
    for i in range(1, m + 1):
        interest = bal * r
        principal = pay - interest
        bal -= principal
        rows.append([f"{i}-oy", interest, principal, pay, max(0.0, bal)])
    return rows

# === Differensial jadvali ===
def diff_table(pr: float, rate: float, m: int) -> List[List]:
    r = rate / 12 / 100
    principal = pr / m
    bal = pr
    rows = [["Boshlanish", 0.0, 0.0, 0.0, pr]]
    for i in range(1, m + 1):
        interest = bal * r
        total = principal + interest
        bal -= principal
        rows.append([f"{i}-oy", interest, principal, total, max(0.0, bal)])
    return rows

# === Jadvalni rasmga chizish ===
def draw_png(rows: List[List], title: str, kredit_summa: float) -> BufferedInputFile:
    headers = ["Sana", "Foizlar", "Asosiy qarz", "Oylik to‘lov", "Qoldiq summa"]
    body = [headers]

    for r in rows:
        body.append([r[0], *[fmt(x) for x in r[1:]]])

    jami_foiz = sum(r[1] for r in rows[1:])
    jami_tolov = sum(r[3] for r in rows[1:])
    body.append(["Jami", fmt(jami_foiz), fmt(kredit_summa), fmt(jami_tolov), "-"])

    row_count = len(body)
    fig, ax = plt.subplots(figsize=(10, 0.45 + row_count * 0.35))
    ax.axis("off")

    table = ax.table(cellText=body, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9 if row_count <= 26 else 7)
    table.scale(1, 1.15)

    for r in range(row_count):
        for c in range(5):
            cell = table[(r, c)]
            if r == 0:
                cell.set_facecolor("#cceeff")
                cell.get_text().set_weight("bold")
            elif r == row_count - 1:
                cell.set_facecolor("#b3e6ff")
                cell.get_text().set_weight("bold")
            elif c == 3 and r not in (0, row_count - 1):
                cell.set_facecolor("#e6e6e6")
                cell.get_text().set_weight("bold")
            elif r % 2 == 0 and r not in (0, row_count - 1):
                cell.set_facecolor("#f9f9f9")
            cell.set_edgecolor("black")
            cell.set_linewidth(0.4)

    plt.suptitle(title, fontsize=13, weight="bold")
    buf = io.BytesIO()
    plt.savefig(buf, dpi=300, format="png", bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return BufferedInputFile(buf.getvalue(), filename=f"{uuid.uuid4()}.png")

# === /kredit — faqat admin uchun ===
@router.message(F.text == "/kredit")
async def start_kredit(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Sizda bu buyruqdan foydalanish huquqi yo‘q.")
    await msg.answer("💰 Kredit summasini kiriting (100 000 – 1 000 000 000) so‘m:")
    await state.set_state(KreditFSM.summa)

# === Summani qabul qilish ===
@router.message(KreditFSM.summa)
async def get_sum(msg: types.Message, state: FSMContext):
    summa_text = only_number(msg.text)  # faqat raqamlar
    if not summa_text:
        return await msg.answer("❗️Faqat raqam kiriting.")
    summa = float(summa_text)
    if not 100_000 <= summa <= 1_000_000_000:
        return await msg.answer("❗️100 000 – 1 000 000 000 so‘m oralig‘ida kiriting.")
    await state.update_data(summa=summa)
    await msg.answer("📆 Kredit muddatini kiriting (1 – 300) oy:")
    await state.set_state(KreditFSM.month)

# === Muddat qabul qilish ===
@router.message(KreditFSM.month)
async def get_month(msg: types.Message, state: FSMContext):
    oy_text = only_number(msg.text)  # faqat raqamlar
    if not oy_text:
        return await msg.answer("❗️Faqat raqam kiriting.")
    month = int(oy_text)
    if not 1 <= month <= 300:
        return await msg.answer("❗️1 – 300 oy oralig‘ida kiriting.")
    await state.update_data(month=month)   # <<— kalit nomi month
    await msg.answer("📊 Foiz stavkasini kiriting (%):")
    await state.set_state(KreditFSM.rate)

# === Foiz stavkasi qabul qilish va natija ===
@router.message(KreditFSM.rate)
async def get_rate_and_result(msg: types.Message, bot: Bot, state: FSMContext):
    rate_text = only_number(msg.text, allow_float=True)  # mas: 24 yoki 24.5
    if not rate_text:
        return await msg.answer("❗️Foiz stavkasini to‘g‘ri kiriting (masalan, 24).")
    rate = float(rate_text)

    data = await state.get_data()
    summa: float = data["summa"]
    months: int = data["month"]  # <<— mos keladi

    # Jadvallar
    ann_png = draw_png(
        ann_table(summa, rate, months),
        f"Kredit – {months} oy | Annuitet ({rate}%)",
        summa,
    )
    diff_png = draw_png(
        diff_table(summa, rate, months),
        f"Kredit – {months} oy | Differensial ({rate}%)",
        summa,
    )

    await bot.send_photo(msg.chat.id, ann_png, caption="📄 <b>Annuitet jadval</b>", parse_mode=ParseMode.HTML)
    await bot.send_photo(msg.chat.id, diff_png, caption="📄 <b>Differensial jadval</b>", parse_mode=ParseMode.HTML)

    await state.clear()
