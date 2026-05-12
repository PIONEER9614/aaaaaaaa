"""
6-Agent 주식 분석 하네스
사용: python stock_agent_harness.py 삼성전자
      python stock_agent_harness.py 005930
      python stock_agent_harness.py TSLA

에이전트 & 데이터 소스:
  재무분석가     ← DART 재무제표(KR) / SEC XBRL(US) + yfinance
  리서치분석가   ← 네이버 리서치 리포트(KR) / SEC 10-K MD&A(US)
  뉴스감성분석가 ← 네이버 뉴스
  밸리인사이트   ← Valley AI 프리미엄 포스트
  업종리서처     ← Valley AI 산업 섹션 + yfinance 섹터
  투자전략가     ← 위 5개 종합 → 최종 판단
"""

import os, io, re, sys, json, time, requests, zipfile
import xml.etree.ElementTree as ET
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from groq import Groq

from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
DART_KEY       = os.getenv("DART_API_KEY", "")
TG_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT        = os.getenv("TELEGRAM_CHAT_ID", "")
VALLEY_EMAIL   = os.getenv("VALLEY_EMAIL", "")
VALLEY_PASS    = os.getenv("VALLEY_PASSWORD", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
NAVER_MANIFEST = Path("data/naver_research/_meta/manifest.json")
HEADERS        = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

client = Groq(api_key=GROQ_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# 에이전트 프롬프트
# ─────────────────────────────────────────────────────────────────────────────
PROMPTS = {
    "재무분석가": """당신은 전문 재무 분석가입니다. 제공된 재무 데이터를 분석하세요.

분석 항목:
1. 최근 3년 매출 추이 및 성장률
2. 영업이익률 (업종 평균 대비)
3. 순이익률
4. PER / PBR 밸류에이션
5. ROE (자본 효율성)
6. 부채비율 (200% 기준)
7. 유동비율 (100% 기준)

각 지표에 수치와 한 줄 해석. 마지막에 재무 건전성 A/B/C/D 등급 + 리스크 요인.
한국어로 작성.""",

    "리서치분석가": """당신은 증권사 리서치 전문가입니다. 제공된 리서치 리포트 또는 10-K 내용을 분석하세요.

분석 항목:
1. 리포트/문서의 핵심 투자 포인트 (3가지)
2. 목표주가 및 투자 의견 (있을 경우)
3. 주요 리스크 요인
4. 애널리스트/문서가 강조하는 성장 동력

데이터가 없으면 "리서치 데이터 없음"으로 명시.
한국어로 작성.""",

    "뉴스감성분석가": """당신은 주식 시장 뉴스 감성 분석 전문가입니다.

분석 항목:
1. 각 뉴스를 호재/악재/중립으로 분류 + 한 줄 요약 + [긍정]/[부정]/[중립] 태그
2. 호재 건수, 악재 건수, 중립 건수
3. 최종 시장 심리: 긍정/중립/부정

한국어로 작성.""",

    "밸리인사이트": """당신은 Valley AI 프리미엄 콘텐츠 분석가입니다. 제공된 Valley AI 포스트를 분석하세요.

분석 항목:
1. 해당 종목/업종과 관련된 핵심 인사이트 (최대 5개)
2. Valley AI 전문가들의 주요 시각 (긍정적/부정적 포인트)
3. 최근 Valley AI 포스트가 시사하는 투자 방향

포스트가 없으면 "관련 Valley AI 콘텐츠 없음"으로 명시.
한국어로 작성.""",

    "업종리서처": """당신은 산업 및 업종 리서치 전문가입니다.

분석 항목:
1. 글로벌 시장 흐름 (현재 트렌드, 성장률)
2. 주요 경쟁사 동향 및 비교
3. 관련 정책·규제 변화
4. 업종 전망: 긍정/중립/부정 + 근거 3줄 이내

한국어로 작성.""",

    "투자전략가": """당신은 공격적 성향의 투자 전략가입니다. 5명의 분석가 결과를 종합하여 최종 투자 판단을 내리세요.

성향: 공격적 (리스크를 감수하더라도 수익 극대화)

최종 판정 (5단계 중 하나):
- 적극 매수 / 분할 매수 / 관망 / 비중 축소 / 매도

필수 포함:
1. 최종 투자 판정
2. 목표 수익률 (%)
3. 손절 라인 (현재가 대비 %)
4. 진입 타이밍
5. 각 분석가 견해 인용하며 근거 설명 (재무·리서치·뉴스·밸리·업종 모두 언급)

한국어로 작성.""",
}

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
# 데이터 수집 — DART (한국 재무제표)
# ─────────────────────────────────────────────────────────────────────────────
def dart_corp_code(stock_code):
    if not DART_KEY: return None, None
    try:
        r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                         params={"crtfc_key": DART_KEY}, timeout=30)
        tree = ET.fromstring(zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml"))
        for item in tree.findall("list"):
            if item.findtext("stock_code","").strip() == stock_code:
                return item.findtext("corp_code","").strip(), item.findtext("corp_name","").strip()
    except Exception as e:
        print(f"  [DART corp] {e}")
    return None, None

def dart_financials(corp_code):
    if not DART_KEY or not corp_code: return {}
    year = datetime.now().year - 1
    out  = {}
    for y in [year, year-1, year-2]:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(y), "reprt_code": "11014", "fs_div": "CFS"},
                timeout=15)
            d = r.json()
            if d.get("status") == "000" and d.get("list"):
                out[y] = d["list"]
            time.sleep(0.3)
        except: pass
    return out

