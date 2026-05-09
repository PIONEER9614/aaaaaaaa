"""
투자 인텔리전스 자동화 시스템
- 매일: 블로그 PDF + 리서치 리포트 PDF → 텔레그램
- 매주 일요일: 주간 종합 PDF
- 매월 1일: 월간 종합 PDF
"""

import os
import re
import time
import io
import requests
import feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from collections import Counter
from dotenv import load_dotenv
from bs4 import BeautifulSoup

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
REPORT_TYPE = (os.getenv("REPORT_TYPE") or "auto").strip()

# ─── 블로그 목록 ─────────────────────────────────────────────────────────
# 블로그 추가 방법: "블로그ID": "https://rss.blog.naver.com/블로그ID.xml"
BLOG_RSS_FEEDS = {
    "pokara61": "https://rss.blog.naver.com/pokara61.xml",
    "audistar": "https://rss.blog.naver.com/audistar.xml",
    "doctordk": "https://rss.blog.naver.com/doctordk.xml",
    "going_tothe_moon": "https://rss.blog.naver.com/going_tothe_moon.xml",
    "chamberine3": "https://rss.blog.naver.com/chamberine3.xml",
    "gangnam_0208": "https://rss.blog.naver.com/gangnam_0208.xml",
    # 아래에 블로그 ID 추가:
    # "blogger5": "https://rss.blog.naver.com/blogger5.xml",
    # "blogger6": "https://rss.blog.naver.com/blogger6.xml",
    # "blogger7": "https://rss.blog.naver.com/blogger7.xml",
    # "blogger8": "https://rss.blog.naver.com/blogger8.xml",
    # "blogger9": "https://rss.blog.naver.com/blogger9.xml",
    # "blogger10": "https://rss.blog.naver.com/blogger10.xml",
}


# ─── 한국어 폰트 설정 ──────────────────────────────────────────────────
def _find_font(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = _find_font([
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/gulim.ttc",
])
FONT_BOLD_PATH = _find_font([
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/nanum/NanumGothicBold.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
])

FONT_REGISTERED = False

def register_fonts():
    global FONT_REGISTERED
    if FONT_REGISTERED:
        return True
    try:
        if FONT_PATH:
            pdfmetrics.registerFont(TTFont("KR", FONT_PATH))
        if FONT_BOLD_PATH:
            pdfmetrics.registerFont(TTFont("KR-Bold", FONT_BOLD_PATH))
        else:
            pdfmetrics.registerFont(TTFont("KR-Bold", FONT_PATH or ""))
        FONT_REGISTERED = True
        return True
    except Exception as e:
        print(f"[경고] 한국어 폰트 등록 실패: {e}")
        return False


# ─── 텍스트 유틸 ───────────────────────────────────────────────────────
def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


# ─── 블로그 RSS 수집 ────────────────────────────────────────────────────
def fetch_blog_posts(rss_url, hours=24):
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "Mozilla/5.0"})
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = []

        for entry in feed.entries:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published < cutoff:
                    continue

                content = ""
                for field in ["content", "summary", "description"]:
                    val = entry.get(field, "")
                    if isinstance(val, list) and val:
                        val = val[0].get("value", "")
                    if val:
                        content = strip_html(str(val))
                        break

                recent.append({
                    "title": entry.get("title", "(제목없음)"),
                    "link": entry.get("link", ""),
                    "content": content[:500],
                    "published": published,
                })
            except Exception:
                continue

        # 오늘 새글 없으면 최신 1개 포함
        if not recent and feed.entries:
            entry = feed.entries[0]
            content = strip_html(str(entry.get("summary", "")))
            recent.append({
                "title": entry.get("title", "(제목없음)"),
                "link": entry.get("link", ""),
                "content": content[:500],
                "published": datetime.now(timezone.utc),
            })

        return recent
    except Exception as e:
        print(f"  [오류] RSS 수집 실패 ({rss_url}): {e}")
        return []


