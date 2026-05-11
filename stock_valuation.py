"""
주식 내재가치 분석 리포트
- yfinance 실시간 데이터 수집
- DCF + PER + PBR + EV/EBITDA 멀티플 모델
- PDF 생성 → 텔레그램 전송
"""

import os, io, time, requests, sys
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, Table, TableStyle, KeepTogether)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID   = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

# ── 분석 대상 종목 ─────────────────────────────────────────────────────────────
STOCKS = [
    # 해외
    {"ticker": "TSLA", "name": "Tesla",       "type": "growth",     "cur": "USD", "wacc": 0.11, "g5": 0.20, "gt": 0.03},
    {"ticker": "AMD",  "name": "AMD",         "type": "growth",     "cur": "USD", "wacc": 0.11, "g5": 0.20, "gt": 0.03},
    {"ticker": "INTC", "name": "Intel",       "type": "turnaround", "cur": "USD", "wacc": 0.10, "g5": 0.15, "gt": 0.02},
    {"ticker": "QCOM", "name": "Qualcomm",    "type": "value",      "cur": "USD", "wacc": 0.10, "g5": 0.15, "gt": 0.03},
    {"ticker": "ARM",  "name": "ARM Holdings","type": "growth",     "cur": "USD", "wacc": 0.09, "g5": 0.25, "gt": 0.04},
    # 국내
    {"ticker": "005930.KS", "name": "삼성전자",   "type": "mixed",    "cur": "KRW", "wacc": 0.09, "g5": 0.10, "gt": 0.03},
    {"ticker": "000660.KS", "name": "SK하이닉스", "type": "cyclical", "cur": "KRW", "wacc": 0.10, "g5": 0.15, "gt": 0.025},
    {"ticker": "066570.KS", "name": "LG전자",     "type": "value",    "cur": "KRW", "wacc": 0.09, "g5": 0.08, "gt": 0.02},
    {"ticker": "298040.KS", "name": "효성중공업", "type": "theme",    "cur": "KRW", "wacc": 0.10, "g5": 0.20, "gt": 0.02},
    {"ticker": "253590.KS", "name": "네오셈",     "type": "theme",    "cur": "KRW", "wacc": 0.12, "g5": 0.30, "gt": 0.02},
    {"ticker": "092870.KS", "name": "엑시콘",     "type": "theme",    "cur": "KRW", "wacc": 0.11, "g5": 0.25, "gt": 0.02},
]

# 업종별 적정 멀티플 벤치마크
PEER = {
    "growth":     {"per_fair": 60,  "per_high": 120, "ev_fair": 40,  "ev_high": 80},
    "cyclical":   {"per_fair": 15,  "per_high": 25,  "ev_fair": 8,   "ev_high": 12},
    "mixed":      {"per_fair": 15,  "per_high": 25,  "ev_fair": 9,   "ev_high": 14},
    "value":      {"per_fair": 15,  "per_high": 22,  "ev_fair": 12,  "ev_high": 18},
    "turnaround": {"per_fair": 40,  "per_high": 80,  "ev_fair": 20,  "ev_high": 35},
    "theme":      {"per_fair": 40,  "per_high": 80,  "ev_fair": 25,  "ev_high": 50},
}

TYPE_KR = {
    "growth": "성장주", "cyclical": "경기순환주", "mixed": "혼합형",
    "value": "가치주", "turnaround": "턴어라운드", "theme": "테마주",
}

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    bold_c = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    ]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR",   font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

# ── 텔레그램 ─────────────────────────────────────────────────────────────────
def send_text(msg):
    if not BOT_TOKEN:
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg[:4000], "parse_mode": "HTML"},
        timeout=15,
    )

def send_pdf(buf, filename, caption=""):
    if not BOT_TOKEN:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": CHAT_ID, "caption": caption[:1000]},
            files={"document": (filename, buf, "application/pdf")},
            timeout=60,
        )
        if not r.ok:
            print(f"[PDF 오류] {r.text[:200]}")
    except Exception as e:
        print(f"[PDF 예외] {e}")

