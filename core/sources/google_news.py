import urllib.parse

import feedparser

from core.sources import item


def fetch_news(company, lang="th", country="TH", limit=20):
    q = urllib.parse.quote(company)
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang}&gl={country}&ceid={country}:{lang}")
    feed = feedparser.parse(url)
    return [
        {"title": e.title, "url": e.link, "published": e.get("published", ""),
         "publisher": e.get("source", {}).get("title", "")}
        for e in feed.entries[:limit]
    ]


def fetch(company, limit=20):
    return [item("news", it["publisher"], it["title"], it["url"], it["published"])
            for it in fetch_news(company["name"], limit=limit)]
