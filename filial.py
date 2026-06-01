from __future__ import annotations

import os
import re
import base64
import json
import logging
import asyncio
import contextlib
import aiohttp
import gspread
from math import radians, sin, cos, sqrt, atan2
from google.oauth2.service_account import Credentials

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command
from config import load_config

logger = logging.getLogger(__name__)
router = Router()

# ── Config ─────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SHEET_NAME     = "malumotlar"
CALL_CENTER    = "+998 55 808 40 00"

COL = {
    "id":          "T/r",
    "viloyat":     "Viloyat",
    "tuman":       "Tuman yoki shashar",
    "manzil":      "Manzil",
    "filial":      "Filial",
    "boshliq":     "Filial Boshqaruvchisi",
    "shaxsiy_tel": "Boshqaruvchi (shaxsiy) raqami",
    "filial_tel":  "Boshqaruvchi (filial) raqami",
    "qabulxona":   "Qabulxona",
    "kredit":      "Kredit bo'limi",
    "unduruv":     "Unduruv bo'limi",
    "buxgalteriya":"Buxgalteriya",
    "lokatsiya":   "Lokatsiya",
    "ichki":       "Ichki nomer",
    "masul":       "Biriktirilgan masul xodim",
    "location":    "Location",
}

_gc: gspread.Client | None = None
_coords_cache: dict[str, tuple[float, float]] = {}
# Barcha filiallar keshi — bir sessiyada bir marta yuklanadi
_branches_cache: list[dict] | None = None


# ── Sheets ─────────────────────────────────────────────────────
def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


async def get_all_branches(force: bool = False) -> list[dict]:
    global _branches_cache
    if _branches_cache is not None and not force:
        return _branches_cache
    try:
        loop = asyncio.get_running_loop()
        def _fetch():
            gc = _get_gc()
            ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            return ws.get_all_records()
        records = await loop.run_in_executor(None, _fetch)
        _branches_cache = [r for r in records if r.get(COL["filial"])]
        return _branches_cache
    except Exception as e:
        logger.error(f"Branches fetch xato: {e}")
        return _branches_cache or []


def _is_admin(user_id: int) -> bool:
    try:
        return user_id == load_config().my_id
    except Exception:
        return False


# ── Koordinata ─────────────────────────────────────────────────
def _parse_coords(url: str) -> tuple[float, float] | None:
    patterns = [
        r"!3d(-?\d+\.?\d+)!4d(-?\d+\.?\d+)",
        r"[?&]q=(-?\d+\.?\d+),(-?\d+\.?\d+)",
        r"/place/[^@]+@(-?\d+\.?\d+),(-?\d+\.?\d+)",
        r"@(-?\d+\.?\d+),(-?\d+\.?\d+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


async def resolve_coords(url: str) -> tuple[float, float] | None:
    if not url:
        return None
    if url in _coords_cache:
        return _coords_cache[url]
    coords = _parse_coords(url)
    if coords:
        _coords_cache[url] = coords
        return coords
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, allow_redirects=True,
                             timeout=aiohttp.ClientTimeout(total=15),
                             headers=headers) as resp:
                final_url = str(resp.url)
                body      = await resp.text(errors="ignore")
        coords = _parse_coords(final_url) or _parse_coords(body)
        if coords:
            _coords_cache[url] = coords
            return coords
    except Exception as e:
        logger.warning(f"Koordinata xato ({url[:60]}): {e}")
    return None


def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    d = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d[0]/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(d[1]/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ── Yordamchi ──────────────────────────────────────────────────
def _g(b: dict, key: str) -> str:
    return str(b.get(COL[key], "") or "").strip()


def _maps_url(b: dict) -> str:
    full = _g(b, "location")
    return full if full else _g(b, "lokatsiya")


# ── Matn ───────────────────────────────────────────────────────
def _user_text(b: dict) -> str:
    url   = _maps_url(b)
    ichki = _g(b, "ichki")
    lines = [f"🏢 <b>{_g(b, 'filial')}</b>", ""]
    lines.append(f"📍 Manzil: {_g(b, 'manzil')}")
    for label, key in [
        ("📞 Qabulxona",      "qabulxona"),
        ("💳 Kredit bo'limi", "kredit"),
        ("📤 Unduruv",        "unduruv"),
        ("📊 Buxgalteriya",   "buxgalteriya"),
    ]:
        v = _g(b, key)
        if v:
            lines.append(f"{label}: {v}")
    lines.append("")
    lines.append(f"📲 Call center: <b>{CALL_CENTER}</b>")
    if ichki:
        lines.append(f"🔢 Ichki nomer: <b>{ichki}</b>")
        lines.append(f"<i>(Qo'ng'iroq qiling va <b>{ichki}</b> ni tering)</i>")
    if url:
        lines.append(f"\n🗺 <a href='{url}'>Google Maps</a>")
    return "\n".join(lines)


def _admin_text(b: dict) -> str:
    url   = _maps_url(b)
    ichki = _g(b, "ichki")
    lines = [
        f"🏢 <b>{_g(b, 'filial')}</b>", "",
        f"🏙 Viloyat: {_g(b, 'viloyat')}",
        f"🏘 Tuman: {_g(b, 'tuman')}",
        f"📍 Manzil: {_g(b, 'manzil')}", "",
        f"👤 Boshqaruvchi: {_g(b, 'boshliq')}",
        f"📱 Shaxsiy: {_g(b, 'shaxsiy_tel')}",
        f"☎️ Filial tel: {_g(b, 'filial_tel')}", "",
        f"📞 Qabulxona: {_g(b, 'qabulxona')}",
        f"💳 Kredit bo'limi: {_g(b, 'kredit')}",
        f"📤 Unduruv: {_g(b, 'unduruv')}",
        f"📊 Buxgalteriya: {_g(b, 'buxgalteriya')}",
    ]
    if ichki:
        lines.append(f"🔢 Ichki nomer: {ichki}")
    lines.append(f"👷 Masul xodim: {_g(b, 'masul')}")
    lines.append(f"📲 Call center: {CALL_CENTER}")
    if url:
        lines.append(f"\n🗺 <a href='{url}'>Google Maps</a>")
    return "\n".join(lines)


# ── Klaviaturalar ───────────────────────────────────────────────
def _branches_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Barcha filiallar", callback_data="list_branches"),
            InlineKeyboardButton(text="📍 Eng yaqin filial",  callback_data="find_nearest"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_menu")],
    ])


