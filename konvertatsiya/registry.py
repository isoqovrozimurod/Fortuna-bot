"""
Konvertatsiya vositalari reyestri. Menyu shu ro'yxatdan quriladi.

Yangi vosita qo'shish:
  1) konvertatsiya/yangi_vosita.py: o'z Router'i va FSM'i bilan yoziladi,
     kirish tugmasi:  @router.callback_query(F.data == "konv:pick:<kalit>")
  2) shu faylda  register(Tool(key="<kalit>", button="...", router=router))
  3) konvertatsiya/__init__.py dagi TOOL_MODULES ro'yxatiga modul nomi qo'shiladi.
Menyu, umumiy yordamchilar (common.py) va boshqa vositalarga tegish shart emas.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Router


@dataclass(frozen=True)
class Tool:
    key: str          # "pdf_qilish" — callback: konv:pick:<key>
    button: str       # menyudagi tugma matni
    router: Router
    order: int = 100  # menyudagi tartib (kichigi yuqorida)


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.key in REGISTRY:
        raise ValueError(f"Vosita kaliti takrorlandi: {tool.key}")
    REGISTRY[tool.key] = tool
    return tool
