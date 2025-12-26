from __future__ import annotations
import io, uuid, re, matplotlib.pyplot as plt
from typing import List
from datetime import datetime

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile,
)

router = Router()

# FSM holatlari
class CalcFSM(StatesGroup):
    year = State()   # faqat "calc_auto" uchun
    sum = State()
    month = State()

# Kredit konfiguratsiyasi
CFG = {
    "calc_pension": {
        "name": "Pensiya krediti", "rate": 49,
        "min": 3_000_000, "max": 30_000_000, "mmin": 12, "mmax": 24},
    "calc_salary": {
        "name": "Ish haqi krediti", "rate": 49,
        "min": 3_000_000, "max": 40_000_000, "mmin": 12, "mmax": 36},
    "calc_auto": {
        "name": "Avto garov krediti", "rate": 54,
        "min": 3_000_000, "max": 300_000_000, "mmin": 12, "mmax": 36},
    "calc_biznes": {
        "name": "Biznes uchun mikroqarz", "rate": 54,
        "min": 10_000_000, "max": 50_000_000, "mmin": 12, "mmax": 24,
    },
}

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kredit turlari", callback_data="credit_types")]]
)

fmt = lambda n: f"{round(n):,}".replace(",", " ")

# === Annuitet jadvali ===
def ann_table(pr: int, rate: float, m: int) -> List[List]:
    r = rate / 12 / 100
    pay = pr * r / (1 - (1 + r) ** -m)
    bal = pr
    rows = [["Boshlanish", 0, 0, 0, pr]]
    for i in range(1, m + 1):
        interest = bal * r
        principal = pay - interest
        bal -= principal
        rows.append([f"{i}-oy", interest, principal, pay, max(0, bal)])
    return rows

# === Differensial jadvali ===
def diff_table(pr: int, rate: float, m: int) -> List[List]:
    r = rate / 12 / 100
    principal = pr / m
    bal = pr
    rows = [["Boshlanish", 0, 0, 0, pr]]
    for i in range(1, m + 1):
        interest = bal * r
        total = principal + interest
        bal -= principal
        rows.append([f"{i}-oy", interest, principal, total, max(0, bal)])
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

    plt.title(title, fontsize=13, weight="bold")
    buf = io.BytesIO()
    plt.savefig(buf, dpi=300, format="png", bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return BufferedInputFile(buf.getvalue(), filename=f"{uuid.uuid4()}.png")

# === Kredit turi tanlandi ===
@router.callback_query(F.data.in_(CFG.keys()))
async def ask_year_or_sum(cb: CallbackQuery, state: FSMContext):
    cfg = CFG[cb.data]
    await state.update_data(code=cb.data)

    if cb.data == "calc_auto":
        await cb.message.answer(
            "🚘 So'nggi 5 yilda ishlab chiqarilgan avtomashinalar uchun hozirgi foiz stavkadan 6% chegirma mavjud.\n\n"
            "<b>Avtomobil ishlab chiqarilgan yilini kiriting:👇</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=BACK_KB
        )
        await state.set_state(CalcFSM.year)
    else:
        await cb.message.answer(
            f"💳 <b>{cfg['name']}</b>\n"
            f"Kredit summasini kiriting:\n({fmt(cfg['min'])} – {fmt(cfg['max'])}) so‘m",
            parse_mode=ParseMode.HTML,
            reply_markup=BACK_KB,
        )
        await state.set_state(CalcFSM.sum)

# === Avto yil kiritildi ===
@router.message(CalcFSM.year)
async def ask_sum_after_year(msg: types.Message, state: FSMContext):
    yil_text = re.sub(r"\D", "", msg.text)
    if not yil_text:
        return await msg.answer("❗️Yilni raqam bilan kiriting (masalan, 2022).")

    yil = int(yil_text)
    hozirgi_yil = datetime.now().year

    if yil < 2000 or yil > hozirgi_yil:
        return await msg.answer(f"❗️Yil 2000 va {hozirgi_yil} oralig‘ida bo‘lishi kerak.")

    farq = hozirgi_yil - yil
    await state.update_data(rate = 48 if farq <= 5 else CFG["calc_auto"]["rate"])

    data = await state.get_data()
    cfg = CFG[data["code"]]
    await msg.answer(
        f"Kredit summasini kiriting:\n({fmt(cfg['min'])} – {fmt(cfg['max'])}) so‘m",
        reply_markup=BACK_KB,
    )
    await state.set_state(CalcFSM.sum)

# === Summani olish ===
@router.message(CalcFSM.sum)
async def ask_months(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    cfg = CFG[data["code"]]

    summa_text = re.sub(r"\D", "", msg.text)
    if not summa_text:
        return await msg.answer("❗️Faqat raqam kiriting.")

    summa = float(summa_text)
    if not cfg["min"] <= summa <= cfg["max"]:
        return await msg.answer(f"❗️{fmt(cfg['min'])} – {fmt(cfg['max'])} oralig‘ida.")

    await state.update_data(summa=summa)
    await state.set_state(CalcFSM.month)
    await msg.answer(f"📆 Muddatni kiriting ({cfg['mmin']} – {cfg['mmax']}) oy:", reply_markup=BACK_KB)

# === Muddat kiritildi – natija ===
@router.message(CalcFSM.month)
async def result(msg: types.Message, bot: Bot, state: FSMContext):
    oy_text = re.sub(r"\D", "", msg.text)
    if not oy_text:
        return await msg.answer("❗️Muddatni butun oyda kiriting.")

    months = int(oy_text)
    data = await state.get_data()
    cfg = CFG[data["code"]]

    if not cfg["mmin"] <= months <= cfg["mmax"]:
        return await msg.answer(f"❗️{cfg['mmin']} – {cfg['mmax']} oy oralig‘ida.")

    summa = data["summa"]
    rate = data.get("rate", cfg["rate"])

    ann_png = draw_png(ann_table(summa, rate, months),
                       f"{cfg['name']} – {months} oy | Annuitet", summa)
    diff_png = draw_png(diff_table(summa, rate, months),
                        f"{cfg['name']} – {months} oy | Differensial", summa)

    await bot.send_photo(msg.chat.id, ann_png, caption="📄 <b>Annuitet jadval\n@Gallaorol_FBbot</b>", parse_mode=ParseMode.HTML)
    await bot.send_photo(msg.chat.id, diff_png, caption="📄 <b>Differensial jadval\n@Gallaorol_FBbot</b>", parse_mode=ParseMode.HTML)
    await msg.answer("⬅️ Kredit turlari", reply_markup=BACK_KB)
    await state.clear()
