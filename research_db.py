"""
네이버 증권 리포트 목록(manifest.json) → SQLite(data/research.db) 변환·검색

원본은 계속 manifest.json이다 (내려받기 스크립트와 GitHub Actions가 거기에 쓴다).
research.db는 언제든 다시 만들 수 있는 검색용 사본이라 저장소에 올리지 않는다 (.gitignore).

  python research_db.py build                       # manifest → research.db 새로 만들기
  python research_db.py q SK하이닉스                 # 제목·회사·업종·증권사 검색 (최근 순)
  python research_db.py q HBM --days 30 --cat company --firm 유안타 -n 50
  python research_db.py stats                       # 분류·증권사·월별 개수
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
META = ROOT / "data" / "naver_research" / "_meta"
MANIFEST = META / "manifest.json"
AI_NOTES = META / "ai_notes_status.json"
DB = ROOT / "data" / "research.db"

COLS = ["key", "category", "date", "company", "company_code", "sector", "firm", "title",
        "saved", "skipped_reason", "page_count", "path", "pdf_url", "detail_url", "checked_at",
        "note_status", "note_path", "raw"]


def norm_date(s):
    """'26.05.08' / '2026-05-08' / '2026.05.08' → '2026-05-08'"""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2}|\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def build():
    print("  [읽기] manifest.json...", flush=True)
    man = json.load(open(MANIFEST, encoding="utf-8"))
    notes = json.load(open(AI_NOTES, encoding="utf-8")) if AI_NOTES.exists() else {}

    rows, bad_date = [], 0
    for key, v in man.items():
        if not isinstance(v, dict):
            v = {"value": v}
        d = norm_date(v.get("date"))
        bad_date += not d
        n = notes.get(key) or {}
        rows.append((
            key, key.split(":", 1)[0], d, v.get("company", ""), v.get("company_code", ""),
            v.get("sector", ""), v.get("firm", ""), v.get("title", ""),
            1 if v.get("saved") else 0, v.get("skipped_reason", ""), v.get("page_count"),
            v.get("path", ""), v.get("pdf_url", ""), v.get("detail_url", ""), v.get("checked_at", ""),
            n.get("status", ""), n.get("path", ""), json.dumps(v, ensure_ascii=False),
        ))

    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE reports (
            key TEXT PRIMARY KEY, category TEXT, date TEXT, company TEXT, company_code TEXT,
            sector TEXT, firm TEXT, title TEXT, saved INTEGER, skipped_reason TEXT,
            page_count INTEGER, path TEXT, pdf_url TEXT, detail_url TEXT, checked_at TEXT,
            note_status TEXT, note_path TEXT, raw TEXT);
        CREATE INDEX ix_date ON reports(date);
        CREATE INDEX ix_company ON reports(company);
        CREATE INDEX ix_code ON reports(company_code);
        CREATE INDEX ix_firm ON reports(firm);
        CREATE INDEX ix_cat ON reports(category, date);
        CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    con.executemany(f"INSERT INTO reports VALUES ({','.join('?' * len(COLS))})", rows)
    # 한글은 낱말 경계가 애매해서 FTS 대신 LIKE 검색을 쓴다 (1만여 건이라 충분히 빠름)
    con.execute("INSERT INTO meta VALUES ('built_from', ?)", (str(MANIFEST),))
    con.execute("INSERT INTO meta VALUES ('rows', ?)", (str(len(rows)),))
    con.commit()

    # 원본과 개수 맞추기
    n_db = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    n_saved = con.execute("SELECT COUNT(*) FROM reports WHERE saved=1").fetchone()[0]
    con.close()
    m_saved = sum(1 for v in man.values() if isinstance(v, dict) and v.get("saved"))
    assert n_db == len(man), f"개수 불일치: manifest {len(man)} / db {n_db}"
    assert n_saved == m_saved, f"저장 건수 불일치: manifest {m_saved} / db {n_saved}"
    tmp.replace(DB)
    print(f"  [완료] {DB}  {n_db:,}건 (PDF 저장 {n_saved:,}, 건너뜀 {n_db - n_saved:,}, 날짜 못 읽음 {bad_date})")


def ensure_fresh():
    if not DB.exists() or DB.stat().st_mtime < MANIFEST.stat().st_mtime:
        build()


def query(a):
    ensure_fresh()
    con = sqlite3.connect(DB)
    w, p = [], []
    for t in a.words:
        w.append("(title LIKE ? OR company LIKE ? OR sector LIKE ? OR firm LIKE ? OR company_code = ?)")
        p += [f"%{t}%"] * 4 + [t]
    if a.days:
        w.append("date >= ?"); p.append((date.today() - timedelta(days=a.days)).isoformat())
    if a.cat:
        w.append("category = ?"); p.append(a.cat)
    if a.firm:
        w.append("firm LIKE ?"); p.append(f"%{a.firm}%")
    if a.saved:
        w.append("saved = 1")
    sql = ("SELECT date, category, company, firm, title, page_count, path FROM reports"
           + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY date DESC, key LIMIT ?")
    rows = con.execute(sql, p + [a.n]).fetchall()
    total = con.execute("SELECT COUNT(*) FROM reports" + (" WHERE " + " AND ".join(w) if w else ""), p).fetchone()[0]
    for d, c, co, f, t, pc, path in rows:
        print(f"{d} [{c}] {co or '-'} | {f} | {t} ({pc or '?'}쪽)" + (f"\n    {path}" if a.path and path else ""))
    print(f"  [결과] {total:,}건 중 {len(rows)}건 표시")


def stats(_):
    ensure_fresh()
    con = sqlite3.connect(DB)
    q = lambda s: con.execute(s).fetchall()
    print("분류:", ", ".join(f"{c} {n:,}" for c, n in q("SELECT category, COUNT(*) FROM reports GROUP BY 1 ORDER BY 2 DESC")))
    print("증권사 상위:", ", ".join(f"{f} {n:,}" for f, n in q("SELECT firm, COUNT(*) FROM reports GROUP BY 1 ORDER BY 2 DESC LIMIT 12")))
    print("월별:", ", ".join(f"{m} {n:,}" for m, n in q("SELECT substr(date,1,7), COUNT(*) FROM reports WHERE date<>'' GROUP BY 1 ORDER BY 1 DESC LIMIT 8")))
    print("AI 노트:", ", ".join(f"{s or '없음'} {n:,}" for s, n in q("SELECT note_status, COUNT(*) FROM reports GROUP BY 1 ORDER BY 2 DESC")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="네이버 리포트 목록 SQLite")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=lambda a: build())
    s = sub.add_parser("q"); s.add_argument("words", nargs="*")
    s.add_argument("--days", type=int); s.add_argument("--cat", choices=["company", "industry", "invest", "economy", "bond"])
    s.add_argument("--firm"); s.add_argument("--saved", action="store_true"); s.add_argument("--path", action="store_true")
    s.add_argument("-n", type=int, default=20); s.set_defaults(fn=query)
    sub.add_parser("stats").set_defaults(fn=stats)
    a = ap.parse_args(); a.fn(a)
