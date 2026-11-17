# VIC 2년치 원문 수집 설계서 — Tech 인계용

- 작성: 2026-11-17, Wrecker
- 대상: 노트북 Tech (Claude Code)
- 상태: **실행 보류** — 약관·robots 확인 결과. 허가를 받으면 §5 설계로 바로 구현 가능
- 사이트 조회 시각: 2026-11-17 11:2x~11:3x KST (값이 바뀌었을 수 있음)
- 요청 배경: Hunter가 VIC 최근 2년치(약 2,000건) 원문 아카이브를 원함. 클라우드 브라우저로 2,000페이지를 여는 건 사용량·차단 때문에 불가하다고 판단해 노트북 Tech가 배치 수집하는 안이 나왔음.

---

## 0. 한눈에 (결론 먼저)

1. **VIC는 자동 수집을 명시적으로 금지한다.** `robots.txt`가 전 경로 `Disallow: /`이고, 약관이 "bulk or automated downloading … scraping … using crawlers … or other automatic methods"를 직접 금지한다(원문 §1). 그래서 **2,000건 무인 배치 수집은 이 설계서에 넣지 않았다.**
2. 지금 할 수 있는 것은 **사람 속도 열람(A안)** 이다. Hunter가 실제로 필요로 하는 만큼, 로그인된 브라우저 세션에서 **한 건씩** 열어 읽고 **로컬에만** 저장한다. 11-17 오전의 10건 원문 정리도 그 방식이었다(한 건씩 열어 읽음, 대량 무인 수집 아님).
3. 규모를 살리려면 **VIC에 직접 물어보는 길(B안)** 이 정공법이다. 설계서에 보낼 편지 초안을 넣어 뒀다(발송은 하지 않았다 — Hunter 결정).
4. 허가가 나오면 **§5의 2단계(인덱스 → 원문) 설계**를 그대로 구현하면 된다. 인증 분리·체크포인트·중단/재개·차단 방지·`aaaaaaaa` 저장 규격을 전부 맞춰 뒀다.
5. 저장은 어느 경우에도 **`data/vic/` 로컬 전용(gitignore)** 이다. 이 저장소는 공개이고, 약관상 Content 재배포는 금지다.

**Tech가 지금 할 일: 없다.** Hunter가 ①B안 문의 ②A안 축소 운영 ③C안 코드 준비 중 무엇을 고르는지에 따라 갈린다. §7 참고.

---

## 1. 먼저 확인한 것 — 이 사이트는 자동 수집을 금지한다

### 1-1. robots.txt (2026-11-17 조회, 원문 그대로)

```
User-agent: *
Disallow: /
User-agent: Google-Extended
Disallow: /
```

전 경로 크롤 금지다. 예외 경로가 하나도 없다.

### 1-2. 약관 (https://valueinvestorsclub.com/terms, "Last updated October 8, 2018")

원문에서 그대로 옮긴다(강조는 이 문서 작성자).

- **금지 조항** — "USE OF SITE; PROMOTION PROHIBITED" 항:
  > "You shall not engage in, or assist others in engaging in, **any bulk or automated downloading of information on VIC**, including without limitation scraping data/information, using crawlers, or retrieving information using algorithms or other automatic methods."

  "assist others in engaging in"까지 들어 있다. 대행 수집기도 이 조항에 걸린다.
- **라이선스 범위** — "LIMITED LICENSE" 항:
  > "grants you a limited, revocable, non-transferrable license to access and use VIC **strictly for your personal, non-commercial use** for the purposes described on VIC"
- **콘텐츠 재배포 금지** — "CONTENT" 항:
  > "You may not modify, publish, transmit, participate in the transfer or sale of, **reproduce** (except as provided herein), **create derivative works from, distribute**, sell, display or in any similar way commercially exploit by resale or otherwise, any of the Content, **in whole or in part**."
  > "Reproduction of the VIC site or any Content, in whole or in part, without written permission of VIC LLC is strictly prohibited."
- 허용되는 다운로드: "To the extent that you may download or copy Content, you may only do so **for personal use(s)** and not for resale or reproduction".

### 1-3. 우리 저장소의 기존 선례

같은 기준을 이미 두 번 적용했다.

