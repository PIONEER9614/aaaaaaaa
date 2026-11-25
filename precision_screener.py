"""미너비니·오닐 정밀 스크리너 (한국·미국·일본·중국)

사용: python precision_screener.py            # 4개 시장 전부
      python precision_screener.py KR US      # 일부만
      python precision_screener.py --no-fund  # 재무 단계 생략

1차 전 종목 필터(공개 스냅샷) → 2차 일봉 검증(yfinance) → 3차 재무·Code 33
결과: data/precision_screener/<날짜>.json, <날짜>.md
"""
import gzip, json, re, subprocess, sys, time, urllib.request, warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path.home() / ".claude-code-secrets" / ".env")

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "precision_screener"
BASE = "https://xang1234.github.io/stock-screener/static-data/"
UA = "precision-screener/1.0 personal-research"
ADV_MIN = {"KR": 700_000, "US": 20_000_000, "JP": 5_000_000, "CN": 10_000_000}
MARKET_NAME = {"KR": "한국", "US": "미국", "JP": "일본", "CN": "중국"}

PASS, WARN, FAIL, UNK = "통과", "주의", "탈락", "확인불가"


# ── 1차: 전 종목 필터 ─────────────────────────────────────────────────────────
def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"Accept-Encoding": "gzip", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def load_market(manifest, code, tries=3):
    """스냅샷이 다시 올라가는 중이면 옛 경로가 404 → 3분 쉬고 목록을 새로 받아 다시 시도"""
    for k in range(tries):
        try:
            return _load_market(manifest, code)
        except OSError as e:  # HTTPError·URLError·타임아웃 포함
            if k == tries - 1:
                raise
            print(f"  [{MARKET_NAME[code]}] 받기 실패({e}) → 3분 뒤 다시 ({k + 2}/{tries})", flush=True)
            time.sleep(180)
            manifest = fetch("manifest.json")


def _load_market(manifest, code):
    root, entry = manifest["data_root"], manifest["markets"][code]
    scan = fetch(root + entry["pages"]["scan"]["path"])
    rows = {r["symbol"]: r for r in scan.get("initial_rows", [])}
    for chunk in scan.get("chunks", []):
        for r in fetch(root + chunk["path"])["rows"]:
            rows[r["symbol"]] = r
    home = fetch(root + entry["pages"]["home"]["path"])
    return entry["as_of_date"], list(rows.values()), home.get("market_health_exposure") or {}


def between(v, lo=None, hi=None):
    if v is None:
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def funnel(rows, code):
    """트렌드 조건 → 위치·베이스·실적 순서로 거른다. 단계별 개수도 돌려준다."""
    trend = [r for r in rows if r.get("ma_alignment") is True and r.get("stage") == 2
             and between(r.get("week_52_low_distance"), 30) and between(r.get("week_52_high_distance"), None, 25)
             and between(r.get("rs_rating"), 80) and between(r.get("adv_usd"), ADV_MIN[code])]
    setup = [r for r in trend if r.get("rs_trend") == 1
             and between(r.get("se_distance_to_pivot_pct"), -8, 5)
             and between(r.get("se_base_length_weeks"), 3) and between(r.get("se_base_depth_pct"), None, 35)]
    # 중국은 eps_growth_yy가 비어 있어서 걸면 무조건 0개가 된다
    final = setup if code == "CN" else [r for r in setup if between(r.get("eps_growth_yy"), 25)]
    return trend, setup, final


# ── 2차: 일봉 검증 ────────────────────────────────────────────────────────────
def swings(high, low, threshold):
    """고점→저점 하락 구간을 왼쪽부터 찾는다. 마지막 하락이 진행 중이어도 포함한다."""
    legs, up, hi_i, lo_i = [], True, 0, 0
    for i in range(len(high)):
        if up:
            if high[i] >= high[hi_i]:
                hi_i = i
            elif low[i] <= high[hi_i] * (1 - threshold):
                up, lo_i = False, i
        else:
            if low[i] <= low[lo_i]:
                lo_i = i
            elif high[i] >= low[lo_i] * (1 + threshold):
                legs.append((hi_i, lo_i))
                up, hi_i = True, i
    if not up:
        legs.append((hi_i, lo_i))
    return legs


def contractions(high, low, min_drop=0.03):
    """책의 VCP 순서대로 잰다: 절대 고점→최저점, 그 뒤 고점→저점을 오른쪽 끝까지 반복."""
    legs, start = [], 0
    while start < len(high) - 2:
        peak = max(range(start, len(high)), key=lambda i: high[i])
        if peak >= len(high) - 1:
            break
        trough = min(range(peak + 1, len(low)), key=lambda i: low[i])
        if 1 - low[trough] / high[peak] < min_drop:
            break
        legs.append((peak, trough))
        start = trough + 1
    return legs


def yahoo_symbol(symbol):
    """코스닥 종목이 .KS로 올라온 경우 .KQ로 다시 찾는다."""
    if symbol.endswith(".KS") and yf.Ticker(symbol).history(period="5d").empty:
        return symbol[:-3] + ".KQ"
    return symbol


