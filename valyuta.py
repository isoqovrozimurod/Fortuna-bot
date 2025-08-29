import datetime
import aiohttp
import re
import io
import matplotlib.pyplot as plt
from aiogram import Router, types, F
from aiogram.types import FSInputFile

router = Router()

ANIQ_URL = "https://aniq.uz/uz/valyuta-kurslari"

# Kerakli banklar ro‘yxati
TARGET_BANKS = {
    "Agrobank": "Agro Bank",
    "Mikrokreditbank": "Mikrokreditbank",
    "Xalq banki": "Xalq Banki",
    "Hamkorbank": "Hamkorbank",
    "Aloqabank": "AloqaBank",
    "Trastbank": "Trastbank",
    "Turon bank": "Turon Bank",
    "Ipoteka bank": "Ipoteka Bank",
    "NBU": "NBU",
    "Asaka bank": "Asaka Bank",
}

@router.message(F.text == "/valyuta")
async def valyuta_handler(msg: types.Message):
    today = datetime.date.today().strftime("%d.%m.%Y")

    try:
        async with aiohttp.ClientSession() as sess:
            resp = await sess.get(ANIQ_URL)
            html = await resp.text()
    except Exception as e:
        await msg.answer("❌ Kurslarni olishda xatolik yuz berdi.")
        print("fetch error:", e)
        return

    banks = []
    for bank_key, bank_name in TARGET_BANKS.items():
        pattern = rf"{re.escape(bank_name)}.*?(\d{{4,6}})[^\d]+(\d{{4,6}})"
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            buy = int(match.group(1))
            sell = int(match.group(2))
            banks.append((bank_key, buy, sell))
        else:
            print(f"⚠️ Ma'lumot topilmadi: {bank_name}")

    if not banks:
        await msg.answer("Banklar bo'yicha ma'lumot topilmadi.")
        return

    # Jadvalni chizish
    fig, ax = plt.subplots(figsize=(8, len(banks)*0.4 + 1.05))
    ax.axis('off')

    # Sarlavha (Title)
    ax.set_title(f"Banklar bo‘yicha USD kurslari ({today})", fontsize=14, fontweight='bold', pad=8)

    # Qo‘shimcha ogohlantirish matni
    ax.text(0.5, 0.95, "Eslatma! Bizda faqat Milliy valyuta(so'm) orqali xizmat ko‘rsatiladi!\nMa'lumotlar 9⁰⁰ dan keyin yangilanadi",
            ha='center', va='center', transform=ax.transAxes,
            fontsize=10, color='red', fontweight='bold')

    # Jadval sarlavhalari va ma'lumotlar
    columns = ["Bank nomi", "Sotib olish (so'm)", "Sotish (so'm)"]
    data = []
    for bank_key, buy, sell in banks:
        data.append([bank_key, f"{buy:,}".replace(",", " "), f"{sell:,}".replace(",", " ")])

    table = ax.table(cellText=data, colLabels=columns, cellLoc='center', loc='center',
                     colColours=["#A9D0F5"]*3)
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1.4)

    # Rasmni buferga yozamiz
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)

    # Faylga saqlaymiz
    with open("valyuta_kurslari.png", "wb") as f:
        f.write(buf.getbuffer())

    photo = FSInputFile("valyuta_kurslari.png")
    await msg.answer_photo(photo=photo)