- **KRED(11-11)**: `kred.dev` robots.txt가 금지한 경로(`/futures-api/`, `/etf-api/`, `/equity-risk-api/`, `/stocks-api/`)는 "수집하지 않음"으로 닫았다.
- **글로벌 IB 소스(11-17)**: "전문 저장 금지 — 공개 저장소에는 요약·링크·발행일만. 원문 전문은 노트북 로컬에만."

VIC에 같은 기준을 적용하면 2,000건 자동 배치는 **열리지 않는다.** 이 판단이 틀렸다면 근거는 위 원문이고, 판단을 바꾸려면 VIC의 서면 허가(§4)가 필요하다.

### 1-4. 그래서 이 문서의 구성

| 층 | 무엇 | 조건 |
|---|---|---|
| §2 | VIC 실제 구조(확인한 사실) | 없음 — 사실 정리 |
| §3 | **A안** 사람 속도 열람 워크플로 | 지금 바로 가능 |
| §4 | **B안** VIC 허가 문의(편지 초안) | Hunter가 보낼지 결정 |
| §5 | **C안** 허가 후 구현 설계(2단계 수집·체크포인트·백오프·저장규격) | **VIC 서면 허가 후에만** |
| §6 | 미검증 항목 | Tech 구현 시 확인 |
| §7 | Hunter 결정 3건 | — |

---

## 2. VIC 구조 — 실제로 확인한 사실

### 2-1. Hunter 계정의 열람 범위

`/ideas` 상단 안내 원문:

> "There are **124 investment ideas you are not eligible to view**. You will not be able to post ideas or comments on the site and you are **limited to viewing ideas that are 45 days old**."

- 유료 정회원이 아니라 **45일 지연 열람 계정**이다. 즉 **2년 전 아이디어도 열람 자체는 가능**하고, 최근 45일분 124건만 막혀 있다.
- 124건 / 45일 ≈ **2.7건/일** → 2년 ≈ **약 2,000건**. (사이트가 준 숫자로 계산한 추정. brief의 "약 2,000건"과 일치한다.)
- 45일이 지나면 그 124건도 열린다. → **나중에 한 번 더 훑으면 빠진 구간이 메워진다.** 인덱스에 `visible_after`를 두는 이유(§5-5).

### 2-2. 목록 페이지 `/ideas`

2026-11-17 조회 시 화면에 있던 것:

- **필터 버튼 6개**: `Show: All Ideas` / `Sort Ideas: Most Recent` / `Market cap: 0 in M to unlimited` / `Location: All` / `Show: Long + Short` / `Go to Date: 10/02/2026`
- `Reset Filters` 링크
- **날짜 헤딩**으로 묶인 목록: `Friday, Oct 2, 2026` → `Thursday, Oct 1, 2026` → `Wednesday, Sep 30, 2026` → `Tuesday, Sep 29, 2026`
- 항목 1건의 구성: 회사명 링크 / `티커 • 가격 • $시총` / `BY 작성자` + (`Short Idea` 또는 `Reactivate` 표시) / Punch Line 앞부분(~200자) + `Read more`
- **`Load More Ideas`** 버튼 — `class="load-more load_more_ideas"`, `href="javascript:void(0)"`. **URL 페이지네이션이 아니라 JS로 이어 붙인다.**
- 날짜 필터는 `MM/DD/YYYY` 형식(`Go to Date: 10/02/2026`).
- 관측된 XHR: `https://valueinvestorsclub.com/ideas/loadideas` (그 외 `/messages/loadmsgs`). **파라미터·응답 형식은 미검증**(§6).
- 함정: 필터 드롭다운 여러 개가 **같은 id(`dropdownMenu1`)를 중복 사용**한다(화면에 `All Ideas`와 `Last 3 months` 두 벌이 잡힘). 자동화에서 id 셀렉터를 쓰면 엉뚱한 걸 누른다 → **텍스트/역할 기준 셀렉터**로 잡을 것.

### 2-3. 전체 인덱스 `/ideas/atoz`

