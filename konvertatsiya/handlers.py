"""
Umumiy konvertatsiya oqimi (FSM). Aniq konvertorga (rasm→PDF va h.k.)
bog'liq emas — hamma narsa registry.REGISTRY orqali.

Poyga holatlariga qarshi (albom, ikki marta bosish):
  * Albom = bir nechta xabar BIR VAQTDA keladi, aiogram ularni parallel
    qayta ishlaydi. Holat filtri handler'dan OLDIN tekshiriladi, shuning uchun
    handler ichida foydalanuvchi bo'yicha lock olib, holatni QAYTA tekshiramiz.
  * Holat MemoryStorage'da — bot qayta ishga tushsa yo'qoladi; eskirgan
    holat (STALE_SECONDS) ham tozalanadi.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import io
import logging
import time
import weakref

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .keyboards import kb_cancel, kb_done, kb_menu, kb_name
from .names import clean_stem
from .registry import REGISTRY, Converter, ConvertError, Source

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")

STALE_SECONDS = 15 * 60
_sem = asyncio.Semaphore(2)     # bir vaqtda ko'pi bilan 2 ta og'ir konvertatsiya
_locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()

MENU_TEXT = "🔄 <b>Konvertatsiya</b>\n\nQaysi turini tanlaysiz?"
EXPIRED_TEXT = "⌛ Vaqt tugadi yoki jarayon to'xtagan. Qaytadan boshlang:"
NAME_PROMPT = (
    "📝 <b>Fayl nomini kiriting</b> (masalan: <i>Pasport</i>)\n"
    "Yoki «O'tkazib yuborish» ni bosing — nom avtomatik beriladi."
)


class KonvFSM(StatesGroup):
    waiting_file = State()
    waiting_name = State()


# ───────────────────────── yordamchilar ─────────────────────────

def _lock(user_id: int) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = _locks.setdefault(user_id, asyncio.Lock())
    return lock


def _not_cmd(m: Message) -> bool:
    return not (m.text or "").startswith("/")


def _stale(data: dict) -> bool:
    return (time.time() - float(data.get("ts", 0))) > STALE_SECONDS


def _fmt_size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


async def _strip_kb(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Eski tugmalarni olib tashlaydi (eskirgan tugma bosilmasligi uchun)."""
    if not message_id:
        return
    with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)


async def _edit_or_send(cb: CallbackQuery, text: str, kb) -> Message | None:
    """Matnni tahrirlaydi; rasmli xabar (start.py) bo'lsa — o'chirib, yangisini yuboradi."""
    try:
        res = await cb.message.edit_text(text, reply_markup=kb)
        return res if isinstance(res, Message) else cb.message
    except TelegramBadRequest:
        with contextlib.suppress(Exception):
            await cb.message.delete()
        return await cb.bot.send_message(cb.from_user.id, text, reply_markup=kb)


def _too_big(src: Source, conv: Converter) -> bool:
    return bool(src.size) and src.size > conv.max_mb * 1024 * 1024


def _too_big_text(conv: Converter) -> str:
    return (f"⚠️ Fayl katta (eng ko'pi bilan {conv.max_mb} MB). "
            f"Kichikroq fayl yuboring.")


# ───────────────────────── menyu ─────────────────────────

@router.message(Command("konvertatsiya"))
async def cmd_konv(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=kb_menu())


