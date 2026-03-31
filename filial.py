from __future__ import annotations

import os
import re
import base64
import json
import logging
import asyncio
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

# ===================== CONFIG =====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SHEET_NAME     = "Лист1"
ISHONCH_TELEFON = "+998 55 808 40 00"

# Ustun nomlari — Sheet bilan mos
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
}

_gc: gspread.Client | None = None
_coords_cache: dict[str, tuple[float, float]] = {}


# ===================== SHEETS =====================
def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


async def get_all_branches() -> list[dict]:
    try:
        loop = asyncio.get_running_loop()
        def _fetch():
            gc = _get_gc()
            ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            return ws.get_all_records()
        records = await loop.run_in_executor(None, _fetch)
        return [r for r in records if r.get(COL["filial"])]
    except Exception as e:
        logger.error(f"Branches fetch xato: {e}")
        return []


def _is_admin(user_id: int) -> bool:
    try:
        return user_id == load_config().my_id
    except Exception:
        return False


# ===================== KOORDINATA =====================
def _parse_coords(url: str) -> tuple[float, float] | None:
    patterns = [
        r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
        r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)",
        r"/place/[^@]+@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


async def resolve_coords(maps_url: str) -> tuple[float, float] | None:
    if not maps_url:
        return None
    if maps_url in _coords_cache:
        return _coords_cache[maps_url]

    # URL ning o'zini tekshiramiz
    coords = _parse_coords(maps_url)
    if coords:
        _coords_cache[maps_url] = coords
        return coords

    # Redirect orqali final URL dan olamiz
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as s:
            async with s.get(maps_url, allow_redirects=True,
                             timeout=aiohttp.ClientTimeout(total=15),
                             headers=headers) as resp:
                final_url = str(resp.url)
                body = await resp.text(errors="ignore")

        coords = _parse_coords(final_url) or _parse_coords(body)
        if coords:
            _coords_cache[maps_url] = coords
            return coords
        logger.warning(f"Koordinata topilmadi: {maps_url} → {final_url[:80]}")
    except Exception as e:
        logger.warning(f"Koordinata xato ({maps_url}): {e}")
    return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ===================== MATN QURISHG =====================
def _g(b: dict, key: str) -> str:
    return str(b.get(COL[key], "") or "").strip()


def _user_text(b: dict) -> str:
    maps_url = _g(b, "lokatsiya")
    lines = [
        f"🏢 <b>{_g(b, 'filial')}</b>",
        f"",
        f"📍 Manzil: {_g(b, 'manzil')}",
    ]
    tel_parts = []
    if _g(b, "qabulxona"):   tel_parts.append(f"📞 Qabulxona: {_g(b, 'qabulxona')}")
    if _g(b, "kredit"):      tel_parts.append(f"💳 Kredit bo'limi: {_g(b, 'kredit')}")
    if _g(b, "unduruv"):     tel_parts.append(f"📤 Unduruv: {_g(b, 'unduruv')}")
    if _g(b, "buxgalteriya"):tel_parts.append(f"📊 Buxgalteriya: {_g(b, 'buxgalteriya')}")
    if tel_parts:
        lines.append("")
        lines.extend(tel_parts)
    if _g(b, "ichki"):
        lines.append(f"🔢 Ichki nomer: {_g(b, 'ichki')}")
    if ISHONCH_TELEFON:
        lines.append(f"\n📲 Ishonch telefoni: {ISHONCH_TELEFON}")
    if maps_url:
        lines.append(f"\n🗺 <a href='{maps_url}'>Google Maps</a>")
    return "\n".join(lines)


def _admin_text(b: dict) -> str:
    maps_url = _g(b, "lokatsiya")
    lines = [
        f"🏢 <b>{_g(b, 'filial')}</b>",
        f"",
        f"🏙 Viloyat: {_g(b, 'viloyat')}",
        f"🏘 Tuman: {_g(b, 'tuman')}",
        f"📍 Manzil: {_g(b, 'manzil')}",
        f"",
        f"👤 Boshqaruvchi: {_g(b, 'boshliq')}",
        f"📱 Shaxsiy: {_g(b, 'shaxsiy_tel')}",
        f"☎️ Filial: {_g(b, 'filial_tel')}",
        f"",
        f"📞 Qabulxona: {_g(b, 'qabulxona')}",
        f"💳 Kredit bo'limi: {_g(b, 'kredit')}",
        f"📤 Unduruv: {_g(b, 'unduruv')}",
        f"📊 Buxgalteriya: {_g(b, 'buxgalteriya')}",
    ]
    if _g(b, "ichki"):
        lines.append(f"🔢 Ichki nomer: {_g(b, 'ichki')}")
    lines.append(f"👷 Masul xodim: {_g(b, 'masul')}")
    if maps_url:
        lines.append(f"\n🗺 <a href='{maps_url}'>Google Maps</a>")
    return "\n".join(lines)