def _val(items, kws):
    for kw in kws:
        for item in items:
            if kw in item.get("account_nm",""):
                raw = item.get("thstrm_amount","0") or "0"
                try: return int(raw.replace(",","").replace("-","0") or "0") / 1e8
                except: pass
    return None

def parse_dart(data):
    out = {}
    for y, items in data.items():
        rev  = _val(items, ["매출액","영업수익"])
        op   = _val(items, ["영업이익"])
        net  = _val(items, ["당기순이익"])
        eq   = _val(items, ["자본총계"])
        ca   = _val(items, ["유동자산"])
        cl   = _val(items, ["유동부채"])
        tl   = _val(items, ["부채총계"])
        out[y] = {
            "revenue": rev, "op_income": op, "net_income": net, "equity": eq,
            "op_margin":    round(op/rev*100,1)  if rev and op  else None,
            "net_margin":   round(net/rev*100,1) if rev and net else None,
            "roe":          round(net/eq*100,1)  if eq and net  else None,
            "debt_ratio":   round(tl/eq*100,1)   if eq and tl  else None,
            "current_ratio":round(ca/cl*100,1)   if ca and cl  else None,
        }
    return out

def format_dart(parsed):
    if not parsed: return ""
    lines = ["[DART 재무제표 — 3개년]"]
    for y in sorted(parsed.keys(), reverse=True):
        d = parsed[y]
        lines.append(f"  {y}년: 매출 {d.get('revenue','N/A')}억 | 영업이익 {d.get('op_income','N/A')}억 | 순이익 {d.get('net_income','N/A')}억")
        lines.append(f"       영업이익률 {d.get('op_margin','N/A')}% | 순이익률 {d.get('net_margin','N/A')}% | ROE {d.get('roe','N/A')}%")
        lines.append(f"       부채비율 {d.get('debt_ratio','N/A')}% | 유동비율 {d.get('current_ratio','N/A')}%")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 — yfinance
# ─────────────────────────────────────────────────────────────────────────────
def yf_data(ticker):
    try:
        info = yf.Ticker(ticker).info
        return {
            "price":     info.get("currentPrice") or info.get("regularMarketPrice"),
            "per":       info.get("trailingPE") or info.get("forwardPE"),
            "pbr":       info.get("priceToBook"),
            "roe":       round(info.get("returnOnEquity",0)*100,1) if info.get("returnOnEquity") else None,
            "op_margin": round(info.get("operatingMargins",0)*100,1) if info.get("operatingMargins") else None,
            "rev_growth":round(info.get("revenueGrowth",0)*100,1)   if info.get("revenueGrowth")    else None,
            "mktcap":    info.get("marketCap"),
            "sector":    info.get("sector",""),
            "industry":  info.get("industry",""),
            "name":      info.get("shortName") or info.get("longName",""),
            "currency":  info.get("currency",""),
        }
    except Exception as e:
        print(f"  [yfinance] {e}")
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 — SEC EDGAR 10-K (미국 주식)
# ─────────────────────────────────────────────────────────────────────────────
def sec_get_cik(ticker):
    """티커 → CIK 번호"""
    try:
        r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar",
            params={"action":"getcompany","CIK":ticker,"type":"10-K",
                    "dateb":"","owner":"include","count":"1","output":"atom"},
            headers={"User-Agent": f"PaperBot/1.0 {VALLEY_EMAIL}"}, timeout=15)
        m = re.search(r"CIK=(\d+)", r.text)
        return m.group(1) if m else None
    except: return None

