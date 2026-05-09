"""
글로벌 경제/주식 뉴스 요약 시스템
- 한국경제, Yahoo Finance, BNN Bloomberg, Bloomberg
- 매일 오전 8시 + 오후 6시 텔레그램 전송
"""

import os
import re
import time
import requests
import feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("ARTICLE_BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()

NEWS_FEEDS = {
    "한국경제 증권": "https://www.hankyung.com/feed/finance",
    "한국경제 경제": "https://www.hankyung.com/feed/economy",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "BNN Bloomberg": "https://www.bnnbloomberg.ca/rss",
    "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss",
}


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def fetch_news(rss_url, hours=12):
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "Mozilla/5.0"})
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        articles = []

        for entry in feed.entries[:10]:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published < cutoff:
                    continue
                content = strip_html(str(entry.get("summary", "") or ""))
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "content": content[:300],
                })
            except Exception:
                continue

        if not articles and feed.entries:
            for entry in feed.entries[:3]:
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "content": strip_html(str(entry.get("summary", "")))[:300],
                })

        return articles
    except Exception as e:
        print(f"  [오류] {rss_url}: {e}")
        return []


def summarize_articles(client, source_name, articles):
    if not articles:
        return None

    titles = "\n".join(f"- {a['title']}" for a in articles[:8])
    prompt = (
        f"다음은 {source_name}의 최신 뉴스 제목들입니다.\n"
        f"경제/주식 관련 핵심 내용을 3~5줄로 한국어로 요약해주세요.\n\n"
        f"{titles}"
    )

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [Groq 오류] {e}")
            if attempt == 0:
                time.sleep(5)
    return None


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    if not resp.ok:
        print(f"  [전송 오류] {resp.text}")
    return resp.ok


def main():
    now = datetime.now()
    time_label = "🌅 오전" if now.hour < 12 else "🌆 오후"
    date_str = now.strftime("%Y년 %m월 %d일")
    print(f"=== 뉴스 요약 시작: {date_str} {now.strftime('%H:%M')} ===")

    client = Groq(api_key=GROQ_API_KEY)

    send_message(
        f"📰 <b>글로벌 경제/주식 뉴스 요약</b>\n"
        f"{time_label} | {date_str}"
    )
    time.sleep(1)

    for source_name, rss_url in NEWS_FEEDS.items():
        print(f"  수집 중: {source_name}")
        articles = fetch_news(rss_url, hours=12)

        if not articles:
            continue

        time.sleep(4)
        summary = summarize_articles(client, source_name, articles)

        if not summary:
            summary = "\n".join(f"• {a['title'][:60]}" for a in articles[:5])

        links = "\n".join(
            f"<a href='{a['link']}'>{a['title'][:45]}...</a>"
            for a in articles[:3] if a.get("link")
        )

        send_message(
            f"<b>📌 {source_name}</b>\n\n"
            f"{summary}\n\n"
            f"{links}"
        )
        time.sleep(2)

    print("  뉴스 요약 완료!")


if __name__ == "__main__":
    main()
