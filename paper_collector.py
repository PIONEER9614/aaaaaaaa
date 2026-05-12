"""
개념사 / 지성사 논문 자동 수집기 v6
- CrossRef API: ISSN으로 해당 연도 전체 논문 목록 수집
- Unpaywall API: DOI로 OA PDF URL 확인
- CORE API: 보완 수집
- 학술지별 폴더 + 저자_제목_학술지_권호_연도 파일명
"""

import os, re, io, json, time, requests, sys, urllib3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                HRFlowable, Table, TableStyle)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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
    # pub_months: 실제 발행월 목록. 이 월 기준으로 하위 폴더 생성
    {"name": "Contributions to the History of Concepts", "folder": "01_Contributions to the History of Concepts", "issn": "1807-9326", "eissn": "1874-656X", "pub_months": [3, 6, 9, 12]},
    {"name": "History of European Ideas",                "folder": "02_History of European Ideas",                "issn": "0191-6599", "eissn": "1873-541X", "pub_months": [2, 4, 6, 8, 10, 12]},
    {"name": "Journal of the History of Ideas",          "folder": "03_Journal of the History of Ideas",          "issn": "0022-5037", "eissn": "1086-3222", "pub_months": [1, 4, 7, 10]},
    {"name": "Intellectual History Review",              "folder": "04_Intellectual History Review",              "issn": "1749-4621", "eissn": "1749-463X", "pub_months": [3, 6, 9, 12]},
    {"name": "History and Theory",                       "folder": "05_History and Theory",                       "issn": "0018-2656", "eissn": "1468-2303", "pub_months": [3, 6, 9, 12]},
    {"name": "Modern Intellectual History",              "folder": "06_Modern Intellectual History",              "issn": "1479-2443", "eissn": "1479-2451", "pub_months": [3, 7, 11]},
    {"name": "Rethinking History",                       "folder": "07_Rethinking History",                       "issn": "1364-2529", "eissn": "1470-1154", "pub_months": [3, 6, 9, 12]},
    {"name": "Gaenyeom-gwa Sotong",                     "folder": "08_Gaenyeom-gwa Sotong",                      "issn": "2092-7649", "eissn": "",           "pub_months": [6, 12]},
]

MONTH_KO = {1:"01_Jan", 2:"02_Feb", 3:"03_Mar", 4:"04_Apr", 5:"05_May",  6:"06_Jun",
            7:"07_Jul", 8:"08_Aug", 9:"09_Sep", 10:"10_Oct", 11:"11_Nov", 12:"12_Dec"}

def issue_subfolder(pub_months, year, month):
    """발행월 → 폴더명.
    month가 있으면 가장 가까운 발행월로 스냅. 없으면 연도만.
    예) pub_months=[3,6,9,12], month=4  →  '2025_06_Jun'  (다음 발행호)
        pub_months=[3,6,9,12], month=3  →  '2025_03_Mar'
    """
    if not month or not year:
        return str(year or "unknown")
    if not pub_months:
        return f"{year}_{MONTH_KO.get(month, f'{month:02d}')}"
    # month 이상인 발행월 중 가장 작은 것 → 해당 호에 수록
    candidates = [m for m in sorted(pub_months) if m >= month]
    target = candidates[0] if candidates else max(pub_months)
    return f"{year}_{MONTH_KO[target]}"

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
def download_pdf(url, title, authors, journal_name, folder, volume="", issue="", year="",
                 pub_month=None, pub_months=None):
    for verify in (True, False):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40, stream=True,
                             verify=verify, allow_redirects=True)
            ct = r.headers.get("Content-Type", "")
            if not r.ok or "pdf" not in ct.lower():
                return False
            # 발행월 기반 하위 폴더
            sub = issue_subfolder(pub_months or [], int(year) if year else None, pub_month)
            target_dir = DOWNLOAD_DIR / folder / sub
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = make_filename(title, authors, journal_name, volume, issue, year)
            path = target_dir / filename
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            print(f"    [저장] {sub}/{filename[:60]}")
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

# ── 폰트 ─────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf",     "C:/Windows/Fonts/malgun.ttf"]
    bold_c     = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR",   font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

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

def send_pdf(buf, filename, caption=""):
    if not BOT_TOKEN or not CHAT_ID:
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

def build_paper_pdf(new_papers, date_str, year_label=""):
    fn, fnb = setup_font()
    def S(nm, **kw):  return ParagraphStyle(nm, fontName=fn,  **kw)
    def SB(nm, **kw): return ParagraphStyle(nm, fontName=fnb, **kw)
    ST = {
        "title":  SB("ti", fontSize=18, leading=24, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":    S ("su", fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":     SB("h2", fontSize=12, leading=17, spaceBefore=10,spaceAfter=4, textColor=colors.HexColor("#1a3a5c")),
        "h3":     SB("h3", fontSize=9,  leading=13, spaceBefore=4, spaceAfter=2, textColor=colors.HexColor("#c0392b")),
        "body":   S ("bo", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#222")),
        "note":   S ("no", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm,  bottomMargin=1.8*cm)
    story = []
    W = doc.width

    story.append(Paragraph(f"📚 논문 수집 리포트{year_label}", ST["title"]))
    story.append(Paragraph(f"{date_str}  ·  신규 {len(new_papers)}편", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # 학술지별 그룹핑
    by_journal = {}
    for p in new_papers:
        j = p["journal"]
        by_journal.setdefault(j, []).append(p)

    for journal, papers in by_journal.items():
        story.append(Paragraph(f"📖 {journal}  ({len(papers)}편)", ST["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaa")))
        for p in papers:
            story.append(Spacer(1, 0.1*cm))
            story.append(Paragraph(f"▶ {p['title'][:90]}", ST["h3"]))
            story.append(Paragraph(f"연도: {p['year']}", ST["note"]))
            story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#eee")))
        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    buf.seek(0)
    return buf

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
            month_p = int(pub[1]) if pub and len(pub) > 1 and pub[1] else None
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
                                journal["folder"], volume, issue, year_p,
                                pub_month=month_p, pub_months=journal.get("pub_months", []))
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
            # CORE publishedDate 예: "2025-06-01"
            pub_date = item.get("publishedDate", "") or ""
            month_p  = int(pub_date[5:7]) if len(pub_date) >= 7 and pub_date[5:7].isdigit() else None
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
                                journal["folder"], volume, issue, year_p,
                                pub_month=month_p, pub_months=journal.get("pub_months", []))
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
        date_str   = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
        year_label = f" [{year_filter}년]" if year_filter else ""
        buf        = build_paper_pdf(new_papers, date_str, year_label)
        filename   = f"papers_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        caption    = f"📚 새 논문 {len(new_papers)}편 수집{year_label}\n{date_str}"
        send_pdf(buf, filename, caption=caption)

if __name__ == "__main__":
    # python paper_collector.py 2025  → 2025년 논문 전체
    # python paper_collector.py       → 올해 신규 논문
    year_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(year_filter=year_arg)
