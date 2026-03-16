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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

# ===================== SOZLAMALAR =====================

router = Router()
logger = logging.getLogger(__name__)
TZ     = ZoneInfo("Asia/Tashkent")

def now_tz() -> datetime: return datetime.now(TZ)
def today_str() -> str:   return now_tz().strftime("%d.%m.%Y")

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
BASE_COLS    = 8
DAILY_TARGET = 2   # Kunlik maqsad

_gc: gspread.Client | None = None
_registering: set[int] = set()
_reg_lock = asyncio.Lock()


# ===================== PROGRESS BAR =====================

def progress_bar(count: int, target: int, width: int = 10) -> str:
    ratio = min(count / target, 1.0) if target > 0 else 0
    fill  = round(ratio * width)
    color = "🟩" if ratio >= 1.0 else "🟨" if ratio >= 0.5 else "🟥"
    return color * fill + "⬜" * (width - fill)


def percent_bar(pct: int, width: int = 10) -> str:
    fill  = min(round(pct / 100 * width), width)
    color = "🟩" if pct >= 100 else "🟨" if pct >= 50 else "🟥"
    return color * fill + "⬜" * (width - fill)


# ===================== SHEETS =====================

def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc

def _ws() -> gspread.Worksheet:
    sh = _get_gc().open_by_key(SPREADSHEET_ID)
    try:
        return sh.worksheet(SUBADMIN_SHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUBADMIN_SHEET, rows="100", cols="50")
        ws.append_row(["T/r", "Telegram ID", "Username", "Ism",
                       "Familiya", "Telefon raqami", "Qo'shilgan sana", "Holati"])
        return ws

def _user_ws() -> gspread.Worksheet:
    return _get_gc().open_by_key(SPREADSHEET_ID).worksheet(USER_SHEET)

def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    for i, v in enumerate(ws.col_values(2), start=1):
        if str(v).strip() == str(user_id):
            return i
    return None

# Ustun yaratish uchun lock — Apps Script va bot bir vaqtda yaratmasin
_col_lock = asyncio.Lock()

def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    """
    Bugungi sana ustunini topadi yoki yaratadi.
    MUHIM: chaqirishdan oldin _col_lock ni olish kerak (async kontekstda).
    Sync kontekstda (run_in_executor) to'g'ridan chaqiriladi —
    shuning uchun Sheets dan qayta o'qib tekshiramiz.
    """
    # Sheets dan fresh o'qiymiz — kesh emas
    headers = ws.row_values(1)
    # Duplicate bo'lsa birinchisini qaytaramiz
    for i, h in enumerate(headers):
        if str(h).strip() == date_str:
            return i + 1
    # Yo'q — yangi ustun
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, date_str)
    return new_col


def _cleanup_duplicate_cols_sync_inner(sheet: gspread.Worksheet) -> int:
    """Sheet object bilan dublikat ustunlarni tozalaydi."""
    headers = sheet.row_values(1)
    seen    = {}
    removed = 0
    for i, h in enumerate(headers):
        h = str(h).strip()
        if not h:
            continue
        if h in seen:
            first_col = seen[h]
            dupe_col  = i + 1
            all_vals  = sheet.get_all_values()
            for row_i, row in enumerate(all_vals[1:], start=2):
                first_val = int(row[first_col-1]) if len(row) >= first_col and str(row[first_col-1]).strip().isdigit() else 0
                dupe_val  = int(row[dupe_col-1])  if len(row) >= dupe_col  and str(row[dupe_col-1]).strip().isdigit()  else 0
                if dupe_val > 0:
                    sheet.update_cell(row_i, first_col, first_val + dupe_val)
            last_row_idx = len(all_vals)
            if last_row_idx > 0:
                sheet.batch_clear([f"{_col_letter(dupe_col)}1:{_col_letter(dupe_col)}{last_row_idx}"])
            removed += 1
        else:
            seen[h] = i + 1
    return removed


