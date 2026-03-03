"""
Reklama Nazorat Tizimi
- Sheets ASOSIY MANBA: read → increment → write (bir operatsiyada)
- Qo'lda kiritilganlar ham hisoblanadi
- 09:30 va 15:00 nazorat
- Haftalik/oylik statistika
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ===================== SOZLAMALAR =====================

router = Router()
logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Tashkent")


def now_tz() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now_tz().strftime("%d.%m.%Y")


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
BASE_COLS = 8

SCHEDULER: AsyncIOScheduler | None = None
_gc: gspread.Client | None = None
_registering: set[int] = set()
_reg_lock = asyncio.Lock()


# ===================== SHEETS =====================

def _get_gc() -> gspread.Client:
    global _gc
    if _gc is None:
        b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
        if not b64:
            raise RuntimeError("GOOGLE_CREDENTIALS_B64 topilmadi")
        info = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc = gspread.authorize(creds)
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


def _get_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    headers = ws.row_values(1)
    if date_str in headers:
        return headers.index(date_str) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, date_str)
    return new_col


def _find_row(ws: gspread.Worksheet, user_id: int) -> int | None:
    for i, v in enumerate(ws.col_values(2), start=1):
        if str(v).strip() == str(user_id):
            return i
    return None


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ===================== SCREENSHOT: READ → INCREMENT → WRITE =====================

def _write_and_get_count_sync(user_id: int) -> int:
    """
    Sheets dan hozirgi sonni o'qiydi, 1 ga oshiradi, yozadi.
    Qo'lda kiritilgan ma'lumotlar ham asosga olinadi.
    """
    try:
        sheet = _ws()
        date_col = _get_date_col(sheet, today_str())
        row = _find_row(sheet, user_id)

        if not row:
            logger.warning(f"Screenshot: {user_id} sub_adminlar da topilmadi")
            return 0

        val = sheet.cell(row, date_col).value
        current = int(val) if val and str(val).strip().isdigit() else 0
        new_count = current + 1
        sheet.update_cell(row, date_col, new_count)
        logger.info(f"Screenshot yozildi: {user_id} → {new_count}")
        return new_count
    except Exception as e:
        logger.error(f"Screenshot yozishda xato ({user_id}): {e}")
        return 0


async def write_and_get_count(user_id: int) -> int:
    return await asyncio.get_event_loop().run_in_executor(
        None, _write_and_get_count_sync, user_id
    )


# ===================== RO'YXATGA OLISH =====================

def _register_sync(user_id: int, full_name: str, username: str) -> bool:
    sheet = _ws()
    if _find_row(sheet, user_id):
        return False

    parts = (full_name or "").split(" ", 1)
    ism = parts[0]
    familiya = parts[1] if len(parts) > 1 else ""
    uname = f"@{username}" if username else ""
    sana = now_tz().strftime("%Y-%m-%d %H:%M")

    all_vals = sheet.get_all_values()
    headers = all_vals[0] if all_vals else []
    valid_count = sum(1 for r in all_vals[1:] if len(r) > 1 and r[1].strip())
    tr = valid_count + 1

    row = [str(tr), str(user_id), uname, ism, familiya, "", sana, "Faol"]
    while len(row) < len(headers):
        row.append("")
    sheet.append_row(row, value_input_option="RAW")
    logger.info(f"Yangi sub_admin: {full_name} ({user_id})")
    return True


def _set_status_sync(user_id: int, status: str) -> None:
    sheet = _ws()
    row = _find_row(sheet, user_id)
    if row:
        sheet.update_cell(row, 8, status)


async def register_user(user_id: int, full_name: str, username: str) -> bool:
    async with _reg_lock:
        if user_id in _registering:
            return False
        _registering.add(user_id)
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, _register_sync, user_id, full_name, username
        )
    finally:
        async with _reg_lock:
            _registering.discard(user_id)


async def set_status(user_id: int, status: str) -> None:
    await asyncio.get_event_loop().run_in_executor(None, _set_status_sync, user_id, status)


# ===================== CLEANUP =====================

def _cleanup_sync() -> None:
    sheet = _ws()
    all_rows = sheet.get_all_values()
    if len(all_rows) <= 1:
        return

    header_len = len(all_rows[0])
    seen: set[str] = set()
    valid: list[list] = []
    sana_now = now_tz().strftime("%Y-%m-%d %H:%M")

    for row in all_rows[1:]:
        tg_id = str(row[1]).strip() if len(row) > 1 else ""
        if not tg_id or tg_id in seen:
            continue
        seen.add(tg_id)
        r = list(row)
        while len(r) < header_len:
            r.append("")
        valid.append(r)

    if not valid:
        return

    for i, row in enumerate(valid, start=1):
        row[0] = str(i)
        if not str(row[7]).strip():
            row[7] = "Faol"
        if not str(row[6]).strip():
            row[6] = sana_now

    total = len(all_rows)
    count = len(valid)
    last = _col_letter(header_len)

    sheet.update(f"A2:{last}{count + 1}", valid, value_input_option="RAW")
    if total > count + 1:
        sheet.update(
            f"A{count + 2}:{last}{total}",
            [[""] * header_len] * (total - count - 1),
            value_input_option="RAW"
        )


async def cleanup() -> None:
    await asyncio.get_event_loop().run_in_executor(None, _cleanup_sync)


# ===================== GURUH HANDLERLARI =====================

def _is_group(message: Message) -> bool:
    return (
        message.from_user is not None
        and not message.from_user.is_bot
        and message.chat.id == GROUP_ID
        and GROUP_ID != 0
    )


def _is_admin(message: Message) -> bool:
    return _is_group(message) and message.from_user.id == ADMIN_ID


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


@router.message(F.photo | F.document)
async def handle_media(message: Message):
    """Rasm yoki rasm-fayl = screenshot. Sheets dan o'qib, yozadi."""
    if not _is_group(message):
        return
    if message.document and not (
        message.document.mime_type or ""
    ).startswith("image/"):
        # Rasm emas — faqat ro'yxatga olamiz
        with contextlib.suppress(Exception):
            await register_user(
                message.from_user.id,
                message.from_user.full_name or "",
                message.from_user.username or ""
            )
        return

    u = message.from_user

    # Avval ro'yxatga olamiz (yangi bo'lsa)
    with contextlib.suppress(Exception):
        await register_user(u.id, u.full_name or "", u.username or "")

    # Sheets dan o'qib, oshirib, yozamiz — AWAIT bilan (background emas)
    count = await write_and_get_count(u.id)

    if count > 0:
        emoji = "📸" if count == 1 else "✅" if count == 2 else "🎉"
        text = f"{emoji} <b>{u.full_name}</b>\n📊 Bugun: <b>{count}/2</b>"
        if count == 2:
            text += "\n\n🌟 Kunlik reja bajarildi!"
        elif count > 2:
            text += f"\n\n🔥 {count}-screenshot — zo'r!"
        with contextlib.suppress(Exception):
            await message.reply(text, parse_mode="HTML")

    logger.info(f"Screenshot: {u.full_name} ({u.id}) → {count}")


