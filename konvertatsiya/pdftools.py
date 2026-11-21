"""PDF bilan ishlash: sahifa soni, birlashtirish, bo'lish (pypdf)."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from .common import ConvertError

MAX_PARTS = 200


def _reader(blob: bytes) -> PdfReader:
    try:
        r = PdfReader(io.BytesIO(blob))
        if r.is_encrypted:
            try:
                ok = r.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise ConvertError("PDF parol bilan himoyalangan.")
        _ = len(r.pages)                       # buzilgan faylda shu yerda xato beradi
        return r
    except ConvertError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError, AttributeError, RecursionError):
        raise ConvertError("PDF faylni ochib bo'lmadi — fayl buzilgan.")


def page_count(blob: bytes) -> int:
    return len(_reader(blob).pages)


def _write(pages) -> bytes:
    w = PdfWriter()
    for p in pages:
        w.add_page(p)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def merge(blobs: list[bytes]) -> bytes:
    if not blobs:
        raise ConvertError("Birlashtirish uchun fayl yo'q.")
    pages = []
    for b in blobs:
        pages.extend(_reader(b).pages)
    return _write(pages)


def split_each(blob: bytes) -> list[tuple[int, int, bytes]]:
    """Har sahifa — alohida PDF. [(from, to, bytes)]"""
    r = _reader(blob)
    n = len(r.pages)
    if n > MAX_PARTS:
        raise ConvertError(f"Sahifalar ko'p ({n}). Bir martada ko'pi bilan {MAX_PARTS} ta bo'lak — oraliqlar bo'yicha bo'ling.")
    return [(i + 1, i + 1, _write([r.pages[i]])) for i in range(n)]


def split_ranges(blob: bytes, ranges: list[tuple[int, int]]) -> list[tuple[int, int, bytes]]:
    r = _reader(blob)
    return [(a, b, _write([r.pages[i] for i in range(a - 1, b)])) for a, b in ranges]


_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-–—]\s*(\d+))?\s*$")


def parse_ranges(text: str, total: int) -> list[tuple[int, int]]:
    """
    "1-3, 5, 7-9" -> [(1,3), (5,5), (7,9)]   (har biri alohida PDF bo'ladi)
    Xato bo'lsa ConvertError (foydalanuvchiga tushunarli matn bilan).
    """
    parts = [p for p in re.split(r"[,;\n]+", text or "") if p.strip()]
    if not parts:
        raise ConvertError("Oraliq kiritilmadi. Masalan: 1-3, 5, 7-9")
    if len(parts) > MAX_PARTS:
        raise ConvertError(f"Oraliqlar ko'p (ko'pi bilan {MAX_PARTS} ta).")
    out: list[tuple[int, int]] = []
    for p in parts:
        m = _RANGE.match(p)
        if not m:
            raise ConvertError(f"«{p.strip()[:20]}» tushunarsiz. Format: 1-3, 5, 7-9")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or b < 1 or a > total or b > total:
            raise ConvertError(f"«{p.strip()}» — PDF da {total} ta sahifa bor.")
        if a > b:
            raise ConvertError(f"«{p.strip()}» — boshlanish oxirgidan katta.")
        out.append((a, b))
    return out
