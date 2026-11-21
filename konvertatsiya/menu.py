"""/konvertatsiya buyrug'i, menyu, bekor qilish. Vositalarga bog'liq emas."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import common
from .keyboards import kb_done, kb_menu

router = Router(name="konv_menu")
router.message.filter(common.PRIVATE)

MENU_TEXT = ("🔄 <b>Konvertatsiya</b>\n\n"
             "Kerakli amalni tanlang:")


@router.message(Command("konvertatsiya"))
async def cmd_konv(m: Message, state: FSMContext):
    common.cancel_timer(m.from_user.id)
    await state.clear()
    await m.answer(MENU_TEXT, reply_markup=kb_menu())


@router.callback_query(F.data == "konv:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    common.cancel_timer(cb.from_user.id)
    await state.clear()
    await common.edit_or_send(cb, MENU_TEXT, kb_menu())


@router.callback_query(F.data == "konv:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    common.cancel_timer(cb.from_user.id)
    await state.clear()
    await common.edit_or_send(cb, "❌ Bekor qilindi.", kb_done())