@router.message(~F.photo, ~F.document)
async def handle_text(message: Message):
    """Matn yoki boshqa xabar — faqat ro'yxatga olish."""
    if not _is_group(message):
        return
    with contextlib.suppress(Exception):
        await register_user(
            message.from_user.id,
            message.from_user.full_name or "",
            message.from_user.username or ""
        )


# ===================== QO'LDA RO'YXAT =====================

@router.message(Command("start_register"))
async def cmd_start_register(message: Message):
    if not _is_admin(message):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ RO'YXATDAN O'TISH", callback_data="reg_me")]
    ])
    await message.bot.send_message(
        GROUP_ID,
        "📢 <b>DIQQAT!</b>\n\nBarcha xodimlar quyidagi tugmani bossin.\n"
        "Bo'lmasa hisobotda ko'rinmaysiz.\n\n👇 <b>Bosing:</b>",
        reply_markup=kb, parse_mode="HTML"
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
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Ro'yxatdan o'tkazishda xato: {e}")
        await callback.answer("❌ Xato. Qayta urinib ko'ring.", show_alert=True)


# ===================== MENTION =====================

def _mention(uid: str, name: str) -> str:
    safe = (name or "Xodim").replace("<", "").replace(">", "").strip() or "Xodim"
    return f'<a href="tg://user?id={uid}">{safe}</a>'


async def _send_long(bot: Bot, chat_id: int, text: str) -> None:
    limit = 3800
    while text:
        if len(text) <= limit:
            await bot.send_message(chat_id, text, parse_mode="HTML")
            break
        cut = text.rfind("\n", 0, limit) or limit
        await bot.send_message(chat_id, text[:cut], parse_mode="HTML")
        text = text[cut:]


# ===================== NAZORAT (09:30 / 15:00) =====================

async def check_screenshots(bot: Bot) -> None:
    """
    get_all_records() → bugungi ustun sarlavhasi kalit sifatida ishlatiladi.
    Qo'lda kiritilgan ma'lumotlar ham hisoblanadi.
    """
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan!")
        return

    try:
        def _read():
            sheet = _ws()
            return sheet.get_all_records()

        data = await asyncio.get_event_loop().run_in_executor(None, _read)
    except Exception as e:
        logger.error(f"Sheets o'qishda xato: {e}")
        return

    if not data:
        logger.warning("sub_adminlar bo'sh!")
        if ADMIN_ID:
            with contextlib.suppress(Exception):
                await bot.send_message(
                    ADMIN_ID,
                    "⚠️ sub_adminlar da hech kim yo'q!\n/start_register yuboring."
                )
        return

    today = today_str()
    time_str = now_tz().strftime("%H:%M")
    h, m = now_tz().hour, now_tz().minute
    next_check = (
        "Bugun 09:30" if h < 9 or (h == 9 and m < 30)
        else "Bugun 15:00" if h < 15
        else "Ertaga 09:30"
    )

    debtors = []
    done_list = []

    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue

        cnt_raw = r.get(today, 0)
        cnt = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0

        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        entry = {"id": tg_id, "name": name, "count": cnt}

        if cnt >= 2:
            done_list.append(entry)
        else:
            debtors.append(entry)

    total = len(done_list) + len(debtors)
    completed = len(done_list)
    percent = int(completed / total * 100) if total else 0

    logger.info(f"Nazorat: jami={total}, bajardi={completed}, bajarmadi={len(debtors)}")

    if debtors:
        done_text = ""
        if done_list:
            done_text = "\n✅ <b>Bajarganlar:</b>\n"
            for u in done_list:
                done_text += f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2\n"

        debtor_text = "\n❌ <b>BAJARMAGAN XODIMLAR:</b>\n"
        for i, u in enumerate(debtors, 1):
            cnt = u["count"]
            note = "bitta yetishmayapti ⚠️" if cnt == 1 else "hali birorta ham yoq 🚫"
            debtor_text += f"\n{i}. {_mention(u['id'], u['name'])}\n   📸 {cnt}/2 — {note}\n"

        text = (
            f"🚨 <b>NAZORAT — {time_str}</b>\n"
            f"📅 {now_tz().strftime('%d.%m.%Y')}\n\n"
            f"👥 Faol: {total} | ✅ {completed} | ❌ {len(debtors)}\n"
            f"📊 {percent}%\n"
            + done_text + debtor_text
            + f"\n➖➖➖➖➖➖➖➖➖➖\n"
            f"❗ <b>Reklama tarqatib screenshot yuborsin!</b>\n"
            f"📌 {CHANNEL_LINK}\n"
            f"⏰ Keyingi: {next_check}"
        )
        try:
            await _send_long(bot, GROUP_ID, text)
        except TelegramForbiddenError:
            logger.error("Guruhda yozish taqiqlangan!")
        except Exception as e:
            logger.error(f"Hisobot yuborishda xato: {e}")
    else:
        done_text = "\n".join(
            f"  ✔️ {_mention(u['id'], u['name'])} — {u['count']}/2"
            for u in done_list
        )
        with contextlib.suppress(Exception):
            await bot.send_message(
                GROUP_ID,
                f"🏆 <b>AJOYIB! — {time_str}</b>\n\n"
                "✅ Barcha xodimlar rejani bajardi!\n\n"
                f"{done_text}\n\n👏 Rahmat!",
                parse_mode="HTML"
            )

    if ADMIN_ID:
        with contextlib.suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"📊 <b>Admin — {time_str}</b>\n"
                f"👥 {total} | ✅ {completed} | ❌ {len(debtors)} | 📈 {percent}%",
                parse_mode="HTML"
            )


