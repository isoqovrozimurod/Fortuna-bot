"""
Reklama Nazorat Tizimi — Bot qismi
Apps Script: nazorat xabarlari, triggerlar
Bot: screenshot hisoblash, reyting, statistika
"""

import os
import base64
import json
import asyncio
import logging
import contextlib
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import gspread
from google.oauth2.service_account import Credentials

from aiogram import Router, Bot, F
from aiogram.types import (
    Message, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER, Command
from aiogram.exceptions import TelegramForbiddenError


# ─── SOZLAMALAR ───────────────────────────────────────────────────────────────

router = Router()
logger = logging.getLogger(__name__)
TZ     = ZoneInfo("Asia/Tashkent")

def now_tz()   -> datetime: return datetime.now(TZ)
def today_str() -> str:     return now_tz().strftime("%d.%m.%Y")

GROUP_ID       = int(os.getenv("GROUP_ID", "0"))
ADMIN_ID       = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_LINK   = "https://t.me/FORTUNABIZNES_GALLAOROL"
SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "sub_adminlar"
USER_SHEET     = "user"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
BASE_COLS    = 8   # T/r, Telegram ID, Username, Ism, Familiya, Telefon, Sana, Holati
DAILY_TARGET = 2   # Kunlik maqsad (screenshot soni)


# ─── PROGRESS BAR ─────────────────────────────────────────────────────────────

def progress_bar(count: int, target: int, width: int = 10) -> str:
    """count/target nisbatini rangli progress bar sifatida ko'rsatadi."""
    ratio = min(count / target, 1.0) if target > 0 else 0
    fill  = round(ratio * width)
    color = "🟩" if ratio >= 1.0 else "🟨" if ratio >= 0.5 else "🟥"
    return color * fill + "⬜" * (width - fill)


def percent_bar(pct: int, width: int = 10) -> str:
    """Foiz asosida rangli progress bar."""
    fill  = min(round(pct / 100 * width), width)
    color = "🟩" if pct >= 100 else "🟨" if pct >= 50 else "🟥"
    return color * fill + "⬜" * (width - fill)


# ─── SHEETS ULANISH ───────────────────────────────────────────────────────────

_gc: gspread.Client | None = None


def _get_gc() -> gspread.Client:
    """gspread clientini yaratadi. Xato bo'lsa qayta yaratadi."""
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc


def _reset_gc() -> None:
    """Sheets ulanishini qayta o'rnatadi (token xatolarida)."""
    global _gc
    _gc = None


def _ws() -> gspread.Worksheet:
    """sub_adminlar varaqini qaytaradi. Yo'q bo'lsa yaratadi."""
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(SUBADMIN_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUBADMIN_SHEET, rows="100", cols="50")
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
                       "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
        return ws


def _user_ws() -> gspread.Worksheet:
    """user varaqini qaytaradi."""
    return _get_gc().open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)


def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    """
    2-ustunda user_id ni qidiradi. Topsa qator raqamini (1-based) qaytaradi.
    "588979280", "588979280.0", 588979280 — barcha formatlarni qabul qiladi.
    Sheets ba'zan integer larni float sifatida saqlashi mumkin.
    """
    for i, v in enumerate(ws.col_values(2), start=1):
        v_str = str(v).strip()
        if not v_str:
            continue
        # To'g'ridan string taqqoslash
        if v_str == str(user_id):
            return i
        # Float format: "588979280.0" → int → taqqoslash
        try:
            if int(float(v_str)) == user_id:
                return i
        except (ValueError, TypeError):
            pass
    return None


