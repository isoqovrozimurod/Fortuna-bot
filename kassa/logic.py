"""Sof funksiyalar: hisob-kitob, summa/sana o'qish, formatlash (Telegram/DB'siz)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .config import IN_KEYS, MAX_AMOUNT, OUT_KEYS, TZ


def compute(boshi: int, vals: dict) -> dict:
    jami_tushum = boshi + sum(int(vals.get(k, 0)) for k in IN_KEYS)
    jami_chiqim = sum(int(vals.get(k, 0)) for k in OUT_KEYS)
    return {
        "jami_tushum": jami_tushum,
        "jami_chiqim": jami_chiqim,
        "qoldiq": jami_tushum - jami_chiqim,
    }


def parse_amount(text: str) -> int | None:
    """'90740600', '90 740 600', '90,740,600', '90.740.600', '-', '0' -> int.
    Tushunarsiz yoki manfiy bo'lsa None. Kasr ('1,5') QABUL QILINMAYDI —
    xato bilan 15 bo'lib ketmasligi uchun."""
    if text is None:
        return None
    s = re.sub(r"[\s '’_]", "", text.strip())
    if s in ("-", "—", "–"):
        return 0
    if re.fullmatch(r"\d+", s):
        n = int(s)
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        n = int(re.sub(r"[.,]", "", s))
    else:
        return None
    return n if n < MAX_AMOUNT else None


def parse_date(text: str, today: date) -> date | None:
    s = text.strip().lower()
    if s in ("bugun", "today"):
        return today
    if s == "kecha":
        return today - timedelta(days=1)
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", s)
    if m:
        try:
            return date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def fmt(n: int) -> str:
    """Chat uchun: 646 882 350"""
    return f"{int(n):,}".replace(",", " ")


def fmt_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d.%m.%Y")


def today_tz() -> date:
    return datetime.now(TZ).date()


def net_income(row: dict) -> int:
    """Kun ichidagi tushum (boshiga qoldiqsiz)."""
    return int(row["jami_tushum"]) - int(row["kun_boshiga"])
