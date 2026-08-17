import os
import aiohttp

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

async def format_news_post(title: str, content: str) -> str:
    prompt = f"""
Siz professional IT jurnalistisiz. Quyidagi IT yangilikni o'zbek tiliga tarjima qiling va Telegram post uchun formatlang.

Qoidalar:
1. Sarlavha boshida <b>...</b> tegi bilan qalin bo'lsin.
2. Muhim iqtibos va tushunchalar <i>...</i> (kursiv) yoki <blockquote>...</blockquote> tegi bilan ajratilsin.
3. Umumiy matn uzunligi (HTML teglari bilan) QAT'IY 850 belgidan oshmasin.
4. Eng oxirida albatta "@isoqovrozimurod_blog" havolasi bo'lsin.
5. Faqat Telegram qabul qiladigan HTML teglaridan foydalaning (<b>, <i>, <code>, <a>, <blockquote>).

Sarlavha: {title}
Matn: {content}
"""

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 600
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                raise RuntimeError(f"OpenAI API xatosi: {data}")
