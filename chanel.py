from __future__ import annotations

import os
import json
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

router = Router()

# 🔒 Doimiy majburiy kanal
PERMANENT_CHANNEL = "@isoqovrozimurod_blog"

CHANNEL_FILE = "channels.json"


# =================== NORMALIZE ===================

def normalize_channel(text: str) -> str | None:
    """Kanal formatini normalizatsiya qilish"""
    text = text.strip()

    # https://t.me/kanal yoki t.me/kanal
    m = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", text)
    if m:
        return "@" + m.group(1)

    # @kanal
    if text.startswith("@"):
        return text

    # -100xxxxxxxxxx
    if text.startswith("-100"):
        return text

    return None


# ================= FILE =================

def load_channels():
    """Kanallar ro'yxatini yuklash"""
    if not os.path.exists(CHANNEL_FILE):
        return []

    try:
        with open(CHANNEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_channels(data):
    """Kanallar ro'yxatini saqlash"""
    with open(CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_all_channels():
    """Barcha kanallarni olish (doimiy + qo'shimcha)"""
    data = load_channels()
    return [PERMANENT_CHANNEL] + data


# ================= ADMIN PANEL =================

@router.message(Command("chanel"))
async def chanel_panel(msg: Message):
    """Admin panel"""
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Siz admin emassiz")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_ch")],
        [InlineKeyboardButton(text="📋 Ro'yxat", callback_data="list_ch")]
    ])

    await msg.answer(
        f"📡 Majburiy obuna tizimi\n\n"
        f"🔒 Doimiy kanal: {PERMANENT_CHANNEL}",
        reply_markup=kb
    )


@router.callback_query(F.data == "add_ch")
async def add_ch(cb: CallbackQuery):
    """Kanal qo'shish ko'rsatmasi"""
    if cb.from_user.id != ADMIN_ID:
        return
    await cb.message.answer(
        "➕ Kanal yuboring:\n"
        "@kanal\n"
        "t.me/kanal\n"
        "https://t.me/kanal\n"
        "-100xxxxxxxxxx"
    )


@router.message(F.text.startswith(("@", "t.me", "https://t.me", "-100")))
async def save_channel(msg: Message):
    """Kanalni saqlash"""
    if msg.from_user.id != ADMIN_ID:
        return

    ch = normalize_channel(msg.text)
    if not ch:
        return await msg.answer("❌ Noto'g'ri format")

    if ch == PERMANENT_CHANNEL:
        return await msg.answer("🔒 Bu kanal doimiy majburiy, o'chirilmaydi")

    data = load_channels()

    if ch in data:
        return await msg.answer("⚠️ Bu kanal allaqachon mavjud")

    data.append(ch)
    save_channels(data)

    await msg.answer(f"✅ Qo'shildi: {ch}")


@router.callback_query(F.data == "list_ch")
async def list_channels(cb: CallbackQuery):
    """Kanallar ro'yxati"""
    if cb.from_user.id != ADMIN_ID:
        return

    data = load_channels()

    if not data:
        return await cb.message.answer("Faqat doimiy kanal mavjud:\n" + PERMANENT_CHANNEL)

    await cb.message.answer("🔒 Doimiy kanal:\n" + PERMANENT_CHANNEL)

    for ch in data:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delch_{ch}")]
        ])
        await cb.message.answer(f"🔗 {ch}", reply_markup=kb)


@router.callback_query(F.data.startswith("delch_"))
async def delete_ch(cb: CallbackQuery):
    """Kanalni o'chirish"""
    if cb.from_user.id != ADMIN_ID:
        return

    ch = cb.data.replace("delch_", "")
    data = load_channels()

    if ch in data:
        data.remove(ch)
        save_channels(data)
        await cb.message.answer(f"🗑 O'chirildi: {ch}")
    else:
        await cb.message.answer("Topilmadi")


# ================= UI =================

def subscription_keyboard(channels):
    """Obuna bo'lish tugmalari"""
    buttons = []

    for ch in channels:
        if ch.startswith("@"):
            url = f"https://t.me/{ch[1:]}"
        else:
            url = f"https://t.me/c/{str(ch)[4:]}"
        buttons.append([InlineKeyboardButton(text=f"🔔 {ch}", url=url)])

    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ================= GLOBAL MIDDLEWARE =================

class SubscriptionMiddleware(BaseMiddleware):
    """Majburiy obuna middleware"""
    
    async def __call__(self, handler, event, data):
        bot = data["bot"]

        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        
        # Admin uchun bypass
        if user.id == ADMIN_ID:
            return await handler(event, data)
        
        chat = event.chat if isinstance(event, Message) else event.message.chat

        # Faqat private chat
        if chat.type != "private":
            return await handler(event, data)

        # /start buyrug'i uchun bypass
        text = event.text if isinstance(event, Message) else ""
        if text.startswith("/start"):
            return await handler(event, data)

        channels = get_all_channels()
        not_joined = []

        for ch in channels:
            try:
                member = await bot.get_chat_member(ch, user.id)
                if member.status in ("left", "kicked"):
                    not_joined.append(ch)
            except TelegramBadRequest:
                not_joined.append(ch)
            except Exception as e:
                print(f"❌ Kanal tekshirish xatosi {ch}: {e}")
                continue

        if not not_joined:
            return await handler(event, data)

        # Obuna bo'lmagan foydalanuvchiga xabar
        await bot.send_message(
            user.id,
            "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
            reply_markup=subscription_keyboard(not_joined)
        )
        return


# ================= CHECK =================

@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery):
    """Obunani qayta tekshirish"""
    await cb.answer("🔄 Tekshirilmoqda...", show_alert=False)
    # Middleware avtomatik tekshiradi
