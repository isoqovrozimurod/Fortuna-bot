"""
Scoring — qarz yuki hisoblash (faqat sub_adminlar uchun)
"""
from __future__ import annotations

import os
import re
import base64
import json
import asyncio
import logging

import gspread
from google.oauth2.service_account import Credentials
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

logger = logging.getLogger(__name__)
router = Router()

SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "sub_adminlar"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

_gc: gspread.Client | None = None


# ===================== RUXSAT TEKSHIRUV =====================

def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


def _is_subadmin_sync(user_id: int) -> bool:
    try:
        gc = _get_gc()
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SUBADMIN_SHEET)
        ids = ws.col_values(2)[1:]
        return str(user_id) in [str(v).strip() for v in ids]
    except Exception as e:
        logger.error(f"Sub-admin tekshirishda xato: {e}")
        return False


async def is_subadmin(user_id: int) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _is_subadmin_sync, user_id)


# ===================== KREDIT KONFIGURATSIYASI =====================

# Foiz stavkalari (yillik annuitet hisoblash uchun)
RATES = {
    "pensiya":  49,
    "ish_haqi": 49,
    "hamkor":   56,
}

# Kredit muddatlari (oy)
TERMS = {
    "pensiya":  [12, 18, 24],
    "ish_haqi": [12, 18, 24, 30, 36],
    "hamkor":   [12],
}

# Qarz yuki chegaralari
def get_limit(kredit_turi: str, kredit_summasi: float, ish_joyi: str = "") -> float:
    """Qarz yuki chegarasi — kredit SUMMASI asosida (0.0 - 1.0)"""
    if kredit_turi == "pensiya":
        return 0.50
    elif kredit_turi == "hamkor":
        return 0.50
    elif kredit_turi == "ish_haqi":
        if ish_joyi == "budjet":
            # summa <= 20M → 75%, 20M < summa <= 40M → 50%
            return 0.75 if kredit_summasi <= 20_000_000 else 0.50
        else:  # xususiy
            # summa <= 10M → 75%, 10M < summa <= 20M → 50%
            return 0.75 if kredit_summasi <= 10_000_000 else 0.50
    return 0.75


LIMIT_TEXT = {
    "pensiya": (
        "📌 <b>Pensiya krediti — qarz yuki chegarasi:</b>\n"
        "• Qarz yuki <b>50%</b> dan oshmasligi kerak\n"
        "• Oylik daromad sifatida oxirgi pensiya summasi kiritiladi"
    ),
    "ish_haqi": (
        "📌 <b>Ish haqi krediti — qarz yuki chegarasi:</b>\n"
        "• Budjet tashkiloti xodimlari:\n"
        "  – Kredit summasi ≤20M → <b>75%</b>\n"
        "  – Kredit summasi 20M–40M → <b>50%</b>\n"
        "• Xususiy tashkilot xodimlari:\n"
        "  – Kredit summasi ≤10M → <b>75%</b>\n"
        "  – Kredit summasi 10M–20M → <b>50%</b>\n"
        "• Xususiy uchun maksimal kredit: 20 000 000 so'm\n"
        "• Formula: Yillik daromad × 88% ÷ 12 = oylik daromad"
    ),
    "hamkor": (
        "📌 <b>Hamkor krediti — qarz yuki chegarasi:</b>\n"
        "• Qarz yuki <b>50%</b> dan oshmasligi kerak\n"
        "• Formula: Yillik daromad × 88% ÷ 12 = oylik daromad\n"
        "• Muddat: faqat 12 oy"
    ),
}


# ===================== HISOBLASH FUNKSIYALARI =====================

def ann_payment(principal: float, rate_annual: float, months: int) -> float:
    """Annuitet oylik to'lov"""
    r = rate_annual / 12 / 100
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def diff_max_payment(principal: float, rate_annual: float, months: int) -> float:
    """Differensial — birinchi (eng katta) oylik to'lov"""
    r         = rate_annual / 12 / 100
    principal_part = principal / months
    interest  = principal * r
    return principal_part + interest


def max_loan_from_payment(max_payment: float, rate_annual: float, months: int) -> float:
    """Berilgan oylik to'lovdan maksimal kredit summasini hisoblaydi (annuitet)"""
    r = rate_annual / 12 / 100
    if r == 0:
        return max_payment * months
    return max_payment * (1 - (1 + r) ** -months) / r


def max_loan_diff(max_payment: float, rate_annual: float, months: int) -> float:
    """Differensial uchun maksimal kredit summasi (birinchi oydan hisoblaydi)"""
    r = rate_annual / 12 / 100
    # max_payment = P/m + P*r  =>  P = max_payment / (1/m + r)
    denom = 1 / months + r
    if denom == 0:
        return 0
    return max_payment / denom


fmt     = lambda n: f"{round(n):,}".replace(",", " ")
fmt100k = lambda n: f"{int(n // 100_000) * 100_000:,}".replace(",", " ")


