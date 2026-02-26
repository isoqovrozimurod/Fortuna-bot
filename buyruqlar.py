"""
Bot buyruqlari sozlamalari
- Oddiy foydalanuvchilar uchun
- Admin uchun
- Reklama guruhi uchun
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
import os
from dotenv import load_dotenv

load_dotenv()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))


async def set_bot_commands(bot: Bot):
    """Bot menyusiga komandalarni o'rnatadi"""

    # =================== UMUMIY FOYDALANUVCHILAR ===================
    default_commands = [
        BotCommand(command="start",         description="Botni ishga tushurish"),
        BotCommand(command="kredit_turlari", description="Kredit turlarini ko'rish"),
        BotCommand(command="manzil",         description="Bizning manzilimiz"),
        BotCommand(command="valyuta",        description="Valyuta kursi"),
        BotCommand(command="vakansiya",      description="Vakansiya"),
        BotCommand(command="filiallar",      description="Filiallar xaritasi"),
    ]

    # =================== ADMIN BUYRUQLARI ===================
    admin_commands = [
        BotCommand(command="kredit",      description="Kredit kalkulyator"),
        BotCommand(command="job",         description="Vakansiya qo'shish"),
        BotCommand(command="chanel",      description="Majburiy obuna qo'shish"),
        BotCommand(command="broadcast",   description="Ommaviy xabar yuborish"),
        BotCommand(command="cleanup_users", description="Foydalanuvchilar jadvalini tozalash"),
        BotCommand(command="download",      description="Ma'lumot va fayllarni yuklab olish"),
        BotCommand(command="filiallar",   description="Filiallar ro'yxati"),
        BotCommand(command="refresh_branches", description="Filiallarni yangilash"),
    ]

    # =================== GURUH BUYRUQLARI ===================
    group_commands = [
        BotCommand(command="start_register",   description="Ro'yxatdan o'tkazish"),
        BotCommand(command="reklama_tekshir",  description="Qo'lda tekshirish"),
        BotCommand(command="reklama_stat",     description="Statistika"),
        BotCommand(command="reklama_users",    description="Foydalanuvchilar"),
        BotCommand(command="reklama_help",     description="Yordam"),
    ]

    # =================== O'RNATISH ===================

    # 1. Barcha foydalanuvchilar uchun (default)
    await bot.set_my_commands(
        commands=default_commands,
        scope=BotCommandScopeDefault()
    )
    print("✅ Umumiy buyruqlar o'rnatildi")

    # 2. Admin uchun (default + admin buyruqlari)
    if ADMIN_ID != 0:
        all_admin_commands = default_commands + admin_commands
        await bot.set_my_commands(
            commands=all_admin_commands,
            scope=BotCommandScopeChat(chat_id=ADMIN_ID)
        )
        print(f"✅ Admin buyruqlari o'rnatildi (ID: {ADMIN_ID})")
    else:
        print("⚠️ ADMIN_ID .env faylida o'rnatilmagan!")

    # 3. Reklama guruhi uchun
    if GROUP_ID != 0:
        try:
            await bot.set_my_commands(
                commands=group_commands,
                scope=BotCommandScopeChat(chat_id=GROUP_ID)
            )
            print(f"✅ Guruh buyruqlari o'rnatildi (ID: {GROUP_ID})")
        except Exception as e:
            print(f"⚠️ Guruh buyruqlarini o'rnatishda xato: {e}")
    else:
        print("⚠️ GROUP_ID .env faylida o'rnatilmagan!")

    print("🎉 Barcha buyruqlar muvaffaqiyatli o'rnatildi!")


async def remove_group_commands(bot: Bot):
    """Guruh buyruqlarini o'chirish (kerak bo'lsa)"""
    if GROUP_ID != 0:
        try:
            await bot.delete_my_commands(
                scope=BotCommandScopeChat(chat_id=GROUP_ID)
            )
            print(f"🗑 Guruh buyruqlari o'chirildi (ID: {GROUP_ID})")
        except Exception as e:
            print(f"⚠️ Guruh buyruqlarini o'chirishda xato: {e}")
