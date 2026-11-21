"""
Kassa moduli — kunlik kassa hisoboti (Fortuna Biznes, G'allaorol filiali).

Oqim (faqat ruxsat etilgan ID'lar: ADMIN_ID va MY_ID):
  /kassa   -> sana -> rejim (Asosiy / Hammasini kiritish)
           -> kun boshiga qoldiq (kechagi hisobotdan, tasdiqlanadi)
           -> summalar -> tasdiqlash -> bazaga saqlash -> hisobot RASMI (sizga)
           -> [Boshliqqa yuborish] tugmasi -> rasm boshliqqa ketadi
  /hisobot [sana]   -> saqlangan hisobot rasmi   (boshliq ham: faqat YUBORILGANlar)
  /oy [oy.yyyy]     -> oylik natija              (boshliq ham: faqat YUBORILGANlar)
  /bekor            -> kiritishni bekor qilish

Fayllar:
  config.py     sozlamalar, hisobot qatorlari (FIELDS), ruxsat filtri
  logic.py      hisob-kitob, summa/sana o'qish, formatlash
  db.py         Supabase (jadval: sql/kassa_schema.sql)
  render.py     hisobot rasmi (Pillow)
  sheets.py     Google Sheets nusxa (ixtiyoriy)
  keyboards.py  inline tugmalar
  handlers.py   buyruqlar va tugmalar (router)

main.py'da:  from kassa import router as kassa_router
"""
from aiogram import Router

from .handlers import read_router, router as _kassir_router

# /hisobot va /oy — kassir VA boshliq (faqat yuborilganlar); qolganlari — faqat kassir.
router = Router(name="kassa")
router.include_router(read_router)
router.include_router(_kassir_router)

__all__ = ["router"]
