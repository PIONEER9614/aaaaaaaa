"""
개념사 / 지성사 논문 자동 수집기 v6
- CrossRef API: ISSN으로 해당 연도 전체 논문 목록 수집
- Unpaywall API: DOI로 OA PDF URL 확인
- CORE API: 보완 수집
- 학술지별 폴더 + 저자_제목_학술지_권호_연도 파일명
"""

import os, re, json, time, requests, sys, urllib3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv()

CORE_KEY      = os.getenv("CORE_API_KEY", "DtGby7HTXo1LdxzenWusjfFJg9N2mrVk")
BOT_TOKEN     = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID       = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
UNPAYWALL_EMAIL = "ninzago9614@gmail.com"

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

# ── 이력 관리 ─────────────────────────────────────────────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"downloaded": []}

def save_history(h):
    HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 파일명 생성 ───────────────────────────────────────────────────────────────
def sanitize(name):
    return re.sub(r'[\\/:*?"<>|\n\r\t]', "_", str(name or "")).strip("_. ")[:80]

def make_filename(title, authors, journal, volume, issue, year):
    author  = sanitize(authors[0].split(",")[0]) if authors else "unknown"
    title_s = sanitize(title)
    jour_s  = sanitize(journal)
    vol_s   = f"v{sanitize(str(volume))}" if volume else ""
    iss_s   = f"n{sanitize(str(issue))}"  if issue  else ""
    year_s  = str(year) if year else "unknown"
    parts   = [author, title_s, jour_s, "_".join(filter(None, [vol_s, iss_s])), year_s]
    return ("_".join(p for p in parts if p) + ".pdf")[:200]

# ── PDF 다운로드 ──────────────────────────────────────────────────────────────
def download_pdf(url, title, authors, journal_name, folder, volume="", issue="", year=""):
    for verify in (True, False):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40, stream=True,
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
            print(f"    [저장] {filename[:70]}")
            return str(path)
        except requests.exceptions.SSLError:
            if verify:
                continue
            return False
        except Exception as e:
            print(f"    [실패] {e.__class__.__name__}: {str(e)[:60]}")
            return False
    return False

