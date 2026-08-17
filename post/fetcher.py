import feedparser
from bs4 import BeautifulSoup

RSS_FEEDS = [
    "https://www.theverge.com/rss/index.xml",
    "https://techcrunch.com/feed/",
]

def get_latest_news():
    articles = []
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]:
            # Rasmni topish
            image_url = None
            if "media_content" in entry:
                image_url = entry.media_content[0].get("url")
            elif "links" in entry:
                for link in entry.links:
                    if link.get("type", "").startswith("image/"):
                        image_url = link.get("href")
                        break

            # Matnni tozalash
            raw_summary = entry.get("summary", "")
            clean_text = BeautifulSoup(raw_summary, "html.parser").get_text()

            articles.append({
                "title": entry.title,
                "link": entry.link,
                "summary": clean_text,
                "image": image_url
            })
    return articles
