"""
기업 종합 분석 리포트
사용법:
    python company_analysis.py 삼성전자
    python company_analysis.py 005930
    python company_analysis.py TSLA

출력: analysis/ 폴더에 PDF 저장
"""

import os, io, re, sys, json, time, requests, zipfile
import xml.etree.ElementTree as ET
import yfinance as yf
from datetime import datetime
from pathlib import Path
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
load_dotenv(Path.home() / ".claude-code-secrets" / ".env")

DART_KEY   = (os.getenv("DART_API_KEY") or "").strip()
OUTPUT_DIR = Path("analysis")
MANIFEST   = Path("data/naver_research/_meta/manifest.json")

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf"]
    bold_c     = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR",   font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

# ── DART: 종목코드 → corp_code ────────────────────────────────────────────────
def dart_get_corp_code(stock_code):
    """종목코드(6자리) → DART 고유번호 (전체 corpCode.xml 파싱)"""
    if not DART_KEY:
        return None, None
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": DART_KEY},
            timeout=30,
        )
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        tree = ET.fromstring(xml_data)
        for item in tree.findall("list"):
            sc = item.findtext("stock_code", "").strip()
            if sc == stock_code:
                corp_code = item.findtext("corp_code", "").strip()
                corp_name = item.findtext("corp_name", "").strip()
                return corp_code, corp_name
    except Exception as e:
        print(f"  [DART corp 오류] {e}")
    return None, None

# ── DART: 재무제표 수집 ───────────────────────────────────────────────────────
def dart_get_financials(corp_code, year=None):
    """연간 재무제표 3개년 수집 (손익 + 재무상태 + 현금흐름)"""
    if not DART_KEY or not corp_code:
        return {}

    target_year = year or datetime.now().year - 1  # 전년도 사업보고서
    results = {}

    for bsns_year in [target_year, target_year - 1, target_year - 2]:
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key": DART_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  str(bsns_year),
                    "reprt_code": "11011",  # 사업보고서 (11014는 3분기)
                    "fs_div":     "CFS",    # 연결재무제표
                },
                timeout=15,
            )
            d = r.json()
            if d.get("status") == "000" and d.get("list"):
                results[bsns_year] = d["list"]
                print(f"  DART {bsns_year}년: {len(d['list'])}개 항목")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [DART 재무 오류] {bsns_year}: {e}")

    return results

def extract_value(items, account_name_keywords, sj_div_priority=("CFS", "IS", "BS", "CF")):
    """재무제표 항목에서 금액 추출 (억원)"""
    for kw in account_name_keywords:
        for sj in sj_div_priority:
            for item in items:
                if kw in item.get("account_nm", "") and item.get("sj_div") == sj:
                    raw = item.get("thstrm_amount", "0") or "0"
                    try:
                        return int(raw.replace(",", "").strip() or "0") / 1e8  # 원 → 억원 (마이너스 유지)
                    except:
                        pass
    return None

def parse_financials(dart_data):
    """DART 데이터 → 핵심 재무지표 딕셔너리 (억원 단위)"""
    parsed = {}
    for year, items in dart_data.items():
        revenue    = extract_value(items, ["매출액", "영업수익"])
        op_income  = extract_value(items, ["영업이익"])
        net_income = extract_value(items, ["당기순이익"])
        assets     = extract_value(items, ["자산총계"])
        equity     = extract_value(items, ["자본총계"])
        op_cf      = extract_value(items, ["영업활동으로 인한 현금흐름", "영업활동현금흐름"])
        capex      = extract_value(items, ["유형자산의 취득", "유형자산취득"])
        cash       = extract_value(items, ["현금및현금성자산"])
        debt       = extract_value(items, ["단기차입금"]) or 0
        long_debt  = extract_value(items, ["장기차입금", "사채"]) or 0

        parsed[year] = {
            "revenue":    revenue,
            "op_income":  op_income,
            "net_income": net_income,
            "assets":     assets,
            "equity":     equity,
            "op_cf":      op_cf,
            "capex":      abs(capex) if capex else None,
            "cash":       cash,
            "total_debt": (debt or 0) + (long_debt or 0),
            "fcf":        (op_cf - abs(capex)) if (op_cf and capex) else None,
            "op_margin":  (op_income / revenue * 100) if (revenue and op_income) else None,
            "net_margin": (net_income / revenue * 100) if (revenue and net_income) else None,
            "roe":        (net_income / equity * 100) if (equity and net_income) else None,
        }
    return parsed

