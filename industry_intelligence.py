"""
산업별 투자 인텔리전스 시스템
- 산업 거시 환경 + 핵심 기업 경쟁력 + 글로벌 비교
- 매주 월요일 오전 7시 텔레그램 + 노션 전송
"""

import os
import io
import re
import time
import requests
import feedparser
from groq import Groq
from datetime import datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from collections import defaultdict

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

BOT_TOKEN      = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID        = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_API_KEY   = (os.getenv("GROQ_API_KEY") or "").strip()
NOTION_TOKEN   = (os.getenv("NOTION_TOKEN") or "").strip()
NOTION_PAGE_ID = (os.getenv("NOTION_PAGE_ID") or "").strip()

# ─── 산업 + 핵심 기업 설정 ─────────────────────────────────────────────
# 산업 추가 방법: 아래 딕셔너리에 항목 추가
INDUSTRIES = {
    "반도체": {
        "keywords": ["반도체", "메모리", "HBM", "파운드리", "AI칩", "DRAM", "낸드"],
        "global_keywords": ["semiconductor", "memory", "HBM", "foundry", "AI chip", "DRAM", "NAND"],
        "key_company": {"name": "삼성전자", "code": "005930"},
        "competitors": [
            {"name": "SK하이닉스", "code": "000660", "market": "KR"},
            {"name": "TSMC",     "ticker": "TSM",   "market": "US"},
            {"name": "마이크론",  "ticker": "MU",    "market": "US"},
            {"name": "인텔",      "ticker": "INTC",  "market": "US"},
        ],
    },
    "로봇": {
        "keywords": ["로봇", "자동화", "협동로봇", "휴머노이드", "스마트팩토리"],
        "global_keywords": ["robotics", "automation", "humanoid robot", "cobots", "smart factory"],
        "key_company": {"name": "현대차", "code": "005380"},
        "competitors": [
            {"name": "현대로보틱스", "code": "267270", "market": "KR"},
            {"name": "ABB",        "ticker": "ABB",   "market": "US"},
            {"name": "FANUC",      "ticker": "FANUY", "market": "US"},
            {"name": "테슬라",      "ticker": "TSLA",  "market": "US"},
        ],
    },
    # 산업 추가 예시:
    # "배터리": {
    #     "keywords": ["배터리", "전기차", "ESS", "리튬", "양극재"],
    #     "global_keywords": ["battery", "EV", "lithium", "cathode"],
    #     "key_company": {"name": "LG에너지솔루션", "code": "373220"},
    #     "competitors": [
    #         {"name": "삼성SDI", "code": "006400", "market": "KR"},
    #         {"name": "CATL", "ticker": "300750.SZ", "market": "US"},
    #     ],
    # },
}

# ─── 뉴스 RSS ─────────────────────────────────────────────────────────
GLOBAL_NEWS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://www.bnnbloomberg.ca/rss",
    "https://feeds.bloomberg.com/markets/news.rss",
]

KOREAN_NEWS_FEEDS = [
    "https://www.hankyung.com/feed/finance",
    "https://www.hankyung.com/feed/economy",
]


# ─── 한국어 폰트 ────────────────────────────────────────────────────────
def _find_font(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None

FONT_PATH      = _find_font(["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf"])
FONT_BOLD_PATH = _find_font(["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"])
FONT_OK = False

def register_fonts():
    global FONT_OK
    if FONT_OK:
        return
    try:
        if FONT_PATH:
            pdfmetrics.registerFont(TTFont("KR", FONT_PATH))
            pdfmetrics.registerFont(TTFont("KR-Bold", FONT_BOLD_PATH or FONT_PATH))
            FONT_OK = True
    except Exception as e:
        print(f"[폰트 오류] {e}")


# ─── 데이터 수집 ───────────────────────────────────────────────────────
def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", str(text))
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ")).strip()


def fetch_filtered_news(rss_url, keywords, max_items=10):
    """키워드 필터링된 뉴스 수집"""
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "Mozilla/5.0"})
        results = []
        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            summary = strip_html(entry.get("summary", ""))
            combined = (title + " " + summary).lower()
            if any(kw.lower() in combined for kw in keywords):
                results.append({
                    "title": title,
                    "summary": summary[:300],
                    "link": entry.get("link", ""),
                })
            if len(results) >= max_items:
                break
        return results
    except Exception:
        return []


