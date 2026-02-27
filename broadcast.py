from __future__ import annotations

import asyncio
import logging
import os
import re
import base64
import json
from typing import Any
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

logger = logging.getLogger(__name__)

# Race condition oldini olish
_registering: set[int] = set()
_register_lock = asyncio.Lock()
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===================== SHEETS CONFIG =====================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
USERS_SHEET = "user"

HEADERS = ["T/r", "Telegram ID", "Username", "Ism", "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"]

_gc: gspread.Client | None = None


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


def get_users_sheet() -> gspread.Worksheet:
    gc = get_sheets_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(USERS_SHEET)
    if not ws.row_values(1):
        ws.append_row(HEADERS)
    return ws


# ===================== USER OPERATSIYALARI =====================

def _cleanup_sheet_sync() -> None:
    """
    Varaqni tozalaydi va T/r ni tartiblab qayta yozadi:
    1. Telegram ID bo'sh qatorlarni o'chiradi
    2. T/r ni 1 dan boshlab ketma-ket tartibda qayta yozadi
    """
    ws = get_users_sheet()
    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return  # Faqat sarlavha bor

    header = all_rows[0]
    data_rows = all_rows[1:]

    # Telegram ID bo'sh bo'lmagan qatorlarni olamiz
    # Dublikatlarni ham o'chiramiz — bir xil ID dan faqat birinchisi qoladi
    seen_ids: set[str] = set()
    valid_rows = []
    for row in data_rows:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if tg_id and tg_id not in seen_ids:
            seen_ids.add(tg_id)
            valid_rows.append(row)

    if not valid_rows:
        return

    # T/r tartiblaymiz, Holati bo'sh bo'lsa "Faol" qilamiz
    for i, row in enumerate(valid_rows, start=1):
        while len(row) < 8:
            row.append("")
        row[0] = str(i)                              # T/r
        if not str(row[7]).strip():                  # Holati bo'sh bo'lsa
            row[7] = "Faol"

    # Butun varaqni qayta yozamiz
    total_existing = len(all_rows)
    total_valid = len(valid_rows)

    # 1. Mavjud ma'lumot qatorlarini yangilaymiz
    if valid_rows:
        ws.update(
            f"A2:H{total_valid + 1}",
            valid_rows,
            value_input_option="RAW"
        )

    # 2. Ortiqcha qatorlarni tozalaymiz (bo'sh qilish)
    if total_existing > total_valid + 1:
        empty_rows = [[""] * 8 for _ in range(total_existing - total_valid - 1)]
        ws.update(
            f"A{total_valid + 2}:H{total_existing}",
            empty_rows,
            value_input_option="RAW"
        )


def _find_user_row_sync(user_id: int) -> int | None:
    """Foydalanuvchi qatorini topadi (1-based), yo'q bo'lsa None"""
    ws = get_users_sheet()
    telegram_ids = ws.col_values(2)
    for i, val in enumerate(telegram_ids, start=1):
        if str(val).strip() == str(user_id):
            return i
    return None


def _user_has_phone_sync(user_id: int) -> bool:
    ws = get_users_sheet()
    telegram_ids = ws.col_values(2)
    for i, val in enumerate(telegram_ids, start=1):
        if str(val).strip() == str(user_id):
            phone = ws.cell(i, 6).value
            return bool(phone and str(phone).strip())
    return False


def _save_user_sync(
    user_id: int,
    first_name: str = "",
    last_name: str = "",
    username: str = "",
    phone: str = "",
) -> None:
    ws = get_users_sheet()
    sana = datetime.now().strftime("%Y-%m-%d %H:%M")
    uname = f"@{username}" if username else ""

    row_idx = _find_user_row_sync(user_id)

    if row_idx is not None:
        # Mavjud foydalanuvchi — username/ism/familiya yangilaymiz
        # Telegram ID hech qachon o'zgarmaydi
        ws.update_cell(row_idx, 3, uname)
        ws.update_cell(row_idx, 4, first_name)
        ws.update_cell(row_idx, 5, last_name)
        if phone:
            ws.update_cell(row_idx, 6, phone)
    else:
        # Yangi foydalanuvchi:
        # 1. Avval tozalaymiz (bo'sh qatorlar o'chadi, T/r tartiblanadi)
        # 2. Keyin T/r ni aniqlaymiz
        # 3. Oxiriga qo'shamiz
        _cleanup_sheet_sync()

        # Tozalanganidan keyin hozirgi faol qatorlar sonini olamiz
        all_vals = ws.get_all_values()
        valid_count = sum(
            1 for r in all_vals[1:]
            if len(r) > 1 and str(r[1]).strip()
        )
        tr = valid_count + 1

        new_row = [
            str(tr),
            str(user_id),
            uname,
            first_name or "",
            last_name or "",
            phone or "",
            sana,
            "Faol",
        ]
        ws.append_row(new_row, value_input_option="RAW")


