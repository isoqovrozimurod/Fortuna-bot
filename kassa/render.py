"""Hisobot rasmi (Pillow): Excel'dagi 'Kunlik' hisoboti ko'rinishida PNG."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

from .config import BASE_DIR, LABELS
from .logic import fmt, fmt_date


_FONT_REG = [
    os.path.join(BASE_DIR, "fonts", "calibri.ttf"),
    os.path.join(BASE_DIR, "fonts", "Carlito-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_FONT_BOLD = [
    os.path.join(BASE_DIR, "fonts", "calibrib.ttf"),
    os.path.join(BASE_DIR, "fonts", "Carlito-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _font(paths: list[str], size: int):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # eski Pillow
        return ImageFont.load_default()


C_GREEN, C_BLUE, C_KEY = "#C6E0B4", "#BDD7EE", "#A6A6A6"
C_ITEM, C_CYAN, C_SALMON = "#E7E6E6", "#CCFFFF", "#FCE4D6"


def render_report(row: dict) -> bytes:
    """Excel'dagi 'Kunlik' hisoboti ko'rinishida PNG."""
    S = 2                      # sifat uchun 2x
    cw, rh = 270 * S, 25 * S   # ustun kengligi, qator balandligi
    top = 24 * S               # sana qatori
    W, H = cw * 2 + 2, top + rh * 19 + 2
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_b = _font(_FONT_BOLD, 19 * S)
    f_r = _font(_FONT_REG, 19 * S)
    f_d = _font(_FONT_BOLD, 16 * S)
    line = (0, 0, 0)

    d.text((W - 6 * S, top // 2), fmt_date(row["sana"]), font=f_d, fill="black", anchor="rm")

    def num(n: int, always: bool = False, dash: bool = False) -> str:
        if n == 0 and not always:
            return "-" if dash else ""
        return fmt(n) + ",0"

    layout = [
        ("title", "FORTUNA BIZNES G'ALLAOROL FILIALI", None, C_GREEN),
        ("kassa", "KASSA", None, C_BLUE),
        ("key", "Kun boshiga qoldiq", int(row["kun_boshiga"]), C_GREEN),
        ("spacer",),
        ("item", LABELS["mijoz_tushum"], "mijoz_tushum"),
        ("item", LABELS["bank"], "bank"),
        ("item", LABELS["boshqa_filialdan"], "boshqa_filialdan"),
        ("item", LABELS["qarz_olindi"], "qarz_olindi"),
        ("spacer",),
        ("key", "Jami tushum", int(row["jami_tushum"]), C_CYAN),
        ("spacer",),
        ("item", LABELS["berilgan_kredit"], "berilgan_kredit"),
        ("item", LABELS["oziq_ovqat"], "oziq_ovqat"),
        ("item", LABELS["boshqa_filialga"], "boshqa_filialga"),
        ("item", LABELS["qarz_berildi"], "qarz_berildi"),
        ("spacer",),
        ("key", "Jami chiqim", int(row["jami_chiqim"]), C_SALMON),
        ("spacer",),
        ("key", "Kun oxiriga qoldiq", int(row["qoldiq"]), C_GREEN),
    ]

    y = top
    for spec in layout:
        kind = spec[0]
        y2 = y + rh
        x0, xm, x1 = 1, 1 + cw, 1 + cw * 2
        if kind == "title":
            d.rectangle([x0, y, x1, y2], fill=spec[3], outline=line, width=S)
            d.text(((x0 + x1) // 2, (y + y2) // 2), spec[1], font=f_b, fill="black", anchor="mm")
        elif kind == "kassa":
            d.rectangle([x0, y, xm, y2], fill=spec[3], outline=line, width=S)
            d.rectangle([xm, y, x1, y2], fill="white", outline=line, width=S)
            d.text(((x0 + xm) // 2, (y + y2) // 2), spec[1], font=f_b, fill="black", anchor="mm")
        elif kind == "key":
            d.rectangle([x0, y, xm, y2], fill=C_KEY, outline=line, width=S)
            d.rectangle([xm, y, x1, y2], fill=spec[3], outline=line, width=S)
            d.text(((x0 + xm) // 2, (y + y2) // 2), spec[1], font=f_b, fill="black", anchor="mm")
            d.text(((xm + x1) // 2, (y + y2) // 2), num(spec[2], always=True), font=f_r, fill="black", anchor="mm")
        elif kind == "item":
            d.rectangle([x0, y, xm, y2], fill=C_ITEM, outline=line, width=S)
            d.rectangle([xm, y, x1, y2], fill="white", outline=line, width=S)
            d.text((x0 + 6 * S, (y + y2) // 2), spec[1], font=f_r, fill="black", anchor="lm")
            d.text(((xm + x1) // 2, (y + y2) // 2),
                   num(int(row.get(spec[2], 0)), dash=(spec[2] == "bank")),
                   font=f_r, fill="black", anchor="mm")
        else:  # spacer
            d.rectangle([x0, y, xm, y2], fill="white", outline=line, width=S)
            d.rectangle([xm, y, x1, y2], fill="white", outline=line, width=S)
        y = y2

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
