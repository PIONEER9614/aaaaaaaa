"""
재무제표 정밀 분석기 — 클로드 참고 자료/_notes/재무제표 분석 틀.md 의 순서대로 DART 숫자를 계산한다.

  python fs_analyzer.py 삼성전자
  python fs_analyzer.py 005930 --years 5
  python fs_analyzer.py 한화에어로스페이스 --ofs      # 별도 재무제표

결과: data/fs_analysis/<회사>_<날짜>.md / .json  (해석은 노트 기준으로 사람이/클로드가 한다)
"""
import os, io, re, sys, json, time, argparse, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path.home() / ".claude-code-secrets" / ".env")
DART_KEY = (os.getenv("DART_API_KEY") or "").strip()

BASE = Path(__file__).parent
CORP_CACHE = BASE / "data" / "dart" / "corpcode.json"
OUT_DIR = BASE / "data" / "fs_analysis"
U = {"div": 1e8, "label": "억", "cur": "원", "head": "억원"}   # 해외면 main()에서 바꿈
API = "https://opendart.fss.or.kr/api"
REPRT = {"annual": "11011", "h1": "11012", "q1": "11013", "q3": "11014"}
REPRT_NAME = {"11013": "1분기", "11012": "반기", "11014": "3분기"}


# ── 회사 찾기 ────────────────────────────────────────────────────────────────
def load_corps():
    if CORP_CACHE.exists() and time.time() - CORP_CACHE.stat().st_mtime < 30 * 86400:
        return json.loads(CORP_CACHE.read_text(encoding="utf-8"))
    print("  [준비] DART 회사 목록 받는 중...")
    r = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": DART_KEY}, timeout=60)
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml"))
    corps = [{"corp_code": i.findtext("corp_code", "").strip(),
              "name": i.findtext("corp_name", "").strip(),
              "stock": i.findtext("stock_code", "").strip()}
             for i in root.findall("list") if i.findtext("stock_code", "").strip()]
    CORP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CORP_CACHE.write_text(json.dumps(corps, ensure_ascii=False), encoding="utf-8")
    return corps


ALIAS = {"현대차": "현대자동차", "기아차": "기아", "엘지전자": "LG전자", "삼전": "삼성전자", "하이닉스": "SK하이닉스",
         "현대모비스": "현대모비스", "포스코": "POSCO홀딩스", "엔솔": "LG에너지솔루션", "삼바": "삼성바이오로직스"}


def find_corp(q):
    corps = load_corps()
    q = q.strip()
    q = ALIAS.get(q.replace(" ", ""), q)   # 흔히 부르는 줄임말 → DART 정식 이름
    if re.fullmatch(r"\d{6}", q):
        hit = [c for c in corps if c["stock"] == q]
    else:
        hit = [c for c in corps if c["name"] == q] or \
              sorted([c for c in corps if q.replace(" ", "") in c["name"].replace(" ", "")], key=lambda c: len(c["name"]))
    if not hit:
        sys.exit(f"  [오류] '{q}' 상장사를 못 찾음")
    return hit[0]


# ── DART 받기 ────────────────────────────────────────────────────────────────
def fetch(corp_code, year, reprt, fs_div):
    for t in range(4):   # DART가 가끔 연결을 끊음(SSL EOF) → 잠깐 쉬고 다시
        try:
            r = requests.get(f"{API}/fnlttSinglAcntAll.json", timeout=20, params={
                "crtfc_key": DART_KEY, "corp_code": corp_code, "bsns_year": str(year),
                "reprt_code": reprt, "fs_div": fs_div})
            break
        except requests.exceptions.RequestException:
            if t == 3:
                raise
            print(f"  [DART] 연결 끊김 — {2 ** t * 2}초 뒤 다시 ({year})")
            time.sleep(2 ** t * 2)
    time.sleep(0.25)
    d = r.json()
    return d["list"] if d.get("status") == "000" and d.get("list") else None


def num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def norm(name):
    n = re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\dIVX]+[\.\)]\s*", "", name or "")
    return re.sub(r"[\s\-·ㆍ]", "", n)


def norm_np(name):
    return re.sub(r"\(.*?\)", "", norm(name))


SJ_IS = ("IS", "CIS")


def pick(items, sjs, ids=(), names=(), contains=(), field="thstrm_amount", exclude=(), src=None):
    """src(dict)를 주면 어떤 줄을 어떤 방법(꼬리표/이름/이름 일부)으로 집었는지 남긴다 — 검산용"""
    rows = [i for i in items if i.get("sj_div") in sjs]

    def hit(i, how):
        if src is not None:
            src.update(how=how, nm=i.get("account_nm", ""), id=i.get("account_id", ""), sj=i.get("sj_div", ""))
        return num(i.get(field))
    for want in ids:
        for i in rows:
            if i.get("account_id") == want and num(i.get(field)) is not None:
                return hit(i, "꼬리표")
    for want in names:
        for i in rows:
            if want in (norm(i["account_nm"]), norm_np(i["account_nm"])) and num(i.get(field)) is not None:
                return hit(i, "이름")
    for want in contains:
        for i in rows:
            n = norm(i["account_nm"])
            if want in n and not any(x in n for x in exclude) and num(i.get(field)) is not None:
                return hit(i, "이름 일부")
    return None


def sum_rows(items, sjs, contains, exclude=(), field="thstrm_amount"):
    seen, tot, hit = set(), 0.0, False
    for i in items:
        if i.get("sj_div") not in sjs:
            continue
        n = norm(i["account_nm"])
        if any(c in n for c in contains) and not any(x in n for x in exclude):
            v = num(i.get(field))
            if v is not None and n not in seen:
                seen.add(n); tot += v; hit = True
    return tot if hit else None