# ── CrossRef API: 학술지 전체 논문 목록 ──────────────────────────────────────
def crossref_get_works(issn, year, offset=0, rows=100):
    """CrossRef works 엔드포인트로 ISSN + 연도 필터 검색"""
    url = "https://api.crossref.org/works"
    params = {
        "filter": f"issn:{issn},from-pub-date:{year}-01-01,until-pub-date:{year}-12-31",
        "rows": rows,
        "offset": offset,
        "select": "DOI,title,author,published,volume,issue,container-title",
        "mailto": UNPAYWALL_EMAIL,
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.ok:
            data = r.json().get("message", {})
            items = data.get("items", [])
            total = data.get("total-results", 0)
            return items, total
        print(f"    [CrossRef {r.status_code}]")
    except Exception as e:
        print(f"    [CrossRef 오류] {e.__class__.__name__}")
    return [], 0

def crossref_all_works(issn, year):
    """페이지네이션으로 전체 목록 수집"""
    all_items, total = crossref_get_works(issn, year, offset=0)
    print(f"    CrossRef ({issn}): 총 {total}편")
    offset = 100
    while offset < total:
        items, _ = crossref_get_works(issn, year, offset=offset)
        if not items:
            break
        all_items.extend(items)
        offset += 100
        time.sleep(0.5)
    return all_items

# ── Unpaywall API: DOI → OA PDF URL ──────────────────────────────────────────
def unpaywall_get_pdf(doi):
    """DOI로 Unpaywall에서 OA PDF URL 반환. 없으면 None."""
    url = f"https://api.unpaywall.org/v2/{requests.utils.quote(doi, safe='')}"
    try:
        r = requests.get(url, params={"email": UNPAYWALL_EMAIL}, headers=HEADERS, timeout=15)
        if not r.ok:
            return None
        data = r.json()
        if not data.get("is_oa"):
            return None
        # best_oa_location 우선, 없으면 첫 번째 oa_location
        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf") or best.get("url")
        if not pdf_url:
            for loc in data.get("oa_locations", []):
                pdf_url = loc.get("url_for_pdf") or loc.get("url")
                if pdf_url:
                    break
        return pdf_url or None
    except Exception:
        return None

# ── CORE API: 보완 수집 ───────────────────────────────────────────────────────
def core_get_works(journal_name, year=None, page_size=100, offset=0):
    url = "https://api.core.ac.uk/v3/search/works"
    hdrs = {**HEADERS, "Authorization": f"Bearer {CORE_KEY}"}
    q = f'journals.title:"{journal_name}"'
    if year:
        q += f" AND yearPublished:{year}"
    params = {"q": q, "limit": page_size, "offset": offset}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=25)
            if r.ok:
                d = r.json()
                return d.get("results", []), d.get("totalHits", 0)
            return [], 0
        except Exception:
            if attempt < 2:
                time.sleep(3)
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
def main(year_filter=None):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    history = load_history()
    downloaded = set(history["downloaded"])
    new_papers = []

    year_label = f" [{year_filter}년]" if year_filter else ""
    print(f"=== 논문 수집 v6{year_label}: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"기존 수집: {len(downloaded)}편\n")

    # ── 1) CrossRef + Unpaywall ──
    print("[CrossRef + Unpaywall 수집]")
    for journal in TARGET_JOURNALS:
        print(f"\n  {journal['name']}")
        year = year_filter or datetime.now().year

        # ISSN / eISSN 둘 다 시도
        issns = [journal["issn"]]
        if journal.get("eissn"):
            issns.append(journal["eissn"])

        all_works = []
        seen_dois = set()
        for issn in issns:
            works = crossref_all_works(issn, year)
            for w in works:
                doi = (w.get("DOI") or "").strip().lower()
                if doi and doi not in seen_dois:
                    seen_dois.add(doi)
                    all_works.append(w)

        oa_count = 0
        for work in all_works:
            doi = (work.get("DOI") or "").strip().lower()
            if not doi:
                continue
            uid = f"doi:{doi}"
            if uid in downloaded:
                continue

            # 메타데이터 추출
            titles  = work.get("title", [])
            title   = titles[0] if titles else ""
            if not title:
                continue
            authors = [
                f"{a.get('family', '')} {a.get('given', '')}".strip()
                for a in work.get("author", [])
            ]
            pub     = work.get("published", {}).get("date-parts", [[None]])[0]
            year_p  = str(pub[0]) if pub else str(year)
            volume  = work.get("volume", "")
            issue   = work.get("issue", "")

            # Unpaywall로 OA PDF 확인
            pdf_url = unpaywall_get_pdf(doi)
            time.sleep(0.15)  # Unpaywall rate limit

            if not pdf_url:
                continue

            oa_count += 1
            print(f"  [OA] {title[:65]}")
            path = download_pdf(pdf_url, title, authors, journal["name"],
                                journal["folder"], volume, issue, year_p)
            if path:
                downloaded.add(uid)
                new_papers.append({"title": title, "journal": journal["name"], "year": year_p})
            time.sleep(0.3)

        print(f"    → 총 {len(all_works)}편 중 OA {oa_count}편 / 저장 {sum(1 for p in new_papers if p['journal']==journal['name'])}편")
        time.sleep(1)

    # ── 2) CORE API: 보완 수집 ──
    print("\n[CORE API 보완 수집]")
    for journal in TARGET_JOURNALS:
        print(f"  {journal['name']}")
        results, total = core_get_works(journal["name"], year=year_filter, page_size=100)
        print(f"    CORE: {total}편")
        saved = 0
        for item in results:
            pid    = str(item.get("id", ""))
            uid    = f"core:{pid}"
            if uid in downloaded:
                continue
            title  = item.get("title", "")
            if not title:
                continue
            # DOI 중복 체크
            doi = (item.get("doi") or "").strip().lower()
            if doi and f"doi:{doi}" in downloaded:
                downloaded.add(uid)
                continue
            authors = [a.get("name", "") for a in item.get("authors", [])]
            year_p  = str(item.get("yearPublished", "") or "")
            pdf_url = item.get("downloadUrl", "")
            if not pdf_url:
                for lk in item.get("links", []):
                    if lk.get("type") in ("download", "pdf"):
                        pdf_url = lk.get("url", "")
                        break
            if not pdf_url:
                continue
            volume = issue = ""
            for jinfo in item.get("journals", []):
                volume = str(jinfo.get("volume", "") or "") or volume
                issue  = str(jinfo.get("issue",  "") or "") or issue

            print(f"  -> {title[:65]}")
            path = download_pdf(pdf_url, title, authors, journal["name"],
                                journal["folder"], volume, issue, year_p)
            if path:
                downloaded.add(uid)
                if doi:
                    downloaded.add(f"doi:{doi}")
                new_papers.append({"title": title, "journal": journal["name"], "year": year_p})
                saved += 1
            time.sleep(0.4)
        print(f"    → {saved}편 추가 저장")
        time.sleep(1)

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
    # python paper_collector.py 2025  → 2025년 논문 전체
    # python paper_collector.py       → 올해 신규 논문
    year_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(year_filter=year_arg)
