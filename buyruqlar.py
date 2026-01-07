from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
import os
from dotenv import load_dotenv

load_dotenv()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

async def set_bot_commands(bot: Bot):
    """Bot menyusiga komandalarni o‘rnatadi"""
    # Umumiy foydalanuvchilar uchun komandalar
    default_commands = [
        BotCommand(command="start", description="Botni ishga tushurish"),
        BotCommand(command="kredit_turlari", description="Kredit turlarini ko‘rish"),
        BotCommand(command="manzil", description="Bizning manzilimiz"),
        BotCommand(command="valyuta", description="Valyuta kursi"),
        BotCommand(command="vakansiya", description="Vakansiya"),
    ]

    # Faqat admin uchun komandalar
    admin_commands = [
        BotCommand(command="kredit", description="Credit calculator"),
        BotCommand(command="job", description="vakansiya qo'shish"),
        BotCommand(command="chanel", description="majburiy obuna qo'shish"),
    ]

    # Barcha komandalar (umumiy + admin) admin chatida ko'rinishi uchun
    all_commands_for_admin = default_commands + admin_commands

    # Umumiy komandalar hamma uchun o'rnatish
    await bot.set_my_commands(commands=default_commands, scope=BotCommandScopeDefault())

    # Admin chatida barcha komandalarni o'rnatish
    if ADMIN_ID != 0:  # ADMIN_ID o'rnatilganligini tekshirish
        await bot.set_my_commands(commands=all_commands_for_admin, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    else:
        print("Xato: ADMIN_ID .env faylida o'rnatilmagan!")