def calculate_scoring(
    kredit_turi: str,
    kredit_summasi: float,
    oylik_daromad: float,
    mavjud_tolovlar: float,
    ish_joyi: str,
    rate: float,
    muddat: int | None = None,
) -> dict:
    """
    Scoring hisoblaydi.
    Qaytaradi: {
        load_pct: float,           # hisoblangan qarz yuki %
        limit_pct: float,          # belgilangan chegara %
        ok: bool,                  # kredit ajratilishi mumkinmi
        max_loan: dict,            # {term: {ann: float, diff: float}}
        ann_payment_requested: float,  # so'ralgan summa uchun annuitet to'lov
        diff_payment_requested: float, # so'ralgan summa uchun diff to'lov
    }
    """
    terms    = TERMS[kredit_turi]
    t0       = muddat if muddat and muddat in terms else min(terms)
    limit    = get_limit(kredit_turi, kredit_summasi, ish_joyi)

    # Tanlangan muddat uchun oylik to'lov
    ann_pay  = ann_payment(kredit_summasi, rate, t0)
    diff_pay = diff_max_payment(kredit_summasi, rate, t0)

    # Qarz yuki (annuitet asosida, konservativ)
    load_pct = (ann_pay + mavjud_tolovlar) / oylik_daromad if oylik_daromad > 0 else 1.0

    # Kredit turi uchun maksimal ruxsat etilgan summa
    max_caps = {
        "pensiya":  30_000_000,
        "hamkor":   20_000_000,
        "ish_haqi": 20_000_000 if ish_joyi == "xususiy" else 40_000_000,
    }
    max_cap = max_caps.get(kredit_turi, 40_000_000)

    # Maksimal ajratilishi mumkin bo'lgan kredit
    max_loan = {}
    for t in terms:
        free_payment = oylik_daromad * limit - mavjud_tolovlar
        if free_payment <= 0:
            max_loan[t] = {"ann": 0, "diff": 0}
        else:
            ann_max  = min(max_loan_from_payment(free_payment, rate, t), max_cap)
            diff_max = min(max_loan_diff(free_payment, rate, t), max_cap)
            max_loan[t] = {"ann": ann_max, "diff": diff_max}

    return {
        "load_pct":               load_pct,
        "limit_pct":              limit,
        "ok":                     load_pct <= limit,
        "max_loan":               max_loan,
        "ann_payment_requested":  ann_pay,
        "diff_payment_requested": diff_pay,
    }


# ===================== FSM =====================

class ScoringFSM(StatesGroup):
    kredit_turi      = State()
    ish_joyi         = State()
    kredit_summasi   = State()
    muddat           = State()
    oylik_daromad    = State()
    mavjud_tolovlar  = State()


# ===================== KLAVIATURALAR =====================

def kredit_turi_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Pensiya",  callback_data="sc_pensiya")],
        [InlineKeyboardButton(text="💼 Ish haqi", callback_data="sc_ish_haqi")],
        [InlineKeyboardButton(text="🤝 Hamkor",   callback_data="sc_hamkor")],
        [InlineKeyboardButton(text="❌ Bekor",    callback_data="sc_cancel")],
    ])


def ish_joyi_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Budjet tashkiloti",   callback_data="sc_budjet")],
        [InlineKeyboardButton(text="🏢 Xususiy tashkilot",   callback_data="sc_xususiy")],
        [InlineKeyboardButton(text="❌ Bekor",               callback_data="sc_cancel")],
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sc_cancel")]
    ])


def muddat_kb(terms: list[int]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{t} oy", callback_data=f"sc_term_{t}")
        for t in terms
    ]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="sc_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===================== HANDLERLAR =====================

def _has_scoring_access(user_id: int) -> bool:
    """ADMIN_ID, JOB_ID yoki sub_admin bo'lsa ruxsat"""
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    job_id   = int(os.getenv("JOB_ID", "0"))
    return user_id in (admin_id, job_id)