def fetch_naver_research_by_stock(stock_code, pages=2):
    """네이버 증권에서 종목별 리포트 수집"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    reports = []
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/research/company_list.nhn?searchType=itemCode&itemCode={stock_code}&page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = "euc-kr"
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", class_="type_1")
            if not table:
                break
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                title_tag = cells[1].find("a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                link = ("https://finance.naver.com" + href) if href.startswith("/") else href
                firm = cells[2].get_text(strip=True)
                date = cells[3].get_text(strip=True)
                price_match = re.search(r"(\d{2,3},?\d{3})원", title)
                target_price = price_match.group(1).replace(",", "") if price_match else None
                reports.append({
                    "title": title, "firm": firm, "date": date,
                    "link": link, "target_price": target_price,
                })
            time.sleep(0.5)
        except Exception:
            break
    return reports[:20]


def fetch_report_content(link):
    """리포트 상세 페이지 본문 추출"""
    if not link:
        return ""
    try:
        resp = requests.get(link, headers={"User-Agent": "Mozilla/5.0",
                                            "Accept-Language": "ko-KR",
                                            "Referer": "https://finance.naver.com/research/"},
                            timeout=15)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        for selector in ["div.view_cnt", "td.view_cnt", "div#content"]:
            tag = soup.select_one(selector)
            if tag:
                text = re.sub(r"\s+", " ", tag.get_text(separator=" ", strip=True))
                if len(text) > 80:
                    return text[:1200]
        return ""
    except Exception:
        return ""


# ─── AI 분석 엔진 ──────────────────────────────────────────────────────
def build_industry_analysis(client, industry_name, config, all_data):
    """산업 전체 + 핵심 기업 종합 분석"""

    key_company = config["key_company"]["name"]

    # 데이터 정리
    kr_news = "\n".join(f"- {a['title']}" for a in all_data.get("kr_news", [])[:8])
    global_news = "\n".join(f"- {a['title']}" for a in all_data.get("global_news", [])[:8])

    key_reports = all_data.get("key_reports", [])
    reports_text = "\n".join(
        f"- [{r['firm']}] {r['title']}" + (f" | 목표주가: {int(r['target_price']):,}원" if r.get("target_price") else "")
        for r in key_reports[:10]
    )
    report_contents = "\n\n".join(
        f"[{r['firm']}]\n{r.get('content','')}"
        for r in key_reports[:3] if r.get("content")
    )

    competitor_reports = ""
    for comp in all_data.get("competitor_reports", []):
        comp_name = comp["company"]
        comp_list = "\n".join(f"  - [{r['firm']}] {r['title']}" for r in comp["reports"][:3])
        if comp_list:
            competitor_reports += f"{comp_name}:\n{comp_list}\n"

    prompt = f"""
당신은 글로벌 투자 전략가입니다. 아래 데이터를 바탕으로 {industry_name} 산업 인텔리전스 리포트를 작성해주세요.

[국내 뉴스]
{kr_news if kr_news else '없음'}

[글로벌 뉴스]
{global_news if global_news else '없음'}

[{key_company} 최신 증권사 리포트]
{reports_text if reports_text else '없음'}

[리포트 주요 내용]
{report_contents if report_contents else '없음'}

[경쟁사 리포트]
{competitor_reports if competitor_reports else '없음'}

아래 구조로 상세히 작성해주세요 (각 항목 3줄 이상):