def sec_get_financials(cik):
    """SEC XBRL API → 주요 재무지표"""
    if not cik: return {}
    try:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
        r   = requests.get(url, headers={"User-Agent": f"PaperBot/1.0 {VALLEY_EMAIL}"}, timeout=20)
        if not r.ok: return {}
        facts = r.json().get("facts", {}).get("us-gaap", {})

        def latest(concept):
            data = facts.get(concept, {}).get("units", {})
            for unit_vals in data.values():
                annual = [v for v in unit_vals if v.get("form") == "10-K"]
                if annual:
                    annual.sort(key=lambda x: x.get("end",""), reverse=True)
                    return annual[0].get("val")
            return None

        rev     = latest("Revenues") or latest("RevenueFromContractWithCustomerExcludingAssessedTax")
        op_inc  = latest("OperatingIncomeLoss")
        net_inc = latest("NetIncomeLoss")
        assets  = latest("Assets")
        equity  = latest("StockholdersEquity")
        return {
            "revenue": rev, "op_income": op_inc, "net_income": net_inc,
            "assets": assets, "equity": equity,
            "op_margin":  round(op_inc/rev*100,1)  if rev and op_inc  else None,
            "net_margin": round(net_inc/rev*100,1)  if rev and net_inc else None,
            "roe":        round(net_inc/equity*100,1) if equity and net_inc else None,
        }
    except Exception as e:
        print(f"  [SEC XBRL] {e}")
        return {}

def sec_get_10k_text(cik):
    """SEC EDGAR → 최신 10-K 요약 텍스트 (Item 1A Risk Factors + Item 7 MD&A 앞부분)"""
    if not cik: return ""
    hdrs = {"User-Agent": f"PaperBot/1.0 {VALLEY_EMAIL}"}
    try:
        # 최신 10-K 파일 목록
        sub = requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
                           headers=hdrs, timeout=15).json()
        filings = sub.get("filings", {}).get("recent", {})
        forms   = filings.get("form", [])
        acc_nos = filings.get("accessionNumber", [])
        dates   = filings.get("filingDate", [])
        idx = next((i for i, f in enumerate(forms) if f == "10-K"), None)
        if idx is None: return ""
        acc = acc_nos[idx].replace("-","")
        date = dates[idx]
        print(f"  [SEC 10-K] {date} 파일 발견")

        # 인덱스 파일
        ix_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{acc_nos[idx]}-index.htm"
        ix_r = requests.get(ix_url, headers=hdrs, timeout=15)
        # 10-K 본문 링크 찾기
        soup = BeautifulSoup(ix_r.text, "html.parser")
        doc_link = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".htm") and "10-k" in href.lower():
                doc_link = "https://www.sec.gov" + href
                break
        if not doc_link:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.endswith(".htm") and acc in href:
                    doc_link = "https://www.sec.gov" + href
                    break
        if not doc_link: return f"[10-K 접수일: {date} — 본문 링크 파싱 실패]"

        # 본문 텍스트 (앞 50KB만)
        doc_r = requests.get(doc_link, headers=hdrs, timeout=20)
        text  = BeautifulSoup(doc_r.text[:60000], "html.parser").get_text(separator=" ")
        text  = re.sub(r'\s+', ' ', text).strip()
        return f"[10-K 제출일: {date}]\n{text[:3000]}"
    except Exception as e:
        print(f"  [SEC 10-K 텍스트] {e}")
        return ""