- A–Z 색인. 상단 필터에 `Last 3 Years`, `Last 10 Years`, 그리고 **연도별(2000~2026)** 항목이 있다.
- 항목 표기: 회사명 + `(Mon YY)` 날짜 라벨. 그 앞에 `S`(Short), `W`(Contest winner) 범례 표시가 붙는다.
- 항목 링크: `/idea/<회사슬러그>/<10자리 숫자ID>` 예) `/idea/A-Living_Services_Co._Ltd/9831097989`
- 슬러그는 HTML 엔티티가 섞여 지저분하다(`A&` → `Aandamp%3B`). **슬러그는 URL 조립용일 뿐, 키로 쓰면 안 된다. 10자리 숫자 ID가 안정 키다.**
- 이 페이지는 **연도 필터로 과거 전체를 훑을 수 있는 유일한 공개 경로**다. 타임라인(`/ideas`) 수집이 빠뜨린 건을 대조하는 교차검증용으로 쓸 수 있다(허가 후).

### 2-4. 아이디어 본문 페이지 `/idea/<슬러그>/<ID>`

11-17 오전 10건을 실제로 열어 확인한 구성:

- 헤더 지표표: 가격, 시가총액, 발행주식수, 순부채, TEV, 2026E/2027E EPS·P/E·P/FCF·EBIT·TEV/EBIT (종목에 따라 0 또는 음수 표기 그대로)
- 작성일·시각(예: `10/02 18:35`, EST 기준으로 보임), 작성자 핸들, 방향(`Long`/`Short Idea`/`Reactivate`)
- 본문 섹션: `Punch Line`, `Business Overview`, `Risks` 등 — **종목마다 섹션 구성이 다르고, `Risks`가 아예 없는 글도 있다.**
- 일부 첨부(8-K 발췌, 도표)는 **이미지로만** 올라와 텍스트 추출이 안 된다(BKKT에서 확인). 차트 수치는 본문 서술에 있는 것만 얻을 수 있다.
- 열람 권한: 45일 이내 글은 비로그인·비회원에게 `Not authorized to view this idea` 응답이 온다(11-17 확인). 즉 **본문 수집은 반드시 로그인 세션이 필요**하다.

### 2-5. 로그인 게이트 설문 모달 (11-17 오전에 실제로 겪음)

- 로그인 직후 **시장 심리 설문 모달**이 뜬다. Bootstrap 계열 **static backdrop**: 배경 클릭으로 닫히지 않고 **ESC도 안 먹는다.**
- 닫으려면 3개 선택지 중 하나를 골라 제출해야 하고, 제출 뒤 결과 화면에서 `Close survey results`를 눌러야 한다.
- **그 답변이 Hunter 계정에 기록된다.** 11-17 오전에는 중간 항목(`An Average Amount of Bargain Priced Stocks`)으로 제출했다.
- 그래서 자동화 설계 원칙: **로그인을 반복하지 않는다.** 한 번 사람이 로그인해 프로필을 만들고, 수집기는 그 쿠키만 재사용한다(§5-1). 재로그인이 필요해지면 설문을 코드로 찍지 말고 **Hunter에게 넘긴다**(계정에 기록이 남는 일은 Hunter 몫).

---

## 3. A안 — 지금 허가 없이 할 수 있는 것 (사람 속도 열람)

자동 수집이 아니라 **Hunter 본인의 개인 열람**이다. 약관이 허용하는 유일한 형태("personal, non-commercial use")에 가장 가깝다.

### 3-1. 워크플로

1. Hunter가 노트북 브라우저에서 **직접 로그인**(설문 모달은 사람이 처리).
2. 필요한 만큼만 목록을 훑는다: `/ideas`에서 `Go to Date`로 날짜를 잡고, 관심 구간만 연다.
3. 마음에 걸리는 글은 **한 건씩 열어** 읽고, Tech가 그 화면을 읽어 요약·메모를 만든다(11-17 10건 방식). 한 번에 10~20건 규모.
4. 결과는 **로컬 `data/vic/notes/`** 에만 둔다. 저장소 커밋 금지.

### 3-2. 실익과 한계

