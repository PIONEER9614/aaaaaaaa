"""
글로벌 경제/주식 뉴스 요약 시스템
- 한국경제, Yahoo Finance, BNN Bloomberg, Bloomberg
- 매일 평일 오전 8시 + 오후 6시 PDF로 텔레그램 전송
"""

import os
import re
import io
import time
import requests
import feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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


# ─── 한국어 폰트 ────────────────────────────────────────────────────────
def _find_font(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = _find_font([
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
])
FONT_BOLD_PATH = _find_font([
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
])
FONT_REGISTERED = False

def register_fonts():
    global FONT_REGISTERED
    if FONT_REGISTERED:
        return
    try:
        if FONT_PATH:
            pdfmetrics.registerFont(TTFont("KR", FONT_PATH))
        if FONT_BOLD_PATH:
            pdfmetrics.registerFont(TTFont("KR-Bold", FONT_BOLD_PATH))
        elif FONT_PATH:
            pdfmetrics.registerFont(TTFont("KR-Bold", FONT_PATH))
        FONT_REGISTERED = True
    except Exception as e:
        print(f"[폰트 오류] {e}")


# ─── 유틸 ──────────────────────────────────────────────────────────────
def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


# ─── 뉴스 수집 ─────────────────────────────────────────────────────────
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
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "content": strip_html(str(entry.get("summary", "")))[:300],
                })
            except Exception:
                continue

        if not articles and feed.entries:
            for entry in feed.entries[:5]:
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "content": strip_html(str(entry.get("summary", "")))[:300],
                })

        return articles
    except Exception as e:
        print(f"  [오류] {rss_url}: {e}")
        return []


# ─── AI 요약 ────────────────────────────────────────────────────────────
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


# ─── PDF 생성 ───────────────────────────────────────────────────────────
def generate_news_pdf(news_data, date_str, time_label):
    register_fonts()
    fn = "KR" if FONT_REGISTERED else "Helvetica"
    fnb = "KR-Bold" if FONT_REGISTERED else "Helvetica-Bold"

    styles = {
        "title": ParagraphStyle("title", fontName=fnb, fontSize=17, leading=22,
                                 spaceAfter=6, textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle("subtitle", fontName=fn, fontSize=10, leading=13,
                                    spaceAfter=8, textColor=colors.HexColor("#555555")),
        "h2": ParagraphStyle("h2", fontName=fnb, fontSize=13, leading=17,
                              spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#16213e")),
        "body": ParagraphStyle("body", fontName=fn, fontSize=9, leading=13,
                                spaceAfter=3, textColor=colors.HexColor("#333333")),
        "bullet": ParagraphStyle("bullet", fontName=fn, fontSize=8, leading=12,
                                   spaceAfter=2, textColor=colors.HexColor("#444444"),
                                   leftIndent=10),
        "link": ParagraphStyle("link", fontName=fn, fontSize=7, leading=10,
                                textColor=colors.HexColor("#0066cc"), leftIndent=10),
        "small": ParagraphStyle("small", fontName=fn, fontSize=8, leading=11,
                                  textColor=colors.HexColor("#888888")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story.append(Paragraph("글로벌 경제/주식 뉴스 요약", styles["title"]))
    story.append(Paragraph(f"{time_label} | {date_str}", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3*cm))

    for source_name, data in news_data.items():
        articles = data.get("articles", [])
        summary = data.get("summary", "")

        if not articles:
            continue

        story.append(Paragraph(f"📌 {source_name}", styles["h2"]))

        if summary:
            story.append(Paragraph(summary, styles["body"]))
            story.append(Spacer(1, 0.2*cm))

        story.append(Paragraph("주요 기사:", styles["small"]))
        for a in articles[:5]:
            title = a.get("title", "")[:70]
            link = a.get("link", "")
            story.append(Paragraph(f"• {title}", styles["bullet"]))
            if link:
                story.append(Paragraph(link, styles["link"]))

        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#eeeeee")))
        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── 텔레그램 전송 ──────────────────────────────────────────────────────
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


def send_pdf(pdf_buf, filename, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    resp = requests.post(url,
                         data={"chat_id": CHAT_ID, "caption": caption[:1024]},
                         files={"document": (filename, pdf_buf, "application/pdf")},
                         timeout=60)
    if not resp.ok:
        print(f"  [PDF 오류] {resp.text}")
    return resp.ok


# ─── 메인 ───────────────────────────────────────────────────────────────
def main():
    now = datetime.now()
    time_label = "🌅 오전" if now.hour < 12 else "🌆 오후"
    date_str = now.strftime("%Y년 %m월 %d일")
    date_file = now.strftime("%Y%m%d_%H")
    print(f"=== 뉴스 요약 시작: {date_str} {now.strftime('%H:%M')} ===")

    client = Groq(api_key=GROQ_API_KEY)
    news_data = {}

    for source_name, rss_url in NEWS_FEEDS.items():
        print(f"  수집 중: {source_name}")
        articles = fetch_news(rss_url, hours=12)

        if not articles:
            continue

        time.sleep(4)
        summary = summarize_articles(client, source_name, articles)

        if not summary:
            summary = "\n".join(f"• {a['title'][:60]}" for a in articles[:5])

        news_data[source_name] = {"articles": articles, "summary": summary}

    if not news_data:
        print("  수집된 뉴스 없음")
        return

    # PDF 생성
    print("  PDF 생성 중...")
    pdf = generate_news_pdf(news_data, date_str, time_label)

    # 전송
    total = sum(len(v["articles"]) for v in news_data.values())
    send_message(
        f"📰 <b>글로벌 경제/주식 뉴스</b>\n"
        f"{time_label} | {date_str}\n\n"
        f"• 수집 매체: {len(news_data)}개\n"
        f"• 총 기사: {total}건\n\n"
        f"아래 PDF를 확인하세요 ↓"
    )
    time.sleep(1)
    send_pdf(pdf, f"news_{date_file}.pdf", f"📰 뉴스 요약 {date_str} {time_label}")

    print("  완료!")


if __name__ == "__main__":
    main()
