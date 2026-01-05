from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.enums import ChatMemberStatus
import re

router = Router()

# Linklarni aniqlash uchun regex
LINK_REGEX = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/)",
    re.IGNORECASE
)

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def delete_links_from_non_admins(message: Message, bot: Bot):
    # Matn bo‘lmasa – chiqib ketamiz
    if not message.text:
        return

    # Link bo‘lmasa – tegmaymiz
    if not LINK_REGEX.search(message.text):
        return

    # Foydalanuvchi statusini tekshiramiz
    member = await bot.get_chat_member(
        chat_id=message.chat.id,
        user_id=message.from_user.id
    )

    # Agar creator yoki admin bo‘lsa – ruxsat
    if member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR
    ):
        return

    # Aks holda – xabarni o‘chiramiz
    try:
        await message.delete()
    except Exception:
        pass
