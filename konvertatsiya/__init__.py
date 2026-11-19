"""
Konvertatsiya moduli — fayllarni bir formatdan boshqasiga o'tkazish.
Hamma foydalanuvchi uchun ochiq (shaxsiy chatda).

Oqim:
  [🔄 Konvertatsiya] yoki /konvertatsiya
     -> menyu (har bir konvertor — alohida tugma)
     -> tugma tanlanadi -> fayl yuboriladi
     -> fayl nomi so'raladi (yozish yoki [⏭ O'tkazib yuborish])
     -> tayyor fayl jo'natiladi

Fayllar:
  registry.py   Converter tavsifi va ro'yxat (YANGI KONVERTOR SHU YERGA ULANADI)
  image_pdf.py  Rasm -> PDF (Pillow)
  names.py      fayl nomini tozalash
  keyboards.py  inline tugmalar (prefiks: 'konv:')
  handlers.py   umumiy FSM oqimi (konvertorga bog'liq emas)

Yangi konvertor qo'shish (masalan PDF -> rasm):
  1) konvertatsiya/pdf_rasm.py yarating: extract(), convert() va
     register(Converter(...)) chaqiring.
  2) konvertatsiya/handlers.py oxiridagi import qatoriga modulni qo'shing.
  handlers.py va keyboards.py ga TEGISH SHART EMAS.

main.py'da:  from konvertatsiya import router as konv_router
"""
from .handlers import router

__all__ = ["router"]