def _col_letter(n: int) -> str:
    """Ustun raqamini harfga aylantiradi: 1→A, 27→AA."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    """
    Berilgan sana ustunini topadi yoki yaratadi.
    Har safar Sheets dan fresh o'qiydi — kesh emas.

    MUHIM: yangi ustun yaratilganda katak MAJBURIY matn formatida
    ("@") belgilanadi. Aks holda Google Sheets "17.07.2026" kabi
    matnni sana deb tanib, uni serial-sanaga aylantiradi va keyin
    jadval lokalizatsiyasiga qarab (masalan "7/17/2026") ko'rsatishi
    mumkin. Natijada datetime.strptime("%d.%m.%Y") mos kelmay, ustun
    valid_dates ro'yxatidan butunlay tushib qoladi — va statistikada
    HAMMA uchun 0 ko'rinadi.
    """
    headers = ws.row_values(1)
    for i, h in enumerate(headers):
        if str(h).strip() == date_str:
            return i + 1
    # Ustun yo'q — yangi ustun yaratamiz
    new_col = len(headers) + 1
    cell    = ws.cell(1, new_col)
    ws.format(cell.address, {"numberFormat": {"type": "TEXT"}})
    ws.update_cell(1, new_col, date_str)
    return new_col


def fix_date_header_formats_sync() -> int:
    """
    BIR MARTALIK TUZATISH.
    Agar sana ustunlari avval Apps Script yoki eski kod tomonidan
    matn-format majburlanmasdan yaratilgan bo'lsa, Sheets ularni
    avtomatik sanaga aylantirib qo'ygan bo'lishi mumkin. Bu funksiya
    barcha BASE_COLS dan keyingi ustunlarni qayta matn formatiga
    o'tkazadi va sarlavhani "dd.MM.yyyy" ko'rinishida qayta yozadi.
    Faqat bitta marta ishga tushirish kifoya.
    """
    sheet   = _ws()
    headers = sheet.row_values(1)
    fixed   = 0
    for i, h in enumerate(headers[BASE_COLS:], start=BASE_COLS + 1):
        raw = str(h).strip()
        if not raw:
            continue
        # Sheets Date obyektini formatlagan bo'lsa, turli formatlarni sinaymiz
        normalized = None
        for fmt in ("%d.%m.%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y", "%b %d, %Y"):
            try:
                dt = datetime.strptime(raw, fmt)
                normalized = dt.strftime("%d.%m.%Y")
                break
            except ValueError:
                continue
        if normalized and normalized != raw:
            cell = sheet.cell(1, i)
            sheet.format(cell.address, {"numberFormat": {"type": "TEXT"}})
            sheet.update_cell(1, i, normalized)
            fixed += 1
    return fixed


def _safe_records(ws: gspread.Worksheet) -> list[dict]:
    """
    get_all_records() dublikat sarlavhada xato beradi.
    Bu funksiya get_all_values() dan o'zimiz dict yasaymiz.
    Sarlavhalar strip() qilinadi — whitespace muammosi yo'q.
    """
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return []
    raw_headers = all_vals[0]
    result      = []
    for row in all_vals[1:]:
        # Bo'sh qatorlarni o'tkazib yuboramiz
        if not any(str(c).strip() for c in row[:8]):
            continue
        # Qisqa qatorlarni sarlavha uzunligiga tenglashtiramiz
        padded = row + [""] * max(0, len(raw_headers) - len(row))
        rec    = {}
        for i, h in enumerate(raw_headers):
            key = str(h).strip()
            if key:
                rec[key] = padded[i] if i < len(padded) else ""
        result.append(rec)
    return result


def _cleanup_duplicate_cols_sync_inner(sheet: gspread.Worksheet) -> int:
    """
    Bir xil nomdagi ustunlarni topadi.
    Dublikat ustundagi qiymatlarni birinchisiga qo'shadi va o'chiradi.
    """
    headers = sheet.row_values(1)
    seen    = {}
    removed = 0
    for i, h in enumerate(headers):
        h_clean = str(h).strip()
        if not h_clean:
            continue
        if h_clean in seen:
            first_col = seen[h_clean]
            dupe_col  = i + 1
            all_vals  = sheet.get_all_values()
            # Dublikat ustundagi qiymatlarni birinchi ustunga qo'shamiz
            for row_i, row in enumerate(all_vals[1:], start=2):
                first_val = int(row[first_col - 1]) if len(row) >= first_col and str(row[first_col - 1]).strip().isdigit() else 0
                dupe_val  = int(row[dupe_col  - 1]) if len(row) >= dupe_col  and str(row[dupe_col  - 1]).strip().isdigit() else 0
                if dupe_val > 0:
                    sheet.update_cell(row_i, first_col, first_val + dupe_val)
            # Dublikat ustunni tozalaymiz
            last_row = len(all_vals)
            if last_row > 0:
                sheet.batch_clear([f"{_col_letter(dupe_col)}1:{_col_letter(dupe_col)}{last_row}"])
            removed += 1
        else:
            seen[h_clean] = i + 1
    return removed


def _cleanup_duplicate_cols_sync() -> int:
    """sub_adminlar varaqidagi dublikat ustunlarni tozalaydi."""
    return _cleanup_duplicate_cols_sync_inner(_ws())


# ─── LOCAL KESH ───────────────────────────────────────────────────────────────
# Kesh faqat tezlik uchun. Bot restart bo'lsa tozalanadi.
# Asosiy manba doim Sheets hisoblanadi.

_local_counts: dict[int, dict]   = {}   # {user_id: {"date": "dd.mm.yyyy", "count": N}}
_seen_files:   dict[int, dict]   = {}   # {user_id: {"date": ..., "files": set()}}
_user_locks:   dict[int, asyncio.Lock] = {}   # Per-user lock (race condition uchun)
_last_reply_msgs: dict[int, int] = {}   # {user_id: message_id} — oxirgi bot javob

_registering: set[int] = set()
_reg_lock     = asyncio.Lock()


def _get_user_lock(user_id: int) -> asyncio.Lock:
    """Har bir user uchun alohida asyncio.Lock qaytaradi."""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _local_get(user_id: int) -> int:
    """
    Bugungi kesh qiymatini qaytaradi.
    -1 = keshda yo'q, Sheets dan o'qish kerak.
    """
    data = _local_counts.get(user_id)
    if data and data.get("date") == today_str():
        return data.get("count", 0)
    return -1


def _local_set(user_id: int, count: int) -> None:
    """Bugungi kesh qiymatini saqlaydi."""
    _local_counts[user_id] = {"date": today_str(), "count": count}


def _is_duplicate(user_id: int, file_unique_id: str) -> bool:
    """Bugun shu fayl yuborilgan-yuborilmaganini tekshiradi."""
    today = today_str()
    rec   = _seen_files.get(user_id)
    if rec is None or rec.get("date") != today:
        _seen_files[user_id] = {"date": today, "files": set()}
    return file_unique_id in _seen_files[user_id]["files"]


def _mark_seen(user_id: int, file_unique_id: str) -> None:
    """Faylni ko'rilgan deb belgilaydi."""
    today = today_str()
    rec   = _seen_files.get(user_id)
    if rec is None or rec.get("date") != today:
        _seen_files[user_id] = {"date": today, "files": set()}
    _seen_files[user_id]["files"].add(file_unique_id)


def _increment_sheet_sync(user_id: int) -> int:
    """
    Sheets dan bugungi qiymatni o'qiydi, +1 qo'shib yozadi.
    Yangi qiymatni qaytaradi. Xato bo'lsa 0 qaytaradi.
    Ulanish xatosida _gc ni qayta o'rnatadi.
    """
    try:
        sheet    = _ws()
        date_col = _get_date_col(sheet, today_str())
        row      = _find_row(sheet, user_id)
        if not row:
            # Foydalanuvchi sub_adminlar da yo'q — jiddiy xato
            logger.error(
                f"[SHEETS] User {user_id} sub_adminlar da topilmadi! "
                f"Screenshot hisoblanmadi. /start_register buyrug'ini yuboring."
            )
            return 0
        val     = sheet.cell(row, date_col).value
        current = int(val) if val and str(val).strip().isdigit() else 0
        next_   = current + 1
        sheet.update_cell(row, date_col, next_)
        logger.debug(f"[SHEETS] User {user_id}: {today_str()} → {next_}")
        return next_
    except Exception as e:
        logger.error(f"[SHEETS] Increment xato (user={user_id}): {e}")
        _reset_gc()   # Keyingi urinishda yangi ulanish
        return 0


