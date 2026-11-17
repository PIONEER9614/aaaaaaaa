# 글로벌 IB·운용사 공개 리서치 · 헤지펀드 서한 · 어닝콜 Q&A 소스 검증표

작성: 2026-11-17 (KST) · Wrecker → Tech
대상: Hunter 리서치용. **로그인·페이월·Cloudflare 없이 원문을 실제로 열 수 있는지**를 이 문서에서 직접 확인한 결과만 적었다.

---

## 0. 이 문서를 쓰는 법

- 검증 방법: 2026-11-17 11:0x~11:4x KST에 각 URL을 **①텍스트 수집기로 직접 열고 ②안 되면 실제 브라우저로 렌더링**해서 확인했다. 확인한 최신 글 제목·발행일을 항목마다 적어 두었으니, 나중에 "그때 그 글이 있었는지" 대조하면 접근이 계속 되는지 바로 판별된다.
- 수집 등급:
  - **[A] 정적 수집** — 로그인 없이 텍스트가 그대로 나온다. 스크립트·수집기가 바로 읽는다.
  - **[B] 브라우저 렌더링 필요** — 페이월은 아니지만 자바스크립트로 그려서, 텍스트 수집기에는 빈 껍데기만 온다. 실제 브라우저(또는 헤드리스 브라우저)로 열면 전문이 그대로 보인다.
  - **[C] 실패** — 로그인·회원제·서버 오류로 원문 수집 불가.
- 수치 인용 원칙: 요약에 숫자를 쓸 때는 **원문 문장에 있는 값만** 옮긴다. 차트 안에만 있는 숫자는 텍스트로 안 나오므로 추정해서 채우지 않는다(아래 §5 참고).
- **저작권·약관 주의(공개 저장소에 특히 중요)**: 이 소스들의 본문은 대부분 "개인 열람용"이고 **재배포·전재가 금지**되어 있다. Apollo는 본문 하단에 "This presentation may not be distributed, transmitted or otherwise communicated to others in whole or in part without the express consent of Apollo Global Management, Inc."라고 명시한다. 따라서 **원문 전문을 저장소에 커밋하지 말고, 요약 + 원문 링크 + 발행일**만 남긴다. (이 문서 자체도 전문 복사가 아니라 확인 결과 기록이다.)

---

## 1. 한눈에 — 통과/탈락

| # | 소스 | 성격 | 발행 주기 | 등급 | 확인한 최신 콘텐츠(2026-11-17 기준) |
|---|---|---|---|---|---|
| 1 | Apollo **The Daily Spark** | IB 수석이코노미스트 일일 매크로 | **평일 매일** | **A** | 11-16 "Higher Rates Hit the Fiscal Side, Not the Private Sector" |
| 2 | Morgan Stanley **Ideas** | IB 리서치 + 팟캐스트 전문 | 주 2~3회 | **A** | "How AI Agents Could Disrupt Consumer Industries" / 11-12 "From AI to Air Conditioning: The Power Boom in Asia"(전문) |
| 3 | BlackRock **BII** | 세계 최대 운용사 매크로·전망 | 주 1회 + 분기 | **A** | 11-16 "AI: looking beyond the buildout"(주간) / 09-15 Q4 아웃룩 "Scarcity vs. abundance" |
| 4 | **J.P. Morgan AM** Market Updates | 미국 최대 운용사 전략가 코멘터리 | 주 1회 | **B** | 11-17 "The Technology Threat"(David Kelly, Episode 358) |
| 5 | **Goldman Sachs** Insights | IB 공개 리서치 | 주 2~3회 | **A**(기사) / **B**(목록) | 11-05 "Emerging Market Credit Shows Resilience amid Energy Shock" |
| 6 | **JPMorganChase** Insights | IB 글로벌 리서치 허브 | 주 1회 | **A** | 10-26 "Four forces shaping M&A heading into year-end" |
| 7 | Oaktree **Howard Marks 메모** | 헤지펀드 회장 정기 서한 | 분기(연 4회) | **A** | 11-11 "A Layman Thinks About AI" |
| 8 | **Bridgewater** Research & Insights | 세계 최대 헤지펀드 공개 리서치 | 월~분기 | **A** | 10-28 CEO 인터뷰 / 10-14 CIO 글로벌 아웃룩 |
| 9 | **Berkshire Hathaway** 주주서한 | 버펫 연례 서한 아카이브 | 연 1회 | **A** | 1977~2022년 서한 링크 전부 열림 |
| 10 | **Motley Fool** 어닝콜 트랜스크립트 | 어닝콜 전문(준비발언+Q&A) | 실적시즌 매일 | **A** | 11-16 AirJoule(AIRJ) Q3 2026 전문 |
| 11 | **EarningsCalls.dev** | 어닝콜 전문(화자 분리) | 실적시즌 매일 | **A** | 11-16 Tyson Foods(TSN) Q4 FY2026 — 애널리스트 실명 Q&A |
| 12 | **StockAnalysis.com** 트랜스크립트 | 어닝콜 전문 + 오디오 | 실적시즌 매일 | **A** | 11-16 Insight Molecular Diagnostics(IMDX) Q3 2026 전문 |
| 13 | **Gloom.sh** | 어닝콜 전문 + 요약·가이던스 | 실적시즌 매일 | **A** | 11-16 여러 건(BAER·GFUZ·XKB 등) |
| 14 | **Investing.com** 트랜스크립트 | 어닝콜 **요약 기사** | 매일 수십 건 | **A** | 11-16 Agora(API) Q3 2026 — 단, 원문 그대로가 아닌 정리 기사 |
| — | VIC(Value Investors Club) | 바이사이드 종목 아이디어 | 하루 1~3건 | **[로그인 필요]** | 이미 별도 경로(45일 지연 열람)로 확보 — §4 |