def technicals(row):
    """미리 계산된 값이 없는 책 기준을 일봉으로 직접 잰다."""
    t = {}
    tk = yf.Ticker(row["yahoo"])
    df = tk.history(period="2y")
    if len(df) < 210:
        return {"bars": len(df)}
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    ma50, ma150, ma200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    t["bars"] = len(df)
    t["last_bar"] = df.index[-1].strftime("%Y-%m-%d")

    last = c.iloc[-1]
    hi52, lo52 = h.tail(252).max(), l.tail(252).min()
    t["from_high_pct"] = round((1 - last / hi52) * 100, 1)
    t["from_low_pct"] = round((last / lo52 - 1) * 100, 1)
    t["template_ok"] = bool(last > ma50.iloc[-1] > ma150.iloc[-1] > ma200.iloc[-1]
                            and last >= lo52 * 1.3 and last >= hi52 * 0.75)

    rising = (ma200 > ma200.shift(5)).dropna()
    run = 0
    for flag in reversed(rising.tolist()):
        if not flag:
            break
        run += 1
    t["ma200_rising_days"] = run

    # 수축: 베이스 구간만 잰다. 이미 돌파했으면 돌파 전까지가 베이스다
    n = int((row.get("se_base_length_weeks") or 8) * 5) + 5
    end = len(df)
    pivot = row.get("se_pivot_price")
    if pivot and last > pivot:
        under = [i for i, x in enumerate(c.tolist()) if x < pivot]
        end = under[-1] + 1 if under else end
    wh, wl = h.iloc[:end].tail(n).tolist(), l.iloc[:end].tail(n).tolist()
    wv = v.iloc[:end].tail(n)
    legs = contractions(wh, wl)
    depths = [round((1 - wl[b] / wh[a]) * 100, 1) for a, b in legs]
    t["contractions"] = depths
    t["contraction_shrinking"] = len(depths) >= 2 and all(x > y for x, y in zip(depths, depths[1:]))
    if legs:
        a, b = legs[-1]
        avg50 = v.rolling(50).mean().iloc[-1]
        if avg50:
            t["last_leg_volume_vs_50d"] = round(float(wv.iloc[a:b + 1].mean() / avg50), 2)
    # 오닐: 베이스 전에 30% 이상 올랐어야 한다
    base_start = max(end - n, 1)
    prior = l.iloc[max(0, base_start - 120):base_start]
    if len(prior):
        t["prior_uptrend_pct"] = round((max(wh) / prior.min() - 1) * 100, 1)

    # 핸들: 스냅샷의 handle_high 날짜부터 그 뒤 최저점까지
    if row.get("se_pivot_type") == "handle_high" and pivot and row.get("se_pivot_date"):
        after = l.iloc[:end][df.index[:end].strftime("%Y-%m-%d") >= row["se_pivot_date"]]
        if len(after) and max(wh) > min(wl):
            t["handle_depth"] = round((1 - after.min() / pivot) * 100, 1)
            t["handle_position"] = round((after.min() - min(wl)) / (max(wh) - min(wl)), 2)

    # 베이스 횟수(근사): 200일선 위로 올라온 뒤 10% 이상 빠지고 3주 이상 걸린 조정
    below = c[c < ma200].index
    start = df.index.get_loc(below[-1]) + 1 if len(below) else 200
    sh, sl, sc = h.iloc[start:].tolist(), l.iloc[start:].tolist(), c.iloc[start:].tolist()
    count = 0
    for a, _ in swings(sh, sl, 0.10):
        recovered = next((i for i in range(a + 1, len(sc)) if sc[i] > sh[a]), len(sc))
        count += (recovered - a) >= 15
    t["base_count"] = count
    t["stage2_days"] = len(sc)

    try:
        shares = tk.balance_sheet.loc["Ordinary Shares Number"].dropna().sort_index()
        if len(shares) >= 2 and shares.iloc[-2]:
            t["shares_change_pct"] = round((shares.iloc[-1] / shares.iloc[-2] - 1) * 100, 1)
    except Exception:
        pass
    return t


# ── 1.5차: 스냅샷이 못 찾는 책의 패턴 ─────────────────────────────────────────
def power_play(df):
    """+100%를 8주 안에 하고, 25% 이내 조정으로 12일~6주 옆으로 가며, 최근이 10% 이내로 조인다."""
    if len(df) < 120:
        return None
    h, l, v = df["High"].tolist(), df["Low"].tolist(), df["Volume"].tolist()
    peak = max(range(len(h) - 45, len(h)), key=lambda i: h[i])
    days = len(h) - 1 - peak
    if not 12 <= days <= 30:
        return None
    run_low_i = min(range(peak - 40, peak), key=lambda i: l[i])
    gain = (h[peak] / l[run_low_i] - 1) * 100
    drop = (1 - min(l[peak:]) / h[peak]) * 100
    tight = (1 - min(l[-10:]) / max(h[-10:])) * 100
    before = sum(v[run_low_i - 50:run_low_i]) / 50 if run_low_i >= 50 else 0
    during = sum(v[run_low_i:peak + 1]) / (peak - run_low_i + 1)
    if gain < 100 or drop > 25 or tight > 10 or (before and during < before * 1.5):
        return None
    return {"pattern": "power_play", "pivot": max(h[-10:]),
            "note": f"8주 내 +{gain:.0f}%, 조정 {drop:.0f}%, {days}일 횡보, 최근 폭 {tight:.1f}%"}


