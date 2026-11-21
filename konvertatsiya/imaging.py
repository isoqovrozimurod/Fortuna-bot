"""
Rasm -> PDF (faqat Pillow).

  * Sahifa A4 (portret/landshaft rasmga qarab). EXIF burilish hisobga olinadi.
  * Shaffof PNG oq fonga qo'yiladi. 300 dpi, JPEG sifat 85.
  * Juda katta rasm (piksel bombasi) rad etiladi.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from .common import ConvertError

DPI = 300
A4_PX = (2480, 3508)          # A4, 300 dpi (kenglik, balandlik), portret
MARGIN = 90                   # ~7.6 mm
JPEG_QUALITY = 85
MAX_PIXELS = 60_000_000

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/bmp",
               "image/tiff", "image/gif"}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


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
    pw, ph = (A4_PX[1], A4_PX[0]) if w > h else A4_PX
    scale = min((pw - 2 * MARGIN) / w, (ph - 2 * MARGIN) / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((nw, nh), _LANCZOS, reducing_gap=2.0)
    page = Image.new("RGB", (pw, ph), "white")
    page.paste(resized, ((pw - nw) // 2, (ph - nh) // 2))
    return page


def images_to_pdf(blobs: list[bytes]) -> bytes:
    """Har bir rasm — alohida A4 sahifa. SINXRON (executor'da chaqiring)."""
    if not blobs:
        raise ConvertError("Rasm topilmadi.")
    pages: list[Image.Image] = []
    for blob in blobs:
        try:
            with Image.open(io.BytesIO(blob)) as im:
                if im.width * im.height > MAX_PIXELS:
                    raise ConvertError("Rasm juda katta (o'lchami). Kichikroq rasm yuboring.")
                im.load()
                pages.append(_make_page(_to_rgb(im)))
        except ConvertError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError,
                OSError, ValueError, SyntaxError):
            raise ConvertError("Rasmni ochib bo'lmadi — fayl buzilgan yoki format qo'llab-quvvatlanmaydi.")
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:],
                  resolution=float(DPI), quality=JPEG_QUALITY)
    return out.getvalue()
