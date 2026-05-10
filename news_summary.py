"""
뉴스 요약 시스템
- 한국경제(경제/증권), Yahoo Finance
- 평일 오전 8시 + 오후 6시 텔레그램 텍스트 전송
"""

import os, re, time, requests, feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("ARTICLE_BOT_TOKEN") or "").strip()
CHAT_ID    = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_KEY   = (os.getenv("GROQ_API_KEY") or "").strip()

NEWS_FEEDS = {
    "한국경제 경제": "https://www.hankyung.com/feed/economy",
    "한국경제 증권": "https://www.hankyung.com/feed/finance",
    "Yahoo Finance":  "https://finance.yahoo.com/news/rssindex",
}

# ── 유틸 ──────────────────────────────────────────────────────────────────────
def strip_html(text):
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ").replace("&amp;", "&")).strip()

# ── 뉴스 수집 ─────────────────────────────────────────────────────────────────
def fetch_news(rss_url, hours=13):
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "Mozilla/5.0"})
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        articles = []
        for entry in feed.entries[:15]:
            try:
                pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                pass  # 날짜 파싱 실패 시 포함
            articles.append({
                "title":   entry.get("title", "").strip(),
                "link":    entry.get("link", ""),
                "content": strip_html(entry.get("summary", ""))[:200],
            })
        # 최근 기사가 없으면 최신 5개라도 반환
        if not articles:
            articles = [{"title": e.get("title",""), "link": e.get("link",""), "content": ""} for e in feed.entries[:5]]
        return articles
    except Exception as e:
        print(f"[RSS 오류] {rss_url}: {e}")
        return []

# ── AI 요약 ───────────────────────────────────────────────────────────────────
def ai_summarize(source, articles):
    client = Groq(api_key=GROQ_KEY)
    titles = "\n".join(f"- {a['title']}" for a in articles[:8])
    prompt = (
        f"다음은 {source}의 최신 뉴스 제목입니다.\n"
        f"경제·주식 관점에서 핵심 내용을 4줄로 한국어로 요약해주세요. "
        f"숫자나 종목명이 있으면 포함하세요.\n\n{titles}"
    )
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=350,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Groq 오류 {attempt+1}] {e}")
            time.sleep(5)
    return "\n".join(f"• {a['title'][:60]}" for a in articles[:5])

# ── 텔레그램 전송 ─────────────────────────────────────────────────────────────
def send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("[텔레그램] 토큰 없음")
        return
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            if not r.ok:
                print(f"[전송 오류] {r.text[:200]}")
        except Exception as e:
            print(f"[전송 예외] {e}")
        time.sleep(0.3)

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    label = "🌅 오전" if now.hour < 12 else "🌆 오후"
    date_str = now.strftime("%Y년 %m월 %d일")
    print(f"=== 뉴스 요약 시작: {date_str} {now.strftime('%H:%M')} ===")

    lines = [f"📰 <b>경제·주식 뉴스 요약</b>  {label}\n{date_str}\n"]

    for source, rss_url in NEWS_FEEDS.items():
        print(f"  수집: {source}")
        articles = fetch_news(rss_url)
        if not articles:
            print(f"    → 기사 없음")
            continue

        print(f"    → {len(articles)}건 수집, AI 요약 중...")
        summary = ai_summarize(source, articles)
        time.sleep(2)

        lines.append(f"━━━━━━━━━━━━━━━━━━")
        lines.append(f"📌 <b>{source}</b>")
        lines.append(summary)
        lines.append("")
        lines.append("주요 기사:")
        for a in articles[:4]:
            title = a["title"][:55]
            link  = a["link"]
            lines.append(f'• <a href="{link}">{title}</a>')
        lines.append("")

    if len(lines) <= 2:
        print("수집된 뉴스 없음")
        return

    send("\n".join(lines))
    print("완료!")

if __name__ == "__main__":
    main()