@router.callback_query(F.data == "konv:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await _edit_or_send(cb, MENU_TEXT, kb_menu())


@router.callback_query(F.data == "konv:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer("Bekor qilindi")
    await state.clear()
    await _edit_or_send(cb, "❌ Bekor qilindi.\n\n" + MENU_TEXT, kb_menu())


@router.callback_query(F.data.startswith("konv:pick:"))
async def cb_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    conv = REGISTRY.get(cb.data.split(":", 2)[2])
    if conv is None:                         # eskirgan tugma
        await state.clear()
        await _edit_or_send(cb, MENU_TEXT, kb_menu())
        return
    await state.set_state(KonvFSM.waiting_file)
    await state.set_data({"key": conv.key, "ts": time.time()})
    sent = await _edit_or_send(cb, conv.prompt, kb_cancel())
    if sent:
        await state.update_data(pmid=sent.message_id)


# ───────────────────────── fayl qabul qilish ─────────────────────────

async def _accept_file(message: Message, state: FSMContext, bot: Bot,
                       conv: Converter, src: Source, data: dict, replaced: bool) -> None:
    """Faylni holatga yozadi va nom so'raydi (yoki to'g'ridan-to'g'ri o'tkazadi)."""
    chat_id = message.chat.id
    await _strip_kb(bot, chat_id, data.get("pmid"))

    if not conv.ask_name:
        await state.clear()
        await _deliver(bot, chat_id, message.from_user.id, conv, src, None)
        return

    note = ""
    if message.media_group_id:
        note = ("\n\n⚠️ Albom yuborildi — undan <b>bitta</b> rasm olindi. "
                "Bir nechta rasmni bitta PDF qilish hozircha yo'q.")
    head = "🔁 Rasm almashtirildi.\n\n" if replaced else ""
    sent = await message.answer(head + NAME_PROMPT + note, reply_markup=kb_name())
    await state.set_state(KonvFSM.waiting_name)
    await state.set_data({
        "key": conv.key, "file_id": src.file_id, "fname": src.name, "size": src.size,
        "ts": time.time(), "group": message.media_group_id, "pmid": sent.message_id,
    })


@router.message(KonvFSM.waiting_file, F.func(_not_cmd))
async def on_file(message: Message, state: FSMContext, bot: Bot) -> None:
    async with _lock(message.from_user.id):
        # Filtrdan keyin holat o'zgargan bo'lishi mumkin (albomning 2-5 rasmi)
        if await state.get_state() != KonvFSM.waiting_file.state:
            return
        data = await state.get_data()
        conv = REGISTRY.get(data.get("key", ""))
        if conv is None or _stale(data):
            await state.clear()
            await message.answer(EXPIRED_TEXT, reply_markup=kb_menu())
            return
        src = conv.extract(message)
        if src is None:
            await message.answer(conv.wrong_input, reply_markup=kb_cancel())
            return
        if _too_big(src, conv):
            await message.answer(_too_big_text(conv), reply_markup=kb_cancel())
            return
        await _accept_file(message, state, bot, conv, src, data, replaced=False)


# ───────────────────────── nom ─────────────────────────

async def _take_pending(user_id: int, state: FSMContext) -> tuple[Converter, dict] | None:
    """
    Nom bosqichidagi ma'lumotni OLADI va holatni tozalaydi (bir marta ishlashi
    uchun). Holat noto'g'ri/eskirgan bo'lsa None.
    """
    async with _lock(user_id):
        if await state.get_state() != KonvFSM.waiting_name.state:
            return None
        data = await state.get_data()
        conv = REGISTRY.get(data.get("key", ""))
        if conv is None or _stale(data):
            await state.clear()
            return None
        await state.clear()
        return conv, data


@router.message(KonvFSM.waiting_name, F.text, F.func(_not_cmd))
async def on_name(message: Message, state: FSMContext, bot: Bot) -> None:
    pending = await _take_pending(message.from_user.id, state)
    if pending is None:
        await message.answer(EXPIRED_TEXT, reply_markup=kb_menu())
        return
    conv, data = pending
    await _strip_kb(bot, message.chat.id, data.get("pmid"))
    src = Source(data["file_id"], data.get("fname"), data.get("size"))
    await _deliver(bot, message.chat.id, message.from_user.id, conv, src, message.text)


@router.callback_query(F.data == "konv:skip")
async def on_skip(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await cb.answer()
    pending = await _take_pending(cb.from_user.id, state)
    if pending is None:
        await _edit_or_send(cb, EXPIRED_TEXT, kb_menu())
        return
    conv, data = pending
    await _strip_kb(bot, cb.from_user.id, data.get("pmid"))
    src = Source(data["file_id"], data.get("fname"), data.get("size"))
    await _deliver(bot, cb.from_user.id, cb.from_user.id, conv, src, None)


@router.message(KonvFSM.waiting_name, F.func(_not_cmd))
async def on_name_other(message: Message, state: FSMContext, bot: Bot) -> None:
    """Nom bosqichida matn emas xabar keldi: albom davomi / yangi rasm / begona narsa."""
    async with _lock(message.from_user.id):
        if await state.get_state() != KonvFSM.waiting_name.state:
            return
        data = await state.get_data()
        conv = REGISTRY.get(data.get("key", ""))
        if conv is None or _stale(data):
            await state.clear()
            await message.answer(EXPIRED_TEXT, reply_markup=kb_menu())
            return
        src = conv.extract(message)
        if src is None:
            await message.answer("📝 Fayl nomini <b>matn</b> bilan yozing yoki «O'tkazib yuborish» ni bosing.",
                                 reply_markup=kb_name())
            return
        if message.media_group_id and message.media_group_id == data.get("group"):
            return                                   # o'sha albomning qolgan rasmlari — jim
        if _too_big(src, conv):
            await message.answer(_too_big_text(conv), reply_markup=kb_name())
            return
        await _accept_file(message, state, bot, conv, src, data, replaced=True)


# ───────────────────────── konvertatsiya va yuborish ─────────────────────────

async def _deliver(bot: Bot, chat_id: int, user_id: int, conv: Converter,
                   src: Source, name_raw: str | None) -> None:
    default = conv.default_stem(src)
    stem = clean_stem(name_raw, conv.out_ext, default) if name_raw else default
    filename = stem + conv.out_ext

    wait = await bot.send_message(chat_id, "⏳ Tayyorlanmoqda...")
    error: str | None = None
    t0 = time.monotonic()
    try:
        buf = io.BytesIO()
        await bot.download(src.file_id, destination=buf, timeout=60)
        blob = buf.getvalue()
        async with _sem:
            out = await asyncio.get_running_loop().run_in_executor(None, conv.convert, [blob])
        await bot.send_document(
            chat_id, BufferedInputFile(out, filename=filename),
            caption=f"✅ <b>{html.escape(filename, quote=False)}</b>\n📦 {_fmt_size(len(out))}",
            reply_markup=kb_done(),
        )
        logger.info("konvertatsiya OK user=%s conv=%s in=%sB out=%sB %.1fs",
                    user_id, conv.key, len(blob), len(out), time.monotonic() - t0)
    except ConvertError as e:
        error = f"❌ {html.escape(str(e), quote=False)}"
    except TelegramBadRequest as e:
        if "too big" in str(e).lower():
            error = _too_big_text(conv).replace("⚠️", "❌")
        else:
            logger.exception("konvertatsiya Telegram xatosi user=%s", user_id)
            error = "❌ Telegram faylni bermadi. Rasmni qayta yuboring."
    except Exception:
        logger.exception("konvertatsiya kutilmagan xato user=%s conv=%s", user_id, conv.key)
        error = "❌ Kutilmagan xato. Birozdan keyin qayta urinib ko'ring."
    finally:
        with contextlib.suppress(Exception):
            await wait.delete()

    if error:
        with contextlib.suppress(Exception):
            await bot.send_message(chat_id, error, reply_markup=kb_menu())


# ── Konvertorlarni ulash ───────────────────────────────────────────────
# Yangi konvertor moduli shu yerga import qilinadi (register() o'zi ishlaydi).
from . import image_pdf  # noqa: E402,F401
