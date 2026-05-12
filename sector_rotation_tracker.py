"""
월별 섹터 로테이션 자동 기록
- 한국/미국 섹터 ETF 수익률 집계
- Groq LLM으로 매크로 이벤트 + 로테이션 분석
- PDF 생성 → 텔레그램 전송
- data/sector_rotation_history.json에 누적 저장

실행: python sector_rotation_tracker.py [YYYY-MM]
      (기본: 이전 달 기준)
"""

import os, io, sys, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import yfinance as yf
from groq import Groq

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TG_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")
GROQ_KEY  = os.getenv("GROQ_API_KEY", "")
HIST_FILE = Path("data/sector_rotation_history.json")

client = Groq(api_key=GROQ_KEY)

KR_ETFS = {
    "반도체":  "091160.KS",
    "2차전지": "305720.KS",
    "바이오":  "244580.KS",
    "금융":    "091170.KS",
    "자동차":  "091180.KS",
    "IT":      "267490.KS",
    "에너지":  "117460.KS",
}

US_ETFS = {
    "Tech":       "XLK",
    "Energy":     "XLE",
    "Finance":    "XLF",
    "Health":     "XLV",
    "Industrial": "XLI",
    "Materials":  "XLB",
    "Consumer":   "XLY",
    "Utilities":  "XLU",
    "Real Estate":"XLRE",
    "Semis":      "SOXX",
}

ANALYSIS_PROMPT = """당신은 섹터 로테이션 전략 전문가입니다.
아래 데이터를 보고 투자자 관점의 분석을 작성하세요.

작성 내용:
1. **이달의 로테이션 요약** (2-3줄): 어떤 섹터가 주도했고 왜인지
2. **주목할 섹터** (2개): 모멘텀이 붙고 있거나 반전 조짐인 섹터
3. **다음 달 시나리오** (2-3줄): 현재 흐름이 이어질 조건 vs 반전 조건
4. **행동 신호**: "지금 진입 가능", "관망", "비중 축소" 중 하나 + 이유

한국어로, 투자 실전에 쓸 수 있게 구체적으로 작성."""

# ─────────────────────────────────────────────────────────────────────────────
# 폰트
# ─────────────────────────────────────────────────────────────────────────────
def setup_font():
    cands = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf"]
    bolds = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    f = next((p for p in cands if os.path.exists(p)), None)
    b = next((p for p in bolds if os.path.exists(p)), f)
    if f:
        try:
            pdfmetrics.registerFont(TTFont("KR", f))
            pdfmetrics.registerFont(TTFont("KR-B", b or f))
            return "KR", "KR-B"
        except: pass
    return "Helvetica", "Helvetica-Bold"

# ─────────────────────────────────────────────────────────────────────────────
# 수익률 수집
# ─────────────────────────────────────────────────────────────────────────────
def get_monthly_return(ticker, year, month):
    """해당 월의 시작→종가 수익률(%) 반환"""
    try:
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        start = f"{year}-{month:02d}-01"
        # end는 다음달 1일로 설정해야 마지막 거래일 포함
        if month == 12:
            end = f"{year+1}-01-01"
        else:
            end = f"{year}-{month+1:02d}-01"
        df = yf.download(ticker, start=start, end=end,
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 2:
            return None
        # yfinance v0.2+ 멀티레벨 컬럼 처리
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        first = float(close.iloc[0])
        last  = float(close.iloc[-1])
        return round((last - first) / first * 100, 2)
    except:
        return None

def collect_returns(year, month):
    print(f"  한국 섹터 ETF ({len(KR_ETFS)}개)...")
    kr = {}
    for name, ticker in KR_ETFS.items():
        r = get_monthly_return(ticker, year, month)
        kr[name] = r
        sym = "+" if (r or 0) >= 0 else ""
        print(f"    {name:<8} {sym}{r:.1f}%" if r is not None else f"    {name:<8} N/A")
        time.sleep(0.3)

    print(f"  미국 섹터 ETF ({len(US_ETFS)}개)...")
    us = {}
    for name, ticker in US_ETFS.items():
        r = get_monthly_return(ticker, year, month)
        us[name] = r
        sym = "+" if (r or 0) >= 0 else ""
        print(f"    {name:<12} {sym}{r:.1f}%" if r is not None else f"    {name:<12} N/A")
        time.sleep(0.3)

    return kr, us

# ─────────────────────────────────────────────────────────────────────────────
# LLM 분석
# ─────────────────────────────────────────────────────────────────────────────
def format_returns_for_llm(kr, us, year, month):
    lines = [f"대상 기간: {year}년 {month}월\n"]
    lines.append("=== 한국 섹터 ETF 수익률 ===")
    for k, v in sorted(kr.items(), key=lambda x: x[1] or -99, reverse=True):
        s = f"+{v:.1f}%" if v is not None and v >= 0 else (f"{v:.1f}%" if v is not None else "N/A")
        lines.append(f"  {k}: {s}")
    lines.append("\n=== 미국 섹터 ETF 수익률 ===")
    for k, v in sorted(us.items(), key=lambda x: x[1] or -99, reverse=True):
        s = f"+{v:.1f}%" if v is not None and v >= 0 else (f"{v:.1f}%" if v is not None else "N/A")
        lines.append(f"  {k}: {s}")
    return "\n".join(lines)

def analyze_rotation(kr, us, year, month):
    print("  LLM 분석 중...")
    data_text = format_returns_for_llm(kr, us, year, month)
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": ANALYSIS_PROMPT},
                {"role": "user",   "content": data_text},
            ],
            temperature=0.3, max_tokens=1024,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"분석 실패: {e}"

