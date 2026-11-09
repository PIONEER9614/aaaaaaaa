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
# 날짜_증권사_제목 형식으로 저장하는 분야 (naver_research_downloader_econ_bond.py 와 같은 폴더/규칙)
FLAT_DIRS = {
    "invest": DATA_DIR / "invest",
    "economy": DATA_DIR / "economy",
    "bond": DATA_DIR / "bond",
}
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
    for path in (COMPANY_DIR, INDUSTRY_DIR, META_DIR, *FLAT_DIRS.values()):
        path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import os as _os
    import time as _time
    # 임시 파일에 다 쓴 뒤 교체: 실행이 중간에 끊겨도 기존 파일이 잘리지 않음
    tmp_path = path.with_name(path.name + ".tmp")
    for attempt in range(5):
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            _os.replace(tmp_path, path)
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


def parse_company_rows_legacy(
    session: requests.Session,
    max_pages: int | None,
    recent_days: int | None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[ReportRow]:
    """구(舊) finance.naver.com/research/company_list.naver 표 기반 파서.
    2026-09 무렵 네이버가 이 페이지를 stock.naver.com/research/company 로 이전하면서
    <table> 구조 자체가 사라져 더 이상 동작하지 않음. 참고용으로만 남겨둠.
    현재는 parse_company_rows (Playwright 기반)를 사용."""
    rows: list[ReportRow] = []
    page = 1

    use_date_filter = from_date is not None or to_date is not None
    fd_str = from_date.strftime("%Y-%m-%d") if from_date else ""
    td_str = (to_date or datetime.now().date()).strftime("%Y-%m-%d") if use_date_filter else ""

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


STOCK_NAVER_URL = "https://stock.naver.com/research/company"
CARD_SELECTOR = "a.ResearchList_research-item-link__OF48E"


def _clean_stock_naver_date(raw: str) -> str:
    # "2026. 09. 18." -> "2026.09.18"
    cleaned = raw.replace(" ", "")
    return cleaned.rstrip(".")


def parse_company_rows(
    session: requests.Session,
    max_pages: int | None,
    recent_days: int | None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[ReportRow]:
    """stock.naver.com/research/company (무한스크롤 카드형) 기반 파서.
    2026-09 네이버 리뉴얼 이후 구조. Playwright로 렌더링 후 카드 데이터를 읽고,
    PDF 실제 URL은 각 리포트 상세 페이지(/research/company/{id})를 방문해 확인한다.
    max_pages는 "스크롤 회차 상한"으로 재해석해 사용한다 (없으면 기본 40회).
    """
    from playwright.sync_api import sync_playwright

    cutoff_date = None
    if recent_days is not None and from_date is None and to_date is None:
        cutoff_date = datetime.now().date() - timedelta(days=recent_days)

    max_scrolls = max_pages if max_pages is not None else 150

    raw_items: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page_obj = browser.new_page(viewport={"width": 1400, "height": 1400})
        page_obj.goto(STOCK_NAVER_URL, wait_until="networkidle", timeout=30000)
        time.sleep(1.5)

        prev_count = -1
        stagnant = 0
        for scroll_i in range(max_scrolls):
            cards = page_obj.locator(CARD_SELECTOR)
            count = cards.count()
            if count == prev_count:
                stagnant += 1
                # CI/클라우드 러너는 네트워크가 느려서 카드 로딩이 늦게 잡히는 경우가 많음.
                # 너무 일찍 멈추면 뒤에 있는(더 오래된) 증권사 리포트들을 놓치게 됨 -> 임계값 상향.
                if stagnant >= 6:
                    break
            else:
                stagnant = 0
            prev_count = count

            # 컷오프 도달 여부: 현재 로드된 마지막 카드의 날짜 확인
            if cutoff_date is not None and count > 0:
                try:
                    last_date_raw = cards.nth(count - 1).locator(".ResearchList_date__tVIZb").inner_text(timeout=2000)
                    last_date = parse_report_date(_clean_stock_naver_date(last_date_raw))
                    if last_date < cutoff_date:
                        break
                except Exception:
                    pass

            page_obj.mouse.wheel(0, 8000)
            time.sleep(1.6)

        cards = page_obj.locator(CARD_SELECTOR)
        n = cards.count()
        for i in range(n):
            c = cards.nth(i)
            try:
                href = c.get_attribute("href") or ""
                title = normalize_whitespace(c.locator(".ResearchList_title__QEejC").inner_text(timeout=2000))
                date_raw = c.locator(".ResearchList_date__tVIZb").inner_text(timeout=2000)
                firm = normalize_whitespace(c.locator(".press").inner_text(timeout=2000))
                company_name = normalize_whitespace(
                    c.locator(".ResearchList_stock-name__RjQiE").inner_text(timeout=2000)
                )
                thumb_src = c.locator(".Thumbnail_img__iYWsD").get_attribute("src", timeout=2000) or ""
            except Exception:
                continue

            code_match = re.search(r"Stock(\d{6})", thumb_src)
            raw_items.append({
                "href": href,
                "title": title,
                "date_raw": date_raw,
                "firm": firm,
                "company_name": company_name,
                "company_code": code_match.group(1) if code_match else "",
            })

        # 날짜 필터링 + 중복 제거
        filtered: list[dict] = []
        seen_href = set()
        for it in raw_items:
            if not it["href"] or it["href"] in seen_href:
                continue
            seen_href.add(it["href"])
            date_clean = _clean_stock_naver_date(it["date_raw"])
            try:
                d = parse_report_date(date_clean)
            except ValueError:
                continue
            if cutoff_date is not None and d < cutoff_date:
                continue
            if from_date is not None and d < from_date:
                continue
            if to_date is not None and d > to_date:
                continue
            it["date_text"] = date_clean
            filtered.append(it)

        # 상세 페이지 방문해서 실제 PDF URL 확인
        # CI(GitHub Actions)처럼 네트워크가 불안정한 환경에서는 상세 페이지 요청이
        # 한 번에 실패하는 경우가 잦고, 예전 코드는 실패 시 바로 포기 -> 조용히 누락됨.
        # (특정 증권사만 계속 누락되는 원인 중 하나였음) 재시도 + 실패 로그를 추가한다.
        detail_failures: list[dict] = []
        for it in filtered:
            detail_url = f"https://stock.naver.com{it['href']}"
            it["pdf_url"] = ""
            last_exc = None
            for attempt in range(3):
                try:
                    page_obj.goto(detail_url, wait_until="domcontentloaded", timeout=25000)
                    page_obj.wait_for_selector("a[href*='.pdf']", timeout=10000)
                    pdf_link = page_obj.locator("a[href*='.pdf']").first
                    it["pdf_url"] = pdf_link.get_attribute("href", timeout=5000) if pdf_link.count() > 0 else ""
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    time.sleep(1.0 * (attempt + 1))
            if last_exc is not None or not it["pdf_url"]:
                print(
                    f"  [warn] PDF 링크 못 찾음 (3회 시도): "
                    f"{it.get('firm','?')} | {it.get('title','')[:30]} "
                    f"({last_exc.__class__.__name__ if last_exc else 'no_pdf_link'})"
                )
                detail_failures.append({
                    "firm": it.get("firm", ""),
                    "title": it.get("title", ""),
                    "date": it.get("date_text", ""),
                    "href": it.get("href", ""),
                    "reason": last_exc.__class__.__name__ if last_exc else "no_pdf_link",
                })
            it["detail_url"] = detail_url
            time.sleep(0.25)

        if detail_failures:
            fail_path = META_DIR / "failed_detail_lookups.json"
            existing = load_json(fail_path, [])
            existing.extend({**f, "run_at": datetime.now().isoformat(timespec="seconds")} for f in detail_failures)
            existing = existing[-2000:]  # 무한 증가 방지
            save_json(fail_path, existing)
            fail_firms = sorted({f["firm"] for f in detail_failures})
            print(f"[warn] 이번 회차에서 PDF 링크 조회 실패: {len(detail_failures)}건 / 증권사: {', '.join(fail_firms)}")

        found_firms = sorted({it.get("firm", "") for it in filtered if it.get("firm")})
        print(f"[collect] 이번 스크롤에서 발견된 증권사({len(found_firms)}개): {', '.join(found_firms)}")

        browser.close()

    rows: list[ReportRow] = []
    for it in filtered:
        if not it.get("pdf_url"):
            continue
        rows.append(
            ReportRow(
                report_type="company",
                title=it["title"],
                firm=it["firm"],
                date_text=it["date_text"],
                detail_url=it["detail_url"],
                pdf_url=it["pdf_url"],
                sector_name="",
                company_name=it["company_name"],
                company_code=it["company_code"],
            )
        )
    return rows


API_BASE = "https://stock.naver.com/api/stockSecurity/researches/v2"
API_HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://stock.naver.com/research"}
# report_type -> API 카테고리
API_CATEGORIES = {
    "company": "company",
    "industry": "industry",
    "invest": "invest",
    "economy": "economy",
    "bond": "debenture",
}


def fetch_api_json(session: requests.Session, url: str) -> dict:
    last_exc = None
    for attempt in range(3):
        try:
            response = session.get(url, headers=API_HEADERS, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"API 요청 실패: {url} ({last_exc})")


def parse_api_rows(
    session: requests.Session,
    report_type: str,
    recent_days: int | None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    max_pages: int | None = None,
) -> list[ReportRow]:
    """stock.naver.com 내부 API 기반 수집.
    목록(?index=N&size=50)에는 PDF 주소가 없어서 상세(/{nid})의 attachUrl을 쓴다.
    상세 화면에 PDF 링크가 안 보이는 증권사(신한투자증권 등)도 attachUrl은 내려온다.
    """
    category = API_CATEGORIES[report_type]
    cutoff = from_date
    if cutoff is None and recent_days is not None:
        cutoff = datetime.now().date() - timedelta(days=recent_days)

    items: list[dict] = []
    index = 0
    while True:
        data = fetch_api_json(session, f"{API_BASE}/{category}?index={index}&size=50")
        page_items = data.get("items") or []
        items.extend(page_items)
        index += 1
        if not page_items or not data.get("hasNext"):
            break
        if cutoff is not None and page_items[-1]["writeDate"] < cutoff.isoformat():
            break
        if max_pages is not None and index >= max_pages:
            break
        time.sleep(0.2)

    rows: list[ReportRow] = []
    failures: list[dict] = []
    for it in items:
        report_date = datetime.strptime(it["writeDate"], "%Y-%m-%d").date()
        if cutoff is not None and report_date < cutoff:
            continue
        if to_date is not None and report_date > to_date:
            continue
        nid = it["nid"]
        try:
            detail = fetch_api_json(session, f"{API_BASE}/{category}/{nid}")
        except RuntimeError as exc:
            detail = {}
            print(f"  [warn] 상세 조회 실패: {it.get('brokerName')} | {it.get('title', '')[:30]} ({exc})")
        pdf_url = detail.get("attachUrl") or ""
        if not pdf_url:
            failures.append({"firm": it.get("brokerName", ""), "title": it.get("title", ""),
                             "date": it["writeDate"], "href": f"/research/{category}/{nid}",
                             "reason": "no_attach_url"})
            continue
        rows.append(
            ReportRow(
                report_type=report_type,
                title=normalize_whitespace(it.get("title", "")),
                firm=normalize_whitespace(it.get("brokerName", "")),
                date_text=report_date.strftime("%Y.%m.%d"),
                detail_url=f"https://stock.naver.com/research/{category}/{nid}",
                pdf_url=pdf_url,
                sector_name=it.get("industryKoreanName") or "",
                company_name=it.get("itemName") or "",
                company_code=it.get("itemCode") or "",
                source_category=category,
            )
        )
        time.sleep(0.1)

    if failures:
        fail_path = META_DIR / "failed_detail_lookups.json"
        existing = load_json(fail_path, [])
        stamp = datetime.now().isoformat(timespec="seconds")
        existing.extend({**f, "run_at": stamp} for f in failures)
        save_json(fail_path, existing[-2000:])
        print(f"[warn] {report_type}: PDF 없는 리포트 {len(failures)}건")

    firms = sorted({row.firm for row in rows})
    print(f"[collect] {report_type}: {len(rows)}건 / 증권사 {len(firms)}곳 ({', '.join(firms)})")
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
    elif report.report_type in FLAT_DIRS:
        stem = f"{date_suffix}_{report.firm}_{report.title}"
    else:
        stem = f"{report.sector_name}_{report.title}_{report.firm}_{date_suffix}"
    return f"{sanitize_filename(stem)}.pdf"


def get_destination(report: ReportRow) -> Path:
    if report.report_type in FLAT_DIRS:
        return FLAT_DIRS[report.report_type] / build_filename(report)
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

    report_types = list(API_CATEGORIES) if mode == "all" else [mode]
    page_limits = {"company": company_pages, "industry": industry_pages}
    rows_by_type: dict[str, list[ReportRow]] = {}

    for report_type in report_types:
        print(f"[collect] {report_type} rows")
        rows = parse_api_rows(session, report_type, recent_days, from_date=from_date,
                              to_date=to_date, max_pages=page_limits.get(report_type))
        if report_type == "company":
            for row in rows:
                if row.company_code:
                    row.sector_name = resolve_company_sector(
                        session=session,
                        company_code=row.company_code,
                        company_name=row.company_name,
                        cache=sector_cache,
                    )
        rows_by_type[report_type] = rows

    saved_counts = {t: 0 for t in report_types}
    industry_skipped = 0
    failed = 0

    for report_type, rows in rows_by_type.items():
        for row in rows:
            try:
                saved, status = download_report(
                    session=session,
                    report=row,
                    manifest=manifest,
                    industry_min_pages=industry_min_pages,
                )
            except Exception as exc:  # 한 건 실패가 전체 회차를 멈추지 않게
                saved, status = False, f"error_{exc.__class__.__name__}"
                failed += 1
            if saved:
                saved_counts[report_type] += 1
            elif status.startswith("skipped_pages_"):
                industry_skipped += 1
            label = row.company_name or row.sector_name or row.firm
            print(f"[{report_type}] {label} | {row.title} -> {status}")
            if saved or status.startswith("skipped_pages_"):
                save_json(MANIFEST_PATH, manifest)
            time.sleep(0.1)

    save_json(MANIFEST_PATH, manifest)
    save_json(SECTOR_CACHE_PATH, sector_cache)

    print("")
    print("[done]")
    for report_type in report_types:
        print(f"  {report_type:<9} saved : {saved_counts[report_type]}")
    print(f"  industry skip   : {industry_skipped}")
    print(f"  download failed : {failed}")
    print(f"  manifest        : {MANIFEST_PATH.relative_to(BASE_DIR)}")


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
        choices=["all", *API_CATEGORIES],
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
