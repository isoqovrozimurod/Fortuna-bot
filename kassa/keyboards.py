"""Inline tugmalar. callback_data prefiksi: 'ks:'."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import STATUS_SENT


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("📝 Asosiy (3 ta)", "ks:mode:asosiy"), btn("📋 Hammasini kiritish", "ks:mode:hammasi")],
        [btn("📅 Boshqa sana", "ks:date")],
        [btn("❌ Yopish", "ks:cancel")],
    ])


def kb_field(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("0 — yo'q", f"ks:zero:{idx}"), btn("⬅️ Orqaga", f"ks:back:{idx}")],
        [btn("❌ Bekor qilish", "ks:cancel")],
    ])


def kb_report(row: dict) -> InlineKeyboardMarkup:
    sana = row["sana"]
    if row.get("status") == STATUS_SENT:
        first = btn("✅ Boshliqqa yuborilgan", "ks:noop")
    else:
        first = btn("📨 Boshliqqa yuborish", f"ks:send:{sana}")
    return InlineKeyboardMarkup(inline_keyboard=[[first], [btn("✏️ Tuzatish", f"ks:edit:{sana}")]])