def _regions_kb(branches: list[dict]) -> InlineKeyboardMarkup:
    regions = sorted(set(_g(b, "viloyat") for b in branches if _g(b, "viloyat")))
    rows = []
    for i in range(0, len(regions), 2):
        row = [InlineKeyboardButton(text=regions[i], callback_data=f"reg_{regions[i]}")]
        if i + 1 < len(regions):
            row.append(InlineKeyboardButton(
                text=regions[i + 1], callback_data=f"reg_{regions[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _filials_kb(branches: list[dict], region: str) -> InlineKeyboardMarkup:
    """branches ro'yxatidagi INDEX ni callback da ishlatadi — T/r ga bog'liq emas."""
    filtered = [(i, b) for i, b in enumerate(branches) if _g(b, "viloyat") == region]
    rows = []
    for j in range(0, len(filtered), 2):
        idx0, b0 = filtered[j]
        row = [InlineKeyboardButton(text=_g(b0, "filial"), callback_data=f"fil_{idx0}")]
        if j + 1 < len(filtered):
            idx1, b1 = filtered[j + 1]
            row.append(InlineKeyboardButton(text=_g(b1, "filial"), callback_data=f"fil_{idx1}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="list_branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyamni yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _nearest_kb(results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for r in results:
        label = f"{_g(r, 'filial')} — {r['_dist']:.1f} km"
        idx   = r["_idx"]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"fil_{idx}")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Handlerlar ──────────────────────────────────────────────────
@router.callback_query(F.data == "branches")
async def cb_branches(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    text = "📍 <b>Filiallar</b>\n\nQuyidagilardan birini tanlang:"
    try:
        await call.message.edit_text(
            text, reply_markup=_branches_main_kb(), parse_mode="HTML")
    except Exception:
        with contextlib.suppress(Exception):
            await call.message.delete()
        await call.message.answer(
            text, reply_markup=_branches_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "list_branches")
async def cb_list_branches(call: CallbackQuery):
    branches = await get_all_branches()
    if not branches:
        await call.answer("❌ Ma'lumot topilmadi", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(
        f"🏙 <b>Viloyatni tanlang:</b>\n({len(branches)} ta filial)",
        reply_markup=_regions_kb(branches), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("reg_"))
async def cb_region(call: CallbackQuery):
    region   = call.data[4:]
    branches = await get_all_branches()
    filtered = [b for b in branches if _g(b, "viloyat") == region]
    if not filtered:
        await call.answer("❌ Bu viloyatda filial topilmadi", show_alert=True)
        return
    await call.answer()
    try:
        await call.message.edit_text(
            f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\nFilialni tanlang:",
            reply_markup=_filials_kb(branches, region), parse_mode="HTML",
        )
    except Exception:
        await call.message.answer(
            f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\nFilialni tanlang:",
            reply_markup=_filials_kb(branches, region), parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("fil_"))
async def cb_filial_detail(call: CallbackQuery, bot: Bot, state: FSMContext):
    # callback data: "fil_{idx}" yoki "fil_{idx}_{del_ids}"
    raw = call.data[4:]

    try:
        idx = int(raw)
    except ValueError:
        await call.answer("❌ Xato", show_alert=True)
        return

    branches = await get_all_branches()
    if idx < 0 or idx >= len(branches):
        await call.answer("❌ Filial topilmadi", show_alert=True)
        return

    b = branches[idx]
    await call.answer()

    uid    = call.from_user.id
    region = _g(b, "viloyat")
    url    = _maps_url(b)
    coords = await resolve_coords(url) if url else None
    text   = _admin_text(b) if _is_admin(uid) else _user_text(b)

    # Ortga callback: oldingi xabarlarni o'chirish uchun IDs saqlash
    # format: filback_{region}_{loc_id}_{text_id}
    # oldin yuborilgan xabarlarni o'chirib tashlaymiz (agar FSM da saqlangan bo'lsa)
    prev = await state.get_data()
    for mid in prev.get("filial_msg_ids", []):
        with contextlib.suppress(Exception):
            await bot.delete_message(uid, mid)

    # 1. Avval asosiy xabarni o'chirib, lokatsiya + matn yuboramiz
    with contextlib.suppress(Exception):
        await call.message.delete()

    msg_ids = []

    # 2. Lokatsiya
    if coords:
        loc_msg = await bot.send_location(uid, latitude=coords[0], longitude=coords[1])
        msg_ids.append(loc_msg.message_id)

    # 3. Matn + Ortga tugmasi
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"filback_{region}")]
    ])
    txt_msg = await bot.send_message(
        uid, text, reply_markup=back_kb,
        parse_mode="HTML", disable_web_page_preview=True,
    )
    msg_ids.append(txt_msg.message_id)

    # FSM da saqlash — "Ortga" bosilganda o'chirish uchun
    await state.update_data(filial_msg_ids=msg_ids, filial_region=region)


@router.callback_query(F.data.startswith("filback_"))
async def cb_filial_back(call: CallbackQuery, bot: Bot, state: FSMContext):
    """Filial ma'lumotlarini yopib, viloyat ro'yxatiga qaytaradi."""
    await call.answer()

    uid  = call.from_user.id
    data = await state.get_data()

    # Oldingi xabarlarni o'chiramiz
    for mid in data.get("filial_msg_ids", []):
        with contextlib.suppress(Exception):
            await bot.delete_message(uid, mid)

    # call.message ni ham o'chiramiz
    with contextlib.suppress(Exception):
        await call.message.delete()

    await state.update_data(filial_msg_ids=[], filial_region="")

    # Viloyat ro'yxatini qayta ko'rsatamiz
    region   = call.data[8:]   # "filback_{region}"
    branches = await get_all_branches()
    filtered = [b for b in branches if _g(b, "viloyat") == region]

    if not filtered:
        await bot.send_message(
            uid, "📍 <b>Filiallar</b>",
            reply_markup=_branches_main_kb(), parse_mode="HTML",
        )
        return

    await bot.send_message(
        uid,
        f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\nFilialni tanlang:",
        reply_markup=_filials_kb(branches, region), parse_mode="HTML",
    )


# ── Eng yaqin filial ────────────────────────────────────────────
class FilialFSM(StatesGroup):
    waiting_location = State()


@router.callback_query(F.data == "find_nearest")
async def cb_find_nearest(call: CallbackQuery, state: FSMContext):
    await state.set_state(FilialFSM.waiting_location)
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_text(
            "📍 <b>Eng yaqin filialni topish</b>\n\nLokatsiyangizni yuboring:",
            parse_mode="HTML",
        )
    await call.message.answer("Quyidagi tugmani bosing 👇", reply_markup=_location_kb())


@router.message(FilialFSM.waiting_location, F.text == "❌ Bekor qilish")
async def cancel_location(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await message.answer("📍 <b>Filiallar</b>",
                         reply_markup=_branches_main_kb(), parse_mode="HTML")


@router.message(FilialFSM.waiting_location, F.location)
async def process_location(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔍 Qidirilmoqda...", reply_markup=ReplyKeyboardRemove())

    user_lat = message.location.latitude
    user_lng = message.location.longitude
    branches = await get_all_branches()

    async def _with_dist(idx: int, b: dict) -> dict | None:
        url    = _maps_url(b)
        coords = await resolve_coords(url) if url else None
        if not coords:
            return None
        return {**b, "_dist": _haversine(user_lat, user_lng, coords[0], coords[1]),
                "_idx": idx}

    results = await asyncio.gather(*[_with_dist(i, b) for i, b in enumerate(branches)])
    valid   = sorted([r for r in results if r], key=lambda x: x["_dist"])[:3]

    if not valid:
        await message.answer(
            "❌ Filiallar koordinatasi aniqlanmadi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")]
            ])
        )
        return

    await message.answer(
        "✅ <b>Eng yaqin 3 ta filial:</b>",
        reply_markup=_nearest_kb(valid), parse_mode="HTML",
    )


# ── Admin buyruqlari ────────────────────────────────────────────
@router.message(Command("filiallar"))
async def cmd_filiallar(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Bu buyruq faqat admin uchun")
        return
    await state.clear()
    branches = await get_all_branches()
    await message.answer(
        f"📡 <b>Filiallar</b> ({len(branches)} ta)",
        reply_markup=_branches_main_kb(), parse_mode="HTML",
    )


@router.message(Command("refresh_branches"))
async def cmd_refresh(message: Message):
    if not _is_admin(message.from_user.id):
        return
    global _gc, _coords_cache, _branches_cache
    _gc = None
    _coords_cache = {}
    _branches_cache = None
    branches = await get_all_branches(force=True)
    await message.answer(
        f"✅ Yangilandi: <b>{len(branches)}</b> ta filial",
        parse_mode="HTML",
    )
