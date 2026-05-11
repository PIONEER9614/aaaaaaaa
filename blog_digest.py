"""
블로그 일간/주간/월간 다이제스트
- 매일 오전 7시: 전날 글 요약 → PDF 전송
- 매주 월요일 오전 7시: 주간 총정리 → PDF 전송
- 매월 1일 오전 7시: 월간 총정리 → PDF 전송
"""

import os, re, io, time, requests, feedparser
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "").strip()

BLOGS = {
    "seanhong99":          "숀홍 시장정리",
    "fullmoon2050":        "보름달 시황/상한가",
    "james_lee_advisors":  "James Lee 거시경제",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
KST = timezone(timedelta(hours=9))

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates  = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",     "C:/Windows/Fonts/malgun.ttf"]
    bold_c      = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR",   font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

# ── 텔레그램 ──────────────────────────────────────────────────────────────────
def send_text(msg):
    if not TELEGRAM_TOKEN:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT, "text": msg[:4000], "parse_mode": "HTML"},
        timeout=15,
    )

def send_pdf(buf, filename, caption=""):
    if not TELEGRAM_TOKEN:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT, "caption": caption[:1000]},
            files={"document": (filename, buf, "application/pdf")},
            timeout=60,
        )
        if not r.ok:
            print(f"[PDF 오류] {r.text[:200]}")
    except Exception as e:
        print(f"[PDF 예외] {e}")

