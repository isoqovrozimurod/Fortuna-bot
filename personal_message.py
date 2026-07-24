"""
personal_message.py — Admin uchun shaxsiy xabar yuborish moduli.

DIQQAT: bu broadcast.py EMAS. broadcast.py — barcha foydalanuvchilarga
ommaviy xabar. Bu fayl — bitta yoki bir nechta TANLANGAN foydalanuvchiga
maqsadli xabar yuborish uchun, mutlaqo alohida va mustaqil modul.

Imkoniyatlar:
  • Qabul qiluvchini tanlash usullari:
      🔍 Qidirish   — ism, username, telefon yoki Telegram ID bo'yicha
      👤 Kontakt    — (a) Telegram ilovasining o'z kontakt daftaridan
                       (b) yoki bizning bazamiz ro'yxatidan
      ↩️ Forward    — foydalanuvchi xabarini forward qilib
  • Bir nechta qabul qiluvchini bitta xabarga tanlash
  • Xabar ISTALGAN formatda (matn, rasm, video, fayl, ovoz va h.k.)
  • Yuborish, bekor qilish, tahrirlash (matn/izoh), o'chirish

FAQAT ADMIN_ID uchun ishlaydi.
"""
from __future__ import annotations

import os
import re
import json
import base64
import asyncio
import logging
import secrets
import contextlib
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    KeyboardButtonRequestUsers,
)

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
USER_SHEET     = "user"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

PAGE_SIZE = 8   # bazadan ro'yxat ko'rinishida bir sahifadagi kishilar soni

_gc: gspread.Client | None = None


def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


# ── "user" varag'ini o'qish — moslashuvchan ustun nomlari ──────────────

_ID_KEYS     = ["Telegram ID", "TelegramID", "ID", "Tg ID", "Chat ID"]
_UNAME_KEYS  = ["Username", "User", "@Username"]
_ISM_KEYS    = ["Ism", "Name", "First Name", "Ismi"]
_FAM_KEYS    = ["Familiya", "Last Name", "Familiyasi"]
_TEL_KEYS    = ["Telefon", "Telefon raqami", "Phone", "Tel"]
_HOLATI_KEYS = ["Holati", "Status"]


def _pick(rec: dict, keys: list[str]) -> str:
    for k in keys:
        if k in rec and str(rec[k]).strip():
            return str(rec[k]).strip()
    return ""


def _load_users_sync() -> list[dict]:
    """
    'user' varag'idan barcha foydalanuvchilarni o'qib, normallashtirilgan
    dict ro'yxatini qaytaradi: {id, username, ism, familiya, fullname,
    telefon, holati}
    """
    gc       = _get_gc()
    ws       = gc.open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return []

    headers = [str(h).strip() for h in all_vals[0]]
    result  = []

    for row in all_vals[1:]:
        if not any(str(c).strip() for c in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        rec    = {headers[i]: padded[i] for i in range(len(headers)) if headers[i]}

        raw_id = _pick(rec, _ID_KEYS)
        try:
            uid = int(float(raw_id))
        except (ValueError, TypeError):
            continue

        ism = _pick(rec, _ISM_KEYS)
        fam = _pick(rec, _FAM_KEYS)
        result.append({
            "id":       uid,
            "username": _pick(rec, _UNAME_KEYS).lstrip("@"),
            "ism":      ism,
            "familiya": fam,
            "fullname": f"{ism} {fam}".strip() or "Noma'lum",
            "telefon":  _pick(rec, _TEL_KEYS),
            "holati":   _pick(rec, _HOLATI_KEYS),
        })
    return result


async def load_users() -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _load_users_sync)


def _search_users(users: list[dict], query: str) -> list[dict]:
    """Ism, familiya, username, telefon, ID bo'yicha (qism mos kelsa ham) qidiradi."""
    q = query.strip().lower().lstrip("@")
    if not q:
        return []
    result = []
    for u in users:
        haystack = " ".join([
            str(u["id"]), u["username"].lower(),
            u["fullname"].lower(), u["telefon"].lower(),
        ])
        if q in haystack:
            result.append(u)
    return result[:20]


