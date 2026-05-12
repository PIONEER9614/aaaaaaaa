"""
네이버 이웃 블로그 새 글 자동 요약 → 텔레그램 PDF 전송

실행:
  python naver_neighbor_digest.py          # 새 글 수집 + 요약 + 전송
  python naver_neighbor_digest.py --login  # 브라우저 열어서 수동 로그인 (첫 실행)
  python naver_neighbor_digest.py --fetch  # 저장된 쿠키로 이웃 목록 갱신
"""

import os, io, re, sys, json, time, requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from groq import Groq

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NAVER_ID      = os.getenv("NAVER_ID", "")
NAVER_PW      = os.getenv("NAVER_PW", "")
TG_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT       = os.getenv("TELEGRAM_CHAT_ID", "")
GROQ_KEY      = os.getenv("GROQ_API_KEY", "")

NEIGHBOR_FILE = Path("data/naver_neighbors.json")
HISTORY_FILE  = Path("data/naver_neighbor_history.json")
COOKIE_FILE   = Path("data/naver_cookies.json")
HEADERS       = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_POSTS     = 40   # 하루 최대 처리 포스트 수
LOOKBACK_HOURS = 26  # 몇 시간 이내 새 글만

client = Groq(api_key=GROQ_KEY)

PROMPT = """당신은 주식/투자 블로그 인사이트 요약 전문가입니다.
아래 블로그 글들을 읽고 투자자 관점에서 핵심만 요약하세요.

각 글마다:
- 글 번호와 제목
- 핵심 2~3줄 요약 (종목명·섹터·투자 아이디어 있으면 반드시 포함)
- 투자 관련성: 높음/보통/낮음

한국어로, 간결하게."""

# ─────────────────────────────────────────────────────────────────────────────
# 폰트
# ─────────────────────────────────────────────────────────────────────────────
def setup_font():
    cands = ["/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf"]
    bolds = ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "C:/Windows/Fonts/malgunbd.ttf"]
    f = next((p for p in cands if os.path.exists(p)), None)
    b = next((p for p in bolds if os.path.exists(p)), f)
    if f:
        try:
            pdfmetrics.registerFont(TTFont("KR", f))
            pdfmetrics.registerFont(TTFont("KR-B", b or f))
            return "KR", "KR-B"
        except: pass
    return "Helvetica", "Helvetica-Bold"

# ─────────────────────────────────────────────────────────────────────────────
# 히스토리
# ─────────────────────────────────────────────────────────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    return set()

def save_history(seen: set):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 최근 2000개만 유지
    trimmed = list(seen)[-2000:]
    HISTORY_FILE.write_text(json.dumps(trimmed, ensure_ascii=False), encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# 로그인 / 쿠키
# ─────────────────────────────────────────────────────────────────────────────
def login_manual():
    """브라우저 열어서 수동 로그인 → 쿠키 저장"""
    from playwright.sync_api import sync_playwright
    print("  브라우저를 열겠습니다. 네이버에 로그인하고 블로그 메인 페이지까지 이동해주세요.")
    print("  로그인 완료 후 콘솔에서 Enter를 눌러주세요.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        input("  ↑ 로그인 완료 후 Enter ...")
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(COOKIE_FILE))
        browser.close()
    print(f"  ✅ 쿠키 저장 완료: {COOKIE_FILE}")

def get_playwright_ctx(p):
    if COOKIE_FILE.exists():
        return p.chromium.launch(headless=True).new_context(storage_state=str(COOKIE_FILE))
    return p.chromium.launch(headless=True).new_context()

# ─────────────────────────────────────────────────────────────────────────────
# 이웃 목록
# ─────────────────────────────────────────────────────────────────────────────
def fetch_neighbor_list():
    """Playwright으로 이웃 목록 수집 → data/naver_neighbors.json 저장"""
    from playwright.sync_api import sync_playwright
    neighbors = []
    seen_ids  = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=str(COOKIE_FILE) if COOKIE_FILE.exists() else None
        )
        page = ctx.new_page()

        # 이웃 목록 API (페이지네이션)
        page_no = 1
        while True:
            url = (f"https://blog.naver.com/NeighborListAsync.naver"
                   f"?blogId={NAVER_ID}&pageNo={page_no}&countPerPage=100")
            page.goto(url)
            try:
                data = json.loads(page.locator("pre").inner_text())
            except:
                content = page.content()
                m = re.search(r'\{.*\}', content, re.DOTALL)
                data = json.loads(m.group()) if m else {}

            items = data.get("neighborList") or data.get("result") or []
            if not items:
                # fallback: HTML 파싱
                page.goto(f"https://blog.naver.com/{NAVER_ID}/n/neighbor")
                page.wait_for_timeout(2000)
                soup = BeautifulSoup(page.content(), "html.parser")
                for a in soup.select("a[href*='blog.naver.com']"):
                    href = a.get("href", "")
                    m2 = re.match(r"https?://blog\.naver\.com/([A-Za-z0-9_]+)$", href)
                    if m2:
                        bid = m2.group(1)
                        if bid != NAVER_ID and bid not in seen_ids:
                            seen_ids.add(bid)
                            name = a.get_text(strip=True)[:40] or bid
                            neighbors.append({"id": bid, "name": name})
                break

            for item in items:
                bid = item.get("blogId") or item.get("neighborBlogId", "")
                if bid and bid not in seen_ids and bid != NAVER_ID:
                    seen_ids.add(bid)
                    name = item.get("blogName") or item.get("nickName", bid)
                    neighbors.append({"id": bid, "name": name})

            total = data.get("totalCount") or data.get("total", 0)
            if len(neighbors) >= total or len(items) < 100:
                break
            page_no += 1

        browser.close()

    print(f"  [이웃 목록] {len(neighbors)}개 수집")
    NEIGHBOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    NEIGHBOR_FILE.write_text(json.dumps(neighbors, ensure_ascii=False, indent=2), encoding="utf-8")
    return neighbors