def three_c(df):
    """앞선 상승 25% 이상, 15~50% 조정, 컵 중간 아래쪽에서 10% 이내로 조이고 거래량이 준다."""
    if len(df) < 260:
        return None
    h, l, v = df["High"].tolist(), df["Low"].tolist(), df["Volume"].tolist()
    peak = max(range(len(h) - 130, len(h) - 15), key=lambda i: h[i])
    if max(h[peak + 1:]) > h[peak]:
        return None
    trough = min(range(peak + 1, len(l)), key=lambda i: l[i])
    prior = (h[peak] / min(l[max(0, peak - 225):peak]) - 1) * 100
    depth = (1 - l[trough] / h[peak]) * 100
    position = (df["Close"].iloc[-1] - l[trough]) / (h[peak] - l[trough])
    tight = (1 - min(l[-7:]) / max(h[-7:])) * 100
    avg50 = sum(v[-50:]) / 50
    quiet = avg50 and sum(v[-7:]) / 7 < avg50
    if prior < 25 or not 15 <= depth <= 50 or len(l) - 1 - trough < 5 or not 0.2 <= position <= 0.75:
        return None
    if tight > 10 or not quiet:
        return None
    return {"pattern": "3c", "pivot": max(h[-7:]),
            "note": f"앞선 상승 +{prior:.0f}%, 조정 {depth:.0f}%, 컵 위치 {position:.2f}, 최근 폭 {tight:.1f}%"}


def pattern_scan(rows, exclude):
    """트렌드 통과 종목에서 3C·파워 플레이를 찾는다. 실적은 여기서 거르지 않고 뒤의 재무 판정에 맡긴다."""
    todo = [r for r in rows if r["symbol"] not in exclude]
    if not todo:
        return []
    data = yf.download([r["symbol"] for r in todo], period="2y", group_by="ticker", progress=False, threads=True)
    hits = []
    for r in todo:
        try:
            df = data[r["symbol"]].dropna(how="all")
        except KeyError:
            df = pd.DataFrame()
        yahoo = r["symbol"]
        if df.empty and yahoo.endswith(".KS"):
            yahoo = yahoo[:-3] + ".KQ"
            df = yf.Ticker(yahoo).history(period="2y")
        if df.empty:
            continue
        hit = power_play(df) or three_c(df)
        if not hit:
            continue
        last = float(df["Close"].iloc[-1])
        hits.append({**r, "yahoo": yahoo, "se_pattern_primary": hit["pattern"], "se_pivot_price": hit["pivot"],
                     "se_pivot_type": None, "se_distance_to_pivot_pct": (last / hit["pivot"] - 1) * 100,
                     "pattern_note": hit["note"]})
    return hits


# ── 3차: Code 33 (분기 7개 필요) ──────────────────────────────────────────────
def yoy_series(q):
    out = {}
    for d in sorted(q):
        prev = [x for x in q if 340 <= (d - x).days <= 390]
        if prev and q[prev[0]] and q[prev[0]] > 0:
            out[d] = (q[d] / q[prev[0]] - 1) * 100
    return out


def accelerating(values):
    return len(values) >= 3 and values[-3] < values[-2] < values[-1]


def code33(rev, profit):
    """최근 3분기 연속으로 이익·매출 YoY가 오르고 이익률도 오르는가."""
    ey, ry = yoy_series(profit), yoy_series(rev)
    margin = {d: profit[d] / rev[d] * 100 for d in sorted(rev) if d in profit and rev[d]}
    if len(ey) < 3 or len(ry) < 3 or len(margin) < 3:
        return {"available": False, "quarters": len(rev)}
    if any(abs(margin[d]) > 100 for d in sorted(margin)[-3:]):
        return {"available": False, "quarters": len(rev), "error": "이익률 100% 초과, 일회성 이익 의심"}
    e3 = [round(ey[d], 1) for d in sorted(ey)[-3:]]
    r3 = [round(ry[d], 1) for d in sorted(ry)[-3:]]
    m3 = [round(margin[d], 1) for d in sorted(margin)[-3:]]
    return {"available": True, "quarters": len(rev), "profit_yoy": e3, "sales_yoy": r3, "margin": m3,
            "pass": accelerating(e3) and accelerating(r3) and accelerating(m3),
            "latest": max(rev).strftime("%Y-%m")}


_corp = {}


def corp_code(symbol):
    from company_analysis import dart_get_corp_code
    key = symbol.split(".")[0]
    if key not in _corp:
        _corp[key] = dart_get_corp_code(key)[0]
    return _corp[key]