# ─── RO'YXATGA OLISH ──────────────────────────────────────────────────────────

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    """
    Foydalanuvchini sub_adminlar ga qo'shadi.
    Allaqachon bor bo'lsa False qaytaradi.
    """
    sheet = _ws()
    if _find_row(sheet, user_id):
        return False
    parts       = (full_name or "").split(" ", 1)
    ism         = parts[0]
    familiya    = parts[1] if len(parts) > 1 else ""
    uname       = f"@{username}" if username else ""
    sana        = now_tz().strftime("%Y-%m-%d %H:%M")
    all_vals    = sheet.get_all_values()
    headers     = all_vals[0] if all_vals else []
    valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
    row         = [str(valid_count + 1), str(user_id), uname, ism, familiya, "", sana, "Faol"]
    while len(row) < len(headers):
        row.append("")
    sheet.append_row(row, value_input_option="RAW")
    logger.info(f"Yangi sub_admin: {full_name} ({user_id})")
    return True


def _set_status_sync(user_id: int, status: str) -> None:
    """Foydalanuvchi Holati ustunini yangilaydi."""
    sheet = _ws()
    row   = _find_row(sheet, user_id)
    if row:
        sheet.update_cell(row, 8, status)


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    """Foydalanuvchini ro'yxatga oladi (race condition xavfsiz)."""
    async with _reg_lock:
        if user_id in _registering:
            return False
        _registering.add(user_id)
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _register_sync, user_id, full_name, username)
    finally:
        async with _reg_lock:
            _registering.discard(user_id)


async def set_status(user_id: int, status: str) -> None:
    """Foydalanuvchi statusini yangilaydi."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _set_status_sync, user_id, status)


# ─── GURUH HANDLERLARI ────────────────────────────────────────────────────────

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_join(event: ChatMemberUpdated):
    """Guruhga yangi a'zo qo'shilganda ro'yxatga oladi."""
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await register_user(u.id, u.full_name or "", u.username or "")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_leave(event: ChatMemberUpdated):
    """A'zo guruhdan chiqqanda statusini o'zgartiradi."""
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await set_status(u.id, "Chiqib ketdi")


@router.message(
    F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0),
    F.photo | F.document,
)
async def handle_media(message: Message):
    """
    Guruhga yuborilgan rasm/hujjatni hisoblaydi.
    Rasmlar: screenshot sifatida qabul qilinadi.
    Rasm bo'lmagan hujjatlar: faqat ro'yxatga olinadi.
    """
    if message.from_user is None or message.from_user.is_bot:
        return

    # Rasm bo'lmagan hujjat — faqat ro'yxatga olamiz
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        with contextlib.suppress(Exception):
            await register_user(
                message.from_user.id,
                message.from_user.full_name or "",
                message.from_user.username or "",
            )
        return

    u = message.from_user
    with contextlib.suppress(Exception):
        await register_user(u.id, u.full_name or "", u.username or "")

    # Dublikat tekshiruv
    file_uid = message.photo[-1].file_unique_id if message.photo else message.document.file_unique_id
    if _is_duplicate(u.id, file_uid):
        with contextlib.suppress(Exception):
            await message.reply(
                "⚠️ <b>Bu rasmni bugun allaqachon yuborgansiz!</b>\n"
                "Yangi reklama screenshotini yuboring.",
                parse_mode="HTML",
            )
        return
    _mark_seen(u.id, file_uid)

    # Hisoblash — per-user lock bilan race condition oldini olamiz
    loop = asyncio.get_running_loop()
    async with _get_user_lock(u.id):
        cached = _local_get(u.id)
        if cached >= 0:
            # Keshda bor — ustiga +1 qo'shamiz, Sheets ga ham yozamiz
            count = cached + 1
            _local_set(u.id, count)
            await loop.run_in_executor(None, _increment_sheet_sync, u.id)
        else:
            # Keshda yo'q — Sheets dan o'qib +1 (increment_sheet qaytaradi)
            count = await loop.run_in_executor(None, _increment_sheet_sync, u.id)
            _local_set(u.id, count)

    # Javob matni
    bar   = progress_bar(count, DAILY_TARGET)
    emoji = "📸" if count == 1 else "✅" if count == 2 else "🔥"
    text  = f"{emoji} <b>{u.full_name}</b>\n{bar} <b>{count}/{DAILY_TARGET}</b>"

    if count == DAILY_TARGET:
        msg = random.choice([
            "✦ Tizim qayd etdi: kunlik vazifa bajarildi. Faoliyat hisobga olindi.",
            "✦ Monitoring tasdiqladi: 2/2. Siz kuzatuv tizimida yashil holatdasiz.",
            "✦ Nazorat tizimi: reja yopildi. Xodim faoliyati — normada.",
            "✦ Tizim hisobi: bugungi majburiyat bajarildi. Natija bazaga yozildi.",
        ])
        text += f"\n✅ <b>Kunlik reja bajarildi.</b>\n🤖 <i>{msg}</i>"

    elif count > DAILY_TARGET:
        msg = random.choice([
            "✦ Tizim qayd etdi: reja oshib ketdi. Qo'shimcha faoliyat hisobga olindi.",
            "✦ Monitoring: rejadan ortiq natija. Siz bugun tizimda lider holatdasiz.",
            f"✦ Nazorat tizimi: {count} ta screenshot — yuqori faollik. Oy reytingida hisoblanmoqda.",
            "✦ Tizim: kunlik norma oshib ketdi. Bunday xodimlar alohida e'tiborga olinadi.",
        ])
        text += f"\n🏆 <b>{count}-screenshot — rejadan oshib ketdingiz.</b>\n🤖 <i>{msg}</i>"

    else:
        remaining = DAILY_TARGET - count
        roast = random.choice([
            "⚡ Tizim ogohlantiradi: vazifa bajarilmagan. Holat — qizil.",
            "⚡ Nazorat tizimi: bugungi faollik nolda. Bu hisobotga tushadi.",
            "⚡ Monitoring: siz hali ro'yxatda ko'rinmayapsiz. Darhol harakat talab etiladi.",
            f"⚡ Tizim qayd etdi: {remaining} ta vazifa bajarilmagan. Vaqt — cheklangan.",
            "⚡ Diqqat: bajarilmagan vazifalar oy reytingida avtomatik hisoblanadi.",
            "⚡ Nazorat tizimi: faolsizlik aniqlandi. Keyingi tekshiruvda holat qayta baholanadi.",
        ])
        text += (
            f"\n⏳ Yana <b>{remaining} ta</b> kerak."
            f"\n🤖 <i>{roast}</i>"
            f"\n📌 {CHANNEL_LINK}"
        )

    # Avvalgi bot javobini o'chiramiz
    if u.id in _last_reply_msgs:
        with contextlib.suppress(Exception):
            await message.bot.delete_message(GROUP_ID, _last_reply_msgs[u.id])
        del _last_reply_msgs[u.id]

    with contextlib.suppress(Exception):
        sent = await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)
        _last_reply_msgs[u.id] = sent.message_id