- **실익**: Hunter가 지금 실제로 판단에 쓰는 건 "최근 몇 달" 아이디어다. 45일 지연 계정으로도 충분히 최신이다. 10건 정리본이 이미 파이프라인에 붙었다(`docs/vic_2026-11-17_digest.md`).
- **한계**: 2년치 전수 검색·통계는 불가능하다. "1990년대식 전수 아카이브"가 목표라면 A안으로는 도달하지 못한다. 그건 B안(허가) 없이는 안 된다.

---

## 4. B안 — VIC에 직접 묻는 길 (권장)

### 4-1. 물어야 할 것 4가지

1. 개인 회원이 **자기 계정으로 열람 가능한 아이디어 목록·본문을 개인 연구용으로 내려받아 로컬 보관**하는 것이 허용되는지.
2. 허용된다면 **허용 범위**(요청 간격, 1회 건수, 보관 기간)와 **금지 사항**.
3. 회원용 **데이터 제공·내보내기(export)·API**가 있는지, 있다면 조건과 비용.
4. 연구 목적(비상업) 사용에 대한 **서면 허가 문구**를 받을 수 있는지.

### 4-2. 편지 초안 (**발송하지 않았다** — Hunter 결정 사항)

받는 곳은 VIC 사이트의 `Contact` 경로. 영문 초안:

```
Subject: Question about member access to older ideas for personal research

Hello,

I am a member of Value Investors Club. I would like to keep a personal, non-commercial
archive of ideas I am already able to read on the site (ideas older than the 45-day
window), so that I can revisit them while researching.

Before doing anything, I want to ask what is allowed:

1. Is it permitted to save the ideas I can read to my own computer for personal research?
2. If so, are there limits I should respect (request spacing, volume, retention)?
3. Does VIC offer any member export or data access, and on what terms?
4. Could you confirm this in writing so I can follow it exactly?

I am asking rather than assuming, and I will not run any automated collection
unless you tell me it is acceptable.

Thank you,
[Hunter]
```

> 발송 여부·서명 방식은 Hunter가 정한다. 계정 이메일·이름을 이 문서에 적지 않는다.

### 4-3. 답에 따라

- **허용/조건부 허용** → §5 설계를 조건에 맞춰 조정해 실행. 받은 답(조건 원문)을 `data/vic/_meta/permission.md`에 보관한다(로컬).
- **불허** → A안만 유지. 2년치 아카이브는 다른 소스(§7-3)로 대체한다.
- **무응답** → 불허로 취급한다. 침묵은 허가가 아니다.

---

## 5. C안 — 허가를 받았을 때의 구현 설계 (**조건부**)

전제: §4에서 VIC의 서면 허가를 받았고, 그 조건을 이 설계보다 우선한다.

### 5-1. 인증 분리

- 자격증명은 저장소에 절대 넣지 않는다. 이 저장소의 기존 관례를 그대로 쓴다: `load_dotenv(Path.home() / ".claude-code-secrets" / ".env")` (다른 스크립트와 동일).
- **권장: 쿠키 재사용.** Hunter가 한 번 사람으로 로그인해 만든 브라우저 프로필(`data/vic/profile/`) 또는 `storage_state`(`data/vic/_meta/cookies.json`)을 수집기가 물려받는다. 로그인 반복 = 설문 모달 반복 = 계정 기록이 쌓이는 일이므로 피한다.
- 세션 확인: `/ideas`를 열어 `Logout` 링크가 있으면 정상, `/login`으로 리다이렉트되면 **즉시 중단**하고 exit 3으로 알린다. 재로그인은 자동으로 하지 않는다(Hunter에게 넘김).
- `.gitignore`에 `data/vic/` 전체와 `vic_cookies.json`을 넣는다(이 커밋에서 추가함).

### 5-2. 1단계 — 목록 인덱스 먼저 (원문보다 먼저)

원칙: **인덱스가 목표 구간을 다 덮기 전에는 원문을 한 건도 받지 않는다.** 원문은 비싸고(차단 위험) 인덱스는 싸다.

