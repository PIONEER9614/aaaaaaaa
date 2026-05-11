"""
Valley.town 새 글 감지 → Telegram 알림
GitHub Actions에서 주기적으로 실행
"""

import os, io, re, json, sys, requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VALLEY_EMAIL    = os.getenv("VALLEY_EMAIL", "")
VALLEY_PASSWORD = os.getenv("VALLEY_PASSWORD", "")
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")
HISTORY_FILE    = Path("valley_history.json")
TARGET_URL      = "https://www.valley.town/wsaj-premium/industry-company"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf"]
    bold_c     = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        try:
            pdfmetrics.registerFont(TTFont("KR",   font))
            pdfmetrics.registerFont(TTFont("KR-B", bold or font))
            return "KR", "KR-B"
        except: pass
    return "Helvetica", "Helvetica-Bold"

# ── Valley.town 로그인 ────────────────────────────────────────────────────────
def login():
    session = requests.Session()
    session.headers.update(HEADERS)

    # 로그인 페이지에서 CSRF 토큰 가져오기
    login_page = session.get("https://www.valley.town/accounts/sign-in", timeout=15)
    soup = BeautifulSoup(login_page.text, "html.parser")

    csrf = ""
    for inp in soup.find_all("input", {"name": re.compile(r"csrf|token|_token", re.I)}):
        csrf = inp.get("value", "")
        break

    # 로그인 요청 (일반적인 form POST)
    payload = {
        "email":    VALLEY_EMAIL,
        "password": VALLEY_PASSWORD,
    }
    if csrf:
        payload["_token"] = csrf

    # 로그인 엔드포인트 추정 (일반적인 패턴들 시도)
    for endpoint in ["/accounts/sign-in", "/api/auth/login", "/login", "/accounts/login"]:
        try:
            r = session.post(
                f"https://www.valley.town{endpoint}",
                data=payload,
                timeout=15,
                allow_redirects=True,
            )
            # 로그인 성공 확인: 리다이렉트되거나 토큰 쿠키가 생기면 성공
            if r.url != f"https://www.valley.town{endpoint}" or "session" in session.cookies:
                print(f"  로그인 성공 (endpoint: {endpoint})")
                return session
        except:
            pass

    print("  로그인 실패 — 쿠키 방식으로 시도")
    return session

# ── 글 목록 가져오기 ──────────────────────────────────────────────────────────
def fetch_posts(session):
    r = session.get(TARGET_URL, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    posts = []

    # 공통 패턴으로 글 목록 추출
    for sel in ["article", ".post-item", ".article-item", '[class*="post"]', 'li[class*="item"]', "a[href*='/wsaj']"]:
        items = soup.select(sel)
        if len(items) >= 2:
            for item in items:
                link = item.find("a") or (item if item.name == "a" else None)
                href = link.get("href", "") if link else ""
                if not href or href == "/":
                    continue
                if not href.startswith("http"):
                    href = "https://www.valley.town" + href

                title_el = item.find(["h1","h2","h3","h4","strong",'.title'])
                title = title_el.get_text(strip=True) if title_el else item.get_text(strip=True)[:50]

                date_el = item.find(["time", '[class*="date"]'])
                date = date_el.get("datetime","") or (date_el.get_text(strip=True) if date_el else "")

                if title and href and "wsaj" in href:
                    posts.append({"title": title, "url": href, "date": date})

            if posts:
                break

    # 못 찾으면 JS 변수에서 추출 시도
    if not posts:
        script_data = re.findall(r'"title"\s*:\s*"([^"]+)".*?"url"\s*:\s*"([^"]+)"', r.text)
        for t, u in script_data[:10]:
            if "wsaj" in u:
                posts.append({"title": t, "url": u, "date": ""})

    print(f"  글 목록 {len(posts)}개 발견")
    return posts

# ── 히스토리 관리 ─────────────────────────────────────────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"seen_urls": []}

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

# ── PDF 생성 ──────────────────────────────────────────────────────────────────
def build_pdf(new_posts, date_str):
    fn, fnb = setup_font()
    ST = {
        "title": ParagraphStyle("ti", fontName=fnb, fontSize=16, leading=22, spaceAfter=4,  textColor=colors.HexColor("#0d1b2a")),
        "sub":   ParagraphStyle("su", fontName=fn,  fontSize=8,  leading=12, spaceAfter=10, textColor=colors.HexColor("#888")),
        "h3":    ParagraphStyle("h3", fontName=fnb, fontSize=10, leading=15, spaceBefore=8, spaceAfter=2, textColor=colors.HexColor("#1a3a5c")),
        "body":  ParagraphStyle("bo", fontName=fn,  fontSize=8,  leading=13, spaceAfter=2,  textColor=colors.HexColor("#444")),
        "link":  ParagraphStyle("lk", fontName=fn,  fontSize=7.5,leading=12, textColor=colors.HexColor("#1a6fb5")),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm,  bottomMargin=2*cm)
    story = []

    story.append(Paragraph(f"Valley.town 새 글 알림", ST["title"]))
    story.append(Paragraph(f"{date_str}  |  신규 {len(new_posts)}건", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    for i, post in enumerate(new_posts, 1):
        story.append(Paragraph(f"{i}. {post['title']}", ST["h3"]))
        if post.get("date"):
            story.append(Paragraph(f"📅 {post['date']}", ST["body"]))
        story.append(Paragraph(
            f'<a href="{post["url"]}" color="#1a6fb5">{post["url"]}</a>', ST["link"]
        ))
        story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ddd")))
        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    buf.seek(0)
    return buf

# ── Telegram 전송 ─────────────────────────────────────────────────────────────
def send_telegram(pdf_buf, filename):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    r = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT,
        "caption": f"🏔 Valley.town 새 글 알림\n{datetime.now().strftime('%Y.%m.%d %H:%M')}",
    }, files={"document": (filename, pdf_buf, "application/pdf")}, timeout=30)
    if r.ok:
        print("  ✅ Telegram 전송 완료")
    else:
        print(f"  ❌ Telegram 오류: {r.text}")

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    print(f"\n=== Valley.town 모니터링 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    if not VALLEY_EMAIL or not VALLEY_PASSWORD:
        print("  ❌ VALLEY_EMAIL / VALLEY_PASSWORD 환경변수 없음")
        sys.exit(1)

    session = login()
    posts   = fetch_posts(session)

    if not posts:
        print("  글 목록을 가져오지 못했습니다.")
        return

    history  = load_history()
    seen     = set(history.get("seen_urls", []))
    new_posts = [p for p in posts if p["url"] not in seen]

    print(f"  신규 글: {len(new_posts)}개")

    if new_posts:
        date_str = datetime.now().strftime("%Y.%m.%d %H:%M")
        pdf_buf  = build_pdf(new_posts, date_str)
        filename = f"valley_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        send_telegram(pdf_buf, filename)

        history["seen_urls"] = list(seen | {p["url"] for p in posts})
        history["last_check"] = date_str
        save_history(history)
    else:
        print("  새 글 없음")
        history["last_check"] = datetime.now().strftime("%Y.%m.%d %H:%M")
        save_history(history)

if __name__ == "__main__":
    main()
