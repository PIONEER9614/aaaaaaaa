# Codex 인수인계 프롬프트

## 프로젝트 개요

주식/금융 데이터 자동화 시스템. Python 3.11, GitHub Actions cron, 텔레그램 PDF 전송.
GitHub 레포: `https://github.com/PIONEER9614/aaaaaaaa` (브랜치: main)
로컬 경로: `c:\Users\sun\OneDrive - 경희대학교\바탕 화면\claude code\`

---

## 완성된 모듈

| 파일 | 상태 | 설명 |
|------|------|------|
| `stock_agent_harness.py` | ✅ 완성+테스트 | 7-Agent 주식 분석 (재무/리서치/뉴스/밸리/가치투자DCF/업종/전략) |
| `naver_neighbor_digest.py` | ⚠️ 코드완성, 미테스트 | 네이버 이웃 블로그 새 글 → LLM 요약 → 텔레그램 PDF |
| `.github/workflows/naver_neighbor_digest.yml` | ✅ 완성 | 매일 KST 오전 8시 실행 |
| `industry_intelligence.py` | ✅ 완성 | 산업별 주간 인텔리전스 |
| `paper_collector.py` | ✅ 완성 | 논문 자동 수집 + 분기별 폴더 |

---

## 지금 당장 해야 할 작업 (순서대로)

### 1. naver_neighbor_digest.py 테스트 실행

로그인 쿠키는 이미 `data/naver_cookies.json`에 저장되어 있음.

```bash
python naver_neighbor_digest.py
```

**동작 방식:**
- `section.blog.naver.com` 이웃새글 피드를 Playwright로 스크롤 (scroll 20회)
- 포스트 URL 패턴 `blog.naver.com/[blogId]/[postNo]` 추출
- 히스토리에 없는 신규 포스트만 처리
- 본문 추출 → Groq LLM 요약 → PDF → 텔레그램 전송

**실패 케이스별 대응:**
- `data/naver_cookies.json` 없음 → `python naver_neighbor_digest.py --login` 먼저 실행 (브라우저 열림, 로그인하면 자동 저장)
- 포스트 0개 수집 → `collect_feed_posts()` 함수에서 `scroll_count=30`으로 늘리기
- `section.blog.naver.com` 구조 변경 → `a[href]` 패턴 대신 다른 선택자 시도
- 본문 추출 실패 → `extract_content()`의 iframe/selector 수정
- Groq rate limit → `time.sleep(1)` 추가

### 2. 테스트 파일 삭제

```bash
# 임시 테스트 파일 정리
del test_neighbor.py
del data\naver_login_status.png
del data\neighbor_page.png
del data\blog_main.png
del data\section_blog.png
del data\section_scroll.png
del data\buddy_test.png
```

### 3. 커밋 & 푸시

```powershell
git add naver_neighbor_digest.py
git commit -m @'
feat: 네이버 이웃새글 피드 직접 수집 방식으로 전환

section.blog.naver.com 스크롤 → 포스트 직접 추출
RSS 80개 개별 체크 방식 대신 단일 피드 스크래핑

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
'@
git stash; git pull --rebase; git stash pop; git push
```

### 4. GitHub Actions Secrets 등록

GitHub 레포 → Settings → Secrets and variables → Actions → New repository secret

필요한 Secrets (아직 없으면 추가):
- `NAVER_ID` = `history9614`
- `NAVER_PW` = `baeksun96141`

**주의:** `NAVER_NEIGHBORS` secret은 더 이상 필요 없음 (피드 직접 수집 방식으로 전환)

### 5. GitHub Actions에서 Playwright 쿠키 문제 해결

현재 워크플로우는 로컬 쿠키 파일에 의존. Actions에서는 쿠키가 없으므로 자동 로그인 구현 필요.

`naver_neighbor_digest.py`의 `collect_feed_posts()` 함수 수정:
```python
# 쿠키 없을 때 자동 로그인 시도
if not COOKIE_FILE.exists():
    auto_login()  # 아래 함수 추가