- 진입: `https://valueinvestorsclub.com/ideas` (Playwright, chromium, headless=false 권장 — 사이트가 headless를 구분할 수 있다는 가정은 미검증이지만 비용이 작다).
- 필터 고정: `Show: All Ideas`, `Sort Ideas: Most Recent`, `Market cap: 0~unlimited`, `Location: All`, `Show: Long + Short`.
- 진행: `Load More Ideas`를 **한 번 누르고 파싱하고, 5~10초 쉬고** 다시 누른다. 화면에 보이는 가장 오래된 날짜 헤딩이 `since`(기본 2024-11-17)보다 과거가 되면 멈춘다.
- 파싱 항목(항목마다): `id`(URL에서), `slug`, `company`, `ticker`, `price`, `mcap_mn`, `author`, `flag`(`Short Idea`/`Reactivate`/없음), `punch`(앞 200자), `posted_at`(날짜 헤딩 + 항목 순서로 복원, 시각이 없으면 날짜만), `url`, `collected_at`.
- 저장은 **append + 원자적 교체**: `index.json.tmp` → `replace`.
- 커서: `_meta/state.json`에 `{phase:"index", cursor_date, cursor_id, pages_done, updated_at}`.
- 교차검증(선택): `/ideas/atoz`에서 `2025`, `2026` 연도를 훑어 타임라인 누락분을 대조한다. 이 페이지는 항목이 수천 개라 **파싱보다 개수 세기용**으로만 쓴다.
- 마지막 45일 구간: 열람 불가 124건은 인덱스에 `status:"hidden"`으로만 남기고 **본문을 시도하지 않는다.** 45일이 지난 뒤 재실행하면 자동으로 `pending`이 되어 채워진다(`visible_after` = `posted_at` + 45일).

### 5-3. 2단계 — 원문 수집

- 인덱스에서 `pending`만 골라 `/idea/<slug>/<id>`를 연다.
- 대기 조건: 본문 컨테이너(예: `Punch Line` 텍스트 또는 헤더 지표표)가 나타날 때까지. 안 나타나면 1회만 새로고침하고, 그래도 없으면 `failed`로 남기고 넘어간다.
- 추출: 제목, 헤더 지표표(항목별 라벨·값), 작성일·시각, 작성자, 방향 플래그, 본문 섹션(제목+문단), 이미지 개수(텍스트화 불가 표시), 댓글 수(선택).
- **본문 텍스트는 마크다운으로 정규화**한다(문단·표·머리글 유지). 이미지로만 있는 도표는 `[이미지: 텍스트 없음]`으로 표시하고 수치를 추정해 채우지 않는다.
- 파일: `data/vic/raw/<id>.md` — YAML front matter + 본문.
- 순서: ① md 파일 쓰기 + fsync → ② `state.json`에 `fetched` 기록. 파일만 있고 state가 없으면 다음 실행에서 다시 받는다(중복은 무해).

### 5-4. 차단 방지 · 중단 · 재개

| 상황 | 처리 |
|---|---|
| 정상 | 요청 간 **균등 5~10초** 랜덤. 50건마다 **60~120초** 긴 휴식 |
| 429 | 60s → 180s → 600s 백오프. 그래도 429면 **중단(exit 2)** |
| 403 / 로그인 리다이렉트 | **즉시 중단(exit 3)**. 재시도 금지 — 세션 문제를 반복 요청으로 덮으면 탐지에 걸린다 |
| 5xx / 타임아웃 | 최대 3회 재시도 후 `failed`로 남기고 계속 |
| 연속 3건 실패 | **중단(exit 2)** 후 상태 저장. 다음 실행에서 이어감 |
| **동시성** | **금지.** 워커 1개, 순차. 병렬은 요청 패턴이 기계적으로 보인다 |
| 일일 상한 | 기본 **150건/일** (5~10초 간격이면 약 20~30분). 2,000건이면 약 14일 |

체크포인트 덕분에 언제 끊겨도 **손실 0**이다. `--limit`으로 한 번에 받을 양을 정하고, 스케줄러(노트북 cron·launchd)가 하루 한 번 부른다.

### 5-5. 저장 포맷 — `aaaaaaaa` 기존 규격에 맞춤

기존 스택(`data/naver_research/_meta/manifest.json` → `research_db.py` → `data/research.db`)과 같은 결을 유지한다.