def dart_quarters(symbol):
    """분기 매출·순이익. 4분기는 사업보고서에서 1~3분기를 뺀다."""
    from company_analysis import DART_KEY
    corp = corp_code(symbol)
    if not corp:
        return None

    def pick(items, ids, names):
        for it in items:
            if it.get("sj_div") in ("IS", "CIS") and (it.get("account_id") in ids or it.get("account_nm", "").strip() in names):
                try:
                    return float(it["thstrm_amount"].replace(",", ""))
                except (KeyError, ValueError):
                    continue
        return None

    rev, ni = {}, {}
    this_year = datetime.now().year
    for year in range(this_year - 2, this_year + 1):
        got = {}
        for code, q in (("11013", 1), ("11012", 2), ("11014", 3), ("11011", 4)):
            items = []
            for fs in ("CFS", "OFS"):
                r = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                                 params={"crtfc_key": DART_KEY, "corp_code": corp, "bsns_year": year,
                                         "reprt_code": code, "fs_div": fs}, timeout=30).json()
                time.sleep(0.2)
                if r.get("status") == "000":
                    items = r.get("list", [])
                    break
            if items:
                got[q] = (pick(items, {"ifrs-full_Revenue"}, {"매출액", "수익(매출액)", "영업수익", "매출"}),
                          pick(items, {"ifrs-full_ProfitLoss"}, {"당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"}))
        for q in (1, 2, 3):
            if q in got and None not in got[q]:
                d = pd.Timestamp(year, q * 3, 28)
                rev[d], ni[d] = got[q]
        if all(q in got and None not in got[q] for q in (1, 2, 3, 4)):
            d = pd.Timestamp(year, 12, 28)
            rev[d] = got[4][0] - sum(got[q][0] for q in (1, 2, 3))
            ni[d] = got[4][1] - sum(got[q][1] for q in (1, 2, 3))
    return rev, ni


def sec_quarters(symbol):
    """SEC 공시의 분기 매출·순이익. 4분기는 연간에서 1~3분기를 뺀다."""
    filings = yf.Ticker(symbol).sec_filings
    if not filings:
        return None
    cik = int(filings[0]["edgarUrl"].rsplit("_", 1)[1])  # 공시 링크 끝이 회사 번호다
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                     headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        return None
    facts = r.json()
    gaap = facts.get("facts", {}).get("us-gaap", {})

    def series(tags):
        best = {}
        for tag in tags:
            q, annual = {}, {}
            for e in gaap.get(tag, {}).get("units", {}).get("USD", []):
                if "start" not in e:
                    continue
                s, d = pd.Timestamp(e["start"]), pd.Timestamp(e["end"])
                days = (d - s).days
                if 80 <= days <= 100:
                    q[d] = e["val"]
                elif 350 <= days <= 380:
                    annual[d] = e["val"]
            for d, val in annual.items():
                prior = [x for x in q if 0 < (d - x).days < 300]
                if d not in q and len(prior) == 3:
                    q[d] = val - sum(q[x] for x in prior)
            if q and (not best or max(q) > max(best)):
                best = q
        return best

    rev = series(["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"])
    return rev, series(["NetIncomeLoss", "ProfitLoss"])


def yahoo_quarters(symbol):
    """일본·중국과 미국 외국 기업용. 분기가 6~7개뿐이라 못 재는 종목이 많다."""
    q = yf.Ticker(symbol).get_income_stmt(freq="quarterly")
    out = []
    for names in (("TotalRevenue", "OperatingRevenue", "Total Revenue"), ("NetIncome", "Net Income")):
        name = next((n for n in names if n in q.index), None)
        out.append({} if name is None else {pd.Timestamp(d): float(x) for d, x in q.loc[name].dropna().items()})
    return out


def get_code33(code, symbol):
    result = {"available": False}
    try:
        data = dart_quarters(symbol) if code == "KR" else sec_quarters(symbol) if code == "US" else None
        if data:
            result = code33(*data)
        if not result.get("available") and not result.get("error"):
            result = code33(*yahoo_quarters(symbol))
    except Exception as e:
        result = {"available": False, "error": str(e)[:100]}
    return result


# ── 3차: 기관·수급·촉매 ───────────────────────────────────────────────────────
def institutions(symbol, history):
    """기관 수는 그날 값만 나오므로 저장해 두고 다음 실행 때 증감을 비교한다."""
    try:
        count = int(yf.Ticker(symbol).major_holders.loc["institutionsCount", "Value"])
    except Exception:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    past = {d: n for d, n in history.get(symbol, {}).items() if d != today}
    history.setdefault(symbol, {})[today] = count
    return {"count": count, "prev": past[max(past)] if past else None, "prev_date": max(past) if past else None}


def kr_flows(symbol):
    """한국투자증권 투자자별 매매동향(시세 조회 전용). 최근 20거래일 기관·외국인 순매수 주식 수 합계."""
    import kis_trader
    r = requests.get(f"{kis_trader.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor",
                     headers=kis_trader._headers("FHKST01010900"), timeout=20,
                     params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol.split(".")[0]})
    time.sleep(0.5)
    r.raise_for_status()
    rows = [x for x in r.json().get("output", []) if x.get("orgn_ntby_qty") not in (None, "")][:20]
    if not rows:
        return None
    return {"days": len(rows), "institution": sum(int(x["orgn_ntby_qty"]) for x in rows),
            "foreign": sum(int(x["frgn_ntby_qty"]) for x in rows)}


