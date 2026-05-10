"""
블로그 일간/주간/월간 다이제스트
- 매일 오전 7시: 전날 글 요약
- 매주 월요일 오전 7시: 주간 총정리
- 매월 1일 오전 7시: 월간 총정리
"""

import os, re, time, requests, feedparser
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "").strip()

BLOGS = {
    "seanhong99":          "숀홍 시장정리",
    "fullmoon2050":        "보름달 시황/상한가",
    "james_lee_advisors":  "James Lee 거시경제",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
KST = timezone(timedelta(hours=9))

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("[텔레그램] 토큰 없음, 건너뜀")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # 4096자 제한 분할
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": chunk, "parse_mode": "HTML"}, timeout=15)
            if not r.ok:
                print(f"[텔레그램 오류] {r.text[:200]}")
        except Exception as e:
            print(f"[텔레그램 예외] {e}")
        time.sleep(0.3)

# ── RSS 수집 ──────────────────────────────────────────────────────────────────
def parse_pub_date(entry):
    """feedparser published_parsed → KST datetime"""
    import calendar
    t = entry.get("published_parsed")
    if t:
        return datetime.fromtimestamp(calendar.timegm(t), tz=KST)
    return None

def fetch_posts_in_range(blog_id, date_from, date_to):
    """date_from ~ date_to 사이 포스트 반환"""
    url = f"https://rss.blog.naver.com/{blog_id}.xml"
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"[RSS 오류] {blog_id}: {e}")
        return []

    results = []
    for entry in feed.entries:
        pub = parse_pub_date(entry)
        if pub is None:
            continue
        pub_date = pub.date()
        if date_from <= pub_date <= date_to:
            results.append({
                "title":   entry.get("title", "").strip(),
                "link":    entry.get("link", ""),
                "date":    pub_date.isoformat(),
                "summary": entry.get("summary", ""),
            })
    return results

# ── 본문 스크래핑 ─────────────────────────────────────────────────────────────
def fetch_post_content(link, max_chars=2000):
    """네이버 블로그 본문 텍스트 추출"""
    try:
        r = requests.get(link, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # 모바일 페이지로 변환해서 시도
        mobile_url = link.replace("blog.naver.com", "m.blog.naver.com")
        r2 = requests.get(mobile_url, headers=HEADERS, timeout=10)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        # 본문 셀렉터 순서대로 시도
        for sel in [".se-main-container", ".post-view", "#postViewArea", ".blog-post"]:
            el = soup2.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)
                return text[:max_chars]

        # 없으면 RSS summary 사용
        return ""
    except Exception as e:
        print(f"[스크래핑 오류] {link[:60]}: {e}")
        return ""

# ── AI 요약 ───────────────────────────────────────────────────────────────────
def ai_summarize(prompt, max_tokens=1200):
    client = Groq(api_key=GROQ_API_KEY)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Groq 오류 {attempt+1}] {e}")
            time.sleep(5)
    return "(AI 요약 실패)"

