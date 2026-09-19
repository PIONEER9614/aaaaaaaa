import os
import re
import requests
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from groq import Groq
from bs4 import BeautifulSoup
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

CHANNELS = [
    {"name": "미국주식 인사이트", "username": "insidertracking"},
    {"name": "주식 급등일보", "username": "faststocknews"},
]

# 폰트 설정
try:
    pdfmetrics.registerFont(TTFont("KR", "C:/Windows/Fonts/malgun.ttf"))
    pdfmetrics.registerFont(TTFont("KR-Bold", "C:/Windows/Fonts/malgunbd.ttf"))
    FONT = "KR"
    FONT_BOLD = "KR-Bold"
except Exception:
    FONT = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fetch_channel_messages(username, hours=12):
    headers = {"User-Agent": "Mozilla/5.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    messages = []  # [{"text": ..., "url": ...}]
    before_id = None

    for _ in range(10):
        url = f"https://t.me/s/{username}"
        if before_id:
            url += f"?before={before_id}"

        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        msg_elements = soup.select(".tgme_widget_message")
        if not msg_elements:
            break

        stop = False
        for msg in reversed(msg_elements):
            time_tag = msg.select_one(".tgme_widget_message_date time")
            if time_tag and time_tag.get("datetime"):
                try:
                    msg_time = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
                    if msg_time < cutoff:
                        stop = True
                        break
                except Exception:
                    pass

            text_tag = msg.select_one(".tgme_widget_message_text")
            if text_tag:
                text = text_tag.get_text(separator=" ").strip()
                if text and len(text) > 10:
                    # data-post="username/1234" → https://t.me/username/1234
                    data_post = msg.get("data-post", "")
                    msg_url = f"https://t.me/{data_post}" if data_post else ""
                    messages.append({"text": text[:400], "url": msg_url})

        if stop:
            break

        first_msg = msg_elements[0]
        data_post = first_msg.get("data-post", "")
        if "/" in data_post:
            before_id = data_post.split("/")[-1]
        else:
            break

    return messages


def summarize_chunk(client, channel_name, texts, chunk_idx, total_chunks):
    combined = "\n\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
    prompt = (
        f"다음은 '{channel_name}' 채널 메시지입니다.\n"
        f"아래 형식으로 핵심만 한국어로 정리해주세요. 번호 매기지 말고 각 항목은 '• '로 시작하세요.\n\n"
        f"[주요 종목 및 이슈]\n"
        f"• 언급된 종목명과 핵심 내용 (수치 포함)\n\n"
        f"[시장 동향]\n"
        f"• 거시경제, 섹터 흐름, 주목할 데이터\n\n"
        f"불필요한 설명 없이 팩트 위주로 간결하게 작성하세요.\n\n"
        f"메시지:\n{combined}"
    )
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"  Groq 오류: {e}")
            wait = 35 if attempt == 0 else 60
            print(f"  {wait}초 후 재시도...")
            time.sleep(wait)
    return None


