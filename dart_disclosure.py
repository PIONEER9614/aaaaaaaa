"""
DART 전자공시 수집 시스템
- 유상증자, 투자결정, 합병, 실적 등 주요 기업 공시
- 매일 오후 7시 PDF로 텔레그램 전송 (장 마감 후)
"""

import os
import io
import time
import requests
from groq import Groq
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

DART_API_KEY = (os.getenv("DART_API_KEY") or "").strip()
BOT_TOKEN    = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID      = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()

# ─── 공시 유형 분류 ────────────────────────────────────────────────────
# DART 공시유형 코드 → 한국어 이름
DISCLOSURE_TYPES = {
    "A": "정기공시 (실적/사업보고서)",
    "B": "주요사항 보고 (유상증자·무상증자·합병 등)",
    "C": "발행공시 (신주·채권 발행)",
    "D": "지분공시 (대량보유·임원 매매)",
    "E": "기타공시",
    "I": "거래소공시 (투자결정·공장건설 등)",
}

# 중요도 높은 유형 순서
PRIORITY_ORDER = ["B", "I", "C", "A", "D", "E"]


# ─── 한국어 폰트 ────────────────────────────────────────────────────────
def _find_font(paths):
    for p in paths:
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


# ─── DART API 공시 수집 ────────────────────────────────────────────────
def fetch_disclosures(days=1):
    """최근 days일간 전체 상장사 공시 수집"""
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    all_items = []
    for pblntf_ty in PRIORITY_ORDER:
        try:
            resp = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "bgn_de": start,
                    "end_de": end,
                    "pblntf_ty": pblntf_ty,
                    "page_no": 1,
                    "page_count": 100,
                    "sort": "date",
                    "sort_mth": "desc",
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("status") == "000" and data.get("list"):
                for item in data["list"]:
                    item["pblntf_ty"] = pblntf_ty
                    all_items.append(item)
                print(f"  {DISCLOSURE_TYPES.get(pblntf_ty, pblntf_ty)}: {len(data['list'])}건")
            time.sleep(0.5)
        except Exception as e:
            print(f"  [DART 오류] {pblntf_ty}: {e}")

    return all_items