```
data/vic/                      # 전부 gitignore (로컬 전용)
├── _meta/
│   ├── index.json             # 1차 원본. key = 10자리 idea id
│   ├── state.json             # 페이즈별 커서·카운터
│   ├── cookies.json           # 세션(있다면)
│   └── permission.md          # VIC 허가 원문(받았다면)
├── raw/<id>.md                # 원문 정규화 마크다운
├── notes/<날짜>_<종목>.md      # A안 수기 메모 자리
└── vic.db                     # 검색용 사본(언제든 재생성)
```

`index.json` 한 건의 형태:

```json
{
  "4596463119": {
    "company": "ICON PLC", "ticker": "ICLR", "exchange": null,
    "direction": "long", "flags": [],
    "price": 162.05, "mcap_mn": 12503,
    "author": "Fat_Tony",
    "posted_at": "2026-10-02T18:35:00-04:00", "date_precision": "minute",
    "url": "https://valueinvestorsclub.com/idea/ICON_PLC/4596463119",
    "slug": "ICON_PLC",
    "punch": "ICLR is a scaled Contract Research Organization …",
    "visible_after": "2026-11-16", "status": "fetched",
    "collected_at": "2026-11-17T11:40:00+09:00"
  }
}
```

- `date_precision`: 목록에서 날짜만 얻은 경우 `date`, 본문에서 시각까지 얻으면 `minute`. **모르는 걸 시각으로 채우지 않는다.**
- `status`: `pending` | `fetched` | `failed` | `hidden`.
- `raw/<id>.md` front matter는 `index.json`과 같은 필드 + `content_bytes`, `sha256`, `images`.

**공개 저장소에 올리는 것은 집계뿐이다.** 원한다면 `docs/vic_coverage.md`에 월별 건수·롱/숏 비율·상위 티커만 적는다(본문·작성자 목록 없음). 인덱스를 폰과 공유해야 하면 **비공개 저장소(`ai-bridge-private`)** 로 보낸다.

### 5-6. CLI

```
python vic_collector.py index  --since 2024-11-17 --until 2026-11-17 [--max-pages 40]
python vic_collector.py fetch  --limit 150 [--retry-failed]
python vic_collector.py status                      # pending/fetched/failed/hidden 집계
python vic_collector.py verify --sample 10           # 무작위 표본 본문 길이·필드 점검
python vic_db.py build | q <단어> | stats            # research_db.py와 같은 인터페이스
```

### 5-7. SQLite (`vic_db.py`)

`research_db.py`를 그대로 베낀다. 같은 명령(`build`/`q`/`stats`), 같은 구조(`meta` 테이블 + 색인), 한 가지만 다르게:

- 테이블 `ideas`: `id, date, company, ticker, direction, price, mcap_mn, author, flags, url, path, bytes, status`
- 색인: `date`, `ticker`, `author`, `(direction, date)`
- `research.db`는 "언제든 다시 만드는 사본" 취급 — `vic.db`도 gitignore에 넣고 `build`로 재생성. 원본은 `index.json` + `raw/`.
- 검색: 영어라 FTS5가 잘 맞지만, 기존 스크립트와 동작을 맞추려면 **LIKE 기본 + `--fts` 옵션**으로 두는 걸 권한다(2,000건이면 LIKE로 충분히 빠르다).

### 5-8. 검증 절차 (끝났다고 말하기 전에)

1. **인덱스**: 건수, 날짜 범위(2024-11-17 ~ 2026-11-17), 중복 id 0건.
2. **알려진 10건 대조**: `docs/vic_2026-11-17_digest.md`의 10개 URL·티커·작성자·게시일이 인덱스에 그대로 있는지. 하나라도 어긋나면 파싱이 틀린 것이다.
3. **원문**: 표본 10건의 본문 길이 중앙값 3,000자 이상, `0 byte` 0건, `Not authorized` 응답 0건.
4. **누락 점검**: `/ideas/atoz`의 2025·2026년 항목 수와 인덱스의 같은 기간 건수를 비교(±5% 넘게 벌어지면 타임라인 파싱 누락).
5. **재현성**: `state.json`을 백업해 두고 `fetch`를 중단·재개해 같은 결과가 나오는지 1회 시험.

### 5-9. 운영