def extract(items, field="thstrm_amount", is_field=None):
    """한 보고서 → 원 단위 숫자 묶음. is_field: 손익·현금흐름에 쓸 필드(분기 누적 등)"""
    f, fi = field, (is_field or field)
    src = {}

    def g(key, sj, **kw):
        src[key] = {}
        return pick(items, sj, field=kw.pop("field", f), src=src[key], **kw)
    d = {
        "revenue": g("revenue", SJ_IS, field=fi, ids=("ifrs-full_Revenue",), names=("매출액", "수익", "영업수익", "매출"), contains=("매출액", "영업수익")),
        "cogs": g("cogs", SJ_IS, field=fi, ids=("ifrs-full_CostOfSales",), names=("매출원가", "영업비용"), contains=("매출원가",)),
        "gross": g("gross", SJ_IS, field=fi, ids=("ifrs-full_GrossProfit",), names=("매출총이익",), contains=("매출총이익",)),
        "op": g("op", SJ_IS, field=fi, ids=("dart_OperatingIncomeLoss",), names=("영업이익", "영업손실"), contains=("영업이익",)),
        "pbt": g("pbt", SJ_IS, field=fi, ids=("ifrs-full_ProfitLossBeforeTax",), contains=("법인세비용차감전", "법인세차감전")),
        "tax": g("tax", SJ_IS, field=fi, ids=("ifrs-full_IncomeTaxExpenseContinuingOperations",), names=("법인세비용", "법인세비용(수익)"), contains=("법인세비용",), exclude=("차감전",)),
        "ni": g("ni", SJ_IS, field=fi, ids=("ifrs-full_ProfitLoss",), names=("당기순이익", "당기순손실", "분기순이익", "반기순이익"), contains=("당기순이익", "분기순이익", "반기순이익")),
        "fin_cost": g("fin_cost", SJ_IS, field=fi, ids=("ifrs-full_FinanceCosts",), names=("금융비용", "금융원가"), contains=("금융비용", "금융원가", "이자비용")),
        "assets": g("assets", ("BS",), ids=("ifrs-full_Assets",), names=("자산총계",)),
        "liab": g("liab", ("BS",), ids=("ifrs-full_Liabilities",), names=("부채총계",)),
        "equity": g("equity", ("BS",), ids=("ifrs-full_Equity",), names=("자본총계",)),
        "cur_assets": g("cur_assets", ("BS",), ids=("ifrs-full_CurrentAssets",), names=("유동자산",)),
        "cur_liab": g("cur_liab", ("BS",), ids=("ifrs-full_CurrentLiabilities",), names=("유동부채",)),
        "inventory": g("inventory", ("BS",), ids=("ifrs-full_Inventories",), names=("재고자산",), contains=("재고자산",)),
        "receivables": g("receivables", ("BS",), ids=("dart_ShortTermTradeReceivable", "ifrs-full_CurrentTradeReceivables", "ifrs-full_TradeAndOtherCurrentReceivables"),
                         names=("매출채권", "매출채권및기타채권", "매출채권및기타유동채권"), contains=("매출채권",), exclude=("장기",)),
        "payables": g("payables", ("BS",), ids=("dart_ShortTermTradePayables", "ifrs-full_TradePayables", "ifrs-full_TradeAndOtherCurrentPayables"),
                      names=("매입채무", "매입채무및기타채무", "매입채무및기타유동채무"), contains=("매입채무",), exclude=("장기",)),
        "retained": g("retained", ("BS",), ids=("ifrs-full_RetainedEarnings",), contains=("이익잉여금",)),
        "contract_liab": sum_rows(items, ("BS",), ("계약부채", "선수금"), exclude=("장기",), field=f),
        "fin_assets": sum_rows(items, ("BS",), ("현금및현금성자산", "단기금융상품", "단기투자자산", "단기금융자산", "장기금융상품",
                                                "당기손익공정가치측정금융자산", "상각후원가측정금융자산"), field=f),
        "fin_liab": sum_rows(items, ("BS",), ("차입금", "사채", "리스부채"), exclude=("사채할인", "합계"), field=f)
                    # 한전처럼 차입금·사채를 '유동/비유동금융부채'로 묶어 적는 회사 (파생상품 등 일부 섞인 근사치)
                    or sum_rows(items, ("BS",), ("유동금융부채", "비유동금융부채"), exclude=("비금융",), field=f),
        "cfo": g("cfo", ("CF",), field=fi, ids=("ifrs-full_CashFlowsFromUsedInOperatingActivities",), contains=("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로인한순현금흐름")),
        "capex": g("capex", ("CF",), field=fi, ids=("ifrs-full_PurchaseOfPropertyPlantAndEquipment",), names=("유형자산의취득", "유형자산취득"), contains=("유형자산의취득", "유형자산취득"), exclude=("기타유형",)),
        "capex_intang": g("capex_intang", ("CF",), field=fi, ids=("ifrs-full_PurchaseOfIntangibleAssets",), contains=("무형자산의취득", "무형자산취득")),
        "dep": sum_rows(items, ("CF",), ("감가상각비", "상각비"), exclude=("환입", "처분"), field=fi),
        # 환율 효과: 현금 증가 = 영업 + 투자 + 재무 + 환율변동효과
        "cash": g("cash", ("BS",), ids=("ifrs-full_CashAndCashEquivalents",), names=("현금및현금성자산",)),
        "cfi": g("cfi", ("CF",), field=fi, ids=("ifrs-full_CashFlowsFromUsedInInvestingActivities",), contains=("투자활동현금흐름", "투자활동으로인한")),
        "cff": g("cff", ("CF",), field=fi, ids=("ifrs-full_CashFlowsFromUsedInFinancingActivities",), contains=("재무활동현금흐름", "재무활동으로인한")),
        "fx_cash": g("fx_cash", ("CF",), field=fi, ids=("ifrs-full_EffectOfExchangeRateChangesOnCashAndCashEquivalents",), contains=("환율변동효과", "환율변동으로인한")),
        "fx_oci": g("fx_oci", ("CIS", "IS"), field=fi, ids=("ifrs-full_OtherComprehensiveIncomeNetOfTaxExchangeDifferencesOnTranslation",), contains=("해외사업환산", "해외사업장환산")),
    }
    if d["capex"] is not None: d["capex"] = abs(d["capex"])
    if d["capex_intang"] is not None: d["capex_intang"] = abs(d["capex_intang"])
    if d["fin_cost"] is not None: d["fin_cost"] = abs(d["fin_cost"])
    if d["gross"] is None and d["revenue"] is not None and d["cogs"] is not None:
        d["gross"] = d["revenue"] - d["cogs"]
        src["gross"] = {"how": "계산(매출-매출원가)"}
    d["_src"] = {k: v for k, v in src.items() if v}
    return d


# ── 지표 계산 ────────────────────────────────────────────────────────────────
def div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def avg(a, b):
    if a is None: return None
    return (a + b) / 2 if b is not None else a


def growth(a, b):
    return (a / b - 1) * 100 if a is not None and b not in (None, 0) and b > 0 else None


