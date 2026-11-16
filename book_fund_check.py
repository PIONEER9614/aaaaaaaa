"""스크리너 최종 후보의 재무 점검 (미너비니·오닐 기준)
사용: python book_fund_check.py MSFT 7550.T 017890.KQ
결과: data/book_fund_check.json
"""
import sys, json, time, warnings
warnings.filterwarnings("ignore")
import yfinance as yf, pandas as pd
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
T = {"ARGS": sys.argv[1:]}
def row(df, names):
    for n in names:
        if n in df.index: return df.loc[n].dropna().sort_index()
    return pd.Series(dtype=float)
def yoy(s):
    out = {}
    for d, v in s.items():
        prev = [x for x in s.index if 340 <= (d - x).days <= 390]
        if prev and s[prev[0]] and s[prev[0]] > 0:
            out[d.strftime("%y-%m")] = round((v / s[prev[0]] - 1) * 100, 1)
    return out
res = {}
for m, ts in T.items():
    for t in ts:
        r = {"market": m}
        try:
            k = yf.Ticker(t); q = k.quarterly_income_stmt; a = k.income_stmt
            info = k.info or {}
            rev = row(q, ["Total Revenue", "Operating Revenue"]); ni = row(q, ["Net Income", "Net Income Common Stockholders"])
            eps = row(q, ["Diluted EPS", "Basic EPS"])
            r["quarters"] = len(rev)
            r["rev_yoy"] = yoy(rev); r["eps_yoy"] = yoy(eps if len(eps) else ni)
            mg = (ni / rev * 100).dropna().round(1) if len(rev) else pd.Series(dtype=float)
            r["net_margin"] = {d.strftime("%y-%m"): v for d, v in mg.tail(5).items()}
            ae = row(a, ["Diluted EPS", "Basic EPS"]); r["annual_eps"] = {d.strftime("%Y"): round(float(v), 2) for d, v in ae.tail(4).items()}
            ap = row(a, ["Pretax Income"]); ar = row(a, ["Total Revenue", "Operating Revenue"])
            if len(ap) and len(ar): r["pretax_margin_fy"] = round(float(ap.iloc[-1] / ar.iloc[-1] * 100), 1)
            for key, f in [("roe","returnOnEquity"),("inst","heldPercentInstitutions"),("insider","heldPercentInsiders")]:
                v = info.get(f); r[key] = round(v * 100, 1) if isinstance(v, (int, float)) else None
            r["debt_equity"] = info.get("debtToEquity"); r["float_m"] = round(info["floatShares"]/1e6, 1) if info.get("floatShares") else None
            r["analysts"] = info.get("numberOfAnalystOpinions")
            try:
                eh = k.earnings_history
                if eh is not None and len(eh): r["surprise_pct"] = [round(float(x) * 100, 1) for x in eh["surprisePercent"].dropna().tail(4)]
            except Exception: pass
            try:
                ee = k.earnings_estimate
                if ee is not None and len(ee): r["est_growth"] = {i: round(float(v) * 100, 1) for i, v in ee["growth"].dropna().items()}
            except Exception: pass
            try:
                ed = k.calendar.get("Earnings Date") if isinstance(k.calendar, dict) else None
                if ed: r["next_earnings"] = str(ed[0])
            except Exception: pass
        except Exception as e:
            r["error"] = str(e)[:120]
        res[t] = r; print(" ", t, "ok" if "error" not in r else r["error"], flush=True); time.sleep(0.6)
json.dump(res, open("data/book_fund_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