# ─────────────────────────────────────────────────────────────────────────────
# 히스토리
# ─────────────────────────────────────────────────────────────────────────────
def load_history():
    if HIST_FILE.exists():
        return json.loads(HIST_FILE.read_text(encoding="utf-8"))
    return {}

def save_history(hist):
    HIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    HIST_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# PDF 생성
# ─────────────────────────────────────────────────────────────────────────────
def return_color(v):
    if v is None:    return colors.HexColor("#999")
    if v >= 5:       return colors.HexColor("#c0392b")
    if v >= 2:       return colors.HexColor("#e74c3c")
    if v >= 0:       return colors.HexColor("#27ae60")
    if v >= -2:      return colors.HexColor("#2980b9")
    return              colors.HexColor("#1a5276")

def build_table(data_dict, fn):
    rows = [["섹터", "수익률"]]
    sorted_items = sorted(data_dict.items(), key=lambda x: x[1] or -99, reverse=True)
    for name, v in sorted_items:
        label = f"+{v:.1f}%" if (v or 0) >= 0 else f"{v:.1f}%"
        rows.append([name, label if v is not None else "N/A"])

    style = TableStyle([
        ("FONT",       (0, 0), (-1, -1), fn, 8),
        ("FONT",       (0, 0), (-1,  0), fn, 8),
        ("BACKGROUND", (0, 0), (-1,  0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",  (0, 0), (-1,  0), colors.white),
        ("ALIGN",      (1, 0), (1, -1), "RIGHT"),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.HexColor("#ccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f9f9f9"), colors.white]),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    for i, (name, v) in enumerate(sorted_items, 1):
        c = return_color(v)
        style.add("TEXTCOLOR", (1, i), (1, i), c)

    return Table(rows, colWidths=[5*cm, 3*cm], style=style)

def build_pdf(year, month, kr, us, analysis):
    fn, fnb = setup_font()
    ST = {
        "title":   ParagraphStyle("t",  fontName=fnb, fontSize=16, leading=22, spaceAfter=4,
                                  textColor=colors.HexColor("#0d1b2a")),
        "sub":     ParagraphStyle("s",  fontName=fn,  fontSize=8,  leading=12, spaceAfter=10,
                                  textColor=colors.HexColor("#666")),
        "section": ParagraphStyle("sc", fontName=fnb, fontSize=11, leading=16, spaceBefore=10,
                                  spaceAfter=4, textColor=colors.HexColor("#1a3a5c")),
        "body":    ParagraphStyle("b",  fontName=fn,  fontSize=8,  leading=13, spaceAfter=2,
                                  textColor=colors.HexColor("#333")),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm,  bottomMargin=2*cm)
    story = []
    story.append(Paragraph(f"📊 {year}년 {month}월 섹터 로테이션 리포트", ST["title"]))
    story.append(Paragraph(f"집계일: {datetime.now().strftime('%Y.%m.%d')}  |  한국 {len(KR_ETFS)}섹터 + 미국 {len(US_ETFS)}섹터", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # 두 테이블 나란히
    story.append(Paragraph("🇰🇷 한국 섹터", ST["section"]))
    story.append(build_table(kr, fn))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("🇺🇸 미국 섹터", ST["section"]))
    story.append(build_table(us, fn))
    story.append(Spacer(1, 0.5*cm))

    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3a5c")))
    story.append(Paragraph("💡 로테이션 분석", ST["section"]))
    for line in (analysis or "").split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.1*cm)); continue
        import re
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"[<>&]", lambda m: {"<":"&lt;",">":"&gt;","&":"&amp;"}[m.group()], line)
        try:
            story.append(Paragraph(line, ST["body"]))
        except:
            story.append(Paragraph(line[:200], ST["body"]))

    doc.build(story)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────
