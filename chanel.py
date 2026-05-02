from __future__ import annotations

import asyncio
import contextlib
import os
import json
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

async def _ensure_user_registered(user) -> None:
    try:
        from broadcast import save_user
        await save_user(
            user_id=user.id,
            full_name=user.full_name or "",
            username=user.username or "",
        )
    except Exception:
        pass

router = Router()

PERMANENT_CHANNEL = "@isoqovrozimurod_blog"
CHANNEL_FILE = "channels.json"


class ChannelFSM(StatesGroup):
    waiting_channel = State()


def normalize_channel(text: str) -> str | None:
    text = text.strip()
    m = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", text)
    if m:
        return "@" + m.group(1)
    if text.startswith("@"):
        return text
    if text.startswith("-100"):
        return text
    return None


def load_channels():
    if not os.path.exists(CHANNEL_FILE):
        return []
    try:
        with open(CHANNEL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_channels(data):
    with open(CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_all_channels():
    data = load_channels()
    return [PERMANENT_CHANNEL] + data


@router.message(Command("chanel"))
async def chanel_panel(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ Siz admin emassiz")
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_ch")],
        [InlineKeyboardButton(text="📋 Ro'yxat", callback_data="list_ch")]
    ])
    await msg.answer(
        f"📡 Majburiy obuna tizimi\n\n🔒 Doimiy kanal: {PERMANENT_CHANNEL}",
        reply_markup=kb
    )


@router.callback_query(F.data == "add_ch")
async def add_ch(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID:
        return
    await state.set_state(ChannelFSM.waiting_channel)
    await cb.message.answer(
        "➕ Kanal yuboring:\n@kanal\nt.me/kanal\nhttps://t.me/kanal\n"
        "-100xxxxxxxxxx\n\n❌ Bekor qilish uchun /cancel"
    )


@router.message(ChannelFSM.waiting_channel)
async def save_channel(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return
    if msg.text and msg.text.strip() == "/cancel":
        await state.clear()
        return await msg.answer("❌ Bekor qilindi.")
    ch = normalize_channel(msg.text or "")
    if not ch:
        return await msg.answer(
            "⚠️ Noto'g'ri format.\n@kanal | t.me/kanal | -100xxxxxxxxxx\n❌ /cancel"
        )
    if ch == PERMANENT_CHANNEL:
        await state.clear()
        return await msg.answer("🔒 Bu kanal doimiy majburiy, o'chirilmaydi")
    data = load_channels()
    if ch in data:
        await state.clear()
        return await msg.answer("⚠️ Bu kanal allaqachon mavjud")
    data.append(ch)
    save_channels(data)
    await state.clear()
    await msg.answer(f"✅ Qo'shildi: {ch}")


@router.callback_query(F.data == "list_ch")
async def list_channels(cb: CallbackQuery):
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


def subscription_keyboard(channels):
    buttons = []
    for i, ch in enumerate(channels, start=1):
        if ch.startswith("@"):
            url = f"https://t.me/{ch[1:]}"
        else:
            url = f"https://t.me/c/{str(ch)[4:]}"
        buttons.append([InlineKeyboardButton(text=f"📢 Kanal {i}", url=url)])
    buttons.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        bot = data["bot"]

        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        chat = event.chat if isinstance(event, Message) else event.message.chat

        if chat.type != "private":
            return await handler(event, data)

        # Har qanday xabarda foydalanuvchini ro'yxatga olamiz
        asyncio.ensure_future(_ensure_user_registered(user))

        # /start va /chanel ni tekshirmasdan o'tkazamiz
        text = (event.text or "") if isinstance(event, Message) else ""
        if text.startswith("/start") or text.startswith("/chanel"):
            return await handler(event, data)

        # check_sub callbackni ham tekshirmasdan o'tkazamiz
        cb_data = event.data if isinstance(event, CallbackQuery) else ""
        if cb_data == "check_sub":
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
            except Exception:
                pass

        if not not_joined:
            return await handler(event, data)

        # contextlib import qilingan — endi xato chiqmaydi
        with contextlib.suppress(Exception):
            await bot.send_message(
                user.id,
                "❗ Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=subscription_keyboard(not_joined)
            )
        return


@router.callback_query(F.data == "check_sub")
async def check_sub(cb: CallbackQuery):
    bot = cb.bot
    channels = get_all_channels()
    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, cb.from_user.id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except TelegramBadRequest:
            not_joined.append(ch)

    if not_joined:
        await cb.answer("❌ Hali obuna bo'lmadingiz!", show_alert=True)
    else:
        await cb.answer("✅ Obuna tasdiqlandi!", show_alert=False)
        with contextlib.suppress(Exception):
            await cb.message.delete()
        from start import send_promo
        await send_promo(bot, cb.from_user.id)
        
