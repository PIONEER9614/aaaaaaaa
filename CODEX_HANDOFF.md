# Codex 인수인계 프롬프트

## 프로젝트 개요

주식/금융 데이터 자동화 시스템. Python 3.11, GitHub Actions cron, 텔레그램 PDF 전송.
GitHub 레포: `https://github.com/PIONEER9614/aaaaaaaa` (브랜치: main)

---

## 현재 완성된 것들

| 파일 | 상태 | 설명 |
|------|------|------|
| `stock_agent_harness.py` | ✅ 완성 | 7-Agent 주식 분석 (재무/리서치/뉴스/밸리/가치투자/업종/전략) |
| `naver_neighbor_digest.py` | ⚠️ 완성, 미테스트 | 네이버 이웃 블로그 새 글 → LLM 요약 → 텔레그램 PDF |
| `.github/workflows/naver_neighbor_digest.yml` | ✅ 완성 | 매일 KST 오전 8시 실행 |
| `industry_intelligence.py` | ✅ 완성 | 산업별 주간 인텔리전스 |
| `paper_collector.py` | ✅ 완성 | 논문 자동 수집 + 분기별 폴더 |

---

## 즉시 해야 할 작업 (우선순위 순)

### 1. 네이버 이웃 목록 수집 완료 [가장 시급]

로그인은 이미 진행 중 (`python naver_neighbor_digest.py --login`으로 브라우저 열림).
로그인 완료 후 쿠키가 `data/naver_cookies.json`에 저장됨.

그 다음 실행:
```bash
python naver_neighbor_digest.py --fetch
```
→ `data/naver_neighbors.json` 생성됨 (블로그 80개+ JSON 배열)

생성된 JSON을 GitHub Secrets에 등록:
- Secret 이름: `NAVER_NEIGHBORS`
- 값: `data/naver_neighbors.json` 파일 전체 내용

추가로 필요한 GitHub Secrets (아직 없으면 추가):
- `NAVER_ID` = `history9614`
- `NAVER_PW` = `baeksun96141`

### 2. naver_neighbor_digest.py 테스트

```bash
python naver_neighbor_digest.py
```

정상이면: 새 글 수집 → Groq 요약 → PDF → 텔레그램 전송 → `data/naver_neighbor_history.json` 생성

실패 케이스별 대응:
- RSS 파싱 실패: `get_rss_posts()` 함수에서 XML 파싱 오류 → BeautifulSoup으로 fallback 추가
- 본문 추출 실패: `extract_content()` → iframe ID가 다를 수 있음, `id="mainFrame"` 외 다른 iframe 시도
- LLM 오류: Groq rate limit → `time.sleep(1)` 추가

### 3. 월별 섹터 로테이션 기록 시스템 [신규 개발 필요]

사용자가 원하는 것:
- 매달 어떤 섹터가 올랐고 내렸는지 자동 기록
- 왜 그랬는지 (매크로 이벤트, 뉴스) 함께 저장
- 누적되면 패턴 라이브러리가 됨

구현 방향:
```python
# sector_rotation_tracker.py
# 월 1회 실행 (매월 1일)
# 1. yfinance로 주요 섹터 ETF 월간 수익률 계산
#    한국: KODEX 반도체, KODEX 2차전지, KODEX 헬스케어 등
#    미국: XLK, XLE, XLF, XLV, XLI, XLC, XLP, XLB, XLRE, XLU
# 2. 네이버 뉴스에서 해당 월 주요 매크로 이벤트 수집
# 3. Groq로 "이번 달 섹터 로테이션 요약 + 원인 분석" 생성
# 4. data/sector_rotation_history.json 에 누적 저장
# 5. PDF + 텔레그램 전송

# 저장 형식:
{
  "2026-05": {
    "top_sectors": [{"name": "반도체", "etf": "KODEX반도체", "return": 8.2}, ...],
    "bottom_sectors": [...],
    "macro_events": ["FOMC 금리 동결", "엔비디아 실적 발표"],
    "analysis": "LLM 생성 텍스트",
    "recorded_at": "2026-06-01"
  }
}
```

GitHub Actions 워크플로우:
```yaml
# .github/workflows/sector_rotation.yml
schedule:
  - cron: "0 23 1 * *"  # 매월 2일 KST 오전 8시 (UTC 전날 23:00)
```

---

## 환경 변수 (.env)

```
TELEGRAM_BOT_TOKEN=<로컬 .env 참조>
TELEGRAM_CHAT_ID=<로컬 .env 참조>
GROQ_API_KEY=<로컬 .env 참조>
DART_API_KEY=<로컬 .env 참조>
NAVER_ID=<로컬 .env 참조>
NAVER_PW=<로컬 .env 참조>
VALLEY_EMAIL=<로컬 .env 참조>
VALLEY_PASSWORD=<로컬 .env 참조>
```
실제 값은 로컬 `.env` 파일에 있음 (GitHub에 올라가지 않음, .gitignore 처리됨)

---

## 기술 스택 / 코딩 규칙

- Python 3.11, Groq API (`llama-3.3-70b-versatile`), ReportLab PDF, Telegram Bot API
- PDF: 항상 ReportLab, `setup_font()`로 한글 폰트 (NanumGothic / 맑은 고딕)
- 새 스크립트 패턴: `load_dotenv()` → 데이터 수집 → LLM 분석 → PDF → Telegram
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 항상 포함
- GitHub Actions에서 히스토리 파일 커밋: `git push || true`로 실패 무시
- KST cron: UTC+9이므로 UTC로 변환 (KST 8시 = UTC 전날 23시)

---

## 주요 데이터 경로

```
data/
  naver_neighbors.json         # 이웃 블로그 목록 [{id, name}, ...]
  naver_neighbor_history.json  # 이미 처리한 포스트 URL 목록
  naver_cookies.json           # 네이버 로그인 쿠키 (Playwright storage_state)
  naver_research/
    _meta/manifest.json        # 네이버 리서치 리포트 메타데이터
  sector_rotation_history.json # (미생성) 월별 섹터 기록
analysis/                      # PDF 출력 폴더
papers/                        # 논문 폴더 (저널별/분기별)
```

---

## 사용자 투자 성향 (시스템 설계 참고)

- 섹터 로테이션 + 모멘텀 추종 전략 선호
- 고점 물린 경험 있어서 확신 없으면 진입 못 하는 패턴
- 원하는 것: "이 섹터 지금 모멘텀 붙고 있음" 같은 명확한 신호
- 한국+미국 주식 둘 다 커버하려고 함
- 이웃 블로그 80개+ = 본인이 신뢰하는 투자자들의 인사이트 소스

---

## 커밋 방법 (PowerShell 환경)

```powershell
git add 파일명
git commit -m @'
커밋 메시지

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
'@
git stash; git pull --rebase; git stash pop; git push
```