- **GitHub Actions에 올리지 않는다.** 이유: ①공개 저장소 로그·시크릿에 자격증명 ②클라우드 IP에서 대량 요청 ③6시간 잡 제한 ④실패 시 자동 재시도가 요청 폭주로 보인다. **노트북 로컬 스케줄만.**
- 스케줄: 노트북이 켜져 있는 시간대에 하루 1회(`fetch --limit 150`). 14일이면 2,000건.
- 로그: `data/vic/_meta/logs/run_YYYYMMDD_HHMM.log` (기존 `naver_research/_meta/logs/` 규격과 동일).

### 5-10. 하지 말 것

- 원문·인덱스를 **공개 저장소에 커밋**하지 않는다.
- **45일 게이트를 우회**하지 않는다(열람 불가 124건).
- 자격증명을 코드·로그·브릿지·커밋 메시지에 쓰지 않는다.
- 요청을 **병렬화**하지 않는다.
- 수집분을 **외부에 배포·판매**하지 않는다(약관상 비상업 개인용).

---

## 6. 미검증 — Tech 구현 시 확인 필요

| 항목 | 상태 | 확인 방법 |
|---|---|---|
| `POST /ideas/loadideas` 파라미터·응답 형식 | **미검증** (엔드포인트만 관측) | 개발자도구 Network에서 `Load More Ideas` 클릭 시 payload |
| `Go to Date` 필터가 URL 파라미터로 재현되는지 | **미검증** | 같은 방식으로 요청 URL 확인 |
| 세션 쿠키 이름·만료·`Remember me` 지속성 | **미검증** | 쿠키 만료일 확인, 세션 재사용 시험 |
| 429·차단의 실제 발생 여부와 형태 | **미검증** (시도 0건) | 허가 후 첫날 20건만 받아 확인 |
| 설문 모달이 재로그인마다 뜨는지 | **미검증** (11-17 1회 목격) | 재로그인 1회 시험(계정에 기록 남음 — Hunter 승인 필요) |
| 아이디어 페이지 자동 파싱 셀렉터 | **미검증** (10건 수동 열람으로 내용만 확인) | 1건으로 셀렉터 확정 후 표본 검증 |
| 본문의 댓글·평점(별) 열람 가능 여부 | **미검증** — 비회원은 평점이 안 보임("Submit an idea for full membership to view ratings") | 허가 후 확인 |
| 2년치 총 건수 | **산술 추정** (124건/45일 → 약 2,000건) | 1단계 인덱스 완료 후 실측 |
| 이미지 전용 도표 텍스트화 | **불가 확인** (BKKT 8-K) | — |

---

## 7. Hunter 결정이 필요한 것

1. **B안 문의 편지를 보낼지.** 보내면 규모 문제가 정공법으로 풀린다(답까지 며칠~몇 주). 발송은 Hunter가 직접 하거나, Wrecker에게 "보내" 지시가 있어야 한다.
2. **A안으로 규모를 줄일지.** 2년치 전수가 아니라 "관심 섹터·종목만" 또는 "최근 6개월"이라면 A안만으로 충분하다.
3. **C안 코드를 허가 전에 준비해 둘지.** 코드 작성 자체는 문제가 없지만, **실행은 허가 후**다. 미리 만들어 두면 답이 오는 날 바로 돌린다.
4. (참고) 2년치 아카이브가 꼭 VIC여야 하는지 — 이미 검증한 글로벌 IB·기관 소스(Apollo, MS Ideas, Oaktree, 어닝콜)는 robots·약관 문제 없이 수집 가능하다. VIC를 "관점 표본"으로 소량만 쓰고, 물량은 그쪽으로 채우는 조합이 현실적이다.

---

## 8. 개인정보·보안 점검

- 이 문서에 **계정 아이디·비밀번호·이메일·실명·연락처를 쓰지 않았다.** 사람 표기는 코드네임 `Hunter`만 쓴다(2026-11-17 공개 문서 실명 치환 규칙).
- VIC 계정 자체의 식별자는 문서·브릿지·커밋 어디에도 남기지 않는다. Tech 쪽 로컬 `.env`에만 둔다.
- 이 저장소는 공개다. 수집물은 `data/vic/`(gitignore) 안에만 둔다.