1. 【거시 환경】 금리·환율·글로벌 수요 등 {industry_name} 산업에 영향을 주는 거시 변수
2. 【산업 동향】 현재 {industry_name} 사이클 위치, 주요 트렌드, 수요/공급 상황
3. 【{key_company} 경쟁력】 현재 포지션, 강점·약점, 핵심 사업 진행 상황
4. 【경쟁사 비교】 주요 경쟁사 대비 {key_company}의 상대적 위치
5. 【시장 컨센서스】 증권사들의 공통 시각과 엇갈리는 부분
6. 【리스크 & 기회】 단기·중기 투자 리스크와 기회 요인
7. 【투자 관점 요약】 지금 시점에서 투자자가 주목해야 할 핵심 포인트
"""

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [Groq 오류] {e}")
            if attempt == 0:
                time.sleep(5)
    return "분석 실패"


# ─── PDF 생성 ───────────────────────────────────────────────────────────
def generate_intelligence_pdf(results, report_date):
    register_fonts()
    fn  = "KR"      if FONT_OK else "Helvetica"
    fnb = "KR-Bold" if FONT_OK else "Helvetica-Bold"

    s = {
        "title":    ParagraphStyle("title",    fontName=fnb, fontSize=18, leading=24,
                                    spaceAfter=6,  textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle("subtitle", fontName=fn,  fontSize=10, leading=13,
                                    spaceAfter=10, textColor=colors.HexColor("#555555")),
        "industry": ParagraphStyle("industry", fontName=fnb, fontSize=14, leading=18,
                                    spaceBefore=12, spaceAfter=6,
                                    textColor=colors.white,
                                    backColor=colors.HexColor("#1a1a2e")),
        "body":     ParagraphStyle("body",     fontName=fn,  fontSize=9,  leading=14,
                                    spaceAfter=6,  textColor=colors.HexColor("#222222")),
        "small":    ParagraphStyle("small",    fontName=fn,  fontSize=8,  leading=11,
                                    textColor=colors.HexColor("#888888")),
        "link":     ParagraphStyle("link",     fontName=fn,  fontSize=7,  leading=10,
                                    textColor=colors.HexColor("#0066cc")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story.append(Paragraph("산업별 투자 인텔리전스 리포트", s["title"]))
    story.append(Paragraph(f"주간 리포트 | {report_date}", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3*cm))

    for industry_name, result in results.items():
        key_company = result["key_company"]

        story.append(Paragraph(f"  📊 {industry_name} 산업  |  핵심: {key_company}", s["industry"]))
        story.append(Spacer(1, 0.2*cm))

        # AI 분석 본문
        analysis = result.get("analysis", "")
        if analysis:
            for line in analysis.split("\n"):
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 0.1*cm))
                    continue
                story.append(Paragraph(line, s["body"]))

        story.append(Spacer(1, 0.3*cm))

        # 최신 리포트 링크
        key_reports = result.get("key_reports", [])
        if key_reports:
            story.append(Paragraph(f"▸ {key_company} 최신 리포트", s["small"]))
            for r in key_reports[:5]:
                price = f" | {int(r['target_price']):,}원" if r.get("target_price") else ""
                story.append(Paragraph(f"• [{r['firm']}] {r['title'][:55]}{price}", s["small"]))
                if r.get("link"):
                    story.append(Paragraph(r["link"], s["link"]))

        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))
        story.append(Spacer(1, 0.4*cm))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── 노션 저장 ─────────────────────────────────────────────────────────
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def save_to_notion(industry_name, key_company, analysis, report_date):
    if not NOTION_TOKEN or not NOTION_PAGE_ID:
        return
    try:
        requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json={
                "parent": {"page_id": NOTION_PAGE_ID},
                "properties": {
                    "title": {"title": [{"text": {"content": f"[{report_date}] {industry_name} 산업 인텔리전스"}}]}
                },
                "children": [
                    {"object": "block", "type": "heading_2",
                     "heading_2": {"rich_text": [{"text": {"content": f"{industry_name} - {key_company}"}}]}},
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"text": {"content": analysis[:2000]}}]}},
                ],
            },
            timeout=15,
        )
        print(f"  노션 저장 완료: {industry_name}")
    except Exception as e:
        print(f"  [노션 오류] {e}")


# ─── 텔레그램 전송 ──────────────────────────────────────────────────────
def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": CHAT_ID, "text": text[:4096],
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }, timeout=15)
    if not resp.ok:
        print(f"  [메시지 오류] {resp.text}")
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
    today = datetime.now()
    report_date = today.strftime("%Y년 %m월 %d일")
    date_str = today.strftime("%Y%m%d")
    print(f"=== 산업 인텔리전스: {report_date} ===")

    client = Groq(api_key=GROQ_API_KEY)
    results = {}

    for industry_name, config in INDUSTRIES.items():
        print(f"\n  [{industry_name}] 데이터 수집 중...")

        # 국내 뉴스
        kr_news = []
        for feed_url in KOREAN_NEWS_FEEDS:
            kr_news += fetch_filtered_news(feed_url, config["keywords"], 5)
        print(f"    국내 뉴스: {len(kr_news)}건")

        # 글로벌 뉴스
        global_news = []
        for feed_url in GLOBAL_NEWS_FEEDS:
            global_news += fetch_filtered_news(feed_url, config["global_keywords"], 5)
        print(f"    글로벌 뉴스: {len(global_news)}건")

        # 핵심 기업 리포트
        key_company = config["key_company"]
        key_reports = fetch_naver_research_by_stock(key_company["code"])
        # 최신 3개 리포트 본문 수집
        for r in key_reports[:3]:
            time.sleep(2)
            r["content"] = fetch_report_content(r.get("link", ""))
        print(f"    {key_company['name']} 리포트: {len(key_reports)}건")

        # 경쟁사 리포트 (국내만)
        competitor_reports = []
        for comp in config["competitors"]:
            if comp.get("market") == "KR" and comp.get("code"):
                time.sleep(1)
                comp_reports = fetch_naver_research_by_stock(comp["code"], pages=1)
                competitor_reports.append({"company": comp["name"], "reports": comp_reports})
                print(f"    {comp['name']} 리포트: {len(comp_reports)}건")

        all_data = {
            "kr_news": kr_news,
            "global_news": global_news,
            "key_reports": key_reports,
            "competitor_reports": competitor_reports,
        }

        # AI 종합 분석
        time.sleep(4)
        print(f"    AI 분석 중...")
        analysis = build_industry_analysis(client, industry_name, config, all_data)

        results[industry_name] = {
            "key_company": key_company["name"],
            "analysis": analysis,
            "key_reports": key_reports,
        }

        # 노션 저장
        save_to_notion(industry_name, key_company["name"], analysis, report_date)
        time.sleep(2)

    # PDF 생성
    print("\n  PDF 생성 중...")
    pdf = generate_intelligence_pdf(results, report_date)

    # 텔레그램 전송
    summary = "\n".join(
        f"• {ind}: {res['key_company']} 중심 분석"
        for ind, res in results.items()
    )
    send_message(
        f"🧠 <b>산업별 투자 인텔리전스 주간 리포트</b>\n"
        f"📅 {report_date}\n\n"
        f"{summary}\n\n"
        f"거시환경 · 산업동향 · 경쟁력 · 리스크 분석 포함\n"
        f"PDF 확인 ↓"
    )
    time.sleep(1)
    send_pdf(pdf, f"intelligence_{date_str}.pdf", f"🧠 산업 인텔리전스 {report_date}")
    print("\n  완료!")


if __name__ == "__main__":
    main()
