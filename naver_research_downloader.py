"""
Download Naver Finance research PDFs into a local knowledge folder.

Rules implemented for this project:
- Download every company report and organize it by sector.
- Save files with a trailing date like "26.05.10".
- Download industry reports only when the PDF appears to have 10+ pages.
- Use the same naming and sector-folder organization for industry reports.

Examples:
    python naver_research_downloader.py
    python naver_research_downloader.py --company-pages 2 --industry-pages 1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "naver_research"
COMPANY_DIR = DATA_DIR / "company"
INDUSTRY_DIR = DATA_DIR / "industry"
META_DIR = DATA_DIR / "_meta"
MANIFEST_PATH = META_DIR / "manifest.json"
SECTOR_CACHE_PATH = META_DIR / "company_sector_cache.json"

BASE_URL = "https://finance.naver.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://finance.naver.com/research/",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


@dataclass
class ReportRow:
    report_type: str
    title: str
    firm: str
    date_text: str
    detail_url: str
    pdf_url: str
    sector_name: str
    company_name: str = ""
    company_code: str = ""
    source_category: str = ""


def ensure_directories() -> None:
    for path in (COMPANY_DIR, INDUSTRY_DIR, META_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import time as _time
    for attempt in range(5):
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            return
        except OSError:
            if attempt == 4:
                raise
            _time.sleep(2)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split()).strip()


def sanitize_filename(value: str) -> str:
    value = normalize_whitespace(value)
    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = value.replace("\u200b", "")
    return value[:180].strip(" ._") or "untitled"


def format_date_suffix(raw: str) -> str:
    raw = raw.strip()
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", raw):
        return raw
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", raw):
        return raw[2:]
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[2:4]}.{raw[4:6]}.{raw[6:8]}"
    raise ValueError(f"Unsupported date format: {raw}")


def parse_report_date(raw: str) -> datetime.date:
    raw = raw.strip()
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", raw):
        year, month, day = raw.split(".")
        return datetime.strptime(f"20{year}.{month}.{day}", "%Y.%m.%d").date()
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", raw):
        return datetime.strptime(raw, "%Y.%m.%d").date()
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d").date()
    raise ValueError(f"Unsupported date format: {raw}")


def join_url(href: str) -> str:
    return urljoin(f"{BASE_URL}/research/", href)


def extract_code_from_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("code", [""])[0]


def fetch_html(session: requests.Session, url: str) -> str:
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except requests.RequestException as error:
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    raise last_error


def fetch_binary(session: requests.Session, url: str) -> bytes:
    last_error = None
    for attempt in range(4):
        try:
            response = session.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException as error:
            last_error = error
            print(f"[retry] pdf fetch failed ({attempt + 1}/4): {url}")
            time.sleep(2 * (attempt + 1))
    raise last_error


def get_last_page(html: str) -> int | None:
    """pgRR(맨뒤) 링크에서 마지막 페이지 번호 추출. 없으면 None."""
    import re as _re
    m = _re.search(r'pgRR.*?page=(\d+)', html, _re.DOTALL)
    return int(m.group(1)) if m else None


def iter_table_rows(session: requests.Session, list_url: str) -> Iterable[list]:
    html = fetch_html(session, list_url)
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("table.type_1 tr"):
        cols = row.select("td")
        if cols:
            yield cols


def fetch_page_html(session: requests.Session, list_url: str) -> tuple[str, list]:
    """(html, list[cols]) 반환 — 마지막 페이지 감지용."""
    html = fetch_html(session, list_url)
    soup = BeautifulSoup(html, "html.parser")
    all_cols = [row.select("td") for row in soup.select("table.type_1 tr") if row.select("td")]
    return html, all_cols


def parse_company_rows(
    session: requests.Session,
    max_pages: int | None,
    recent_days: int | None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[ReportRow]:
    rows: list[ReportRow] = []
    page = 1

    # from_date/to_date 지정 시 날짜 필터 URL 사용 (과거 데이터 접근 가능)
    use_date_filter = from_date is not None or to_date is not None
    fd_str = from_date.strftime("%Y-%m-%d") if from_date else ""
    td_str = (to_date or datetime.now().date()).strftime("%Y-%m-%d") if use_date_filter else ""

    # recent_days 전용 컷오프 (날짜 필터 미사용 시만)
    cutoff_date = None
    if recent_days is not None and not use_date_filter:
        cutoff_date = datetime.now().date() - timedelta(days=recent_days)

    last_page: int | None = None

    while True:
        if use_date_filter:
            list_url = (
                f"{BASE_URL}/research/company_list.naver"
                f"?searchType=writeDate&writeFromDate={fd_str}&writeToDate={td_str}&page={page}"
            )
        else:
            list_url = f"{BASE_URL}/research/company_list.naver?page={page}"

        html, all_cols = fetch_page_html(session, list_url)

        # 첫 페이지에서 마지막 페이지 번호 파악
        if last_page is None:
            last_page = get_last_page(html)

        page_rows = 0
        reached_cutoff = False

        for cols in all_cols:
            if len(cols) < 5:
                continue

            company_link = cols[0].select_one("a")
            detail_link = cols[1].select_one("a")
            pdf_link = cols[3].select_one("a")
            if not company_link or not detail_link or not pdf_link:
                continue

            company_name = normalize_whitespace(cols[0].get_text(" ", strip=True))
            title = normalize_whitespace(cols[1].get_text(" ", strip=True))
            firm = normalize_whitespace(cols[2].get_text(" ", strip=True))
            date_text = normalize_whitespace(cols[4].get_text(" ", strip=True))
            report_date = parse_report_date(date_text)

            if cutoff_date is not None and report_date < cutoff_date:
                reached_cutoff = True
                break

            company_url = join_url(company_link.get("href", ""))
            rows.append(
                ReportRow(
                    report_type="company",
                    title=title,
                    firm=firm,
                    date_text=date_text,
                    detail_url=join_url(detail_link.get("href", "")),
                    pdf_url=join_url(pdf_link.get("href", "")),
                    sector_name="",
                    company_name=company_name,
                    company_code=extract_code_from_url(company_url),
                )
            )
            page_rows += 1

        if page_rows == 0:
            break
        if reached_cutoff:
            break
        if last_page is not None and page >= last_page:
            break
        if max_pages is not None and page >= max_pages:
            break
        if page % 50 == 0:
            print(f"  [page {page}] 수집 중... ({len(rows)}건)")
        page += 1
        time.sleep(0.2)

    return rows


def parse_industry_rows(
    session: requests.Session,
    max_pages: int | None,
    recent_days: int | None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[ReportRow]:
    rows: list[ReportRow] = []
    page = 1
    cutoff_date = None
    if recent_days is not None:
        cutoff_date = datetime.now().date() - timedelta(days=recent_days)
    if from_date is not None:
        cutoff_date = from_date

    while True:
        list_url = f"{BASE_URL}/research/industry_list.naver?page={page}"
        page_rows = 0
        reached_cutoff = False

        for cols in iter_table_rows(session, list_url):
            if len(cols) < 5:
                continue

            detail_link = cols[1].select_one("a")
            pdf_link = cols[3].select_one("a")
            if not detail_link or not pdf_link:
                continue

            category = normalize_whitespace(cols[0].get_text(" ", strip=True))
            title = normalize_whitespace(cols[1].get_text(" ", strip=True))
            firm = normalize_whitespace(cols[2].get_text(" ", strip=True))
            date_text = normalize_whitespace(cols[4].get_text(" ", strip=True))
            report_date = parse_report_date(date_text)

            if cutoff_date is not None and report_date < cutoff_date:
                reached_cutoff = True
                break
            if to_date is not None and report_date > to_date:
                page_rows += 1
                continue

            rows.append(
                ReportRow(
                    report_type="industry",
                    title=title,
                    firm=firm,
                    date_text=date_text,
                    detail_url=join_url(detail_link.get("href", "")),
                    pdf_url=join_url(pdf_link.get("href", "")),
                    sector_name=category or "기타",
                    source_category=category,
                )
            )
            page_rows += 1

        if page_rows == 0:
            break
        if reached_cutoff:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1
        time.sleep(0.2)

    return rows


def extract_sector_from_item_page(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select('a[href*="/sise/sise_group_detail.naver?type=upjong"]'):
        text = normalize_whitespace(anchor.get_text(" ", strip=True))
        if text:
            return text
    return None


def resolve_company_sector(
    session: requests.Session,
    company_code: str,
    company_name: str,
    cache: dict[str, str],
) -> str:
    if company_code in cache:
        return cache[company_code]

    item_url = f"{BASE_URL}/item/main.naver?code={company_code}"
    html = fetch_html(session, item_url)
    sector = extract_sector_from_item_page(html) or "기타"
    cache[company_code] = sector
    print(f"[sector] {company_name} -> {sector}")
    time.sleep(0.15)
    return sector


def estimate_pdf_page_count(pdf_bytes: bytes) -> int:
    count = len(re.findall(rb"/Type\s*/Page\b", pdf_bytes))
    if count == 0:
        count = len(re.findall(rb"/Count\s+(\d+)", pdf_bytes))
    return count


def build_filename(report: ReportRow) -> str:
    date_suffix = format_date_suffix(report.date_text)
    if report.report_type == "company":
        stem = f"{report.company_name}_{report.title}_{report.firm}_{date_suffix}"
    else:
        stem = f"{report.sector_name}_{report.title}_{report.firm}_{date_suffix}"
    return f"{sanitize_filename(stem)}.pdf"


def get_destination(report: ReportRow) -> Path:
    sector_dir = sanitize_filename(report.sector_name or "기타")
    base_dir = COMPANY_DIR if report.report_type == "company" else INDUSTRY_DIR
    return base_dir / sector_dir / build_filename(report)


def make_manifest_key(report: ReportRow) -> str:
    return f"{report.report_type}:{report.pdf_url}"


def is_recent_report(report: ReportRow, recent_days: int | None) -> bool:
    if recent_days is None:
        return True
    report_date = parse_report_date(report.date_text)
    cutoff = datetime.now().date() - timedelta(days=recent_days)
    return report_date >= cutoff


def download_report(
    session: requests.Session,
    report: ReportRow,
    manifest: dict[str, dict],
    industry_min_pages: int,
) -> tuple[bool, str]:
    key = make_manifest_key(report)
    destination = get_destination(report)
    if destination.exists():
        return False, "already_saved"
    if key in manifest and manifest[key].get("saved") and Path(manifest[key].get("path", "X")).exists():
        return False, "already_saved"

    pdf_bytes = fetch_binary(session, report.pdf_url)
    page_count = estimate_pdf_page_count(pdf_bytes)

    if report.report_type == "industry" and page_count < industry_min_pages:
        manifest[key] = {
            "saved": False,
            "skipped_reason": f"page_count_lt_{industry_min_pages}",
            "page_count": page_count,
            "title": report.title,
            "firm": report.firm,
            "date": report.date_text,
            "pdf_url": report.pdf_url,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        return False, f"skipped_pages_{page_count}"

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(pdf_bytes)
    manifest[key] = {
        "saved": True,
        "path": str(destination.relative_to(BASE_DIR)),
        "page_count": page_count,
        "title": report.title,
        "firm": report.firm,
        "date": report.date_text,
        "pdf_url": report.pdf_url,
        "detail_url": report.detail_url,
        "sector": report.sector_name,
        "company": report.company_name,
        "company_code": report.company_code,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    return True, f"saved_pages_{page_count}"


def run(
    company_pages: int | None,
    industry_pages: int | None,
    industry_min_pages: int,
    recent_days: int | None,
    mode: str,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> None:
    ensure_directories()
    manifest = load_json(MANIFEST_PATH, {})
    sector_cache = load_json(SECTOR_CACHE_PATH, {})

    session = requests.Session()
    session.headers.update(HEADERS)

    if from_date:
        print(f"[filter] {from_date} ~ {to_date or '오늘'} 범위 수집")

    company_rows: list[ReportRow] = []
    industry_rows: list[ReportRow] = []

    if mode in {"all", "company"}:
        print("[collect] company rows")
        company_rows = parse_company_rows(session, company_pages, recent_days,
                                          from_date=from_date, to_date=to_date)
        print(f"[collect] found {len(company_rows)} company reports")

        for row in company_rows:
            row.sector_name = resolve_company_sector(
                session=session,
                company_code=row.company_code,
                company_name=row.company_name,
                cache=sector_cache,
            )

    if mode in {"all", "industry"}:
        print("[collect] industry rows")
        industry_rows = parse_industry_rows(session, industry_pages, recent_days,
                                            from_date=from_date, to_date=to_date)
        print(f"[collect] found {len(industry_rows)} industry reports")

    company_saved = 0
    industry_saved = 0
    industry_skipped = 0

    for row in company_rows:
        saved, status = download_report(
            session=session,
            report=row,
            manifest=manifest,
            industry_min_pages=industry_min_pages,
        )
        if saved:
            company_saved += 1
        print(f"[company] {row.company_name} | {row.title} -> {status}")
        save_json(MANIFEST_PATH, manifest)
        time.sleep(0.1)

    for row in industry_rows:
        saved, status = download_report(
            session=session,
            report=row,
            manifest=manifest,
            industry_min_pages=industry_min_pages,
        )
        if saved:
            industry_saved += 1
        elif status.startswith("skipped_pages_"):
            industry_skipped += 1
        print(f"[industry] {row.sector_name} | {row.title} -> {status}")
        save_json(MANIFEST_PATH, manifest)
        time.sleep(0.1)

    save_json(SECTOR_CACHE_PATH, sector_cache)

    print("")
    print("[done]")
    print(f"  company saved  : {company_saved}")
    print(f"  industry saved : {industry_saved}")
    print(f"  industry skip  : {industry_skipped}")
    print(f"  manifest       : {MANIFEST_PATH.relative_to(BASE_DIR)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Naver Finance research PDFs.")
    parser.add_argument(
        "--company-pages",
        type=int,
        default=None,
        help="Limit company list pagination for testing. Default: crawl all pages.",
    )
    parser.add_argument(
        "--industry-pages",
        type=int,
        default=None,
        help="Limit industry list pagination for testing. Default: crawl all pages.",
    )
    parser.add_argument(
        "--industry-min-pages",
        type=int,
        default=10,
        help="Save industry reports only when the PDF has at least this many pages.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only keep reports published in the most recent N days. Example: --days 30",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "company", "industry"],
        default="all",
        help="Choose which report type to process.",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Reports older than this are skipped.",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Reports newer than this are skipped.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()

    from_date = None
    to_date = None
    if arguments.from_date:
        from_date = datetime.strptime(arguments.from_date, "%Y-%m-%d").date()
    if arguments.to_date:
        to_date = datetime.strptime(arguments.to_date, "%Y-%m-%d").date()

    run(
        company_pages=arguments.company_pages,
        industry_pages=arguments.industry_pages,
        industry_min_pages=arguments.industry_min_pages,
        recent_days=arguments.days,
        mode=arguments.mode,
        from_date=from_date,
        to_date=to_date,
    )
