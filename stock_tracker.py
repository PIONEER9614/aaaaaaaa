"""
종목별 증권사 리포트 추적 시스템
- 네이버 증권에서 종목 리포트 수집
- 이전 리포트와 목표주가/투자의견/핵심내용 비교
- 매일 변화 사항 텔레그램 전송
"""

import os
import io
import re
import json
import time
import requests
from groq import Groq
from datetime import datetime, timedelta
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

BOT_TOKEN     = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID       = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_API_KEY  = (os.getenv("GROQ_API_KEY") or "").strip()
NOTION_TOKEN  = (os.getenv("NOTION_TOKEN") or "").strip()
NOTION_PAGE_ID = (os.getenv("NOTION_PAGE_ID") or "").strip()

# ─── 추적 종목 목록 ────────────────────────────────────────────────────
# 종목명: 네이버 증권 검색 코드
TRACKED_STOCKS = {
    "삼성전자": "005930",
    # 종목 추가:
    # "SK하이닉스": "000660",
    # "LG에너지솔루션": "373220",
    # "카카오": "035720",
}

# 이력 저장 파일
HISTORY_FILE = "stock_report_history.json"


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


# ─── 이력 관리 ─────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─── 네이버 증권 리포트 수집 ────────────────────────────────────────────
def fetch_stock_reports(stock_code, stock_name, pages=3):
    """네이버 증권에서 종목 리포트 수집"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
                try:
                    title_tag = cells[1].find("a")
                    if not title_tag:
                        continue

                    title = title_tag.get_text(strip=True)
                    href  = title_tag.get("href", "")
                    link  = ("https://finance.naver.com" + href) if href.startswith("/") else href
                    firm  = cells[2].get_text(strip=True)
                    date  = cells[3].get_text(strip=True)

                    # 목표주가 추출 (제목에서 패턴 파싱)
                    target_price = None
                    price_match = re.search(r"(\d{2,3},?\d{3})원", title)
                    if price_match:
                        target_price = price_match.group(1).replace(",", "")

                    # 투자의견 추출
                    opinion = None
                    for keyword in ["매수", "BUY", "Buy", "중립", "Neutral", "비중확대", "Outperform"]:
                        if keyword in title:
                            opinion = keyword
                            break

                    reports.append({
                        "title": title,
                        "firm": firm,
                        "date": date,
                        "link": link,
                        "target_price": target_price,
                        "opinion": opinion,
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                    })
                except Exception:
                    continue

            time.sleep(0.5)
        except Exception as e:
            print(f"  [수집 오류] {stock_name} p{page}: {e}")
            break

    print(f"  {stock_name}: 리포트 {len(reports)}건 수집")
    return reports


# ─── 변화 분석 ─────────────────────────────────────────────────────────
def analyze_changes(stock_name, new_reports, prev_data):
    """이전 데이터와 비교해 변화 사항 추출"""
    changes = []

    prev_reports = prev_data.get("reports", [])
    prev_titles  = {r["title"] for r in prev_reports}

    # 새로 추가된 리포트
    new_ones = [r for r in new_reports if r["title"] not in prev_titles]

    if new_ones:
        changes.append(f"새 리포트 {len(new_ones)}건 추가됨")

    # 목표주가 변화
    prev_prices = [r["target_price"] for r in prev_reports if r.get("target_price")]
    new_prices  = [r["target_price"] for r in new_reports[:10] if r.get("target_price")]

    if prev_prices and new_prices:
        try:
            avg_prev = sum(int(p) for p in prev_prices[:5]) / min(5, len(prev_prices))
            avg_new  = sum(int(p) for p in new_prices[:5])  / min(5, len(new_prices))
            diff_pct = (avg_new - avg_prev) / avg_prev * 100
            if abs(diff_pct) >= 2:
                direction = "상향" if diff_pct > 0 else "하향"
                changes.append(f"목표주가 평균 {direction} ({diff_pct:+.1f}%): {int(avg_prev):,}원 → {int(avg_new):,}원")
        except Exception:
            pass

    return new_ones, changes


# ─── AI 분석 ────────────────────────────────────────────────────────────
def analyze_with_ai(client, stock_name, new_reports, changes):
    """신규 리포트와 변화 사항을 AI로 분석"""
    if not new_reports and not changes:
        return "오늘 새 리포트 없음"

    new_titles = "\n".join(
        f"- [{r['firm']}] {r['title']} ({r['date']})"
        for r in new_reports[:10]
    )
    change_text = "\n".join(f"- {c}" for c in changes) if changes else "없음"

    prompt = (
        f"종목: {stock_name}\n\n"
        f"[오늘 새로 나온 리포트]\n{new_titles if new_titles else '없음'}\n\n"
        f"[감지된 변화]\n{change_text}\n\n"
        f"투자자 관점에서 아래 내용을 포함해 5줄 이상 분석해주세요:\n"
        f"1. 오늘 리포트의 핵심 메시지\n"
        f"2. 목표주가/투자의견 변화 의미\n"
        f"3. 증권사들이 주목하는 포인트\n"
        f"4. 이전 대비 달라진 시각\n"
        f"5. 투자자가 주의할 점"
    )

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [Groq 오류] {e}")
            if attempt == 0:
                time.sleep(5)

    return "\n".join(f"• {r['title']}" for r in new_reports[:5])


# ─── PDF 생성 ───────────────────────────────────────────────────────────
def generate_tracker_pdf(stock_results, report_date):
    register_fonts()
    fn  = "KR"      if FONT_OK else "Helvetica"
    fnb = "KR-Bold" if FONT_OK else "Helvetica-Bold"

    s = {
        "title":    ParagraphStyle("title",    fontName=fnb, fontSize=17, leading=22,
                                    spaceAfter=6,  textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle("subtitle", fontName=fn,  fontSize=10, leading=13,
                                    spaceAfter=8,  textColor=colors.HexColor("#555555")),
        "h2":       ParagraphStyle("h2",       fontName=fnb, fontSize=13, leading=17,
                                    spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#0f3460")),
        "analysis": ParagraphStyle("analysis", fontName=fn,  fontSize=9,  leading=14,
                                    spaceAfter=4,  textColor=colors.HexColor("#222222")),
        "change":   ParagraphStyle("change",   fontName=fnb, fontSize=9,  leading=13,
                                    spaceAfter=3,  textColor=colors.HexColor("#c0392b")),
        "report":   ParagraphStyle("report",   fontName=fn,  fontSize=8,  leading=12,
                                    spaceAfter=2,  textColor=colors.HexColor("#444444")),
        "link":     ParagraphStyle("link",     fontName=fn,  fontSize=7,  leading=10,
                                    textColor=colors.HexColor("#0066cc")),
        "small":    ParagraphStyle("small",    fontName=fn,  fontSize=8,  leading=11,
                                    textColor=colors.HexColor("#888888")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story.append(Paragraph("종목별 증권사 리포트 추적", s["title"]))
    story.append(Paragraph(f"기준일: {report_date}  |  추적 종목: {len(stock_results)}개", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3*cm))

    for stock_name, result in stock_results.items():
        story.append(Paragraph(f"📈 {stock_name}", s["h2"]))

        # 변화 사항
        changes = result.get("changes", [])
        if changes:
            for c in changes:
                story.append(Paragraph(f"🔺 {c}", s["change"]))
            story.append(Spacer(1, 0.15*cm))

        # AI 분석
        analysis = result.get("analysis", "")
        if analysis:
            story.append(Paragraph(analysis, s["analysis"]))
            story.append(Spacer(1, 0.2*cm))

        # 새 리포트 목록
        new_reports = result.get("new_reports", [])
        if new_reports:
            story.append(Paragraph(f"새 리포트 ({len(new_reports)}건):", s["small"]))
            for r in new_reports[:8]:
                firm_date = f"[{r.get('firm','')} | {r.get('date','')}]"
                story.append(Paragraph(f"• {r.get('title','')[:60]}  {firm_date}", s["report"]))
                if r.get("link"):
                    story.append(Paragraph(r["link"], s["link"]))
            story.append(Spacer(1, 0.1*cm))

        # 최근 리포트 목표주가 현황
        all_reports = result.get("all_reports", [])
        price_reports = [r for r in all_reports[:10] if r.get("target_price")]
        if price_reports:
            t_data = [["증권사", "목표주가", "날짜"]]
            for r in price_reports[:6]:
                t_data.append([r.get("firm",""), f"{int(r['target_price']):,}원", r.get("date","")])
            t = Table(t_data, colWidths=[5*cm, 4*cm, 4*cm])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#0f3460")),
                ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
                ("FONTNAME",      (0,0), (-1,-1), fn),
                ("FONTSIZE",      (0,0), (-1,0), 8),
                ("FONTSIZE",      (0,1), (-1,-1), 7),
                ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID",          (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ]))
            story.append(t)

        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#eeeeee")))
        story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    buf.seek(0)
    return buf


# ─── 노션 저장 ─────────────────────────────────────────────────────────
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

def get_or_create_notion_db():
    """노션 페이지 안에 데이터베이스 찾거나 생성"""
    # 기존 DB 검색
    search_resp = requests.post(
        "https://api.notion.com/v1/search",
        headers=NOTION_HEADERS,
        json={"query": "증권사 리포트 추적", "filter": {"property": "object", "value": "database"}},
        timeout=15,
    )
    if search_resp.ok:
        results = search_resp.json().get("results", [])
        if results:
            return results[0]["id"]

    # 없으면 새로 생성
    db_resp = requests.post(
        "https://api.notion.com/v1/databases",
        headers=NOTION_HEADERS,
        json={
            "parent": {"type": "page_id", "page_id": NOTION_PAGE_ID},
            "title": [{"type": "text", "text": {"content": "증권사 리포트 추적"}}],
            "properties": {
                "종목명":    {"title": {}},
                "리포트 제목": {"rich_text": {}},
                "증권사":    {"rich_text": {}},
                "목표주가":  {"rich_text": {}},
                "날짜":      {"date": {}},
                "변화 사항": {"rich_text": {}},
                "AI 분석":   {"rich_text": {}},
                "링크":      {"url": {}},
            },
        },
        timeout=15,
    )
    if db_resp.ok:
        db_id = db_resp.json()["id"]
        print(f"  노션 DB 생성 완료: {db_id}")
        return db_id
    else:
        print(f"  [노션 DB 오류] {db_resp.text}")
        return None


def save_to_notion(db_id, stock_name, new_reports, changes, analysis, today):
    """새 리포트와 분석 결과를 노션에 저장"""
    if not db_id:
        return

    change_text = " | ".join(changes) if changes else "변화 없음"
    analysis_short = analysis[:1900] if analysis else ""

    # 종목별 오늘 요약 페이지 1개 저장
    page_data = {
        "parent": {"database_id": db_id},
        "properties": {
            "종목명":    {"title": [{"text": {"content": stock_name}}]},
            "변화 사항": {"rich_text": [{"text": {"content": change_text[:500]}}]},
            "AI 분석":   {"rich_text": [{"text": {"content": analysis_short}}]},
            "날짜":      {"date": {"start": today.strftime("%Y-%m-%d")}},
        },
        "children": [],
    }

    # 새 리포트 목록을 페이지 본문에 추가
    if new_reports:
        blocks = [
            {"object": "block", "type": "heading_2",
             "heading_2": {"rich_text": [{"text": {"content": f"새 리포트 ({len(new_reports)}건)"}}]}},
        ]
        for r in new_reports[:10]:
            price = f" | 목표주가: {int(r['target_price']):,}원" if r.get("target_price") else ""
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"text": {"content": f"[{r.get('firm','')}] {r.get('title','')[:80]}{price}"}}]
                }
            })
        page_data["children"] = blocks

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json=page_data,
        timeout=15,
    )
    if resp.ok:
        print(f"  노션 저장 완료: {stock_name}")
    else:
        print(f"  [노션 저장 오류] {resp.text[:200]}")


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
    print(f"=== 종목 리포트 추적: {report_date} ===")

    history = load_history()
    client = Groq(api_key=GROQ_API_KEY)
    stock_results = {}

    for stock_name, stock_code in TRACKED_STOCKS.items():
        print(f"  {stock_name} 수집 중...")
        reports = fetch_stock_reports(stock_code, stock_name)

        prev_data = history.get(stock_name, {})
        new_reports, changes = analyze_changes(stock_name, reports, prev_data)

        time.sleep(4)
        analysis = analyze_with_ai(client, stock_name, new_reports, changes)

        stock_results[stock_name] = {
            "new_reports": new_reports,
            "all_reports": reports,
            "changes": changes,
            "analysis": analysis,
        }

        # 이력 업데이트
        history[stock_name] = {
            "reports": reports[:50],
            "last_updated": today.strftime("%Y-%m-%d"),
        }

    save_history(history)

    # 노션 저장
    print("  노션 저장 중...")
    db_id = get_or_create_notion_db()
    for stock_name, result in stock_results.items():
        save_to_notion(
            db_id, stock_name,
            result["new_reports"], result["changes"], result["analysis"], today
        )
        time.sleep(1)

    # PDF 생성
    print("  PDF 생성 중...")
    pdf = generate_tracker_pdf(stock_results, report_date)

    # 요약 메시지
    summary_lines = []
    for stock_name, result in stock_results.items():
        n = len(result["new_reports"])
        c = len(result["changes"])
        summary_lines.append(f"• {stock_name}: 새 리포트 {n}건, 변화 {c}건")

    send_message(
        f"📈 <b>종목 리포트 추적 리포트</b>\n"
        f"📅 {report_date}\n\n"
        + "\n".join(summary_lines) +
        "\n\n전체 분석은 PDF 확인 ↓"
    )
    time.sleep(1)
    send_pdf(pdf, f"tracker_{date_str}.pdf", f"📈 종목 리포트 추적 {report_date}")
    print("  완료!")


if __name__ == "__main__":
    main()