def metrics(yrs):
    out = {}
    ys = sorted(yrs)
    for idx, y in enumerate(ys):
        d, p = yrs[y], (yrs[ys[idx - 1]] if idx else None)
        P = (lambda k: p.get(k)) if p else (lambda k: None)
        m = {}
        t = div(d["tax"], d["pbt"])
        # 세금 환급·이상치 해는 법정세율 근사(22%)로 — 일회성 세금 효과를 영업이익에 섞지 않기
        t = t if t is not None and d["pbt"] and d["pbt"] > 0 and 0.05 <= t <= 0.4 else 0.22
        m["실효세율"] = t * 100
        fa, fl = d["fin_assets"] or 0, d["fin_liab"] or 0
        noa = None
        if d["assets"] is not None and d["liab"] is not None:
            noa = (d["assets"] - fa) - (d["liab"] - fl)
        d["noa"], d["nfo"] = noa, fl - fa
        nopat = d["op"] * (1 - t) if d["op"] is not None else None
        d["nopat"] = nopat
        avg_noa = avg(noa, P("noa"))
        avg_eq = avg(d["equity"], P("equity"))
        m["매출성장률"] = growth(d["revenue"], P("revenue"))
        m["영업이익성장률"] = growth(d["op"], P("op"))
        m["매출총이익률"] = div(d["gross"], d["revenue"]) and div(d["gross"], d["revenue"]) * 100
        m["판관비율"] = (div(d["gross"] - d["op"], d["revenue"]) * 100) if d["gross"] is not None and d["op"] is not None and d["revenue"] else None
        m["영업이익률"] = div(d["op"], d["revenue"]) and div(d["op"], d["revenue"]) * 100
        m["순이익률"] = div(d["ni"], d["revenue"]) and div(d["ni"], d["revenue"]) * 100
        m["RNOA"] = div(nopat, avg_noa) and div(nopat, avg_noa) * 100 if avg_noa and avg_noa > 0 else None
        m["세후영업이익률"] = div(nopat, d["revenue"]) and div(nopat, d["revenue"]) * 100
        m["순영업자산회전율"] = div(d["revenue"], avg_noa) if avg_noa and avg_noa > 0 else None
        m["ROE"] = div(d["ni"], avg_eq) and div(d["ni"], avg_eq) * 100
        m["재무레버리지(NFO/자본)"] = div(d["nfo"], d["equity"])
        m["매출채권회수일"] = div(d["receivables"], d["revenue"]) and div(d["receivables"], d["revenue"]) * 365
        m["재고보유일"] = div(d["inventory"], d["cogs"]) and div(d["inventory"], d["cogs"]) * 365
        m["매입채무지급일"] = div(d["payables"], d["cogs"]) and div(d["payables"], d["cogs"]) * 365
        parts = [m["매출채권회수일"], m["재고보유일"], m["매입채무지급일"]]
        m["현금전환주기"] = parts[0] + (parts[1] or 0) - (parts[2] or 0) if parts[0] is not None else None
        m["매출채권증가율"] = growth(d["receivables"], P("receivables"))
        m["재고증가율"] = growth(d["inventory"], P("inventory"))
        m["계약부채·선수금증가율"] = growth(d["contract_liab"], P("contract_liab"))
        m["영업현금/순이익"] = div(d["cfo"], d["ni"]) if d["ni"] and d["ni"] > 0 else None
        m["발생액비율"] = (div(d["ni"] - d["cfo"], avg_noa) * 100) if d["ni"] is not None and d["cfo"] is not None and avg_noa and avg_noa > 0 else None
        d["fcf"] = d["cfo"] - d["capex"] if d["cfo"] is not None and d["capex"] is not None else None
        m["설비투자/감가상각"] = div(d["capex"], d["dep"]) if d["dep"] else None
        m["유동비율"] = div(d["cur_assets"], d["cur_liab"]) and div(d["cur_assets"], d["cur_liab"]) * 100
        m["부채비율"] = div(d["liab"], d["equity"]) and div(d["liab"], d["equity"]) * 100
        ebitda = d["op"] + d["dep"] if d["op"] is not None and d["dep"] else None
        d["ebitda"] = ebitda
        m["순차입금/EBITDA"] = div(d["nfo"], ebitda) if ebitda and ebitda > 0 else None
        m["이자보상배율"] = div(d["op"], d["fin_cost"])
        # 환율 효과
        fx = d.get("fx_cash")
        dc = d.get("cash") - P("cash") if d.get("cash") is not None and P("cash") is not None else None
        d["cash_delta"] = dc
        m["현금증가 중 환율효과"] = fx / U["div"] if fx is not None else None
        m["환율효과/영업현금"] = div(fx, d["cfo"]) * 100 if fx is not None and d.get("cfo") else None
        m["환율 빼고 현금증가"] = (dc - fx) / U["div"] if dc is not None and fx is not None else None
        m["해외환산손익/순이익"] = div(d.get("fx_oci"), abs(d["ni"])) * 100 if d.get("fx_oci") is not None and d["ni"] else None
        out[y] = m
    return out


def altman_z(d, mcap):
    if not all(d.get(k) for k in ("assets", "liab")) or mcap is None:
        return None
    ta = d["assets"]
    wc = (d["cur_assets"] or 0) - (d["cur_liab"] or 0)
    return (1.2 * wc / ta + 1.4 * (d["retained"] or 0) / ta + 3.3 * (d["op"] or 0) / ta
            + 0.6 * mcap / d["liab"] + 1.0 * (d["revenue"] or 0) / ta)


def market_cap(stock, sufs=(".KS", ".KQ")):
    try:
        import yfinance as yf
        for suf in sufs:
            fi = yf.Ticker(stock + suf).fast_info
            mc = getattr(fi, "market_cap", None)
            if mc:
                return float(mc), float(getattr(fi, "last_price", 0) or 0)
    except Exception as e:
        print(f"  [주가] 못 받음: {e}")
    return None, None


# ── 경고 신호 ────────────────────────────────────────────────────────────────
def flags(yrs, ms, z):
    ys = sorted(ms)
    f = []
    y = ys[-1]; m = ms[y]; d = yrs[y]
    py = ys[-2] if len(ys) > 1 else None
    pm = ms[py] if py else {}

    def add(level, title, why, check):
        f.append({"수준": level, "신호": title, "근거": why, "확인할 것": check})

    rg = m.get("매출성장률")
    if rg is not None and m.get("매출채권증가율") is not None and m["매출채권증가율"] - rg > 10:
        add("주의", "매출채권이 매출보다 빨리 늘었다",
            f"매출 {rg:+.1f}% vs 매출채권 {m['매출채권증가율']:+.1f}%",
            "밀어내기·대금 회수 지연 vs 연말 매출 집중·대형 고객 결제조건 변경 — 주석의 매출채권 연령·대손충당금")
    if rg is not None and m.get("재고증가율") is not None and m["재고증가율"] - rg > 10:
        add("주의", "재고가 매출보다 빨리 늘었다",
            f"매출 {rg:+.1f}% vs 재고 {m['재고증가율']:+.1f}%",
            "수요 둔화·진부화 vs 수주 대비 원재료 선확보 — 주석의 재고 구성(원재료/제품)·평가손실")
    if m.get("계약부채·선수금증가율") is not None and m["계약부채·선수금증가율"] > 30 and (d.get("contract_liab") or 0) > (d.get("revenue") or 1) * 0.03:
        add("좋은 신호", "계약부채·선수금 급증",
            f"{m['계약부채·선수금증가율']:+.1f}%",
            "수주 증가의 선행 신호인지 — 수주잔고 공시·사업보고서의 수주 현황")
    cn = [ms[k].get("영업현금/순이익") for k in ys[-2:]]
    if all(c is not None and c < 0.8 for c in cn) and len(cn) == 2:
        add("주의", "2년 연속 영업현금이 순이익의 80% 미만", f"{cn[0]:.2f}, {cn[1]:.2f}",
            "이익이 운전자본에 묶였는지, 영업외 평가이익인지 — 현금흐름표 조정 항목")
    if (d.get("ni") or 0) > 0 and (d.get("cfo") or 0) < 0:
        add("경고", "흑자인데 영업현금흐름이 마이너스", f"순이익 {d['ni']/U['div']:,.0f}{U['label']}, 영업현금 {d['cfo']/U['div']:,.0f}{U['label']}",
            "흑자도산 구조인지 — 운전자본 변동, 차입 증가 여부")
    if m.get("발생액비율") is not None and m["발생액비율"] > 10:
        add("주의", "발생액 비율이 높다", f"{m['발생액비율']:.1f}% (순영업자산 대비)",
            "장부 이익 비중이 커서 다음 해 이익이 꺾일 위험 — 이익의 질 점검")
    if m.get("매출총이익률") is not None and pm.get("매출총이익률") is not None and m.get("영업이익률") is not None and pm.get("영업이익률") is not None:
        if m["매출총이익률"] < pm["매출총이익률"] - 1 and m["영업이익률"] > pm["영업이익률"] + 0.5:
            add("주의", "매출총이익률은 떨어졌는데 영업이익률은 올랐다",
                f"총이익률 {pm['매출총이익률']:.1f}→{m['매출총이익률']:.1f}%, 영업이익률 {pm['영업이익률']:.1f}→{m['영업이익률']:.1f}%",
                "판관비 절감이 지속 가능한지 (연구개발·광고 축소, 충당금 환입 같은 일회성인지)")
    if m.get("RNOA") is not None and pm.get("RNOA") is not None and rg is not None and rg > 5 and m["RNOA"] < pm["RNOA"] - 3:
        add("주의", "매출은 늘었는데 사업 수익성(RNOA)이 떨어졌다", f"RNOA {pm['RNOA']:.1f}→{m['RNOA']:.1f}%",
            "외형 성장을 위해 자산을 과하게 늘렸는지, 가격 경쟁인지")
    cd = m.get("설비투자/감가상각")
    if cd is not None and cd < 0.8:
        add("참고", "설비투자가 감가상각보다 작다", f"{cd:.2f}배", "투자 축소로 이익을 당겨쓰는지, 성숙 사업이라 정상인지")
    elif cd is not None and cd > 2:
        add("참고", "증설기 — 설비투자가 감가상각의 2배 이상", f"{cd:.2f}배", "앞으로 늘어날 감가상각 부담과 증설 수요의 근거")
    if m.get("순차입금/EBITDA") is not None and m["순차입금/EBITDA"] > 3:
        add("경고", "순차입금이 EBITDA의 3배 초과", f"{m['순차입금/EBITDA']:.1f}배", "차입 만기 구조·금리 민감도")
    if m.get("이자보상배율") is not None and m["이자보상배율"] < 1.5 and (d.get("nfo") or 0) > 0:
        add("경고", "이자보상배율 1.5배 미만", f"{m['이자보상배율']:.1f}배 (금융비용엔 환손실 포함될 수 있음)", "주석의 이자비용만 따로 확인")
    if z is not None and z < 1.81:
        cl_share = div(d.get("contract_liab"), d.get("liab"))
        if cl_share is not None and cl_share > 0.2:
            add("참고", "알트만 Z 위험권이지만 선수금 때문일 가능성", f"Z {z:.2f}, 부채 중 계약부채·선수금 {cl_share*100:.0f}%",
                "수주업은 고객이 미리 낸 돈이 부채로 잡혀 Z가 낮게 나옴 — 차입금 기준 안정성으로 판단")
        else:
            add("경고", "알트만 Z 위험권", f"{z:.2f}", "제조업 기준 — 금융·서비스업·수주업이면 무시")
    if d.get("op") is not None and d.get("ni") is not None and d["op"] > 0:
        gap = d["ni"] - d["op"] * (1 - ms[y]["실효세율"] / 100)
        if abs(gap) > abs(d["op"]) * 0.3:
            add("참고", "순이익과 영업이익 사이 차이가 크다", f"영업외·일회성 영향 약 {gap/U['div']:+,.0f}{U['label']}",
                "지분법·처분이익·평가손익·환율 — 반복될 이익인지")
    fx, dc = d.get("fx_cash"), d.get("cash_delta")
    if fx is not None and dc is not None and dc > 0 and fx > 0 and fx >= dc * 0.3:
        add("참고", "현금 증가의 상당 부분이 환율 덕분", f"현금 +{dc/U['div']:,.0f}{U['label']} 중 환율효과 +{fx/U['div']:,.0f}{U['label']} ({fx/dc*100:.0f}%)",
            "외화 현금이 많아 자국 통화 약세로 환산액만 늘었는지 — 영업 성과로 보면 안 됨, 환율 반대로 가면 그대로 줄어듦")
    elif fx is not None and d.get("cfo") and abs(fx) > abs(d["cfo"]) * 0.1:
        add("참고", "환율효과가 영업현금의 10% 넘음", f"환율효과 {fx/U['div']:+,.0f}{U['label']} vs 영업현금 {d['cfo']/U['div']:,.0f}{U['label']}",
            "외화 자산·부채 규모와 통화 구성 — 주석의 환위험 민감도(환율 10% 변동 시 손익)")
    oc = m.get("해외환산손익/순이익")
    if oc is not None and abs(oc) > 10:
        add("참고", "해외법인 환산손익이 크다 (순이익을 안 거치고 자본으로)", f"순이익의 {oc:+.0f}%",
            "자본·ROE가 환율로 출렁임 — 원화 기준 성장과 현지 통화 기준 성장을 구분, 해외 매출 비중 확인")
    return f