def _cleanup_duplicate_cols_sync() -> int:
    """
    Bir xil sana ustunlari bo'lsa ikkinchisini o'chiradi.
    """
    sheet   = _ws()
    headers = sheet.row_values(1)
    return _cleanup_duplicate_cols_sync_inner(sheet)

def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _safe_records(ws: gspread.Worksheet) -> list[dict]:
    """
    get_all_records() dublikat sarlavhada xato beradi.
    Shuning uchun get_all_values() ishlatamiz va o'zimiz dict yasaymiz.
    Dublikat ustunlarda oxirgisi qaytariladi — shuning uchun
    avval _cleanup_duplicate_cols_sync() chaqirilishi kerak.
    """
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return []
    headers = all_vals[0]
    result  = []
    for row in all_vals[1:]:
        # Bo'sh qatorlarni o'tkazib yuboramiz
        if not any(str(c).strip() for c in row[:8]):
            continue
        # Pad qisqa qatorlarni
        padded = row + [""] * (len(headers) - len(row))
        d = {}
        for i, h in enumerate(headers):
            h = str(h).strip()
            if h:
                d[h] = padded[i]
        result.append(d)
    return result


# ===================== LOCAL KESH =====================
# Cache faqat tezlik uchun — Sheets ASOSIY manba.
# Bot restart bo'lsa cache tozalanadi, shuning uchun
# har safar Sheets dan o'qib, ustiga +1 qo'shamiz.

_local_counts: dict[int, dict] = {}
# Bugungi yuborilgan file_unique_id lar — dublikatni aniqlash uchun
_seen_files: dict[int, set] = {}
# Per-user lock — bir vaqtda bir nechta screenshot kelganda race condition ni oldini olish
_user_locks: dict[int, asyncio.Lock] = {}
# Har bir user uchun oxirgi bot reply message_id — yangi kelganda o'chiramiz
_last_reply_msgs: dict[int, int] = {}

def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

def _local_get(user_id: int) -> int:
    data = _local_counts.get(user_id)
    if data and data.get("date") == today_str():
        return data.get("count", 0)
    return -1   # -1 = keshda yoq, Sheets dan oqish kerak

def _local_set(user_id: int, count: int) -> None:
    _local_counts[user_id] = {"date": today_str(), "count": count}

def _is_duplicate(user_id: int, file_unique_id: str) -> bool:
    """Bugun shu faylni yuborgan-yubormaganini tekshiradi."""
    today = today_str()
    rec   = _seen_files.get(user_id)
    if rec is None or rec.get("date") != today:
        _seen_files[user_id] = {"date": today, "files": set()}
    return file_unique_id in _seen_files[user_id]["files"]

def _mark_seen(user_id: int, file_unique_id: str) -> None:
    """Faylni korilgan deb belgilaydi."""
    today = today_str()
    rec   = _seen_files.get(user_id)
    if rec is None or rec.get("date") != today:
        _seen_files[user_id] = {"date": today, "files": set()}
    _seen_files[user_id]["files"].add(file_unique_id)

def _read_sheet_count_sync(user_id: int) -> int:
    """Sheets dagi bugungi son — kesh yo'q bo'lganda chaqiriladi."""
    try:
        sheet    = _ws()
        date_col = _get_date_col(sheet, today_str())
        row      = _find_row(sheet, user_id)
        if not row:
            return 0
        val = sheet.cell(row, date_col).value
        return int(val) if val and str(val).strip().isdigit() else 0
    except Exception as e:
        logger.error(f"Sheets o'qishda xato ({user_id}): {e}")
        return 0