# ─── AI 요약 ────────────────────────────────────────────────────────────
def summarize_type(client, type_name, items):
    """공시 유형별 AI 요약"""
    if not items:
        return None

    titles = "\n".join(
        f"- [{item.get('corp_name', '')}] {item.get('report_nm', '')}"
        for item in items[:15]
    )
    prompt = (
        f"다음은 오늘 나온 '{type_name}' 관련 기업 공시 목록입니다.\n"
        f"투자자 관점에서 주목할 만한 내용을 3~5줄로 한국어로 요약해주세요.\n\n"
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
def generate_dart_pdf(grouped, summaries, report_date, total):
    register_fonts()
    fn  = "KR"      if FONT_OK else "Helvetica"
    fnb = "KR-Bold" if FONT_OK else "Helvetica-Bold"

    s = {
        "title":    ParagraphStyle("title",    fontName=fnb, fontSize=17, leading=22,
                                    spaceAfter=6,  textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle("subtitle", fontName=fn,  fontSize=10, leading=13,
                                    spaceAfter=8,  textColor=colors.HexColor("#555555")),
        "h2":       ParagraphStyle("h2",       fontName=fnb, fontSize=12, leading=16,
                                    spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#16213e")),
        "summary":  ParagraphStyle("summary",  fontName=fn,  fontSize=9,  leading=13,
                                    spaceAfter=4,  textColor=colors.HexColor("#333333")),
        "corp":     ParagraphStyle("corp",     fontName=fnb, fontSize=8,  leading=12,
                                    textColor=colors.HexColor("#0f3460")),
        "report":   ParagraphStyle("report",   fontName=fn,  fontSize=8,  leading=12,
                                    spaceAfter=1,  textColor=colors.HexColor("#444444")),
        "link":     ParagraphStyle("link",     fontName=fn,  fontSize=7,  leading=10,
                                    textColor=colors.HexColor("#0066cc")),
        "small":    ParagraphStyle("small",    fontName=fn,  fontSize=7,  leading=10,
                                    textColor=colors.HexColor("#888888")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    story.append(Paragraph("DART 기업 공시 일일 리포트", s["title"]))
    story.append(Paragraph(f"기준일: {report_date}  |  총 {total}건", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 0.3*cm))

    # 공시 유형별 건수 요약 테이블
    t_data = [["공시 유형", "건수"]]
    for ty in PRIORITY_ORDER:
        items = grouped.get(ty, [])
        if items:
            t_data.append([DISCLOSURE_TYPES.get(ty, ty), f"{len(items)}건"])
    if len(t_data) > 1:
        t = Table(t_data, colWidths=[12*cm, 3*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,-1), fn),
            ("FONTSIZE",   (0,0), (-1,0), 9),
            ("FONTSIZE",   (0,1), (-1,-1), 8),
            ("ALIGN",      (0,0), (-1,-1), "CENTER"),
            ("ALIGN",      (0,1), (0,-1),  "LEFT"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.4*cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cccccc")))

    # 유형별 상세
    for ty in PRIORITY_ORDER:
        items = grouped.get(ty, [])
        if not items:
            continue

        type_name = DISCLOSURE_TYPES.get(ty, ty)
        story.append(Paragraph(f"📌 {type_name} ({len(items)}건)", s["h2"]))

        # AI 요약
        if summaries.get(ty):
            story.append(Paragraph(summaries[ty], s["summary"]))
            story.append(Spacer(1, 0.15*cm))

        # 공시 목록
        for item in items[:30]:
            corp = item.get("corp_name", "")
            report = item.get("report_nm", "")
            rcept_no = item.get("rcept_no", "")
            corp_cls = {"Y": "코스피", "K": "코스닥", "N": "코넥스", "E": "기타"}.get(
                item.get("corp_cls", ""), ""
            )
            link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""

            story.append(Paragraph(f"▸ {corp}  [{corp_cls}]", s["corp"]))
            story.append(Paragraph(f"   {report}", s["report"]))
            if link:
                story.append(Paragraph(link, s["link"]))
            story.append(Spacer(1, 0.1*cm))

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
    print(f"=== DART 공시 수집: {report_date} ===")

    # 공시 수집
    items = fetch_disclosures(days=1)
    if not items:
        print("  오늘 공시 없음")
        send_message(f"📋 <b>DART 공시 리포트</b>\n{report_date}\n\n오늘 공시 없음")
        return

    # 유형별 그룹화
    grouped = defaultdict(list)
    for item in items:
        grouped[item["pblntf_ty"]].append(item)

    total = len(items)
    print(f"  총 {total}건 수집 완료")

    # AI 요약
    client = Groq(api_key=GROQ_API_KEY)
    summaries = {}
    for ty in ["B", "I", "C"]:  # 중요 유형만 요약
        if grouped.get(ty):
            time.sleep(4)
            summaries[ty] = summarize_type(client, DISCLOSURE_TYPES.get(ty, ty), grouped[ty])

    # PDF 생성
    print("  PDF 생성 중...")
    pdf = generate_dart_pdf(grouped, summaries, report_date, total)

    # 주요 공시 요약 메시지
    highlights = []
    for ty in ["B", "I"]:
        for item in grouped.get(ty, [])[:3]:
            highlights.append(f"• [{item.get('corp_name','')}] {item.get('report_nm','')[:35]}")

    highlight_text = "\n".join(highlights) or "주요 공시 없음"

    send_message(
        f"📋 <b>DART 기업 공시 리포트</b>\n"
        f"📅 {report_date}\n\n"
        f"총 <b>{total}건</b> 공시\n\n"
        f"<b>주요 공시:</b>\n{highlight_text}\n\n"
        f"전체 내용은 PDF 확인 ↓"
    )
    time.sleep(1)
    send_pdf(pdf, f"dart_{date_str}.pdf", f"📋 DART 공시 리포트 {report_date}")
    print("  완료!")


if __name__ == "__main__":
    main()
