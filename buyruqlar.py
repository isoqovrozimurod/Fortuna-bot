"""
Bot buyruqlari sozlamalari
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
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
        BotCommand(command="reklama_tozala",   description="Dublikat ustunlarni tozalash"),
        BotCommand(command="filiallar",        description="Filiallar ro'yxati"),
        BotCommand(command="refresh_branches", description="Filiallarni yangilash"),
        scoring_command,
    ]

    group_commands = [
        BotCommand(command="start_register",  description="Ro'yxatdan o'tkazish"),
        BotCommand(command="reklama_tekshir", description="Qo'lda tekshirish"),
        BotCommand(command="reklama_stat",    description="Statistika"),
        BotCommand(command="reklama_users",   description="Foydalanuvchilar"),
        BotCommand(command="reklama_help",    description="Yordam"),
        BotCommand(command="reklama_reyting", description="Oylik reyting 🏆"),
    ]

    # Scoring + default — sub_adminlar va JOB_ID uchun
    subadmin_commands = default_commands + [scoring_command]

    # ── O'rnatish ─────────────────────────────────────────────────
    await bot.set_my_commands(commands=default_commands, scope=BotCommandScopeDefault())
    print("✅ Umumiy buyruqlar o'rnatildi")

    if ADMIN_ID:
        await bot.set_my_commands(
            commands=default_commands + admin_commands,
            scope=BotCommandScopeChat(chat_id=ADMIN_ID)
        )
        print(f"✅ Admin buyruqlari o'rnatildi (ID: {ADMIN_ID})")

    if JOB_ID:
        try:
            await bot.set_my_commands(
                commands=subadmin_commands,
                scope=BotCommandScopeChat(chat_id=JOB_ID)
            )
            print(f"✅ JOB_ID buyruqlari o'rnatildi (ID: {JOB_ID})")
        except Exception as e:
            print(f"⚠️ JOB_ID buyruqlarini o'rnatishda xato: {e}")

    if GROUP_ID:
        try:
            await bot.set_my_commands(
                commands=group_commands,
                scope=BotCommandScopeChat(chat_id=GROUP_ID)
            )
            print(f"✅ Guruh buyruqlari o'rnatildi (ID: {GROUP_ID})")
        except Exception as e:
            print(f"⚠️ Guruh buyruqlarini o'rnatishda xato: {e}")

    # Sub_adminlar uchun alohida
    loop = asyncio.get_running_loop()
    subadmin_ids = await loop.run_in_executor(None, _get_subadmin_ids)
    for uid in subadmin_ids:
        if uid in (ADMIN_ID, JOB_ID):
            continue  # allaqachon o'rnatilgan
        try:
            await bot.set_my_commands(
                commands=subadmin_commands,
                scope=BotCommandScopeChat(chat_id=uid)
            )
        except Exception as e:
            logger.warning(f"Sub-admin {uid} buyruq o'rnatishda xato: {e}")

    count = len(subadmin_ids)
    print(f"✅ Sub-adminlar ({count} ta) uchun /scoring qo'shildi")
    print("🎉 Barcha buyruqlar muvaffaqiyatli o'rnatildi!")


async def remove_group_commands(bot: Bot):
    if GROUP_ID:
        try:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=GROUP_ID))
            print(f"🗑 Guruh buyruqlari o'chirildi (ID: {GROUP_ID})")
        except Exception as e:
            print(f"⚠️ Guruh buyruqlarini o'chirishda xato: {e}")