탈락·보류: `lettersandinterviews.com`(서버 500), `acquirersmultiple.com`(서한 아카이브 아님·종목명 멤버제), `valueinvestingworld.com`(2020년 유료 전환 후 중단), Pershing Square 분기레터 페이지(404·504), GMO Research Library(목록 빈 응답 — 미확인), SumZero(포스팅 또는 유료 라이선스 필요). 상세는 §6.

---

## 2. IB·운용사 공개 리서치 — 항목별 확인 기록

### 2.1 Apollo — The Daily Spark  **[A]**
- 목록: `https://www.apolloacademy.com/the-daily-spark/`
- 개별 글 정식 주소는 `apollo.com/wealth/insights-news/insights/daily-spark/<슬러그>` 형태로 리다이렉트된다(11-16 기준 확인).
- 성격: Apollo 수석이코노미스트 Torsten Slok(유럽 담당 Huw van Steenis 공저 다수)이 **평일 하루 1건**, 차트 1~3장 + 한 문단 "bottom line".
- 텍스트로 오는 것: 제목·발행일·본문 서술·출처 목록·개별 글 링크. **차트 그림 안의 수치 라벨은 텍스트에 없다** → 숫자를 쓸 때는 본문 문장에 적힌 값만.
- 확인 근거(11-17 조회): 11-16 "Higher Rates Hit the Fiscal Side…"에서 "interest bill has more than doubled from about $500 billion in summer 2020 to about $1.25 trillion today" 문장 확인. 11-09까지 목록에 8건 노출.
- 브리핑 활용: 하루 1건이라 놓쳐도 목록에서 날짜로 따라잡을 수 있다. **주 2회(월·목) 브리핑이면 직전 브리핑 이후 3~4건**이 쌓인다.

### 2.2 Morgan Stanley — Ideas  **[A]**
- `https://www.morganstanley.com/ideas`
- 성격: 매크로·섹터 리서치 요약 + **Thoughts on the Market 팟캐스트 전문**이 본문에 그대로 실린다(가장 값어치 있는 부분).
- 확인 근거: 11-12 "From AI to Air Conditioning: The Power Boom in Asia"(아시아 에너지 애널리스트 Mayank Maheshwari) 전문, 11-11 "Midterms Could Delay the AI Buildout, Not Derail It"(공공정책 리서치 헤드 Ariana Salvatore) 전문이 한 페이지에서 그대로 수집됨. "How AI Agents Could Disrupt Consumer Industries" 최신 노출.
- 주의: 수치가 많은데 전부 애널리스트 발언 인용 형태("we estimate ~36 trillion units by 2030")라 **출처 화자와 함께 인용**하면 신뢰도가 유지된다.

### 2.3 BlackRock Investment Institute — BII  **[A]**
- 허브: `https://www.blackrock.com/corporate/insights/blackrock-investment-institute`
- 주간: `…/blackrock-investment-institute/publications/weekly-commentary` (11-16 "AI: looking beyond the buildout")
- 분기: `…/blackrock-investment-institute/outlook` (Q4 2026 "Scarcity vs. abundance", 2026-09-15)
- 성격: 주간 시장 코멘터리(월요일), 분기 아웃룩, 자본시장가정(CMA), 지정학 리스크 대시보드. **주간 코멘터리에는 영상 스크립트 전문 + 본문 + 차트 설명**이 함께 온다.
- 확인 근거: 11-16 주간 코멘터리에서 "For the first time since 2020, we are taking a more constructive view on duration risk"(인플레연동채 비중확대) 본문 확인. Q4 아웃룩 테마 3개(AI scarcity / durable income / beyond labels)와 저자(Jean Boivin)까지 확인.
- 주의: 일부 기관용 자료는 "professional investors only" 표기가 붙는다. Hunter는 개인 리서치 용도이므로 **요약·인용은 하되 출처 표기를 유지**한다.

