# -*- coding: utf-8 -*-
"""
교보문고 Ebook / 전자도서관 캡처 스크립트 (Windows 포팅 버전)
원본 Mac 스크립트(NEM-NE/ebook-script)의 동작을 Windows Python 환경으로 100% 동일하게 구현한 스크립트입니다.

[필요 라이브러리 설치 (노트북 터미널/CMD)]:
    pip install pyautogui pillow

[작동 순서]:
1. 책 제목, 총 페이지 수, 페이지 넘김 딜레이(초)를 입력합니다.
2. 캡처할 영역의 [좌상단]과 [우하단] 좌표를 마우스로 쉽게 찍습니다.
3. 5초 카운트다운 동안 교보문고 뷰어를 맨 앞에 띄워둡니다.
4. 지정한 페이지 수만큼 [캡처 -> 오른쪽 방향키 입력 -> 딜레이]를 자동 반복합니다.
5. 캡처가 끝나면 Pillow로 PNG 파일들을 하나의 깔끔한 PDF로 자동 병합합니다.
"""

import os
import sys
import time
from PIL import Image, ImageGrab
import pyautogui

# 긴급 중지: 마우스를 모니터 네 귀퉁이(화면 맨 구석)로 밀어넣으면 즉시 안전 종료
pyautogui.FAILSAFE = True

def get_coordinates():
    print("\n[1단계: 캡처 영역 설정]")
    print("교보문고 뷰어의 책 본문 영역 좌표를 설정합니다.")
    input(">> 캡처할 영역의 [왼쪽 위(좌상단)] 모서리에 마우스를 올리고 Enter를 누르세요...")
    x1, y1 = pyautogui.position()
    print(f"   -> 좌상단 좌표 기억 완료: ({x1}, {y1})")

    input(">> 캡처할 영역의 [오른쪽 아래(우하단)] 모서리에 마우스를 올리고 Enter를 누르세요...")
    x2, y2 = pyautogui.position()
    print(f"   -> 우하단 좌표 기억 완료: ({x2}, {y2})")

    left = min(x1, x2)
    top = min(y1, y2)
    right = max(x1, x2)
    bottom = max(y1, y2)
    width = right - left
    height = bottom - top

    print(f"   => 최종 캡처 영역: Left={left}, Top={top}, Width={width}, Height={height}")
    return (left, top, right, bottom)

def main():
    print("=" * 60)
    print("   교보문고 E-Book 자동 캡처 & PDF 생성기 (Windows)")
    print("=" * 60)

    book_name = input("\n1. 책 제목 (PDF 파일명이 됩니다): ").strip()
    if not book_name:
        book_name = f"교보Ebook_{int(time.time())}"

    while True:
        try:
            pages = int(input("2. 캡처할 총 페이지 수: "))
            if pages > 0:
                break
        except ValueError:
            pass
        print("올바른 숫자를 입력해주세요.")

    delay_input = input("3. 페이지 넘김 대기 시간(초) [기본값: 1.2초]: ").strip()
    delay = float(delay_input) if delay_input else 1.2

    bbox = get_coordinates()

    # 이미지 임시 저장 폴더
    temp_dir = os.path.join(os.getcwd(), f"temp_{book_name}")
    os.makedirs(temp_dir, exist_ok=True)

    print("\n" + "=" * 60)
    print(f"준비 완료! 5초 뒤에 자동 캡처가 시작됩니다.")
    print("지금 교보문고 뷰어 창을 클릭해서 맨 앞으로 띄워두세요!")
    print("※ 긴급 중단 방법: 마우스를 화면 맨 구석(모서리)으로 확 던지세요.")
    print("=" * 60)

    for sec in range(5, 0, -1):
        print(f"{sec}초 전...", end="\r")
        time.sleep(1)
    print("캡처 시작!                            ")

    image_paths = []
    try:
        for p in range(1, pages + 1):
            time.sleep(delay)

            # 화면 영역 캡처 (Windows Pillow ImageGrab)
            img = ImageGrab.grab(bbox=bbox)
            file_name = f"page_{p:05d}.png"
            file_path = os.path.join(temp_dir, file_name)
            img.save(file_path, "PNG")
            image_paths.append(file_path)

            print(f"[{p}/{pages}] 페이지 캡처 완료 -> 다음 페이지로 이동")

            # 마지막 페이지가 아니면 오른쪽 방향키 입력
            if p < pages:
                pyautogui.press("right")

    except KeyboardInterrupt:
        print("\n사용자에 의해 작업이 일시 중단되었습니다.")
    except Exception as e:
        print(f"\n캡처 중단 발생: {e}")

    if not image_paths:
        print("캡처된 이미지가 없습니다.")
        return

    # PDF 병합
    output_pdf = os.path.join(os.getcwd(), f"{book_name}.pdf")
    print(f"\nPDF 파일 병합 중... ({len(image_paths)}페이지)")

    try:
        first_img = Image.open(image_paths[0]).convert("RGB")
        other_imgs = [Image.open(p).convert("RGB") for p in image_paths[1:]]

        first_img.save(
            output_pdf,
            "PDF",
            resolution=100.0,
            save_all=True,
            append_images=other_imgs
        )
        print("=" * 60)
        print(f"🎉 PDF 생성 완료!: {output_pdf}")
        print("=" * 60)

        # 임시 이미지 정리 여부
        clean = input("임시 캡처 이미지들을 삭제하시겠습니까? (Y/n): ").strip().lower()
        if clean in ("", "y", "yes"):
            for p in image_paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass
            print("임시 파일 정리 완료.")

    except Exception as e:
        print(f"PDF 병합 중 오류: {e}")

if __name__ == "__main__":
    main()
