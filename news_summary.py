"""
뉴스 종합 분석 시스템 v2
- 한국경제(경제/증권) + Yahoo Finance 전체 기사 수집
- 빈출 핫 이슈 TOP7 강조 분석
- 기사별 3줄 AI 요약
- 종합 시장 분석 (6개 섹션)
- PDF 생성 → 텔레그램 전송
"""

import os, re, io, time, requests, feedparser
from groq import Groq
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from collections import Counter

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("ARTICLE_BOT_TOKEN") or "").strip()
CHAT_ID   = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
GROQ_KEY  = (os.getenv("GROQ_API_KEY") or "").strip()

NEWS_FEEDS = {
    "한국경제 경제": "https://www.hankyung.com/feed/economy",
    "한국경제 증권": "https://www.hankyung.com/feed/finance",
    "Yahoo Finance":  "https://finance.yahoo.com/news/rssindex",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 폰트 ─────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    ]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_candidates if os.path.exists(p)), font)
    if font:
        pdfmetrics.registerFont(TTFont("KR", font))
        pdfmetrics.registerFont(TTFont("KR-B", bold or font))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"

# ── 유틸 ─────────────────────────────────────────────────────────────────────
def strip_html(text):
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ").replace("&amp;", "&")).strip()

def groq_call(prompt, max_tokens=1200, model="llama-3.3-70b-versatile"):
    client = Groq(api_key=GROQ_KEY)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Groq {attempt+1}] {e}")
            time.sleep(6)
    return ""

# ── RSS 수집 ──────────────────────────────────────────────────────────────────
def fetch_rss(rss_url, hours=13):
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "Mozilla/5.0"})
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        articles = []
        for entry in feed.entries[:50]:
            try:
                pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                pass
            articles.append({
                "title":   entry.get("title", "").strip(),
                "link":    entry.get("link", ""),
                "summary": strip_html(entry.get("summary", ""))[:500],
                "content": "",
                "summary3": "",
            })
        # 시간 내 기사가 없으면 최신 15개라도 가져옴
        if not articles:
            articles = [{
                "title":   e.get("title", "").strip(),
                "link":    e.get("link", ""),
                "summary": strip_html(e.get("summary", ""))[:500],
                "content": "",
                "summary3": "",
            } for e in feed.entries[:15]]
        return articles
    except Exception as e:
        print(f"[RSS 오류] {rss_url}: {e}")
        return []

# ── 기사 본문 스크래핑 ────────────────────────────────────────────────────────
def fetch_content(url, max_chars=1200):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for sel in ["article", ".article-body", ".news-content", "#articleBodyContents",
                    ".article_body", "main", ".content"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator=" ", strip=True)
                return re.sub(r"\s+", " ", text)[:max_chars]
        paras = soup.select("p")
        text = " ".join(p.get_text(strip=True) for p in paras[:12])
        return text[:max_chars]
    except Exception:
        return ""

# ── 기사 배치 3줄 요약 ────────────────────────────────────────────────────────
def ai_batch_summarize(articles, source):
    """5개씩 묶어 기사별 3줄 요약"""
    results = [""] * len(articles)
    batch_size = 5
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        prompt_lines = []
        for j, a in enumerate(batch, 1):
            body = (a.get("content") or a.get("summary") or "")[:600]
            prompt_lines.append(f"[기사{j}]\n제목: {a['title']}\n내용: {body}")

        prompt = f"""다음 {source} 기사 {len(batch)}개를 각각 3줄로 요약해줘.
핵심 수치, 종목/기업명, 시장 영향을 반드시 포함해.

{chr(10).join(prompt_lines)}

출력 형식 (반드시 지켜줘):
[기사1]
• 줄1
• 줄2
• 줄3
[기사2]
• 줄1
...
"""
        result = groq_call(prompt, max_tokens=800, model="llama-3.1-8b-instant")
        time.sleep(2)

        # 파싱
        parsed = parse_batch_result(result, len(batch))
        for k, summary in enumerate(parsed):
            results[i + k] = summary

    return results

def parse_batch_result(text, count):
    """배치 결과 파싱 → 리스트"""
    summaries = []
    for i in range(1, count + 1):
        # [기사N] 이후 텍스트 추출
        pattern = rf"\[기사{i}\](.*?)(?=\[기사{i+1}\]|$)"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            block = m.group(1).strip()
            lines = [l.strip().lstrip("•·-").strip() for l in block.split("\n") if l.strip() and l.strip() not in ["", "•"]]
            summaries.append("\n".join(f"• {l}" for l in lines[:3]) if lines else "")
        else:
            summaries.append("")
    return summaries