def _increment_sheet_sync(user_id: int) -> int:
    """
    Sheets dan hozirgi qiymatni o'qiydi, +1 qo'shib yozadi.
    Har safar dublikat ustunlarni ham tozalaydi.
    Yangi qiymatni qaytaradi.
    """
    try:
        sheet    = _ws()
        date_col = _get_date_col(sheet, today_str())
        row      = _find_row(sheet, user_id)
        if not row:
            return 0
        val     = sheet.cell(row, date_col).value
        current = int(val) if val and str(val).strip().isdigit() else 0
        next_   = current + 1
        sheet.update_cell(row, date_col, next_)
        return next_
    except Exception as e:
        logger.error(f"Sheets increment xato ({user_id}): {e}")
        return 0


# ===================== RO'YXATGA OLISH =====================

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
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
    row = [str(valid_count + 1), str(user_id), uname, ism, familiya, "", sana, "Faol"]
    while len(row) < len(headers):
        row.append("")
    sheet.append_row(row, value_input_option="RAW")
    logger.info(f"Yangi sub_admin: {full_name} ({user_id})")
    return True

def _set_status_sync(user_id: int, status: str) -> None:
    sheet = _ws()
    row   = _find_row(sheet, user_id)
    if row:
        sheet.update_cell(row, 8, status)

async def register_user(user_id: int, full_name: str, username: str) -> bool:
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
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _set_status_sync, user_id, status)


# ===================== GURUH HANDLERLARI =====================

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_join(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await register_user(u.id, u.full_name or "", u.username or "")

@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_leave(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return
    u = event.new_chat_member.user
    if not u.is_bot:
        with contextlib.suppress(Exception):
            await set_status(u.id, "Chiqib ketdi")

@router.message(F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0), F.photo | F.document)
async def handle_media(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
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

    # ── Duplicate tekshiruv ──────────────────────────────────────
    # Eng katta rasmning file_unique_id ni olamiz
    if message.photo:
        file_uid = message.photo[-1].file_unique_id
    else:
        file_uid = message.document.file_unique_id

    if _is_duplicate(u.id, file_uid):
        with contextlib.suppress(Exception):
            await message.reply(
                "⚠️ <b>Bu rasmni bugun allaqachon yuborgansiz!</b>\n"
                "Yangi reklama screenshotini yuboring.",
                parse_mode="HTML",
            )
        return

    _mark_seen(u.id, file_uid)

    # ── Hisoblash (per-user lock — race condition yo'q) ──────────
    loop = asyncio.get_running_loop()
    async with _get_user_lock(u.id):
        cached = _local_get(u.id)
        if cached >= 0:
            count = cached + 1
            _local_set(u.id, count)
            # Sheets ga yozish — await bilan, serialized
            await loop.run_in_executor(None, _increment_sheet_sync, u.id)
        else:
            # Keshda yoq — Sheets dan o'qib +1
            count = await loop.run_in_executor(None, _increment_sheet_sync, u.id)
            _local_set(u.id, count)

    # ── Javob ────────────────────────────────────────────────────
    bar   = progress_bar(count, DAILY_TARGET)
    emoji = "📸" if count == 1 else "✅" if count == 2 else "🔥"
    text  = f"{emoji} <b>{u.full_name}</b>\n{bar} <b>{count}/{DAILY_TARGET}</b>"

    ragbat_done = [
        "✦ Tizim qayd etdi: kunlik vazifa bajarildi. Faoliyat hisobga olindi.",
        "✦ Monitoring tasdiqladi: 2/2. Siz kuzatuv tizimida yashil holatdasiz.",
        "✦ Nazorat tizimi: reja yopildi. Xodim faoliyati — normada.",
        "✦ Tizim hisobi: bugungi majburiyat bajarildi. Natija bazaga yozildi.",
    ]
    ragbat_over = [
        "✦ Tizim qayd etdi: reja oshib ketdi. Qo'shimcha faoliyat hisobga olindi.",
        "✦ Monitoring: rejadan ortiq natija. Siz bugun tizimda lider holatdasiz.",
        "✦ Nazorat tizimi: {count} ta screenshot — yuqori faollik. Oy reytingida hisoblanmoqda.",
        "✦ Tizim: kunlik norma oshib ketdi. Bunday xodimlar alohida e'tiborga olinadi.",
    ]
    import random
    if count == DAILY_TARGET:
        msg = random.choice(ragbat_done)
        text += (
            f"\n✅ <b>Kunlik reja bajarildi.</b>"
            f"\n🤖 <i>{msg}</i>"
        )
    elif count > DAILY_TARGET:
        msg = random.choice(ragbat_over).replace("{count}", str(count))
        text += (
            f"\n🏆 <b>{count}-screenshot — rejadan oshib ketdingiz.</b>"
            f"\n🤖 <i>{msg}</i>"
        )
    else:
        remaining = DAILY_TARGET - count
        roasts = [
            "⚡ Tizim ogohlantiradi: vazifa bajarilmagan. Holat — qizil.",
            "⚡ Nazorat tizimi: bugungi faollik nolda. Bu hisobotga tushadi.",
            "⚡ Monitoring: siz hali ro'yxatda ko'rinmayapsiz. Darhol harakat talab etiladi.",
            "⚡ Tizim qayd etdi: {remaining} ta vazifa bajarilmagan. Vaqt — cheklangan.",
            "⚡ Diqqat: bajarilmagan vazifalar oy reytingida avtomatik hisoblanadi.",
            "⚡ Nazorat tizimi: faolsizlik aniqlandi. Keyingi tekshiruvda holat qayta baholanadi.",
        ]
        import random
        roast = random.choice(roasts).replace("{remaining}", str(remaining))
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

@router.message(F.chat.func(lambda c: c.id == GROUP_ID and GROUP_ID != 0), ~F.photo, ~F.document)
async def handle_text(message: Message):
    if message.from_user is None or message.from_user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    with contextlib.suppress(Exception):
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or "",
        )


# ===================== QO'LDA RO'YXAT =====================

@router.message(Command("start_register"))
async def cmd_start_register(message: Message):
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
    u = callback.from_user
    try:
        is_new = await register_user(u.id, u.full_name or "", u.username or "")
        await callback.answer(
            "✅ Ro'yxatga olindingiz!" if is_new else "✅ Allaqachon bazadasiz.",
            show_alert=True,
        )
    except Exception:
        await callback.answer("❌ Xato. Qayta urinib ko'ring.", show_alert=True)


# ===================== YORDAMCHI =====================

def _mention(uid: str, name: str) -> str:
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={uid}">{safe}</a>'

async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML",
                                   disable_web_page_preview=True)
            break
        cut  = text.rfind("\n", 0, limit) or limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML",
                               disable_web_page_preview=True)
        text = text[cut:]