# ─── 네이버 증권 리서치 리포트 스크래핑 ─────────────────────────────────
def fetch_naver_research(report_type="company"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    url = f"https://finance.naver.com/research/{report_type}_list.nhn"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")

        today = datetime.now().strftime("%Y.%m.%d")
        reports = []

        table = soup.find("table", class_="type_1")
        if not table:
            print(f"  [경고] 리서치 테이블을 찾지 못함 ({report_type})")
            return []

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            try:
                if report_type == "company":
                    stock_name = cells[0].get_text(strip=True)
                    title_tag = cells[1].find("a")
                    firm = cells[2].get_text(strip=True)
                    date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                else:
                    stock_name = ""
                    title_tag = cells[0].find("a")
                    firm = cells[1].get_text(strip=True)
                    date = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                link = ("https://finance.naver.com" + href) if href.startswith("/") else href

                # 오늘 날짜 필터
                if title and (date == today or not date):
                    reports.append({
                        "stock": stock_name,
                        "title": title,
                        "firm": firm,
                        "date": date,
                        "link": link,
                    })
            except Exception:
                continue

        print(f"  네이버 {report_type} 리포트: {len(reports)}건")
        return reports

    except Exception as e:
        print(f"  [오류] 리서치 스크래핑 실패 ({report_type}): {e}")
        return []


# ─── AI 요약 (Groq) ─────────────────────────────────────────────────────
def summarize_post(client, post):
    text = (post.get("content") or post.get("title") or "")[:400]
    if not text:
        return "(내용 없음)", []

    prompt = (
        f"아래 주식 블로그 포스트를 2~3줄로 요약하고, 언급된 한국 종목명을 추출하세요.\n\n"
        f"제목: {post['title']}\n내용: {text}\n\n"
        f"형식 (반드시 이 형식으로):\n"
        f"요약: (2~3줄)\n"
        f"종목: 종목명1, 종목명2 (없으면 '없음')"
    )

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
            )
            result = resp.choices[0].message.content

            summary, stocks = "", []
            for line in result.split("\n"):
                if line.startswith("요약:"):
                    summary = line.replace("요약:", "").strip()
                elif line.startswith("종목:"):
                    s = line.replace("종목:", "").strip()
                    if s and s != "없음":
                        stocks = [x.strip() for x in s.split(",") if x.strip() and x.strip() != "없음"]

            return summary or result[:150], stocks

        except Exception as e:
            print(f"    [Groq 오류] {e}")
            if attempt == 0:
                time.sleep(5)

    # Groq 실패 시 제목만 반환
    return post["title"][:80], []


# ─── 종목 빈도 분석 ─────────────────────────────────────────────────────
def analyze_frequency(stock_list, top_n=20):
    cleaned = [s for s in stock_list if len(s) >= 2 and not s.isdigit()]
    return Counter(cleaned).most_common(top_n)