@router.message(
    F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0),
    ~F.photo,
    ~F.document,
    # MUHIM: buyruqlarni FILTR DARAJASIDA chetlab o'tamiz.
    # Funksiya ichidagi "if text.startswith('/'): return" YETARLI EMAS —
    # aiogram uchun filtr mos kelib handler bir marta chaqirilgan zahoti
    # event "qayta ishlangan" deb hisoblanadi va keyingi handlerlarga
    # (jumladan Command("reklama_stat") kabi) umuman yetib bormaydi.
    # Shu sabab guruhdagi barcha buyruqlar javobsiz qolgan edi.
    F.func(lambda m: not (m.text or "").startswith("/")),
)
async def handle_text(message: Message):
    """Guruhga yozilgan (buyruq bo'lmagan) matn xabarida ham ro'yxatdan o'tkazadi."""
    if message.from_user is None or message.from_user.is_bot:
        return
    with contextlib.suppress(Exception):
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or "",
        )


# ─── QO'LDA RO'YXAT ───────────────────────────────────────────────────────────

@router.message(Command("start_register"))
async def cmd_start_register(message: Message):
    """Guruhga ro'yxatdan o'tish tugmasini yuboradi (faqat admin)."""
    if not (message.chat.id == GROUP_ID and message.from_user
            and message.from_user.id == ADMIN_ID):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ RO'YXATDAN O'TISH", callback_data="reg_me")]
    ])
    await message.bot.send_message(
        GROUP_ID,
        "📢 <b>DIQQAT!</b>\n\nBarcha xodimlar quyidagi tugmani bossin.\n\n👇 <b>Bosing:</b>",
        reply_markup=kb, parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data == "reg_me")
async def cb_reg_me(callback: CallbackQuery):
    """Foydalanuvchi tugmani bosganda ro'yxatga oladi."""
    u = callback.from_user
    try:
        is_new = await register_user(u.id, u.full_name or "", u.username or "")
        await callback.answer(
            "✅ Ro'yxatga olindingiz!" if is_new else "✅ Allaqachon bazadasiz.",
            show_alert=True,
        )
    except Exception:
        await callback.answer("❌ Xato. Qayta urinib ko'ring.", show_alert=True)


# ─── YORDAMCHI ────────────────────────────────────────────────────────────────

def _mention(uid: str, name: str) -> str:
    """Telegram mention linki yasaydi."""
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={uid}">{safe}</a>'


async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    """
    Uzun matnni 3800 belgili bo'laklarga bo'lib yuboradi.
    Telegram 4096 belgidan uzun xabar qabul qilmaydi.
    """
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML",
                                   disable_web_page_preview=True)
            break
        # Eng yaqin \n dan kesamiz — so'z o'rtasida kesilmasin
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML",
                               disable_web_page_preview=True)
        text = text[cut:].lstrip("\n")


# ─── STATISTIKA ───────────────────────────────────────────────────────────────