# ── yfinance 현재 주가 ─────────────────────────────────────────────────────────
def get_price_data(ticker):
    """yfinance → 현재가 + 멀티플"""
    try:
        info = yf.Ticker(ticker).info
        price   = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        mktcap  = info.get("marketCap", 0)
        shares  = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding", 0)
        net_inc = info.get("netIncomeToCommon", 0)
        eps_cy  = info.get("epsCurrentYear", 0)
        eps_tr  = net_inc / shares if (net_inc and shares) else 0
        fwd_pe  = info.get("priceEpsCurrentYear") or info.get("forwardPE")
        pbr     = info.get("priceToBook")
        ev_eb   = info.get("enterpriseToEbitda")
        ev      = info.get("enterpriseValue", 0)
        ebitda  = info.get("ebitda", 0)
        op_cf   = info.get("operatingCashflow", 0)
        capex   = info.get("capitalExpenditures", 0)
        fcf     = op_cf + capex if capex else op_cf * 0.7
        debt    = info.get("totalDebt", 0)
        cash    = info.get("totalCash", 0)
        roe     = info.get("returnOnEquity", 0)
        op_mar  = info.get("operatingMargins", 0)
        rev     = info.get("totalRevenue", 0)
        rev_g   = info.get("revenueGrowth", 0)
        earn_g  = info.get("earningsGrowth", 0)
        trail_pe = price / eps_tr if eps_tr > 0 else None

        return {
            "price": price, "mktcap": mktcap, "shares": shares,
            "eps_tr": eps_tr, "eps_cy": eps_cy,
            "trail_pe": trail_pe, "fwd_pe": fwd_pe,
            "pbr": pbr, "ev_ebitda": ev_eb,
            "ev": ev, "ebitda": ebitda,
            "op_cf": op_cf, "fcf": fcf,
            "debt": debt, "cash": cash,
            "roe": roe, "op_margin": op_mar,
            "revenue": rev, "rev_growth": rev_g, "earn_growth": earn_g,
        }
    except Exception as e:
        print(f"  [yfinance 오류] {e}")
        return {}

# ── 리서치 리포트 검색 ────────────────────────────────────────────────────────
def find_reports(company_name, company_code=""):
    """manifest에서 해당 기업 리포트 검색 (최근 5개)"""
    if not MANIFEST.exists():
        return []
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except:
        return []

    matches = []
    name_kw = company_name.replace(" ", "")
    for key, v in data.items():
        cn   = (v.get("company") or "").replace(" ", "")
        code = v.get("company_code", "")
        title = v.get("title", "")
        if (company_code and code == company_code) or \
           (name_kw and name_kw in cn) or \
           (name_kw and name_kw in title):
            matches.append(v)

    # 날짜 최신순 정렬
    matches.sort(key=lambda x: x.get("date", ""), reverse=True)
    return matches[:5]

# ── DCF 계산 ─────────────────────────────────────────────────────────────────
def calc_dcf(fcf_base, shares, wacc, g5, gt, net_cash=0):
    """FCF 기반 DCF → 주당 가치 반환"""
    if not fcf_base or fcf_base <= 0 or not shares:
        return None
    pv, cf = 0, fcf_base
    for yr in range(1, 6):
        cf  *= (1 + g5)
        pv  += cf / (1 + wacc) ** yr
    tv    = cf * (1 + gt) / (wacc - gt)
    pv_tv = tv / (1 + wacc) ** 5
    equity = pv + pv_tv + net_cash
    return equity / shares

# ── 숫자 포맷 ─────────────────────────────────────────────────────────────────
def fmtv(v, is_krw=True):
    if v is None: return "N/A"
    if is_krw:
        if abs(v) >= 1e12: return f"{v/1e12:.1f}조원"
        if abs(v) >= 1e8:  return f"{v/1e8:.0f}억원"
        return f"{v:,.0f}원"
    else:
        if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6: return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"

def fmtp(v): return f"{v:.1f}%" if v is not None else "N/A"
def fmtx(v): return f"{v:.1f}배" if v is not None else "N/A"
def fmtprice(v, is_krw):
    if v is None: return "N/A"
    return f"{v:,.0f}원" if is_krw else f"${v:,.2f}"

