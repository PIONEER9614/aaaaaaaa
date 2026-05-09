"""
웹 대시보드용 데이터 수집 스크립트
- 네이버 증권 종목/산업 리포트 수집 → docs/data/reports.json
- 실행: python data_collector.py
"""

import os, json, time, requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ── 섹터 키워드 매핑 ─────────────────────────────────────────────────────────
SECTOR_KEYWORDS = {
    "반도체": ["삼성전자", "SK하이닉스", "한미반도체", "리노공업", "HPSP", "반도체", "HBM", "DRAM", "낸드", "파운드리"],
    "로봇":   ["현대로보틱스", "두산로보틱스", "레인보우로보틱스", "로봇", "자동화", "협동로봇"],
    "방산":   ["한화에어로스페이스", "LIG넥스원", "현대로템", "한국항공우주", "방산", "K방산", "무기"],
    "조선":   ["HD현대중공업", "삼성중공업", "한화오션", "조선", "LNG선", "해양플랜트", "선박"],
    "2차전지":["LG에너지솔루션", "삼성SDI", "SK온", "에코프로", "포스코퓨처엠", "배터리", "2차전지", "전기차"],
    "바이오": ["삼성바이오로직스", "셀트리온", "유한양행", "한미약품", "바이오", "신약", "제약"],
    "플랫폼": ["카카오", "NAVER", "네이버", "쿠팡", "크래프톤", "플랫폼", "게임", "IT서비스"],
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

REPORTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "reports.json")

# ── 날짜 파싱 헬퍼 ──────────────────────────────────────────────────────────
def parse_naver_date(raw):
    """네이버 날짜 포맷 변환: '26.05.08' → '2026-05-08'"""
    raw = raw.strip()
    if "." in raw:
        parts = raw.split(".")
        if len(parts) == 3:
            y = parts[0]
            m = parts[1].zfill(2)
            d = parts[2].zfill(2)
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{m}-{d}"
    elif len(raw) == 8 and raw.isdigit():
        return raw[:4] + "-" + raw[4:6] + "-" + raw[6:]
    return raw

def parse_naver_link(href):
    """네이버 링크 절대경로로 변환"""
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://finance.naver.com" + href
    return "https://finance.naver.com/research/" + href

# ── 섹터 추론 ─────────────────────────────────────────────────────────────────
def guess_sector(text):
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return sector
    return None

# ── 기존 데이터 로드/저장 ────────────────────────────────────────────────────
def load_existing():
    if os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_reports(reports):
    os.makedirs(os.path.dirname(REPORTS_PATH), exist_ok=True)
    with open(REPORTS_PATH, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(f"[저장] reports.json: {len(reports)}개")

# ── 네이버 증권: 종목 분석 리포트 수집 ───────────────────────────────────────
def fetch_company_reports(days=14):
    """전체 종목분석 리포트 목록 수집 (섹터 키워드로 자동 분류)
    네이버 컬럼: 종목명(0) | 리포트명(1) | 증권사(2) | 첨부(3) | 날짜(4) | 조회(5)
    """
    results = []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    for page in range(1, 6):
        url = f"https://finance.naver.com/research/company_list.naver?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table.type_1 tr")
            found_old = False

            for row in rows:
                cols = row.select("td")
                if len(cols) < 5:
                    continue
                title_tag = cols[1].select_one("a")
                if not title_tag:
                    continue

                company = cols[0].get_text(strip=True)
                title   = cols[1].get_text(strip=True)
                firm    = cols[2].get_text(strip=True)
                raw_dt  = cols[4].get_text(strip=True)

                if not company or not title:
                    continue

                date_str = parse_naver_date(raw_dt)
                if date_str and date_str < cutoff:
                    found_old = True
                    continue

                link = parse_naver_link(title_tag.get("href", ""))
                sector = guess_sector(company + " " + title) or "기타"
                uid = f"stock_{date_str.replace('-','')}_{company[:6]}_{firm[:4]}"

                results.append({
                    "id": uid,
                    "type": "stock",
                    "sector": sector,
                    "company": company,
                    "firm": firm,
                    "title": title,
                    "date": date_str,
                    "target_price": None,
                    "summary": "",
                    "link": link,
                })

            if found_old:
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"[오류] 종목리포트 page{page}: {e}")
            break

    return results

# ── 네이버 증권: 산업 분석 리포트 수집 ───────────────────────────────────────
def fetch_industry_reports(days=14):
    """산업 분석 리포트 수집
    네이버 컬럼: 업종(0) | 리포트명(1) | 증권사(2) | 첨부(3) | 날짜(4) | 조회(5)
    """
    results = []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    for page in range(1, 4):
        url = f"https://finance.naver.com/research/industry_list.naver?page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            rows = soup.select("table.type_1 tr")
            found_old = False

            for row in rows:
                cols = row.select("td")
                if len(cols) < 5:
                    continue
                title_tag = cols[1].select_one("a")
                if not title_tag:
                    continue

                naver_cat = cols[0].get_text(strip=True)
                title     = cols[1].get_text(strip=True)
                firm      = cols[2].get_text(strip=True)
                raw_dt    = cols[4].get_text(strip=True)

                if not title:
                    continue

                date_str = parse_naver_date(raw_dt)
                if date_str and date_str < cutoff:
                    found_old = True
                    continue

                link = parse_naver_link(title_tag.get("href", ""))
                sector = guess_sector(naver_cat + " " + title) or "기타"
                uid = f"ind_{date_str.replace('-','')}_{firm[:4]}_{title[:8]}"

                results.append({
                    "id": uid,
                    "type": "industry",
                    "sector": sector,
                    "company": f"[{naver_cat}] 산업분석",
                    "firm": firm,
                    "title": title,
                    "date": date_str,
                    "target_price": None,
                    "summary": "",
                    "link": link,
                })

            if found_old and page > 1:
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"[오류] 산업리포트 page{page}: {e}")
            break

    return results

# ── 메인 수집 ─────────────────────────────────────────────────────────────────
def collect_all(days=14):
    existing = load_existing()
    existing_ids = {r["id"] for r in existing}
    new_reports = []

    print("[1/2] 종목 분석 리포트 수집 중...")
    for r in fetch_company_reports(days=days):
        if r["id"] not in existing_ids:
            new_reports.append(r)
            existing_ids.add(r["id"])

    print("[2/2] 산업 분석 리포트 수집 중...")
    for r in fetch_industry_reports(days=days):
        if r["id"] not in existing_ids:
            new_reports.append(r)
            existing_ids.add(r["id"])

    print(f"[수집] 신규 리포트: {len(new_reports)}개")

    all_reports = new_reports + existing
    all_reports.sort(key=lambda x: x.get("date", ""), reverse=True)
    all_reports = all_reports[:500]

    save_reports(all_reports)
    return len(new_reports)


if __name__ == "__main__":
    print("=" * 50)
    print(f"데이터 수집 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    n = collect_all(days=14)
    print(f"완료. 신규 {n}개 추가됨")
    print("=" * 50)
