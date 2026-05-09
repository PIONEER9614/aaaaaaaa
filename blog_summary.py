import os
import re
import requests
import feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

BLOG_RSS_FEEDS = [
    "https://rss.blog.naver.com/pokara61.xml",
]


def strip_html(html):
    return re.sub(re.compile("<.*?>"), "", html).strip()


def fetch_recent_posts(rss_url, hours=24):
    feed = feedparser.parse(rss_url)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []

    for entry in feed.entries:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published >= cutoff:
                content = entry.get("summary", "") or entry.get("description", "")
                recent.append({
                    "title": entry.title,
                    "link": entry.link,
                    "content": strip_html(content)[:3000],
                })
        except Exception:
            continue

    # 오늘 새 글이 없으면 최신 글 1개라도 포함
    if not recent and feed.entries:
        entry = feed.entries[0]
        content = entry.get("summary", "") or entry.get("description", "")
        recent.append({
            "title": entry.title,
            "link": entry.link,
            "content": strip_html(content)[:3000],
        })

    return recent


def summarize_with_groq(all_posts):
    client = Groq(api_key=GROQ_API_KEY)

    if not all_posts:
        return "오늘 가져올 포스트가 없습니다."

    posts_text = ""
    for p in all_posts:
        posts_text += f"\n[제목] {p['title']}\n[링크] {p['link']}\n[내용]\n{p['content']}\n{'=' * 40}\n"

    prompt = (
        "다음 블로그 포스트를 한국어로 요약해주세요.\n"
        "각 포스트마다:\n"
        "- 핵심 내용 3~5줄 요약\n"
        "- 중요 포인트 bullet point\n\n"
        f"{posts_text}"
    )

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
    )
    return response.choices[0].message.content


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if len(message) > 4000:
        message = message[:4000] + "...\n\n(내용이 길어 일부 생략)"
    response = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    })
    return response.ok


def main():
    today = datetime.now().strftime("%Y년 %m월 %d일")
    all_posts = []

    for rss_url in BLOG_RSS_FEEDS:
        posts = fetch_recent_posts(rss_url)
        all_posts.extend(posts)

    summary = summarize_with_groq(all_posts)
    message = f"블로그 일일 요약 - {today}\n\n{summary}"

    if send_telegram(message):
        print("텔레그램 전송 완료")
    else:
        print("텔레그램 전송 실패")


if __name__ == "__main__":
    main()