async def cleanup_sheet() -> None:
    """user va Sub-adminlar varaqlarini tozalaydi:
    - Bo'sh qatorlar o'chiriladi
    - Dublikatlar (bir xil Telegram ID) o'chiriladi
    - T/r 1 dan tartiblab qayta yoziladi
    """
    loop = asyncio.get_event_loop()

    # 1. user varag'ini tozalaymiz
    try:
        await loop.run_in_executor(None, _cleanup_sheet_sync)
    except Exception as e:
        logger.error(f"user varag'ini tozalashda xato: {e}")

    # 2. Sub-adminlar varag'ini tozalaymiz
    try:
        from reklama_nazorati import _get_ws, _cleanup_sync
        def _cleanup_subadmin():
            ws = _get_ws()
            _cleanup_sync(ws)
        await loop.run_in_executor(None, _cleanup_subadmin)
    except Exception as e:
        logger.error(f"Sub-adminlar varag'ini tozalashda xato: {e}")


async def save_user(
    user_id: int,
    full_name: str = "",
    username: str = "",
    phone: str = "",
) -> None:
    """Bir vaqtda bir xil user uchun faqat bitta yozuv — lock bilan"""
    async with _register_lock:
        if user_id in _registering:
            return  # Hozir yozilmoqda
        _registering.add(user_id)
    try:
        parts = (full_name or "").split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, _save_user_sync, user_id, first_name, last_name, username, phone
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchi saqlashda xato: {e}")
    finally:
        async with _register_lock:
            _registering.discard(user_id)


async def user_has_phone(user_id: int) -> bool:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _user_has_phone_sync, user_id)
    except Exception:
        return False


async def get_all_users() -> list[int]:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_all_users_sync)
    except Exception as e:
        logger.error(f"Foydalanuvchilarni olishda xato: {e}")
        return []


def _get_all_users_sync() -> list[int]:
    ws = get_users_sheet()
    values = ws.col_values(2)[1:]  # 2-ustun: Telegram ID, 1-qator sarlavha
    result = []
    for v in values:
        try:
            result.append(int(v))
        except (ValueError, TypeError):
            continue
    return list(set(result))


async def get_user_count() -> int:
    users = await get_all_users()
    return len(users)


# ===================== TELEGRAM POST LINK PARSER =====================

def parse_tg_link(text: str) -> tuple[str | int | None, int | None]:
    text = text.strip()
    m = re.search(r"t\.me/c/(\d+)/(\d+)", text)
    if m:
        return int("-100" + m.group(1)), int(m.group(2))
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", text)
    if m:
        return "@" + m.group(1), int(m.group(2))
    return None, None


# ===================== FSM =====================

class BroadcastFSM(StatesGroup):
    collecting = State()
    confirming = State()


# ===================== KLAVIATURALAR =====================

def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data="bc_send"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bc_cancel"),
        ],
        [InlineKeyboardButton(text="➕ Yana qo'shish", callback_data="bc_more")],
    ])


def collecting_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tayyor, yuborish", callback_data="bc_preview")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bc_cancel")],
    ])


# ===================== BROADCAST HANDLERLAR =====================