### 2.4 J.P. Morgan Asset Management — Market Updates  **[B]**
- `https://am.jpmorgan.com/us/en/asset-management/adv/insights/market-insights/market-updates/`
- 하위: `…/notes-on-the-week-ahead/` (David Kelly 주간), `…/weekly-market-recap/`, `…/on-the-minds-of-investors/`, `…/economic-update/`, `…/guide-to-the-markets/`
- **중요**: 텍스트 수집기로는 제목만 오고 본문이 안 나온다(자바스크립트 렌더링). **실제 브라우저로 열면 전문이 그대로 보인다** — 11-17 기준 "The Technology Threat"(Episode 358) 본문 전체·각주·섹션 앵커까지 확인.
- 접속 시 "You appear to be located in: Korea — Do you want to be redirected?" 창이 뜬다. **"No, stay on the US site"**를 눌러야 미국판 콘텐츠가 유지된다. 이걸 자동화하려면 브라우저 단계에서 이 버튼을 먼저 눌러야 한다.
- 활용: Kelly의 주간 코멘트는 매크로 해석 + 포트폴리오 함의가 한 편에 다 있어 **브리핑 본문용으로 가장 효율이 좋다**(주 1회).

### 2.5 Goldman Sachs — Insights  **[A 기사 / B 목록]**
- 목록: `https://www.goldmansachs.com/insights` — 목록 자체는 브라우저에서 카드 형태로 렌더링(수집기에는 첫 카드만 노출).
- 개별 기사: 수집기로 전문이 온다. 확인: 11-05 "Emerging Market Credit Shows Resilience amid Energy Shock"(GSAM 이머징 채권, Anupam Damani 인터뷰 형식) 전문 + 링크.
- 부가: `…/insights/top-of-mind`(Allison Nathan 매크로 인터뷰)는 브라우저 렌더링 필요(B).
- 운영 팁: 목록을 브라우저로 한 번 열어 카드 링크를 모으고, 본문은 [A]로 받는 2단 구조가 가장 싸다.

### 2.6 JPMorganChase — Insights(글로벌 리서치 허브)  **[A]**
- `https://www.jpmorgan.com/insights`
- 확인: 10-26 "Four forces shaping M&A heading into year-end", 10-19 "Global bond yields at multi-decade highs: Implications for consumers, equities and more", 10-12 "The long road home: Examining the global housing affordability crisis" — 전부 전문 수집 가능.
- J.P. Morgan AM(2.4)과 별개 도메인이고 **여기는 [A]**라서, AM 쪽이 브라우저로 막힐 때 대체재로 쓸 수 있다.

---

## 3. 헤지펀드·바이사이드 서한

### 3.1 Oaktree — Howard Marks 메모  **[A]**
- 아카이브: `https://www.oaktreecapital.com/insights/memo` (개별 메모 `…/insights/memo/<슬러그>`)
- 확인: 2026년 메모 4건이 전부 열린다 — 11-11 "A Layman Thinks About AI", 09-22 "Shall We Repeal the Laws of Economics – Part III", 04-09 "What's Going on in Private Credit?", 02-26 "AI Hurtles Ahead". 1990년대까지 전체 아카이브 목록이 한 페이지에 있다.
- 개별 메모는 **본문 전체가 텍스트로 온다**(11-11 메모에서 AI 수익성·규제·밸류에이션 논지 전문 확인).
- 주의: 구 주소 `…/insights/howard-marks-memos`는 이번 조회에서 빈 응답(HTTP 500)이었다. **`/insights/memo`를 쓸 것.**
- 주기: 대략 분기 1회(2026년 4건). 월·목 브리핑에서는 "새 메모가 있을 때만" 다루면 된다.