# ── PDF 생성 ──────────────────────────────────────────────────────────────────
def build_pdf(company_name, ticker, price_data, dart_parsed, reports,
              wacc, g5, gt, is_krw):
    fn, fnb = setup_font()
    def S(nm, **kw):  return ParagraphStyle(nm, fontName=fn,  **kw)
    def SB(nm, **kw): return ParagraphStyle(nm, fontName=fnb, **kw)
    ST = {
        "title":  SB("ti", fontSize=20, leading=26, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":    S ("su", fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":     SB("h2", fontSize=12, leading=17, spaceBefore=12,spaceAfter=5, textColor=colors.HexColor("#1a3a5c")),
        "h3":     SB("h3", fontSize=9,  leading=14, spaceBefore=5, spaceAfter=2, textColor=colors.HexColor("#c0392b")),
        "body":   S ("bo", fontSize=8.5,leading=14, spaceAfter=3,  textColor=colors.HexColor("#222")),
        "bullet": S ("bl", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#333"), leftIndent=12),
        "note":   S ("no", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
        "red":    SB("re", fontSize=10, leading=14, textColor=colors.HexColor("#c62828")),
        "blue":   SB("bl2",fontSize=10, leading=14, textColor=colors.HexColor("#1a6fb5")),
        "green":  SB("gr", fontSize=10, leading=14, textColor=colors.HexColor("#2e7d32")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm,  bottomMargin=1.8*cm)
    story = []
    W = doc.width
    now_str = datetime.now().strftime("%Y.%m.%d %H:%M")

    # ── 커버 ──
    story.append(Paragraph(f"{company_name} 기업 종합 분석", ST["title"]))
    story.append(Paragraph(f"{ticker}  ·  {now_str}  ·  DART 재무제표 + Naver 리서치 + yfinance", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2.5, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # ── 현재 주가 & 멀티플 ──
    story.append(Paragraph("📈 현재 주가 & 밸류에이션", ST["h2"]))
    price = price_data.get("price", 0)
    mktcap = price_data.get("mktcap", 0)

    price_rows = [
        ["현재가",     fmtprice(price, is_krw),           "시가총액",  fmtv(mktcap, is_krw)],
        ["Trail PER",  fmtx(price_data.get("trail_pe")),  "선행 PER",  fmtx(price_data.get("fwd_pe"))],
        ["PBR",        fmtx(price_data.get("pbr")),       "EV/EBITDA", fmtx(price_data.get("ev_ebitda"))],
        ["매출성장",   fmtp(price_data.get("rev_growth")*100 if price_data.get("rev_growth") else None),
                                                           "이익성장",  fmtp(price_data.get("earn_growth")*100 if price_data.get("earn_growth") else None)],
        ["영업이익률", fmtp(price_data.get("op_margin")*100 if price_data.get("op_margin") else None),
                                                           "ROE",       fmtp(price_data.get("roe")*100 if price_data.get("roe") else None)],
    ]
    pt = _make_table(price_rows, W, fn, fnb)
    story.append(pt)
    story.append(Spacer(1, 0.3*cm))

    # ── DART 재무제표 ──
    if dart_parsed:
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3a5c")))
        story.append(Paragraph("📊 DART 재무제표 (연결기준, 억원)", ST["h2"]))

        years = sorted(dart_parsed.keys(), reverse=True)
        hdr   = ["항목"] + [f"{y}년" for y in years]
        items_def = [
            ("매출액",       "revenue"),
            ("영업이익",     "op_income"),
            ("영업이익률",   "op_margin"),
            ("순이익",       "net_income"),
            ("순이익률",     "net_margin"),
            ("ROE",          "roe"),
            ("FCF",          "fcf"),
            ("영업CF",       "op_cf"),
            ("CAPEX",        "capex"),
            ("현금",         "cash"),
            ("총부채",       "total_debt"),
            ("자본총계",     "equity"),
        ]
        fin_rows = [hdr]
        for label, key in items_def:
            row = [label]
            for y in years:
                v = dart_parsed[y].get(key)
                if key in ("op_margin", "net_margin", "roe"):
                    row.append(fmtp(v))
                else:
                    row.append(fmtv(v, is_krw) if v else "N/A")
            fin_rows.append(row)

        cw = [W * 0.20] + [W * 0.80 / len(years)] * len(years)
        ft = Table(fin_rows, colWidths=cw, repeatRows=1)
        ft.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
            ("FONTNAME",      (0,0), (-1,0),  fnb),
            ("FONTNAME",      (0,1), (0,-1),  fnb),
            ("FONTNAME",      (1,1), (-1,-1), fn),
            ("FONTSIZE",      (0,0), (-1,-1), 7.5),
            ("ALIGN",         (1,0), (-1,-1), "RIGHT"),
            ("ALIGN",         (0,0), (0,-1),  "LEFT"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#f0f4f8"), colors.white]),
            ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#ccc")),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ]))
        story.append(ft)
        story.append(Spacer(1, 0.3*cm))

    # ── DCF 분석 ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3a5c")))
    story.append(Paragraph("💰 DCF 내재가치 분석", ST["h2"]))

    # FCF 소스: DART 우선, 없으면 yfinance
    fcf_base  = None
    fcf_src   = ""
    shares    = price_data.get("shares", 0)
    net_cash_yf = (price_data.get("cash", 0) or 0) - (price_data.get("debt", 0) or 0)

    if dart_parsed:
        latest_year = max(dart_parsed.keys())
        dart_fcf = dart_parsed[latest_year].get("fcf")
        if dart_fcf and dart_fcf > 0:
            fcf_base = dart_fcf * 1e8  # 억원 → 원
            fcf_src  = f"DART {latest_year}년 FCF"

    if not fcf_base:
        yf_fcf = price_data.get("fcf", 0)
        if yf_fcf and yf_fcf > 0:
            fcf_base = yf_fcf
            fcf_src  = "yfinance FCF (TTM)"

    if fcf_base and shares:
        dcf_base = calc_dcf(fcf_base, shares, wacc, g5,     gt, net_cash_yf)
        dcf_bull = calc_dcf(fcf_base, shares, wacc, g5+0.1, gt, net_cash_yf)
        dcf_bear = calc_dcf(fcf_base, shares, wacc, g5-0.1, gt, net_cash_yf)

        def arrow_str(dcf_val):
            if not dcf_val or not price: return ""
            diff = (dcf_val / price - 1) * 100
            return f"{'▲' if diff>0 else '▼'}{abs(diff):.1f}%"

        dcf_rows = [
            ["시나리오",      "FCF 성장(5년)", "목표가",                          "현재가 대비"],
            ["낙관 (Bull)",   f"{(g5+0.1)*100:.0f}%",  fmtprice(dcf_bull, is_krw), arrow_str(dcf_bull)],
            ["기본 (Base)",   f"{g5*100:.0f}%",         fmtprice(dcf_base, is_krw), arrow_str(dcf_base)],
            ["보수적 (Bear)", f"{max(g5-0.1,0)*100:.0f}%", fmtprice(dcf_bear, is_krw), arrow_str(dcf_bear)],
        ]
        dt = Table(dcf_rows, colWidths=[W*0.22, W*0.18, W*0.30, W*0.20], repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#2c5282")),
            ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
            ("FONTNAME",      (0,0), (-1,0),  fnb),
            ("FONTNAME",      (0,1), (-1,-1), fn),
            ("FONTSIZE",      (0,0), (-1,-1), 8),
            ("ALIGN",         (1,0), (-1,-1), "CENTER"),
            ("ALIGN",         (0,0), (0,-1),  "LEFT"),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.HexColor("#EBF5FB"), colors.white]),
            ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#aaa")),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            # 기본 시나리오 강조
            ("BACKGROUND",    (0,2), (-1,2),  colors.HexColor("#D6EAF8")),
            ("FONTNAME",      (0,2), (-1,2),  fnb),
        ]))
        story.append(dt)
        story.append(Spacer(1, 0.1*cm))
        story.append(Paragraph(
            f"FCF 출처: {fcf_src}  |  WACC {wacc*100:.0f}%  |  터미널 성장 {gt*100:.1f}%",
            ST["note"]
        ))
    else:
        story.append(Paragraph("FCF 데이터 부족 — DCF 산출 불가", ST["body"]))

    story.append(Spacer(1, 0.3*cm))

    # ── 리서치 리포트 목록 ──
    if reports:
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3a5c")))
        story.append(Paragraph(f"📋 Naver 리서치 리포트 (최근 {len(reports)}건)", ST["h2"]))

        for rep in reports:
            title   = rep.get("title", "")[:70]
            firm    = rep.get("firm",  "")
            date    = rep.get("date",  "")
            pages   = rep.get("page_count", "")
            pdf_url = rep.get("pdf_url", "")
            path    = rep.get("path", "")

            story.append(Spacer(1, 0.1*cm))
            if pdf_url:
                story.append(Paragraph(
                    f'<a href="{pdf_url}" color="#1a6fb5"><u>▶ {title}</u></a>',
                    ST["h3"]
                ))
            else:
                story.append(Paragraph(f"▶ {title}", ST["h3"]))

            meta = f"{firm}  |  {date}"
            if pages:
                meta += f"  |  {pages}p"
            story.append(Paragraph(meta, ST["note"]))
            if path:
                story.append(Paragraph(f"저장경로: {path}", ST["note"]))
            story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ddd")))

    # ── 주석 ──
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "※ DART 재무제표(연결기준), yfinance 실시간 데이터 기반 자동 생성 리포트. "
        "DCF는 FCF 기반 5개년 할인모형. 투자 권유 아님.",
        ST["note"]
    ))

    doc.build(story)
    buf.seek(0)
    return buf

def _make_table(rows, W, fn, fnb):
    t = Table(rows, colWidths=[W*0.15, W*0.22, W*0.15, W*0.22])
    t.setStyle(TableStyle([
        ("FONTNAME",      (0,0), (-1,-1), fn),
        ("FONTNAME",      (0,0), (0,-1),  fnb),
        ("FONTNAME",      (2,0), (2,-1),  fnb),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("TEXTCOLOR",     (0,0), (0,-1),  colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",     (2,0), (2,-1),  colors.HexColor("#1a3a5c")),
        ("ALIGN",         (1,0), (1,-1),  "RIGHT"),
        ("ALIGN",         (3,0), (3,-1),  "RIGHT"),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#ddd")),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [colors.HexColor("#f8f9fa"), colors.white]),
    ]))
    return t

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("사용법: python company_analysis.py <종목명 또는 코드>")
        print("  예)  python company_analysis.py 삼성전자")
        print("       python company_analysis.py 005930")
        print("       python company_analysis.py TSLA")
        sys.exit(1)

    query = sys.argv[1].strip()
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 종목 판별
    is_us    = not re.match(r"^\d{6}$", query) and re.match(r"^[A-Z]{1,5}$", query.upper())
    is_code  = re.match(r"^\d{6}$", query)
    is_krw   = not is_us

    stock_code  = query if is_code else ""
    ticker      = query.upper() if is_us else (f"{query}.KS" if not is_code else f"{query}.KS")
    company_name = query

    print(f"\n=== {query} 기업 분석 시작 ===")

    # ── 1) DART corp_code 조회 ──
    corp_code = None
    dart_corp_name = None
    if is_krw and stock_code and DART_KEY:
        print("  DART 종목 조회 중...")
        corp_code, dart_corp_name = dart_get_corp_code(stock_code)
        if dart_corp_name:
            company_name = dart_corp_name
            print(f"  → {company_name} (corp_code: {corp_code})")

    # ── 2) DART 재무제표 ──
    dart_raw    = {}
    dart_parsed = {}
    if corp_code:
        print("  DART 재무제표 수집 중...")
        dart_raw    = dart_get_financials(corp_code)
        dart_parsed = parse_financials(dart_raw)

    # ── 3) yfinance 현재가 ──
    print(f"  yfinance 데이터 수집 중... ({ticker})")
    price_data = get_price_data(ticker)
    if price_data.get("price"):
        cur = "원" if is_krw else "$"
        print(f"  → 현재가: {price_data['price']:,.0f}{cur}")

    # ── 4) 리서치 리포트 검색 ──
    print("  리서치 리포트 검색 중...")
    reports = find_reports(company_name, stock_code)
    print(f"  → {len(reports)}개 리포트 발견")

    # ── 5) DCF 파라미터 ──
    # yfinance 성장률 기반 자동 설정
    earn_g = abs(price_data.get("earn_growth") or 0)
    if earn_g > 0.5:   g5 = 0.25
    elif earn_g > 0.2: g5 = 0.15
    elif earn_g > 0:   g5 = 0.10
    else:              g5 = 0.07
    wacc = 0.10 if is_krw else 0.11
    gt   = 0.025 if is_krw else 0.03

    # ── 6) PDF 생성 ──
    print("  PDF 생성 중...")
    buf = build_pdf(
        company_name, ticker,
        price_data, dart_parsed, reports,
        wacc, g5, gt, is_krw
    )

    # ── 7) 저장 ──
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", company_name)
    filename  = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    out_path  = OUTPUT_DIR / filename
    out_path.write_bytes(buf.read())
    print(f"\n✅ 저장 완료: {out_path}")

if __name__ == "__main__":
    main()