def auto_login():
    """Actions 환경에서 자동 로그인 (캡차 없을 때만 작동)"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        page.fill("#id", NAVER_ID)
        page.wait_for_timeout(500)
        page.fill("#pw", NAVER_PW)
        page.wait_for_timeout(500)
        page.click(".btn_login")
        page.wait_for_timeout(3000)
        if "nid.naver.com" not in page.url:
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            ctx.storage_state(path=str(COOKIE_FILE))
            print("  자동 로그인 성공")
        else:
            print("  자동 로그인 실패 (캡차 등) - 수동 로그인 필요")
        browser.close()
```

---

## 다음으로 개발할 것 (우선순위 순)

### 월별 섹터 로테이션 기록 시스템 [신규]

사용자가 원하는 것:
- 매달 어떤 섹터가 올랐고 내렸는지 자동 기록
- 왜 그랬는지 (매크로 이벤트, 뉴스) 함께 저장
- 누적되면 나만의 패턴 라이브러리

```python
# sector_rotation_tracker.py 신규 생성
# 월 1회 실행 (매월 1일)

# 수집할 섹터 ETF:
KR_ETFS = {
    "반도체": "091160.KS",   # KODEX 반도체
    "2차전지": "305720.KS",  # KODEX 2차전지
    "바이오": "244580.KS",   # KODEX 바이오
    "금융": "091170.KS",     # KODEX 은행
    "자동차": "091180.KS",   # KODEX 자동차
}
US_ETFS = {
    "Tech": "XLK", "Energy": "XLE", "Finance": "XLF",
    "Health": "XLV", "Industrial": "XLI", "Materials": "XLB",
}

# 저장 형식: data/sector_rotation_history.json
{
  "2026-05": {
    "top_kr": [{"sector": "반도체", "return": 8.2}, ...],
    "top_us": [{"sector": "Tech", "return": 5.1}, ...],
    "macro_events": ["FOMC 금리 동결", "엔비디아 실적 서프라이즈"],
    "analysis": "LLM 생성 분석 텍스트",
    "recorded_at": "2026-06-01"
  }
}

# GitHub Actions: 매월 2일 KST 오전 8시
# cron: "0 23 1 * *"
```

---

## 기술 스택 / 코딩 규칙

- Python 3.11, Groq API (`llama-3.3-70b-versatile`), ReportLab PDF, Telegram Bot API
- PDF: 항상 ReportLab, `setup_font()`로 한글 폰트 (NanumGothic / 맑은 고딕)
- 새 스크립트 패턴: `load_dotenv()` → 데이터 수집 → LLM 분석 → PDF → Telegram
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 항상 포함
- GitHub Actions에서 히스토리 파일 커밋: `git push || true`로 실패 무시
- KST cron: UTC+9이므로 UTC로 변환 (KST 8시 = UTC 전날 23시)
- **절대 .env 내용을 코드나 마크다운에 하드코딩 금지** (GitHub Push Protection 차단됨)

---

## 주요 데이터 경로

```
data/
  naver_cookies.json           # 네이버 로그인 쿠키 (로컬만, git 제외)
  naver_neighbors.json         # 이웃 블로그 목록 (--fetch로 생성, 현재 미사용)
  naver_neighbor_history.json  # 처리한 포스트 URL (중복 방지)
  naver_research/_meta/manifest.json  # 네이버 리서치 리포트 메타
  sector_rotation_history.json # (미생성) 월별 섹터 기록
analysis/                      # PDF 출력 폴더
papers/                        # 논문 폴더 (저널별/분기별)
```

## .gitignore 확인 (이미 설정됨)

```
.env
data/naver_cookies.json  ← 이것도 추가 권장
```

---

## 커밋 방법 (PowerShell 환경 주의)

```powershell
# heredoc은 반드시 이 형식 사용 (<<'EOF' 문법 PowerShell 미지원)
git commit -m @'
커밋 메시지

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
'@

# push 충돌 시
git stash; git pull --rebase; git stash pop; git push
```

---

## 사용자 투자 성향 (시스템 설계 참고)

- 섹터 로테이션 + 모멘텀 추종 전략 선호
- 고점 물린 경험으로 확신 없으면 진입 못 하는 패턴 → 시스템이 신호 줘야 행동 가능
- 원하는 것: "이 섹터 지금 모멘텀 붙고 있음" 같은 명확한 알림
- 이웃 블로그 80개+ = 본인이 신뢰하는 투자자들의 인사이트 소스
- 한국+미국 주식 커버, 크립토 경험 있음