# ── 핫 이슈 분석 ─────────────────────────────────────────────────────────────
def ai_hot_topics(all_articles):
    """전체 기사에서 빈출 핫 이슈 TOP7 추출"""
    lines = []
    for a in all_articles:
        lines.append(f"[{a['source']}] {a['title']}")

    prompt = f"""다음은 오늘 수집된 경제·주식 뉴스 {len(all_articles)}건의 제목 목록입니다.
여러 기사에서 반복 언급되는 핫 이슈/테마를 분석해서 TOP 7을 뽑아줘.

뉴스 제목 목록:
{chr(10).join(lines[:80])}

아래 형식으로 출력해줘 (JSON 말고 텍스트로):
🔥 [이슈명] | 관련기사 N건
핵심: (이 이슈가 왜 중요한지, 어떤 영향이 있는지 2줄)
관련: (관련 종목/섹터 나열)
---
🔥 [이슈명2] ...
"""
    return groq_call(prompt, max_tokens=1000)

# ── 종합 시장 분석 ────────────────────────────────────────────────────────────
def ai_overall_analysis(all_text, label, total):
    prompt = f"""다음은 {label} 수집된 경제·주식 뉴스 {total}건의 전문입니다.
아래 6개 항목으로 종합 분석해주세요. 각 항목은 구체적 수치와 종목명을 포함할 것.

1. 📈 오늘의 핵심 시장 흐름 (5줄 이상, 지수/환율/금리 수치 포함)
2. 🏭 주요 섹터별 동향 (반도체/AI/에너지/금융/자동차/방산 등 언급된 섹터, 각 2~3줄)
3. 🌍 글로벌 매크로 이슈 (금리/환율/원자재/지정학, 4줄)
4. 💡 주목할 종목 또는 테마 (5~7개, 각 2줄 이유+리스크 포함)
5. ⚠️ 주요 리스크 요인 (3줄, 구체적 근거 포함)
6. 📋 내일·이번주 주목 포인트 (이벤트/발표 일정 포함, 3줄)

뉴스 내용:
{all_text[:6000]}

분석:"""
    return groq_call(prompt, max_tokens=1800)

# ── PDF 생성 ──────────────────────────────────────────────────────────────────
def build_pdf(news_data, hot_topics, overall_analysis, date_str, label):
    fn, fnb = setup_font()

    def S(name, **kw):
        return ParagraphStyle(name, fontName=fn, **kw)

    styles = {
        "title":    ParagraphStyle("t",  fontName=fnb, fontSize=20, leading=26, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":      S("s",  fontSize=9,  leading=13, spaceAfter=10, textColor=colors.HexColor("#666")),
        "h2":       ParagraphStyle("h2", fontName=fnb, fontSize=13, leading=18, spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#1a3a5c")),
        "h3":       ParagraphStyle("h3", fontName=fnb, fontSize=10, leading=15, spaceBefore=8,  spaceAfter=3, textColor=colors.HexColor("#c0392b")),
        "h3b":      ParagraphStyle("h3b",fontName=fnb, fontSize=10, leading=15, spaceBefore=8,  spaceAfter=3, textColor=colors.HexColor("#2c5282")),
        "body":     S("b",  fontSize=9,  leading=14, spaceAfter=3,  textColor=colors.HexColor("#222")),
        "bullet":   S("bl", fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#333"), leftIndent=10),
        "small":    S("sm", fontSize=7,  leading=11, textColor=colors.HexColor("#888")),
        "analysis": S("an", fontSize=9,  leading=15, spaceAfter=4,  textColor=colors.HexColor("#111")),
        "hot_body": S("hb", fontSize=9,  leading=14, spaceAfter=3,  textColor=colors.HexColor("#1a1a1a")),
        "art_title":ParagraphStyle("at", fontName=fnb, fontSize=8, leading=12, spaceAfter=2, textColor=colors.HexColor("#1a3a5c")),
        "art_sum":  S("as", fontSize=8,  leading=13, spaceAfter=1,  textColor=colors.HexColor("#333"), leftIndent=8),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=1.8*cm, bottomMargin=1.8*cm)
    story = []

    # ── 헤더 ──
    story.append(Paragraph("경제·주식 뉴스 종합 분석", styles["title"]))
    total = sum(len(v["articles"]) for v in news_data.values())
    story.append(Paragraph(f"{label} | {date_str}  ·  총 {total}건 분석", styles["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # ── 🔥 핫 이슈 강조 섹션 ──
    story.append(Paragraph("🔥 오늘의 핫 이슈 TOP7", styles["h2"]))
    if hot_topics:
        hot_blocks = hot_topics.split("---")
        for block in hot_blocks:
            block = block.strip()
            if not block:
                continue
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            # 이슈 제목 (🔥 로 시작하는 줄)
            title_line = lines[0]
            rest_lines = lines[1:]

            # 배경색 박스 효과 (Table 이용)
            title_para = Paragraph(title_line, styles["h3"])
            data = [[title_para]]
            t = Table(data, colWidths=[doc.width])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#FFF3CD")),
                ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#F0A500")),
                ("LEFTPADDING",  (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
                ("TOPPADDING",   (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ]))
            story.append(t)
            for l in rest_lines:
                story.append(Paragraph(l, styles["hot_body"]))
            story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 0.2*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))

    # ── 종합 시장 분석 ──
    story.append(Paragraph("📊 종합 시장 분석", styles["h2"]))
    for line in overall_analysis.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.1*cm))
        elif line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "📈", "🏭", "🌍", "💡", "⚠️", "📋")):
            story.append(Paragraph(line, styles["h3b"]))
        else:
            story.append(Paragraph(line, styles["analysis"]))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))

    # ── 소스별 기사 상세 요약 ──
    for source, data in news_data.items():
        articles = data["articles"]
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(f"📌 {source}  ({len(articles)}건)", styles["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aaa")))

        for a in articles:
            title = a["title"][:90]
            summary3 = a.get("summary3", "")

            story.append(Spacer(1, 0.15*cm))
            story.append(Paragraph(f"▶ {title}", styles["art_title"]))

            if summary3:
                for line in summary3.split("\n"):
                    line = line.strip()
                    if line:
                        story.append(Paragraph(line, styles["art_sum"]))
            elif a.get("summary"):
                story.append(Paragraph(f"• {a['summary'][:150]}", styles["art_sum"]))

            story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ddd")))

    doc.build(story)
    buf.seek(0)
    return buf

