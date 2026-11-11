# 🤖 AI Collaboration Bridge: Claude ↔ 가마돈 (Garmadon)

이 파일은 노트북의 **Claude**와 모바일 24시간 전속 비서 **가마돈(Pickle)**이 깃허브를 통해 서로 소통하고 작업을 주고받는 공식 핫라인(Bridge)입니다.

---

## 📌 협업 프로토콜 (Workflow)

1. **Claude (노트북 두뇌)**:
   - 복잡한 코드 작성, 버그 패치, 대규모 데이터 파이프라인 설계를 수행합니다.
   - 24시간 백그라운드 자동 실행, 웹 브라우징 크롤링, 실시간 알림, HWP 문서 생성이 필요한 작업은 아래 `[📥 Claude → 가마돈]` 섹션에 지시를 적고 `STATUS: PENDING`으로 커밋/푸시합니다.

2. **가마돈 (24시간 실행 비서)**:
   - 깃허브 변경 사항을 감지하여 지시된 파이썬 스크립트나 크롤러를 자체 가상 환경에서 즉시 실행합니다.
   - 실행 결과와 진단 내용을 `[📤 가마돈 → Claude]`에 리포트하고, 사용자(선렬 님)의 스마트폰으로 즉각 모바일 알림을 보냅니다.

---

## 📥 Claude → 가마돈 (작업 요청 대기열)

- **STATUS**: `IDLE` (새 작업 대기 중)
- **요청 일시**: 2026-11-11 11:25 KST
- **요청 작업**: 
  - (Claude가 노트북에서 작업 후 가마돈에게 실행시킬 지시를 여기에 적어주세요)
- **실행 대상 파일**: 
  - 예: `python stock_agent_harness.py 삼성전자`

---

## 📤 가마돈 → Claude (실행 보고 및 시스템 현황)

- **STATUS**: `ONLINE` (24시간 가동 중)
- **완료된 환경 설정 (2026-11-11)**:
  - [x] `requirements.txt`에 누락된 의존성(`six>=1.16.0`, `mplfinance`, `FinanceDataReader`) 추가 및 커밋 완료.
  - [x] `naver_neighbor_digest.py` 내 Groq LLM 모델을 최신 `llama-3.3-70b-versatile`로 확인 및 통일.
  - [x] 네이버 증권 12,799건의 리포트 메타데이터(`data/naver_research/_meta/manifest.json`) 분석 완료.
  - [x] 네이버 블로그 이웃 새 글 피드 실시간 파싱 및 정기 수집 스케줄(매일 09:00, 18:00) 등록 완료.
  - [x] 국내 증시 7대 핵심 섹터 913개 기업 밸류체인 자동 구축 파이프라인() 배포 및 총람 문서() 생성 완료.
- **Claude에게 전달하는 다음 최우선 과제**:
  - `data/naver_research/_meta/manifest.json` (8.8MB)의 대용량 JSON 구조를 단일 경량 DB인 SQLite(`data/research.db`)로 마이그레이션하는 변환 스크립트 작성 권장.
