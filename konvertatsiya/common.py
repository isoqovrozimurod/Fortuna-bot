"""Hamma vositalar uchun umumiy yordamchilar (lock, yuklab olish, yuborish)."""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
import weakref
import zipfile
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (BufferedInputFile, CallbackQuery, InputMediaDocument,
                           Message)

from .keyboards import kb_done

logger = logging.getLogger(__name__)

MB = 1024 * 1024
MAX_FILE_MB = 19            # Telegram bot yuklab olish limiti 20 MB
MAX_OUT_MB = 48             # Telegram bot yuborish limiti 50 MB
MEDIA_GROUP_MAX = 10        # Telegram: albomda 2..10 ta hujjat
STALE_SECONDS = 20 * 60

EXPIRED_TEXT = "⌛ Vaqt tugadi yoki jarayon to'xtagan. Qaytadan boshlang:"

PRIVATE = F.chat.type == "private"


class ConvertError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato matni (oddiy matn, HTML emas)."""


@dataclass(frozen=True)
class Item:
    file_id: str
    name: Optional[str]      # asl fayl nomi (rasm 'photo' bo'lsa — None)
    size: Optional[int]
    kind: str                # "image" | "pdf" | "office"


@dataclass(frozen=True)
class Output:
    filename: str
    data: bytes


# ───────── lock / holat ─────────

_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()
_timers: dict[int, asyncio.Task] = {}


def user_lock(user_id: int) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = _locks.setdefault(user_id, asyncio.Lock())
    return lock


def cancel_timer(user_id: int) -> None:
    t = _timers.pop(user_id, None)
    if t and not t.done():
        t.cancel()


def set_timer(user_id: int, task: asyncio.Task) -> None:
    cancel_timer(user_id)
    _timers[user_id] = task


def not_cmd(m: Message) -> bool:
    return not (m.text or "").startswith("/")


def stale(data: dict) -> bool:
    return (time.time() - float(data.get("ts", 0))) > STALE_SECONDS


def fmt_size(n: int) -> str:
    return f"{n / MB:.1f} MB" if n >= MB else f"{max(1, round(n / 1024))} KB"


# ───────── xabarlar ─────────

async def strip_kb(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Eski tugmalarni olib tashlaydi (eskirgan tugma bosilmasligi uchun)."""
    if not message_id:
        return
    with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id,
                                            reply_markup=None)


async def delete_msg(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if message_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id, message_id)


async def edit_or_send(cb: CallbackQuery, text: str, kb) -> Message | None:
    """Matnni tahrirlaydi; rasmli xabar (start.py) bo'lsa — o'chirib, yangisini yuboradi."""
    try:
        res = await cb.message.edit_text(text, reply_markup=kb)
        return res if isinstance(res, Message) else cb.message
    except TelegramBadRequest:
        with contextlib.suppress(Exception):
            await cb.message.delete()
        return await cb.bot.send_message(cb.from_user.id, text, reply_markup=kb)


# ───────── yuklab olish / yuborish ─────────

async def download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    try:
        await bot.download(file_id, destination=buf, timeout=60)
    except TelegramBadRequest as e:
        if "too big" in str(e).lower():
            raise ConvertError(f"Fayl katta (eng ko'pi bilan {MAX_FILE_MB} MB).")
        raise ConvertError("Telegram faylni bermadi. Faylni qayta yuboring.")
    return buf.getvalue()


def unique_names(names: list[str]) -> list[str]:
    """Takrorlangan fayl nomlariga _2, _3 qo'shadi (ZIP/albomda yo'qolib ketmasin)."""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        key = n.lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 1:
            out.append(n)
        else:
            stem, dot, ext = n.rpartition(".")
            out.append(f"{stem}_{seen[key]}.{ext}" if dot else f"{n}_{seen[key]}")
    return out


async def deliver(bot: Bot, chat_id: int, outputs: list[Output],
                  zip_stem: str = "natija", note: str = "") -> None:
    """
    1 ta fayl  -> oddiy hujjat
    2..10 ta   -> hujjatlar albomi
    >10 ta     -> bitta ZIP
    """
    if not outputs:
        raise ConvertError("Natija bo'sh.")
    names = unique_names([o.filename for o in outputs])
    outputs = [Output(n, o.data) for n, o in zip(names, outputs)]
    total = sum(len(o.data) for o in outputs)
    if total > MAX_OUT_MB * MB:
        raise ConvertError(
            f"Natija juda katta ({fmt_size(total)}). Telegram {MAX_OUT_MB} MB gacha "
            f"qabul qiladi. Kamroq fayl yoki kichikroq qismlar bilan urinib ko'ring.")

    tail = f"\n{note}" if note else ""
    if len(outputs) == 1:
        o = outputs[0]
        await bot.send_document(
            chat_id, BufferedInputFile(o.data, filename=o.filename),
            caption=f"✅ <b>{_esc(o.filename)}</b>\n📦 {fmt_size(len(o.data))}{tail}",
            reply_markup=kb_done())
    elif len(outputs) <= MEDIA_GROUP_MAX:
        await bot.send_media_group(chat_id, [
            InputMediaDocument(media=BufferedInputFile(o.data, filename=o.filename))
            for o in outputs])
        await bot.send_message(
            chat_id, f"✅ {len(outputs)} ta fayl tayyor ({fmt_size(total)}){tail}",
            reply_markup=kb_done())
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:      # PDF baribir siqilmaydi
            for o in outputs:
                z.writestr(o.filename, o.data)
        data = buf.getvalue()
        if len(data) > MAX_OUT_MB * MB:
            raise ConvertError("Natija juda katta. Kamroq fayl bilan urinib ko'ring.")
        await bot.send_document(
            chat_id, BufferedInputFile(data, filename=f"{zip_stem}.zip"),
            caption=f"✅ {len(outputs)} ta PDF — ZIP arxivda\n📦 {fmt_size(len(data))}{tail}",
            reply_markup=kb_done())


def _esc(s: str) -> str:
    import html
    return html.escape(s, quote=False)
