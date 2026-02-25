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
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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
SHEET_NAME = "malumotlar"

ISHONCH_TELEFON = "+998 55 808 40 00"

_gc: gspread.Client | None = None
_coords_cache: dict[str, tuple[float, float]] = {}  # maps_url → (lat, lng)


# ===================== SHEETS =====================
def get_sheets_client() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


async def get_all_branches() -> list[dict]:
    try:
        gc = get_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
        records = ws.get_all_records()
        return [r for r in records if r.get("Filial")]
    except Exception as e:
        logger.error(f"Sheets xato: {e}")
        return []


def is_admin(user_id: int) -> bool:
    try:
        return user_id == load_config().my_id
    except Exception:
        return False


# ===================== KOORDINATA OLISH =====================

async def resolve_coords(maps_url: str) -> tuple[float, float] | None:
    """
    maps.app.goo.gl yoki maps.google.com linkdan koordinata oladi.
    Qisqa linkni kuzatib, oxirgi URL dagi @lat,lng ni topadi.
    """
    if not maps_url:
        return None

    # Cache da bormi?
    if maps_url in _coords_cache:
        return _coords_cache[maps_url]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                maps_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                final_url = str(resp.url)

        # @lat,lng formatini qidirish
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", final_url)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            _coords_cache[maps_url] = (lat, lng)
            return lat, lng

        # ?q=lat,lng formatini qidirish
        m = re.search(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)", final_url)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            _coords_cache[maps_url] = (lat, lng)
            return lat, lng

    except Exception as e:
        logger.warning(f"Koordinata olishda xato ({maps_url}): {e}")

    return None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi masofani km da hisoblaydi"""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ===================== FSM =====================
class FilialStates(StatesGroup):
    waiting_location = State()


# ===================== KLAVIATURALAR =====================

def branches_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Barcha filiallar", callback_data="list_branches"),
            InlineKeyboardButton(text="📍 Eng yaqin filial", callback_data="find_nearest"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_menu")],
    ])


def regions_kb(branches: list[dict]) -> InlineKeyboardMarkup:
    regions = sorted(set(b["Viloyat"] for b in branches if b.get("Viloyat")))
    buttons = []
    for i in range(0, len(regions), 2):
        row = [InlineKeyboardButton(text=regions[i], callback_data=f"reg_{regions[i]}")]
        if i + 1 < len(regions):
            row.append(InlineKeyboardButton(text=regions[i+1], callback_data=f"reg_{regions[i+1]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def filials_kb(branches: list[dict], region: str) -> InlineKeyboardMarkup:
    filtered = [b for b in branches if b.get("Viloyat") == region]
    buttons = []
    for i in range(0, len(filtered), 2):
        row = [InlineKeyboardButton(
            text=filtered[i]["Filial"],
            callback_data=f"fil_{filtered[i]['T/r']}"
        )]
        if i + 1 < len(filtered):
            row.append(InlineKeyboardButton(
                text=filtered[i+1]["Filial"],
                callback_data=f"fil_{filtered[i+1]['T/r']}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="list_branches")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyamni yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def nearest_results_kb(results: list[dict]) -> InlineKeyboardMarkup:
    """Eng yaqin 3 ta filial tugmalari"""
    buttons = []
    for r in results:
        km = r["distance"]
        label = f"{r['Filial']} — {km:.1f} km"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"fil_{r['T/r']}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===================== NAVIGATSIYA =====================

@router.callback_query(F.data == "branches")
async def branches_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_text(
            "📍 <b>Filiallar</b>\n\nQuyidagilardan birini tanlang:",
            reply_markup=branches_main_kb(),
            parse_mode="HTML",
        )
    except Exception:
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer(
            "📍 <b>Filiallar</b>\n\nQuyidagilardan birini tanlang:",
            reply_markup=branches_main_kb(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "list_branches")
async def show_regions(call: CallbackQuery):
    branches = await get_all_branches()
    if not branches:
        await call.answer("❌ Ma'lumot topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        "🏙 <b>Viloyatni tanlang:</b>",
        reply_markup=regions_kb(branches),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("reg_"))
async def show_filials_in_region(call: CallbackQuery):
    region = call.data[4:]
    branches = await get_all_branches()
    filtered = [b for b in branches if b.get("Viloyat") == region]
    if not filtered:
        await call.answer("❌ Bu viloyatda filial topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\nFilialni tanlang:",
        reply_markup=filials_kb(branches, region),
        parse_mode="HTML",
    )
    await call.answer()


# ===================== FILIAL DETAIL =====================

def _build_admin_text(b: dict) -> str:
    ichki = b.get("Ichki nomer", "")
    maps_url = b.get("Lokatsiya", "")
    kredit = b.get("Kredit bo'limi", "")
    unduruv = b.get("Unduruv bo'limi", "")
    text = (
        f"🏢 <b>{b['Filial']}</b>\n\n"
        f"🏙 Viloyat: {b.get('Viloyat', '')}\n"
        f"🏘 Tuman: {b.get('Tuman yoki shashar', '')}\n"
        f"📍 Manzil: {b.get('Manzil', '')}\n\n"
        f"👤 Boshqaruvchi: {b.get('Filial Boshqaruvchisi', '')}\n"
        f"📱 Shaxsiy: {b.get('Boshqaruvchi (shaxsiy) raqami', '')}\n"
        f"☎️ Filial: {b.get('Boshqaruvchi (filial) raqami', '')}\n\n"
        f"📞 Qabulxona: {b.get('Qabulxona', '')}\n"
        f"💳 Kredit bo'limi: {kredit}\n"
        f"📤 Unduruv: {unduruv}\n"
        f"📊 Buxgalteriya: {b.get('Buxgalteriya', '')}\n"
    )
    if ichki:
        text += f"🔢 Ichki nomer: {ichki}\n"
    text += f"👷 Masul xodim: {b.get('Biriktirilgan masul xodim', '')}\n"
    if maps_url:
        text += f"\n🗺 <a href='{maps_url}'>Google Maps</a>"
    return text


def _build_user_text(b: dict) -> str:
    ichki = b.get("Ichki nomer", "")
    maps_url = b.get("Lokatsiya", "")
    kredit = b.get("Kredit bo'limi", "")
    unduruv = b.get("Unduruv bo'limi", "")
    text = (
        f"🏢 <b>{b['Filial']}</b>\n\n"
        f"📍 Manzil: {b.get('Manzil', '')}\n\n"
        f"📞 Qabulxona: {b.get('Qabulxona', '')}\n"
        f"💳 Kredit bo'limi: {kredit}\n"
        f"📤 Unduruv: {unduruv}\n"
        f"📊 Buxgalteriya: {b.get('Buxgalteriya', '')}\n"
    )
    if ichki:
        text += f"🔢 Ichki nomer: {ichki}\n"
    if ISHONCH_TELEFON:
        text += f"\n📲 Ishonch telefoni: {ISHONCH_TELEFON}\n"
    if maps_url:
        text += f"\n🗺 <a href='{maps_url}'>Google Maps</a>"
    return text


@router.callback_query(F.data.startswith("fil_"))
async def show_filial_detail(call: CallbackQuery, bot: Bot):
    try:
        filial_id = int(call.data[4:])
    except ValueError:
        await call.answer("Xato", show_alert=True)
        return

    branches = await get_all_branches()
    b = next((x for x in branches if int(x.get("T/r", -1)) == filial_id), None)
    if not b:
        await call.answer("❌ Filial topilmadi", show_alert=True)
        return

    region = b.get("Viloyat", "")
    maps_url = b.get("Lokatsiya", "")
    coords = await resolve_coords(maps_url) if maps_url else None

    # Orqaga: viloyat tanlash (agar region bo'lsa)
    back_cb = f"reg_{region}" if region else "list_branches"
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_cb)]
    ])

    admin = is_admin(call.from_user.id)
    text = _build_admin_text(b) if admin else _build_user_text(b)

    await call.message.edit_text(
        text,
        reply_markup=back_kb,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Telegram lokatsiyasi (koordinata topilsa)
    if coords:
        lat, lng = coords
        await bot.send_location(
            chat_id=call.from_user.id,
            latitude=lat,
            longitude=lng,
        )

    await call.answer()


# ===================== ENG YAQIN FILIAL =====================

@router.callback_query(F.data == "find_nearest")
async def find_nearest_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(FilialStates.waiting_location)
    await call.answer()
    await call.message.edit_text(
        "📍 <b>Eng yaqin filialni topish</b>\n\n"
        "Lokatsiyangizni yuboring:",
        parse_mode="HTML",
    )
    await call.message.answer(
        "Quyidagi tugmani bosing 👇",
        reply_markup=location_request_kb(),
    )


@router.message(FilialStates.waiting_location, F.text == "❌ Bekor qilish")
async def cancel_location(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "📍 <b>Filiallar</b>",
        reply_markup=branches_main_kb(),
        parse_mode="HTML",
    )


@router.message(FilialStates.waiting_location, F.location)
async def process_location(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await message.answer("🔍 Qidirilmoqda...", reply_markup=ReplyKeyboardRemove())

    user_lat = message.location.latitude
    user_lng = message.location.longitude

    branches = await get_all_branches()

    # Barcha filiallar uchun koordinatalarni parallel olamiz
    async def fetch_coords(b: dict) -> tuple[dict, tuple[float, float] | None]:
        url = b.get("Lokatsiya", "")
        coords = await resolve_coords(url) if url else None
        return b, coords

    tasks = [fetch_coords(b) for b in branches]
    results = await asyncio.gather(*tasks)

    # Masofa hisoblash
    with_distance = []
    for b, coords in results:
        if coords:
            dist = haversine(user_lat, user_lng, coords[0], coords[1])
            with_distance.append({**b, "distance": dist, "_coords": coords})

    if not with_distance:
        await message.answer(
            "❌ Filiallar koordinatasi aniqlanmadi. Keyinroq urinib ko'ring.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches")]
            ])
        )
        return

    # Eng yaqin 3 ta
    nearest3 = sorted(with_distance, key=lambda x: x["distance"])[:3]

    await message.answer(
        "✅ <b>Eng yaqin 3 ta filial:</b>",
        reply_markup=nearest_results_kb(nearest3),
        parse_mode="HTML",
    )


# ===================== ADMIN BUYRUQLARI =====================

@router.message(Command("filiallar"))
async def cmd_filiallar(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Bu buyruq faqat admin uchun")
        return
    await state.clear()
    branches = await get_all_branches()
    await message.answer(
        f"📡 <b>Filiallar</b> ({len(branches)} ta)",
        reply_markup=branches_main_kb(),
        parse_mode="HTML",
    )


@router.message(Command("refresh_branches"))
async def refresh_branches(message: Message):
    if not is_admin(message.from_user.id):
        return
    global _gc, _coords_cache
    _gc = None
    _coords_cache = {}
    branches = await get_all_branches()
    await message.answer(
        f"✅ Yangilandi: <b>{len(branches)}</b> ta filial, koordinata cache tozalandi",
        parse_mode="HTML",
    )
