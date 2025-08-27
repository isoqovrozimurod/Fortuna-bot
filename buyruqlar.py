from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault


async def set_bot_commands(bot: Bot):
    """Bot menyusiga komandalarni o‘rnatadi"""
    commands = [
        BotCommand(command="start", description="Botni ishga tushurish"),
        BotCommand(command="kredit_turlari", description="Kredit turlarini ko‘rish"),
        BotCommand(command="manzil", description="Bizning manzilimiz"),
        BotCommand(command="kredit", description="Admin uchun"),
    ]

    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
