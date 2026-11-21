"""Umumiy inline tugmalar. callback_data prefiksi: 'konv:'."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .registry import REGISTRY


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb_menu() -> InlineKeyboardMarkup:
    tools = sorted(REGISTRY.values(), key=lambda t: t.order)
    rows = [[btn(t.button, f"konv:pick:{t.key}")] for t in tools]
    rows.append([btn("⬅️ Bosh menyu", "back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("⬅️ Ortga", "konv:menu"), btn("❌ Bekor qilish", "konv:cancel")],
    ])


def kb_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🔄 Yana konvertatsiya", "konv:menu")],
        [btn("🏠 Bosh menyu", "back_to_menu")],
    ])