# ── PDF 빌더 ──────────────────────────────────────────────────────────────────
def build_pdf(title_str, subtitle_str, sections):
    """
    sections: [{"heading": str, "body": str, "items": [(label, text, link), ...]}, ...]
    """
    fn, fnb = setup_font()

    def S(nm, **kw):  return ParagraphStyle(nm, fontName=fn,  **kw)
    def SB(nm, **kw): return ParagraphStyle(nm, fontName=fnb, **kw)

    ST = {
        "title":  SB("ti", fontSize=18, leading=24, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":    S ("su", fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":     SB("h2", fontSize=12, leading=17, spaceBefore=12,spaceAfter=5, textColor=colors.HexColor("#1a3a5c")),
        "h3":     SB("h3", fontSize=9,  leading=14, spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#c0392b")),
        "body":   S ("bo", fontSize=8,  leading=13, spaceAfter=3,  textColor=colors.HexColor("#222")),
        "bullet": S ("bl", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#333"), leftIndent=10),
        "link":   SB("lk", fontSize=8,  leading=12, spaceAfter=4,  textColor=colors.HexColor("#1a6fb5")),
        "note":   S ("no", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm,  bottomMargin=1.8*cm)
    story = []

    story.append(Paragraph(title_str,    ST["title"]))
    story.append(Paragraph(subtitle_str, ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    for sec in sections:
        if sec.get("heading"):
            story.append(Paragraph(sec["heading"], ST["h2"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaa")))

        # 자유 텍스트 body
        if sec.get("body"):
            for line in sec["body"].split("\n"):
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 0.1*cm))
                elif line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.",
                                      "📈", "📊", "🏭", "🌍", "💡", "⚠️", "📋", "━")):
                    story.append(Paragraph(line, ST["h3"]))
                elif line.startswith(("•", "-", "·")):
                    story.append(Paragraph(line, ST["bullet"]))
                else:
                    story.append(Paragraph(line, ST["body"]))

        # 아이템 리스트 (제목+요약+링크)
        for item in sec.get("items", []):
            label, text, link = item
            story.append(Spacer(1, 0.15*cm))
            # 블로그명 태그
            tag_data = [[Paragraph(f"📌 {label}", ST["h3"])]]
            tag_t = Table(tag_data, colWidths=[doc.width])
            tag_t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#EBF5FB")),
                ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#2980B9")),
                ("LEFTPADDING",   (0,0),(-1,-1), 8),
                ("TOPPADDING",    (0,0),(-1,-1), 3),
                ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ]))
            story.append(tag_t)

            if link:
                story.append(Paragraph(
                    f'<a href="{link}" color="#1a6fb5"><u>{text.split(chr(10))[0][:80]}</u></a>',
                    ST["link"]
                ))
            for i, line in enumerate(text.split("\n")):
                if i == 0 and link:
                    continue  # 링크로 이미 표시
                line = line.strip()
                if line:
                    story.append(Paragraph(line, ST["bullet"]))
            if link:
                story.append(Paragraph(
                    f'<a href="{link}" color="#888"><font size="7">▶ 원문 보기</font></a>',
                    ST["note"]
                ))
            story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ddd")))

        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    buf.seek(0)
    return buf

# ── RSS 수집 ──────────────────────────────────────────────────────────────────
def parse_pub_date(entry):
    import calendar
    t = entry.get("published_parsed")
    if t:
        return datetime.fromtimestamp(calendar.timegm(t), tz=KST)
    return None

def fetch_posts_in_range(blog_id, date_from, date_to):
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"[RSS 오류] {blog_id}: {e}")
        return []
    results = []
    for entry in feed.entries:
        pub = parse_pub_date(entry)
        if pub is None:
            continue
        pub_date = pub.date()
        if date_from <= pub_date <= date_to:
            results.append({
                "title":   entry.get("title", "").strip(),
                "link":    entry.get("link", ""),
                "date":    pub_date.isoformat(),
                "summary": entry.get("summary", ""),
            })
    return results

def fetch_post_content(link, max_chars=2000):
    try:
        mobile_url = link.replace("blog.naver.com", "m.blog.naver.com")
        r = requests.get(mobile_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for sel in [".se-main-container", ".post-view", "#postViewArea", ".blog-post"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                return re.sub(r"\n{3,}", "\n\n", text)[:max_chars]
        return ""
    except Exception as e:
        print(f"[스크래핑 오류] {link[:60]}: {e}")
        return ""

# ── AI 요약 ───────────────────────────────────────────────────────────────────
def ai_summarize(prompt, max_tokens=1200):
    client = Groq(api_key=GROQ_API_KEY)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Groq 오류 {attempt+1}] {e}")
            time.sleep(5)
    return "(AI 요약 실패)"

# ── 일간 ──────────────────────────────────────────────────────────────────────
def run_daily(target_date):
    print(f"\n[일간] {target_date}")
    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, target_date, target_date)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print(f"  {target_date} 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    sections = []
    for p in all_posts:
        body = p["content"] or p["summary"] or p["title"]
        prompt = f"""주식 블로그 글을 5줄로 요약해줘. 핵심 종목명, 수치, 시장 판단 위주로.
블로그: {p['blog_name']}
제목: {p['title']}
내용:
{body[:1500]}
요약 (5줄):"""
        summary = ai_summarize(prompt, max_tokens=400)
        time.sleep(1)

        full_text = f"{p['title']}\n{summary}"
        sections.append({
            "items": [(p["blog_name"], full_text, p["link"])]
        })

    date_str = target_date.strftime("%Y년 %m월 %d일")
    buf = build_pdf(
        f"📰 블로그 일간 다이제스트",
        f"{date_str}  ·  {len(all_posts)}건",
        sections,
    )
    filename = f"blog_daily_{target_date.strftime('%Y%m%d')}.pdf"
    send_pdf(buf, filename, caption=f"📰 {date_str} 블로그 요약 ({len(all_posts)}건)")
    print(f"  일간 PDF 전송 완료")

# ── 주간 ──────────────────────────────────────────────────────────────────────
def run_weekly(week_end):
    week_start = week_end - timedelta(days=6)
    print(f"\n[주간] {week_start} ~ {week_end}")

    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, week_start, week_end)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print("  이번 주 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    combined = ""
    for p in all_posts:
        body = (p["content"] or p["summary"] or "")[:600]
        combined += f"\n[{p['date']} | {p['blog_name']}] {p['title']}\n{body}\n"

    prompt = f"""다음은 이번 주({week_start} ~ {week_end}) 주식 블로그 3곳의 글 모음입니다.
아래 형식으로 이번 주 시장 흐름을 정리해줘:

1. 이번 주 전반적인 시장 흐름 (3줄)
2. 자주 언급된 주요 종목 TOP5 (각 1줄)
3. 섹터별 동향 (반도체/방산/2차전지 등 언급된 것 위주, 3줄)
4. 블로거들이 공통적으로 주목한 포인트 (2줄)
5. 다음 주 주목할 이슈 (2줄)

블로그 내용:
{combined[:4000]}"""

    analysis = ai_summarize(prompt, max_tokens=1000)

    # 글 목록 텍스트
    post_list = "\n".join(f"• [{p['date']}] {p['blog_name']}: {p['title'][:40]}" for p in all_posts)

    sections = [
        {"heading": "📊 주간 시장 분석", "body": analysis},
        {"heading": f"📝 이번 주 글 목록 ({len(all_posts)}건)", "body": post_list},
    ]

    period = f"{week_start.strftime('%m.%d')} ~ {week_end.strftime('%m.%d')}"
    buf = build_pdf(
        f"📊 블로그 주간 다이제스트",
        f"{period}  ·  {len(all_posts)}건",
        sections,
    )
    filename = f"blog_weekly_{week_end.strftime('%Y%m%d')}.pdf"
    send_pdf(buf, filename, caption=f"📊 주간 블로그 총정리 {period}")
    print("  주간 PDF 전송 완료")

# ── 월간 ──────────────────────────────────────────────────────────────────────
def run_monthly(year, month):
    import calendar as cal
    last_day    = cal.monthrange(year, month)[1]
    month_start = datetime(year, month, 1).date()
    month_end   = datetime(year, month, last_day).date()
    print(f"\n[월간] {year}년 {month}월")

    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, month_start, month_end)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print("  이번 달 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    combined = ""
    for p in all_posts:
        body = (p["content"] or p["summary"] or "")[:300]
        combined += f"\n[{p['date']} | {p['blog_name']}] {p['title']}\n{body}\n"

    prompt = f"""다음은 {year}년 {month}월 한 달간 주식 블로그 3곳의 글 모음입니다.
아래 형식으로 이번 달 시장을 정리해줘:

1. 이번 달 전반적인 시장 흐름 (4줄)
2. 이달의 핵심 테마/섹터 (3줄)
3. 자주 등장한 주요 종목 TOP7 (각 1줄 설명)
4. 이달 최대 이슈/사건 (3줄)
5. 다음 달 주목해야 할 포인트 (3줄)

블로그 내용:
{combined[:5000]}"""

    analysis = ai_summarize(prompt, max_tokens=1200)

    post_list = "\n".join(
        f"• [{p['date']}] {p['blog_name']}: {p['title'][:40]}"
        for p in sorted(all_posts, key=lambda x: x["date"])
    )

    sections = [
        {"heading": "📅 월간 시장 분석", "body": analysis},
        {"heading": f"📝 이번 달 글 목록 ({len(all_posts)}건)", "body": post_list},
    ]

    buf = build_pdf(
        f"📅 블로그 월간 다이제스트",
        f"{year}년 {month}월  ·  {len(all_posts)}건",
        sections,
    )
    filename = f"blog_monthly_{year}{month:02d}.pdf"
    send_pdf(buf, filename, caption=f"📅 {year}년 {month}월 블로그 월간 총정리")
    print("  월간 PDF 전송 완료")

# ── 메인 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    now       = datetime.now(tz=KST)
    today     = now.date()
    yesterday = today - timedelta(days=1)

    print(f"블로그 다이제스트 실행: {now.strftime('%Y-%m-%d %H:%M')} KST")
    print(f"대상 블로그: {', '.join(BLOGS.values())}")

    run_daily(yesterday)

    if today.weekday() == 0:
        run_weekly(yesterday)

    if today.day == 1:
        last_month = today.replace(day=1) - timedelta(days=1)
        run_monthly(last_month.year, last_month.month)

    print("\n완료")
