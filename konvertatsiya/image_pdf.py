"""
Rasm -> PDF (faqat Pillow, qo'shimcha kutubxona kerak emas).

Qarorlar (sabablari bilan):
  * Sahifa A4. Hujjat suratga olinadi, ko'pincha chop etiladi — A4 standart.
    Rasm yo'nalishiga qarab portret/landshaft avtomatik tanlanadi.
  * EXIF burilish hisobga olinadi — aks holda telefondan olingan rasm PDF'da
    yonboshlab chiqadi (eng ko'p uchraydigan xato).
  * Shaffof PNG oq fonga qo'yiladi (aks holda PDF'da qora fon chiqadi).
  * 300 dpi dan oshmaydi, JPEG sifat 85 — hajm kichik, matn o'qiladi.
  * Juda katta rasm (piksel bombasi) rad etiladi — xotira cheklangan.
"""
from __future__ import annotations

import io
from typing import Optional

from aiogram.types import Message
from PIL import Image, ImageOps, UnidentifiedImageError

from .names import clean_stem, now_stamp
from .registry import Converter, ConvertError, Source, register

DPI = 300
A4_PX = (2480, 3508)          # A4, 300 dpi (kenglik, balandlik), portret
MARGIN = 90                   # ~7.6 mm
JPEG_QUALITY = 85
MAX_PIXELS = 60_000_000       # ~ 7700 x 7700

_MIMES = {"image/jpeg", "image/png", "image/webp", "image/bmp",
          "image/tiff", "image/gif"}
_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def extract(message: Message) -> Optional[Source]:
    """'photo' (siqilgan) yoki rasm formatidagi 'document' (asl sifat)."""
    if message.photo:
        p = message.photo[-1]                      # eng katta o'lcham
        return Source(p.file_id, None, p.file_size)
    d = message.document
    if d:
        mime = (d.mime_type or "").lower()
        name = (d.file_name or "").lower()
        if mime in _MIMES or name.endswith(_EXTS):
            return Source(d.file_id, d.file_name, d.file_size)
    return None


def _to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _make_page(img: Image.Image) -> Image.Image:
    w, h = img.size
    pw, ph = (A4_PX[1], A4_PX[0]) if w > h else A4_PX      # landshaft / portret
    scale = min((pw - 2 * MARGIN) / w, (ph - 2 * MARGIN) / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((nw, nh), _LANCZOS, reducing_gap=2.0)
    page = Image.new("RGB", (pw, ph), "white")
    page.paste(resized, ((pw - nw) // 2, (ph - nh) // 2))
    return page


def convert(blobs: list[bytes]) -> bytes:
    """Har bir rasm — alohida A4 sahifa. SINXRON (executor'da chaqiriladi)."""
    if not blobs:
        raise ConvertError("Rasm topilmadi.")
    pages: list[Image.Image] = []
    for blob in blobs:
        try:
            with Image.open(io.BytesIO(blob)) as im:
                if im.width * im.height > MAX_PIXELS:
                    raise ConvertError(
                        "Rasm juda katta (o'lchami). Kichikroq rasm yuboring.")
                im.load()
                pages.append(_make_page(_to_rgb(im)))
        except ConvertError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError,
                OSError, ValueError, SyntaxError):
            raise ConvertError(
                "Rasmni ochib bo'lmadi — fayl buzilgan yoki format qo'llab-quvvatlanmaydi.")
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:],
                  resolution=float(DPI), quality=JPEG_QUALITY)
    return out.getvalue()


def _default_stem(src: Source) -> str:
    stem = (src.name or "").rsplit(".", 1)[0] if src.name else ""
    return clean_stem(stem, ".pdf", f"rasm_{now_stamp()}")


register(Converter(
    key="rasm_pdf",
    button="🖼 Rasm → PDF",
    prompt=(
        "🖼 <b>Rasm → PDF</b>\n\n"
        "Rasmni yuboring.\n"
        "💡 Matn aniq chiqishi uchun rasmni <b>«Fayl» (📎 → File)</b> ko'rinishida yuboring — "
        "oddiy «Foto» Telegram tomonidan siqiladi.\n\n"
        "<i>Qo'llab-quvvatlanadi: JPG, PNG, WEBP, BMP, TIFF, GIF</i>"
    ),
    wrong_input=(
        "⚠️ Bu rasm emas.\n"
        "JPG, PNG, WEBP, BMP, TIFF yoki GIF formatidagi rasm yuboring.\n"
        "<i>iPhone HEIC bo'lsa — «Foto» sifatida yuboring, Telegram o'zi JPG qiladi.</i>"
    ),
    out_ext=".pdf",
    extract=extract,
    convert=convert,
    default_stem=_default_stem,
    ask_name=True,
    max_mb=15,
))