# ── 일간 요약 ─────────────────────────────────────────────────────────────────
def run_daily(target_date):
    """target_date 하루치 글 요약"""
    print(f"\n[일간] {target_date}")
    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, target_date, target_date)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print(f"  {target_date} 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    # 글별 요약
    summaries = []
    for p in all_posts:
        body = p["content"] or p["summary"] or p["title"]
        prompt = f"""주식 블로그 글을 5줄로 요약해줘. 핵심 종목명, 수치, 시장 판단 위주로.

블로그: {p['blog_name']}
제목: {p['title']}
내용:
{body[:1500]}

요약 (5줄):"""
        summary = ai_summarize(prompt, max_tokens=400)
        summaries.append((p['blog_name'], p['title'], summary, p['link']))
        time.sleep(1)

    # 메시지 조립
    lines = [f"📰 <b>[일간] {target_date.strftime('%m월 %d일')} 블로그 요약</b>\n"]
    for blog_name, title, summary, link in summaries:
        lines.append(f"━━━━━━━━━━━━━━━━━━")
        lines.append(f"📌 <b>{blog_name}</b>")
        lines.append(f"<i>{title}</i>")
        lines.append(summary)
        lines.append(f'<a href="{link}">▶ 원문 보기</a>')
        lines.append("")

    send_telegram("\n".join(lines))
    print(f"  일간 요약 전송 완료")

# ── 주간 요약 ─────────────────────────────────────────────────────────────────
def run_weekly(week_end):
    """week_end 기준 직전 7일 주간 요약"""
    week_start = week_end - timedelta(days=6)
    print(f"\n[주간] {week_start} ~ {week_end}")

    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, week_start, week_end)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print("  이번 주 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    # 전체 내용 통합해서 AI에게 주간 분석 요청
    combined = ""
    for p in all_posts:
        body = (p["content"] or p["summary"] or "")[:600]
        combined += f"\n[{p['date']} | {p['blog_name']}] {p['title']}\n{body}\n"

    prompt = f"""다음은 이번 주({week_start} ~ {week_end}) 주식 블로그 3곳의 글 모음입니다.
아래 형식으로 이번 주 시장 흐름을 정리해줘:

1. 이번 주 전반적인 시장 흐름 (3줄)
2. 자주 언급된 주요 종목 TOP5 (각 1줄)
3. 섹터별 동향 (반도체/방산/2차전지 등 언급된 것 위주, 3줄)
4. 블로거들이 공통적으로 주목한 포인트 (2줄)
5. 다음 주 주목할 이슈 (2줄)

블로그 내용:
{combined[:4000]}"""

    analysis = ai_summarize(prompt, max_tokens=1000)

    lines = [
        f"📊 <b>[주간] {week_start.strftime('%m.%d')} ~ {week_end.strftime('%m.%d')} 시장 총정리</b>\n",
        analysis,
        f"\n━━━━━━━━━━━━━━━━━━",
        f"📝 이번 주 글 목록 ({len(all_posts)}건):",
    ]
    for p in all_posts:
        lines.append(f"• [{p['date']}] {p['blog_name']}: {p['title'][:35]}")

    send_telegram("\n".join(lines))
    print("  주간 요약 전송 완료")

# ── 월간 요약 ─────────────────────────────────────────────────────────────────
def run_monthly(year, month):
    """해당 월 전체 요약"""
    import calendar as cal
    last_day = cal.monthrange(year, month)[1]
    month_start = datetime(year, month, 1).date()
    month_end   = datetime(year, month, last_day).date()
    print(f"\n[월간] {year}년 {month}월")

    all_posts = []
    for blog_id, blog_name in BLOGS.items():
        posts = fetch_posts_in_range(blog_id, month_start, month_end)
        for p in posts:
            p["blog_name"] = blog_name
            p["content"]   = fetch_post_content(p["link"])
            all_posts.append(p)
            time.sleep(0.5)

    if not all_posts:
        print("  이번 달 포스팅 없음")
        return

    print(f"  총 {len(all_posts)}개 글 수집")

    combined = ""
    for p in all_posts:
        body = (p["content"] or p["summary"] or "")[:300]
        combined += f"\n[{p['date']} | {p['blog_name']}] {p['title']}\n{body}\n"

    prompt = f"""다음은 {year}년 {month}월 한 달간 주식 블로그 3곳의 글 모음입니다.
아래 형식으로 이번 달 시장을 정리해줘:

1. 이번 달 전반적인 시장 흐름 (4줄)
2. 이달의 핵심 테마/섹터 (3줄)
3. 자주 등장한 주요 종목 TOP7 (각 1줄 설명)
4. 이달 최대 이슈/사건 (3줄)
5. 다음 달 주목해야 할 포인트 (3줄)

블로그 내용:
{combined[:5000]}"""

    analysis = ai_summarize(prompt, max_tokens=1200)

    lines = [
        f"📅 <b>[월간] {year}년 {month}월 시장 총정리</b>\n",
        analysis,
        f"\n━━━━━━━━━━━━━━━━━━",
        f"📝 이번 달 글 목록 ({len(all_posts)}건):",
    ]
    for p in sorted(all_posts, key=lambda x: x["date"]):
        lines.append(f"• [{p['date']}] {p['blog_name']}: {p['title'][:35]}")

    send_telegram("\n".join(lines))
    print("  월간 요약 전송 완료")

# ── 메인 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    now = datetime.now(tz=KST)
    today     = now.date()
    yesterday = today - timedelta(days=1)

    print(f"블로그 다이제스트 실행: {now.strftime('%Y-%m-%d %H:%M')} KST")
    print(f"대상 블로그: {', '.join(BLOGS.values())}")

    # 1) 일간: 항상 실행 (어제 글)
    run_daily(yesterday)

    # 2) 주간: 월요일마다 (지난 주 월~일 요약)
    if today.weekday() == 0:  # 0 = Monday
        run_weekly(yesterday)  # 어제(일요일)까지

    # 3) 월간: 매월 1일마다 (지난달 전체 요약)
    if today.day == 1:
        last_month = today.replace(day=1) - timedelta(days=1)
        run_monthly(last_month.year, last_month.month)

    print("\n완료")