def _stats_sync(days: int) -> list[dict]:
    """
    Sheets dan so'nggi `days` kunlik statistikani hisoblaydi.

    MUHIM: bitta get_all_values() ishlatiladi.
    Avval row_values(1) + _safe_records() alohida chaqirilganda
    sarlavhalar strip() qilinmagan holda valid_dates ga kirar,
    lekin rec dict da stripped kalit bo'lardi.
    Natijada rec.get(d, 0) = 0 — barchada 0 ko'rinardi.
    """
    sheet    = _ws()
    all_vals = sheet.get_all_values()   # BITTA o'qish
    if len(all_vals) < 2:
        return []

    # Sarlavhalarni strip() qilamiz — whitespace muammosini oldini olamiz
    headers = [str(h).strip() for h in all_vals[0]]

    # So'nggi `days` kunlik sana ustunlarini topamiz
    cutoff = (now_tz() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    valid_dates = []
    for h in headers[BASE_COLS:]:
        if not h:
            continue
        try:
            dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
            if dt >= cutoff:
                valid_dates.append(h)
        except ValueError:
            pass

    today_s = today_str()
    result  = []

    for row in all_vals[1:]:
        # Bo'sh qatorlarni o'tkazib yuboramiz
        if not any(str(c).strip() for c in row[:8]):
            continue

        # Qisqa qatorni sarlavha uzunligiga tenglashtiramiz
        padded = row + [""] * max(0, len(headers) - len(row))

        # Dict yasaymiz: stripped kalit → qiymat
        # valid_dates ham stripped — ikkalasi mos keladi
        rec = {headers[i]: padded[i] for i in range(len(headers)) if headers[i]}

        if str(rec.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(rec.get("Telegram ID", "")).strip()
        if not tg_id:
            continue

        name = (
            f"{rec.get('Ism', '')} {rec.get('Familiya', '')}".strip()
            or "Noma'lum"
        )

        total = 0
        for d in valid_dates:
            v          = rec.get(d, "")
            from_sheet = int(v) if str(v).strip().isdigit() else 0

            # Bugungi kun uchun local cache ni ham hisobga olamiz
            if d == today_s:
                try:
                    from_local = _local_get(int(float(tg_id)))
                    if from_local > from_sheet:
                        from_sheet = from_local
                except (ValueError, TypeError):
                    pass

            total += from_sheet

        result.append({"id": tg_id, "name": name, "total": total})

    result.sort(key=lambda x: x["total"], reverse=True)
    return result


async def get_stats(days: int) -> list[dict]:
    """_stats_sync ni async wrapperda ishlatadi."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _stats_sync, days)


def _stat_text(stats: list[dict], label: str, days: int) -> str:
    """Statistikani progress bar ko'rinishida matn sifatida qaytaradi."""
    if not stats:
        return f"📊 <b>{label} statistika</b>\n\nMa'lumot yo'q."

    total_all    = sum(u["total"] for u in stats)
    ideal        = days * DAILY_TARGET   # Maksimal mumkin bo'lgan son
    max_possible = ideal * len(stats)
    overall_pct  = int(total_all / max_possible * 100) if max_possible else 0
    d_start      = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end        = now_tz().strftime("%d.%m.%Y")

    lines = [
        f"📊 <b>{label} statistika</b>",
        f"📅 {d_start} — {d_end}",
        f"👥 {len(stats)} xodim | 📸 Jami: {total_all} ta",
        f"{percent_bar(overall_pct)} {overall_pct}%",
        "➖➖➖➖➖➖➖➖➖➖",
    ]

    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(stats):
        pct   = int(u["total"] / ideal * 100) if ideal else 0
        bar   = progress_bar(u["total"], ideal)
        medal = medals[i] if i < 3 else f"{i + 1}."
        lines.append(
            f"\n{medal} {_mention(u['id'], u['name'])}\n"
            f"   {bar} <b>{u['total']}/{ideal}</b> ({pct}%)"
        )

    return "\n".join(lines)


def _stat_kb() -> InlineKeyboardMarkup:
    """Statistika klaviaturasi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Kunlik",   callback_data="stat_daily"),
            InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
            InlineKeyboardButton(text="🗓 Oylik",    callback_data="stat_monthly"),
        ],
        [
            InlineKeyboardButton(text="🏆 Reyting", callback_data="stat_rating"),
            InlineKeyboardButton(text="❌ Yopish",  callback_data="stat_close"),
        ],
    ])


@router.message(Command("reklama_stat"))
async def cmd_stat(message: Message, bot: Bot):
    """Statistika menyusini adminga shaxsan yuboradi."""
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    await bot.send_message(
        ADMIN_ID,
        "📊 <b>Reklama statistikasi</b>\n\nQaysi davrni ko'rmoqchisiz?",
        reply_markup=_stat_kb(), parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data.in_({"stat_daily", "stat_weekly", "stat_monthly",
                                    "stat_rating", "stat_close"}))
async def cb_stat(call: CallbackQuery):
    """Statistika tugmalarini qayta ishlaydi."""
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    if call.data == "stat_close":
        with contextlib.suppress(Exception):
            await call.message.delete()
        return

    if call.data == "stat_rating":
        await call.answer("⏳ Reyting hisoblanmoqda...")
        loop = asyncio.get_running_loop()
        with contextlib.suppress(Exception):
            await loop.run_in_executor(None, _cleanup_duplicate_cols_sync)
        try:
            text = await _build_rating_text(30)
            await call.message.edit_text(text, reply_markup=_stat_kb(), parse_mode="HTML")
        except Exception as e:
            with contextlib.suppress(Exception):
                await call.message.edit_text(f"❌ Xato: {e}", reply_markup=_stat_kb())
        return

    await call.answer("⏳ Hisoblanmoqda...")
    loop = asyncio.get_running_loop()
    with contextlib.suppress(Exception):
        await loop.run_in_executor(None, _cleanup_duplicate_cols_sync)

    days_map = {
        "stat_daily":   (1,  "Kunlik"),
        "stat_weekly":  (7,  "Haftalik"),
        "stat_monthly": (30, "Oylik"),
    }
    days, label = days_map[call.data]
    try:
        stats = await get_stats(days)
        await call.message.edit_text(
            _stat_text(stats, label, days),
            reply_markup=_stat_kb(), parse_mode="HTML",
        )
    except Exception as e:
        with contextlib.suppress(Exception):
            await call.message.edit_text(f"❌ Xato: {e}", reply_markup=_stat_kb())


# ─── REYTING TIZIMI ───────────────────────────────────────────────────────────

async def _build_rating_text(days: int = 30) -> str:
    """
    Oylik reyting matnini yaratadi.
    TOP-3 alohida ajratilgan, qolganlar oddiy ro'yxatda.
    """
    stats = await get_stats(days)
    if not stats:
        return "🏆 <b>Reyting</b>\n\nMa'lumot yo'q."

    ideal     = days * DAILY_TARGET
    total_all = sum(u["total"] for u in stats)
    d_start   = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end     = now_tz().strftime("%d.%m.%Y")
    medals    = ["🥇", "🥈", "🥉"]

    top_lines = []
    for i, u in enumerate(stats[:3]):
        pct   = int(u["total"] / ideal * 100) if ideal else 0
        bar   = progress_bar(u["total"], ideal)
        stars = "⭐" * (3 - i)
        top_lines.append(
            f"{medals[i]} {stars} {_mention(u['id'], u['name'])}\n"
            f"   {bar} <b>{u['total']}/{ideal}</b> ({pct}%)"
        )

    rest_lines = []
    for i, u in enumerate(stats[3:], start=4):
        pct = int(u["total"] / ideal * 100) if ideal else 0
        bar = progress_bar(u["total"], ideal)
        rest_lines.append(
            f"{i}. {_mention(u['id'], u['name'])}\n"
            f"   {bar} {u['total']}/{ideal} ({pct}%)"
        )

    text = (
        f"🏆 <b>OYLIK REYTING</b>\n"
        f"📅 {d_start} — {d_end}\n"
        f"👥 {len(stats)} xodim | 📸 Jami: {total_all} ta\n"
        f"➖➖➖➖➖➖➖➖➖➖\n\n"
        f"<b>🌟 TOP-3:</b>\n\n"
        + "\n\n".join(top_lines)
    )
    if rest_lines:
        text += "\n\n➖➖➖➖➖➖➖➖➖➖\n" + "\n\n".join(rest_lines)

    return text


@router.message(Command("reklama_reyting"))
async def cmd_reyting(message: Message, bot: Bot):
    """Oylik reytingni guruh va adminga yuboradi."""
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("⏳ Reyting hisoblanmoqda...")
    try:
        text = await _build_rating_text(30)
        await _send_long(bot, GROUP_ID, text)
        with contextlib.suppress(Exception):
            await bot.send_message(ADMIN_ID, text, parse_mode="HTML",
                                   disable_web_page_preview=True)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Xato: {e}")
    with contextlib.suppress(Exception):
        await message.delete()


async def announce_monthly_rating(bot: Bot) -> None:
    """
    Har oyning oxirida guruhga tantanali reyting e'lon qiladi.
    Apps Script yoki scheduler dan chaqiriladi.
    """
    stats = await get_stats(30)
    if not stats:
        return

    ideal   = 30 * DAILY_TARGET
    medals  = ["🥇", "🥈", "🥉"]
    d_end   = now_tz().strftime("%d.%m.%Y")
    d_start = (now_tz() - timedelta(days=29)).strftime("%d.%m.%Y")

    header = (
        f"🎉 <b>OY REYTINGI E'LON QILINMOQDA!</b>\n"
        f"📅 {d_start} — {d_end}\n\n"
        f"📸 Eng ko'p reklama tarqatgan xodimlar:\n\n"
    )

    top_lines = []
    for i, u in enumerate(stats[:3]):
        pct   = int(u["total"] / ideal * 100) if ideal else 0
        bar   = progress_bar(u["total"], ideal)
        congrats = (
            "🎊 <b>1-o'rin — CHAMPION!</b>" if i == 0 else
            "🎊 <b>2-o'rin — Ajoyib!</b>"   if i == 1 else
            "🎊 <b>3-o'rin — Zo'r!</b>"
        )
        top_lines.append(
            f"{medals[i]} {_mention(u['id'], u['name'])}\n"
            f"   {congrats}\n"
            f"   {bar} <b>{u['total']}/{ideal}</b> ({pct}%)"
        )

    footer = (
        "\n\n👏 <b>Barcha ishtirokchilar rahmat!</b>\n"
        f"Keyingi oy ham davom eting! 💪\n"
        f"📌 {CHANNEL_LINK}"
    )

    text = header + "\n\n".join(top_lines) + footer
    with contextlib.suppress(TelegramForbiddenError):
        await _send_long(bot, GROUP_ID, text)


# ─── QOLDA NAZORAT ────────────────────────────────────────────────────────────

async def check_screenshots(bot: Bot) -> None:
    """
    Hozirgi holatni guruhga yuboradi: kim bajargan, kim bajarmagan.
    Apps Script trigger yoki /reklama_tekshir dan chaqiriladi.
    """
    if GROUP_ID == 0:
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _safe_records(_ws()))
    except Exception as e:
        logger.error(f"check_screenshots Sheets xato: {e}")
        return

    if not data:
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID, "⚠️ sub_adminlar da hech kim yo'q!\n/start_register yuboring.")
        return

    today    = today_str()
    time_str = now_tz().strftime("%H:%M")
    debtors  = []
    done     = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw    = r.get(today, "")
        from_sheet = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            from_local = _local_get(int(tg_id))
            if from_local < 0:
                from_local = 0
        except (ValueError, TypeError):
            from_local = 0
        cnt  = max(from_sheet, from_local)
        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        (done if cnt >= DAILY_TARGET else debtors).append(
            {"id": tg_id, "name": name, "count": cnt})

    total    = len(done) + len(debtors)
    done_cnt = len(done)
    pct      = int(done_cnt / total * 100) if total else 0

    lines = [
        f"📊 <b>NAZORAT — {time_str}</b>",
        f"📅 {today}\n",
        f"{percent_bar(pct)} <b>{pct}%</b>",
        f"👥 Jami: {total}  ✅ {done_cnt}  ❌ {len(debtors)}",
    ]

    if done:
        lines.append("\n✅ <b>Bajardilar:</b>")
        for u in done:
            bar = progress_bar(u["count"], DAILY_TARGET)
            lines.append(
                f"{_mention(u['id'], u['name'])}\n"
                f"   {bar} <b>{u['count']}/{DAILY_TARGET}</b>"
            )

    if debtors:
        lines.append("\n❌ <b>Bajarmadi:</b>")
        for i, u in enumerate(debtors, 1):
            bar  = progress_bar(u["count"], DAILY_TARGET)
            note = f"yana {DAILY_TARGET - u['count']} ta ⚠️" if u["count"] > 0 else "hali boshlamadi 🚫"
            lines.append(
                f"{i}. {_mention(u['id'], u['name'])}\n"
                f"   {bar} {u['count']}/{DAILY_TARGET} — {note}"
            )
        lines += [
            "\n➖➖➖➖➖➖➖➖➖➖",
            "❗ <b>Reklama tarqatib screenshot yuborsin!</b>",
            f"📌 {CHANNEL_LINK}",
        ]

    try:
        await _send_long(bot, GROUP_ID, "\n".join(lines))
    except TelegramForbiddenError:
        logger.error("Guruhda yozish taqiqlangan!")

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>{time_str}</b>\n"
                f"{percent_bar(pct)} {pct}%\n"
                f"✅ {done_cnt}  ❌ {len(debtors)} / {total}",
                parse_mode="HTML",
            )


async def check_midday(bot: Bot) -> None:
    """
    12:00 tekshiruvi — faqat hali screenshot tashlamaganlar uchun ogohlantirish.
    """
    if GROUP_ID == 0:
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _safe_records(_ws()))
    except Exception as e:
        logger.error(f"check_midday Sheets xato: {e}")
        return

    today   = today_str()
    debtors = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw = r.get(today, "")
        cnt     = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            local = _local_get(int(tg_id))
            if local > cnt:
                cnt = local
        except (ValueError, TypeError):
            pass
        if cnt < DAILY_TARGET:
            name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
            debtors.append({"id": tg_id, "name": name, "count": cnt})

    if not debtors:
        return

    lines = [
        "⏰ <b>12:00 — Tushlik nazorati</b>",
        f"📅 {today}\n",
        f"❌ Hali screenshot tashlamaganlar: <b>{len(debtors)}</b> ta\n",
    ]
    for i, u in enumerate(debtors, 1):
        bar  = progress_bar(u["count"], DAILY_TARGET)
        note = f"{u['count']}/{DAILY_TARGET}" if u["count"] > 0 else "hali boshlamadi"
        lines.append(
            f"{i}. {_mention(u['id'], u['name'])}\n"
            f"   {bar} {note}"
        )
    lines += [
        "\n➖➖➖➖➖➖➖➖➖➖",
        "⚡ <b>Tizim ogohlantiradi: kunning yarmi o'tdi!</b>",
        f"📌 {CHANNEL_LINK}",
    ]

    with contextlib.suppress(TelegramForbiddenError):
        await _send_long(bot, GROUP_ID, "\n".join(lines))


# ─── ADMIN BUYRUQLARI ─────────────────────────────────────────────────────────

def _is_admin(message: Message) -> bool:
    """Xabar guruhdan va admindan kelganini tekshiradi."""
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


@router.message(Command("reklama_tekshir"))
async def cmd_check(message: Message, bot: Bot):
    """Qo'lda nazorat: hozirgi holatni guruhga chiqaradi."""
    if not _is_admin(message):
        return
    msg = await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    with contextlib.suppress(Exception):
        await msg.delete()
        await message.delete()


@router.message(Command("reklama_users"))
async def cmd_users(message: Message):
    """Bugungi xodimlar holatini progress bar bilan ko'rsatadi (60 soniyadan so'ng o'chadi)."""
    if not _is_admin(message):
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _safe_records(_ws()))
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    today = today_str()
    lines = ["👥 <b>Faol xodimlar bugun:</b>\n"]
    count = 0

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw = r.get(today, "")
        cnt     = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            local = _local_get(int(tg_id))
            if local > cnt:
                cnt = local
        except (ValueError, TypeError):
            pass
        name  = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        bar   = progress_bar(cnt, DAILY_TARGET)
        emoji = "✅" if cnt >= DAILY_TARGET else "⚠️" if cnt > 0 else "❌"
        lines.append(f"{emoji} <b>{name}</b>\n   {bar} {cnt}/{DAILY_TARGET}")
        count += 1
        if count >= 30:
            break

    if count == 0:
        await message.answer("❌ Faol xodimlar yo'q")
        return

    sent = await message.answer("\n".join(lines), parse_mode="HTML")
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(60)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("sync_subadmin"))
async def cmd_sync(message: Message, bot: Bot):
    """user varag'idagi ma'lumotlarni sub_adminlar ga ko'chiradi."""
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    msg = await bot.send_message(ADMIN_ID, "⏳ Sinxronlanmoqda...")
    try:
        def _sync() -> int:
            subws    = _ws()
            usrws    = _user_ws()
            user_map = {
                str(r[1]).strip(): r
                for r in usrws.get_all_values()[1:]
                if len(r) > 1 and str(r[1]).strip()
            }
            updated = 0
            for i, row in enumerate(subws.get_all_values()[1:], start=2):
                tid = str(row[1]).strip() if len(row) > 1 else ""
                if not tid or tid not in user_map:
                    continue
                u       = user_map[tid]
                changed = False
                # (user ustun indeksi, sub_adminlar ustun indeksi)
                for ui, sc in [(2, 3), (3, 4), (4, 5), (5, 6)]:
                    cur = str(row[sc - 1]).strip() if len(row) > sc - 1 else ""
                    src = str(u[ui]).strip()        if len(u)   > ui     else ""
                    if not cur and src:
                        subws.update_cell(i, sc, src)
                        changed = True
                if changed:
                    updated += 1
            return updated

        loop    = asyncio.get_running_loop()
        updated = await loop.run_in_executor(None, _sync)
        await msg.edit_text(f"✅ Sinxronlash yakunlandi! {updated} ta qator yangilandi.")
    except Exception as e:
        await msg.edit_text(f"❌ Xato: {e}")
    with contextlib.suppress(Exception):
        await message.delete()