def format_sec(fin, text):
    if not fin and not text: return ""
    lines = ["[SEC 재무지표 (최신 10-K)]"]
    if fin:
        def fmt(v): return f"${v/1e9:.1f}B" if v and abs(v) >= 1e9 else (f"${v/1e6:.0f}M" if v else "N/A")
        lines.append(f"  매출: {fmt(fin.get('revenue'))}")
        lines.append(f"  영업이익: {fmt(fin.get('op_income'))}  (이익률 {fin.get('op_margin','N/A')}%)")
        lines.append(f"  순이익: {fmt(fin.get('net_income'))}  (이익률 {fin.get('net_margin','N/A')}%)")
        lines.append(f"  ROE: {fin.get('roe','N/A')}%")
    if text:
        lines.append("\n[10-K 본문 요약]")
        lines.append(text[:1500])
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 — 네이버 리서치 리포트
# ─────────────────────────────────────────────────────────────────────────────
def naver_reports(company_name, company_code=""):
    if not NAVER_MANIFEST.exists(): return []
    try:
        data = json.loads(NAVER_MANIFEST.read_text(encoding="utf-8"))
    except: return []
    kw = company_name.replace(" ","")
    matches = []
    for v in data.values():
        cn   = (v.get("company") or "").replace(" ","")
        code = v.get("company_code","")
        if (company_code and code == company_code) or (kw and kw in cn):
            matches.append(v)
    matches.sort(key=lambda x: x.get("date",""), reverse=True)
    return matches[:5]

def format_reports(reports):
    if not reports: return "네이버 리서치 리포트 없음"
    lines = [f"[네이버 리서치 리포트 — 최근 {len(reports)}건]"]
    for r in reports:
        lines.append(f"  [{r.get('date','')}] {r.get('firm','')} | {r.get('title','')}")
        if r.get("target_price"):
            lines.append(f"    목표주가: {r['target_price']}  의견: {r.get('opinion','')}")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 — Valley AI
# ─────────────────────────────────────────────────────────────────────────────
_valley_session = None

def valley_login():
    global _valley_session
    if _valley_session: return _valley_session
    if not VALLEY_EMAIL or not VALLEY_PASS: return None
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        r = s.post("https://api.valley.town/auth/sign-in",
                   json={"email": VALLEY_EMAIL, "password": VALLEY_PASS, "type": "session"},
                   headers={**HEADERS, "Content-Type":"application/json",
                            "Origin":"https://www.valley.town"},
                   timeout=20)
        if r.status_code in (200, 201):
            _valley_session = s
            print("  [Valley AI] 로그인 성공")
        else:
            print(f"  [Valley AI] 로그인 실패 {r.status_code}")
    except Exception as e:
        print(f"  [Valley AI] {e}")
    return _valley_session

def valley_fetch_posts(max_posts=20):
    """산업과 기업 섹션 포스트 목록"""
    s = valley_login()
    if not s: return []
    try:
        r = s.get("https://www.valley.town/wsaj-premium/industry-company",
                  timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        posts = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if re.match(r"^/wsaj-premium/industry-company/[a-f0-9]{10,}", href):
                title = a.get_text(strip=True)[:80]
                if title and {"href": href, "title": title} not in posts:
                    posts.append({"url": "https://www.valley.town" + href, "title": title})
                if len(posts) >= max_posts:
                    break
        return posts
    except Exception as e:
        print(f"  [Valley 포스트] {e}")
        return []

def valley_search_related(posts, query):
    """포스트 목록에서 query와 관련된 것 필터링"""
    keywords = re.findall(r'\w+', query.lower())
    related  = []
    for p in posts:
        title_lower = p["title"].lower()
        if any(kw in title_lower for kw in keywords):
            related.append(p)
    # 관련 없으면 최신 5개
    return related[:5] if related else posts[:5]

def valley_get_post_content(url):
    """포스트 본문 텍스트 (앞 2000자)"""
    s = valley_login()
    if not s: return ""
    try:
        r    = s.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        # 본문 영역
        for sel in ["article", ".post-content", "main", ".content"]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator="\n", strip=True)[:2000]
        return soup.get_text(separator="\n", strip=True)[:2000]
    except: return ""

