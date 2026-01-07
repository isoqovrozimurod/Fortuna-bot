import os
import json
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

router = Router()

CHANNEL_FILE = "channels.json"


# ================= FILE =================
def load_channels():
    if not os.path.exists(CHANNEL_FILE):
        return []
    try:
        with open(CHANNEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_channels(data):
    with open(CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================= ADMIN PANEL =================
@router.message(Command("chanel"))
async def chanel_panel(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Siz admin emassiz")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo‘shish", callback_data="add_ch")],
        [InlineKeyboardButton(text="📋 Ro‘yxat", callback_data="list_ch")]
    ])

    await msg.answer("📡 Majburiy obuna kanallari:", reply_markup=kb)


@router.callback_query(F.data == "add_ch")
async def add_ch(cb: CallbackQuery):
    await cb.message.answer("➕ Kanal username yoki ID yuboring (masalan: @kanal yoki -100xxxx):")


@router.message(F.text.startswith("@") | F.text.startswith("-100"))
async def save_channel(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return

    ch = msg.text.strip()
    data = load_channels()

    if ch in data:
        return await msg.answer("⚠️ Bu kanal allaqachon mavjud")

    data.append(ch)
    save_channels(data)

    await msg.answer("✅ Kanal qo‘shildi")


@router.callback_query(F.data == "list_ch")
async def list_channels(cb: CallbackQuery):
    data = load_channels()
    if not data:
        return await cb.message.answer("❌ Kanal yo‘q")

    for ch in data:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 O‘chirish", callback_data=f"delch_{ch}")]
        ])
        await cb.message.answer(f"🔗 {ch}", reply_markup=kb)


@router.callback_query(F.data.startswith("delch_"))
async def delete_ch(cb: CallbackQuery):
    ch = cb.data.replace("delch_", "")
    data = load_channels()
    data = [x for x in data if x != ch]
    save_channels(data)
    await cb.message.answer("🗑 Kanal o‘chirildi")


# ================= SUBSCRIPTION CHECK =================
@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery):
    await cb.answer("Tekshirildi", show_alert=False)


# ================= GLOBAL MIDDLEWARE =================
class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data["bot"]

        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        chat = event.chat if isinstance(event, Message) else event.message.chat

        if chat.type != "private":
            return await handler(event, data)

        text = event.text if isinstance(event, Message) else ""
        if text.startswith("/start") or text.startswith("/chanel"):
            return await handler(event, data)

        channels = load_channels()
        if not channels:
            return await handler(event, data)

        not_joined = []

        for ch in channels:
            try:
                member = await bot.get_chat_member(ch, user.id)
                if member.status in ("left", "kicked"):
                    not_joined.append(ch)
            except TelegramBadRequest:
                continue

        if not not_joined:
            return await handler(event, data)

        buttons = []
        for ch in not_joined:
            link = f"https://t.me/{ch[1:]}" if ch.startswith("@") else f"https://t.me/c/{str(ch)[4:]}"
            buttons.append([InlineKeyboardButton(text="🔔 Obuna bo‘lish", url=link)])

        buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

        await bot.send_message(
            user.id,
            "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling:",
            reply_markup=kb
        )

        return  # boshqa routerlarni BLOKLAYDI
