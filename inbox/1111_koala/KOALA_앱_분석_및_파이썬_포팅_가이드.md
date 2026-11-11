# 🐨 KOALA(경희대 도서관 클라이언트) 앱 분석 및 파이썬 포팅 가이드

- **원작 저장소**: `shlewislee/koala` (Flutter / Dart, Archived)
- **전체 명칭**: Kyunghee University's Opensource App for Library Access
- **목적**: 무겁고 느린 공식 도서관 WebView 앱을 대체하여, 최소 HTTP 요청으로 좌석 예약/연장/QR 출입을 수행하는 초경량 클라이언트.

---

## 1. 백엔드 통신 아키텍처 및 핵심 API

- **도서관 메인**: `https://lib.khu.ac.kr`
- **좌석 예약 서버**: `https://libseat.khu.ac.kr`

### (1) 로그인 암호화 프로토콜 (`lib/services/login.dart`)
1. `GET https://lib.khu.ac.kr/login` 요청으로 서버의 공개키(RSA Key) 수신.
2. 학번과 비밀번호를 `fast_rsa`로 암호화 후 `POST /login`으로 전송 → 로그인 세션 토큰 획득.
3. 세션 토큰을 헤더/쿠키에 담아 `POST https://libseat.khu.ac.kr/login_library` 호출하여 좌석 예약 세션 동기화.

### (2) 실시간 열람실 현황 조회 (`lib/services/library_rooms.dart`)
- `GET https://libseat.khu.ac.kr/libraries/lib-status/1` (1: 서울캠퍼스 중앙도서관, 2: 국제캠퍼스)
- 반환 필드: `code`(열람실 번호), `name`(열람실명), `available`(잔여 좌석 수), `inUse`(사용 중 좌석 수), `maxMi`(최대 이용 시간), `maxRenewMi`(연장 단위 시간).

### (3) 좌석 발권·연장·반납 프로토콜 (`lib/services/seat.dart`)
- **좌석 발권**: `POST https://libseat.khu.ac.kr/libraries/assign/{seatCode}`
- **좌석 연장**: `POST https://libseat.khu.ac.kr/libraries/renew/{seatCode}`
- **좌석 반납**: `POST https://libseat.khu.ac.kr/libraries/leave/{seatCode}`

### (4) 출입 게이트 QR 스트링 발급 (`lib/services/qrcode.dart`)
- `GET https://libseat.khu.ac.kr/libraries/user-status` 호출하여 유저 세션 확인 후 게이트 바코드/QR 스트링 즉시 추출.

---

## 2. `aaaaaaaa` 저장소 포팅 방안 (우 사부 작업 권고)

- **신규 모듈명**: `khu_lib/client.py`
- **포팅 핵심**:
  - `cryptography` 라이브러리로 RSA 공개키 암호화 구현.
  - `requests.Session` 객체로 도서관 및 좌석 서버 간 쿠키 영속화.
  - 가마돈의 24시간 모바일 환경과 연동하여 잔여석 감시 알림 및 원클릭 좌석 연장 CLI 기능 제공.
