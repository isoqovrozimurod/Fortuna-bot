"""Konvertorlar reyestri. Handler'lar faqat shu yerdagi Converter bilan ishlaydi."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from aiogram.types import Message


class ConvertError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato matni (HTML emas, oddiy matn)."""


@dataclass(frozen=True)
class Source:
    """Xabardan ajratib olingan fayl haqida ma'lumot."""
    file_id: str
    name: Optional[str]     # asl fayl nomi (rasm 'photo' sifatida kelsa — None)
    size: Optional[int]     # bayt (Telegram ba'zan bermaydi)


@dataclass(frozen=True)
class Converter:
    key: str                              # callback uchun qisqa kalit: "rasm_pdf"
    button: str                           # menyudagi tugma matni
    prompt: str                           # tanlanganda ko'rsatiladigan ko'rsatma (HTML)
    wrong_input: str                      # mos kelmagan xabarga javob (HTML)
    out_ext: str                          # ".pdf"
    extract: Callable[[Message], Optional[Source]]
    # SINXRON va og'ir ish — handler uni executor'da ishga tushiradi.
    # Kirish: baytlar ro'yxati (hozir 1 ta; keyin ko'p sahifali PDF uchun
    # bir nechta bo'lishi mumkin). Chiqish: tayyor fayl baytlari.
    convert: Callable[[list[bytes]], bytes]
    default_stem: Callable[[Source], str]  # nom o'tkazib yuborilganda
    ask_name: bool = True
    max_mb: int = 15                      # Telegram bot yuklab olish limiti 20 MB


REGISTRY: dict[str, Converter] = {}


def register(conv: Converter) -> Converter:
    if conv.key in REGISTRY:
        raise ValueError(f"Konvertor kaliti takrorlandi: {conv.key}")
    REGISTRY[conv.key] = conv
    return conv