def format_valley(posts, company_name):
    if not posts: return "관련 Valley AI 콘텐츠 없음"
    lines = [f"[Valley AI 프리미엄 포스트 — '{company_name}' 관련 {len(posts)}건]"]
    for p in posts:
        lines.append(f"\n  📄 {p['title']}")
        if p.get("content"):
            lines.append(f"  {p['content'][:400]}")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 — 네이버 뉴스
# ─────────────────────────────────────────────────────────────────────────────
def naver_news(query, days=30, max_items=15):
    items = []
    try:
        url = f"https://search.naver.com/search.naver?where=news&query={requests.utils.quote(query)}&sort=1&pd=4"
        r   = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".news_area")[:max_items]:
            title_el = item.select_one(".news_tit")
            desc_el  = item.select_one(".dsc_wrap") or item.select_one(".api_txt_lines")
            time_el  = item.select_one(".info_group .info")
            title = title_el.get_text(strip=True) if title_el else ""
            desc  = desc_el.get_text(strip=True)[:100]  if desc_el  else ""
            date  = time_el.get_text(strip=True)         if time_el  else ""
            if title:
                items.append({"title": title, "desc": desc, "date": date})
    except Exception as e:
        print(f"  [뉴스] {e}")
    return items

def format_news(items, company_name):
    if not items: return f"{company_name} 관련 뉴스 없음"
    lines = [f"[네이버 뉴스 — 최근 30일 {len(items)}건]"]
    for i, n in enumerate(items, 1):
        lines.append(f"  {i}. [{n['date']}] {n['title']}")
        if n['desc']:
            lines.append(f"     {n['desc']}")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 종목 식별
# ─────────────────────────────────────────────────────────────────────────────
NAME_TO_CODE = {
    "삼성전자":"005930","sk하이닉스":"000660","lg에너지솔루션":"373220",
    "현대차":"005380","카카오":"035720","네이버":"035420","셀트리온":"068270",
    "posco홀딩스":"005490","kb금융":"105560","신한지주":"055550",
    "하이브":"352820","크래프톤":"259960","에코프로비엠":"247540",
    "lg화학":"051910",
}

def resolve_stock(query):
    q = query.strip()
    if re.match(r"^[A-Za-z]{1,5}$", q):                        # 미국 주식
        info = yf_data(q.upper())
        return {"name": info.get("name",q.upper()), "stock_code": None,
                "yf_ticker": q.upper(), "is_us": True,
                "sector": info.get("sector",""), "industry": info.get("industry","")}
    if re.match(r"^\d{6}$", q):                                  # 6자리 코드
        corp_code, corp_name = dart_corp_code(q)
        info = yf_data(f"{q}.KS")
        return {"name": corp_name or info.get("name",q), "stock_code": q,
                "yf_ticker": f"{q}.KS", "is_us": False, "corp_code": corp_code,
                "sector": info.get("sector",""), "industry": info.get("industry","")}
    code = NAME_TO_CODE.get(q.lower())
    if not code and DART_KEY:                                    # 이름으로 DART 검색
        try:
            r    = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                                params={"crtfc_key": DART_KEY}, timeout=30)
            tree = ET.fromstring(zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml"))
            for item in tree.findall("list"):
                if q in item.findtext("corp_name",""):
                    code = item.findtext("stock_code","").strip()
                    if code: break
        except: pass
    if code:
        corp_code, corp_name = dart_corp_code(code)
        info = yf_data(f"{code}.KS")
        return {"name": corp_name or q, "stock_code": code,
                "yf_ticker": f"{code}.KS", "is_us": False, "corp_code": corp_code,
                "sector": info.get("sector",""), "industry": info.get("industry","")}
    return {"name": q, "stock_code": None, "yf_ticker": None,
            "is_us": False, "sector": "", "industry": ""}

# ─────────────────────────────────────────────────────────────────────────────
# LLM 실행
# ─────────────────────────────────────────────────────────────────────────────
def run_agent(agent_name, user_content):
    print(f"  [{agent_name}] 분석 중...")
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role":"system","content": PROMPTS[agent_name]},
                    {"role":"user",  "content": user_content},
                ],
                temperature=0.3, max_tokens=2048,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"    오류 (시도 {attempt+1}): {e}")
            time.sleep(2)
    return f"[{agent_name}] 분석 실패"