# ─── PDF 스타일 ─────────────────────────────────────────────────────────
def make_styles():
    fn = "KR" if FONT_REGISTERED else "Helvetica"
    fnb = "KR-Bold" if FONT_REGISTERED else "Helvetica-Bold"

    return {
        "title": ParagraphStyle("title", fontName=fnb, fontSize=17, leading=22,
                                 spaceAfter=8, textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle("subtitle", fontName=fn, fontSize=10, leading=13,
                                    spaceAfter=6, textColor=colors.HexColor("#555555")),
        "h2": ParagraphStyle("h2", fontName=fnb, fontSize=13, leading=17,
                              spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#16213e")),
        "h3": ParagraphStyle("h3", fontName=fnb, fontSize=10, leading=14,
                              spaceBefore=4, spaceAfter=3, textColor=colors.HexColor("#0f3460")),
        "body": ParagraphStyle("body", fontName=fn, fontSize=9, leading=13,
                                spaceAfter=3, textColor=colors.HexColor("#333333")),
        "small": ParagraphStyle("small", fontName=fn, fontSize=8, leading=11,
                                  textColor=colors.HexColor("#666666")),
        "link": ParagraphStyle("link", fontName=fn, fontSize=7, leading=10,
                                textColor=colors.HexColor("#0066cc")),
    }


def _freq_table(freq_data, styles, max_rows=20):
    if not freq_data:
        return Paragraph("언급 종목 없음", styles["small"])

    data = [["순위", "종목명", "언급 횟수"]]
    for i, (stock, cnt) in enumerate(freq_data[:max_rows], 1):
        data.append([str(i), stock, f"{cnt}회"])

    t = Table(data, colWidths=[1.5 * cm, 8 * cm, 3 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "KR" if FONT_REGISTERED else "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


# ─── PDF: 블로그 일일 리포트 ───────────────────────────────────────────
def generate_blog_pdf(blog_data, freq_data, report_date):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    s = make_styles()
    story = []

    story.append(Paragraph("주식 블로그 일일 리포트", s["title"]))
    story.append(Paragraph(f"기준일: {report_date}  |  블로그 수: {len(blog_data)}개", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3 * cm))

    # 종목 빈도
    story.append(Paragraph("📊 오늘 블로그에서 가장 많이 언급된 종목", s["h2"]))
    story.append(_freq_table(freq_data, s, 10))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 블로그별 내용
    story.append(Paragraph("📰 블로거별 요약", s["h2"]))

    for blog_name, posts in blog_data.items():
        story.append(Paragraph(f"▶ {blog_name}", s["h2"]))

        if not posts:
            story.append(Paragraph("오늘 새 포스트 없음", s["small"]))
            story.append(Spacer(1, 0.15 * cm))
            continue

        for post in posts:
            title = post.get("title", "")[:80]
            story.append(Paragraph(f"• {title}", s["h3"]))
            if post.get("summary"):
                story.append(Paragraph(post["summary"][:200], s["body"]))
            if post.get("stocks"):
                story.append(Paragraph(f"언급 종목: {', '.join(post['stocks'][:8])}", s["small"]))
            link = post.get("link", "")
            if link:
                story.append(Paragraph(link, s["link"]))
            story.append(Spacer(1, 0.2 * cm))

        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#eeeeee")))
        story.append(Spacer(1, 0.1 * cm))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── PDF: 리서치 리포트 ────────────────────────────────────────────────
def generate_research_pdf(research_data, report_date):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    s = make_styles()
    story = []

    company_list = research_data.get("company", [])
    industry_list = research_data.get("industry", [])
    total = len(company_list) + len(industry_list)

    story.append(Paragraph("네이버 증권 리서치 리포트", s["title"]))
    story.append(Paragraph(f"기준일: {report_date}  |  총 {total}건", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3 * cm))

    # 종목별 빈도
    if company_list:
        stock_freq = Counter([r["stock"] for r in company_list if r.get("stock")]).most_common(15)
        story.append(Paragraph("📊 오늘 리포트 대상 종목 현황", s["h2"]))
        t_data = [["종목명", "리포트 수"]]
        for stock, cnt in stock_freq:
            t_data.append([stock, f"{cnt}건"])
        t = Table(t_data, colWidths=[9 * cm, 3 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "KR" if FONT_REGISTERED else "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 1), (0, -1), "LEFT"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 기업 분석 리포트
    story.append(Paragraph(f"📋 기업 분석 리포트 ({len(company_list)}건)", s["h2"]))
    if company_list:
        for r in company_list:
            story.append(Paragraph(f"• [{r.get('stock', '')}] {r.get('title', '')[:70]}", s["h3"]))
            meta = f"증권사: {r.get('firm', '')}  |  날짜: {r.get('date', '')}"
            story.append(Paragraph(meta, s["small"]))
            if r.get("link"):
                story.append(Paragraph(r["link"], s["link"]))
            story.append(Spacer(1, 0.15 * cm))
    else:
        story.append(Paragraph("오늘 기업 분석 리포트 없음", s["small"]))

    story.append(Spacer(1, 0.2 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 산업 분석 리포트
    story.append(Paragraph(f"🏭 산업 분석 리포트 ({len(industry_list)}건)", s["h2"]))
    if industry_list:
        for r in industry_list:
            story.append(Paragraph(f"• {r.get('title', '')[:70]}", s["h3"]))
            meta = f"증권사: {r.get('firm', '')}  |  날짜: {r.get('date', '')}"
            story.append(Paragraph(meta, s["small"]))
            if r.get("link"):
                story.append(Paragraph(r["link"], s["link"]))
            story.append(Spacer(1, 0.15 * cm))
    else:
        story.append(Paragraph("오늘 산업 분석 리포트 없음", s["small"]))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── PDF: 주간/월간 종합 리포트 ──────────────────────────────────────────
def generate_summary_pdf(label, period_label, freq_data, grouped_posts, all_research):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    s = make_styles()
    story = []

    story.append(Paragraph(f"{label} 투자 인텔리전스 리포트", s["title"]))
    story.append(Paragraph(f"기간: {period_label}", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3 * cm))

    # TOP 종목
    story.append(Paragraph(f"🏆 {label} TOP 20 관심 종목 (블로그 기준)", s["h2"]))
    story.append(_freq_table(freq_data, s, 20))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 리서치 종목 빈도
    if all_research:
        research_stocks = [r["stock"] for r in all_research if r.get("stock")]
        if research_stocks:
            research_freq = Counter(research_stocks).most_common(10)
            story.append(Paragraph(f"📋 {label} 증권사 리포트 TOP 10 종목", s["h2"]))
            t_data = [["종목명", "리포트 수"]]
            for stock, cnt in research_freq:
                t_data.append([stock, f"{cnt}건"])
            t = Table(t_data, colWidths=[9 * cm, 3 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "KR" if FONT_REGISTERED else "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "LEFT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.4 * cm))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 기간별 주요 포스트
    story.append(Paragraph("📝 기간별 주요 포스트", s["h2"]))
    for period_key in sorted(grouped_posts.keys()):
        posts = grouped_posts[period_key]
        story.append(Paragraph(f"▶ {period_key}", s["h3"]))
        for post in posts[:4]:
            story.append(Paragraph(f"• {post.get('title', '')[:60]}", s["body"]))
            if post.get("summary"):
                story.append(Paragraph(f"  {post['summary'][:100]}", s["small"]))
        story.append(Spacer(1, 0.2 * cm))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── 텔레그램 전송 ──────────────────────────────────────────────────────
def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4096],
        "parse_mode": "HTML",
    }, timeout=15)
    if not resp.ok:
        print(f"  [텔레그램 메시지 오류] {resp.text}")
    return resp.ok


def send_pdf(pdf_buf, filename, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    resp = requests.post(url,
                         data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]},
                         files={"document": (filename, pdf_buf, "application/pdf")},
                         timeout=60)
    if not resp.ok:
        print(f"  [텔레그램 PDF 오류] {resp.text}")
    return resp.ok


# ─── 리포트 실행 ───────────────────────────────────────────────────────
def run_daily():
    today = datetime.now()
    report_date = today.strftime("%Y년 %m월 %d일")
    date_str = today.strftime("%Y%m%d")
    print(f"=== 일일 리포트: {report_date} ===")

    client = Groq(api_key=GROQ_API_KEY)

    # 블로그 수집 + AI 요약
    blog_data = {}
    all_stocks = []

    for blog_name, rss_url in BLOG_RSS_FEEDS.items():
        print(f"  수집 중: {blog_name}")
        posts = fetch_blog_posts(rss_url, hours=24)
        enriched = []
        for post in posts:
            time.sleep(4)
            summary, stocks = summarize_post(client, post)
            post["summary"] = summary
            post["stocks"] = stocks
            all_stocks.extend(stocks)
            enriched.append(post)
        blog_data[blog_name] = enriched

    freq = analyze_frequency(all_stocks, 10)

    # 리서치 리포트 수집
    print("  네이버 증권 리서치 수집 중...")
    research = {
        "company": fetch_naver_research("company"),
        "industry": fetch_naver_research("industry"),
    }

    # PDF 생성
    register_fonts()
    print("  PDF 생성 중...")
    blog_pdf = generate_blog_pdf(blog_data, freq, report_date)
    research_pdf = generate_research_pdf(research, report_date)

    # 텔레그램 전송
    total_posts = sum(len(v) for v in blog_data.values())
    total_research = len(research["company"]) + len(research["industry"])
    top_stocks = ", ".join(s for s, _ in freq[:5]) or "없음"

    send_message(
        f"📊 <b>투자 인텔리전스 일일 리포트</b>\n"
        f"📅 {report_date}\n\n"
        f"• 블로그 {len(blog_data)}개 | 포스트 {total_posts}건\n"
        f"• 리서치 리포트 {total_research}건\n"
        f"• TOP 언급 종목: {top_stocks}\n\n"
        f"아래 PDF 파일을 확인하세요 ↓"
    )

    send_pdf(blog_pdf, f"blog_{date_str}.pdf", f"📰 블로그 리포트 {report_date}")
    time.sleep(2)
    send_pdf(research_pdf, f"research_{date_str}.pdf", f"📋 리서치 리포트 {report_date}")

    print("  일일 리포트 완료!")


def run_weekly():
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%Y.%m.%d')} ~ {week_end.strftime('%Y.%m.%d')}"
    date_str = today.strftime("%Y%m%d")
    print(f"=== 주간 리포트: {week_label} ===")

    client = Groq(api_key=GROQ_API_KEY)

    all_stocks = []
    grouped = {}

    for blog_name, rss_url in BLOG_RSS_FEEDS.items():
        posts = fetch_blog_posts(rss_url, hours=168)
        for post in posts:
            time.sleep(4)
            summary, stocks = summarize_post(client, post)
            post["summary"] = summary
            post["stocks"] = stocks
            all_stocks.extend(stocks)
            day_key = post["published"].strftime("%m/%d (%a)")
            grouped.setdefault(day_key, []).append(post)

    # 리서치 (오늘 기준 일주일치 - 오늘 것만 수집 가능)
    research = fetch_naver_research("company") + fetch_naver_research("industry")

    freq = analyze_frequency(all_stocks, 20)
    register_fonts()
    pdf = generate_summary_pdf("📅 주간", week_label, freq, grouped, research)

    top_stocks = ", ".join(s for s, _ in freq[:5]) or "없음"
    send_message(
        f"📅 <b>주간 투자 인텔리전스 리포트</b>\n"
        f"📆 {week_label}\n\n"
        f"• 이번 주 TOP 종목: {top_stocks}\n"
        f"• 총 포스트: {sum(len(v) for v in grouped.values())}건"
    )
    send_pdf(pdf, f"weekly_{date_str}.pdf", f"📅 주간 리포트 {week_label}")
    print("  주간 리포트 완료!")


def run_monthly():
    today = datetime.now()
    month_label = today.strftime("%Y년 %m월")
    date_str = today.strftime("%Y%m")
    print(f"=== 월간 리포트: {month_label} ===")

    client = Groq(api_key=GROQ_API_KEY)

    all_stocks = []
    grouped = {}

    for blog_name, rss_url in BLOG_RSS_FEEDS.items():
        posts = fetch_blog_posts(rss_url, hours=720)
        for post in posts:
            time.sleep(4)
            summary, stocks = summarize_post(client, post)
            post["summary"] = summary
            post["stocks"] = stocks
            all_stocks.extend(stocks)
            week_key = "W" + post["published"].strftime("%W (%m/%d~)")
            grouped.setdefault(week_key, []).append(post)

    research = fetch_naver_research("company") + fetch_naver_research("industry")

    freq = analyze_frequency(all_stocks, 20)
    register_fonts()
    pdf = generate_summary_pdf("📆 월간", month_label, freq, grouped, research)

    top_stocks = ", ".join(s for s, _ in freq[:10]) or "없음"
    send_message(
        f"📆 <b>월간 투자 인텔리전스 리포트</b>\n"
        f"📅 {month_label}\n\n"
        f"• 이달 TOP 종목: {top_stocks}"
    )
    send_pdf(pdf, f"monthly_{date_str}.pdf", f"📆 월간 리포트 {month_label}")
    print("  월간 리포트 완료!")


# ─── 진입점 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    today = datetime.now()
    rtype = REPORT_TYPE.strip().lower()

    if rtype == "daily":
        run_daily()
    elif rtype == "weekly":
        run_weekly()
    elif rtype == "monthly":
        run_monthly()
    else:  # auto
        run_daily()
        if today.weekday() == 6:   # 일요일
            run_weekly()
        if today.day == 1:          # 매월 1일
            run_monthly()