# ── 데이터 검산 ──────────────────────────────────────────────────────────────
# DART 공개 통로는 숫자는 맞아도 꼬리표(표준코드)가 빠지거나 엉뚱하게 붙은 경우가 있다.
# 잘못 집으면 빈칸 대신 그럴듯한 숫자가 들어가므로, 회계 등식·전년 대조·튀는 값으로 들키게 만든다.
NAME_KW = {"revenue": ("매출", "수익"), "cogs": ("원가", "비용"), "gross": ("총이익", "총손실", "총손익"),
           "op": ("영업",), "ni": ("순이익", "순손실", "순손익"), "pbt": ("차감전",), "tax": ("법인세",),
           "assets": ("자산",), "liab": ("부채",), "equity": ("자본",), "cur_assets": ("유동자산",),
           "cur_liab": ("유동부채",), "inventory": ("재고",), "receivables": ("채권",), "payables": ("채무",),
           "cfo": ("영업",), "cfi": ("투자",), "cff": ("재무",), "cash": ("현금",), "retained": ("잉여금", "결손금")}
# 꼬리표는 맞는 항목인데 이름에 이런 말이 있으면 다른 줄일 가능성이 큼
NAME_BAD = {"revenue": ("기타", "금융", "영업외", "이자", "배당", "지분법", "투자"), "cogs": ("판매비", "관리비", "금융", "기타"),
            "op": ("영업외", "기타영업"), "ni": ("지배", "비지배", "주당", "중단", "포괄"), "assets": ("유동", "금융", "기타"),
            "liab": ("유동", "금융", "기타"), "equity": ("지배", "비지배", "기타"), "cfo": ("기타",), "cash": ("기타", "단기")}
KEY_KO = {"revenue": "매출", "cogs": "매출원가", "gross": "매출총이익", "op": "영업이익", "ni": "순이익",
          "pbt": "세전이익", "tax": "법인세", "assets": "자산총계", "liab": "부채총계", "equity": "자본총계",
          "cur_assets": "유동자산", "cur_liab": "유동부채", "inventory": "재고자산", "receivables": "매출채권",
          "payables": "매입채무", "cfo": "영업현금흐름", "cfi": "투자현금흐름", "cff": "재무현금흐름",
          "cash": "현금", "retained": "이익잉여금", "fin_cost": "금융비용", "capex": "설비투자"}
CORE = ("revenue", "cogs", "op", "ni", "assets", "liab", "equity", "inventory", "receivables", "cfo")
UNTAGGED = ("", "-표준계정코드 미사용-")


def _off(a, b, base, tol):
    """a와 b가 base 대비 tol 넘게 다르면 차이를 돌려준다"""
    if a is None or b is None:
        return None
    gap = a - b
    return gap if abs(gap) > max(abs(base or 0) * tol, 1e6 if U["div"] >= 1e8 else 1) else None


