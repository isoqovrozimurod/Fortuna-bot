from __future__ import annotations

import os
import base64
import json
import logging
import gspread
from google.oauth2.service_account import Credentials

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    # ReplyKeyboardMarkup,      # Foydalanuvchi qismi uchun kerak
    # KeyboardButton,           # Foydalanuvchi qismi uchun kerak
    # ReplyKeyboardRemove,      # Foydalanuvchi qismi uchun kerak
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from config import load_config

logger = logging.getLogger(__name__)
router = Router()

# ===================== GOOGLE SHEETS ULANISH =====================
# Koyeb Environment Variables da saqlanadi:
# GOOGLE_CREDENTIALS_B64 = credentials.json ning base64 ko'rinishi

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Google Sheets ID — URL'dan:
# docs.google.com/spreadsheets/d/  >>BU_QISM<<  /edit
SPREADSHEET_ID = "1U87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SHEET_NAME = "Лист1"

_gc: gspread.Client | None = None


def get_sheets_client() -> gspread.Client:
    """Lazy init — environment variable dan o'qiydi, fayl kerak emas"""
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_B64 topilmadi. "
                "Koyeb Environment Variables ga qo'shing."
            )
        creds_dict = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


async def get_all_branches() -> list[dict]:
    """
    Google Sheets'dan barcha filiallarni o'qish.

    Ustunlar (rasmga qarab):
    A=T/r  B=Viloyat  C=Tuman yoki shahar  D=Manzil  E=Filial
    F=Filial Boshqaruvchisi  G=Boshqaruvchi (shaxsiy) raqam
    H=Boshqaruvchi (filial) raqam  I=Qabulxona
    J=Kredit bo'limi  K=Unduruv bo'limi  L=Buxgalteriya
    """
    try:
        gc = get_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet(SHEET_NAME)
        records = worksheet.get_all_records()
        # Bo'sh "Filial" ustuni bo'lgan qatorlarni o'tkazib yuborish
        return [r for r in records if r.get("Filial")]
    except Exception as e:
        logger.error(f"Google Sheets'dan ma'lumot olishda xato: {e}")
        return []


# ===================== FSM =====================
class FilialStates(StatesGroup):
    pass
    # --- Foydalanuvchi uchun (keyinroq yoqiladi) ---
    # waiting_for_location = State()


# ===================== KLAVIATURALAR =====================

def branches_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Barcha filiallar", callback_data="list_branches")],
            [InlineKeyboardButton(text="🏙 Viloyat bo'yicha", callback_data="branches_by_region")],
            # Sheets'ga lat/lng qo'shilgach:
            # [InlineKeyboardButton(text="📍 Yaqin filialni topish", callback_data="find_nearest")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_menu")],
        ]
    )


# ===================== ADMIN HANDLERLAR =====================

@router.message(Command("filiallar"))
async def cmd_filiallar(message: Message, state: FSMContext):
    config = load_config()
    if message.from_user.id != config.my_id:
        await message.answer("⛔ Bu buyruq faqat admin uchun")
        return
    await state.clear()
    await message.answer(
        "📡 <b>Filiallar</b>\n\nMa'lumotlar Google Sheets'dan olinadi.",
        reply_markup=branches_menu_kb(),
        parse_mode="HTML",
    )


@router.message(Command("refresh_branches"))
async def refresh_branches(message: Message):
    """Sheets cache'ni tozalab qayta yuklash"""
    config = load_config()
    if message.from_user.id != config.my_id:
        return
    global _gc
    _gc = None
    branches = await get_all_branches()
    await message.answer(
        f"✅ Yangilandi: <b>{len(branches)}</b> ta filial yuklandi",
        parse_mode="HTML",
    )


# ---- Barcha filiallar ----

@router.callback_query(F.data == "list_branches")
async def show_all_branches(call: CallbackQuery):
    branches = await get_all_branches()

    if not branches:
        await call.answer("❌ Filiallar topilmadi. Sheets'ni tekshiring.", show_alert=True)
        return

    text = f"📋 <b>Barcha Filiallar</b> ({len(branches)} ta)\n\n"
    for b in branches:
        filial_raqam = b.get("Boshqaruvchi (filial) raqam", "")
        text += (
            f"<b>{b['Filial']}</b>\n"
            f"   🏙 {b.get('Viloyat', '')} — {b.get('Tuman yoki shahar', '')}\n"
            f"   📍 {b.get('Manzil', '')}\n"
        )
        if filial_raqam:
            text += f"   ☎️ {filial_raqam}\n"
        text += "\n"

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")]
    ])

    # Telegram limiti 4096 belgi
    if len(text) <= 4096:
        await call.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text[:4090] + "...", reply_markup=None, parse_mode="HTML")
        await call.message.answer("..." + text[4090:], reply_markup=back_kb, parse_mode="HTML")

    await call.answer()


# ---- Viloyat bo'yicha ----

