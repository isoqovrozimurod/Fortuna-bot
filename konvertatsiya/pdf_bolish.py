"""
✂️ PDFni bo'lish — ko'p sahifali PDF ni bo'laklarga ajratish.

  1) PDF yuboriladi -> sahifalar soni ko'rsatiladi
  2) [📑 Har sahifa alohida]  yoki  [✂️ Oraliqlar bo'yicha]  ("1-3, 5, 7-9" — har bir bo'lak alohida PDF)
  3) natija: 1 ta fayl / 2..10 ta albom / 10 dan ko'p — ZIP
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import common, pdftools
from .common import EXPIRED_TEXT, MAX_FILE_MB, MB, ConvertError, Output, PRIVATE
from .keyboards import btn, kb_cancel, kb_done, kb_menu
from .names import clean_stem, now_stamp
from .registry import Tool, register

logger = logging.getLogger(__name__)

router = Router(name="konv_pdf_bolish")
router.message.filter(PRIVATE)

_sem = asyncio.Semaphore(2)


class PB(StatesGroup):
    waiting = State()
    choose = State()
    ranges = State()


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def kb_choose(pages: int) -> InlineKeyboardMarkup:
    rows = []
    if pages <= pdftools.MAX_PARTS:
        rows.append([btn("📑 Har sahifa alohida", "konv:pb:each")])
    rows.append([btn("✂️ Oraliqlar bo'yicha", "konv:pb:ranges")])
    rows.append([btn("⬅️ Ortga", "konv:menu"), btn("❌ Bekor qilish", "konv:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


PROMPT = ("✂️ <b>PDFni bo'lish</b>\n\n"
          f"Bo'lmoqchi bo'lgan <b>PDF</b> faylni yuboring ({MAX_FILE_MB} MB gacha).")


@router.callback_query(F.data == "konv:pick:pdf_bolish")
async def pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    uid = cb.from_user.id
    common.cancel_timer(uid)
    async with common.user_lock(uid):
        await state.clear()
        await state.set_state(PB.waiting)
        await state.update_data(ts=time.time())
    await common.edit_or_send(cb, PROMPT, kb_cancel())


def _is_pdf(m: Message) -> bool:
    d = m.document
    return bool(d and ((d.mime_type or "").lower() == "application/pdf"
                       or (d.file_name or "").lower().endswith(".pdf")))


@router.message(PB.waiting, F.document)
async def on_pdf(m: Message, state: FSMContext, bot: Bot):
    d = m.document
    if not _is_pdf(m):
        await m.answer("Bu PDF emas. Faqat PDF fayl yuboring.")
        return
    if d.file_size and d.file_size > MAX_FILE_MB * MB:
        await m.answer(f"Fayl katta (eng ko'pi bilan {MAX_FILE_MB} MB).")
        return
    uid = m.from_user.id
    async with common.user_lock(uid):                   # ikkinchi PDF shu yerda kutadi
        if await state.get_state() != PB.waiting.state:
            await m.answer("ℹ️ Avval joriy PDF bilan ishni tugating yoki bekor qiling.")
            return
        data = await state.get_data()
        if common.stale(data):
            await state.clear()
            await m.answer(EXPIRED_TEXT, reply_markup=kb_menu())
            return
        wait = await m.answer("⏳ Tekshirilmoqda…")
        try:
            blob = await common.download(bot, d.file_id)
            pages = await asyncio.to_thread(pdftools.page_count, blob)
        except ConvertError as e:
            await m.answer(f"❌ {esc(e)}", reply_markup=kb_cancel())
            return
        except Exception:
            logger.exception("PDF tekshirishda xato")
            await m.answer("❌ Kutilmagan xato. Qayta yuboring.", reply_markup=kb_cancel())
            return
        finally:
            await common.delete_msg(bot, m.chat.id, wait.message_id)
        if pages < 2:
            await m.answer("ℹ️ Bu PDF da 1 ta sahifa bor — bo'lishga hojat yo'q. Boshqa PDF yuboring.",
                           reply_markup=kb_cancel())
            return
        await state.set_state(PB.choose)
        await state.update_data(file_id=d.file_id, name=d.file_name or "hujjat.pdf",
                                pages=pages, ts=time.time())
    await m.answer(f"📕 <b>{esc((d.file_name or 'hujjat.pdf')[:50])}</b> — {pages} sahifa.\n\n"
                   "Qanday bo'lamiz?", reply_markup=kb_choose(pages))


@router.message(PB.waiting, common.not_cmd)
async def on_not_pdf(m: Message):
    await m.answer("Faqat PDF fayl yuboring (hujjat sifatida).")


@router.callback_query(PB.choose, F.data == "konv:pb:each")
async def each(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await _take(cb.from_user.id, state, PB.choose)
    await cb.answer()
    if data is None:
        await common.edit_or_send(cb, EXPIRED_TEXT, kb_menu())
        return
    await common.strip_kb(bot, cb.message.chat.id, cb.message.message_id)
    await _run(bot, cb.from_user.id, data, None)


@router.callback_query(PB.choose, F.data == "konv:pb:ranges")
async def ask_ranges(cb: CallbackQuery, state: FSMContext):
    async with common.user_lock(cb.from_user.id):
        if await state.get_state() != PB.choose.state:
            await cb.answer()
            return
        pages = (await state.get_data())["pages"]
        await state.set_state(PB.ranges)
        await state.update_data(ts=time.time())
    await cb.answer()
    await common.edit_or_send(
        cb, f"✂️ Oraliqlarni vergul bilan yozing (jami <b>{pages}</b> sahifa).\n\n"
            "Masalan: <code>1-3, 5, 7-9</code>\n"
            "Har bir oraliq — <b>alohida PDF</b> bo'ladi (1-3 | 5 | 7-9).", kb_cancel())


@router.message(PB.ranges, F.text, common.not_cmd)
async def on_ranges(m: Message, state: FSMContext, bot: Bot):
    uid = m.from_user.id
    async with common.user_lock(uid):
        if await state.get_state() != PB.ranges.state:
            return
        data = await state.get_data()
        try:
            rng = pdftools.parse_ranges(m.text, int(data["pages"]))
        except ConvertError as e:
            await m.answer(f"⚠️ {esc(e)}\nQayta yozing:", reply_markup=kb_cancel())
            return
        await state.clear()
        if common.stale(data):
            await m.answer(EXPIRED_TEXT, reply_markup=kb_menu())
            return
    await _run(bot, uid, data, rng, chat_id=m.chat.id)


@router.message(PB.choose)
@router.message(PB.ranges)
async def on_wrong(m: Message):
    if common.not_cmd(m):
        await m.answer("Tugmalardan birini bosing yoki oraliqni matn bilan yozing.")


async def _take(uid: int, state: FSMContext, expected: State) -> dict | None:
    async with common.user_lock(uid):
        if await state.get_state() != expected.state:
            return None
        data = await state.get_data()
        await state.clear()
        return None if common.stale(data) else data


def _num(i: int, width: int) -> str:
    return f"{i:0{width}d}"


async def _run(bot: Bot, uid: int, data: dict, rng: list[tuple[int, int]] | None,
               chat_id: int | None = None):
    chat_id = chat_id or uid
    wait = await bot.send_message(chat_id, "⏳ Bo'linmoqda…")
    try:
        async with _sem:
            blob = await common.download(bot, data["file_id"])
            if rng is None:
                parts = await asyncio.to_thread(pdftools.split_each, blob)
            else:
                parts = await asyncio.to_thread(pdftools.split_ranges, blob, rng)
        w = len(str(data["pages"]))
        stem = clean_stem(Path(data["name"]).stem, ".pdf", "hujjat")
        outs = [Output(f"{stem}_{_num(a, w)}.pdf" if a == b else f"{stem}_{_num(a, w)}-{_num(b, w)}.pdf", pdf)
                for a, b, pdf in parts]
        await common.deliver(bot, chat_id, outs, zip_stem=f"{stem}_bolaklar",
                             note=f"{data['pages']} sahifa → {len(outs)} ta PDF")
    except ConvertError as e:
        await bot.send_message(chat_id, f"❌ {esc(e)}", reply_markup=kb_done())
    except Exception:
        logger.exception("PDF bo'lishda kutilmagan xato")
        await bot.send_message(chat_id, "❌ Kutilmagan xato. Birozdan so'ng qayta urinib ko'ring.",
                               reply_markup=kb_done())
    finally:
        await common.delete_msg(bot, chat_id, wait.message_id)


register(Tool(key="pdf_bolish", button="✂️ PDFni bo'lish (sahifalarga)", router=router, order=20))