def verify(yrs, raw_items=None, meta=None):
    """→ (결과 목록, 요약). raw_items: {연도: DART 원본 줄들} (SEC면 None), meta: {"acc_mt": 결산월}"""
    raw_items, meta = raw_items or {}, meta or {}
    ys = sorted(yrs)
    out, n_eq, n_ok = [], 0, 0
    amt = lambda v: f"{v/U['div']:,.1f}{U['label']}"

    def add(level, y, what, detail, where):
        out.append({"수준": level, "연도": y, "검산": what, "내용": detail, "원문 볼 곳": where})

    def eq(y, what, a, b, base, tol, detail, where, level="확인 필요"):
        nonlocal n_eq, n_ok
        if a is None or b is None:
            return
        n_eq += 1
        gap = _off(a, b, base, tol)
        if gap is None:
            n_ok += 1
        else:
            add(level, y, what, f"{detail} → 차이 {amt(gap)}", where)

    def label(d, k):
        s = d.get("_src", {}).get(k)
        return f"'{s['nm']}'" if s and s.get("nm") else KEY_KO.get(k, k)

    for idx, y in enumerate(ys):
        d = yrs[y]
        # 1) 자산 = 부채 + 자본
        if d.get("liab") is not None and d.get("equity") is not None:
            eq(y, "자산 = 부채 + 자본", d.get("assets"), d["liab"] + d["equity"], d.get("assets"), 0.005,
               f"자산 {amt(d['assets'])} vs 부채+자본 {amt(d['liab'] + d['equity'])}", "재무상태표 합계 줄")
        # 2) 매출 - 매출원가 = 매출총이익 (총이익을 직접 가져온 경우만)
        #    플랫폼·금융형(영업수익-영업비용 구조)은 매출원가 줄이 없어 이 등식이 원래 안 맞음 → 참고 한 줄만
        sr = d.get("_src", {})
        platform = "영업수익" in norm(sr.get("gross", {}).get("nm", "")) or "영업비용" in norm(sr.get("cogs", {}).get("nm", ""))
        if platform and None not in (d.get("revenue"), d.get("cogs")):
            add("참고", y, "영업수익−영업비용 구조", f"매출원가 줄이 없고 '{sr.get('cogs', {}).get('nm', '')}'가 대신 잡힘 — 매출총이익·원가율 숫자는 의미 없음",
                "플랫폼·서비스 회사의 정상 형식. 영업이익부터 보면 됨")
        elif sr.get("gross", {}).get("how", "").startswith("계산") is False and None not in (d.get("revenue"), d.get("cogs")):
            eq(y, "매출 − 매출원가 = 매출총이익", d.get("gross"), d["revenue"] - d["cogs"], d["revenue"], 0.01,
               f"매출총이익 {amt(d['gross'])} vs 매출-원가 {amt(d['revenue'] - d['cogs'])} ({label(d, 'revenue')}, {label(d, 'cogs')})",
               "손익계산서 매출·매출원가 줄 — 매출을 엉뚱한 줄(영업수익 합계 등)로 집었는지")
        # 3) 세전이익 - 법인세 = 순이익 (중단영업이 있으면 어긋나는 게 정상)
        if None not in (d.get("pbt"), d.get("tax")):
            disc = any("중단영업" in norm(i.get("account_nm", "")) and num(i.get("thstrm_amount")) for i in raw_items.get(y, []))
            eq(y, "세전이익 − 법인세 = 순이익", d.get("ni"), d["pbt"] - d["tax"], d["pbt"], 0.02,
               f"순이익 {amt(d['ni'])} vs 세전-법인세 {amt(d['pbt'] - d['tax'])}" + (" (중단영업손익 있음 — 그만큼 차이는 정상)" if disc else ""),
               "손익계산서 아래쪽 — 법인세가 '환급(수익)'이라 부호가 반대인지, 중단영업손익", level="참고" if disc else "확인 필요")
        # 4) 현금흐름 합 = 현금 증감
        cash_begin = None
        if y in raw_items:
            cash_begin = pick(raw_items[y], ("BS",), ids=("ifrs-full_CashAndCashEquivalents",), names=("현금및현금성자산",), field="frmtrm_amount")
        elif idx:
            cash_begin = yrs[ys[idx - 1]].get("cash")
        if None not in (d.get("cash"), cash_begin, d.get("cfo"), d.get("cfi"), d.get("cff")):
            flow = d["cfo"] + d["cfi"] + d["cff"] + (d.get("fx_cash") or 0)
            eq(y, "영업+투자+재무+환율 = 현금 증감", flow, d["cash"] - cash_begin, max(abs(d["cfo"]), abs(d["cash"])), 0.01,
               f"현금흐름 합 {amt(flow)} vs 재무상태표 현금 증감 {amt(d['cash'] - cash_begin)}",
               "현금흐름표 맨 아래 — 매각예정자산으로 옮긴 현금·연결범위 변동 줄이 따로 있으면 정상", level="참고")
        # 5) 부분 ≤ 전체
        for part, whole in (("cur_assets", "assets"), ("cur_liab", "liab"), ("inventory", "cur_assets"), ("receivables", "cur_assets")):
            a, b = d.get(part), d.get(whole)
            if a is not None and b is not None:
                n_eq += 1
                if a > b * 1.001:
                    add("확인 필요", y, f"{KEY_KO[part]} ≤ {KEY_KO[whole]}", f"{label(d, part)} {amt(a)} > {KEY_KO[whole]} {amt(b)}",
                        f"{KEY_KO[part]}을 엉뚱한 줄로 집었을 가능성 — 재무상태표에서 직접 확인")
                else:
                    n_ok += 1
        if d.get("revenue") is not None and d.get("cogs") is not None and d["revenue"] > 0 and d["cogs"] > d["revenue"] * 1.5:
            add("확인 필요", y, "매출원가가 매출의 1.5배 초과", f"{label(d, 'cogs')} {amt(d['cogs'])} vs {label(d, 'revenue')} {amt(d['revenue'])}",
                "매출이나 매출원가를 다른 줄로 집었는지")
        # 6) 꼬리표와 이름이 서로 안 맞음 / 꼬리표 없이 이름으로 찾음
        for k, s in d.get("_src", {}).items():
            if k not in NAME_KW or not s.get("nm"):
                continue
            nm = norm(s["nm"])
            bad = [w for w in NAME_BAD.get(k, ()) if w in nm and not (k in ("assets", "liab") and nm.endswith(("총계", "합계")) and "유동" not in nm)]
            if platform and k in ("gross", "cogs"):
                continue
            if s["how"] == "꼬리표" and (not any(w in nm for w in NAME_KW[k]) or bad):
                add("확인 필요", y, "꼬리표와 이름이 안 맞음", f"{KEY_KO.get(k, k)} 꼬리표({s['id']})가 붙은 줄 이름이 '{s['nm']}'",
                    "회사가 꼬리표를 잘못 붙였을 수 있음 — 원문에서 이 줄이 정말 그 항목인지")
            elif s["how"] == "이름 일부" and k in CORE:
                add("참고", y, "꼬리표 없이 이름 일부로 찾음", f"{KEY_KO.get(k, k)} ← '{s['nm']}'",
                    "이름만 비슷한 다른 줄일 수 있음 — 원문 확인")
        # 7) 다음 해 보고서의 '전년' 숫자와 대조
        ny = ys[idx + 1] if idx + 1 < len(ys) else None
        if ny is not None and ny in raw_items:
            prev = extract(raw_items[ny], field="frmtrm_amount")
            for k in CORE:
                a, b = d.get(k), prev.get(k)
                if a is None or b is None:
                    continue
                n_eq += 1
                if _off(a, b, max(abs(a), abs(b)), 0.01) is None:
                    n_ok += 1
                else:
                    s0, s1 = d.get("_src", {}).get(k, {}), prev.get("_src", {}).get(k, {})
                    pn = s1.get("nm", "")
                    same = (s0.get("how") == s1.get("how") == "꼬리표" and s0.get("id") == s1.get("id")) or                            (s0.get("nm") is not None and norm_np(s0.get("nm", "")) == norm_np(pn))
                    if same and abs(a - b) <= 0.1 * max(abs(a), abs(b)):   # 같은 줄인데 숫자만 조금 바뀜 → 회사가 고쳐 다시 낸(재작성) 경우가 대부분
                        add("참고", y, "다음 해 보고서에서 숫자가 고쳐짐",
                            f"{KEY_KO[k]}: {y}년 보고서 {amt(a)} → {ny}년 보고서의 전년 {amt(b)} (같은 줄 '{pn}')",
                            "재작성 사유(회계정책 변경·중단영업 분류·오류 수정) — 비교할 땐 고친 숫자를 쓰는 게 맞음")
                    else:
                        add("확인 필요", y, "다음 해 보고서의 전년 숫자와 다름",
                            f"{KEY_KO[k]}: {y}년 보고서 {amt(a)} ({label(d, k)}) vs {ny}년 보고서의 전년 {amt(b)} ('{pn}')",
                            "같은 이름인데 10% 넘게 고쳐짐 — 합병·사업 매각·회계정책 변경 공시가 있었는지" if same else
                            "해마다 다른 줄을 집었거나 꼬리표가 바뀜 — 두 해 원문에서 같은 항목인지")
        # 8) 앞뒤 해와 비교해 혼자 튀거나 빠진 값
        if 0 < idx < len(ys) - 1:
            for k in ("revenue", "cogs", "assets", "equity", "inventory", "receivables"):
                a, b, c = yrs[ys[idx - 1]].get(k), d.get(k), yrs[ys[idx + 1]].get(k)
                if a and c and b is None:
                    add("확인 필요", y, "혼자 빠진 값", f"{KEY_KO[k]}: {ys[idx-1]}·{ys[idx+1]}년엔 있는데 {y}년만 없음",
                        "그해에만 꼬리표·이름이 바뀌었을 가능성")
                elif a and b and c and a > 0 and b > 0 and c > 0 and ((b / a > 3 and b / c > 3) or (b / a < 1/3 and b / c < 1/3)):
                    add("확인 필요", y, "혼자 튀는 값", f"{KEY_KO[k]}: {amt(a)} → {amt(b)} → {amt(c)}",
                        "그해에만 다른 줄을 집었을 가능성 (실제 인수합병·분할이면 정상)")
        # 9) 부호가 말이 안 되는 값 (자동 수집에서 흔한 부호 뒤집힘)
        for k in ("revenue", "assets", "liab", "cash", "inventory", "receivables", "cur_assets"):
            if d.get(k) is not None and d[k] < 0:
                add("확인 필요", y, "음수가 될 수 없는 값", f"{label(d, k)} {amt(d[k])}",
                    "부호를 반대로 적은 줄이거나 차감 줄(충당금 등)을 집은 것")
        # 10) 같은 꼬리표가 한 표에 여러 줄 (합계와 세부 줄에 같은 꼬리표) → 어느 걸 집었는지에 따라 숫자가 달라짐
        rows = [i for i in raw_items.get(y, []) if i.get("sj_div") in ("BS", "IS", "CIS", "CF")
                and (i.get("account_detail") or "-").strip() in ("-", "")]
        for k in CORE:
            sk = d.get("_src", {}).get(k, {})
            if sk.get("how") != "꼬리표" or d.get(k) is None:
                continue
            vals = {}
            for i in rows:
                if i.get("account_id") == sk["id"] and i.get("sj_div") == sk.get("sj"):
                    v = num(i.get("thstrm_amount"))
                    if v is not None:
                        vals.setdefault(v, i.get("account_nm", ""))
            if len(vals) > 1:
                top = max(vals, key=abs)
                lst = ", ".join(f"'{n}' {amt(v)}" for v, n in sorted(vals.items(), key=lambda t: -abs(t[0]))[:4])
                add("확인 필요" if abs(d[k]) < abs(top) * 0.999 else "참고", y, "같은 꼬리표가 여러 줄",
                    f"{KEY_KO[k]} 꼬리표({sk['id']})가 {len(vals)}줄: {lst} — 집은 값 {amt(d[k])}",
                    "합계 줄을 집었는지 원문 표에서 확인 (세부 줄을 집으면 작게 나옴)")
    # 11) 통화·결산월·빠진 해 — AI가 가장 흔히 섞는 기간·단위 문제
    cur = {i.get("currency") for its in raw_items.values() for i in its if i.get("currency")}
    if cur - {"KRW"}:
        add("확인 필요", "전체", "원화가 아닌 통화", f"재무제표 통화: {', '.join(sorted(cur))}",
            "금액 단위(억 원) 표기와 PBR·시가총액 비교가 틀어짐 — 원문 통화로 다시 읽기")
    if meta.get("acc_mt") and str(meta["acc_mt"]).lstrip("0") != "12":
        add("참고", "전체", f"{int(meta['acc_mt'])}월 결산 회사",
            f"'{ys[-1] if ys else ''}년'은 달력 연도가 아니라 {int(meta['acc_mt'])}월에 끝나는 회계연도",
            "다른 회사·분기 실적과 같은 해로 나란히 비교하면 기간이 어긋남")
    gaps = [y for y in range(ys[0], ys[-1]) if y not in yrs] if ys else []
    if gaps:
        add("확인 필요", "전체", "중간에 빠진 해", f"{', '.join(map(str, gaps))}년 사업보고서 숫자가 없음",
            "그해만 연결/별도가 바뀌었거나 보고서가 정정 중 — 성장률·평균이 빈 해를 건너뛰어 계산됨")
    # 12) 꼬리표 없는 줄 비율 (최근 연도)
    cover = None
    if ys and ys[-1] in raw_items:
        rows = raw_items[ys[-1]]
        cover = sum(1 for i in rows if (i.get("account_id") or "").strip() in UNTAGGED) / max(len(rows), 1) * 100
    bad = sum(1 for x in out if x["수준"] == "확인 필요")
    return out, {"등식·대조 수": n_eq, "통과": n_ok, "확인 필요": bad, "꼬리표 없는 줄(%)": cover}