@router.message(Command("cleanup_users"))
async def cmd_cleanup_users(message: Message, state: FSMContext):
    """Foydalanuvchilar varag'ini tozalaydi va T/r ni tartiblab qayta yozadi"""
    if message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("⏳ Tozalanmoqda...")
    await cleanup_sheet()
    await msg.edit_text(
        "✅ <b>Tozalash yakunlandi!</b>\n\n"
        "• Bosh qatorlar ochirildi\n"
        "• Dublikatlar ochirildi\n"
        "• T/r tartiblab qayta yozildi\n\n"
        "user va Sub-adminlar varaqlari tozalandi.",
        parse_mode="HTML"
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    await state.clear()
    await state.set_state(BroadcastFSM.collecting)
    await state.update_data(items=[])

    count = await get_user_count()
    await message.answer(
        f"📢 <b>Ommaviy xabar yuborish</b>\n\n"
        f"👥 Foydalanuvchilar soni: <b>{count}</b>\n\n"
        f"Quyidagilarni yuboring (barchasini ketma-ket):\n"
        f"• Matn\n"
        f"• Rasm (caption bilan yoki alohida)\n"
        f"• Lokatsiya\n"
        f"• Telegram post linki (t.me/kanal/123)\n\n"
        f"Tayyor bo'lgach — ✅ <b>Tayyor</b> tugmasini bosing.",
        reply_markup=collecting_kb(),
        parse_mode="HTML",
    )


@router.message(BroadcastFSM.collecting)
async def collect_content(message: Message, state: FSMContext):
    data = await state.get_data()
    items: list[dict] = data.get("items", [])
    item: dict[str, Any] = {}

    if message.photo:
        item["type"] = "photo"
        item["file_id"] = message.photo[-1].file_id
        item["caption"] = message.caption or ""
    elif message.location:
        item["type"] = "location"
        item["latitude"] = message.location.latitude
        item["longitude"] = message.location.longitude
    elif message.text:
        chat_id, msg_id = parse_tg_link(message.text)
        if chat_id and msg_id:
            item["type"] = "forward"
            item["from_chat"] = chat_id
            item["message_id"] = msg_id
        else:
            item["type"] = "text"
            item["text"] = message.text
    else:
        await message.answer("⚠️ Bu turdagi kontent qo'llab-quvvatlanmaydi.")
        return

    items.append(item)
    await state.update_data(items=items)

    type_names = {
        "text": "📝 Matn",
        "photo": "🖼 Rasm",
        "location": "📍 Lokatsiya",
        "forward": "🔗 Post",
    }
    await message.answer(
        f"✅ {type_names.get(item['type'], item['type'])} qo'shildi. "
        f"Jami: <b>{len(items)}</b> ta.\n\n"
        f"Yana qo'shishingiz yoki tayyor tugmasini bosishingiz mumkin.",
        reply_markup=collecting_kb(),
        parse_mode="HTML",
    )


@router.callback_query(BroadcastFSM.collecting, F.data == "bc_preview")
async def preview_broadcast(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    items: list[dict] = data.get("items", [])

    if not items:
        await call.answer("❌ Hech narsa qo'shilmadi!", show_alert=True)
        return

    await call.answer()
    await call.message.edit_text("👁 <b>Ko'rib chiqish (faqat sizga):</b>", parse_mode="HTML")
    await _send_items(bot, call.from_user.id, items, is_preview=True)

    count = await get_user_count()
    await call.message.answer(
        f"📢 Yuqoridagi kontent <b>{count}</b> ta foydalanuvchiga yuboriladi.\n\n"
        f"Tasdiqlaysizmi?",
        reply_markup=confirm_kb(),
        parse_mode="HTML",
    )
    await state.set_state(BroadcastFSM.confirming)


@router.callback_query(BroadcastFSM.collecting, F.data == "bc_more")
async def add_more(call: CallbackQuery):
    await call.answer("Yana kontent yuboring 👇")


@router.callback_query(BroadcastFSM.confirming, F.data == "bc_send")
async def send_broadcast(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    items: list[dict] = data.get("items", [])
    await state.clear()

    users = await get_all_users()
    if not users:
        await call.answer("❌ Foydalanuvchilar topilmadi!", show_alert=True)
        return

    await call.answer()
    status_msg = await call.message.edit_text(f"⏳ Yuborilmoqda... 0 / {len(users)}")

    success = 0
    failed = 0

    for i, user_id in enumerate(users, 1):
        try:
            await _send_items(bot, user_id, items)
            success += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception as e:
            logger.warning(f"Yuborishda xato ({user_id}): {e}")
            failed += 1

        if i % 50 == 0:
            try:
                await status_msg.edit_text(f"⏳ Yuborilmoqda... {i} / {len(users)}")
            except Exception:
                pass

        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Yuborildi!</b>\n\n"
        f"👥 Jami: {len(users)}\n"
        f"✅ Muvaffaqiyatli: {success}\n"
        f"❌ Bloklagan / o'chirgan: {failed}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bc_cancel")
async def cancel_broadcast(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Bekor qilindi.")
    await call.message.edit_text("❌ Ommaviy xabar bekor qilindi.")


# ===================== YUBORISH FUNKSIYASI =====================

async def _send_items(
    bot: Bot, user_id: int, items: list[dict], is_preview: bool = False
) -> None:
    for item in items:
        t = item["type"]

        if t == "text":
            await bot.send_message(user_id, item["text"])
        elif t == "photo":
            await bot.send_photo(
                user_id,
                item["file_id"],
                caption=item.get("caption") or None,
            )
        elif t == "location":
            await bot.send_location(user_id, item["latitude"], item["longitude"])
        elif t == "forward":
            try:
                await bot.forward_message(
                    chat_id=user_id,
                    from_chat_id=item["from_chat"],
                    message_id=item["message_id"],
                )
            except Exception as e:
                if is_preview:
                    await bot.send_message(
                        user_id,
                        f"⚠️ Post forward qilinmadi.\n"
                        f"Sabab: {e}\n"
                        f"Yopiq kanal bo'lsa — bot kanalga admin sifatida qo'shilishi kerak.",
                    )
                else:
                    raise

        await asyncio.sleep(0.03)