def create_pdf(channel_name, summaries, messages, date_str):
    filename = f"tg_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4,
                            leftMargin=22*mm, rightMargin=22*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    title_style = ParagraphStyle(
        "title", fontName=FONT_BOLD, fontSize=18, spaceAfter=4,
        textColor=colors.HexColor("#1a1a2e")
    )
    sub_style = ParagraphStyle(
        "sub", fontName=FONT, fontSize=10, spaceAfter=0,
        textColor=colors.HexColor("#666666")
    )
    section_style = ParagraphStyle(
        "section", fontName=FONT_BOLD, fontSize=11, spaceAfter=4, spaceBefore=8,
        textColor=colors.HexColor("#16213e")
    )
    bullet_style = ParagraphStyle(
        "bullet", fontName=FONT, fontSize=9.5, spaceAfter=3, leading=15,
        leftIndent=8, textColor=colors.HexColor("#222222")
    )
    link_label_style = ParagraphStyle(
        "link_label", fontName=FONT_BOLD, fontSize=10, spaceAfter=4, spaceBefore=6,
        textColor=colors.HexColor("#16213e")
    )
    link_style = ParagraphStyle(
        "link", fontName=FONT, fontSize=8, spaceAfter=2, leading=13,
        textColor=colors.HexColor("#0066cc")
    )

    story = []
    story.append(Paragraph(f"📊 {channel_name}", title_style))
    story.append(Paragraph(f"{date_str} | 총 {len(messages)}개 메시지", sub_style))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a1a2e")))
    story.append(Spacer(1, 4*mm))

    # AI 요약
    for i, summary in enumerate(summaries, 1):
        if not summary:
            continue

        lines = summary.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 섹션 헤더: [제목], ### 제목, **제목** 등 모두 처리
            is_header = (
                (line.startswith("[") and line.endswith("]")) or
                line.startswith("###") or
                line.startswith("##") or
                (line.startswith("**") and line.endswith("**"))
            )
            if is_header:
                header_text = line.lstrip("#").strip().strip("[]").strip("*").strip()
                story.append(Spacer(1, 2*mm))
                story.append(Paragraph(f"[ {_esc(header_text)} ]", section_style))
                story.append(HRFlowable(width="100%", thickness=0.5,
                                        color=colors.HexColor("#cccccc")))
                story.append(Spacer(1, 1*mm))
            elif line.startswith("•") or line.startswith("-") or line.startswith("*"):
                text = line.lstrip("•-* ").strip()
                story.append(Paragraph(f"• {_esc(text)}", bullet_style))
            else:
                story.append(Paragraph(_esc(line), bullet_style))

        if i < len(summaries):
            story.append(Spacer(1, 3*mm))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor("#eeeeee"), lineCap="round"))
            story.append(Spacer(1, 3*mm))

    # 원문 링크 섹션
    links = [(i + 1, m["url"]) for i, m in enumerate(messages) if m.get("url")]
    if links:
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#aaaaaa")))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("원문 링크", link_label_style))
        story.append(Spacer(1, 1*mm))

        # 한 줄에 5개씩 묶어서 표시
        row_size = 5
        for row_start in range(0, len(links), row_size):
            row = links[row_start:row_start + row_size]
            parts = "　 ".join(
                f'<link href="{url}" color="#0066cc">[{idx}]</link>'
                for idx, url in row
            )
            story.append(Paragraph(parts, link_style))

    doc.build(story)
    return filename


def send_pdf(filename, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(filename, "rb") as f:
        res = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
        }, files={"document": f})
    return res.ok


def main():
    now = datetime.now()
    hours = 24
    date_str = now.strftime("%Y년 %m월 %d일")

    print(f"=== 텔레그램 채널 요약: {date_str} {now.strftime('%H:%M')} ===")

    client = Groq(api_key=GROQ_API_KEY)

    for channel in CHANNELS:
        print(f"수집 중: {channel['name']}")
        messages = fetch_channel_messages(channel["username"], hours=hours)
        print(f"수집된 메시지: {len(messages)}개")

        if not messages:
            print("  메시지 없음, 건너뜀")
            continue

        texts = [m["text"] for m in messages]
        chunk_size = 15
        chunks = [texts[i:i+chunk_size] for i in range(0, len(texts), chunk_size)]
        summaries = []

        for i, chunk in enumerate(chunks):
            print(f"  요약 중... ({i+1}/{len(chunks)})")
            summary = summarize_chunk(client, channel["name"], chunk, i+1, len(chunks))
            if summary:
                summaries.append(summary)
                print(f"    → {len(summary)}자 요약 완료")
            else:
                print(f"    → 요약 실패 (건너뜀)")
            if i < len(chunks) - 1:
                time.sleep(35)

        if not summaries:
            print("  모든 요약 실패, PDF 생성 건너뜀")
            continue

        print(f"PDF 생성 중... (요약 {len(summaries)}/{len(chunks)}개 성공)")
        filename = create_pdf(channel["name"], summaries, messages, date_str)

        caption = f"📊 {channel['name']} 요약\n{date_str} | {len(messages)}개 메시지"
        if send_pdf(filename, caption):
            print("전송 완료")
        else:
            print("전송 실패")

        os.remove(filename)


if __name__ == "__main__":
    main()
