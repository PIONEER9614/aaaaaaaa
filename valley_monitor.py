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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

    # 실제 API 엔드포인트: POST https://api.valley.town/auth/sign-in
    try:
        r = session.post(
            "https://api.valley.town/auth/sign-in",
            json={"email": VALLEY_EMAIL, "password": VALLEY_PASSWORD, "type": "session"},
            headers={**HEADERS, "Content-Type": "application/json", "Origin": "https://www.valley.town", "Referer": "https://www.valley.town/login"},
            timeout=20,
        )
        print(f"  로그인 응답: {r.status_code}")
        if r.status_code in (200, 201):
            # 쿠키가 세션에 자동 저장됨
            if session.cookies:
                data = r.json() if r.text else {}
                name = data.get("user", {}).get("name", "")
                print(f"  ✅ 로그인 성공 ({name})")
                return session, True
            print(f"  응답 본문: {r.text[:200]}")
    except Exception as e:
        print(f"  로그인 오류: {e}")

    print("  ❌ 로그인 실패")
    return session, False

# ── 글 목록 가져오기 ──────────────────────────────────────────────────────────
def fetch_posts(session):
    try:
        r = session.get(TARGET_URL, timeout=20)
        r.encoding = "utf-8"
    except Exception as e:
        print(f"  페이지 요청 오류: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    posts = []

    # valley.town 포스트 URL 패턴: /wsaj-premium/industry-company/<id>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # /wsaj-premium/industry-company/<24자 이상의 hex id>
        if re.match(r"^/wsaj-premium/industry-company/[a-f0-9]{10,}", href):
            full_url = "https://www.valley.town" + href
            title_el = a.find(["h1","h2","h3","h4","strong","span","p"])
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)[:80]
            if not title:
                title = href.split("/")[-1]

            date_el = a.find(["time", '[class*="date"]']) or a.find_parent(["article","li","div"])
            date = ""
            if date_el:
                t = date_el.find("time") if date_el.name != "time" else date_el
                if t:
                    date = t.get("datetime","") or t.get_text(strip=True)

            if full_url not in [p["url"] for p in posts]:
                posts.append({"title": title, "url": full_url, "date": date})

    # API 방식으로도 시도
    if not posts:
        try:
            api_r = session.get(
                "https://api.valley.town/premium-content/posts",
                params={"category": "industry-company", "page": 1, "limit": 20},
                timeout=15,
            )
            if api_r.status_code == 200:
                data = api_r.json()
                items = data if isinstance(data, list) else data.get("data") or data.get("posts") or []
                for item in items:
                    url_id = item.get("id") or item.get("slug","")
                    if url_id:
                        posts.append({
                            "title": item.get("title",""),
                            "url":   f"https://www.valley.town/wsaj-premium/industry-company/{url_id}",
                            "date":  item.get("createdAt","") or item.get("date",""),
                        })
        except Exception:
            pass

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

    story.append(Paragraph("Valley.town 새 글 알림", ST["title"]))
    story.append(Paragraph(f"{date_str}  |  신규 {len(new_posts)}건", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    for i, post in enumerate(new_posts, 1):
        story.append(Paragraph(f"{i}. {post['title']}", ST["h3"]))
        if post.get("date"):
            story.append(Paragraph(f"날짜: {post['date']}", ST["body"]))
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

    if not HISTORY_FILE.exists():
        save_history({"seen_urls": [], "last_check": ""})

    if not VALLEY_EMAIL or not VALLEY_PASSWORD:
        print("  ❌ VALLEY_EMAIL / VALLEY_PASSWORD 환경변수 없음")
        sys.exit(1)

    session, ok = login()
    if not ok:
        print("  로그인 실패 — 페이지 접근 시도 (로그인 불필요한 경우)")

    posts = fetch_posts(session)

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
