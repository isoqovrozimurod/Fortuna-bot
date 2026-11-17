"""Baza: Supabase (PostgREST) orqali. supabase-py ishlatilmaydi (httpx mosligi muammosi)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime

import aiohttp

from .config import FIELDS, STATUS_SAVED, STATUS_SENT, TZ

logger = logging.getLogger(__name__)


class KassaDBError(Exception):
    pass


class SupabaseDB:
    """PostgREST orqali ishlaydi (supabase-py kerak emas)."""

    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        # Eski service_role (JWT, 'eyJ...') Bearer sifatida ham yuboriladi.
        # Yangi 'sb_secret_...' kaliti JWT emas — uni faqat apikey sifatida yuborish kerak.
        if not key.startswith("sb_"):
            self.headers["Authorization"] = f"Bearer {key}"

    async def _req(self, method: str, table: str, params=None, body=None, prefer: str | None = None):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.request(
                    method, f"{self.base}/{table}", params=params, json=body, headers=headers
                ) as r:
                    text = await r.text()
                    if r.status >= 400:
                        raise KassaDBError(f"{r.status}: {text[:300]}")
                    return json.loads(text) if text else None
        except aiohttp.ClientError as e:
            raise KassaDBError(f"ulanish xatosi: {e}") from e
        except asyncio.TimeoutError as e:
            raise KassaDBError("baza javob bermadi (timeout)") from e

    async def get(self, sana: date) -> dict | None:
        rows = await self._req("GET", "kassa_hisobot", {"sana": f"eq.{sana.isoformat()}", "select": "*"})
        return rows[0] if rows else None

    async def prev(self, sana: date) -> dict | None:
        rows = await self._req(
            "GET", "kassa_hisobot",
            {"sana": f"lt.{sana.isoformat()}", "order": "sana.desc", "limit": "1", "select": "*"},
        )
        return rows[0] if rows else None

    async def month(self, year: int, month: int) -> list[dict]:
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        return await self._req(
            "GET", "kassa_hisobot",
            [("sana", f"gte.{start.isoformat()}"), ("sana", f"lt.{end.isoformat()}"),
             ("order", "sana.asc"), ("select", "*")],
        )

    async def save(self, sana: date, boshi: int, boshi_qolda: bool, vals: dict, kim: int) -> dict:
        old = await self.get(sana)
        body = {
            "sana": sana.isoformat(),
            "kun_boshiga": int(boshi),
            "kun_boshiga_qolda": bool(boshi_qolda),
            "kiritgan": kim,
            "versiya": (int(old["versiya"]) + 1) if old else 1,
            "status": STATUS_SAVED,
            "yangilangan": datetime.now(TZ).isoformat(),
            "yuborilgan_vaqt": None,
        }
        for k, _, _, _ in FIELDS:
            body[k] = int(vals.get(k, 0))
        rows = await self._req(
            "POST", "kassa_hisobot", {"on_conflict": "sana"}, body,
            prefer="resolution=merge-duplicates,return=representation",
        )
        if not rows:
            raise KassaDBError("saqlash javobi bo'sh")
        new = rows[0]
        try:
            await self._req(
                "POST", "kassa_log", None,
                {"sana": sana.isoformat(), "amal": "yangilash" if old else "yangi",
                 "eski": old, "yangi": new, "kim": kim},
            )
        except KassaDBError as e:  # jurnal xatosi hisobotni to'xtatmasin
            logger.warning("kassa_log yozilmadi: %s", e)
        return new

    async def mark_sent(self, sana: date, versiya: int) -> dict | None:
        """Atomik 'egallash': faqat hali yuborilmagan VA versiyasi o'zgarmagan bo'lsa."""
        rows = await self._req(
            "PATCH", "kassa_hisobot",
            {"sana": f"eq.{sana.isoformat()}", "versiya": f"eq.{versiya}", "status": f"eq.{STATUS_SAVED}"},
            {"status": STATUS_SENT, "yuborilgan_vaqt": datetime.now(TZ).isoformat()},
            prefer="return=representation",
        )
        return rows[0] if rows else None

    async def unmark_sent(self, sana: date, versiya: int) -> None:
        await self._req(
            "PATCH", "kassa_hisobot",
            {"sana": f"eq.{sana.isoformat()}", "versiya": f"eq.{versiya}", "status": f"eq.{STATUS_SENT}"},
            {"status": STATUS_SAVED, "yuborilgan_vaqt": None},
        )


_db = None


def get_db():
    global _db
    if _db is None:
        url = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or ""
        key = os.getenv("SUPABASE_SERVICE_KEY") or ""
        if not url or not key:
            raise KassaDBError("Baza sozlanmagan: SUPABASE_URL va SUPABASE_SERVICE_KEY kerak")
        _db = SupabaseDB(url, key)
    return _db
