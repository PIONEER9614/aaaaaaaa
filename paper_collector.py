"""
개념사 / 지성사 오픈액세스 논문 자동 수집기 v5
- Semantic Scholar: 학술지별 타겟 쿼리 + OA PDF 필터링
- CORE API: 오픈액세스 학술지 기사 수집
- 학술지별 폴더 + 저자_제목_학술지_권호_연도 파일명
"""

import os, re, json, time, requests, sys, urllib3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

CORE_KEY  = os.getenv("CORE_API_KEY", "DtGby7HTXo1LdxzenWusjfFJg9N2mrVk")
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID   = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

DOWNLOAD_DIR = Path("papers")
HISTORY_FILE = Path("paper_history.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PaperBot/1.0)"}

TARGET_JOURNALS = [
    {"name": "Contributions to the History of Concepts", "folder": "01_Contributions to the History of Concepts", "issn": "1807-9326", "eissn": "1874-656X"},
    {"name": "History of European Ideas",                "folder": "02_History of European Ideas",                "issn": "0191-6599", "eissn": "1873-541X"},
    {"name": "Journal of the History of Ideas",          "folder": "03_Journal of the History of Ideas",          "issn": "0022-5037", "eissn": "1086-3222"},
    {"name": "Intellectual History Review",              "folder": "04_Intellectual History Review",              "issn": "1749-4621", "eissn": "1749-463X"},
    {"name": "History and Theory",                       "folder": "05_History and Theory",                       "issn": "0018-2656", "eissn": "1468-2303"},
    {"name": "Modern Intellectual History",              "folder": "06_Modern Intellectual History",              "issn": "1479-2443", "eissn": "1479-2451"},
    {"name": "Rethinking History",                       "folder": "07_Rethinking History",                       "issn": "1364-2529", "eissn": "1470-1154"},
    {"name": "Gaenyeom-gwa Sotong",                     "folder": "08_Gaenyeom-gwa Sotong",                      "issn": "2092-7649", "eissn": ""},
]

# Semantic Scholar: 학술지명 포함 타겟 쿼리
S2_QUERIES = [
    # 일반 방법론 쿼리
    ("general", "Begriffsgeschichte conceptual history Koselleck"),
    ("general", "Cambridge school intellectual history Skinner Pocock"),
    ("general", "Sattelzeit historical semantics modernity"),
    # 학술지명 직접 타겟 쿼리
    ("01_Contributions to the History of Concepts", "Contributions History Concepts Begriffsgeschichte"),
    ("02_History of European Ideas",                "History of European Ideas intellectual political"),
    ("03_Journal of the History of Ideas",          "Journal History Ideas intellectual thought"),
    ("04_Intellectual History Review",              "Intellectual History Review Cambridge"),
    ("05_History and Theory",                       "History and Theory historiography methodology"),
    ("06_Modern Intellectual History",              "Modern Intellectual History nineteenth twentieth century"),
    ("07_Rethinking History",                       "Rethinking History theory practice"),
]

# ── 이력 관리 ─────────────────────────────────────────────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"downloaded": []}

def save_history(h):
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 파일명 생성 ───────────────────────────────────────────────────────────────
def sanitize(name):
    return re.sub(r'[\\/:*?"<>|]', "_", str(name or "")).strip("_")[:80]

def make_filename(title, authors, journal, volume, issue, year):
    author  = sanitize(authors[0].split(",")[0]) if authors else "unknown"
    title_s = sanitize(title)
    jour_s  = sanitize(journal)
    vol_s   = f"v{sanitize(str(volume))}" if volume else ""
    iss_s   = f"n{sanitize(str(issue))}"  if issue  else ""
    year_s  = str(year) if year else "unknown"
    parts   = [author, title_s, jour_s, "_".join(filter(None, [vol_s, iss_s])), year_s]
    name    = "_".join(p for p in parts if p) + ".pdf"
    return name[:200]

# ── PDF 다운로드 ──────────────────────────────────────────────────────────────
def download_pdf(url, title, authors, journal_name, folder, volume="", issue="", year=""):
    for verify in (True, False):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, stream=True,
                             verify=verify, allow_redirects=True)
            ct = r.headers.get("Content-Type", "")
            if not r.ok or "pdf" not in ct.lower():
                return False
            target_dir = DOWNLOAD_DIR / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = make_filename(title, authors, journal_name, volume, issue, year)
            path = target_dir / filename
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            print(f"  [저장] {folder}/{filename[:65]}")
            return str(path)
        except requests.exceptions.SSLError:
            if verify:
                continue
            return False
        except Exception as e:
            print(f"  [실패] {e}")
            return False
    return False

# ── Semantic Scholar ──────────────────────────────────────────────────────────
def search_semantic(query, limit=25):
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query, "limit": limit,
        "fields": "title,authors,year,journal,openAccessPdf,externalIds",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.ok:
            return [p for p in r.json().get("data", []) if p.get("openAccessPdf")]
    except Exception as e:
        print(f"  [S2 오류] {e}")
    return []