def verify_md(vr, vs):
    L = ["", "## 데이터 검산 (DART 숫자를 그대로 믿어도 되는지)"]
    head = f"- 등식·전년 대조 {vs['등식·대조 수']}개 중 {vs['통과']}개 통과 · **확인 필요 {vs['확인 필요']}건**"
    if vs.get("꼬리표 없는 줄(%)") is not None:
        head += f" · 최근 연도 꼬리표 없는 줄 {vs['꼬리표 없는 줄(%)']:.0f}%"
    L.append(head)
    if not vr:
        L.append("- 걸린 것 없음 — 핵심 숫자는 서로 앞뒤가 맞음")
    for x in sorted(vr, key=lambda x: (x["수준"] != "확인 필요", x["연도"])):
        L.append(f"- [{x['수준']}] {x['연도']} · {x['검산']} — {x['내용']}  \n  원문 볼 곳: {x['원문 볼 곳']}")
    return L


# ── 출력 ─────────────────────────────────────────────────────────────────────
ROW_ABS = [("매출", "revenue"), ("영업이익", "op"), ("순이익", "ni"), ("영업현금흐름", "cfo"), ("설비투자", "capex"),
           ("잉여현금흐름", "fcf"), ("순영업자산(NOA)", "noa"), ("순금융부채(NFO, -는 순현금)", "nfo"), ("자본총계", "equity"),
           ("매출채권", "receivables"), ("재고자산", "inventory"), ("계약부채·선수금", "contract_liab")]