# ===================== STATISTIKA (umumiy) =====================

def _stats_sync(days: int) -> list[dict]:
    sheet       = _ws()
    headers     = sheet.row_values(1)
    data        = _safe_records(sheet)
    cutoff      = (now_tz() - timedelta(days=days - 1)).replace(
                    hour=0, minute=0, second=0, microsecond=0)
    valid_dates = []
    for h in headers[BASE_COLS:]:
        try:
            dt = datetime.strptime(h, "%d.%m.%Y").replace(tzinfo=TZ)
            if dt >= cutoff:
                valid_dates.append(h)
        except ValueError:
            pass
    result = []
    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        name  = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        total = sum(int(r[d]) if str(r.get(d, 0)).strip().isdigit() else 0
                    for d in valid_dates)
        result.append({"id": tg_id, "name": name, "total": total})
    result.sort(key=lambda x: x["total"], reverse=True)
    return result

async def get_stats(days: int) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _stats_sync, days)


def _stat_text(stats: list[dict], label: str, days: int) -> str:
    """Progress bar shaklidagi statistika matni."""
    if not stats:
        return f"📊 <b>{label} statistika</b>\n\nMa'lumot yo'q."

    total_all = sum(u["total"] for u in stats)
    ideal     = days * DAILY_TARGET          # Maksimal mumkin bo'lgan son
    d_start   = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end     = now_tz().strftime("%d.%m.%Y")

    # Umumiy foiz
    max_possible = ideal * len(stats)
    overall_pct  = int(total_all / max_possible * 100) if max_possible else 0

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
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(
            f"\n{medal} {_mention(u['id'], u['name'])}\n"
            f"   {bar} <b>{u['total']}/{ideal}</b> ({pct}%)"
        )

    return "\n".join(lines)


