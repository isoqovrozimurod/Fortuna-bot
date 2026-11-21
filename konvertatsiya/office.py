"""
Word / Excel / PowerPoint / TXT -> PDF  (LibreOffice orqali).

DIQQAT: LibreOffice pip bilan o'rnatilmaydi — serverda `soffice` bo'lishi kerak
(Dockerfile namunasi: konvertatsiya/Dockerfile.example). Bo'lmasa available()
False qaytaradi va bot Word/Excel fayllarni muloyimlik bilan rad etadi;
rasm va PDF vositalari ta'sirlanmaydi.

Xavfsizlik/barqarorlik:
  * har bir konvertatsiya — alohida vaqtinchalik papka va alohida LO profili
    (parallel ishlaganda profil qulflanmaydi);
  * kirish fayli nomi foydalanuvchidan olinmaydi (yo'l/belgilar bilan muammo yo'q);
  * bir vaqtda faqat 1 ta jarayon (RAM), 120 soniya timeout, jarayon guruhi o'ldiriladi.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import tempfile
from pathlib import Path

from .common import ConvertError

logger = logging.getLogger(__name__)

OFFICE_EXTS = (".doc", ".docx", ".odt", ".rtf", ".txt",
               ".xls", ".xlsx", ".ods", ".csv",
               ".ppt", ".pptx", ".odp")
TIMEOUT_SECONDS = 120

_sem = asyncio.Semaphore(1)


def soffice_path() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def available() -> bool:
    return soffice_path() is not None


async def office_to_pdf(blob: bytes, filename: str | None) -> bytes:
    exe = soffice_path()
    if not exe:
        raise ConvertError("Word/Excel → PDF bu serverda yoqilmagan.")
    ext = Path(filename or "").suffix.lower()
    if ext not in OFFICE_EXTS:
        ext = ".docx"

    async with _sem:
        with tempfile.TemporaryDirectory(prefix="konv_") as tmp:
            src = Path(tmp) / f"input{ext}"
            src.write_bytes(blob)
            profile = Path(tmp) / "profile"
            env = {**os.environ, "HOME": tmp}
            proc = await asyncio.create_subprocess_exec(
                exe, "--headless", "--norestore", "--nolockcheck", "--nodefault",
                "--nofirststartwizard", f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to", "pdf", "--outdir", tmp, str(src),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                env=env, start_new_session=True,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    await proc.wait()
                raise ConvertError("Fayl juda uzoq o'tdi (timeout). Kichikroq fayl bilan urinib ko'ring.")
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                raise
            out = Path(tmp) / "input.pdf"
            if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
                logger.warning("soffice xato rc=%s: %s", proc.returncode,
                               (err or b"")[:300].decode("utf-8", "replace"))
                raise ConvertError("Faylni PDF ga o'tkazib bo'lmadi (buzilgan yoki parol bilan himoyalangan bo'lishi mumkin).")
            return out.read_bytes()