@router.callback_query(F.data == "branches_by_region")
async def branches_by_region(call: CallbackQuery):
    branches = await get_all_branches()

    if not branches:
        await call.answer("❌ Filiallar topilmadi", show_alert=True)
        return

    regions = sorted(set(b["Viloyat"] for b in branches if b.get("Viloyat")))
    buttons = [
        [InlineKeyboardButton(text=region, callback_data=f"region_{region}")]
        for region in regions
    ]
    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")])

    await call.message.edit_text(
        "🏙 <b>Viloyatni tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("region_"))
async def show_region_branches(call: CallbackQuery):
    region = call.data.replace("region_", "")
    branches = await get_all_branches()
    filtered = [b for b in branches if b.get("Viloyat") == region]

    if not filtered:
        await call.answer("❌ Bu viloyatda filial topilmadi", show_alert=True)
        return

    text = f"🏙 <b>{region}</b> — {len(filtered)} ta filial\n\n"
    for b in filtered:
        text += (
            f"<b>{b['Filial']}</b>\n"
            f"   🏘 {b.get('Tuman yoki shahar', '')}\n"
            f"   📍 {b.get('Manzil', '')}\n"
            f"   👤 {b.get('Filial Boshqaruvchisi', '')}\n"
        )
        if b.get("Boshqaruvchi (filial) raqam"):
            text += f"   ☎️ Filial: {b['Boshqaruvchi (filial) raqam']}\n"
        if b.get("Boshqaruvchi (shaxsiy) raqam"):
            text += f"   📱 Shaxsiy: {b['Boshqaruvchi (shaxsiy) raqam']}\n"
        text += "\n"

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Viloyatlar", callback_data="branches_by_region")]
    ])

    if len(text) <= 4096:
        await call.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    else:
        await call.message.edit_text(text[:4090] + "...", reply_markup=None, parse_mode="HTML")
        await call.message.answer("..." + text[4090:], reply_markup=back_kb, parse_mode="HTML")

    await call.answer()


# ---- Orqaga ----

@router.callback_query(F.data == "branches_back")
async def branches_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "📡 <b>Filiallar</b>",
        reply_markup=branches_menu_kb(),
        parse_mode="HTML",
    )
    await call.answer()


# ==============================================================
# FOYDALANUVCHILAR UCHUN (hozircha kommentda)
# Yoqish uchun:
#   1. Yuqoridagi ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove importlarini oching
#   2. FilialStates.waiting_for_location ni yoqing
#   3. branches_menu_kb() da "find_nearest" tugmasini yoqing
#   4. Quyidagi handlerlardan # belgisini olib tashlang
# ==============================================================

# @router.callback_query(F.data == "branches")
# async def branches_for_users(call: CallbackQuery, state: FSMContext):
#     await state.clear()
#     await call.message.edit_text(
#         "📍 Filiallar bo'limiga xush kelibsiz!",
#         reply_markup=branches_menu_kb(),
#         parse_mode="HTML",
#     )
#     await call.answer()

# @router.callback_query(F.data == "find_nearest")
# async def request_location(call: CallbackQuery, state: FSMContext):
#     """Sheets'ga latitude, longitude ustunlari qo'shilgach ishlaydi"""
#     await state.set_state(FilialStates.waiting_for_location)
#     await call.message.edit_text("📍 Joylashuvingizni yuboring:")
#     await call.message.answer(
#         "Quyidagi tugmani bosing 👇",
#         reply_markup=ReplyKeyboardMarkup(
#             keyboard=[
#                 [KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)],
#                 [KeyboardButton(text="❌ Bekor qilish")],
#             ],
#             resize_keyboard=True,
#             one_time_keyboard=True,
#         ),
#     )
#     await call.answer()

# @router.message(FilialStates.waiting_for_location, F.text == "❌ Bekor qilish")
# async def cancel_location(message: Message, state: FSMContext):
#     await state.clear()
#     await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
#     await message.answer("📍 Filiallar:", reply_markup=branches_menu_kb())

# @router.message(FilialStates.waiting_for_location, F.location)
# async def process_location(message: Message, state: FSMContext):
#     """
#     Sheets'da 'latitude' va 'longitude' ustunlari bo'lishi kerak.
#     Qo'shilgach quyidagi kodni yoqing:
#     """
#     await state.clear()
#     from geopy.distance import geodesic
#
#     branches = await get_all_branches()
#     user_pos = (message.location.latitude, message.location.longitude)
#
#     nearest = None
#     min_dist = float("inf")
#     for b in branches:
#         try:
#             dist = geodesic(user_pos, (float(b["latitude"]), float(b["longitude"]))).km
#             if dist < min_dist:
#                 min_dist = dist
#                 nearest = {**b, "distance": round(dist, 2)}
#         except Exception:
#             continue
#
#     await message.answer("✅", reply_markup=ReplyKeyboardRemove())
#
#     if not nearest:
#         await message.answer("❌ Filiallar topilmadi")
#         return
#
#     text = (
#         f"🎯 <b>Eng Yaqin Filial</b>\n\n"
#         f"<b>{nearest['Filial']}</b>\n"
#         f"📍 {nearest.get('Manzil', '')}\n"
#         f"☎️ {nearest.get('Boshqaruvchi (filial) raqam', '')}\n"
#         f"📏 Sizdan: <b>{nearest['distance']} km</b>\n"
#     )
#     await message.answer(
#         text,
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
#             [InlineKeyboardButton(text="🗺️ Google Xaritada ko'rish",
#              url=f"https://maps.google.com/?q={nearest['latitude']},{nearest['longitude']}")],
#             [InlineKeyboardButton(text="🔙 Orqaga", callback_data="branches_back")],
#         ]),
#         parse_mode="HTML",
#     )
