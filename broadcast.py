from __future__ import annotations

import asyncio
import logging
import os
import re
import base64
import json
from typing import Any

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
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===================== SHEETS CONFIG =====================
# Yozish uchun spreadsheets (readonly emas) scope kerak
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
USERS_SHEET = "foydalanuvchilar"  # Yangi varaq nomi

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
    """
    'foydalanuvchilar' varag'ini qaytaradi.
    Agar mavjud bo'lmasa — avtomatik yaratadi.
    """
    gc = get_sheets_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(USERS_SHEET)
    except gspread.WorksheetNotFound:
        # Varaq yo'q — yaratamiz
        ws = sh.add_worksheet(title=USERS_SHEET, rows=10000, cols=3)
        ws.append_row(["user_id", "sana", "username"])
        logger.info(f"'{USERS_SHEET}' varag'i yaratildi")

    return ws


# ===================== USER SAQLASH =====================

async def save_user(user_id: int, username: str = "") -> None:
    """
    Foydalanuvchi ID sini Sheets'ga saqlaydi.
    Agar allaqachon mavjud bo'lsa — qo'shmaydi.
    """
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _save_user_sync, user_id, username)
    except Exception as e:
        logger.warning(f"Foydalanuvchi saqlashda xato: {e}")


def _save_user_sync(user_id: int, username: str = "") -> None:
    ws = get_users_sheet()
    existing = ws.col_values(1)  # 1-ustun: user_id lar

    if str(user_id) in existing:
        return  # Allaqachon bor

    from datetime import datetime
    sana = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.append_row([str(user_id), sana, username or ""])


async def get_all_users() -> list[int]:
    """Barcha foydalanuvchi IDlarini qaytaradi"""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_all_users_sync)
    except Exception as e:
        logger.error(f"Foydalanuvchilarni olishda xato: {e}")
        return []


def _get_all_users_sync() -> list[int]:
    ws = get_users_sheet()
    values = ws.col_values(1)[1:]  # 1-qator sarlavha, o'tkazib yuborish
    result = []
    for v in values:
        try:
            result.append(int(v))
        except (ValueError, TypeError):
            continue
    # Dublikatlarni olib tashlash
    return list(set(result))


async def get_user_count() -> int:
    users = await get_all_users()
    return len(users)


# ===================== TELEGRAM POST LINK PARSER =====================

def parse_tg_link(text: str) -> tuple[str | int | None, int | None]:
    """
    Telegram post linkidan chat va message_id ni ajratadi.
    Formatlar:
      https://t.me/channel/123
      https://t.me/c/1234567890/123  (yopiq kanal)
    """
    text = text.strip()

    # Yopiq kanal: t.me/c/CHAT_ID/MSG_ID
    m = re.search(r"t\.me/c/(\d+)/(\d+)", text)
    if m:
        chat_id = int("-100" + m.group(1))
        msg_id = int(m.group(2))
        return chat_id, msg_id

    # Ochiq kanal: t.me/CHANNEL/MSG_ID
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", text)
    if m:
        chat_username = "@" + m.group(1)
        msg_id = int(m.group(2))
        return chat_username, msg_id

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


# ===================== HANDLERLAR =====================

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
    added = type_names.get(item["type"], item["type"])
    await message.answer(
        f"✅ {added} qo'shildi. Jami: <b>{len(items)}</b> ta.\n\n"
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
    await call.message.edit_text(
        "👁 <b>Ko'rib chiqish (faqat sizga):</b>",
        parse_mode="HTML",
    )

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
    status_msg = await call.message.edit_text(
        f"⏳ Yuborilmoqda... 0 / {len(users)}",
    )

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

        await asyncio.sleep(0.05)  # Telegram flood limit

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

async def _send_items(bot: Bot, user_id: int, items: list[dict], is_preview: bool = False) -> None:
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