# ===================== KLAVIATURALAR =====================
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
            row.append(InlineKeyboardButton(text=regions[i+1], callback_data=f"reg_{regions[i+1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _filials_kb(branches: list[dict], region: str) -> InlineKeyboardMarkup:
    filtered = [b for b in branches if _g(b, "viloyat") == region]
    rows = []
    for i in range(0, len(filtered), 2):
        row = [InlineKeyboardButton(
            text=_g(filtered[i], "filial"),
            callback_data=f"fil_{_g(filtered[i], 'id')}"
        )]
        if i + 1 < len(filtered):
            row.append(InlineKeyboardButton(
                text=_g(filtered[i+1], "filial"),
                callback_data=f"fil_{_g(filtered[i+1], 'id')}"
            ))
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
        rows.append([InlineKeyboardButton(text=label, callback_data=f"fil_{_g(r, 'id')}")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===================== HANDLERLAR =====================

@router.callback_query(F.data == "branches")
async def cb_branches(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    text = "📍 <b>Filiallar</b>\n\nQuyidagilardan birini tanlang:"
    try:
        await call.message.edit_text(text, reply_markup=_branches_main_kb(), parse_mode="HTML")
    except Exception:
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(text, reply_markup=_branches_main_kb(), parse_mode="HTML")


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
    region = call.data[4:]
    branches = await get_all_branches()
    filtered = [b for b in branches if _g(b, "viloyat") == region]
    if not filtered:
        await call.answer("❌ Bu viloyatda filial topilmadi", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(
        f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\nFilialni tanlang:",
        reply_markup=_filials_kb(branches, region), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("fil_"))
async def cb_filial_detail(call: CallbackQuery, bot: Bot):
    try:
        filial_id = int(call.data[4:])
    except ValueError:
        await call.answer("Xato", show_alert=True)
        return

    branches = await get_all_branches()
    b = next((x for x in branches if str(_g(x, "id")) == str(filial_id)), None)
    if not b:
        await call.answer("❌ Filial topilmadi", show_alert=True)
        return

    await call.answer()

    region   = _g(b, "viloyat")
    maps_url = _g(b, "lokatsiya")
    coords   = await resolve_coords(maps_url) if maps_url else None

    back_cb = f"reg_{region}" if region else "list_branches"
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_cb)]
    ])

    text = _admin_text(b) if _is_admin(call.from_user.id) else _user_text(b)

    try:
        await call.message.edit_text(text, reply_markup=back_kb,
                                     parse_mode="HTML", disable_web_page_preview=True)
    except Exception:
        await call.message.answer(text, reply_markup=back_kb,
                                  parse_mode="HTML", disable_web_page_preview=True)

    if coords:
        await bot.send_location(chat_id=call.from_user.id,
                                latitude=coords[0], longitude=coords[1])


# ===================== ENG YAQIN FILIAL =====================

class FilialFSM(StatesGroup):
    waiting_location = State()


@router.callback_query(F.data == "find_nearest")
async def cb_find_nearest(call: CallbackQuery, state: FSMContext):
    await state.set_state(FilialFSM.waiting_location)
    await call.answer()
    try:
        await call.message.edit_text(
            "📍 <b>Eng yaqin filialni topish</b>\n\nLokatsiyangizni yuboring:",
            parse_mode="HTML",
        )
    except Exception:
        pass
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

    async def _with_dist(b: dict) -> dict | None:
        url    = _g(b, "lokatsiya")
        coords = await resolve_coords(url) if url else None
        if not coords:
            return None
        dist = _haversine(user_lat, user_lng, coords[0], coords[1])
        return {**b, "_dist": dist, "_coords": coords}

    results = await asyncio.gather(*[_with_dist(b) for b in branches])
    valid   = sorted([r for r in results if r], key=lambda x: x["_dist"])[:3]

    if not valid:
        await message.answer(
            "❌ Filiallar koordinatasi aniqlanmadi. Keyinroq urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")]
            ])
        )
        return

    await message.answer(
        "✅ <b>Eng yaqin 3 ta filial:</b>",
        reply_markup=_nearest_kb(valid), parse_mode="HTML",
    )


# ===================== ADMIN BUYRUQLARI =====================

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
    global _gc, _coords_cache
    _gc = None
    _coords_cache = {}
    branches = await get_all_branches()
    await message.answer(
        f"✅ Yangilandi: <b>{len(branches)}</b> ta filial, koordinata cache tozalandi",
        parse_mode="HTML",
    )
