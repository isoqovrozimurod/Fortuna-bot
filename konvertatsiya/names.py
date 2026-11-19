"""Fayl nomini xavfsiz holatga keltirish."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Tashkent")
except Exception:                      # tzdata yo'q (masalan Windows) bo'lsa
    TZ = timezone(timedelta(hours=5))

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_RESERVED = {"con", "prn", "aux", "nul",
             *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
MAX_STEM = 60


def now_stamp() -> str:
    return datetime.now(TZ).strftime("%d.%m.%Y_%H-%M")


def clean_stem(raw: str | None, ext: str, fallback: str) -> str:
    """
    Foydalanuvchi yozgan nomni fayl nomiga aylantiradi (kengaytmasiz).
    - taqiqlangan belgilar (\\ / : * ? " < > |) va boshqaruv belgilari -> probel
    - bo'sh/faqat nuqta/Windows zahira nomlari (CON, NUL...) -> fallback
    - oxirida ".pdf" yozilgan bo'lsa — qirqiladi (nom.pdf.pdf bo'lmasin)
    """
    s = _BAD.sub(" ", raw or "")
    s = re.sub(r"\s+", " ", s).strip()
    if s.lower().endswith(ext.lower()):          # ".pdf" yoki "nom.pdf"
        s = s[: -len(ext)]
    s = s.strip(" .")[:MAX_STEM].rstrip(" .")
    if not s or s.lower() in _RESERVED:
        return fallback
    return s
