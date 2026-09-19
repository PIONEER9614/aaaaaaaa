import os
import io
import time
import zipfile
import xml.etree.ElementTree as ET
import requests
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

_corp_map = {}  # corp_name → {corp_code, stock_code}


def _load_corp_codes():
    global _corp_map
    if _corp_map:
        return
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(res.content))
    xml_data = z.read("CORPCODE.xml")
    root = ET.fromstring(xml_data)
    for item in root.findall("list"):
        name = (item.findtext("corp_name") or "").strip()
        code = (item.findtext("corp_code") or "").strip()
        stock = (item.findtext("stock_code") or "").strip()
        if name and code:
            _corp_map[name] = {"corp_code": code, "stock_code": stock}


def _find_corp(query):
    _load_corp_codes()
    # 정확히 일치
    if query in _corp_map:
        return _corp_map[query]["corp_code"], query
    # 주식코드로 검색
    for name, info in _corp_map.items():
        if info["stock_code"] == query:
            return info["corp_code"], name
    # 부분 일치 (상장사 우선)
    matches = [
        (name, info) for name, info in _corp_map.items()
        if query in name and info["stock_code"]
    ]
    if matches:
        matches.sort(key=lambda x: len(x[0]))
        name, info = matches[0]
        return info["corp_code"], name
    return None, None


def _get_statements(corp_code, year, reprt_code="11011"):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    for fs_div in ("CFS", "OFS"):  # 연결 우선, 없으면 개별
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        if data.get("status") == "000" and data.get("list"):
            return data["list"], fs_div
    return [], None


def _pick(items, *keywords):
    """account_nm에 키워드가 포함된 항목의 당기 금액 반환 (억원)"""
    for kw in keywords:
        for item in items:
            nm = item.get("account_nm", "")
            if kw in nm:
                raw = item.get("thstrm_amount", "").replace(",", "").replace(" ", "")
                try:
                    return int(raw) // 100_000_000  # 원 → 억원
                except ValueError:
                    pass
    return None


def _pick_prev(items, *keywords):
    """전기 금액 반환 (억원)"""
    for kw in keywords:
        for item in items:
            nm = item.get("account_nm", "")
            if kw in nm:
                raw = item.get("frmtrm_amount", "").replace(",", "").replace(" ", "")
                try:
                    return int(raw) // 100_000_000
                except ValueError:
                    pass
    return None


def _fmt(val):
    if val is None:
        return "N/A"
    if abs(val) >= 10000:
        return f"{val/10000:.1f}조원"
    return f"{val:,}억원"


def _pct(a, b):
    if a is None or b is None or b == 0:
        return "N/A"
    return f"{(a - b) / abs(b) * 100:+.1f}%"


def analyze(query: str) -> str:
    # 1. 종목 찾기
    corp_code, corp_name = _find_corp(query)
    if not corp_code:
        return f"'{query}' 종목을 DART에서 찾을 수 없습니다."

    # 2. 최근 2개년 연간 재무제표 수집
    from datetime import datetime
    cur_year = datetime.now().year
    items, fs_div = _get_statements(corp_code, cur_year - 1)
    if not items:
        items, fs_div = _get_statements(corp_code, cur_year - 2)
        report_year = cur_year - 2
    else:
        report_year = cur_year - 1

    if not items:
        return f"{corp_name}: 재무데이터를 가져올 수 없습니다."

    fs_label = "연결" if fs_div == "CFS" else "개별"

    # 3. 핵심 항목 추출
    rev   = _pick(items, "매출액", "수익(매출액)", "영업수익")
    op    = _pick(items, "영업이익")
    net   = _pick(items, "당기순이익")
    asset = _pick(items, "자산총계")
    liab  = _pick(items, "부채총계")
    eq    = _pick(items, "자본총계")

    rev_p  = _pick_prev(items, "매출액", "수익(매출액)", "영업수익")
    op_p   = _pick_prev(items, "영업이익")
    net_p  = _pick_prev(items, "당기순이익")

    # 4. 비율 계산
    op_margin  = f"{op/rev*100:.1f}%" if op and rev else "N/A"
    net_margin = f"{net/rev*100:.1f}%" if net and rev else "N/A"
    roe        = f"{net/eq*100:.1f}%" if net and eq else "N/A"
    debt_ratio = f"{liab/eq*100:.1f}%" if liab and eq else "N/A"

    # 5. Groq 분석
    summary_input = (
        f"기업명: {corp_name}\n"
        f"기준: {report_year}년 연간 ({fs_label}재무제표)\n\n"
        f"[손익]\n"
        f"매출액: {_fmt(rev)} (전년 {_fmt(rev_p)}, {_pct(rev, rev_p)})\n"
        f"영업이익: {_fmt(op)} (전년 {_fmt(op_p)}, {_pct(op, op_p)}) | 영업이익률: {op_margin}\n"
        f"당기순이익: {_fmt(net)} (전년 {_fmt(net_p)}, {_pct(net, net_p)}) | 순이익률: {net_margin}\n\n"
        f"[재무상태]\n"
        f"자산총계: {_fmt(asset)}\n"
        f"부채총계: {_fmt(liab)}\n"
        f"자본총계: {_fmt(eq)}\n"
        f"부채비율: {debt_ratio} | ROE: {roe}\n"
    )

    prompt = (
        f"다음은 {corp_name}의 재무 데이터입니다.\n"
        f"투자자 관점에서 핵심 포인트를 3~5줄로 한국어로 분석해주세요.\n"
        f"수익성, 성장성, 재무건전성 중심으로 간결하게 작성하세요.\n\n"
        f"{summary_input}"
    )

    try:
        client = Groq(api_key=GROQ_API_KEY)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        ai_comment = resp.choices[0].message.content.strip()
    except Exception as e:
        ai_comment = f"AI 분석 실패: {e}"

    # 6. 최종 메시지 조합
    result = (
        f"📊 {corp_name} 재무분석\n"
        f"({report_year}년 연간 · {fs_label})\n"
        f"{'─'*28}\n"
        f"💰 손익\n"
        f"  매출액    {_fmt(rev)}  ({_pct(rev, rev_p)})\n"
        f"  영업이익  {_fmt(op)}  ({_pct(op, op_p)})\n"
        f"  당기순이익 {_fmt(net)}  ({_pct(net, net_p)})\n\n"
        f"🏦 재무상태\n"
        f"  자산  {_fmt(asset)}\n"
        f"  부채  {_fmt(liab)}\n"
        f"  자본  {_fmt(eq)}\n\n"
        f"📐 지표\n"
        f"  영업이익률 {op_margin}  순이익률 {net_margin}\n"
        f"  ROE {roe}  부채비율 {debt_ratio}\n"
        f"{'─'*28}\n"
        f"🤖 AI 분석\n{ai_comment}"
    )
    return result
