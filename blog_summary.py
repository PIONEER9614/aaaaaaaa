"""
블로그 일일 요약 → PDF 텔레그램 전송
"""

import os, re, io, requests, feedparser
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from groq import Groq

from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, Table, TableStyle)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "").strip()

BLOG_RSS_FEEDS = [
    "https://rss.blog.naver.com/pokara61.xml",
]

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",     "C:/Windows/Fonts/malgun.ttf"]
    bold_c     = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR",   font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

# ── 텔레그램 ──────────────────────────────────────────────────────────────────
def send_pdf(buf, filename, caption=""):
    if not TELEGRAM_BOT_TOKEN:
        print("[텔레그램] 토큰 없음")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000]},
            files={"document": (filename, buf, "application/pdf")},
            timeout=60,
        )
        if not r.ok:
            print(f"[PDF 오류] {r.text[:200]}")
        return r.ok
    except Exception as e:
        print(f"[PDF 예외] {e}")
        return False

# ── PDF 빌더 ──────────────────────────────────────────────────────────────────
def build_pdf(posts, summary_text, date_str):
    fn, fnb = setup_font()

    def S(nm, **kw):  return ParagraphStyle(nm, fontName=fn,  **kw)
    def SB(nm, **kw): return ParagraphStyle(nm, fontName=fnb, **kw)

    ST = {
        "title":  SB("ti", fontSize=18, leading=24, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":    S ("su", fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":     SB("h2", fontSize=12, leading=17, spaceBefore=12,spaceAfter=5, textColor=colors.HexColor("#1a3a5c")),
        "h3":     SB("h3", fontSize=9,  leading=14, spaceBefore=5, spaceAfter=2, textColor=colors.HexColor("#c0392b")),
        "body":   S ("bo", fontSize=8,  leading=13, spaceAfter=3,  textColor=colors.HexColor("#222")),
        "bullet": S ("bl", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#333"), leftIndent=10),
        "link":   SB("lk", fontSize=8,  leading=12, spaceAfter=6,  textColor=colors.HexColor("#1a6fb5")),
        "note":   S ("no", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm,  bottomMargin=1.8*cm)
    story = []
    W = doc.width

    story.append(Paragraph("📝 블로그 일일 요약", ST["title"]))
    story.append(Paragraph(f"{date_str}  ·  {len(posts)}건", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # AI 종합 요약
    story.append(Paragraph("🤖 AI 종합 요약", ST["h2"]))
    for line in summary_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.1*cm))
        elif line.startswith(("•", "-")):
            story.append(Paragraph(line, ST["bullet"]))
        else:
            story.append(Paragraph(line, ST["body"]))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))

    # 개별 포스트
    story.append(Paragraph("📌 포스트 목록", ST["h2"]))
    for p in posts:
        story.append(Spacer(1, 0.15*cm))
        if p.get("link"):
            story.append(Paragraph(
                f'<a href="{p["link"]}" color="#1a6fb5"><u>▶ {p["title"][:80]}</u></a>',
                ST["link"]
            ))
        else:
            story.append(Paragraph(f"▶ {p['title'][:80]}", ST["h3"]))
        story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ddd")))

    doc.build(story)
    buf.seek(0)
    return buf

# ── RSS 수집 ──────────────────────────────────────────────────────────────────
def strip_html(html):
    return re.sub(re.compile("<.*?>"), "", html).strip()

def fetch_recent_posts(rss_url, hours=24):
    feed   = feedparser.parse(rss_url)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for entry in feed.entries:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published >= cutoff:
                content = entry.get("summary", "") or entry.get("description", "")
                recent.append({
                    "title":   entry.title,
                    "link":    entry.link,
                    "content": strip_html(content)[:3000],
                })
        except Exception:
            continue
    if not recent and feed.entries:
        entry   = feed.entries[0]
        content = entry.get("summary", "") or entry.get("description", "")
        recent.append({
            "title":   entry.title,
            "link":    entry.link,
            "content": strip_html(content)[:3000],
        })
    return recent

# ── AI 요약 ───────────────────────────────────────────────────────────────────
def summarize_with_groq(all_posts):
    client = Groq(api_key=GROQ_API_KEY)
    if not all_posts:
        return "오늘 가져올 포스트가 없습니다."

    posts_text = ""
    for p in all_posts:
        posts_text += f"\n[제목] {p['title']}\n[링크] {p['link']}\n[내용]\n{p['content']}\n{'='*40}\n"

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

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    today    = datetime.now().strftime("%Y년 %m월 %d일")
    all_posts = []
    for rss_url in BLOG_RSS_FEEDS:
        all_posts.extend(fetch_recent_posts(rss_url))

    summary = summarize_with_groq(all_posts)
    buf      = build_pdf(all_posts, summary, today)
    filename = f"blog_summary_{datetime.now().strftime('%Y%m%d')}.pdf"

    ok = send_pdf(buf, filename, caption=f"📝 블로그 일일 요약 - {today}")
    print("텔레그램 PDF 전송 완료" if ok else "텔레그램 전송 실패")

if __name__ == "__main__":
    main()