def _stat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Kunlik",   callback_data="stat_daily"),
            InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
            InlineKeyboardButton(text="🗓 Oylik",    callback_data="stat_monthly"),
        ],
        [
            InlineKeyboardButton(text="🏆 Reyting",  callback_data="stat_rating"),
            InlineKeyboardButton(text="❌ Yopish",   callback_data="stat_close"),
        ],
    ])


@router.message(Command("reklama_stat"))
async def cmd_stat(message: Message, bot: Bot):
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
    # Dublikat ustunlarni tozalaymiz
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


# ===================== REYTING TIZIMI =====================

async def _build_rating_text(days: int = 30) -> str:
    """
    Top-3 xodim + barchaning progress bar ko'rinishi.
    Oylik ideal = days * DAILY_TARGET (masalan 30*2=60).
    """
    stats = await get_stats(days)
    if not stats:
        return "🏆 <b>Reyting</b>\n\nMa'lumot yo'q."

    ideal     = days * DAILY_TARGET
    total_all = sum(u["total"] for u in stats)
    d_start   = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end     = now_tz().strftime("%d.%m.%Y")

    # ── TOP-3 alohida ajratilgan ──
    medals     = ["🥇", "🥈", "🥉"]
    top_lines  = []
    for i, u in enumerate(stats[:3]):
        pct   = int(u["total"] / ideal * 100) if ideal else 0
        bar   = progress_bar(u["total"], ideal)
        stars = "⭐" * (3 - i)
        top_lines.append(
            f"{medals[i]} {stars} {_mention(u['id'], u['name'])}\n"
            f"   {bar} <b>{u['total']}/{ideal}</b> ({pct}%)"
        )

    # ── Qolganlar ──
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
        # Guruhga
        await _send_long(bot, GROUP_ID, text)
        # Adminga ham
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
    Har oyning oxirgi kunida (yoki Apps Script dan) chaqiriladi.
    Guruhga tantanali e'lon qiladi.
    """
    stats = await get_stats(30)
    if not stats or len(stats) < 1:
        return

    ideal    = 30 * DAILY_TARGET
    medals   = ["🥇", "🥈", "🥉"]
    d_end    = now_tz().strftime("%d.%m.%Y")
    d_start  = (now_tz() - timedelta(days=29)).strftime("%d.%m.%Y")

    # Tantanali sarlavha
    header = (
        f"🎉 <b>OY REYTINGI E'LON QILINMOQDA!</b>\n"
        f"📅 {d_start} — {d_end}\n\n"
        f"📸 Eng ko'p reklama tarqatgan xodimlar:\n\n"
    )

    top_lines = []
    for i, u in enumerate(stats[:3]):
        pct  = int(u["total"] / ideal * 100) if ideal else 0
        bar  = progress_bar(u["total"], ideal)
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


# ===================== QOLDA NAZORAT =====================

async def check_screenshots(bot: Bot) -> None:
    if GROUP_ID == 0:
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _safe_records(_ws()))
    except Exception as e:
        logger.error(f"Sheets o'qishda xato: {e}")
        return

    if not data:
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID, "⚠️ sub_adminlar da hech kim yo'q!\n/start_register yuboring.")
        return

    today     = today_str()
    time_str  = now_tz().strftime("%H:%M")
    debtors   = []
    done_list = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw    = r.get(today, 0)
        from_sheet = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            from_local = _local_get(int(tg_id))
        except ValueError:
            from_local = 0
        cnt  = max(from_sheet, from_local)
        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        (done_list if cnt >= DAILY_TARGET else debtors).append(
            {"id": tg_id, "name": name, "count": cnt})

    total    = len(done_list) + len(debtors)
    done_cnt = len(done_list)
    pct      = int(done_cnt / total * 100) if total else 0

    # ── Umumiy holat + progress bar ──
    lines = [
        f"📊 <b>NAZORAT — {time_str}</b>",
        f"📅 {today}\n",
        f"{percent_bar(pct)} <b>{pct}%</b>",
        f"👥 Jami: {total}  ✅ {done_cnt}  ❌ {len(debtors)}",
    ]

    if done_list:
        lines.append("\n✅ <b>Bajardilar:</b>")
        for u in done_list:
            bar = progress_bar(u["count"], DAILY_TARGET)
            lines.append(f"{_mention(u['id'], u['name'])}\n   {bar} <b>{u['count']}/{DAILY_TARGET}</b>")

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
            f"\n➖➖➖➖➖➖➖➖➖➖",
            f"❗ <b>Reklama tarqatib screenshot yuborsin!</b>",
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
    """12:00 — faqat hali screenshot tashlamaganlar uchun ogohlantirish."""
    if GROUP_ID == 0:
        return
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, lambda: _safe_records(_ws()))
    except Exception as e:
        logger.error(f"check_midday Sheets xato: {e}")
        return

    today    = today_str()
    debtors  = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw = r.get(today, 0)
        cnt     = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        try:
            local = _local_get(int(tg_id))
        except ValueError:
            local = 0
        cnt = max(cnt, local)
        if cnt < DAILY_TARGET:
            name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
            debtors.append({"id": tg_id, "name": name, "count": cnt})

    if not debtors:
        return

    lines = [
        "⏰ <b>12:00 — Tushlik nazorati</b>",
        f"📅 {today}\n",
        f"❌ Hali taslimot qilmaganlar: <b>{len(debtors)}</b> ta\n",
    ]
    for i, u in enumerate(debtors, 1):
        bar  = progress_bar(u["count"], DAILY_TARGET)
        note = f"{u['count']}/{DAILY_TARGET}" if u["count"] > 0 else "hali boshlmadi"
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


# ===================== ADMIN BUYRUQLARI =====================

def _is_admin(message: Message) -> bool:
    return (
        message.from_user is not None
        and message.from_user.id == ADMIN_ID
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


@router.message(Command("reklama_tekshir"))
async def cmd_check(message: Message, bot: Bot):
    if not _is_admin(message):
        return
    msg = await message.answer("🔍 Tekshirilmoqda...")
    await check_screenshots(bot)
    with contextlib.suppress(Exception):
        await msg.delete()
        await message.delete()


@router.message(Command("reklama_users"))
async def cmd_users(message: Message):
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
        cnt_raw = r.get(today, 0)
        cnt     = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        name    = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        bar     = progress_bar(cnt, DAILY_TARGET)
        emoji   = "✅" if cnt >= DAILY_TARGET else "⚠️" if cnt > 0 else "❌"
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
                for ui, sc in [(2, 3), (3, 4), (4, 5), (5, 6)]:
                    cur = str(row[sc - 1]).strip() if len(row) > sc - 1 else ""
                    src = str(u[ui]).strip()        if len(u) > ui else ""
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


@router.message(Command("reklama_tozala"))
async def cmd_cleanup_dupes(message: Message):
    """Sheets dagi takroriy sana ustunlarini birlashtiradi."""
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
        "/sync_subadmin — User → sub_admin sinxronlash\n\n"
        "<b>Avtomatik (Apps Script):</b>\n"
        "⏰ 09:30, 15:00 — Nazorat + progress bar\n"
        "📆 Har dushanba 09:00 — Haftalik reyting\n"
        "🗓 Har oyning 1-si 09:00 — Oylik reyting 🏆",
        parse_mode="HTML",
    )
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(40)
    with contextlib.suppress(Exception):
        await sent.delete()
