"""Kassa sozlamalari: konstantalar, hisobot qatorlari, muhit o'zgaruvchilari, ruxsat filtri.

Muhit o'zgaruvchilari:
  ADMIN_ID, MY_ID          - kassir/admin (mavjud)
  KASSA_BOSS_ID            - boshliqning Telegram ID'si
  SUPABASE_URL             - https://xxxx.supabase.co  (yoki VITE_SUPABASE_URL)
  SUPABASE_SERVICE_KEY     - service_role kaliti (ANON kalit EMAS!)
  KASSA_SHEET_ID           - (ixtiyoriy) yangi Google Sheets fayl ID'si
  GOOGLE_CREDENTIALS_B64   - (mavjud) servis akkaunt, Sheets uchun
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from aiogram.filters import BaseFilter

TZ = ZoneInfo("Asia/Tashkent")
# repo ildizi (fonts/ shu yerda); bu fayl kassa/ ichida turibdi
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATUS_SAVED = "saqlangan"
STATUS_SENT = "yuborilgan"
MAX_AMOUNT = 10**13  # 10 trillion so'm — aniq xato chegarasi

MONTHS_UZ = [
    "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
    "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr",
]

# (kalit, yorliq, tur, asosiy_rejimda_bormi) — hisobotdagi qatorlar tartibida
FIELDS: list[tuple[str, str, str, bool]] = [
    ("mijoz_tushum",    "Mijozlardan tushum",        "in",  True),
    ("bank",            "Bankdan olingan pul",       "in",  True),
    ("boshqa_filialdan", "Boshqa filialdan olindi",  "in",  False),
    ("qarz_olindi",     "Qarz shartnoma olindi",     "in",  False),
    ("berilgan_kredit", "Berilgan kredit",           "out", True),
    ("oziq_ovqat",      "Oziq-ovqat puli berildi",   "out", False),
    ("boshqa_filialga", "Boshqa filialga jo'natildi", "out", False),
    ("qarz_berildi",    "Qarz shartnoma berildi",    "out", False),
]
IN_KEYS = [k for k, _, t, _ in FIELDS if t == "in"]
OUT_KEYS = [k for k, _, t, _ in FIELDS if t == "out"]
LABELS = {k: lbl for k, lbl, _, _ in FIELDS}


# ───────────────────────── Sozlamalar ─────────────────────────

def _int_env(name: str) -> int:
    try:
        return int(os.getenv(name, "0") or 0)
    except ValueError:
        return 0


def allowed_ids() -> set[int]:
    return {i for i in (_int_env("ADMIN_ID"), _int_env("MY_ID")) if i}


def boss_id() -> int:
    return _int_env("KASSA_BOSS_ID")


def is_boss_view(user_id: int) -> bool:
    """Boshliq (faqat o'qish): KASSA_BOSS_ID, lekin kassir/admin emas."""
    b = boss_id()
    return bool(b) and user_id == b and user_id not in allowed_ids()


class ReadAllowed(BaseFilter):
    """Kassir/admin YOKI boshliq — faqat o'qish buyruqlari (/hisobot, /oy) uchun."""

    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False
        return user.id in allowed_ids() or is_boss_view(user.id)


class Allowed(BaseFilter):
    """Faqat kassir/admin. Boshqalar uchun handler 'topilmadi' bo'ladi va
    xabar boshqa routerlarga o'tadi (bot ularga bu modulni bildirmaydi)."""

    async def __call__(self, event) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user and user.id in allowed_ids())