@router.message(Command("scoring"))
async def cmd_scoring(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not (_has_scoring_access(uid) or await is_subadmin(uid)):
        await message.answer("⛔ Bu buyruq faqat xodimlar uchun.")
        return
    await state.clear()
    await state.set_state(ScoringFSM.kredit_turi)
    await message.answer(
        "🧮 <b>Scoring — Qarz yuki hisoblash</b>\n\nKredit turini tanlang:",
        reply_markup=kredit_turi_kb(),
        parse_mode="HTML",
    )


@router.callback_query(ScoringFSM.kredit_turi, F.data.startswith("sc_"))
async def cb_kredit_turi(call: CallbackQuery, state: FSMContext):
    data = call.data
    if data == "sc_cancel":
        await state.clear()
        await call.message.edit_text("❌ Scoring bekor qilindi.")
        return

    turi_map = {"sc_pensiya": "pensiya", "sc_ish_haqi": "ish_haqi", "sc_hamkor": "hamkor"}
    turi = turi_map.get(data)
    if not turi:
        return

    await state.update_data(kredit_turi=turi, ish_joyi="")
    await call.answer()

    # Izoh ko'rsatamiz
    izoh = LIMIT_TEXT[turi]
    await call.message.edit_text(izoh, parse_mode="HTML")

    if turi == "ish_haqi":
        await state.set_state(ScoringFSM.ish_joyi)
        await call.message.answer(
            "🏢 Ish joyi turini tanlang:",
            reply_markup=ish_joyi_kb(),
        )
    else:
        min_s = 3_000_000
        max_s = {"pensiya": 30_000_000, "hamkor": 20_000_000}.get(turi, 50_000_000)
        await state.update_data(min_summa=min_s, max_summa=max_s)
        await state.set_state(ScoringFSM.kredit_summasi)
        await call.message.answer(
            f"💰 Mijoz olmoqchi bo'lgan kredit summasini kiriting (so'mda):\n"
            f"📌 Minimal: <b>{fmt(min_s)}</b> | Maksimal: <b>{fmt(max_s)}</b>",
            reply_markup=cancel_kb(),
            parse_mode="HTML",
        )


@router.callback_query(ScoringFSM.ish_joyi, F.data.startswith("sc_"))
async def cb_ish_joyi(call: CallbackQuery, state: FSMContext):
    if call.data == "sc_cancel":
        await state.clear()
        await call.message.edit_text("❌ Scoring bekor qilindi.")
        return

    ish_joyi_map = {"sc_budjet": "budjet", "sc_xususiy": "xususiy"}
    ish_joyi = ish_joyi_map.get(call.data)
    if not ish_joyi:
        return

    await state.update_data(ish_joyi=ish_joyi)
    await call.answer()
    await state.set_state(ScoringFSM.kredit_summasi)
    min_s, max_s = 3_000_000, 40_000_000
    await state.update_data(min_summa=min_s, max_summa=max_s)
    await call.message.edit_text(
        f"✅ Muddat: <b>{term} oy</b>\n\n{daromad_prompt}",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )


@router.message(ScoringFSM.kredit_summasi)
async def get_kredit_summasi(message: Message, state: FSMContext):
    val = re.sub(r"\D", "", message.text or "")
    if not val:
        await message.answer("❗ Faqat raqam kiriting:", reply_markup=cancel_kb())
        return
    summa = float(val)
    data_check = await state.get_data()
    min_s = data_check.get("min_summa", 3_000_000)
    max_s = data_check.get("max_summa", 300_000_000)
    if summa < min_s:
        await message.answer(
            f"❗ Minimal kredit summasi: <b>{fmt(min_s)}</b> so'm",
            reply_markup=cancel_kb(), parse_mode="HTML"
        )
        return
    if summa > max_s:
        await message.answer(
            f"❗ Maksimal kredit summasi: <b>{fmt(max_s)}</b> so'm",
            reply_markup=cancel_kb(), parse_mode="HTML"
        )
        return
    await state.update_data(kredit_summasi=summa)

    data = await state.get_data()
    turi = data["kredit_turi"]
    terms = TERMS[turi]
    await state.set_state(ScoringFSM.muddat)
    await message.answer(
        "📆 Kredit muddatini tanlang:",
        reply_markup=muddat_kb(terms),
    )


@router.callback_query(ScoringFSM.muddat, F.data.startswith("sc_term_"))
async def cb_muddat(call: CallbackQuery, state: FSMContext):
    try:
        term = int(call.data.split("_")[-1])
    except ValueError:
        return
    await state.update_data(muddat=term)
    await call.answer()

    data = await state.get_data()
    turi = data["kredit_turi"]
    await state.set_state(ScoringFSM.oylik_daromad)

    daromad_prompt = (
        "🏦 Mijozning oxirgi pensiya summasini kiriting (so'mda):"
        if turi == "pensiya" else
        "💼 Mijozning yillik daromadini kiriting (so'mda):"
    )
    await call.message.edit_text(
        f"\u2705 Muddat: <b>{term} oy</b>\n\n{daromad_prompt}",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )




@router.message(ScoringFSM.oylik_daromad)
async def get_daromad(message: Message, state: FSMContext):
    val = re.sub(r"\D", "", message.text or "")
    if not val:
        await message.answer("❗ Faqat raqam kiriting:", reply_markup=cancel_kb())
        return
    kiritilgan = float(val)
    if kiritilgan <= 0:
        await message.answer("❗ Daromad 0 dan katta bo'lishi kerak:", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    turi = data["kredit_turi"]

    if turi == "pensiya":
        oylik = kiritilgan  # Pensiyada to'g'ridan kiritiladi
    else:
        oylik = kiritilgan * 0.88 / 12

    await state.update_data(oylik_daromad=oylik, yillik_daromad=kiritilgan)
    await state.set_state(ScoringFSM.mavjud_tolovlar)
    await message.answer(
        f"✅ Oylik daromad: <b>{fmt(oylik)}</b> so'm\n\n"
        f"📋 Mavjud oylik kredit to'lovlarini kiriting (so'mda).\n"
        f"Agar yo'q bo'lsa — <b>0</b> kiriting:",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )


@router.message(ScoringFSM.mavjud_tolovlar)
async def get_mavjud_tolovlar(message: Message, state: FSMContext):
    val = re.sub(r"\D", "", message.text or "")
    if val == "":
        val = "0"
    mavjud = float(val)
    if mavjud < 0:
        await message.answer("❗ Manfiy son kiritib bo'lmaydi:", reply_markup=cancel_kb())
        return

    await state.update_data(mavjud_tolovlar=mavjud)
    data = await state.get_data()
    await state.clear()

    turi            = data["kredit_turi"]
    ish_joyi        = data.get("ish_joyi", "")
    kredit_summasi  = data["kredit_summasi"]
    oylik_daromad   = data["oylik_daromad"]
    yillik_daromad  = data.get("yillik_daromad", oylik_daromad)
    rate            = RATES[turi]

    muddat = data.get("muddat", min(TERMS[turi]))

    result = calculate_scoring(
        kredit_turi=turi,
        kredit_summasi=kredit_summasi,
        oylik_daromad=oylik_daromad,
        mavjud_tolovlar=mavjud,
        ish_joyi=ish_joyi,
        rate=rate,
        muddat=muddat,
    )

    load_pct   = result["load_pct"]
    limit_pct  = result["limit_pct"]
    ok         = result["ok"]
    max_loan   = result["max_loan"]
    ann_pay    = result["ann_payment_requested"]
    diff_pay   = result["diff_payment_requested"]

    # ── Sarlavha ──
    turi_nomi = {"pensiya": "✅ Pensiya", "ish_haqi": "💼 Ish haqi", "hamkor": "🤝 Hamkor"}[turi]
    if turi == "ish_haqi":
        ish_joyi_label = "Budjet" if ish_joyi == "budjet" else "Xususiy"
        turi_nomi += f" ({ish_joyi_label})"

    lines = [
        f"📊 <b>SCORING NATIJASI</b>",
        f"",
        f"👤 Kredit turi: {turi_nomi}",
        f"💰 So'ralgan summa: <b>{fmt(kredit_summasi)}</b> so'm",
    ]
    if turi == "pensiya":
        lines.append(f"🏦 Pensiya: <b>{fmt(oylik_daromad)}</b> so'm")
    else:
        lines.append(f"📈 Yillik daromad: <b>{fmt(yillik_daromad)}</b> so'm")
        lines.append(f"💵 Oylik daromad (×88%÷12): <b>{fmt(oylik_daromad)}</b> so'm")

    if mavjud > 0:
        lines.append(f"📋 Mavjud kredit to'lovlari: <b>{fmt(mavjud)}</b> so'm")

    lines += [
        f"",
        f"── Hisoblash ({muddat} oy) ──",
        f"📌 Annuitet oylik to'lov: <b>{fmt(ann_pay)}</b> so'm",
        f"📌 Differensial 1-oy to'lov: <b>{fmt(diff_pay)}</b> so'm",
        f"",
        f"📊 Qarz yuki: <b>{load_pct*100:.1f}%</b> (chegara: {limit_pct*100:.0f}%)",
        f"",
    ]

    # ── Qaror ──
    if ok:
        lines.append("✅ <b>KREDIT AJRATILISHI MUMKIN</b>")
    else:
        lines.append("❌ <b>KREDIT AJRATILISHI MUMKIN EMAS</b>")
        lines.append(f"⚠️ Qarz yuki {load_pct*100:.1f}% — chegara {limit_pct*100:.0f}% dan oshib ketdi")

    # ── Tanlangan muddat uchun holat ──
    lines += ["", "──────────────────────────", ""]
    icon   = "✅" if ok else "❌"
    status = "beriladi" if ok else "berilmaydi"
    lines.append(
        f"  {icon} <b>{muddat} oy — {status}</b> "
        f"(qarz yuki {load_pct*100:.1f}%)"
    )

    # ── Maksimal ajratilishi mumkin bo'lgan kredit ──
    lines += ["", "──────────────────────────", "📈 <b>Maksimal ajratilishi mumkin:</b>", ""]

    # Annuitet jadval
    lines.append("🔵 <b>Annuitet:</b>")
    for t, v in max_loan.items():
        ann_max = int(v["ann"] // 100_000) * 100_000
        if ann_max > 0:
            lines.append(f"  {t} oy → <b>{fmt100k(v['ann'])}</b> so'm")
        else:
            lines.append(f"  {t} oy → ajratilmaydi")

    lines.append("")
    # Differensial jadval
    lines.append("🟢 <b>Differensial:</b>")
    for t, v in max_loan.items():
        diff_max = int(v["diff"] // 100_000) * 100_000
        if diff_max > 0:
            lines.append(f"  {t} oy → <b>{fmt100k(v['diff'])}</b> so'm")
        else:
            lines.append(f"  {t} oy → ajratilmaydi")

    ortga_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangi hisoblash", callback_data="sc_restart")],
    ])
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=ortga_kb)


# ===================== CANCEL / RESTART =====================

@router.callback_query(F.data == "sc_cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ Scoring bekor qilindi.")


@router.callback_query(F.data == "sc_restart")
async def cb_restart(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        "🧮 <b>Scoring — Qarz yuki hisoblash</b>\n\nKredit turini tanlang:",
        reply_markup=kredit_turi_kb(),
        parse_mode="HTML",
    )
    await state.set_state(ScoringFSM.kredit_turi)





# """
# Scoring — qarz yuki hisoblash (faqat sub_adminlar uchun)
# """
# from __future__ import annotations

# import os
# import re
# import base64
# import json
# import asyncio
# import logging

# import gspread
# from google.oauth2.service_account import Credentials
# from aiogram import Router, F, Bot
# from aiogram.filters import Command
# from aiogram.fsm.context import FSMContext
# from aiogram.fsm.state import State, StatesGroup
# from aiogram.types import (
#     Message,
#     InlineKeyboardMarkup,
#     InlineKeyboardButton,
#     CallbackQuery,
# )

# logger = logging.getLogger(__name__)
# router = Router()

# SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
# SUBADMIN_SHEET = "sub_adminlar"
# SCOPES = [
#     "https://www.googleapis.com/auth/spreadsheets.readonly",
#     "https://www.googleapis.com/auth/drive.readonly",
# ]

# _gc: gspread.Client | None = None


# # ===================== RUXSAT TEKSHIRUV =====================

# def _get_gc() -> gspread.Client:
#     global _gc
#     if _gc is None:
#         b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
#         info  = json.loads(base64.b64decode(b64).decode())
#         creds = Credentials.from_service_account_info(info, scopes=SCOPES)
#         _gc   = gspread.authorize(creds)
#     return _gc


# def _is_subadmin_sync(user_id: int) -> bool:
#     try:
#         gc = _get_gc()
#         ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SUBADMIN_SHEET)
#         ids = ws.col_values(2)[1:]
#         return str(user_id) in [str(v).strip() for v in ids]
#     except Exception as e:
#         logger.error(f"Sub-admin tekshirishda xato: {e}")
#         return False


# async def is_subadmin(user_id: int) -> bool:
#     loop = asyncio.get_running_loop()
#     return await loop.run_in_executor(None, _is_subadmin_sync, user_id)


# # ===================== KREDIT KONFIGURATSIYASI =====================

# # Foiz stavkalari (yillik annuitet hisoblash uchun)
# RATES = {
#     "pensiya":  49,
#     "ish_haqi": 49,
#     "hamkor":   56,
# }

# # Kredit muddatlari (oy)
# TERMS = {
#     "pensiya":  [12, 18, 24],
#     "ish_haqi": [12, 18, 24, 30, 36],
#     "hamkor":   [12],
# }

# # Qarz yuki chegaralari
# def get_limit(kredit_turi: str, kredit_summasi: float, ish_joyi: str = "") -> float:
#     """Qarz yuki chegarasi — kredit SUMMASI asosida (0.0 - 1.0)"""
#     if kredit_turi == "pensiya":
#         return 0.50
#     elif kredit_turi == "hamkor":
#         return 0.50
#     elif kredit_turi == "ish_haqi":
#         if ish_joyi == "budjet":
#             # summa <= 20M → 75%, 20M < summa <= 40M → 50%
#             return 0.75 if kredit_summasi <= 20_000_000 else 0.50
#         else:  # xususiy
#             # summa <= 10M → 75%, 10M < summa <= 20M → 50%
#             return 0.75 if kredit_summasi <= 10_000_000 else 0.50
#     return 0.75


# LIMIT_TEXT = {
#     "pensiya": (
#         "📌 <b>Pensiya krediti — qarz yuki chegarasi:</b>\n"
#         "• Qarz yuki <b>50%</b> dan oshmasligi kerak\n"
#         "• Oylik daromad sifatida oxirgi pensiya summasi kiritiladi"
#     ),
#     "ish_haqi": (
#         "📌 <b>Ish haqi krediti — qarz yuki chegarasi:</b>\n"
#         "• Budjet tashkiloti xodimlari:\n"
#         "  – Kredit summasi ≤20M → <b>75%</b>\n"
#         "  – Kredit summasi 20M–40M → <b>50%</b>\n"
#         "• Xususiy tashkilot xodimlari:\n"
#         "  – Kredit summasi ≤10M → <b>75%</b>\n"
#         "  – Kredit summasi 10M–20M → <b>50%</b>\n"
#         "• Xususiy uchun maksimal kredit: 20 000 000 so'm\n"
#     ),
#     "hamkor": (
#         "📌 <b>Hamkor krediti — qarz yuki chegarasi:</b>\n"
#         "• Qarz yuki <b>50%</b> dan oshmasligi kerak\n"
#         "• Muddat: faqat 12 oy"
#     ),
# }


# # ===================== HISOBLASH FUNKSIYALARI =====================

# def ann_payment(principal: float, rate_annual: float, months: int) -> float:
#     """Annuitet oylik to'lov"""
#     r = rate_annual / 12 / 100
#     if r == 0:
#         return principal / months
#     return principal * r / (1 - (1 + r) ** -months)


# def diff_max_payment(principal: float, rate_annual: float, months: int) -> float:
#     """Differensial — birinchi (eng katta) oylik to'lov"""
#     r         = rate_annual / 12 / 100
#     principal_part = principal / months
#     interest  = principal * r
#     return principal_part + interest


# def max_loan_from_payment(max_payment: float, rate_annual: float, months: int) -> float:
#     """Berilgan oylik to'lovdan maksimal kredit summasini hisoblaydi (annuitet)"""
#     r = rate_annual / 12 / 100
#     if r == 0:
#         return max_payment * months
#     return max_payment * (1 - (1 + r) ** -months) / r


# def max_loan_diff(max_payment: float, rate_annual: float, months: int) -> float:
#     """Differensial uchun maksimal kredit summasi (birinchi oydan hisoblaydi)"""
#     r = rate_annual / 12 / 100
#     # max_payment = P/m + P*r  =>  P = max_payment / (1/m + r)
#     denom = 1 / months + r
#     if denom == 0:
#         return 0
#     return max_payment / denom


# fmt     = lambda n: f"{round(n):,}".replace(",", " ")
# fmt100k = lambda n: f"{int(n // 100_000) * 100_000:,}".replace(",", " ")


# def calculate_scoring(
#     kredit_turi: str,
#     kredit_summasi: float,
#     oylik_daromad: float,
#     mavjud_tolovlar: float,
#     ish_joyi: str,
#     rate: float,
# ) -> dict:
#     """
#     Scoring hisoblaydi.
#     Qaytaradi: {
#         load_pct: float,           # hisoblangan qarz yuki %
#         limit_pct: float,          # belgilangan chegara %
#         ok: bool,                  # kredit ajratilishi mumkinmi
#         max_loan: dict,            # {term: {ann: float, diff: float}}
#         ann_payment_requested: float,  # so'ralgan summa uchun annuitet to'lov
#         diff_payment_requested: float, # so'ralgan summa uchun diff to'lov
#     }
#     """
#     terms    = TERMS[kredit_turi]
#     min_term = min(terms)
#     limit    = get_limit(kredit_turi, kredit_summasi, ish_joyi)

#     # So'ralgan kredit eng qisqa muddatdagi oylik to'lovi
#     ann_pay  = ann_payment(kredit_summasi, rate, min_term)
#     diff_pay = diff_max_payment(kredit_summasi, rate, min_term)

#     # Qarz yuki (annuitet asosida, konservativ)
#     load_pct = (ann_pay + mavjud_tolovlar) / oylik_daromad if oylik_daromad > 0 else 1.0

#     # Kredit turi uchun maksimal ruxsat etilgan summa
#     max_caps = {
#         "pensiya":  30_000_000,
#         "hamkor":   20_000_000,
#         "ish_haqi": 20_000_000 if ish_joyi == "xususiy" else 40_000_000,
#     }
#     max_cap = max_caps.get(kredit_turi, 40_000_000)

#     # Maksimal ajratilishi mumkin bo'lgan kredit
#     max_loan = {}
#     for t in terms:
#         free_payment = oylik_daromad * limit - mavjud_tolovlar
#         if free_payment <= 0:
#             max_loan[t] = {"ann": 0, "diff": 0}
#         else:
#             ann_max  = min(max_loan_from_payment(free_payment, rate, t), max_cap)
#             diff_max = min(max_loan_diff(free_payment, rate, t), max_cap)
#             max_loan[t] = {"ann": ann_max, "diff": diff_max}

#     return {
#         "load_pct":               load_pct,
#         "limit_pct":              limit,
#         "ok":                     load_pct <= limit,
#         "max_loan":               max_loan,
#         "ann_payment_requested":  ann_pay,
#         "diff_payment_requested": diff_pay,
#     }


# # ===================== FSM =====================

# class ScoringFSM(StatesGroup):
#     kredit_turi      = State()
#     ish_joyi         = State()   # faqat ish_haqi uchun
#     kredit_summasi   = State()
#     oylik_daromad    = State()
#     mavjud_tolovlar  = State()


# # ===================== KLAVIATURALAR =====================

# def kredit_turi_kb() -> InlineKeyboardMarkup:
#     return InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="✅ Pensiya",  callback_data="sc_pensiya")],
#         [InlineKeyboardButton(text="💼 Ish haqi", callback_data="sc_ish_haqi")],
#         [InlineKeyboardButton(text="🤝 Hamkor",   callback_data="sc_hamkor")],
#         [InlineKeyboardButton(text="❌ Bekor",    callback_data="sc_cancel")],
#     ])


# def ish_joyi_kb() -> InlineKeyboardMarkup:
#     return InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="🏛 Budjet tashkiloti",   callback_data="sc_budjet")],
#         [InlineKeyboardButton(text="🏢 Xususiy tashkilot",   callback_data="sc_xususiy")],
#         [InlineKeyboardButton(text="❌ Bekor",               callback_data="sc_cancel")],
#     ])


# def cancel_kb() -> InlineKeyboardMarkup:
#     return InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sc_cancel")]
#     ])


# # ===================== HANDLERLAR =====================

# def _has_scoring_access(user_id: int) -> bool:
#     """ADMIN_ID, JOB_ID yoki sub_admin bo'lsa ruxsat"""
#     admin_id = int(os.getenv("ADMIN_ID", "0"))
#     job_id   = int(os.getenv("JOB_ID", "0"))
#     return user_id in (admin_id, job_id)


# @router.message(Command("scoring"))
# async def cmd_scoring(message: Message, state: FSMContext):
#     uid = message.from_user.id
#     if not (_has_scoring_access(uid) or await is_subadmin(uid)):
#         await message.answer("⛔ Bu buyruq faqat xodimlar uchun.")
#         return
#     await state.clear()
#     await state.set_state(ScoringFSM.kredit_turi)
#     await message.answer(
#         "🧮 <b>Scoring — Qarz yuki hisoblash</b>\n\nKredit turini tanlang:",
#         reply_markup=kredit_turi_kb(),
#         parse_mode="HTML",
#     )


# @router.callback_query(ScoringFSM.kredit_turi, F.data.startswith("sc_"))
# async def cb_kredit_turi(call: CallbackQuery, state: FSMContext):
#     data = call.data
#     if data == "sc_cancel":
#         await state.clear()
#         await call.message.edit_text("❌ Scoring bekor qilindi.")
#         return

#     turi_map = {"sc_pensiya": "pensiya", "sc_ish_haqi": "ish_haqi", "sc_hamkor": "hamkor"}
#     turi = turi_map.get(data)
#     if not turi:
#         return

#     await state.update_data(kredit_turi=turi, ish_joyi="")
#     await call.answer()

#     # Izoh ko'rsatamiz
#     izoh = LIMIT_TEXT[turi]
#     await call.message.edit_text(izoh, parse_mode="HTML")

#     if turi == "ish_haqi":
#         await state.set_state(ScoringFSM.ish_joyi)
#         await call.message.answer(
#             "🏢 Ish joyi turini tanlang:",
#             reply_markup=ish_joyi_kb(),
#         )
#     else:
#         min_s = 3_000_000
#         max_s = {"pensiya": 30_000_000, "hamkor": 20_000_000}.get(turi, 50_000_000)
#         await state.update_data(min_summa=min_s, max_summa=max_s)
#         await state.set_state(ScoringFSM.kredit_summasi)
#         await call.message.answer(
#             f"💰 Mijoz olmoqchi bo'lgan kredit summasini kiriting (so'mda):\n"
#             f"📌 Minimal: <b>{fmt(min_s)}</b> | Maksimal: <b>{fmt(max_s)}</b>",
#             reply_markup=cancel_kb(),
#             parse_mode="HTML",
#         )


# @router.callback_query(ScoringFSM.ish_joyi, F.data.startswith("sc_"))
# async def cb_ish_joyi(call: CallbackQuery, state: FSMContext):
#     if call.data == "sc_cancel":
#         await state.clear()
#         await call.message.edit_text("❌ Scoring bekor qilindi.")
#         return

#     ish_joyi_map = {"sc_budjet": "budjet", "sc_xususiy": "xususiy"}
#     ish_joyi = ish_joyi_map.get(call.data)
#     if not ish_joyi:
#         return

#     await state.update_data(ish_joyi=ish_joyi)
#     await call.answer()
#     await state.set_state(ScoringFSM.kredit_summasi)
#     min_s, max_s = 3_000_000, 40_000_000
#     await state.update_data(min_summa=min_s, max_summa=max_s)
#     await call.message.edit_text(
#         f"💰 Mijoz olmoqchi bo'lgan kredit summasini kiriting (so'mda):\n"
#         f"📌 Minimal: <b>{fmt(min_s)}</b> | Maksimal: <b>{fmt(max_s)}</b>",
#         reply_markup=cancel_kb(),
#         parse_mode="HTML",
#     )


# @router.message(ScoringFSM.kredit_summasi)
# async def get_kredit_summasi(message: Message, state: FSMContext):
#     val = re.sub(r"\D", "", message.text or "")
#     if not val:
#         await message.answer("❗ Faqat raqam kiriting:", reply_markup=cancel_kb())
#         return
#     summa = float(val)
#     data_check = await state.get_data()
#     min_s = data_check.get("min_summa", 3_000_000)
#     max_s = data_check.get("max_summa", 300_000_000)
#     if summa < min_s:
#         await message.answer(
#             f"❗ Minimal kredit summasi: <b>{fmt(min_s)}</b> so'm",
#             reply_markup=cancel_kb(), parse_mode="HTML"
#         )
#         return
#     if summa > max_s:
#         await message.answer(
#             f"❗ Maksimal kredit summasi: <b>{fmt(max_s)}</b> so'm",
#             reply_markup=cancel_kb(), parse_mode="HTML"
#         )
#         return
#     await state.update_data(kredit_summasi=summa)

#     data = await state.get_data()
#     turi = data["kredit_turi"]
#     await state.set_state(ScoringFSM.oylik_daromad)

#     if turi == "pensiya":
#         await message.answer(
#             "🏦 Mijozning oxirgi pensiya summasini kiriting (so'mda):",
#             reply_markup=cancel_kb(),
#         )
#     else:
#         await message.answer(
#             "💼 Mijozning yillik daromadini kiriting (so'mda):\n",
#             reply_markup=cancel_kb(),
#             parse_mode="HTML",
#         )


# @router.message(ScoringFSM.oylik_daromad)
# async def get_daromad(message: Message, state: FSMContext):
#     val = re.sub(r"\D", "", message.text or "")
#     if not val:
#         await message.answer("❗ Faqat raqam kiriting:", reply_markup=cancel_kb())
#         return
#     kiritilgan = float(val)
#     if kiritilgan <= 0:
#         await message.answer("❗ Daromad 0 dan katta bo'lishi kerak:", reply_markup=cancel_kb())
#         return

#     data = await state.get_data()
#     turi = data["kredit_turi"]

#     if turi == "pensiya":
#         oylik = kiritilgan  # Pensiyada to'g'ridan kiritiladi
#     else:
#         oylik = kiritilgan * 0.88 / 12

#     await state.update_data(oylik_daromad=oylik, yillik_daromad=kiritilgan)
#     await state.set_state(ScoringFSM.mavjud_tolovlar)
#     await message.answer(
#         f"✅ Oylik daromad: <b>{fmt(oylik)}</b> so'm\n\n"
#         f"📋 Mavjud oylik kredit to'lovlarini kiriting (so'mda).\n"
#         f"Agar yo'q bo'lsa — <b>0</b> kiriting:",
#         reply_markup=cancel_kb(),
#         parse_mode="HTML",
#     )


# @router.message(ScoringFSM.mavjud_tolovlar)
# async def get_mavjud_tolovlar(message: Message, state: FSMContext):
#     val = re.sub(r"\D", "", message.text or "")
#     if val == "":
#         val = "0"
#     mavjud = float(val)
#     if mavjud < 0:
#         await message.answer("❗ Manfiy son kiritib bo'lmaydi:", reply_markup=cancel_kb())
#         return

#     await state.update_data(mavjud_tolovlar=mavjud)
#     data = await state.get_data()
#     await state.clear()

#     turi            = data["kredit_turi"]
#     ish_joyi        = data.get("ish_joyi", "")
#     kredit_summasi  = data["kredit_summasi"]
#     oylik_daromad   = data["oylik_daromad"]
#     yillik_daromad  = data.get("yillik_daromad", oylik_daromad)
#     rate            = RATES[turi]

#     result = calculate_scoring(
#         kredit_turi=turi,
#         kredit_summasi=kredit_summasi,
#         oylik_daromad=oylik_daromad,
#         mavjud_tolovlar=mavjud,
#         ish_joyi=ish_joyi,
#         rate=rate,
#     )

#     load_pct   = result["load_pct"]
#     limit_pct  = result["limit_pct"]
#     ok         = result["ok"]
#     max_loan   = result["max_loan"]
#     ann_pay    = result["ann_payment_requested"]
#     diff_pay   = result["diff_payment_requested"]

#     # ── Sarlavha ──
#     turi_nomi = {"pensiya": "✅ Pensiya", "ish_haqi": "💼 Ish haqi", "hamkor": "🤝 Hamkor"}[turi]
#     if turi == "ish_haqi":
#         ish_joyi_label = "Budjet" if ish_joyi == "budjet" else "Xususiy"
#         turi_nomi += f" ({ish_joyi_label})"

#     lines = [
#         f"📊 <b>SCORING NATIJASI</b>",
#         f"",
#         f"👤 Kredit turi: {turi_nomi}",
#         f"💰 So'ralgan summa: <b>{fmt(kredit_summasi)}</b> so'm",
#     ]
#     if turi == "pensiya":
#         lines.append(f"🏦 Pensiya: <b>{fmt(oylik_daromad)}</b> so'm")
#     else:
#         lines.append(f"📈 Yillik daromad: <b>{fmt(yillik_daromad)}</b> so'm")
#         lines.append(f"💵 Oylik daromad: <b>{fmt(oylik_daromad)}</b> so'm")

#     if mavjud > 0:
#         lines.append(f"📋 Mavjud kredit to'lovlari: <b>{fmt(mavjud)}</b> so'm")

#     lines += [
#         f"",
#         f"── Hisoblash ({min(TERMS[turi])} oy, eng qisqa muddat) ──",
#         f"📌 Annuitet oylik to'lov: <b>{fmt(ann_pay)}</b> so'm",
#         f"📌 Differensial 1-oy to'lov: <b>{fmt(diff_pay)}</b> so'm",
#         f"",
#         f"📊 Qarz yuki: <b>{load_pct*100:.1f}%</b> (chegara: {limit_pct*100:.0f}%)",
#         f"",
#     ]

#     # ── Qaror ──
#     if ok:
#         lines.append("✅ <b>KREDIT AJRATILISHI MUMKIN</b>")
#     else:
#         lines.append("❌ <b>KREDIT AJRATILISHI MUMKIN EMAS</b>")
#         lines.append(f"⚠️ Qarz yuki {load_pct*100:.1f}% — chegara {limit_pct*100:.0f}% dan oshib ketdi")

#     # ── Har bir muddat uchun beriladi/berilmaydi ──
#     lines += ["", "──────────────────────────",
#               "📋 <b>Muddatlar bo'yicha holat (so'ralgan summa):</b>", ""]
#     for t in TERMS[turi]:
#         ann_pay_t  = ann_payment(kredit_summasi, rate, t)
#         load_t     = (ann_pay_t + mavjud) / oylik_daromad if oylik_daromad > 0 else 1.0
#         if load_t <= limit_pct:
#             lines.append(f"  ✅ {t} oy — beriladi "
#                          f"(qarz yuki {load_t*100:.1f}%)")
#         else:
#             lines.append(f"  ❌ {t} oy — berilmaydi "
#                          f"(qarz yuki {load_t*100:.1f}% > {limit_pct*100:.0f}%)")

#     # ── Maksimal ajratilishi mumkin bo'lgan kredit ──
#     lines += ["", "──────────────────────────", "📈 <b>Maksimal ajratilishi mumkin:</b>", ""]

#     # Annuitet jadval
#     lines.append("🔵 <b>Annuitet:</b>")
#     for t, v in max_loan.items():
#         ann_max = int(v["ann"] // 100_000) * 100_000
#         if ann_max > 0:
#             lines.append(f"  {t} oy → <b>{fmt100k(v['ann'])}</b> so'm")
#         else:
#             lines.append(f"  {t} oy → ajratilmaydi")

#     lines.append("")
#     # Differensial jadval
#     lines.append("🟢 <b>Differensial:</b>")
#     for t, v in max_loan.items():
#         diff_max = int(v["diff"] // 100_000) * 100_000
#         if diff_max > 0:
#             lines.append(f"  {t} oy → <b>{fmt100k(v['diff'])}</b> so'm")
#         else:
#             lines.append(f"  {t} oy → ajratilmaydi")

#     ortga_kb = InlineKeyboardMarkup(inline_keyboard=[
#         [InlineKeyboardButton(text="🔄 Yangi hisoblash", callback_data="sc_restart")],
#     ])
#     await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=ortga_kb)


# # ===================== CANCEL / RESTART =====================

# @router.callback_query(F.data == "sc_cancel")
# async def cb_cancel(call: CallbackQuery, state: FSMContext):
#     await state.clear()
#     await call.answer()
#     await call.message.edit_text("❌ Scoring bekor qilindi.")


# @router.callback_query(F.data == "sc_restart")
# async def cb_restart(call: CallbackQuery, state: FSMContext):
#     await state.clear()
#     await call.answer()
#     await call.message.edit_reply_markup(reply_markup=None)
#     await call.message.answer(
#         "🧮 <b>Scoring — Qarz yuki hisoblash</b>\n\nKredit turini tanlang:",
#         reply_markup=kredit_turi_kb(),
#         parse_mode="HTML",
#     )
#     await state.set_state(ScoringFSM.kredit_turi)