def catalysts(code, row):
    """기계적으로 모은 재료 후보다. 진짜 촉매인지는 사람이 판단한다."""
    out = []
    try:
        if code == "KR":
            from company_analysis import DART_KEY
            now = datetime.now()
            r = requests.get("https://opendart.fss.or.kr/api/list.json", timeout=20, params={
                "crtfc_key": DART_KEY, "corp_code": corp_code(row["yahoo"]), "page_count": 40,
                "bgn_de": (now - timedelta(days=45)).strftime("%Y%m%d"), "end_de": now.strftime("%Y%m%d")}).json()
            words = ("공급계약", "실적", "자기주식", "유상증자", "전환사채", "신규시설", "합병", "무상증자", "기업가치제고")
            seen = []
            for it in r.get("list", []):
                name = " ".join(it["report_nm"].split())
                if any(w in name for w in words) and name not in seen:
                    seen.append(name)
            out += [f"공시: {x}" for x in seen[:4]]
            out += [f"리포트: {x}" for x in research_titles(row.get("company_name", ""))]
        else:
            for n in (yf.Ticker(row["yahoo"]).news or [])[:3]:
                title = (n.get("content") or n).get("title")
                if title:
                    out.append(f"뉴스: {title}")
    except Exception:
        out.append("뉴스·공시 조회 실패")
    return out


_research = []


def research_titles(name):
    """내 PC에 모아 둔 증권사 리포트 중 최근 120일 제목."""
    if not _research:
        path = ROOT / "data" / "naver_research" / "_meta" / "manifest.json"
        if path.exists():
            m = json.loads(path.read_text(encoding="utf-8"))
            _research.extend(x for x in (m.get("reports") or m.values()) if isinstance(x, dict))
    limit = (datetime.now() - timedelta(days=120)).strftime("%y.%m.%d")
    found = [x for x in _research if f"\\{name}_" in str(x.get("path")) and str(x.get("date", "")) >= limit]
    found.sort(key=lambda x: x["date"], reverse=True)
    return [f"{x['date']} {x.get('firm')} {x.get('title')}" for x in found[:3]]


def fund_check(symbols):
    if not symbols:
        return {}
    subprocess.run([sys.executable, "book_fund_check.py", *symbols], cwd=ROOT, capture_output=True, timeout=1800)
    path = ROOT / "data" / "book_fund_check.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ── 판정 ──────────────────────────────────────────────────────────────────────
def chk(name, status, value=""):
    return {"name": name, "status": status, "value": value}


