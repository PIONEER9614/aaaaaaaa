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
    """브라우저 열어서 수동 로그인 → 로그인 감지 → 쿠키 자동 저장"""
    from playwright.sync_api import sync_playwright
    print("  브라우저가 열립니다. 네이버에 로그인해주세요.")
    print("  로그인 완료되면 자동으로 쿠키가 저장됩니다. (최대 120초 대기)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        for _ in range(120):
            page.wait_for_timeout(1000)
            if "nid.naver.com" not in page.url:
                print(f"  로그인 감지!")
                break
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(COOKIE_FILE))
        browser.close()
    print(f"  ✅ 쿠키 저장 완료: {COOKIE_FILE}")

def auto_login():
    """GitHub Actions 환경에서 자동 로그인 (캡차 없을 때만 작동)"""
    if not NAVER_ID or not NAVER_PW:
        print("  NAVER_ID / NAVER_PW 환경변수 없음")
        return False
    from playwright.sync_api import sync_playwright
    print("  자동 로그인 시도 중...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto("https://nid.naver.com/nidlogin.login")
            page.wait_for_timeout(1000)
            page.fill("#id", NAVER_ID)
            page.wait_for_timeout(500)
            page.fill("#pw", NAVER_PW)
            page.wait_for_timeout(500)
            page.click(".btn_login")
            page.wait_for_timeout(3000)
            if "nid.naver.com" not in page.url:
                COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=str(COOKIE_FILE))
                browser.close()
                print("  ✅ 자동 로그인 성공")
                return True
            else:
                browser.close()
                print("  ❌ 자동 로그인 실패 (캡차 등) — 로컬에서 --login 실행 필요")
                return False
    except Exception as e:
        print(f"  ❌ 자동 로그인 오류: {e}")
        return False

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

    def extract_blog_ids(html):
        soup = BeautifulSoup(html, "html.parser")
        found = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"blog\.naver\.com/([A-Za-z0-9_]{4,})", href)
            if m:
                bid = m.group(1)
                if bid != NAVER_ID and bid not in seen_ids and bid not in ("PostList", "PostView", "search"):
                    seen_ids.add(bid)
                    name = a.get_text(strip=True)[:40] or bid
                    found.append({"id": bid, "name": name})
        return found

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=str(COOKIE_FILE) if COOKIE_FILE.exists() else None
        )
        page = ctx.new_page()

        # 이웃 관리 페이지 (스크롤 방식)
        for url in [
            f"https://blog.naver.com/{NAVER_ID}/n/neighbor",
            f"https://blog.naver.com/NeighborList.naver?blogId={NAVER_ID}",
        ]:
            page.goto(url)
            page.wait_for_timeout(2500)
            # 스크롤로 더 불러오기
            for _ in range(10):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
            found = extract_blog_ids(page.content())
            neighbors.extend(found)
            print(f"  {url.split('?')[0][-40:]} → {len(found)}개")
            if len(neighbors) > 10:
                break

        # 이웃 새글 피드에서도 추가 수집
        page.goto(f"https://blog.naver.com/{NAVER_ID}")
        page.wait_for_timeout(2000)
        found2 = extract_blog_ids(page.content())
        neighbors.extend(found2)

        browser.close()

    # 중복 제거
    seen = set()
    unique = []
    for n in neighbors:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique.append(n)

    print(f"  [이웃 목록] 총 {len(unique)}개 수집")
    NEIGHBOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    NEIGHBOR_FILE.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    return unique

def load_neighbors():
    if not NEIGHBOR_FILE.exists():
        print("  이웃 목록 없음 → --fetch 로 먼저 수집하세요")
        return []
    return json.loads(NEIGHBOR_FILE.read_text(encoding="utf-8"))

# ─────────────────────────────────────────────────────────────────────────────
# 이웃새글 피드 직접 수집 (section.blog.naver.com)
# ─────────────────────────────────────────────────────────────────────────────
def collect_feed_posts(scroll_count=20):
    """로그인 쿠키로 이웃새글 피드 스크롤 → 포스트 목록 반환"""
    from playwright.sync_api import sync_playwright
    if not COOKIE_FILE.exists():
        if not auto_login():
            print("  쿠키 없음 → --login 먼저 실행하세요")
            return []
    posts = []
    seen_urls = set()

    SKIP_IDS = {"PostList", "PostView", "search", "blogscrap", "CommentList",
                "GuestBook", "MyBlog", "MarketPlace", "market"}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(COOKIE_FILE))
        page = ctx.new_page()
        page.goto("https://section.blog.naver.com/BlogHome.naver")
        page.wait_for_timeout(3000)

        # 이웃새글 탭 클릭 시도
        for tab_text in ["이웃새글", "구독"]:
            try:
                page.click(f"text={tab_text}", timeout=2000)
                page.wait_for_timeout(1500)
                break
            except:
                pass

        # 스크롤 반복
        for _ in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)

        soup = BeautifulSoup(page.content(), "html.parser")
        browser.close()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"https?://blog\.naver\.com/([A-Za-z0-9_]{4,})/(\d+)", href)
        if not m:
            continue
        bid, post_no = m.group(1), m.group(2)
        if bid in SKIP_IDS or href in seen_urls:
            continue
        title = a.get_text(strip=True)[:80]
        if len(title) < 3:
            continue
        seen_urls.add(href)
        posts.append({"blog_id": bid, "post_no": post_no,
                      "url": href, "title": title})

    return posts


# ─────────────────────────────────────────────────────────────────────────────
# RSS 새 글 수집 (개별 블로그 - 보조용)
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

    # ── 이웃새글 피드에서 직접 수집 ──
    date_str = datetime.now().strftime("%Y.%m.%d")
    seen     = load_history()

    print(f"[새 글 수집] section.blog.naver.com 이웃새글 피드")
    raw_posts = collect_feed_posts()

    new_posts = [p for p in raw_posts if p["url"] not in seen]
    print(f"  전체 {len(raw_posts)}건 중 신규 {len(new_posts)}건")

    if not new_posts:
        print("  새 글 없음")
        return

    # 블로그별로 그룹화
    by_blog = {}
    for p in new_posts[:MAX_POSTS]:
        bid = p["blog_id"]
        by_blog.setdefault(bid, {"blog_name": p["blog_id"], "posts": []})
        by_blog[bid]["posts"].append(p)

    # ── 본문 추출 ──
    print(f"[본문 추출] {sum(len(v['posts']) for v in by_blog.values())}건")
    for item in by_blog.values():
        for p in item["posts"]:
            p["content"] = extract_content(p["url"])
            time.sleep(0.2)

    # ── LLM 요약 ──
    print("[LLM 요약]")
    digest_items = []
    for bid, item in by_blog.items():
        print(f"  {bid} ({len(item['posts'])}건) ...")
        summary = summarize_blog_posts(item["blog_name"], item["posts"])
        digest_items.append({
            "blog_name": item["blog_name"],
            "posts":     item["posts"],
            "summary":   summary,
        })
        time.sleep(0.5)

    total = sum(len(d["posts"]) for d in digest_items)

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
    for p in new_posts:
        seen.add(p["url"])
    save_history(seen)
    print("  히스토리 저장 완료")


if __name__ == "__main__":
    main()
