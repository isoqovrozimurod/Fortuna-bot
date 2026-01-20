# Filiallar Xaritasi Integratsiyasi

## O'rnatish Ko'chami

### 1. Supabase Jadvalini Yaratish

Supabase SQL Editor-ga kirib, quyidagi buyruqni ishga tushiring:

```sql
CREATE TABLE IF NOT EXISTS branches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  address text NOT NULL,
  phone text NOT NULL,
  latitude numeric NOT NULL,
  longitude numeric NOT NULL,
  working_hours text DEFAULT '09:00 - 18:00',
  description text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

ALTER TABLE branches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Hammasi filiallari ko'rishi mumkin"
  ON branches
  FOR SELECT
  USING (true);
```

### 2. Requirements O'rnatish

```bash
pip install supabase geopy
```

### 3. Bot Komandalarini Ishlatish

#### Foydalanuvchilar uchun:
- `/filiallar` - Filiallar menyu
- Asosiy menyu -> "📍 Filiallar" tugmasi

#### Admin uchun:
- `/init_branches` - Misoliy filiallarni o'rnatish

## Funksiyalar

### 1. Filiallar Xaritasi Ko'rish
- Barcha filiallarning ro'yxati
- Har bir filialga direct Google Maps link
- Telefon raqamiga direct call link

### 2. Yaqin Filialni Topish
- Foydalanuvchining joylashuvini so'rash
- GPS koordinatalardan eng yaqin filialni hisoblash
- Masofani km da ko'rsatish
- Direct Google Maps va call linklar

### 3. Barcha Filiallar
- To'liq filiallar ro'yxati
- Manzil, telefon, ish vaqti, tavsif

## Misoliy Filiallar

Xozirda 3 ta misoliy filial o'rnatilgan:
1. **Gallaorol Filiali** - G'allaorol tumani
2. **Markaз Filiali** - Tashkent shahri
3. **Samarqand Filiali** - Samarqand shahri

## Filiallar Qo'shish (Admin Panel)

Telegramda:
```
/init_branches
```

Supabase-ga direct qo'shish:
```sql
INSERT INTO branches (name, address, phone, latitude, longitude, working_hours, description)
VALUES (
  'Filial nomi',
  'Manzil',
  '+998XXXXXXXXX',
  40.1234,  -- Latitude
  69.5678,  -- Longitude
  '09:00 - 18:00',
  'Tavsif'
);
```

## Texnik Detallar

### Fayllar
- `filiallar.py` - Asosiy modul
- `config.py` - Supabase konfiguratsiyasi
- `main.py` - Router integratsiyasi
- `buyruqlar.py` - Bot komandalar

### API'lar
- **Google Maps** - Xarita linklar (API key kerak emas - URL-based)
- **Geopy** - Masofani hisoblash algoritmi
- **Supabase** - Ma'lumotbaza

### Xavfsizlik
- RLS yoqilgan - Barcha foydalanuvchilar filiallarni ko'rishi mumkin
- Filiallar ma'lumotlari public (hech qanday sirli ma'lumot yo'q)