def judge(row, t, f, c33, extra):
    out = []
    if t.get("bars", 0) < 210:
        out.append(chk("일봉 검증", UNK, f"{t.get('bars', 0)}일치뿐"))
    else:
        out.append(chk("트렌드 템플릿(일봉 재계산)", PASS if t["template_ok"] else FAIL,
                       f"고점 -{t['from_high_pct']}%, 저점 +{t['from_low_pct']}%"))
        d = t["ma200_rising_days"]
        out.append(chk("200일선 상승 기간", PASS if d >= 85 else WARN if d >= 21 else FAIL, f"{d}거래일"))
        n = t["base_count"]
        out.append(chk("베이스 횟수(근사)", PASS if n <= 2 else WARN if n == 3 else FAIL, f"{n}번째"))

    if t.get("prior_uptrend_pct") is not None:
        x = t["prior_uptrend_pct"]
        out.append(chk("베이스 전 상승 30%", PASS if x >= 30 else FAIL, f"{x}%"))
    if row.get("correction_survivor"):
        out.append(chk("조정장 방어", PASS, "시장 조정에도 버팀"))
    rank = row.get("ibd_group_rank")
    if row.get("market") != "KR" and rank is not None:
        out.append(chk("업종 순위", PASS if rank <= 40 else WARN, f"{rank}위"))

    pattern = row.get("se_pattern_primary")
    depth, weeks = row.get("se_base_depth_pct"), row.get("se_base_length_weeks")
    if row.get("pattern_note"):
        out.append(chk(f"패턴 {pattern}", PASS, row["pattern_note"]))
    else:
        out.append(chk("베이스 길이", PASS if between(weeks, 5, 26) else WARN, f"{weeks}주 ({pattern})"))
    depths = t.get("contractions")
    if depths is not None and not row.get("pattern_note"):
        ok = 2 <= len(depths) <= 6 and t["contraction_shrinking"]
        if pattern == "vcp" or row.get("vcp_detected"):
            out.append(chk("VCP 수축(2~6회, 점점 작게)", PASS if ok else FAIL, str(depths)))
        else:
            out.append(chk("변동성 수축", PASS if ok else WARN, str(depths)))
    if t.get("last_leg_volume_vs_50d") is not None:
        x = t["last_leg_volume_vs_50d"]
        out.append(chk("마지막 수축 거래량", PASS if x < 1 else WARN, f"50일 평균의 {x}배"))
    if pattern == "cup_with_handle":
        pos, leg = t.get("handle_position"), t.get("handle_depth")
        if pos is None:
            out.append(chk("핸들 위치(상단 절반, 15% 이내)", UNK, "핸들 구간을 못 찾음"))
        else:
            good = pos >= 0.5 and leg <= 15
            out.append(chk("핸들 위치(상단 절반, 15% 이내)", PASS if good else FAIL, f"위치 {pos}, 깊이 {leg}%"))
        out.append(chk("컵 깊이·길이", PASS if between(depth, 15, 35) and between(weeks, 7) else WARN, f"{depth}%, {weeks}주"))

    dist = row.get("se_distance_to_pivot_pct")
    out.append(chk("피봇 위치(+5% 이내)", PASS if between(dist, None, 5) else FAIL, f"{round(dist, 1)}%"))
    if between(dist, 0):
        x = row.get("se_volume_vs_50d")
        out.append(chk("돌파일 거래량 +50%", PASS if between(x, 1.5) else WARN, f"{round(x, 2) if x else '?'}배"))
    out.append(chk("RS 라인 신고가", PASS if row.get("rs_line_new_high") else WARN, f"RS {row.get('rs_rating')}"))

    if f is None:
        return out
    if extra.get("inst"):
        i = extra["inst"]
        change = f", {i['prev_date']} {i['prev']}곳에서 {i['count'] - i['prev']:+d}" if i["prev"] is not None else ", 증감은 다음 실행부터"
        out.append(chk("기관 10곳 이상", PASS if i["count"] >= 10 else FAIL, f"{i['count']}곳{change}"))
        if i["prev"] is not None and i["count"] < i["prev"]:
            out.append(chk("기관 수 증가", WARN, f"{i['count'] - i['prev']:+d}곳"))
    else:
        out.append(chk("기관 10곳 이상", UNK))
    if extra.get("flows"):
        x = extra["flows"]
        net = x["institution"] + x["foreign"]
        out.append(chk(f"수급 {x['days']}일", PASS if net > 0 else WARN, f"기관 {x['institution']:+,}주, 외국인 {x['foreign']:+,}주"))
    elif "flows" in extra:
        out.append(chk("수급", UNK))
    ne = str(f.get("next_earnings") or "")[:10]
    today = datetime.now().strftime("%Y-%m-%d")
    if ne and today <= ne <= (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"):
        out.append(chk("실적 발표 임박", WARN, ne))
    if f.get("error") or not f.get("quarters"):
        out.append(chk("재무", UNK, f.get("error", "데이터 없음")))
        return out
    eps = list((f.get("eps_yoy") or {}).values())
    rev = list((f.get("rev_yoy") or {}).values())
    if eps:
        out.append(chk("분기 EPS +25%", PASS if eps[-1] >= 25 else WARN if eps[-1] >= 18 else FAIL, f"{eps[-1]}%"))
    else:
        out.append(chk("분기 EPS +25%", UNK))
    if rev:
        ok = rev[-1] >= 25 or (len(rev) >= 2 and rev[-1] > rev[-2])
        out.append(chk("매출 +25% 또는 가속", PASS if ok else FAIL, f"{rev[-1]}%"))
    else:
        out.append(chk("매출 +25% 또는 가속", UNK))
    roe = f.get("roe")
    out.append(chk("ROE 17%", UNK if roe is None else PASS if roe >= 17 else FAIL, f"{roe}%"))
    retail = "retail" in (row.get("gics_industry") or "").lower()
    pm = f.get("pretax_margin_fy")
    out.append(chk("세전이익률 18%", UNK if pm is None else PASS if pm >= 18 or retail else FAIL, f"{pm}%"))
    annual = list((f.get("annual_eps") or {}).values())
    if len(annual) >= 3:
        a = annual[-3:]
        out.append(chk("연 EPS 3년 성장", PASS if a[0] < a[1] < a[2] else FAIL, str(a)))
    else:
        out.append(chk("연 EPS 3년 성장", UNK, str(annual)))
    if c33.get("available"):
        out.append(chk("Code 33", PASS if c33["pass"] else FAIL,
                       f"이익 {c33['profit_yoy']} 매출 {c33['sales_yoy']} 이익률 {c33['margin']}"))
    else:
        out.append(chk("Code 33", UNK, c33.get("error", f"분기 {c33.get('quarters', 0)}개")))
    return out


FUNDAMENTAL = ("분기 EPS", "매출 +25%", "ROE", "세전이익률", "연 EPS", "Code 33")


def relax_for_power_play(checks):
    """책 p269: 파워 플레이는 현재 실적과 무관하게 본다. 재무 탈락을 주의로 낮춘다."""
    for c in checks:
        if c["status"] == FAIL and c["name"].startswith(FUNDAMENTAL):
            c["status"] = WARN
    return checks


def tally(checks):
    return {s: sum(c["status"] == s for c in checks) for s in (PASS, WARN, FAIL, UNK)}


# ── 실행 ──────────────────────────────────────────────────────────────────────
def market_trend(rows, trend, code, health):
    """시장 전체 흐름. 후보가 0개여도 항상 남긴다."""
    from collections import Counter
    key = "gics_industry" if code == "KR" else "ibd_industry_group"
    none = "업종 정보 없음"
    top = sorted(trend, key=lambda r: -(r.get("rs_rating") or 0))[:10]
    groups = sorted({(r["ibd_group_rank"], r.get("ibd_industry_group")) for r in rows if r.get("ibd_group_rank")})[:10]
    prev = None
    for f in sorted(OUT.glob("20*.json"), reverse=True):
        if f.stem >= datetime.now().strftime("%Y-%m-%d"):
            continue
        try:
            old = next((m for m in json.loads(f.read_text(encoding="utf-8")) if m["market"] == code), None)
        except Exception:
            old = None
        if old:
            prev = {"date": f.stem, "trend": old["funnel"]["트렌드"]}
            break
    return {"index_trend": health.get("trend"), "vix": health.get("vix"),
            "stage2_pct": round(sum(r.get("stage") == 2 for r in rows) / len(rows) * 100, 1),
            "aligned_pct": round(sum(r.get("ma_alignment") is True for r in rows) / len(rows) * 100, 1),
            "sectors": Counter(r.get("gics_sector") or none for r in trend).most_common(8),
            "industries": Counter(r.get(key) or r.get("gics_industry") or none for r in trend).most_common(10),
            "rs_top": [(r.get("company_name"), r["symbol"], r.get("rs_rating"), r.get(key) or none) for r in top],
            "group_rank_top": groups, "prev": prev}


def run_market(manifest, code, with_fund):
    print(f"  [{MARKET_NAME[code]}] 데이터 받는 중...", flush=True)
    as_of, rows, health = load_market(manifest, code)
    trend, setup, final = funnel(rows, code)
    print(f"  [{MARKET_NAME[code]}] {len(rows)} → 트렌드 {len(trend)} → 셋업 {len(setup)} → 실적 {len(final)}", flush=True)

    for r in final:
        r["yahoo"] = yahoo_symbol(r["symbol"])
    extra_hits = pattern_scan(trend, {r["symbol"] for r in final})
    print(f"  [{MARKET_NAME[code]}] 3C·파워 플레이 추가 {len(extra_hits)}", flush=True)
    final = final + extra_hits
    hist_path = OUT / "institution_history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else {}
    funds = fund_check([r["yahoo"] for r in final]) if with_fund else {}
    picks = []
    for r in sorted(final, key=lambda x: -x["rs_rating"]):
        try:
            t = technicals(r)
        except Exception as e:
            t = {"bars": 0, "error": str(e)[:100]}
        f = funds.get(r["yahoo"]) if with_fund else None
        c33 = get_code33(code, r["yahoo"]) if with_fund else {}
        extra = {}
        if with_fund:
            extra["inst"] = institutions(r["yahoo"], history)
            if code == "KR":
                try:
                    extra["flows"] = kr_flows(r["yahoo"])
                except Exception:
                    extra["flows"] = None
        checks = judge(r, t, f, c33, extra)
        if r.get("se_pattern_primary") == "power_play":
            checks = relax_for_power_play(checks)
        pivot = r.get("se_pivot_price")
        picks.append({"symbol": r["symbol"], "name": r.get("company_name"), "price": r.get("current_price"),
                      "pivot": pivot, "buy_limit": round(pivot * 1.05, 2) if pivot else None,
                      "stop": round(pivot * 0.925, 2) if pivot else None, "catalysts": catalysts(code, r) if with_fund else [],
                      "pivot_dist": r.get("se_distance_to_pivot_pct"),
                      "pattern": r.get("se_pattern_primary"), "rs": r.get("rs_rating"),
                      "industry": r.get("gics_industry"), "group_rank": r.get("ibd_group_rank"),
                      "next_earnings": (f or {}).get("next_earnings"), "inst_pct": (f or {}).get("inst"),
                      "shares_change_pct": t.get("shares_change_pct"), "last_bar": t.get("last_bar"), "checks": checks, "tally": tally(checks)})
        print(f"    {r['symbol']} {picks[-1]['tally']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=0), encoding="utf-8")
    picks.sort(key=lambda p: (p["tally"][FAIL], p["tally"][UNK], p["tally"][WARN]))
    return {"market": code, "as_of": as_of, "stance": health.get("stance"),
            "distribution_days": health.get("distribution_day_count"),
            "follow_through": health.get("follow_through_day"), "exposure": health.get("exposure_score"),
            "funnel": {"전체": len(rows), "트렌드": len(trend), "셋업": len(setup), "실적": len(final) - len(extra_hits),
                       "패턴추가": len(extra_hits)},
            "trend_summary": market_trend(rows, trend, code, health), "picks": picks}


STALE_DAYS = 3  # 미국은 장 마감이 늦어 하루 늦는 게 정상, 사흘 이상이면 멈춘 것


def stale_note(m):
    d = m.get("stale_days", 0)
    return f"⚠ 원본 데이터 {d}일째 갱신 없음 — 아래는 {m['as_of']} 시점 그대로" if d >= STALE_DAYS else ""


def to_markdown(results):
    lines = [f"# 정밀 스크리너 결과 ({datetime.now():%Y-%m-%d})", ""]
    for m in results:
        f = m["funnel"]
        lines += [f"## {MARKET_NAME[m['market']]} (기준일 {m['as_of']})", "",
                  *([f"> {stale_note(m)}", ""] if stale_note(m) else []),
                  f"- 시장: {m['stance']}, 분산일 {m['distribution_days']}, 팔로스루 {m['follow_through']}, 노출 점수 {m['exposure']}",
                  f"- 깔때기: 전체 {f['전체']} → 트렌드 {f['트렌드']} → 셋업 {f['셋업']} → 실적 {f['실적']}, 3C·파워 플레이 추가 {f['패턴추가']}", ""]
        ts = m["trend_summary"]
        prev = f", {ts['prev']['date']} {ts['prev']['trend']}개에서 {f['트렌드'] - ts['prev']['trend']:+d}" if ts["prev"] else ", 비교할 지난 결과 없음"
        lines += ["### 시장 트렌드", "",
                  f"- 지수 추세 {ts['index_trend']}, VIX {ts['vix'] if ts['vix'] is not None else '없음'}",
                  f"- 2단계 종목 {ts['stage2_pct']}%, 이평선 정배열 {ts['aligned_pct']}%",
                  f"- 트렌드 통과 {f['트렌드']}개{prev}",
                  "- 트렌드 통과 섹터: " + (", ".join(f"{k} {v}" for k, v in ts["sectors"]) or "없음"),
                  "- 트렌드 통과 업종: " + (", ".join(f"{k} {v}" for k, v in ts["industries"]) or "없음"),
                  "- 업종 순위 상위: " + (", ".join(f"{r}위 {g}" for r, g in ts["group_rank_top"]) or "없음"),
                  "- RS 상위: " + (", ".join(f"{n}({s}) RS {r}, {g}" for n, s, r, g in ts["rs_top"]) or "없음"), ""]
        clean = [p["name"] for p in m["picks"] if p["tally"][FAIL] == 0]
        added = [p["name"] for p in m["picks"] if p["pattern"] in ("3c", "power_play")]
        lines += [f"- 탈락 0개 종목: {', '.join(clean) or '없음'}",
                  f"- 3C·파워 플레이로 추가된 종목: {', '.join(added) or '없음'}", ""]
        if not m["picks"]:
            lines += ["후보 종목 없음", ""]
        for p in m["picks"]:
            t = p["tally"]
            lines.append(f"### {p['name']} ({p['symbol']}) 탈락 {t[FAIL]} / 주의 {t[WARN]} / 확인불가 {t[UNK]} / 통과 {t[PASS]}")
            lines.append(f"피봇 {p['pivot']}, 현재가 {p['price']}, 패턴 {p['pattern']}, RS {p['rs']}, 업종 {p['industry']}, "
                         f"일봉 기준일 {p['last_bar']}, 다음 실적 {p['next_earnings']}, 기관 {p['inst_pct']}%, 주식 수 변화 {p['shares_change_pct']}%")
            lines.append(f"매수 상한(피봇 +5%) {p['buy_limit']}, 손절 참고(피봇 -7.5%) {p['stop']}")
            lines += [f"- {c['status']}: {c['name']} {c['value']}" for c in p["checks"]]
            lines += [f"- 재료 후보: {x}" for x in p["catalysts"]] or ["- 재료 후보: 없음"]
            lines.append("")
    return "\n".join(lines)


def main():
    args = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    codes = args or ["KR", "US", "JP", "CN"]
    with_fund = "--no-fund" not in sys.argv
    manifest = fetch("manifest.json")
    results = [run_market(manifest, c, with_fund) for c in codes]
    newest = datetime.fromisoformat(manifest["as_of_date"])
    for m in results:  # 원본 스냅샷이 시장별로 멈추는 일이 있음(2026-11 중국 11-17 동결) → 숨기지 말고 표시
        m["stale_days"] = (newest - datetime.fromisoformat(m["as_of"])).days
        if m["stale_days"] >= STALE_DAYS:
            print(f"::warning::{MARKET_NAME[m['market']]} 원본 데이터 {m['as_of']} 이후 갱신 없음 ({m['stale_days']}일 뒤처짐)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / datetime.now().strftime("%Y-%m-%d")
    stem.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    stem.with_suffix(".md").write_text(to_markdown(results), encoding="utf-8")
    print(f"  [완료] {stem}.md")
    if "--summary" in sys.argv:
        (OUT / "latest_summary.txt").write_text(telegram_summary(results), encoding="utf-8")
        (OUT / "latest.md").write_text(to_markdown(results), encoding="utf-8")
    if "--telegram" in sys.argv:
        send_telegram(results, stem.with_suffix(".md"))


def telegram_summary(results):
    lines = [f"📈 정밀 스크리너 {datetime.now():%m/%d}"]
    for m in results:
        f = m["funnel"]
        lines.append(f"\n[{MARKET_NAME[m['market']]}] 기준일 {m['as_of']} · {m['stance']}")
        if stale_note(m):
            lines.append(stale_note(m))
        lines.append(f"트렌드 {f['트렌드']} → 셋업 {f['셋업']} → 실적 {f['실적']}")
        picks = sorted(m["picks"], key=lambda p: (p["tally"][FAIL], p["tally"][WARN]))[:5]
        if not picks:
            lines.append("후보 없음")
        for p in picks:
            t = p["tally"]
            num = lambda v: f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, (int, float)) else v
            lines.append(f"· {p['name']} ({p['symbol']}) RS {num(p['rs'])} · 탈락{t[FAIL]}/주의{t[WARN]} · 피봇 {num(p['pivot'])} 현재 {num(p['price'])}")
    return "\n".join(lines)[:4000]


def send_telegram(results, md_path):
    import os
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("  [텔레그램] 토큰 없음, 건너뜀")
        return
    api = f"https://api.telegram.org/bot{token}"
    r1 = requests.post(f"{api}/sendMessage", data={"chat_id": chat, "text": telegram_summary(results)}, timeout=30)
    with open(md_path, "rb") as fh:
        r2 = requests.post(f"{api}/sendDocument", data={"chat_id": chat, "caption": "정밀 스크리너 전체 결과"},
                           files={"document": (md_path.name, fh, "text/markdown")}, timeout=60)
    print(f"  [텔레그램] 요약 {r1.status_code}, 파일 {r2.status_code}")


if __name__ == "__main__":
    main()