### 3.2 Bridgewater — Research & Insights  **[A]**
- `https://www.bridgewater.com/research-and-insights`
- 확인: 10-28 CEO 인터뷰, 10-14 Greg Jensen 글로벌 아웃룩, 09-21 "Carbon Pricing's Impact on Global Industry Is Quietly Growing", 08-27 AI 규제 논의 — 제목·날짜·저자·요약이 모두 수집되고 개별 글 링크도 노출된다.
- 성격: "Modern Mercantilism(현대 중상주의)"·AI·포트폴리오 리질리언스 3개 축의 장문 에세이. **매크로 프레임을 잡는 용도**로 Oaktree(자산·사이클 관점)와 보완적.

### 3.3 Berkshire Hathaway — 주주서한 아카이브  **[A]**
- `https://www.berkshirehathaway.com/letters/letters.html`
- 확인: 1977~2022년 서한 링크가 전부 살아 있다(HTML, 2003년 이후 PDF). 연 1회 발행.
- 주의: 이번 조회에서 **2023년 이후 서한 링크는 페이지에 보이지 않았다**(사이트 갱신 여부 미확인). 최신 서한은 버크셔 IR 공지로 따로 확인해야 한다 — **미확인 항목**.

### 3.4 Pershing Square — 분기 레터  **[C/제한]**
- `https://www.pershingsquareholdings.com` 홈은 열리지만 **분기레터 목록 페이지(`/quarterly-letters/`)는 404**, 자산 호스팅(`assets.pershingsquareholdings.com`)은 응답 지연·타임아웃이 있었다. 다운로드 전 면책 동의 절차가 있다.
- 결론: **정기 수집 대상으로는 부적합.** 필요할 때 수동으로 연다.

### 3.5 VIC(Value Investors Club) — 별도 경로
- 45일 지연 공개 + **로그인 필요**(비로그인은 "Not authorized to view this idea"). 이미 자격증명이 저장되어 있어 Wrecker 쪽에서 열람 가능.
- 이 문서의 "무로그인 소스" 묶음과는 성격이 다르므로 분리해 둔다(2026-11-17 VIC 10선은 AI_BRIDGE.md에 별도 인계).

---

## 4. 어닝콜 Q&A 트랜스크립트 — "애널리스트가 뭘 캐묻는지" 보는 용도

> 목적: 유료 증권사 리포트 없이도 **골드만·모건·BTIG·니덤 애널리스트가 실제로 던진 질문**을 그대로 읽는 것. 아래 4곳 모두 로그인 없이 열린다.

### 4.1 Motley Fool — Earnings Call Transcripts  **[A]**
- 목록 `https://www.fool.com/earnings-call-transcripts/`, 개별 `…/earnings/call-transcripts/<YYYY>/<MM>/<DD>/<슬러그>/`
- 확인: 11-16 AirJoule(AIRJ) Q3 2026 — **Takeaways 요약 → Risks → Summary → Full Conference Call Transcript**(오퍼레이터 인사말부터 Q&A까지 전문) 구조. 발언자 이름·직함 목록도 함께 온다.
- 특징: 소형·중형주 비중이 높고, 대형주는 커버가 들쭉날쭉. 실적시즌에는 하루 수십 건.

### 4.2 EarningsCalls.dev  **[A]** ★추천
- `https://earningscalls.dev/transcripts`, 회사별 이력 `https://earningscalls.dev/company/<티커>`
- 확인: 11-16 Tyson Foods(TSN) Q4 FY2026 — 화자별 세그먼트(`### 이름 / analyst|executive`)로 끊겨 있고, **Q&A에서 애널리스트 실명·소속이 그대로 나온다**(Andrew Strelzik, Tom Palmer 등 질문 원문 + 경영진 답변 전문).
- 이력: TSN 기준 2020-02-06~2026-11-16 **28건** 목록 노출.
- 무료 범위: "최신 콜은 무료, 전체 이력은 API"라고 사이트가 명시한다. API는 월 $39.99부터(무료 티어 있음), MCP 엔드포인트도 제공 → **노트북 쪽 자동화에 가장 잘 맞는 후보**(유료 전환은 Hunter 승인 사항).

### 4.3 StockAnalysis.com — Earnings Call Transcripts  **[A]** ★추천
- `https://stockanalysis.com/earnings-call-transcripts/`, 개별 `https://stockanalysis.com/stocks/<티커>/transcripts/<id>-<분기>/`
- 확인: 11-16 Insight Molecular Diagnostics(IMDX) Q3 2026 전문 — 화자별 발언 + **애널리스트 이름·소속·직함**(BTIG Mark Massaro, Needham Mike Matson, Stephens Ben Mee)이 그대로.
- 특징: 계정 없이 전문 열람, 오디오 재생·AI 요약 부가(Quartr 공급). 미국 외 종목도 커버.

