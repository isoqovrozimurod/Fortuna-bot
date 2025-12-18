# 💻 GitHub'dagi `kredit_analiz.js` skriptini brauzer konsolida ishga tushurish

Agar siz sahifadagi jadval ma'lumotlari asosida **kreditlar statistik tahlilini** amalga oshirmoqchi bo‘lsangiz, quyidagi ko‘rsatmalarga amal qilib, GitHub'dagi skriptni brauzer konsoli orqali yuklab olib ishlatishingiz mumkin.

---

## 📁 1. Skript manzili

Quyidagi havola orqali JavaScript faylga kirishingiz mumkin:

🔗 [`kredit_analiz.js`](https://raw.githubusercontent.com/isoqovrozimurod/Fortuna-bot/main/konveyer/kredit_analiz.js) (RAW format)

---

## 🧪 2. Konsolda ishga tushirish

### 🖥️ Qadamlar:

1. Kerakli sahifani oching (masalan, `table` mavjud bo‘lgan tizim sahifasi).
2. Jadvalda kerakli **filtrlash yoki saralash** ishlarini bajaring.
3. **F12** tugmasini bosing (yoki sichqonchaning o‘ng tugmasi → `Inspect` → `Console`).
4. `Console` bo‘limiga quyidagi kodni to‘liq kiriting va `Enter` tugmasini bosing:

```js
(async () => {
  const url = 'https://raw.githubusercontent.com/isoqovrozimurod/Fortuna-bot/main/kredit_analiz.js';

  try {
    console.log('⏳ GitHub fayli yuklanmoqda…');
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Yuklab bo‘lmadi. Status: ${res.status}`);
    const script = await res.text();
    console.log('✅ Fayl yuklandi. Kod ishga tushirilmoqda...');
    eval(script);
  } catch (err) {
    console.error('❌ Xato:', err);
  }
})();
```