# ── 텔레그램 ─────────────────────────────────────────────────────────────────
def send_text(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text[:4000],
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    )
    print(f"[텔레그램] {r.status_code}")

def send_pdf(buf, filename, caption=""):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": CHAT_ID, "caption": caption[:1000]},
            files={"document": (filename, buf, "application/pdf")},
            timeout=60,
        )
        if not r.ok:
            print(f"[PDF 오류] {r.text[:200]}")
    except Exception as e:
        print(f"[PDF 예외] {e}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now()
    label    = "🌅 오전" if now.hour < 12 else "🌆 오후"
    date_str = now.strftime("%Y년 %m월 %d일")
    print(f"=== 뉴스 분석 v2 시작: {date_str} {now.strftime('%H:%M')} ===")

    # 시작 알림
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": f"⏳ 뉴스 분석 시작... {date_str} {label}\n(기사 수집 + AI 분석 중, 5~10분 소요)"},
        timeout=10,
    )

    # ── 1) 수집 + 본문 스크래핑 ──
    news_data = {}
    all_articles_flat = []
    all_text = ""

    for source, url in NEWS_FEEDS.items():
        print(f"  수집: {source}")
        articles = fetch_rss(url)
        if not articles:
            continue

        # 전체 기사 본문 스크래핑
        for idx, a in enumerate(articles):
            a["source"] = source
            a["content"] = fetch_content(a["link"])
            time.sleep(0.4)
            if (idx + 1) % 5 == 0:
                print(f"    스크래핑 {idx+1}/{len(articles)}")

        news_data[source] = {"articles": articles}
        all_articles_flat.extend(articles)
        for a in articles:
            body = a["content"] or a["summary"]
            all_text += f"\n[{source}] {a['title']}\n{body}\n"

        print(f"    → {len(articles)}건")

    if not news_data:
        send_text("⚠️ 뉴스 수집 실패")
        return

    total = len(all_articles_flat)
    print(f"  총 {total}건 수집 완료, AI 분석 시작...")

    # ── 2) 핫 이슈 분석 ──
    print("  핫 이슈 분석 중...")
    hot_topics = ai_hot_topics(all_articles_flat)
    time.sleep(3)

    # ── 3) 종합 시장 분석 ──
    print("  종합 분석 중...")
    overall = ai_overall_analysis(all_text, label, total)
    time.sleep(3)

    # ── 4) 기사별 3줄 요약 ──
    for source, data in news_data.items():
        print(f"  {source} 기사 요약 중...")
        summaries = ai_batch_summarize(data["articles"], source)
        for a, s in zip(data["articles"], summaries):
            a["summary3"] = s
        time.sleep(2)

    # ── 5) PDF 생성 ──
    print("  PDF 생성 중...")
    pdf = build_pdf(news_data, hot_topics, overall, date_str, label)

    # ── 6) 전송 ──
    # 핫 이슈 텍스트 요약 (텔레그램 본문)
    hot_preview = ""
    if hot_topics:
        lines = [l for l in hot_topics.split("\n") if l.startswith("🔥")][:5]
        hot_preview = "\n".join(lines)

    send_text(
        f"📰 <b>경제·주식 뉴스 분석</b>  {label}\n"
        f"{date_str}  |  총 {total}건\n\n"
        f"<b>🔥 오늘의 핫 이슈</b>\n{hot_preview}\n\n"
        f"▼ 전체 분석 PDF 확인"
    )
    time.sleep(1)
    send_pdf(pdf, f"news_{now.strftime('%Y%m%d_%H')}.pdf",
             f"📊 뉴스 종합 분석 | {date_str} {label} | {total}건")
    print("  완료!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": f"⚠️ 오류\n{str(e)[:300]}"},
                timeout=10,
            )
        except:
            pass