def send_telegram(pdf_buf, year, month):
    if not TG_TOKEN or not TG_CHAT:
        print("  Telegram 설정 없음"); return
    fname = f"섹터로테이션_{year}{month:02d}.pdf"
    kr_top = ""
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
        data={"chat_id": TG_CHAT,
              "caption": f"📊 {year}년 {month}월 섹터 로테이션 리포트\n한국 {len(KR_ETFS)}섹터 + 미국 {len(US_ETFS)}섹터"},
        files={"document": (fname, pdf_buf, "application/pdf")}, timeout=30)
    print("  ✅ Telegram 전송 완료" if r.ok else f"  ❌ {r.text[:100]}")

# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # 기본값: 이전 달
    now = datetime.now()
    if len(sys.argv) > 1:
        try:
            year, month = map(int, sys.argv[1].split("-"))
        except:
            print(f"사용법: python sector_rotation_tracker.py 2026-04"); return
    else:
        first_of_month = now.replace(day=1)
        prev = first_of_month - timedelta(days=1)
        year, month = prev.year, prev.month

    key = f"{year}-{month:02d}"
    print(f"[섹터 로테이션] {year}년 {month}월")

    hist = load_history()
    if key in hist:
        print(f"  이미 기록됨: {key} — 덮어쓰려면 data/sector_rotation_history.json에서 해당 키 삭제")
        return

    print("[수익률 수집]")
    kr, us = collect_returns(year, month)

    print("[LLM 분석]")
    analysis = analyze_rotation(kr, us, year, month)

    print("[PDF 생성]")
    pdf_buf = build_pdf(year, month, kr, us, analysis)
    out = Path("analysis")
    out.mkdir(exist_ok=True)
    path = out / f"섹터로테이션_{year}{month:02d}.pdf"
    path.write_bytes(pdf_buf.getvalue())
    print(f"  저장: {path}")

    pdf_buf.seek(0)
    send_telegram(pdf_buf, year, month)

    # 히스토리 저장
    top_kr = sorted([(k, v) for k, v in kr.items() if v is not None],
                    key=lambda x: x[1], reverse=True)[:3]
    top_us = sorted([(k, v) for k, v in us.items() if v is not None],
                    key=lambda x: x[1], reverse=True)[:3]
    bot_kr = sorted([(k, v) for k, v in kr.items() if v is not None],
                    key=lambda x: x[1])[:2]
    bot_us = sorted([(k, v) for k, v in us.items() if v is not None],
                    key=lambda x: x[1])[:2]

    hist[key] = {
        "top_kr":  [{"sector": k, "return": v} for k, v in top_kr],
        "top_us":  [{"sector": k, "return": v} for k, v in top_us],
        "bot_kr":  [{"sector": k, "return": v} for k, v in bot_kr],
        "bot_us":  [{"sector": k, "return": v} for k, v in bot_us],
        "all_kr":  kr,
        "all_us":  us,
        "analysis": analysis,
        "recorded_at": now.strftime("%Y-%m-%d"),
    }
    save_history(hist)
    print(f"  히스토리 저장 완료: {key}")

    print(f"\n[완료] {year}년 {month}월 섹터 로테이션 리포트")
    print(f"  🇰🇷 TOP3: {', '.join(f'{k}({v:+.1f}%)' for k,v in top_kr)}")
    print(f"  🇺🇸 TOP3: {', '.join(f'{k}({v:+.1f}%)' for k,v in top_us)}")


if __name__ == "__main__":
    main()