@router.message(Command("reklama_sana_tuzat"))
async def cmd_fix_date_headers(message: Message):
    """
    BIR MARTALIK: sana ustunlari formati buzilgan bo'lsa tuzatadi.
    Agar oylik/haftalik statistika hammada 0 ko'rsatsa — shu buyruqni
    bir marta ishlating.
    """
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("🔧 Sana ustunlari tekshirilmoqda...")
    try:
        loop  = asyncio.get_running_loop()
        fixed = await loop.run_in_executor(None, fix_date_header_formats_sync)
        if fixed:
            await msg.edit_text(f"✅ {fixed} ta sana ustuni tuzatildi! Endi statistikani qayta tekshiring.")
        else:
            await msg.edit_text("✅ Barcha sana ustunlari to'g'ri formatda edi.")
    except Exception as e:
        await msg.edit_text(f"❌ Xato: {e}")
    with contextlib.suppress(Exception):
        await message.delete()


@router.message(Command("reklama_tozala"))
async def cmd_cleanup_dupes(message: Message):
    """Sheets dagi takroriy sana ustunlarini birlashtiradi va o'chiradi."""
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    msg = await message.answer("🧹 Dublikat ustunlar tekshirilmoqda...")
    try:
        loop    = asyncio.get_running_loop()
        removed = await loop.run_in_executor(None, _cleanup_duplicate_cols_sync)
        if removed:
            await msg.edit_text(f"✅ {removed} ta dublikat ustun tozalandi!")
        else:
            await msg.edit_text("✅ Dublikat ustun topilmadi.")
    except Exception as e:
        await msg.edit_text(f"❌ Xato: {e}")
    with contextlib.suppress(Exception):
        await message.delete()