def match_journal(journal_name_or_issn):
    """학술지명 또는 ISSN으로 타겟 학술지 매칭"""
    if not journal_name_or_issn:
        return None
    q = journal_name_or_issn.lower()
    for j in TARGET_JOURNALS:
        eissn = j.get("eissn", "")
        if (j["name"].lower() in q or q in j["name"].lower()
                or j["issn"] in q or (eissn and eissn in q)):
            return j
    return None

# ── CORE API ──────────────────────────────────────────────────────────────────
def search_core_journal(journal_name, page_size=30, offset=0):
    """CORE API: 학술지명으로 OA 논문 검색"""
    url = "https://api.core.ac.uk/v3/search/works"
    headers = {**HEADERS, "Authorization": f"Bearer {CORE_KEY}"}
    params = {
        "q": f'journals.title:"{journal_name}"',
        "limit": page_size,
        "offset": offset,
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.ok:
            data = r.json()
            total = data.get("totalHits", 0)
            results = data.get("results", [])
            print(f"    CORE: 총 {total}편 (이번 {len(results)}편)")
            return results, total
        print(f"  [CORE {r.status_code}] {r.text[:120]}")
    except Exception as e:
        print(f"  [CORE 오류] {e}")
    return [], 0

# ── 텔레그램 ─────────────────────────────────────────────────────────────────
def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text[:4000], "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    history = load_history()
    downloaded = set(history["downloaded"])
    new_papers = []

    print(f"=== 논문 수집 v5: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"기존 수집: {len(downloaded)}편\n")

    # ── 1) CORE API: 학술지명 기반 수집 ──
    print("[CORE API 수집]")
    for journal in TARGET_JOURNALS:
        print(f"  {journal['name']}")
        results, _ = search_core_journal(journal["name"], page_size=50)
        saved_count = 0
        for item in results:
            pid     = str(item.get("id", ""))
            core_id = f"core:{pid}"
            if core_id in downloaded:
                continue
            title   = item.get("title", "")
            authors = [a.get("name", "") for a in item.get("authors", [])]
            year    = item.get("yearPublished", "")
            pdf_url = item.get("downloadUrl", "")
            if not pdf_url:
                for lk in item.get("links", []):
                    if lk.get("type") in ("download", "pdf"):
                        pdf_url = lk.get("url", "")
                        break
            if not pdf_url or not title:
                continue

            volume = ""
            issue  = ""
            for jinfo in item.get("journals", []):
                volume = str(jinfo.get("volume", "") or "") or volume
                issue  = str(jinfo.get("issue",  "") or "") or issue

            print(f"  -> {title[:70]}")
            path = download_pdf(pdf_url, title, authors, journal["name"],
                                journal["folder"], volume, issue, year)
            if path:
                downloaded.add(core_id)
                new_papers.append({"title": title, "journal": journal["name"], "year": year})
                saved_count += 1
            time.sleep(0.5)
        print(f"    → {saved_count}편 저장")
        time.sleep(1)

    # ── 2) Semantic Scholar: 타겟 학술지 OA 논문 ──
    print("\n[Semantic Scholar 수집]")
    for folder_hint, query in S2_QUERIES:
        print(f"  쿼리: {query[:60]}")
        results = search_semantic(query, limit=25)
        for paper in results:
            pid = paper.get("paperId", "")
            s2_id = f"s2:{pid}"
            if s2_id in downloaded:
                continue
            title   = paper.get("title", "")
            authors = [a["name"] for a in paper.get("authors", [])]
            year    = paper.get("year", "")
            pdf_url = paper.get("openAccessPdf", {}).get("url", "")
            jinfo   = paper.get("journal") or {}
            jname   = jinfo.get("name", "")
            volume  = jinfo.get("volume", "")
            issue   = jinfo.get("pages", "")

            if not pdf_url or not title:
                continue

            matched = match_journal(jname)
            if not matched:
                # folder_hint가 일반 쿼리("general")이면 건너뜀
                if folder_hint == "general":
                    continue
                # folder_hint가 특정 학술지이면 해당 학술지로 분류
                matched = next((j for j in TARGET_JOURNALS if j["folder"] == folder_hint), None)
                if not matched:
                    continue

            print(f"  -> [{matched['folder']}] {title[:55]}")
            path = download_pdf(pdf_url, title, authors, matched["name"],
                                matched["folder"], volume, issue, year)
            if path:
                downloaded.add(s2_id)
                new_papers.append({"title": title, "journal": matched["name"], "year": year})
            time.sleep(0.5)
        time.sleep(2)

    # ── 결과 저장 ──
    history["downloaded"] = list(downloaded)
    history["last_run"]   = datetime.now().isoformat()
    save_history(history)

    print(f"\n=== 완료: 신규 {len(new_papers)}편 ===")
    for p in new_papers:
        print(f"  [{p['year']}] {p['journal']} / {p['title'][:60]}")

    if new_papers and BOT_TOKEN:
        lines = [f"📚 <b>새 논문 {len(new_papers)}편 수집</b>\n"]
        for p in new_papers[:15]:
            lines.append(f"• [{p['year']}] {p['journal']}\n  {p['title'][:55]}")
        send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
