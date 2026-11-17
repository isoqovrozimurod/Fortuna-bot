-- Kassa hisoboti jadvallari (Supabase -> SQL Editor'da BIR MARTA ishga tushiring)
-- Qoldiq va jami summalar BAZANING O'ZIDA hisoblanadi (generated column),
-- shuning uchun ular hech qachon kiritilgan summalarga zid bo'lib qolmaydi.

create table if not exists public.kassa_hisobot (
  sana              date        primary key,           -- kuniga bitta hisobot
  kun_boshiga       bigint      not null check (kun_boshiga >= 0),
  mijoz_tushum      bigint      not null default 0 check (mijoz_tushum >= 0),
  bank              bigint      not null default 0 check (bank >= 0),
  boshqa_filialdan  bigint      not null default 0 check (boshqa_filialdan >= 0),
  qarz_olindi       bigint      not null default 0 check (qarz_olindi >= 0),
  berilgan_kredit   bigint      not null default 0 check (berilgan_kredit >= 0),
  oziq_ovqat        bigint      not null default 0 check (oziq_ovqat >= 0),
  boshqa_filialga   bigint      not null default 0 check (boshqa_filialga >= 0),
  qarz_berildi      bigint      not null default 0 check (qarz_berildi >= 0),

  jami_tushum bigint generated always as
    (kun_boshiga + mijoz_tushum + bank + boshqa_filialdan + qarz_olindi) stored,
  jami_chiqim bigint generated always as
    (berilgan_kredit + oziq_ovqat + boshqa_filialga + qarz_berildi) stored,
  qoldiq bigint generated always as
    (kun_boshiga + mijoz_tushum + bank + boshqa_filialdan + qarz_olindi
     - berilgan_kredit - oziq_ovqat - boshqa_filialga - qarz_berildi) stored,

  kun_boshiga_qolda boolean     not null default false, -- kechagi qoldiqdan farqli, qo'lda kiritilgan
  versiya           integer     not null default 1,
  status            text        not null default 'saqlangan'
                    check (status in ('saqlangan', 'yuborilgan')),
  kiritgan          bigint      not null,               -- Telegram ID
  yaratilgan        timestamptz not null default now(),
  yangilangan       timestamptz not null default now(),
  yuborilgan_vaqt   timestamptz,

  constraint qoldiq_manfiy_emas check (
    kun_boshiga + mijoz_tushum + bank + boshqa_filialdan + qarz_olindi
    - berilgan_kredit - oziq_ovqat - boshqa_filialga - qarz_berildi >= 0)
);

-- Har bir o'zgarish izi (kim, qachon, nima edi -> nima bo'ldi)
create table if not exists public.kassa_log (
  id    bigint generated always as identity primary key,
  sana  date        not null,
  amal  text        not null,      -- 'yangi' | 'yangilash'
  eski  jsonb,
  yangi jsonb,
  kim   bigint      not null,
  vaqt  timestamptz not null default now()
);

-- MUHIM: RLS yoqiladi va hech qanday policy berilmaydi.
-- Natijada ANON kalit bu jadvallarni o'qiy ham, yoza ham olmaydi;
-- faqat bot (service_role kaliti) kira oladi.
alter table public.kassa_hisobot enable row level security;
alter table public.kassa_log     enable row level security;