@router.message(Command("reklama_help"))
async def cmd_help(message: Message):
    """Yordam xabarini guruhga yuboradi (40 soniyadan so'ng o'chadi)."""
    if not _is_admin(message):
        return
    sent = await message.answer(
        "📋 <b>Reklama Nazorat — Yordam</b>\n\n"
        "<b>Xodimlar:</b>\n"
        "• Guruhga rasm yuboring — bot hisoblaydi\n"
        "• Har kuni kamida 2 ta rasm kerak\n\n"
        "<b>Admin buyruqlari:</b>\n"
        "/start_register — Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir — Qo'lda nazorat\n"
        "/reklama_stat — Statistika (kunlik/haftalik/oylik)\n"
        "/reklama_reyting — Oylik reyting e'lon qilish\n"
        "/reklama_users — Faol xodimlar (progress bar)\n"
        "/sync_subadmin — User → sub_admin sinxronlash\n"
        "/reklama_tozala — Dublikat ustunlarni tozalash 🧹\n\n"
        "<b>Avtomatik (Apps Script):</b>\n"
        "⏰ 09:30, 15:00 — Nazorat + progress bar\n"
        "🕛 12:00 — Tushlik nazorati\n"
        "📆 Har dushanba 09:00 — Haftalik reyting\n"
        "🗓 Har oyning 1-si 09:00 — Oylik reyting 🏆",
        parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(40)
    with contextlib.suppress(Exception):
        await sent.delete()


# ─── SCHEDULER UCHUN YORDAMCHI FUNKSIYALAR ───────────────────────────────────

async def _send_today_stats(bot: Bot) -> None:
    """18:00 — bugungi statistikani guruhga yuboradi."""
    stats = await get_stats(1)
    text  = _stat_text(stats, "Kunlik", 1)
    with contextlib.suppress(TelegramForbiddenError):
        await _send_long(bot, GROUP_ID, text)


async def _send_weekly_stats(bot: Bot) -> None:
    """Dushanba 09:00 — haftalik statistikani guruhga yuboradi."""
    loop = asyncio.get_running_loop()
    # Dublikat ustunlarni avval tozalaymiz
    with contextlib.suppress(Exception):
        await loop.run_in_executor(None, _cleanup_duplicate_cols_sync)
    stats = await get_stats(7)
    text  = _stat_text(stats, "Haftalik", 7)
    with contextlib.suppress(TelegramForbiddenError):
        await _send_long(bot, GROUP_ID, text)
    logger.info("Haftalik statistika yuborildi")


async def _check_and_send_monthly(bot: Bot) -> None:
    """
    Har kuni 09:05 da ishga tushadi.
    Faqat oyning 1-sanasida oylik reyting e'lon qiladi.
    """
    if now_tz().day == 1:
        await announce_monthly_rating(bot)
        logger.info("Oylik reyting e'lon qilindi")


async def _create_daily_column_job() -> None:
    """
    00:00 — bugungi sana ustunini Sheets da yaratadi.
    Apps Script `createDailyColumn` o'rnini bosadi.
    """
    loop = asyncio.get_running_loop()
    try:
        def _create():
            sheet = _ws()
            _get_date_col(sheet, today_str())
        await loop.run_in_executor(None, _create)
        logger.info(f"Kunlik ustun yaratildi: {today_str()}")
    except Exception as e:
        logger.error(f"create_daily_column xato: {e}")


# ─── SETUP SCHEDULER ─────────────────────────────────────────────────────────

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    APScheduler ni sozlaydi va qaytaradi.
    main.py da chaqiriladi:
        from reklama_nazorati import setup_scheduler
        scheduler = setup_scheduler(bot)

    Trigger jadval (Asia/Tashkent):
      00:00        — Kunlik sana ustuni yaratish
      09:30        — Nazorat (check_screenshots)
      12:00        — Tushlik nazorati (check_midday)
      15:00        — Nazorat (check_screenshots)
      18:00        — Bugungi statistika
      Dushanba 09:00 — Haftalik statistika
      Har kuni 09:05 — Oylik reyting (faqat 1-sana)
    """
    TZ_STR = "Asia/Tashkent"
    sched  = AsyncIOScheduler(timezone=TZ_STR)

    sched.add_job(
        lambda: asyncio.ensure_future(_create_daily_column_job()),
        CronTrigger(hour=0, minute=0, timezone=TZ_STR),
        id="daily_col", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(check_screenshots(bot)),
        CronTrigger(hour=9, minute=30, timezone=TZ_STR),
        id="check_0930", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(check_midday(bot)),
        CronTrigger(hour=12, minute=0, timezone=TZ_STR),
        id="midday", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(check_screenshots(bot)),
        CronTrigger(hour=15, minute=0, timezone=TZ_STR),
        id="check_1500", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(_send_today_stats(bot)),
        CronTrigger(hour=18, minute=0, timezone=TZ_STR),
        id="today_stats", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(_send_weekly_stats(bot)),
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=TZ_STR),
        id="weekly_stats", replace_existing=True,
    )
    sched.add_job(
        lambda: asyncio.ensure_future(_check_and_send_monthly(bot)),
        CronTrigger(hour=9, minute=5, timezone=TZ_STR),
        id="monthly_check", replace_existing=True,
    )

    sched.start()
    logger.info("Scheduler ishga tushdi — 7 ta trigger faol")
    return sched