# ── yfinance 데이터 수집 ──────────────────────────────────────────────────────
def fetch(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        price     = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        mktcap    = info.get("marketCap") or 0
        trail_pe  = info.get("trailingPE")
        fwd_pe    = info.get("forwardPE")
        pbr       = info.get("priceToBook")
        ev_ebitda = info.get("enterpriseToEbitda")
        psr       = info.get("priceToSalesTrailing12Months")
        eps       = info.get("trailingEps") or 0
        bps       = info.get("bookValue") or 0
        revenue   = info.get("totalRevenue") or 0
        op_cf     = info.get("operatingCashflow") or 0
        capex     = info.get("capitalExpenditures") or 0   # 보통 음수
        fcf       = info.get("freeCashflow") or (op_cf + capex)  # capex 음수이므로 더함
        ebitda    = info.get("ebitda") or 0
        ev        = info.get("enterpriseValue") or 0
        debt      = info.get("totalDebt") or 0
        cash      = info.get("totalCash") or 0
        roe       = info.get("returnOnEquity") or 0
        op_margin = info.get("operatingMargins") or 0
        rev_growth= info.get("revenueGrowth") or 0
        beta      = info.get("beta") or 1.0
        shares    = info.get("sharesOutstanding") or (mktcap / price if price else 1)
        name_long = info.get("shortName") or info.get("longName") or ticker
        analyst_target = info.get("targetMeanPrice") or 0

        return {
            "ticker": ticker, "name_long": name_long,
            "price": price, "mktcap": mktcap, "shares": shares,
            "trail_pe": trail_pe, "fwd_pe": fwd_pe,
            "pbr": pbr, "ev_ebitda": ev_ebitda, "psr": psr,
            "eps": eps, "bps": bps,
            "revenue": revenue, "ebitda": ebitda, "ev": ev,
            "debt": debt, "cash": cash,
            "op_cf": op_cf, "capex": capex, "fcf": fcf,
            "roe": roe, "op_margin": op_margin,
            "rev_growth": rev_growth, "beta": beta,
            "analyst_target": analyst_target,
            "ok": price > 0,
        }
    except Exception as e:
        print(f"[yfinance 오류] {ticker}: {e}")
        return {"ticker": ticker, "ok": False, "price": 0}

# ── DCF 계산 ─────────────────────────────────────────────────────────────────
def calc_dcf(d, cfg):
    """FCF 기반 5년 DCF → 주당 내재가치 반환. 실패 시 None."""
    fcf    = d.get("fcf", 0) or 0
    shares = d.get("shares", 0) or 1
    wacc   = cfg["wacc"]
    g5     = cfg["g5"]
    gt     = cfg["gt"]

    if fcf <= 0:
        return None  # FCF 음수면 DCF 산출 불가

    pv_fcf = 0
    cf = fcf
    for yr in range(1, 6):
        cf *= (1 + g5)
        pv_fcf += cf / (1 + wacc) ** yr

    # 터미널 밸류
    tv    = cf * (1 + gt) / (wacc - gt)
    pv_tv = tv / (1 + wacc) ** 5

    net_cash = (d.get("cash") or 0) - (d.get("debt") or 0)
    equity   = pv_fcf + pv_tv + net_cash
    per_share = equity / shares
    return per_share

# ── 멀티플 기반 적정가 ────────────────────────────────────────────────────────
def calc_multiples(d, cfg):
    stype   = cfg["type"]
    p       = PEER[stype]
    price   = d["price"]
    results = {}

    # PER 기반
    eps = d.get("eps") or 0
    if eps > 0:
        results["per_fair"]  = eps * p["per_fair"]
        results["per_high"]  = eps * p["per_high"]

    # EV/EBITDA 기반
    ebitda = d.get("ebitda") or 0
    shares = d.get("shares") or 1
    net_cash = (d.get("cash") or 0) - (d.get("debt") or 0)
    if ebitda > 0:
        results["ev_fair"]   = (ebitda * p["ev_fair"]  + net_cash) / shares
        results["ev_high"]   = (ebitda * p["ev_high"]  + net_cash) / shares

    # PBR 기반 (가치주·혼합형에만)
    bps = d.get("bps") or 0
    if bps > 0 and stype in ("value", "mixed", "cyclical"):
        results["pbr_fair"] = bps * 1.5
        results["pbr_high"] = bps * 2.5

    return results

# ── 고평가/저평가 판단 ────────────────────────────────────────────────────────
def judge(price, targets):
    if not targets:
        return "판단 불가", colors.HexColor("#888888")
    fair_vals = [v for k, v in targets.items() if "fair" in k and v > 0]
    if not fair_vals:
        return "판단 불가", colors.HexColor("#888888")
    avg_fair = sum(fair_vals) / len(fair_vals)
    ratio = price / avg_fair
    if ratio < 0.85:
        return f"저평가 ({ratio:.1%})", colors.HexColor("#1a6fb5")
    elif ratio < 1.15:
        return f"적정 ({ratio:.1%})", colors.HexColor("#2e7d32")
    elif ratio < 1.50:
        return f"소폭 고평가 ({ratio:.1%})", colors.HexColor("#e65100")
    else:
        return f"고평가 ({ratio:.1%})", colors.HexColor("#c62828")

# ── 숫자 포맷 ─────────────────────────────────────────────────────────────────
def fmt_price(v, cur):
    if not v:
        return "-"
    if cur == "KRW":
        return f"{v:,.0f}원"
    return f"${v:,.2f}"

def fmt_big(v, cur):
    if not v:
        return "-"
    if cur == "KRW":
        if v >= 1e12:
            return f"{v/1e12:.1f}조"
        if v >= 1e8:
            return f"{v/1e8:.0f}억"
        return f"{v:,.0f}"
    else:
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"

def fmt_pct(v):
    return f"{v*100:.1f}%" if v else "-"

def fmt_x(v):
    return f"{v:.1f}배" if v else "-"

# ── PDF 생성 ─────────────────────────────────────────────────────────────────
def build_pdf(results, date_str):
    fn, fnb = setup_font()

    def S(nm, **kw):
        return ParagraphStyle(nm, fontName=fn, **kw)
    def SB(nm, **kw):
        return ParagraphStyle(nm, fontName=fnb, **kw)

    ST = {
        "title":   SB("ti", fontSize=20, leading=26, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":     S ("su", fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":      SB("h2", fontSize=13, leading=18, spaceBefore=14,spaceAfter=6, textColor=colors.HexColor("#1a3a5c")),
        "h3":      SB("h3", fontSize=10, leading=15, spaceBefore=6, spaceAfter=3, textColor=colors.HexColor("#c0392b")),
        "label":   SB("lb", fontSize=8,  leading=12, textColor=colors.HexColor("#1a3a5c")),
        "val":     S ("vl", fontSize=8,  leading=12, textColor=colors.HexColor("#111")),
        "body":    S ("bo", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#222")),
        "note":    S ("no", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
        "tag_g":   SB("tg", fontSize=8,  leading=12, textColor=colors.HexColor("#1a6fb5")),
        "tag_r":   SB("tr", fontSize=8,  leading=12, textColor=colors.HexColor("#c62828")),
        "tag_n":   SB("tn", fontSize=8,  leading=12, textColor=colors.HexColor("#2e7d32")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm, bottomMargin=1.8*cm)
    story = []
    W = doc.width

    # ── 커버 ──
    story.append(Paragraph("📊 주식 내재가치 분석 리포트", ST["title"]))
    story.append(Paragraph(f"{date_str}  ·  총 {len(results)}개 종목  ·  yfinance 실시간 데이터", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # ── 요약 테이블 ──
    story.append(Paragraph("전종목 요약", ST["h2"]))
    hdr = ["종목", "현재가", "유형", "PER", "PBR", "EV/EBITDA", "판단"]
    rows = [hdr]
    for r in results:
        cfg   = r["cfg"]
        d     = r["data"]
        cur   = cfg["cur"]
        jtext, jcol = r["judgment"]
        rows.append([
            f"{cfg['name']}\n({cfg['ticker']})",
            fmt_price(d.get("price"), cur),
            TYPE_KR.get(cfg["type"], cfg["type"]),
            fmt_x(d.get("trail_pe")),
            fmt_x(d.get("pbr")),
            fmt_x(d.get("ev_ebitda")),
            jtext,
        ])

    col_w = [W*0.16, W*0.13, W*0.11, W*0.10, W*0.10, W*0.14, W*0.26]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",    (0,0), (-1,0),  colors.white),
        ("FONTNAME",     (0,0), (-1,0),  fnb),
        ("FONTSIZE",     (0,0), (-1,-1), 7),
        ("FONTNAME",     (0,1), (-1,-1), fn),
        ("ALIGN",        (1,0), (-1,-1), "CENTER"),
        ("ALIGN",        (0,0), (0,-1),  "LEFT"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.HexColor("#f8f9fa"), colors.white]),
        ("GRID",         (0,0), (-1,-1), 0.3, colors.HexColor("#ddd")),
        ("TOPPADDING",   (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ("LEFTPADDING",  (0,0), (-1,-1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))

    # ── 종목별 상세 ──
    for r in results:
        cfg  = r["cfg"]
        d    = r["data"]
        dcf  = r["dcf"]
        mult = r["multiples"]
        cur  = cfg["cur"]
        jtext, jcol = r["judgment"]

        story.append(Spacer(1, 0.2*cm))

        # 종목 헤더
        type_str = TYPE_KR.get(cfg["type"], cfg["type"])
        title_para = Paragraph(
            f"{cfg['name']}  <font size='9' color='#666'>({cfg['ticker']})  [{type_str}]</font>",
            ST["h2"]
        )
        judge_para = Paragraph(jtext, ST["body"])
        hdr_data = [[title_para, judge_para]]
        hdr_t = Table(hdr_data, colWidths=[W*0.75, W*0.25])
        hdr_t.setStyle(TableStyle([
            ("VALIGN",        (0,0),(-1,-1),"BOTTOM"),
            ("ALIGN",         (1,0),(1,0),  "RIGHT"),
            ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#f0f4f8")),
            ("LEFTPADDING",   (0,0),(-1,-1), 6),
            ("RIGHTPADDING",  (0,0),(-1,-1), 6),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
            ("BOX",           (0,0),(-1,-1), 0.5, colors.HexColor("#1a3a5c")),
        ]))
        story.append(KeepTogether([hdr_t]))
        story.append(Spacer(1, 0.2*cm))

        # ── 핵심 지표 테이블 ──
        price_str  = fmt_price(d.get("price"), cur)
        mktcap_str = fmt_big(d.get("mktcap"), cur)
        rev_str    = fmt_big(d.get("revenue"), cur)
        fcf_str    = fmt_big(d.get("fcf"), cur) if (d.get("fcf") or 0) > 0 else "음수/N/A"
        roe_str    = fmt_pct(d.get("roe"))
        margin_str = fmt_pct(d.get("op_margin"))
        growth_str = fmt_pct(d.get("rev_growth"))
        analyst_t  = fmt_price(d.get("analyst_target"), cur) if d.get("analyst_target") else "N/A"

        metric_rows = [
            ["현재가", price_str,          "시가총액", mktcap_str],
            ["매출(TTM)", rev_str,         "FCF",      fcf_str],
            ["영업이익률", margin_str,     "ROE",      roe_str],
            ["매출성장(YoY)", growth_str,  "애널 목표", analyst_t],
        ]
        mt = Table(metric_rows, colWidths=[W*0.15, W*0.22, W*0.15, W*0.22])
        mt.setStyle(TableStyle([
            ("FONTNAME",     (0,0), (-1,-1), fn),
            ("FONTNAME",     (0,0), (0,-1),  fnb),
            ("FONTNAME",     (2,0), (2,-1),  fnb),
            ("FONTSIZE",     (0,0), (-1,-1), 7.5),
            ("TEXTCOLOR",    (0,0), (0,-1),  colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR",    (2,0), (2,-1),  colors.HexColor("#1a3a5c")),
            ("ALIGN",        (1,0), (1,-1),  "RIGHT"),
            ("ALIGN",        (3,0), (3,-1),  "RIGHT"),
            ("GRID",         (0,0), (-1,-1), 0.3, colors.HexColor("#ddd")),
            ("TOPPADDING",   (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",(0,0), (-1,-1), 3),
            ("LEFTPADDING",  (0,0), (-1,-1), 5),
        ]))
        story.append(mt)
        story.append(Spacer(1, 0.2*cm))

        # ── 밸류에이션 모델 ──
        story.append(Paragraph("밸류에이션 모델", ST["h3"]))

        val_rows = [["모델", "목표가 (적정)", "목표가 (고점)", "현재가 대비"]]
        cur_price = d.get("price") or 0

        # DCF
        if dcf and dcf > 0:
            diff = (dcf / cur_price - 1) * 100 if cur_price else 0
            flag = "▲" if diff > 0 else "▼"
            val_rows.append(["DCF",
                              fmt_price(dcf, cur),
                              "-",
                              f"{flag}{abs(diff):.1f}%"])
        else:
            val_rows.append(["DCF", "FCF 음수 - 산출 불가", "-", "-"])

        # PER 기반
        if mult.get("per_fair"):
            pf = mult["per_fair"]
            ph = mult.get("per_high", 0)
            diff = (pf / cur_price - 1) * 100 if cur_price else 0
            flag = "▲" if diff > 0 else "▼"
            val_rows.append(["PER 멀티플",
                              fmt_price(pf, cur),
                              fmt_price(ph, cur) if ph else "-",
                              f"{flag}{abs(diff):.1f}%"])

        # EV/EBITDA 기반
        if mult.get("ev_fair"):
            ef = mult["ev_fair"]
            eh = mult.get("ev_high", 0)
            diff = (ef / cur_price - 1) * 100 if cur_price else 0
            flag = "▲" if diff > 0 else "▼"
            val_rows.append(["EV/EBITDA",
                              fmt_price(ef, cur),
                              fmt_price(eh, cur) if eh else "-",
                              f"{flag}{abs(diff):.1f}%"])

        # PBR 기반
        if mult.get("pbr_fair"):
            bf = mult["pbr_fair"]
            bh = mult.get("pbr_high", 0)
            diff = (bf / cur_price - 1) * 100 if cur_price else 0
            flag = "▲" if diff > 0 else "▼"
            val_rows.append(["PBR",
                              fmt_price(bf, cur),
                              fmt_price(bh, cur) if bh else "-",
                              f"{flag}{abs(diff):.1f}%"])

        # 현재 멀티플 현황
        val_rows.append(["─── 현재 지표 ───", "", "", ""])
        val_rows.append(["PER (Trail / 선행)",
                          fmt_x(d.get("trail_pe")),
                          fmt_x(d.get("fwd_pe")), ""])
        val_rows.append(["PBR / EV/EBITDA",
                          fmt_x(d.get("pbr")),
                          fmt_x(d.get("ev_ebitda")), ""])

        col_w2 = [W*0.22, W*0.24, W*0.24, W*0.20]
        vt = Table(val_rows, colWidths=col_w2, repeatRows=1)
        vt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#2c5282")),
            ("TEXTCOLOR",     (0,0),(-1,0),  colors.white),
            ("FONTNAME",      (0,0),(-1,0),  fnb),
            ("FONTNAME",      (0,1),(-1,-1), fn),
            ("FONTSIZE",      (0,0),(-1,-1), 7.5),
            ("ALIGN",         (1,0),(-1,-1), "CENTER"),
            ("ALIGN",         (0,0),(0,-1),  "LEFT"),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.HexColor("#f0f4f8"), colors.white]),
            ("GRID",          (0,0),(-1,-1), 0.3, colors.HexColor("#ccc")),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 5),
            # 구분선 행
            ("BACKGROUND",    (0,-3),(-1,-3), colors.HexColor("#e8ecf0")),
            ("FONTNAME",      (0,-3),(0,-3),  fnb),
        ]))
        story.append(vt)

        # DCF 가정 표시
        story.append(Spacer(1, 0.1*cm))
        story.append(Paragraph(
            f"DCF 가정: 5년 성장률 {cfg['g5']*100:.0f}%/yr | 터미널 성장 {cfg['gt']*100:.1f}% | WACC {cfg['wacc']*100:.0f}%",
            ST["note"]
        ))

        story.append(Spacer(1, 0.3*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaa")))

    # 주의사항
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "⚠ 본 리포트는 yfinance 공개 데이터 기반 자동 산출 결과이며 투자 권유가 아닙니다. "
        "DCF는 FCF 양수 종목만 산출. 멀티플은 업종 피어 벤치마크 기준.",
        ST["note"]
    ))

    doc.build(story)
    buf.seek(0)
    return buf

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일 %H:%M")
    print(f"=== 주식 분석 시작: {date_str} ===")

    send_text(f"⏳ 주식 내재가치 분석 시작...\n{date_str}\n종목 {len(STOCKS)}개 데이터 수집 중")

    results = []
    for cfg in STOCKS:
        print(f"  [{cfg['ticker']}] 수집 중...")
        d    = fetch(cfg["ticker"])
        dcf  = calc_dcf(d, cfg)  if d["ok"] else None
        mult = calc_multiples(d, cfg) if d["ok"] else {}

        # 판단 근거: DCF + 멀티플 목표가 평균
        all_targets = {}
        if dcf:
            all_targets["dcf"] = dcf
        all_targets.update(mult)
        judgment = judge(d.get("price", 0), all_targets)

        results.append({
            "cfg": cfg, "data": d,
            "dcf": dcf, "multiples": mult,
            "judgment": judgment,
        })
        time.sleep(0.5)

    print("  PDF 생성 중...")
    buf = build_pdf(results, date_str)

    # 요약 텍스트
    lines = ["📊 <b>주식 내재가치 분석 완료</b>\n"]
    for r in results:
        jtext, _ = r["judgment"]
        price = fmt_price(r["data"].get("price"), r["cfg"]["cur"])
        lines.append(f"• {r['cfg']['name']} {price} → {jtext}")
    summary = "\n".join(lines)

    filename = f"stock_valuation_{now.strftime('%Y%m%d_%H%M')}.pdf"
    send_pdf(buf, filename, caption=summary)
    print(f"  전송 완료: {filename}")

if __name__ == "__main__":
    main()