# ─────────────────────────────────────────────────────────────────────────────
# 메인 분석 파이프라인
# ─────────────────────────────────────────────────────────────────────────────
def analyze(stock_query):
    print(f"\n{'='*62}")
    print(f"  6-Agent 주식 분석: {stock_query}")
    print(f"{'='*62}\n")

    stock = resolve_stock(stock_query)
    name  = stock["name"]
    is_us = stock["is_us"]
    print(f"  종목: {name}  |  {'미국' if is_us else '한국'}  |  {stock.get('stock_code') or stock.get('yf_ticker','')}\n")

    # ── 데이터 수집 ──
    print("[데이터 수집]")

    # yfinance (공통)
    yf = yf_data(stock["yf_ticker"]) if stock.get("yf_ticker") else {}
    yf_text = (
        f"현재가: {yf.get('price','N/A')} {yf.get('currency','')}\n"
        f"PER: {yf.get('per','N/A')}  PBR: {yf.get('pbr','N/A')}  ROE: {yf.get('roe','N/A')}%\n"
        f"영업이익률: {yf.get('op_margin','N/A')}%  매출성장률: {yf.get('rev_growth','N/A')}%\n"
        f"섹터: {yf.get('sector','')}  업종: {yf.get('industry','')}"
    )

    # 재무 데이터
    if is_us:
        print("  SEC 10-K 수집...")
        cik        = sec_get_cik(stock["yf_ticker"])
        sec_fin    = sec_get_financials(cik)
        sec_text   = sec_get_10k_text(cik)
        fin_text   = f"종목: {name}\n{yf_text}\n\n{format_sec(sec_fin, sec_text)}"
    else:
        print("  DART 재무제표 수집...")
        dart_raw   = dart_financials(stock.get("corp_code"))
        dart_parsed = parse_dart(dart_raw)
        fin_text   = f"종목: {name}\n{yf_text}\n\n{format_dart(dart_parsed)}"

    # 리서치 리포트 / 10-K
    if is_us:
        research_text = f"종목: {name}\n\n{format_sec({}, sec_text)}" if 'sec_text' in dir() else f"종목: {name}\n미국 주식 — SEC 10-K 텍스트 참조"
    else:
        print("  네이버 리서치 리포트 수집...")
        reports      = naver_reports(name, stock.get("stock_code",""))
        research_text = f"종목: {name}\n\n{format_reports(reports)}"

    # 뉴스
    print("  뉴스 수집...")
    news_items = naver_news(name)
    news_text  = f"종목: {name}\n\n{format_news(news_items, name)}"

    # Valley AI
    print("  Valley AI 포스트 수집...")
    all_posts  = valley_fetch_posts(max_posts=30)
    rel_posts  = valley_search_related(all_posts, f"{name} {stock.get('sector','')} {stock.get('industry','')}")
    for p in rel_posts[:3]:                  # 관련 포스트 본문 가져오기
        p["content"] = valley_get_post_content(p["url"])
        time.sleep(0.3)
    valley_text = f"종목: {name}\n\n{format_valley(rel_posts, name)}"

    # 업종
    industry_text = (
        f"종목: {name}\n섹터: {yf.get('sector','')}\n업종: {yf.get('industry','')}\n\n"
        f"[Valley AI 최신 산업 포스트 제목 목록]\n"
        + "\n".join(f"  - {p['title']}" for p in all_posts[:10])
    )

    # ── 에이전트 순차 실행 ──
    print("\n[에이전트 분석]")
    r_fin     = run_agent("재무분석가",     fin_text)
    r_research= run_agent("리서치분석가",   research_text)
    r_news    = run_agent("뉴스감성분석가", news_text)
    r_valley  = run_agent("밸리인사이트",   valley_text)
    r_industry= run_agent("업종리서처",     industry_text)

    strat_input = f"""종목명: {name}
현재가: {yf.get('price','N/A')}  PER: {yf.get('per','N/A')}  PBR: {yf.get('pbr','N/A')}

=== 재무분석가 ===\n{r_fin}
=== 리서치분석가 ===\n{r_research}
=== 뉴스감성분석가 ===\n{r_news}
=== 밸리인사이트 ===\n{r_valley}
=== 업종리서처 ===\n{r_industry}"""

    r_strat = run_agent("투자전략가", strat_input)

    return {
        "name": name, "stock": stock, "yf": yf,
        "fin": r_fin, "research": r_research, "news": r_news,
        "valley": r_valley, "industry": r_industry, "strategy": r_strat,
        "timestamp": datetime.now().strftime("%Y.%m.%d %H:%M"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# PDF 생성
# ─────────────────────────────────────────────────────────────────────────────
def build_pdf(result):
    fn, fnb = setup_font()
    ST = {
        "cover": ParagraphStyle("cv", fontName=fnb, fontSize=18, leading=26, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":   ParagraphStyle("sb", fontName=fn,  fontSize=9,  leading=14, spaceAfter=12, textColor=colors.HexColor("#666")),
        "head":  ParagraphStyle("hd", fontName=fnb, fontSize=12, leading=18, spaceBefore=12,spaceAfter=4, textColor=colors.HexColor("#1a3a5c")),
        "body":  ParagraphStyle("bo", fontName=fn,  fontSize=8,  leading=13, spaceAfter=3,  textColor=colors.HexColor("#333")),
        "strat": ParagraphStyle("st", fontName=fnb, fontSize=9,  leading=14, spaceAfter=3,  textColor=colors.HexColor("#8b0000")),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm,  bottomMargin=2*cm)
    story = []
    yf = result["yf"]
    story.append(Paragraph(f"{result['name']} 종합 투자 분석 리포트", ST["cover"]))
    story.append(Paragraph(
        f"{result['timestamp']}  |  현재가 {yf.get('price','N/A')}  |  PER {yf.get('per','N/A')}  |  PBR {yf.get('pbr','N/A')}",
        ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    sections = [
        ("📊 재무분석가",             result["fin"]),
        ("📋 리서치분석가",           result["research"]),
        ("📰 뉴스감성분석가",         result["news"]),
        ("🏔 밸리인사이트",           result["valley"]),
        ("🏭 업종리서처",             result["industry"]),
        ("⚡ 투자전략가 (공격적)",    result["strategy"]),
    ]
    for title, content in sections:
        story.append(Paragraph(title, ST["head"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaa")))
        style = ST["strat"] if "전략가" in title else ST["body"]
        for line in (content or "").split("\n"):
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line.strip())
            if not line:
                story.append(Spacer(1, 0.1*cm)); continue
            line = re.sub(r"[<>&]", lambda m: {"<":"&lt;",">":"&gt;","&":"&amp;"}[m.group()], line)
            try:
                story.append(Paragraph(line, style))
            except:
                story.append(Paragraph(line[:200], style))
        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────
def send_telegram(pdf_buf, name, ts):
    if not TG_TOKEN or not TG_CHAT:
        print("  Telegram 설정 없음")
        return
    fname = f"{name}_분석_{ts.replace('.','').replace(':','').replace(' ','_')}.pdf"
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
        data={"chat_id": TG_CHAT, "caption": f"📈 {name} 6-Agent 투자 분석\n{ts}"},
        files={"document": (fname, pdf_buf, "application/pdf")}, timeout=30)
    print("  ✅ Telegram 전송 완료" if r.ok else f"  ❌ {r.text[:100]}")

# ─────────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("사용: python stock_agent_harness.py <종목명 또는 코드>")
        sys.exit(1)
    result  = analyze(" ".join(sys.argv[1:]))
    print("\n[PDF 생성...]")
    pdf_buf = build_pdf(result)
    out     = Path("analysis")
    out.mkdir(exist_ok=True)
    ts_safe = result["timestamp"].replace(".","").replace(":","").replace(" ","_")
    path    = out / f"{result['name']}_분석_{ts_safe}.pdf"
    path.write_bytes(pdf_buf.getvalue())
    print(f"  저장: {path}")
    pdf_buf.seek(0)
    send_telegram(pdf_buf, result["name"], result["timestamp"])

if __name__ == "__main__":
    main()