# ===================== STATISTIKA =====================

def _stats_sync(days: int) -> list[dict]:
    """
    get_all_records() kalit sifatida sana sarlavhasini ishlatadi.
    Oxirgi `days` kunlik umumiy sonni hisoblaydi.
    """
    sheet = _ws()
    headers = sheet.row_values(1)
    data = sheet.get_all_records()

    # Kerakli sana sarlavhalarini topamiz
    cutoff = (now_tz() - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
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

        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        total = sum(
            int(r[d]) if str(r.get(d, 0)).strip().isdigit() else 0
            for d in valid_dates
        )
        result.append({"id": tg_id, "name": name, "total": total})

    result.sort(key=lambda x: x["total"], reverse=True)
    return result


async def get_stats(days: int) -> list[dict]:
    return await asyncio.get_event_loop().run_in_executor(None, _stats_sync, days)


def _stat_text(stats: list[dict], label: str, days: int) -> str:
    if not stats:
        return f"📊 <b>{label} statistika</b>\n\nMa'lumot yo'q."

    total_all = sum(u["total"] for u in stats)
    d_start = (now_tz() - timedelta(days=days - 1)).strftime("%d.%m.%Y")
    d_end = now_tz().strftime("%d.%m.%Y")

    lines = []
    for i, u in enumerate(stats, 1):
        filled = min(u["total"], 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)
        lines.append(
            f"{i}. {_mention(u['id'], u['name'])}\n"
            f"   {bar} <b>{u['total']}</b> ta"
        )

    return (
        f"📊 <b>{label} statistika</b>\n"
        f"📅 {d_start} — {d_end}\n\n"
        f"👥 {len(stats)} xodim | 📸 Jami: {total_all} ta\n"
        "➖➖➖➖➖➖➖➖➖➖\n\n"
        + "\n\n".join(lines)
    )


def _stat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Kunlik",   callback_data="stat_daily"),
            InlineKeyboardButton(text="📆 Haftalik", callback_data="stat_weekly"),
            InlineKeyboardButton(text="🗓 Oylik",    callback_data="stat_monthly"),
        ],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="stat_close")],
    ])