# ── Kampaniyalar (yuborilgan xabarlar) xotirasi ─────────────────────────
# {campaign_id: {"recipients": {user_id: message_id}, "created": datetime}}
_campaigns: dict[str, dict] = {}


# ── FSM ──────────────────────────────────────────────────────────────────

class PersonalMsgFSM(StatesGroup):
    search           = State()   # qidiruv matni kutilmoqda
    waiting_contact  = State()   # telefon kontakti kutilmoqda
    waiting_chat_pick = State()  # Telegram chat-picker orqali tanlov kutilmoqda
    waiting_forward  = State()   # forward xabar kutilmoqda
    composing        = State()   # yuboriladigan kontent kutilmoqda
    edit_wait        = State()   # tahrirlash uchun yangi matn kutilmoqda


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def _not_command(m: Message) -> bool:
    """Buyruq (masalan /xabar) bo'lsa False — keyingi handlerlarga o'tkazadi."""
    return not (m.text or "").startswith("/")


# ── Klaviaturalar ─────────────────────────────────────────────────────────

def _menu_kb(recipients: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔍 Qidirish", callback_data="pm_search"),
            InlineKeyboardButton(text="👤 Kontakt",   callback_data="pm_contact"),
        ],
        [InlineKeyboardButton(text="↩️ Forward orqali", callback_data="pm_forward")],
    ]
    for r in recipients:
        rows.append([InlineKeyboardButton(
            text=f"❌ {r['label']}", callback_data=f"pm_remove_{r['id']}"
        )])
    if recipients:
        rows.append([InlineKeyboardButton(
            text=f"✅ Davom etish ({len(recipients)} kishi)", callback_data="pm_continue"
        )])
    rows.append([InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="pm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _search_results_kb(results: list[dict], picked: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for i, u in enumerate(results):
        mark  = "✅" if i in picked else "➕"
        label = f"{mark} {u['fullname']}"
        if u["username"]:
            label += f" (@{u['username']})"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"pm_pick_{i}")])
    rows.append([InlineKeyboardButton(text="✅ Tanlashni yakunlash", callback_data="pm_search_done")])
    rows.append([InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="pm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _contact_choice_kb() -> InlineKeyboardMarkup:
    """Qabul qiluvchini tanlashning uch usuli."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Telefon kontaktidan",      callback_data="pm_contact_phone")],
        [InlineKeyboardButton(text="💬 Shaxsiy chatlaringizdan",  callback_data="pm_contact_chat")],
        [InlineKeyboardButton(text="📋 Bizning ro'yxatdan",        callback_data="pm_contact_db")],
        [InlineKeyboardButton(text="⬅️ Orqaga",                    callback_data="pm_back_menu")],
    ])


def _telegram_chat_pick_kb() -> ReplyKeyboardMarkup:
    """
    Telegramning o'z ichki 'foydalanuvchi tanlash' pickeri.
    Admin o'zining istalgan shaxsiy chatidan (telefon kitobiga
    bog'liq bo'lmagan holda) kimnidir tanlab yuborishi mumkin.
    Bot API 7.0+ va aiogram 3.4+ talab qilinadi.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="💬 Chatdan foydalanuvchi tanlash",
                request_users=KeyboardButtonRequestUsers(
                    request_id=1,
                    max_quantity=10,
                    request_name=True,
                    request_username=True,
                ),
            )],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Kontakt yuborish", request_contact=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _paginate_kb(users: list[dict], page: int, picked: set[int]) -> InlineKeyboardMarkup:
    """Bazadagi foydalanuvchilar ro'yxatini sahifalab, tanlash imkonini beradi."""
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    chunk = users[start:end]

    rows = []
    for i, u in enumerate(chunk, start=start):
        mark  = "✅" if i in picked else "➕"
        label = f"{mark} {u['fullname']}"
        if u["username"]:
            label += f" (@{u['username']})"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"pm_db_pick_{i}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"pm_db_page_{page - 1}"))
    total_pages = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE)
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="pm_noop"))
    if end < len(users):
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"pm_db_page_{page + 1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text="✅ Tanlashni yakunlash", callback_data="pm_db_done")])
    rows.append([InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="pm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yuborish",     callback_data="pm_send")],
        [InlineKeyboardButton(text="✏️ Qayta yozish", callback_data="pm_edit_draft")],
        [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="pm_cancel")],
    ])


