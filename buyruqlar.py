"""
Bot buyruqlari sozlamalari
"""
from aiogram import Bot, Router, types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    BotCommandScopeAllGroupChats,
)
import os
import asyncio
import base64
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
JOB_ID   = int(os.getenv("JOB_ID",   "0"))

SPREADSHEET_ID = "1UU87w2q9zk8q5_3pQqfVhp0Zp2hnU70bWWgu1R9q3No"
SUBADMIN_SHEET = "sub_adminlar"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

_gc = None

def _get_gc():
    global _gc
    if _gc is None:
        b64   = os.getenv("GOOGLE_CREDENTIALS_B64")
        info  = json.loads(base64.b64decode(b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        _gc   = gspread.authorize(creds)
    return _gc

def _get_subadmin_ids() -> list[int]:
    try:
        gc  = _get_gc()
        ws  = gc.open_by_key(SPREADSHEET_ID).worksheet(SUBADMIN_SHEET)
        ids = ws.col_values(2)[1:]
        result = []
        for v in ids:
            try:
                result.append(int(str(v).strip()))
            except (ValueError, TypeError):
                pass
        return result
    except Exception as e:
        logger.error(f"Sub-admin IDlarni olishda xato: {e}")
        return []


# ─── DIAGNOSTIKA: guruhning haqiqiy chat_id sini ko'rsatadi ───────────
# Guruhga yozib, /chatid buyrug'ini yuboring. .env dagi GROUP_ID bilan
# solishtiring. Mos kelmasa — shu yer muammo manbai.

diag_router = Router()

@diag_router.message(Command("chatid"))
async def cmd_chatid(message: types.Message):
    actual_id     = message.chat.id
    configured_id = GROUP_ID
    match         = "✅ MOS KELADI" if actual_id == configured_id else "❌ MOS KELMAYDI!"
    await message.answer(
        f"🆔 <b>Chat ID diagnostikasi</b>\n\n"
        f"Haqiqiy chat_id: <code>{actual_id}</code>\n"
        f"Chat turi: <code>{message.chat.type}</code>\n"
        f".env dagi GROUP_ID: <code>{configured_id}</code>\n\n"
        f"{match}\n\n"
        f"<i>Mos kelmasa, .env dagi GROUP_ID ni yuqoridagi "
        f"haqiqiy qiymatga o'zgartiring va botni qayta ishga tushiring.</i>",
        parse_mode="HTML",
    )


async def set_bot_commands(bot: Bot):
    # ── Buyruqlar ro'yxatlari ──────────────────────────────────────
    default_commands = [
        BotCommand(command="start",          description="Botni ishga tushurish"),
        BotCommand(command="kredit_turlari", description="Kredit turlarini ko'rish"),
        BotCommand(command="manzil",         description="Bizning manzilimiz"),
        BotCommand(command="valyuta",        description="Valyuta kursi"),
        BotCommand(command="vakansiya",      description="Vakansiya"),
        BotCommand(command="filiallar",      description="Filiallar xaritasi"),
    ]

    scoring_command = BotCommand(command="scoring", description="Scoring — qarz yuki hisoblash")

    admin_commands = [
        BotCommand(command="kredit",           description="Kredit kalkulyator"),
        BotCommand(command="job",              description="Vakansiya qo'shish"),
        BotCommand(command="chanel",           description="Majburiy obuna qo'shish"),
        BotCommand(command="broadcast",        description="Ommaviy xabar yuborish"),
        BotCommand(command="cleanup_users",    description="Foydalanuvchilar jadvalini tozalash"),
        BotCommand(command="download",         description="Ma'lumot va fayllarni yuklab olish"),
        BotCommand(command="reklama_stat",     description="Reklama statistikasi"),
        BotCommand(command="sync_subadmin",    description="User dan sub_admin ga sinxronlash"),
        BotCommand(command="reklama_tozala",   description="Oylarga birlashtirish + tozalash"),
        BotCommand(command="filiallar",        description="Filiallar ro'yxati"),
        BotCommand(command="refresh_branches", description="Filiallarni yangilash"),
        BotCommand(command="guruhlar",         description="Bot admin bo'lgan guruhlar ro'yxati"),
        BotCommand(command="guruhlar_tekshir", description="Guruhlar holatini qo'lda tekshirish"),
        scoring_command,
    ]

    group_commands = [
        BotCommand(command="start_register",  description="Ro'yxatdan o'tkazish"),
        BotCommand(command="reklama_tekshir", description="Qo'lda tekshirish"),
        BotCommand(command="reklama_stat",    description="Statistika"),
        BotCommand(command="reklama_users",   description="Foydalanuvchilar"),
        BotCommand(command="reklama_help",    description="Yordam"),
        BotCommand(command="reklama_reyting", description="Oylik reyting 🏆"),
        BotCommand(command="chatid",          description="Chat ID diagnostikasi"),
    ]

    # Scoring + default — sub_adminlar va JOB_ID uchun
    subadmin_commands = default_commands + [scoring_command]

    # Bot admin qilingan ISTALGAN guruhda ko'rinishi kerak — faqat
    # GROUP_ID (asosiy Fortuna guruhi) emas, shuning uchun alohida
    # BotCommandScopeAllGroupChats() ishlatiladi.
    all_groups_commands = [
        BotCommand(command="link_sozlama", description="Havola (reklama) nazorati sozlamasi"),
    ]

    # ── O'rnatish ─────────────────────────────────────────────────
    await bot.set_my_commands(commands=default_commands, scope=BotCommandScopeDefault())
    logger.info("✅ Umumiy buyruqlar o'rnatildi")

    if ADMIN_ID:
        try:
            await bot.set_my_commands(
                commands=default_commands + admin_commands,
                scope=BotCommandScopeChat(chat_id=ADMIN_ID)
            )
            logger.info(f"✅ Admin buyruqlari o'rnatildi (ID: {ADMIN_ID})")
        except Exception as e:
            logger.error(f"⚠️ Admin buyruqlarini o'rnatishda xato: {e}")

    if JOB_ID:
        try:
            await bot.set_my_commands(
                commands=subadmin_commands,
                scope=BotCommandScopeChat(chat_id=JOB_ID)
            )
            logger.info(f"✅ JOB_ID buyruqlari o'rnatildi (ID: {JOB_ID})")
        except Exception as e:
            logger.error(f"⚠️ JOB_ID buyruqlarini o'rnatishda xato: {e}")

    if GROUP_ID:
        try:
            await bot.set_my_commands(
                commands=group_commands,
                scope=BotCommandScopeChat(chat_id=GROUP_ID)
            )
            logger.info(f"✅ Guruh buyruqlari o'rnatildi (ID: {GROUP_ID})")
        except Exception as e:
            # MUHIM: bu xato ko'pincha GROUP_ID noto'g'ri (masalan
            # guruh supergruppaga aylanib, chat_id o'zgargan) bo'lganda
            # chiqadi. "chat not found" xabari aynan shu sababdan.
            logger.error(
                f"⚠️ Guruh buyruqlarini o'rnatishda xato "
                f"(GROUP_ID={GROUP_ID} noto'g'ri bo'lishi mumkin): {e}"
            )
    else:
        logger.warning("⚠️ GROUP_ID sozlanmagan — guruh buyruqlari o'rnatilmadi")

    try:
        await bot.set_my_commands(
            commands=all_groups_commands, scope=BotCommandScopeAllGroupChats()
        )
        logger.info("✅ /link_sozlama barcha guruhlar uchun o'rnatildi")
    except Exception as e:
        logger.error(f"⚠️ BotCommandScopeAllGroupChats o'rnatishda xato: {e}")

    # Sub_adminlar uchun alohida
    loop = asyncio.get_running_loop()
    subadmin_ids = await loop.run_in_executor(None, _get_subadmin_ids)
    ok_count  = 0
    err_count = 0
    for uid in subadmin_ids:
        if uid in (ADMIN_ID, JOB_ID):
            continue  # allaqachon o'rnatilgan
        try:
            await bot.set_my_commands(
                commands=subadmin_commands,
                scope=BotCommandScopeChat(chat_id=uid)
            )
            ok_count += 1
        except Exception as e:
            err_count += 1
            logger.warning(f"Sub-admin {uid} buyruq o'rnatishda xato: {e}")

    logger.info(f"✅ Sub-adminlar: {ok_count} muvaffaqiyatli, {err_count} xato")
    logger.info("🎉 Barcha buyruqlar o'rnatish jarayoni yakunlandi!")


async def remove_group_commands(bot: Bot):
    if GROUP_ID:
        try:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=GROUP_ID))
            logger.info(f"🗑 Guruh buyruqlari o'chirildi (ID: {GROUP_ID})")
        except Exception as e:
            logger.error(f"⚠️ Guruh buyruqlarini o'chirishda xato: {e}")