### 4.4 Gloom.sh  **[A]**
- `https://gloom.sh/transcripts`
- 확인: 11-16 다수 — 각 콜마다 **요약 + 가이던스 + "애널리스트가 압박한 지점"** + 톤 점수(예: Confident 0.72)가 붙는다.
- 특징: 전문도 있지만 **한눈에 훑는 용도**로 강하다. 브리핑에서 "이번 주 실적콜에서 반복된 질문"을 뽑을 때 유용.

### 4.5 Investing.com — Earnings Call Transcripts  **[A, 단 요약형]**
- `https://www.investing.com/news/transcripts`
- 확인: 11-16 Agora(API) Q3 2026 — Key Takeaways / Financial Highlights / Outlook / **Q&A(질문 주제 요약)** 구조. **발언 원문 그대로가 아니라 정리 기사**다.
- 결론: 물량은 압도적(하루 수십~수백 건)이지만 **"애널리스트 질문 원문"이 목적이면 4.1~4.3을 먼저** 쓰고, 여기는 속보 확인용.

---

## 5. 수집기로 돌릴 때의 실무 규칙 (Tech 인계용)

1. **등급별로 경로를 나눈다** — [A]는 HTTP 텍스트 수집, [B]는 브라우저 렌더링 후 텍스트 추출. [B]를 [A]처럼 돌리면 "빈 페이지"를 성공으로 오인한다(실제로 J.P. Morgan AM이 그렇게 나왔다).
2. **차트-only 수치 금지** — Apollo·BIS류는 핵심 숫자가 그림 안에만 있다. 텍스트에 없는 값은 "차트 참조"로만 표기.
3. **발행일·제목·원문 URL 3종 세트로 저장** — 중복 판정은 이 3개 조합으로. (브리핑 스케줄은 `notes.md`에 직전 처리분을 남겨 재보고를 막는다.)
4. **지오 리다이렉트 대응** — J.P. Morgan AM은 한국 IP로 들어가면 리다이렉트 제안이 뜬다. "미국판 유지"를 먼저 눌러야 한다.
5. **전문 저장 금지** — 공개 저장소에는 요약·링크만(§0 약관). 원문 전문은 로컬(노트북)에만.
6. **실적시즌/비시즌 구분** — 4장(어닝콜)은 1·4·7·10월에 폭증하고 그 외엔 거의 없다. 브리핑에서 "새 콜 없음"이 정상인 주가 많다.

---

## 6. 탈락·보류 목록 (다시 시도하지 말 것 / 조건부)

| 소스 | 이번 결과 | 판정 |
|---|---|---|
| `lettersandinterviews.com` | HTTP 500 (2회, www/비www 모두) | **탈락** — 서버 응답 없음 |
| `acquirersmultiple.com` | 페이지는 열리나 딥밸류 스크리너 사이트, 종목명·분석은 회원제("Unlock") | **탈락** — 헤지펀드 서한 아카이브가 아님 |
| `valueinvestingworld.com` | 2020-05 공지로 유료 뉴스레터 전환, 이후 갱신 없음 | **탈락** |
| Pershing Square `/quarterly-letters/` | 404, 자산서버 타임아웃 | **보류**(수동) |
| GMO Research Library (`/europe/research-library/`, `/americas/…`) | 목록 본문 빈 응답 | **미확인** — 브라우저로 재확인 필요 |
| SumZero | 홈은 열리나 리서치 DB는 "post or pay" 라이선스 | **조건부** — 무료 열람 불가 |
| Berkshire 2023년 이후 서한 | 페이지에 링크 미노출 | **미확인** |

---

## 7. Wrecker 쪽 정기 브리핑 연결 상태

- **스케줄**: 「🌍 글로벌 IB·기관 리서치 및 헤지펀드 브리핑」 — **매주 월·목 19:00 KST** 등록 완료(2026-11-17).
- 편입 소스(이번 검증 반영): Apollo Daily Spark · Morgan Stanley Ideas · BlackRock BII(주간) · Oaktree 메모 · Bridgewater Research · VIC 신규 공개분.
- J.P. Morgan AM·Goldman은 **브라우저 렌더링이 필요**해 정기 브리핑 기본 경로에서는 빼고, 대체·보강용으로 둔다.
- 이 문서의 등급 표는 "그날 확인한 결과"다. 사이트 개편으로 등급이 바뀔 수 있으니, 실패가 반복되면 §6에 추가하고 §2·§3에서 등급을 고쳐 쓴다.

---

*검증 시각: 2026-11-17 11:00~11:50 KST. 확인되지 않은 것은 "미확인"으로 남겼다.*
