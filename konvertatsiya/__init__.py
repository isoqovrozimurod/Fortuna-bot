"""
Konvertatsiya moduli (shaxsiy chatda hamma uchun ochiq).  Kirish: /konvertatsiya

  menu.py        /konvertatsiya, menyu, bekor qilish
  pdf_qilish.py  📄 rasm/albom/Word/Excel/PowerPoint/PDF -> bitta yoki alohida PDF
  pdf_bolish.py  ✂️ PDF ni sahifa/oraliq bo'yicha bo'laklash
  common.py      umumiy: lock, yuklab olish, yuborish (1 / albom / ZIP)
  imaging.py     rasm -> PDF (Pillow)
  office.py      Word/Excel/PPT -> PDF (LibreOffice, serverda o'rnatilgan bo'lishi kerak)
  pdftools.py    PDF birlashtirish/bo'lish (pypdf)
  registry.py    vositalar ro'yxati (menyu shundan quriladi)

Yangi vosita: yangi modul yozing (o'z Router + FSM), registry.register(Tool(...)) chaqiring
va quyidagi import qatoriga modul nomini qo'shing. Boshqa fayllarga tegish shart emas.

main.py:  from konvertatsiya import router as konv_router
"""
from aiogram import Router

from . import menu, pdf_bolish, pdf_qilish  # noqa: F401  (import vositalarni ro'yxatga oladi)
from .registry import REGISTRY

router = Router(name="konvertatsiya")
router.include_router(menu.router)
for _tool in sorted(REGISTRY.values(), key=lambda t: t.order):
    router.include_router(_tool.router)

__all__ = ["router"]