def _campaign_kb(campaign_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"pmc_edit_{campaign_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish",   callback_data=f"pmc_delete_{campaign_id}")],
    ])


# ── Boshlash ──────────────────────────────────────────────────────────────
# MUHIM: buyruq handlerlari fayl boshida turishi kerak — pastda keladigan
# holat-asosli "catch-all" handlerlar buyruqlarni ushlab qolmasligi uchun.

@router.message(Command("xabar"))
async def cmd_xabar(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await state.update_data(recipients=[])
    await message.answer(
        "📨 <b>Shaxsiy xabar yuborish</b>\n\n"
        "Qabul qiluvchini tanlash usulini tanlang:\n"
        "🔍 <b>Qidirish</b> — ism, username, telefon yoki ID bo'yicha\n"
        "👤 <b>Kontakt</b> — telefon daftaridan yoki bizning ro'yxatdan\n"
        "↩️ <b>Forward</b> — foydalanuvchining istalgan xabarini forward qilib",
        reply_markup=_menu_kb([]),
        parse_mode="HTML",
    )


@router.message(Command("xabarlarim"))
async def cmd_xabarlarim(message: Message):
    if not _is_admin(message.from_user.id):
        return
    if not _campaigns:
        await message.answer("📭 Hozircha yuborilgan kampaniyalar yo'q.")
        return
    rows = []
    for cid, camp in list(_campaigns.items())[-15:][::-1]:
        cnt = len(camp["recipients"])
        ts  = camp["created"].strftime("%d.%m %H:%M")
        rows.append([InlineKeyboardButton(
            text=f"🕐 {ts} — {cnt} kishi", callback_data=f"pmc_info_{cid}"
        )])
    await message.answer(
        "📨 <b>So'nggi kampaniyalar:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "pm_noop")
async def pm_noop(call: CallbackQuery):
    await call.answer()


# ── Bekor qilish / orqaga ────────────────────────────────────────────────

@router.callback_query(F.data == "pm_cancel")
async def pm_cancel(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await state.clear()
    await call.answer("Bekor qilindi")
    with contextlib.suppress(Exception):
        await call.message.edit_text("🚫 Bekor qilindi.")


@router.callback_query(F.data == "pm_back_menu")
async def pm_back_menu(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    data       = await state.get_data()
    recipients = data.get("recipients", [])
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_text(
            f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
            reply_markup=_menu_kb(recipients), parse_mode="HTML",
        )


@router.message(PersonalMsgFSM.waiting_contact, F.text == "❌ Bekor qilish")
async def pm_contact_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🚫 Bekor qilindi.", reply_markup=ReplyKeyboardRemove())


@router.message(PersonalMsgFSM.waiting_chat_pick, F.text == "❌ Bekor qilish")
async def pm_chat_pick_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🚫 Bekor qilindi.", reply_markup=ReplyKeyboardRemove())


# ── 1) Qidirish orqali tanlash ───────────────────────────────────────────

@router.callback_query(F.data == "pm_search")
async def pm_search_btn(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.search)
    await call.message.answer("🔍 Ism, username, telefon yoki Telegram ID kiriting:")


@router.message(PersonalMsgFSM.search, F.func(_not_command))
async def pm_search_input(message: Message, state: FSMContext):
    users   = await load_users()
    results = _search_users(users, message.text or "")
    if not results:
        await message.answer("❌ Hech kim topilmadi. Boshqa so'z bilan urinib ko'ring:")
        return
    await state.update_data(search_results=results, picked_idx=[])
    await message.answer(
        f"✅ {len(results)} ta natija topildi. Kerakli(lar)ni tanlang:",
        reply_markup=_search_results_kb(results, set()),
    )


@router.callback_query(F.data.startswith("pm_pick_"))
async def pm_pick(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    idx     = int(call.data.split("_")[-1])
    data    = await state.get_data()
    results = data.get("search_results", [])
    picked  = set(data.get("picked_idx", []))
    picked.symmetric_difference_update({idx})
    await state.update_data(picked_idx=list(picked))
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup(reply_markup=_search_results_kb(results, picked))


@router.callback_query(F.data == "pm_search_done")
async def pm_search_done(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    data       = await state.get_data()
    results    = data.get("search_results", [])
    picked     = set(data.get("picked_idx", []))
    recipients = data.get("recipients", [])
    existing   = {r["id"] for r in recipients}

    added = 0
    for i in picked:
        u = results[i]
        if u["id"] not in existing:
            label = u["fullname"] + (f" (@{u['username']})" if u["username"] else "")
            recipients.append({"id": u["id"], "label": label})
            existing.add(u["id"])
            added += 1

    await state.update_data(recipients=recipients, search_results=[], picked_idx=[])
    await call.answer(f"✅ {added} kishi qo'shildi")
    await call.message.edit_text(
        f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# ── 2) Kontakt orqali tanlash (ikki xil manba) ──────────────────────────

@router.callback_query(F.data == "pm_contact")
async def pm_contact_btn(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_text(
            "👤 <b>Qabul qiluvchini qayerdan tanlaysiz?</b>\n\n"
            "📱 Telefoningiz kontakt daftaridan\n"
            "📋 Bizning botda ro'yxatdan o'tgan foydalanuvchilar ro'yxatidan",
            reply_markup=_contact_choice_kb(), parse_mode="HTML",
        )


# — 2a) Telegram kontakt daftaridan —

@router.callback_query(F.data == "pm_contact_phone")
async def pm_contact_phone(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.waiting_contact)
    await call.message.answer("👤 Kontaktni ulashing:", reply_markup=_contact_kb())


@router.message(PersonalMsgFSM.waiting_contact, F.contact)
async def pm_contact_received(message: Message, state: FSMContext):
    contact    = message.contact
    data       = await state.get_data()
    recipients = data.get("recipients", [])

    uid = contact.user_id  # faqat kontakt Telegram akkauntga bog'liq bo'lsa mavjud
    if uid:
        label = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or str(uid)
    else:
        # Telegram ID mavjud bo'lmasa — telefon raqami orqali bazadan qidiramiz
        users       = await load_users()
        phone_clean = re.sub(r"\D", "", contact.phone_number or "")
        match = next(
            (u for u in users if phone_clean and re.sub(r"\D", "", u["telefon"]) == phone_clean),
            None,
        )
        if not match:
            await message.answer(
                "❌ Bu kontaktning Telegram ID sini aniqlab bo'lmadi va "
                "telefon raqami bazamizdan topilmadi.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        uid, label = match["id"], match["fullname"]

    if not any(r["id"] == uid for r in recipients):
        recipients.append({"id": uid, "label": label})

    await state.update_data(recipients=recipients)
    await state.set_state(None)
    await message.answer(f"✅ Qo'shildi: {label}", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# — 2c) Telegramning o'z chat/kontakt ro'yxatidan (telefon kitobiga bog'liq emas) —

@router.callback_query(F.data == "pm_contact_chat")
async def pm_contact_chat_btn(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.waiting_chat_pick)
    with contextlib.suppress(Exception):
        await call.message.delete()
    await call.message.answer(
        "💬 Quyidagi tugmani bosib, Telegramdagi istalgan shaxsiy chatingizdan "
        "birortasini tanlang (telefon raqami shart emas):",
        reply_markup=_telegram_chat_pick_kb(),
    )


@router.message(PersonalMsgFSM.waiting_chat_pick, F.users_shared)
async def pm_users_shared(message: Message, state: FSMContext):
    """
    Telegram 'foydalanuvchi tanlash' pickeridan kelgan javobni qayta ishlaydi.
    Bot API versiyasiga qarab natija ikki xil shaklda kelishi mumkin:
    yangi 'users' (SharedUser obyektlari) yoki eski 'user_ids' (oddiy ID lar).
    Ikkalasini ham qo'llab-quvvatlaymiz.
    """
    shared = message.users_shared
    picked_users = list(getattr(shared, "users", None) or [])
    if not picked_users:
        for uid in getattr(shared, "user_ids", []) or []:
            picked_users.append(type("_U", (), {
                "user_id": uid, "first_name": None,
                "last_name": None, "username": None,
            })())

    if not picked_users:
        await message.answer(
            "❌ Hech kim tanlanmadi.", reply_markup=ReplyKeyboardRemove()
        )
        return

    data       = await state.get_data()
    recipients = data.get("recipients", [])
    existing   = {r["id"] for r in recipients}
    added      = []

    for u in picked_users:
        uid = u.user_id
        if uid in existing:
            continue
        first = getattr(u, "first_name", None) or ""
        last  = getattr(u, "last_name", None) or ""
        uname = getattr(u, "username", None)
        label = f"{first} {last}".strip() or (f"@{uname}" if uname else str(uid))
        recipients.append({"id": uid, "label": label})
        existing.add(uid)
        added.append(label)

    await state.update_data(recipients=recipients)
    await state.set_state(None)
    await message.answer(
        f"✅ Qo'shildi: {', '.join(added) if added else '(hech kim, allaqachon ro\'yxatda)'}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# — 2b) Bizning Google Sheets bazamiz ro'yxatidan —

@router.callback_query(F.data == "pm_contact_db")
async def pm_contact_db(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer("⏳ Yuklanmoqda...")
    users = await load_users()
    if not users:
        with contextlib.suppress(Exception):
            await call.message.edit_text(
                "❌ Bazada foydalanuvchi topilmadi.", reply_markup=_contact_choice_kb()
            )
        return
    await state.update_data(db_users=users, db_page=0, db_picked=[])
    with contextlib.suppress(Exception):
        await call.message.edit_text(
            f"📋 <b>Ro'yxatdan tanlang</b> ({len(users)} kishi):",
            reply_markup=_paginate_kb(users, 0, set()), parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("pm_db_page_"))
async def pm_db_page(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    page   = int(call.data.split("_")[-1])
    data   = await state.get_data()
    users  = data.get("db_users", [])
    picked = set(data.get("db_picked", []))
    await state.update_data(db_page=page)
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup(reply_markup=_paginate_kb(users, page, picked))


@router.callback_query(F.data.startswith("pm_db_pick_"))
async def pm_db_pick(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    idx    = int(call.data.split("_")[-1])
    data   = await state.get_data()
    users  = data.get("db_users", [])
    page   = data.get("db_page", 0)
    picked = set(data.get("db_picked", []))
    picked.symmetric_difference_update({idx})
    await state.update_data(db_picked=list(picked))
    await call.answer()
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup(reply_markup=_paginate_kb(users, page, picked))


@router.callback_query(F.data == "pm_db_done")
async def pm_db_done(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    data       = await state.get_data()
    users      = data.get("db_users", [])
    picked     = set(data.get("db_picked", []))
    recipients = data.get("recipients", [])
    existing   = {r["id"] for r in recipients}

    added = 0
    for i in picked:
        u = users[i]
        if u["id"] not in existing:
            label = u["fullname"] + (f" (@{u['username']})" if u["username"] else "")
            recipients.append({"id": u["id"], "label": label})
            existing.add(u["id"])
            added += 1

    await state.update_data(recipients=recipients, db_users=[], db_picked=[], db_page=0)
    await call.answer(f"✅ {added} kishi qo'shildi")
    await call.message.edit_text(
        f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# ── 3) Forward orqali tanlash ────────────────────────────────────────────

@router.callback_query(F.data == "pm_forward")
async def pm_forward_btn(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.waiting_forward)
    await call.message.answer(
        "↩️ Foydalanuvchining istalgan xabarini shu yerga forward qiling.\n\n"
        "<i>Eslatma: agar foydalanuvchi forward sozlamalarida ismini "
        "yashirgan bo'lsa, bu usul ishlamaydi.</i>",
        parse_mode="HTML",
    )


@router.message(PersonalMsgFSM.waiting_forward, F.func(_not_command))
async def pm_forward_received(message: Message, state: FSMContext):
    # aiogram/Bot API versiyasidan qat'i nazar ikkala usulni ham sinaymiz
    fwd_user = getattr(message, "forward_from", None)
    if not fwd_user:
        origin   = getattr(message, "forward_origin", None)
        fwd_user = getattr(origin, "sender_user", None) if origin else None

    if not fwd_user:
        await message.answer(
            "❌ Bu foydalanuvchining ID sini aniqlab bo'lmadi "
            "(forward sozlamalarida ismini yashirgan bo'lishi mumkin)."
        )
        return

    data       = await state.get_data()
    recipients = data.get("recipients", [])
    label      = fwd_user.full_name or (f"@{fwd_user.username}" if fwd_user.username else str(fwd_user.id))

    if not any(r["id"] == fwd_user.id for r in recipients):
        recipients.append({"id": fwd_user.id, "label": label})

    await state.update_data(recipients=recipients)
    await state.set_state(None)
    await message.answer(
        f"✅ Qo'shildi: {label}\n\n📨 Tanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# ── Tanlangan ro'yxatdan o'chirish ───────────────────────────────────────

@router.callback_query(F.data.startswith("pm_remove_"))
async def pm_remove(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    uid  = int(call.data.split("_")[-1])
    data = await state.get_data()
    recipients = [r for r in data.get("recipients", []) if r["id"] != uid]
    await state.update_data(recipients=recipients)
    await call.answer("O'chirildi")
    await call.message.edit_text(
        f"📨 <b>Shaxsiy xabar yuborish</b>\n\nTanlangan: {len(recipients)} kishi",
        reply_markup=_menu_kb(recipients), parse_mode="HTML",
    )


# ── Xabar yozish bosqichi ────────────────────────────────────────────────

@router.callback_query(F.data == "pm_continue")
async def pm_continue(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    data       = await state.get_data()
    recipients = data.get("recipients", [])
    if not recipients:
        await call.answer("❌ Hech kim tanlanmagan!", show_alert=True)
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.composing)
    await call.message.answer(
        f"✍️ Endi xabarni yuboring — <b>istalgan formatda</b> "
        f"(matn, rasm, video, fayl, ovozli xabar va h.k.):\n\n"
        f"Qabul qiluvchilar: {len(recipients)} kishi",
        parse_mode="HTML",
    )


@router.message(PersonalMsgFSM.composing, F.func(_not_command))
async def pm_receive_draft(message: Message, state: FSMContext):
    """
    Har qanday turdagi xabarni qabul qiladi — matn, rasm, video, fayl va h.k.
    copy_message() barcha turlarni universal ko'chiradi, shuning uchun
    content_type bo'yicha alohida ishlov berish shart emas.
    """
    await state.update_data(draft_chat_id=message.chat.id, draft_message_id=message.message_id)
    await message.reply(
        "👆 Xabar shu ko'rinishda yuboriladi. Tasdiqlaysizmi?",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(F.data == "pm_edit_draft")
async def pm_edit_draft(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.composing)
    await call.message.answer("✏️ Yangi xabarni yuboring:")


# ── Yuborish ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "pm_send")
async def pm_send(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not _is_admin(call.from_user.id):
        return
    await call.answer("⏳ Yuborilmoqda...")

    data             = await state.get_data()
    recipients       = data.get("recipients", [])
    draft_chat_id    = data.get("draft_chat_id")
    draft_message_id = data.get("draft_message_id")

    if not recipients or not draft_message_id:
        with contextlib.suppress(Exception):
            await call.message.edit_text("❌ Xato: ma'lumot to'liq emas. Qaytadan /xabar bilan boshlang.")
        await state.clear()
        return

    sent_map: dict[int, int] = {}
    ok, fail = 0, 0
    for r in recipients:
        try:
            sent = await bot.copy_message(
                chat_id=r["id"], from_chat_id=draft_chat_id, message_id=draft_message_id,
            )
            sent_map[r["id"]] = sent.message_id
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"Xabar yuborilmadi ({r['id']}): {e}")

    campaign_id = secrets.token_hex(4)
    _campaigns[campaign_id] = {
        "admin_id":   call.from_user.id,
        "recipients": sent_map,
        "created":    datetime.now(),
    }

    with contextlib.suppress(Exception):
        await call.message.edit_text(
            f"✅ Yuborildi: <b>{ok}</b> ta\n❌ Yuborilmadi: <b>{fail}</b> ta\n\n"
            f"🆔 Kampaniya: <code>{campaign_id}</code>\n"
            f"<i>Buni keyinroq /xabarlarim orqali topib, tahrirlash yoki "
            f"o'chirish mumkin.</i>",
            reply_markup=_campaign_kb(campaign_id), parse_mode="HTML",
        )
    await state.clear()


# ── Yuborilgan kampaniyani tahrirlash / o'chirish ────────────────────────

@router.callback_query(F.data.startswith("pmc_info_"))
async def pmc_info(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    campaign_id = call.data.split("_", 2)[2]
    camp = _campaigns.get(campaign_id)
    if not camp:
        await call.answer("❌ Topilmadi (bot qayta ishga tushgandan keyin xotira tozalanadi)", show_alert=True)
        return
    await state.clear()  # agar tahrirlash o'rtasida "Orqaga" bosilgan bo'lsa ham holat tozalanadi
    await call.answer()
    await call.message.edit_text(
        f"🆔 Kampaniya: <code>{campaign_id}</code>\n"
        f"👥 Qabul qiluvchilar: {len(camp['recipients'])}\n"
        f"🕐 Yaratilgan: {camp['created'].strftime('%d.%m.%Y %H:%M')}",
        reply_markup=_campaign_kb(campaign_id), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pmc_delete_"))
async def pmc_delete(call: CallbackQuery, bot: Bot):
    if not _is_admin(call.from_user.id):
        return
    campaign_id = call.data.split("_", 2)[2]
    camp = _campaigns.get(campaign_id)
    if not camp:
        await call.answer("❌ Topilmadi (eski bo'lishi mumkin)", show_alert=True)
        return
    await call.answer("⏳ O'chirilmoqda...")

    ok, fail = 0, 0
    for uid, mid in camp["recipients"].items():
        try:
            await bot.delete_message(uid, mid)
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"O'chirishda xato ({uid}): {e}")

    with contextlib.suppress(Exception):
        await call.message.edit_text(f"🗑 O'chirildi: {ok} ta, xato: {fail} ta")
    del _campaigns[campaign_id]


@router.callback_query(F.data.startswith("pmc_edit_"))
async def pmc_edit_start(call: CallbackQuery, state: FSMContext):
    if not _is_admin(call.from_user.id):
        return
    campaign_id = call.data.split("_", 2)[2]
    if campaign_id not in _campaigns:
        await call.answer("❌ Topilmadi", show_alert=True)
        return
    await call.answer()
    await state.set_state(PersonalMsgFSM.edit_wait)
    await state.update_data(edit_campaign_id=campaign_id)
    edit_cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"pmc_info_{campaign_id}")],
        [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data="pm_cancel")],
    ])
    await call.message.answer(
        "✏️ Yangi matnni yuboring:\n\n"
        "<i>Eslatma: bu faqat matnli xabarlarni yoki media izohini (caption) "
        "tahrirlaydi. Rasm/videoning o'zini almashtirish qo'llab-quvvatlanmaydi — "
        "bunday holda avval o'chirib, qaytadan yuborish tavsiya etiladi.</i>",
        reply_markup=edit_cancel_kb,
        parse_mode="HTML",
    )


@router.message(PersonalMsgFSM.edit_wait, F.text, F.func(_not_command))
async def pmc_edit_apply(message: Message, state: FSMContext, bot: Bot):
    data        = await state.get_data()
    campaign_id = data.get("edit_campaign_id")
    camp        = _campaigns.get(campaign_id)
    if not camp:
        await message.answer("❌ Kampaniya topilmadi (eski bo'lishi mumkin).")
        await state.clear()
        return

    ok, fail = 0, 0
    for uid, mid in camp["recipients"].items():
        try:
            await bot.edit_message_text(message.text, chat_id=uid, message_id=mid)
            ok += 1
            continue
        except Exception:
            pass
        try:
            await bot.edit_message_caption(chat_id=uid, message_id=mid, caption=message.text)
            ok += 1
        except Exception as e:
            fail += 1
            logger.warning(f"Tahrirlashda xato ({uid}): {e}")

    await message.answer(f"✏️ Tahrirlandi: {ok} ta, xato: {fail} ta")
    await state.clear()