GROUPS = [("성장·마진", ["매출성장률", "영업이익성장률", "매출총이익률", "판관비율", "영업이익률", "순이익률"]),
          ("수익성 분해", ["RNOA", "세후영업이익률", "순영업자산회전율", "ROE", "재무레버리지(NFO/자본)", "실효세율"]),
          ("운전자본", ["매출채권회수일", "재고보유일", "매입채무지급일", "현금전환주기", "매출채권증가율", "재고증가율", "계약부채·선수금증가율"]),
          ("이익의 질", ["영업현금/순이익", "발생액비율", "설비투자/감가상각"]),
          ("안정성", ["유동비율", "부채비율", "순차입금/EBITDA", "이자보상배율"]),
          ("환율 효과", ["현금증가 중 환율효과", "환율 빼고 현금증가", "환율효과/영업현금", "해외환산손익/순이익"])]
RATIO_X = {"순영업자산회전율", "재무레버리지(NFO/자본)", "영업현금/순이익", "설비투자/감가상각", "순차입금/EBITDA", "이자보상배율"}
DAYS = {"매출채권회수일", "재고보유일", "매입채무지급일", "현금전환주기"}


def fmt(k, v):
    if v is None: return "-"
    if k in RATIO_X: return f"{v:.2f}"
    if k in DAYS: return f"{v:.0f}일"
    if k in ("현금증가 중 환율효과", "환율 빼고 현금증가"): return f"{v:,.0f}{U['label']}"
    return f"{v:.1f}%"


def eok(v):
    return "-" if v is None else f"{v/U['div']:,.0f}"


def report(corp, fs_div, yrs, ms, fl, z, mcap, price, recent, vr=None, vs=None):
    ys = sorted(yrs)
    L = [f"# {corp['name']} ({corp['stock']}) 재무제표 분석 — {datetime.now():%Y-%m-%d}",
         f"- 기준: {'연결' if fs_div == 'CFS' else '별도'} 재무제표, 사업보고서 {ys[0]}~{ys[-1]}" if fs_div in ("CFS", "OFS") else f"- 기준: SEC 공시 연차보고서(10-K/20-F) 회계연도 {ys[0]}~{ys[-1]}, 단위 {U['head']}",
         f"- 틀: 클로드 참고 자료\\_notes\\재무제표 분석 틀.md"]
    if mcap:
        L.append(f"- 시가총액 {mcap/U['div']:,.0f}{U['label']} (주가 {price:,.2f}{U['cur']})" +
                 (f" · PBR {mcap/yrs[ys[-1]]['equity']:.2f}배" if yrs[ys[-1]].get("equity") else "") +
                 (f" · 알트만 Z {z:.2f}" if z is not None else ""))
    if vs is not None:
        L += verify_md(vr, vs)
    L += ["", "## 경고 신호 (최근 연도 기준)"]
    if fl:
        for x in fl:
            L.append(f"- **[{x['수준']}] {x['신호']}** — {x['근거']}  \n  확인할 것: {x['확인할 것']}")
    else:
        L.append("- 규칙에 걸린 신호 없음")
    if recent:
        L += ["", f"## 최근 누적 실적 ({recent['label']}, 전년 동기 대비)"]
        for k, nm in (("revenue", "매출"), ("op", "영업이익"), ("ni", "순이익"), ("cfo", "영업현금흐름")):
            a, b = recent["cur"].get(k), recent["prev"].get(k)
            g = growth(a, b)
            L.append(f"- {nm}: {eok(a)}{U['label']} (전년 동기 {eok(b)}{U['label']}{', ' + format(g, '+.1f') + '%' if g is not None else ''})")
        for k, nm in (("receivables", "매출채권"), ("inventory", "재고"), ("contract_liab", "계약부채·선수금"), ("nfo", "순금융부채")):
            a, b = recent["cur"].get(k), yrs[ys[-1]].get(k)
            g = growth(a, b)
            L.append(f"- {nm}: {eok(a)}{U['label']} (직전 연말 {eok(b)}{U['label']}{', ' + format(g, '+.1f') + '%' if g is not None else ''})")
    L += ["", f"## 금액 ({U['head']})", "| 항목 | " + " | ".join(map(str, ys)) + " |", "|---|" + "---:|" * len(ys)]
    for nm, k in ROW_ABS:
        L.append(f"| {nm} | " + " | ".join(eok(yrs[y].get(k)) for y in ys) + " |")
    for g, keys in GROUPS:
        L += ["", f"## {g}", "| 지표 | " + " | ".join(map(str, ys)) + " |", "|---|" + "---:|" * len(ys)]
        for k in keys:
            L.append(f"| {k} | " + " | ".join(fmt(k, ms[y].get(k)) for y in ys) + " |")
    miss = sorted({k for y in ys for k, v in yrs[y].items() if v is None and k in ("receivables", "inventory", "dep", "capex", "fin_cost", "contract_liab", "cogs")})
    if miss:
        L += ["", f"> 못 찾은 항목: {', '.join(miss)} — 재무제표 본문에 없거나 이름이 달라서. 감가상각은 주석에만 있는 회사가 많음."]
    L += ["", "> 금융자산=현금·금융상품·금융자산류, 금융부채=차입금·사채·리스부채로 자동 분류한 근사치. 금융업·지주사는 이 틀이 안 맞음."]
    return "\n".join(L)


def corp_meta(corp_code):
    """DART 기업개황 — 결산월 등"""
    try:
        r = requests.get(f"{API}/company.json", params={"crtfc_key": DART_KEY, "corp_code": corp_code}, timeout=20).json()
        return {"acc_mt": r.get("acc_mt")}
    except Exception:
        return {}


def recent_quarter(corp_code, fs_div, last_annual):
    for year in (last_annual + 1,):
        for code in ("11014", "11012", "11013"):
            items = fetch(corp_code, year, code, fs_div)
            if items:
                # 손익: 누적(thstrm_add_amount, 없으면 thstrm_amount) / 현금흐름: thstrm_amount 가 누적
                cur = extract(items, field="thstrm_amount", is_field="thstrm_add_amount")
                cur_cf = extract(items, field="thstrm_amount")
                prev = extract(items, field="frmtrm_amount", is_field="frmtrm_add_amount")
                prev_cf = extract(items, field="frmtrm_amount")
                for k in ("revenue", "op", "ni"):
                    if cur[k] is None: cur[k] = cur_cf[k]
                    if prev[k] is None: prev[k] = prev_cf[k]
                cur["cfo"], prev["cfo"] = cur_cf["cfo"], prev_cf["cfo"]
                cur["nfo"] = (cur["fin_liab"] or 0) - (cur["fin_assets"] or 0)
                return {"label": f"{year}년 {REPRT_NAME[code]}", "cur": cur, "prev": prev}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("company")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--ofs", action="store_true", help="별도 재무제표")
    ap.add_argument("--check", metavar="글파일", help="분석 글 속 숫자를 최근 계산 결과와 대조")
    a = ap.parse_args()
    if a.check:
        return main_check(a)
    if not DART_KEY:
        sys.exit("  [오류] DART_API_KEY 없음")
    if not re.fullmatch(r"\d{6}", a.company) and re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,9}", a.company):
        return main_sec(a)
    corp = find_corp(a.company)
    print(f"  [회사] {corp['name']} ({corp['stock']})")
    fs_div = "OFS" if a.ofs else "CFS"
    yrs, raw = {}, {}
    now = datetime.now().year
    for y in range(now - 1, now - 1 - a.years - 1, -1):
        items = fetch(corp["corp_code"], y, REPRT["annual"], fs_div)
        if not items and fs_div == "CFS" and not yrs and y == now - 1:
            items = None
        if items:
            yrs[y], raw[y] = extract(items), items
            print(f"  [DART] {y} 사업보고서 {len(items)}개 항목")
        if len(yrs) >= a.years:
            break
    if not yrs and fs_div == "CFS":
        print("  [DART] 연결 없음 → 별도로 다시")
        fs_div = "OFS"
        for y in range(now - 1, now - 1 - a.years - 1, -1):
            items = fetch(corp["corp_code"], y, REPRT["annual"], fs_div)
            if items: yrs[y], raw[y] = extract(items), items
            if len(yrs) >= a.years: break
    if not yrs:
        sys.exit("  [오류] 사업보고서 재무제표를 못 받음")
    ms = metrics(yrs)
    mcap, price = market_cap(corp["stock"])
    last = max(yrs)
    z = altman_z(yrs[last], mcap)
    fl = flags(yrs, ms, z)
    recent = recent_quarter(corp["corp_code"], fs_div, last)
    vr, vs = verify(yrs, raw, corp_meta(corp["corp_code"]))
    print(f"  [검산] {vs['등식·대조 수']}개 중 {vs['통과']}개 통과, 확인 필요 {vs['확인 필요']}건")
    md = report(corp, fs_div, yrs, ms, fl, z, mcap, price, recent, vr, vs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"{corp['name']}_{datetime.now():%Y%m%d}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(
        {"corp": corp, "fs_div": fs_div, "raw": yrs, "metrics": ms, "flags": fl, "altman_z": z,
         "market_cap": mcap, "recent": recent, "verify": vr, "verify_summary": vs}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md)
    print(f"\n  [저장] {stem}.md")


