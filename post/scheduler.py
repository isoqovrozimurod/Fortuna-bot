import os
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from post.fetcher import get_latest_news
from post.ai_service import format_news_post
from post.handlers import get_post_keyboard

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # O'z telegram chat ID'ingiz
LAST_LINK_FILE = "post/last_link.txt"

def get_last_posted_link() -> str:
    if os.path.exists(LAST_LINK_FILE):
        with open(LAST_LINK_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_last_posted_link(link: str):
    with open(LAST_LINK_FILE, "w", encoding="utf-8") as f:
        f.write(link)

async def check_and_send_daily_news(bot: Bot):
    """Har kuni ishga tushadigan asosiy vazifa"""
    if not ADMIN_ID:
        print("[Scheduler Xato] ADMIN_ID topilmadi!")
        return

    articles = get_latest_news()
    if not articles:
        return

    last_link = get_last_posted_link()
    selected_article = None

    # Eng so'nggi va hali yuborilmagan yangilikni tanlash
    for article in articles:
        if article["link"] != last_link:
            selected_article = article
            break

    if not selected_article:
        return  # Yangi maqola yo'q

    # ChatGPT orqali formatlash
    formatted_caption = await format_news_post(
        title=selected_article["title"],
        content=selected_article["summary"]
    )

    # Adminga tasdiqlash uchun yuborish
    if selected_article.get("image"):
        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=selected_article["image"],
                caption=formatted_caption,
                parse_mode="HTML",
                reply_markup=get_post_keyboard()
            )
        except Exception:
            # Agar rasm URL orqali yuklanmasa, oddiy matn qilib yuboradi
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=formatted_caption,
                parse_mode="HTML",
                reply_markup=get_post_keyboard()
            )
    else:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=formatted_caption,
            parse_mode="HTML",
            reply_markup=get_post_keyboard()
        )

    # Oxirgi linkni saqlab qo'yish
    save_last_posted_link(selected_article["link"])

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Schedulerni sozlash va vaqtini belgilash"""
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    
    # Har kuni ertalab soat 09:00 da ishga tushadi
    scheduler.add_job(
        check_and_send_daily_news,
        trigger="cron",
        hour=9,
        minute=0,
        args=[bot]
    )
    
    return scheduler
