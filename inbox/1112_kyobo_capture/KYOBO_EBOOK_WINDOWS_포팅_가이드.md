# 📖 교보문고 전용 뷰어 앱 eBook 자동 캡처 & PDF 생성 가이드 (Windows)

> **수신:** 우 (노트북 Claude)  
> **발신:** 가마돈 (모바일 전속 비서)  
> **관련 요청:** 선렬 님 "Ebook를 pdf파일로 변환 가능", "교보문고 ebook전용 앱으로 보지", "니 동생한테 잘 정리해서 알려주람 너가 하지는 못하잖아"

---

## 1. 배경 및 문제 분석

1. **상황**: 선렬 님이 교보문고 전용 뷰어 앱(`교보eBook for PC`)으로 열람 중인 전자책을 태블릿/필기용 단일 PDF 파일로 변환하고자 하심.
2. **기술적 제약**:
   - 교보문고 전용 뷰어 앱에 저장된 eBook 파일은 독자 DRM 암호화가 걸려 있어 단순 파일 복호화나 Calibre 변환이 원천 차단됨.
   - GitHub에 있던 기존 인기 오픈소스(`NEM-NE/ebook-script`)는 **macOS 전용 AppleScript**로 작성되어 있어 선렬 님의 윈도우 노트북 및 리눅스 헤드리스 환경에서 실행 불가.
3. **해결책**:
   - `NEM-NE/ebook-script`의 핵심 로직(`AppleScript` 윈도우 활성화 -> 루프 [영역 캡처 -> 방향키 입력 -> 딜레이] -> `ImageMagick` 병합)을 **순수 Windows Python 스크립트**로 100% 동일하게 재구현함.
   - 가마돈은 모바일/원격 서버에서 실행되므로 선렬 님의 윈도우 로컬 GUI(교보eBook 창)를 직접 제어할 수 없음. 따라서 노트북에서 돌아가는 **우(Claude)**가 선렬 님 노트북에서 직접 실행할 수 있도록 본 가이드와 단일 파이썬 스크립트를 인계함.

---

## 2. 제공 파일 구성

- `inbox/1112_kyobo_capture/kyobo_ebook_capture_win.py`: 윈도우 환경 전용 자동 캡처 및 PDF 생성 단일 스크립트.

### 의존성 (Dependencies)
```bash
pip install pyautogui pillow
```

---

## 3. 스크립트 주요 기능 및 작동 프로토콜

1. **인터랙티브 마우스 좌표 측정**:
   - 뷰어 창 크기를 픽셀 단위로 직접 계산할 필요 없이, 실행 후 [좌상단 모서리]에서 엔터, [우하단 모서리]에서 엔터를 누르면 Bounding Box `(left, top, right, bottom)`가 자동 연산됨.
2. **5초 카운트다운**:
   - 교보문고 뷰어 창을 클릭하여 최상단 활성 윈도우(Focus)로 둘 시간을 줌.
3. **루프 자동화**:
   - `ImageGrab.grab(bbox=bbox)`로 본문 영역만 무손실 PNG로 고속 저장.
   - `pyautogui.press('right')`로 다음 페이지 넘김.
   - 지정된 딜레이(기본 1.2초, 네트워크/PC 성능에 따라 가감 가능) 준수.
4. **Pillow 내장 무손실 PDF 병합**:
   - 별도 외부 유틸리티(ImageMagick 등) 설치 없이 Pillow의 `save(..., save_all=True, append_images=...)`를 통해 단일 고화질 PDF 파일로 즉시 묶음.
5. **안전장치 (Fail-Safe)**:
   - `pyautogui.FAILSAFE = True` 적용으로, 긴급 중단이 필요할 때 마우스를 모니터 네 귀퉁이 모서리로 밀어 넣으면 즉시 안전 종료됨.

---

## 4. 우(Claude)가 노트북에서 수행할 일

1. 선렬 님이 노트북을 켜고 "가마돈 인계 받아"라고 하시면, 본 브랜치(`garmadon/inbox-1112-kyobo-capture`)에서 `kyobo_ebook_capture_win.py`를 내려받을 것.
2. 선렬 님께 교보문고 전용 뷰어 앱에서 변환할 책을 전체화면 또는 보기 편한 크기로 열어두게 안내할 것.
3. 터미널/CMD에서 `python kyobo_ebook_capture_win.py`를 실행하여 책 이름, 페이지 수, 딜레이를 넣고 캡처를 돌릴 것.
4. 완성된 PDF를 태블릿(아이패드/갤럭시탭)이나 구글 드라이브로 복사할 수 있도록 파일 경로 안내할 것.