@router.message(Command("reklama_stat"))
async def cmd_stat(message: Message, bot: Bot):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    await bot.send_message(
        ADMIN_ID,
        "📊 <b>Reklama statistikasi</b>\n\nQaysi davrni ko'rmoqchisiz?",
        reply_markup=_stat_kb(), parse_mode="HTML"
    )
    with contextlib.suppress(Exception):
        await message.delete()


@router.callback_query(F.data.in_({"stat_daily", "stat_weekly", "stat_monthly", "stat_close"}))
async def cb_stat(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    if call.data == "stat_close":
        with contextlib.suppress(Exception):
            await call.message.delete()
        return

    await call.answer("⏳ Hisoblanmoqda...")
    days_map = {
        "stat_daily":   (1,  "Kunlik"),
        "stat_weekly":  (7,  "Haftalik"),
        "stat_monthly": (30, "Oylik"),
    }
    days, label = days_map[call.data]
    try:
        stats = await get_stats(days)
        text = _stat_text(stats, label, days)
        await call.message.edit_text(text, reply_markup=_stat_kb(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Statistika xato: {e}")
        with contextlib.suppress(Exception):
            await call.message.edit_text(f"❌ Xato: {e}", reply_markup=_stat_kb())


# ===================== SCHEDULER =====================

async def _auto_weekly(bot: Bot) -> None:
    with contextlib.suppress(Exception):
        stats = await get_stats(7)
        await _send_long(bot, GROUP_ID, _stat_text(stats, "Haftalik", 7))


async def _auto_monthly(bot: Bot) -> None:
    with contextlib.suppress(Exception):
        stats = await get_stats(30)
        await _send_long(bot, GROUP_ID, _stat_text(stats, "Oylik", 30))


def setup_scheduler(bot: Bot) -> AsyncIOScheduler | None:
    global SCHEDULER
    if GROUP_ID == 0:
        logger.error("GROUP_ID sozlanmagan!")
        return None

    s = AsyncIOScheduler(timezone="Asia/Tashkent")
    s.add_job(check_screenshots, CronTrigger(hour=9,  minute=30),
              args=[bot], id="morning",   replace_existing=True,
              max_instances=1, coalesce=True, misfire_grace_time=300)
    s.add_job(check_screenshots, CronTrigger(hour=15, minute=0),
              args=[bot], id="afternoon", replace_existing=True,
              max_instances=1, coalesce=True, misfire_grace_time=300)
    s.add_job(_auto_weekly,  CronTrigger(day_of_week="mon", hour=9, minute=0),
              args=[bot], id="weekly",  replace_existing=True, max_instances=1)
    s.add_job(_auto_monthly, CronTrigger(day=1, hour=9, minute=0),
              args=[bot], id="monthly", replace_existing=True, max_instances=1)
    s.start()
    SCHEDULER = s
    logger.info("Scheduler: 09:30/15:00 nazorat | Du haftalik | 1-chi oylik")
    return s


# ===================== ADMIN BUYRUQLARI =====================

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
        def _read():
            return _ws().get_all_records()
        data = await asyncio.get_event_loop().run_in_executor(None, _read)
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    today = today_str()
    text = "👥 <b>Faol xodimlar:</b>\n\n"
    count = 0
    for r in data:
        if str(r.get("Holati", "")).strip() == "Chiqib ketdi":
            continue
        tg_id = str(r.get("Telegram ID", "")).strip()
        if not tg_id:
            continue
        cnt_raw = r.get(today, 0)
        cnt = int(cnt_raw) if str(cnt_raw).strip().isdigit() else 0
        name = f"{r.get('Ism', '')} {r.get('Familiya', '')}".strip() or "Noma'lum"
        emoji = "✅" if cnt >= 2 else "⚠️" if cnt == 1 else "❌"
        text += f"{emoji} <b>{name}</b> — 📸 {cnt}/2\n"
        count += 1
        if count >= 30:
            break

    if count == 0:
        await message.answer("❌ Faol xodimlar yo'q")
        return

    sent = await message.answer(text, parse_mode="HTML")
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
            subws = _ws()
            usrws = _user_ws()
            user_map: dict[str, list] = {}
            for r in usrws.get_all_values()[1:]:
                tid = str(r[1]).strip() if len(r) > 1 else ""
                if tid:
                    user_map[tid] = r
            updated = 0
            for i, row in enumerate(subws.get_all_values()[1:], start=2):
                tid = str(row[1]).strip() if len(row) > 1 else ""
                if not tid or tid not in user_map:
                    continue
                u = user_map[tid]
                changed = False
                for ui, sc in [(2, 3), (3, 4), (4, 5), (5, 6)]:
                    cur = str(row[sc - 1]).strip() if len(row) > sc - 1 else ""
                    src = str(u[ui]).strip() if len(u) > ui else ""
                    if not cur and src:
                        subws.update_cell(i, sc, src)
                        changed = True
                if changed:
                    updated += 1
            return updated

        updated = await asyncio.get_event_loop().run_in_executor(None, _sync)
        await msg.edit_text(f"✅ Sinxronlash yakunlandi! {updated} ta qator yangilandi.")
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
        "• Qo'lda Sheets ga ham kiritish mumkin\n"
        "• Har kuni kamida 2 ta rasm kerak\n\n"
        "<b>Admin buyruqlari:</b>\n"
        "/start_register — Barchani ro'yxatdan o'tkazish\n"
        "/reklama_tekshir — Qo'lda nazorat (guruhda)\n"
        "/reklama_stat — Statistika (kunlik/haftalik/oylik)\n"
        "/reklama_users — Faol xodimlar\n"
        "/sync_subadmin — User dan sub_admin ga ko'chirish\n\n"
        "<b>Avtomatik:</b>\n"
        "⏰ 09:30, 15:00 — Nazorat\n"
        "📆 Har dushanba 09:00 — Haftalik stat (guruhga)\n"
        "🗓 Har oyning 1-si 09:00 — Oylik stat (guruhga)",
        parse_mode="HTML"
    )
    with contextlib.suppress(Exception):
        await message.delete()
    await asyncio.sleep(40)
    with contextlib.suppress(Exception):
        await sent.delete()


@router.message(Command("debug_reklama"))
async def cmd_debug(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    try:
        def _read():
            data = _ws().get_all_records()
            today = today_str()
            counts = {
                str(r.get("Telegram ID", "")): r.get(today, 0)
                for r in data
                if str(r.get("Telegram ID", "")).strip()
            }
            return counts

        counts = await asyncio.get_event_loop().run_in_executor(None, _read)
        detail = "\n".join(f"  {k}: {v}" for k, v in list(counts.items())[:10])
        sheet_info = f"Sheets bugun ({today_str()}):\n{detail}"
    except Exception as e:
        sheet_info = f"Sheets xato: {e}"

    await message.answer(
        f"🔧 <b>Debug</b>\n\n"
        f"Chat: <code>{message.chat.id}</code>\n"
        f"GROUP_ID: <code>{GROUP_ID}</code>\n"
        f"Match: {'✅' if message.chat.id == GROUP_ID else '❌'}\n\n"
        f"{sheet_info}",
        parse_mode="HTML"
    )