def load_neighbors():
    if not NEIGHBOR_FILE.exists():
        print("  이웃 목록 없음 → --fetch 로 먼저 수집하세요")
        return []
    return json.loads(NEIGHBOR_FILE.read_text(encoding="utf-8"))

# ─────────────────────────────────────────────────────────────────────────────
# RSS 새 글 수집
# ─────────────────────────────────────────────────────────────────────────────
def parse_rss_date(s):
    try:
        return parsedate_to_datetime(s)
    except:
        return None

def get_rss_posts(blog_id, cutoff_dt):
    """RSS에서 cutoff 이후 새 글 반환"""
    url = f"https://rss.blog.naver.com/{blog_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if not r.ok: return []
        root = ET.fromstring(r.content)
        posts = []
        for item in root.findall(".//item"):
            link  = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or "").strip()
            pub   = parse_rss_date(item.findtext("pubDate") or "")
            desc  = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:400]
            if not link: continue
            if pub and pub < cutoff_dt: continue
            posts.append({"blog_id": blog_id, "title": title,
                          "link": link, "pub": pub.isoformat() if pub else "",
                          "desc": desc})
        return posts
    except:
        return []

def extract_content(url):
    """네이버 블로그 본문 텍스트 (iframe 처리)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        iframe = soup.find("iframe", id="mainFrame")
        if iframe:
            src = iframe.get("src", "")
            if src.startswith("/"):
                src = "https://blog.naver.com" + src
            r2   = requests.get(src, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r2.text, "html.parser")
        for sel in [".se-main-container", "#postViewArea", ".post-view", "main"]:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator=" ", strip=True)[:1500]
        return soup.get_text(separator=" ", strip=True)[:1500]
    except:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# LLM 요약
# ─────────────────────────────────────────────────────────────────────────────
def summarize_blog_posts(blog_name, posts):
    """한 블로그의 새 글들을 한 번에 요약"""
    lines = [f"블로그: {blog_name}\n"]
    for i, p in enumerate(posts, 1):
        lines.append(f"[{i}] {p['title']}")
        if p.get("content"):
            lines.append(p["content"][:800])
        elif p.get("desc"):
            lines.append(p["desc"])
        lines.append("")
    user_input = "\n".join(lines)
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"system","content":PROMPT},
                      {"role":"user","content":user_input}],
            temperature=0.3, max_tokens=1024,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"요약 실패: {e}"

# ─────────────────────────────────────────────────────────────────────────────
# PDF 생성
# ─────────────────────────────────────────────────────────────────────────────
def build_pdf(digest_items, date_str):
    """digest_items: [{"blog_name":..., "posts":[...], "summary":...}]"""
    fn, fnb = setup_font()
    ST = {
        "title": ParagraphStyle("t", fontName=fnb, fontSize=16, leading=22, spaceAfter=4,
                                textColor=colors.HexColor("#0d1b2a")),
        "sub":   ParagraphStyle("s", fontName=fn,  fontSize=8,  leading=12, spaceAfter=10,
                                textColor=colors.HexColor("#666")),
        "blog":  ParagraphStyle("b", fontName=fnb, fontSize=11, leading=16, spaceBefore=8,
                                spaceAfter=2, textColor=colors.HexColor("#1a3a5c")),
        "post":  ParagraphStyle("p", fontName=fn,  fontSize=8,  leading=12, spaceAfter=1,
                                textColor=colors.HexColor("#555")),
        "body":  ParagraphStyle("bd", fontName=fn, fontSize=8,  leading=13, spaceAfter=2,
                                textColor=colors.HexColor("#333")),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm,  bottomMargin=2*cm)
    story = []
    total_posts = sum(len(d["posts"]) for d in digest_items)
    story.append(Paragraph("이웃 블로그 인사이트 다이제스트", ST["title"]))
    story.append(Paragraph(f"{date_str}  |  블로그 {len(digest_items)}개  |  새 글 {total_posts}건", ST["sub"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    for item in digest_items:
        story.append(Paragraph(f"📝 {item['blog_name']}", ST["blog"]))
        for p in item["posts"]:
            title_clean = re.sub(r"[<>&]", lambda m: {"<":"&lt;",">":"&gt;","&":"&amp;"}[m.group()], p["title"])
            story.append(Paragraph(f"  · {title_clean}", ST["post"]))
        story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#ccc")))
        for line in (item["summary"] or "").split("\n"):
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line.strip())
            if not line:
                story.append(Spacer(1, 0.1*cm)); continue
            line = re.sub(r"[<>&]", lambda m: {"<":"&lt;",">":"&gt;","&":"&amp;"}[m.group()], line)
            try:
                story.append(Paragraph(line, ST["body"]))
            except:
                story.append(Paragraph(line[:200], ST["body"]))
        story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────
def send_telegram(pdf_buf, date_str, total_posts):
    if not TG_TOKEN or not TG_CHAT:
        print("  Telegram 설정 없음"); return
    fname = f"이웃블로그_{date_str.replace('.','')}.pdf"
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
        data={"chat_id": TG_CHAT,
              "caption": f"📚 이웃 블로그 인사이트\n{date_str}  새 글 {total_posts}건"},
        files={"document": (fname, pdf_buf, "application/pdf")}, timeout=30)
    print("  ✅ Telegram 전송 완료" if r.ok else f"  ❌ {r.text[:100]}")

# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    if "--login" in args:
        login_manual()
        return

    if "--fetch" in args:
        print("[이웃 목록 갱신]")
        fetch_neighbor_list()
        return

    # ── 새 글 수집 ──
    date_str  = datetime.now().strftime("%Y.%m.%d")
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    seen      = load_history()
    neighbors = load_neighbors()
    if not neighbors:
        return

    print(f"[새 글 수집] 이웃 {len(neighbors)}개 / {LOOKBACK_HOURS}시간 이내")
    all_new_posts = []

    for n in neighbors:
        posts = get_rss_posts(n["id"], cutoff_dt)
        new   = [p for p in posts if p["link"] not in seen]
        if new:
            print(f"  {n['name']} ({n['id']}): 새 글 {len(new)}건")
            all_new_posts.append({"blog_name": n["name"], "blog_id": n["id"], "posts": new})
        if sum(len(x["posts"]) for x in all_new_posts) >= MAX_POSTS:
            break
        time.sleep(0.15)

    total = sum(len(x["posts"]) for x in all_new_posts)
    print(f"\n  총 {total}건 새 글 (블로그 {len(all_new_posts)}개)\n")

    if not all_new_posts:
        print("  새 글 없음")
        return

    # ── 본문 추출 ──
    print("[본문 추출]")
    for item in all_new_posts:
        for p in item["posts"]:
            p["content"] = extract_content(p["link"])
            time.sleep(0.2)

    # ── LLM 요약 ──
    print("[LLM 요약]")
    digest_items = []
    for item in all_new_posts:
        print(f"  {item['blog_name']} ...")
        summary = summarize_blog_posts(item["blog_name"], item["posts"])
        digest_items.append({
            "blog_name": item["blog_name"],
            "posts":     item["posts"],
            "summary":   summary,
        })
        time.sleep(0.5)

    # ── PDF + 전송 ──
    print("\n[PDF 생성]")
    pdf_buf = build_pdf(digest_items, date_str)
    out = Path("analysis")
    out.mkdir(exist_ok=True)
    path = out / f"이웃블로그_{date_str.replace('.','')}.pdf"
    path.write_bytes(pdf_buf.getvalue())
    print(f"  저장: {path}")

    pdf_buf.seek(0)
    send_telegram(pdf_buf, date_str, total)

    # ── 히스토리 업데이트 ──
    for item in all_new_posts:
        for p in item["posts"]:
            seen.add(p["link"])
    save_history(seen)
    print("  히스토리 저장 완료")


if __name__ == "__main__":
    main()