# ── 글 속 숫자 대조 ──────────────────────────────────────────────────────────
# AI(나 포함)가 분석 글을 쓰면 계산기 결과와 다른 숫자가 자신 있게 섞여 들어간다(기간·단위·항목 혼동, 암산 실수).
# 글에 나온 억·조·%·배 숫자를 계산기 json의 숫자와 하나씩 맞춰 보고, 근거를 못 찾은 숫자만 골라 보여준다.
NUM_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*조(?:\s*(\d[\d,]*(?:\.\d+)?)\s*억)?|(-?\d[\d,]*(?:\.\d+)?)\s*(억|%p|%|배)")


def _pool(js):
    """json → {'억': [...], '%': [...], '배': [...]} (부호 무시)"""
    eok, pct, x = [], [], []
    def walk_raw(d):
        for k, v in (d or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                eok.append(abs(v) / 1e8)
    for d in (js.get("raw") or {}).values():
        walk_raw(d)
    rc = js.get("recent") or {}
    walk_raw(rc.get("cur")); walk_raw(rc.get("prev"))
    for m in (js.get("metrics") or {}).values():
        for k, v in m.items():
            if isinstance(v, (int, float)):
                pct.append(abs(v)); x.append(abs(v))   # 글에서 % / 배 표기가 섞여도 잡히게 둘 다
    if js.get("altman_z") is not None and isinstance(js["altman_z"], (int, float)):
        x.append(abs(js["altman_z"]))
    if js.get("market_cap"):
        eok.append(js["market_cap"] / 1e8)
    return {"억": eok, "%": pct, "배": x}


def _step(t):
    t = t.replace(",", "")
    return 10 ** -len(t.split(".")[1]) if "." in t else 1


def check_claims(text, js):
    pool = _pool(js)
    res = []
    for ln, line in enumerate(text.splitlines(), 1):
        for m in NUM_RE.finditer(line):
            if m.group(1):   # 조 (+ 억)
                a = abs(float(m.group(1).replace(",", "")))
                val, tol = a * 1e4, _step(m.group(1)) * 1e4 / 2
                if m.group(2):
                    val += float(m.group(2).replace(",", "")); tol = _step(m.group(2)) / 2
                kind = "억"
            else:
                kind = {"억": "억", "%": "%", "배": "배", "%p": "%p"}[m.group(4)]
                if kind == "%p":
                    continue   # 차이(%p)는 두 숫자의 뺄셈 — 따로 근거가 없음
                val = abs(float(m.group(3).replace(",", "")))
                tol = _step(m.group(3)) / 2
            tol = tol * 1.01 + val * 0.003 + 1e-9
            ok = any(abs(v - val) <= tol for v in pool[kind])
            res.append({"줄": ln, "숫자": m.group(0).strip(), "근거": ok, "문장": line.strip()[:90]})
    return res


def main_check(a):
    corp = find_corp(a.company)
    safe = re.sub(r'[\\/:*?"<>|]', '', corp['name']).rstrip('. ')
    cands = sorted(OUT_DIR.glob(f"{safe}_*.json"))
    if not cands:
        sys.exit(f"  [오류] {safe} 분석 결과(json)가 없음 — 먼저 python fs_analyzer.py {a.company}")
    js = json.loads(cands[-1].read_text(encoding="utf-8"))
    res = check_claims(Path(a.check).read_text(encoding="utf-8"), js)
    bad = [r for r in res if not r["근거"]]
    print(f"  [대조] {Path(a.check).name} ↔ {cands[-1].name}: 숫자 {len(res)}개 중 {len(res) - len(bad)}개 근거 있음, {len(bad)}개 근거 못 찾음")
    for r in bad:
        print(f"   - {r['줄']}줄 '{r['숫자']}' : {r['문장']}")
    if bad:
        print("  → 계산기에 없는 숫자: 직접 계산한 것(차이·합·평균)이면 식을 옆에 적고, 아니면 기간·단위·항목을 다시 확인")


def save(corp, md, payload):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', '', corp['name'])
    stem = OUT_DIR / f"{safe.rstrip('. ')}_{datetime.now():%Y%m%d}"
    Path(f"{stem}.md").write_text(md, encoding="utf-8")
    Path(f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md)
    print(f"\n  [저장] {stem}.md")


def main_sec(a):
    """미국·미국 상장 외국기업 — SEC 공시 숫자"""
    import sec_facts
    print(f"  [SEC] {a.company.upper()} 공시 숫자 받는 중...")
    got = sec_facts.load(a.company, a.years)
    if not got or not got["yrs"]:
        sys.exit(f"  [오류] SEC에서 '{a.company}' 연차보고서 숫자를 못 찾음 (미국 상장 티커인지 확인)")
    corp, yrs, unit = got["corp"], got["yrs"], got["unit"]
    U.update({"div": 1e6, "label": f"백만 {unit}", "cur": f" {unit}" if unit != "USD" else " USD", "head": f"백만 {unit}"})
    print(f"  [회사] {corp['name']} ({corp['stock']}) · 회계연도 {min(yrs)}~{max(yrs)} · {unit}")
    ms = metrics(yrs)
    mcap, price = market_cap(corp["stock"], ("",))
    if unit != "USD":   # 재무 통화와 시가총액 통화가 다르면 PBR·Z 계산 안 함
        print(f"  [주의] 재무제표 통화 {unit} ≠ 주가 통화 USD → PBR·알트만 Z 생략")
        mcap = None
    last = max(yrs)
    z = altman_z(yrs[last], mcap)
    fl = flags(yrs, ms, z)
    vr, vs = verify(yrs)
    print(f"  [검산] {vs['등식·대조 수']}개 중 {vs['통과']}개 통과, 확인 필요 {vs['확인 필요']}건")
    md = report(corp, "SEC", yrs, ms, fl, z, mcap, price, got["recent"], vr, vs)
    save(corp, md, {"corp": corp, "source": "SEC companyfacts", "unit": unit, "raw": yrs, "metrics": ms,
                    "flags": fl, "altman_z": z, "market_cap_usd": mcap, "recent": got["recent"], "verify": vr, "verify_summary": vs})


if __name__ == "__main__":
    main()
