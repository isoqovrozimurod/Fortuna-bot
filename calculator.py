from __future__ import annotations
import io, uuid, re, asyncio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from typing import List
from datetime import datetime
from functools import partial

from aiogram import Router, F, Bot, types
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    BufferedInputFile,
)

router = Router()
_plt_lock = asyncio.Lock()  # matplotlib thread-safe emas

class CalcFSM(StatesGroup):
    year  = State()
    sum   = State()
    month = State()

CFG = {
    "calc_pension": {
        "name": "Pensiya krediti", "rate": 49,
        "min": 3_000_000, "max": 30_000_000, "mmin": 12, "mmax": 24
    },
    "calc_salary": {
        "name": "Ish haqi krediti", "rate": 49,
        "min": 3_000_000, "max": 40_000_000, "mmin": 12, "mmax": 36
    },
    "calc_auto": {
        "name": "Avto garov krediti", "rate": 54,
        "min": 3_000_000, "max": 300_000_000, "mmin": 12, "mmax": 36
    },
    "calc_biznes": {
        "name": "Biznes uchun mikroqarz", "rate": 54,
        "min": 10_000_000, "max": 50_000_000, "mmin": 12, "mmax": 24
    },
    "calc_hamkor": {
        "name": "Hamkor krediti", "rate": 56,
        "min": 3_000_000, "max": 20_000_000, "mmin": 12, "mmax": 12,
        "grace_days": 30
    },
}

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kredit turlari", callback_data="credit_types")]]
)

fmt = lambda n: f"{round(n):,}".replace(",", " ")


# ── Jadvallar ─────────────────────────────────────────────────────

def ann_table(pr: int, rate: float, m: int, grace_days: int = 0) -> List[List]:
    r   = rate / 12 / 100
    pay = pr * r / (1 - (1 + r) ** -m)
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
        rows.append([f"{i}-oy", actual_interest, principal, actual_payment, max(0, bal)])
    return rows


def diff_table(pr: int, rate: float, m: int, grace_days: int = 0) -> List[List]:
    r         = rate / 12 / 100
    principal = pr / m
    bal       = pr
    rows = [["Boshlanish", 0, 0, 0, pr]]
    for i in range(1, m + 1):
        interest = 0 if (i == 1 and grace_days >= 30) else bal * r
        total    = principal + interest
        bal     -= principal
        rows.append([f"{i}-oy", interest, principal, total, max(0, bal)])
    return rows


# ── PNG generatsiya — executor da ishlaydi ────────────────────────

def _draw_png_sync(rows: List[List], title: str, kredit_summa: float) -> bytes:
    """Sinxron — run_in_executor orqali chaqiriladi."""
    headers = ["Sana", "Foizlar", "Asosiy qarz", "Oylik to'lov", "Qoldiq summa"]
    body    = [headers]
    for r in rows:
        body.append([r[0], *[fmt(x) for x in r[1:]]])
    jami_foiz  = sum(r[1] for r in rows[1:])
    jami_tolov = sum(r[3] for r in rows[1:])
    body.append(["Jami", fmt(jami_foiz), fmt(kredit_summa), fmt(jami_tolov), "-"])

    row_count = len(body)
    fig, ax   = plt.subplots(figsize=(10, 0.45 + row_count * 0.35))
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
            elif r % 2 == 0:
                cell.set_facecolor("#f9f9f9")
            cell.set_edgecolor("black")
            cell.set_linewidth(0.4)

    plt.title(title, fontsize=13, weight="bold")
    buf = io.BytesIO()
    plt.savefig(buf, dpi=200, format="png", bbox_inches="tight")  # 200 dpi — tezroq
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


async def draw_png(rows: List[List], title: str, kredit_summa: float) -> BufferedInputFile:
    """Async wrapper — event loop ni bloklamaydi. Lock bilan thread-safe."""
    async with _plt_lock:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, partial(_draw_png_sync, rows, title, kredit_summa))
    return BufferedInputFile(data, filename=f"{uuid.uuid4()}.png")


# ── Natija chiqarish ──────────────────────────────────────────────

async def _send_results(
    msg: types.Message,
    bot: Bot,
    cfg: dict,
    summa: float,
    months: int,
    rate: float,
    grace_days: int,
):
    """Ikki jadval rasmini parallel generatsiya qilib yuboradi."""
    ann_rows  = ann_table(summa, rate, months, grace_days)
    diff_rows = diff_table(summa, rate, months, grace_days)
    label     = f"{cfg['name']} – {months} oy"

    # Ketma-ket — matplotlib lock tufayli parallel foyda yo'q
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


# ── Handlerlar ────────────────────────────────────────────────────

@router.callback_query(F.data.in_(CFG.keys()))
async def ask_year_or_sum(cb: CallbackQuery, state: FSMContext):
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
        return await msg.answer("❗️Yilni raqam bilan kiriting (masalan, 2022).")
    yil = int(yil_text)
    hozirgi_yil = datetime.now().year
    if yil < 2000 or yil > hozirgi_yil:
        return await msg.answer(f"❗️Yil 2000 va {hozirgi_yil} oralig'ida bo'lishi kerak.")
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
        return await msg.answer("❗️Faqat raqam kiriting.")
    summa = float(summa_text)
    if not cfg["min"] <= summa <= cfg["max"]:
        return await msg.answer(f"❗️{fmt(cfg['min'])} – {fmt(cfg['max'])} oralig'ida.")
    await state.update_data(summa=summa)
    if cfg["mmin"] == cfg["mmax"]:
        await state.update_data(months=cfg["mmin"])
        await state.set_state(CalcFSM.month)
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

    # Muddat avtomatik o'rnatilgan (hamkor) — raqam kutmaydi
    if "months" in data and cfg["mmin"] == cfg["mmax"]:
        await _finish(msg, bot, state)
        return

    oy_text = re.sub(r"\D", "", msg.text or "")
    if not oy_text:
        return await msg.answer("❗️Muddatni butun oyda kiriting.")
    months = int(oy_text)
    if not cfg["mmin"] <= months <= cfg["mmax"]:
        return await msg.answer(f"❗️{cfg['mmin']} – {cfg['mmax']} oy oralig'ida.")
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
    await msg.answer("⏳ Jadval tayyorlanmoqda...")
    await _send_results(msg, bot, cfg, summa, months, rate, grace_days)
