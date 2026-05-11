"""
네이버 블로그/카페 → PDF 저장기
실행: python naver_blog_pdf.py
브라우저에서 http://localhost:5100 열기
"""

import io, os, re, sys, time, json, threading, webbrowser
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image as RLImage
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = Path("naver_pdfs")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.naver.com/",
}

# ── 폰트 ──────────────────────────────────────────────────────────────────────
def setup_font():
    candidates = ["C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
    bold_c     = ["C:/Windows/Fonts/malgunbd.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]
    font = next((p for p in candidates if os.path.exists(p)), None)
    bold = next((p for p in bold_c    if os.path.exists(p)), font)
    if font:
        try:
            pdfmetrics.registerFont(TTFont("KR",   font))
            pdfmetrics.registerFont(TTFont("KR-B", bold or font))
            return "KR", "KR-B"
        except:
            pass
    return "Helvetica", "Helvetica-Bold"

# ── URL 정규화 ─────────────────────────────────────────────────────────────────
def normalize_url(url):
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url

def detect_type(url):
    if "cafe.naver.com" in url:
        return "cafe"
    if "blog.naver.com" in url:
        return "blog"
    return "unknown"

# ── 네이버 블로그 스크래핑 ─────────────────────────────────────────────────────
def scrape_blog(url):
    """네이버 블로그 → {title, author, date, content, images}"""
    # 모바일 URL로 변환 (파싱 쉬움)
    # blog.naver.com/아이디/글번호 형식 처리
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")

    mobile_url = url.replace("blog.naver.com", "m.blog.naver.com")

    r = requests.get(mobile_url, headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    # 제목
    title = ""
    for sel in [".se-title-text", ".se_title", ".htitle", "h3.title", ".tit_h3"]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break
    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else "제목없음"

    # 작성자
    author = ""
    for sel in [".blog_name", ".nick", ".writer"]:
        el = soup.select_one(sel)
        if el:
            author = el.get_text(strip=True)
            break

    # 날짜: JS 변수 postWriteDate (Unix ms) 우선 추출
    date = ""
    ts_match = re.search(r"postWriteDate['\"]?\s*[:=]\s*['\"]?(\d{10,13})", r.text)
    if ts_match:
        ts = int(ts_match.group(1))
        if ts > 1e12:
            ts //= 1000
        date = datetime.fromtimestamp(ts).strftime("%y.%m.%d")
    if not date:
        for sel in [".se_publishDate", ".date", ".post_date", ".se-date"]:
            el = soup.select_one(sel)
            if el:
                date = el.get_text(strip=True)
                break

    # 본문 텍스트
    content_parts = []
    images = []
    for sel in [".se-main-container", ".se_component_wrap", ".post-view", "#postViewArea"]:
        container = soup.select_one(sel)
        if container:
            for el in container.find_all(["p", "h1", "h2", "h3", "h4", "span", "div"], recursive=False):
                text = el.get_text(separator="\n", strip=True)
                if text and len(text) > 1:
                    content_parts.append(text)
            # 이미지
            for img in container.find_all("img"):
                src = img.get("src") or img.get("data-src", "")
                if src and ("postfiles" in src or "blogfiles" in src or "pstatic" in src):
                    images.append(src)
            break

    if not content_parts:
        body = soup.find("body")
        if body:
            for script in body(["script", "style", "nav", "header", "footer"]):
                script.decompose()
            content_parts = [body.get_text(separator="\n", strip=True)]

    return {
        "title":   title,
        "author":  author,
        "date":    date,
        "url":     url,
        "content": "\n\n".join(content_parts),
        "images":  images[:5],
    }

# ── 네이버 카페 스크래핑 ─────────────────────────────────────────────────────────
def scrape_cafe(url):
    """네이버 카페 글 → {title, author, date, content}"""
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")

    # 카페는 iframe 내부에 실제 글이 있는 경우 많음
    # article_id, clubid 파싱
    qs = parse_qs(urlparse(url).query)
    article_id = qs.get("articleid", qs.get("ArticleID", [None]))[0]
    club_id    = qs.get("clubid",    qs.get("clubId",    [None]))[0]

    title = ""
    author = ""
    date   = ""
    content_parts = []

    if article_id and club_id:
        api_url = f"https://cafe.naver.com/ArticleRead.nhn?clubid={club_id}&articleid={article_id}"
        r2 = requests.get(api_url, headers=HEADERS, timeout=15)
        r2.encoding = "utf-8"
        soup = BeautifulSoup(r2.text, "html.parser")

    for sel in [".title-text", ".tit-subject", "h3.title", ".ArticleTitle"]:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break
    for sel in [".writer-nick", ".nick-name", ".m-tcol-c"]:
        el = soup.select_one(sel)
        if el:
            author = el.get_text(strip=True)
            break
    for sel in [".date", ".article_info .date", ".RelativeDate"]:
        el = soup.select_one(sel)
        if el:
            date = el.get_text(strip=True)
            break

    for sel in [".article_body", "#tbody", ".se-main-container", ".ContentRenderer"]:
        container = soup.select_one(sel)
        if container:
            for tag in container(["script", "style"]):
                tag.decompose()
            content_parts.append(container.get_text(separator="\n", strip=True))
            break

    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else "제목없음"

    return {
        "title":   title,
        "author":  author,
        "date":    date,
        "url":     url,
        "content": "\n\n".join(content_parts) if content_parts else "본문을 가져오지 못했습니다.",
        "images":  [],
    }

# ── Valley.town HTML 파싱 ─────────────────────────────────────────────────────
def parse_valley_html(html, url, fallback_title=""):
    soup = BeautifulSoup(html, "html.parser")

    # 제목
    title = fallback_title
    for sel in ["h1", "h2", ".title", ".post-title", ".article-title", '[class*="title"]']:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if len(t) > 3:
                title = t
                break
    if not title:
        og = soup.find("meta", property="og:title")
        title = og["content"] if og else "Valley 리포트"

    # 날짜
    date = ""
    for sel in ["time", '[class*="date"]', '[class*="time"]', ".published", ".created"]:
        el = soup.select_one(sel)
        if el:
            date = el.get("datetime", "") or el.get_text(strip=True)
            if date: break
    if not date:
        m = re.search(r'20\d\d[.\-/]\d{2}[.\-/]\d{2}', html)
        date = m.group() if m else ""

    # 날짜 yy.mm.dd 포맷 정리
    clean_date = re.sub(r'[^\d.]', '.', date)
    clean_date = re.sub(r'\.+', '.', clean_date).strip('.')
    if len(clean_date) >= 8:
        clean_date = clean_date[-8:]  # 뒤 8자리 (yy.mm.dd 또는 mm.dd.yy)

    # 본문: script/style/nav/header/footer 제거 후 본문 영역 추출
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    content = ""
    for sel in ["article", "main", '[class*="content"]', '[class*="body"]', '[class*="post"]', ".prose"]:
        el = soup.select_one(sel)
        if el:
            content = el.get_text(separator="\n", strip=True)
            if len(content) > 100:
                break
    if not content:
        content = soup.get_text(separator="\n", strip=True)

    return {
        "title":   title,
        "author":  "WSAJ Premium",
        "date":    clean_date,
        "url":     url,
        "content": content,
        "images":  [],
    }

# ── PDF 생성 ──────────────────────────────────────────────────────────────────
def build_pdf(data):
    fn, fnb = setup_font()
    def S(nm, **kw):  return ParagraphStyle(nm, fontName=fn,  **kw)
    def SB(nm, **kw): return ParagraphStyle(nm, fontName=fnb, **kw)

    ST = {
        "title":  SB("ti", fontSize=18, leading=24, spaceAfter=6,  textColor=colors.HexColor("#0d1b2a")),
        "meta":   S ("me", fontSize=8,  leading=13, spaceAfter=10, textColor=colors.HexColor("#888")),
        "body":   S ("bo", fontSize=9,  leading=15, spaceAfter=4,  textColor=colors.HexColor("#222")),
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm,  bottomMargin=2*cm)
    story = []
    W = doc.width

    # 제목
    story.append(Paragraph(data["title"] or "제목없음", ST["title"]))
    meta_parts = []
    if data.get("author"): meta_parts.append(data["author"])
    if data.get("date"):   meta_parts.append(data["date"])
    meta_parts.append(data["url"])
    meta_parts.append(datetime.now().strftime("저장: %Y.%m.%d %H:%M"))
    story.append(Paragraph("  ·  ".join(meta_parts), ST["meta"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.3*cm))

    # 이미지 (최대 3장)
    for img_url in data.get("images", [])[:3]:
        try:
            img_r = requests.get(img_url, headers=HEADERS, timeout=8)
            if img_r.status_code == 200:
                img_buf = io.BytesIO(img_r.content)
                rl_img = RLImage(img_buf, width=W, height=W*0.5, kind="proportional")
                story.append(rl_img)
                story.append(Spacer(1, 0.2*cm))
        except:
            pass

    # 본문
    content = data.get("content", "")
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 0.15*cm))
            continue
        # 특수문자 이스케이프
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            story.append(Paragraph(line, ST["body"]))
        except:
            pass

    doc.build(story)
    buf.seek(0)
    return buf

# ── Flask 웹앱 ────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>네이버 블로그/카페 → PDF</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Malgun Gothic', sans-serif; background: #f0f4f8; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; }
  .card { background: white; border-radius: 16px; padding: 40px; width: 560px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.10); }
  h1 { font-size: 22px; color: #0d1b2a; margin-bottom: 6px; }
  .sub { color: #888; font-size: 13px; margin-bottom: 28px; }
  label { font-size: 13px; color: #444; font-weight: bold; display: block; margin-bottom: 6px; }
  input { width: 100%; padding: 12px 16px; border: 1.5px solid #ddd; border-radius: 8px;
          font-size: 14px; outline: none; transition: border 0.2s; }
  input:focus { border-color: #1a3a5c; }
  button { width: 100%; margin-top: 16px; padding: 13px; background: #1a3a5c;
           color: white; border: none; border-radius: 8px; font-size: 15px;
           font-weight: bold; cursor: pointer; transition: background 0.2s; }
  button:hover { background: #2c5282; }
  button:disabled { background: #aaa; cursor: not-allowed; }
  .status { margin-top: 20px; padding: 14px 16px; border-radius: 8px; font-size: 13px;
            display: none; }
  .status.loading { background: #e8f4fd; color: #1a6fb5; display: block; }
  .status.success { background: #e8f8e8; color: #2e7d32; display: block; }
  .status.error   { background: #fde8e8; color: #c62828; display: block; }
  .dl-btn { display: block; margin-top: 12px; text-align: center; padding: 10px;
            background: #2e7d32; color: white; border-radius: 6px; text-decoration: none;
            font-size: 13px; font-weight: bold; }
  .history { margin-top: 28px; }
  .history h2 { font-size: 14px; color: #444; margin-bottom: 10px; }
  .history-item { padding: 8px 12px; background: #f8f9fa; border-radius: 6px;
                  margin-bottom: 6px; font-size: 12px; color: #333;
                  display: flex; justify-content: space-between; align-items: center; }
  .history-item a { color: #1a6fb5; text-decoration: none; font-weight: bold; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #1a6fb5;
             border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite;
             margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <h1>📄 네이버 → PDF 저장기</h1>
  <p class="sub">블로그 또는 카페 글 URL을 붙여넣고 버튼을 누르세요</p>

  <label>URL</label>
  <input type="text" id="url" placeholder="https://blog.naver.com/..." autofocus>
  <button onclick="convert()" id="btn">PDF 저장</button>

  <div class="status" id="status"></div>

  <div class="history" id="historySection" style="display:none">
    <h2>최근 저장</h2>
    <div id="historyList"></div>
  </div>
</div>

<script>
const history = [];

async function convert() {
  const url = document.getElementById('url').value.trim();
  if (!url) { showStatus('error', 'URL을 입력해주세요.'); return; }

  const btn = document.getElementById('btn');
  btn.disabled = true;
  showStatus('loading', '<span class="spinner"></span>변환 중... (10~30초 소요)');

  try {
    const res = await fetch('/convert', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url})
    });
    const data = await res.json();

    if (data.ok) {
      showStatus('success',
        `✅ 저장 완료: <b>${data.title}</b><br>
         <a class="dl-btn" href="/download/${data.filename}" download>⬇ PDF 다운로드</a>`
      );
      addHistory(data.title, data.filename);
      document.getElementById('url').value = '';
    } else {
      showStatus('error', '❌ ' + data.error);
    }
  } catch(e) {
    showStatus('error', '❌ 서버 오류: ' + e.message);
  }
  btn.disabled = false;
}

function showStatus(type, msg) {
  const el = document.getElementById('status');
  el.className = 'status ' + type;
  el.innerHTML = msg;
}

function addHistory(title, filename) {
  history.unshift({title, filename});
  const section = document.getElementById('historySection');
  const list    = document.getElementById('historyList');
  section.style.display = 'block';
  list.innerHTML = history.slice(0, 5).map(h =>
    `<div class="history-item">
       <span>${h.title.slice(0, 35)}${h.title.length > 35 ? '...' : ''}</span>
       <a href="/download/${h.filename}" download>다운로드</a>
     </div>`
  ).join('');
}

document.getElementById('url').addEventListener('keydown', e => {
  if (e.key === 'Enter') convert();
});
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return HTML

@app.route("/convert", methods=["POST"])
def convert():
    data = request.get_json()
    url  = normalize_url(data.get("url", ""))
    kind = detect_type(url)

    try:
        if kind == "blog":
            scraped = scrape_blog(url)
        elif kind == "cafe":
            scraped = scrape_cafe(url)
        else:
            return jsonify(ok=False, error="네이버 블로그/카페 URL만 지원합니다.")

        if not scraped.get("content") or len(scraped["content"]) < 20:
            return jsonify(ok=False, error="본문을 가져오지 못했습니다. 공개글인지 확인해주세요.")

        pdf_buf  = build_pdf(scraped)
        safe_t    = re.sub(r'[\\/:*?"<>|]', "_", scraped["title"])[:40] or "naver"
        post_date = scraped.get("date", "")
        date_dir  = OUTPUT_DIR / datetime.now().strftime("%y.%m.%d")
        date_dir.mkdir(exist_ok=True)
        prefix    = f"[{post_date}] " if post_date else ""
        filename  = f"{prefix}{safe_t}.pdf"
        out_path = date_dir / filename
        out_path.write_bytes(pdf_buf.read())

        print(f"  ✅ 저장: {out_path}")
        dl_path = f"{datetime.now().strftime('%y.%m.%d')}/{filename}"
        return jsonify(ok=True, title=scraped["title"], filename=dl_path)

    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.route("/convert-html", methods=["POST"])
def convert_html():
    """브라우저에서 직접 추출한 HTML → PDF (Valley.town 등 로그인 필요 사이트)"""
    data  = request.get_json()
    html  = data.get("html", "")
    url   = data.get("url", "")
    title = data.get("title", "")
    site  = data.get("site", "valley")

    try:
        if site == "valley":
            scraped = parse_valley_html(html, url, title)
        else:
            return jsonify(ok=False, error="지원하지 않는 사이트입니다.")

        if not scraped.get("content") or len(scraped["content"]) < 20:
            return jsonify(ok=False, error="본문을 가져오지 못했습니다.")

        pdf_buf   = build_pdf(scraped)
        safe_t    = re.sub(r'[\\/:*?"<>|]', "_", scraped["title"])[:40] or "valley"
        post_date = scraped.get("date", "")
        date_dir  = OUTPUT_DIR / datetime.now().strftime("%y.%m.%d")
        date_dir.mkdir(exist_ok=True)
        prefix    = f"[{post_date}] " if post_date else ""
        filename  = f"{prefix}{safe_t}.pdf"
        out_path  = date_dir / filename
        out_path.write_bytes(pdf_buf.read())

        print(f"  ✅ Valley 저장: {out_path}")
        dl_path = f"{datetime.now().strftime('%y.%m.%d')}/{filename}"
        return jsonify(ok=True, title=scraped["title"], filename=dl_path)

    except Exception as e:
        return jsonify(ok=False, error=str(e))

@app.route("/download/<path:filename>")
def download(filename):
    path = OUTPUT_DIR / filename
    if not path.exists():
        return "파일 없음", 404
    return send_file(str(path), as_attachment=True, download_name=Path(filename).name)

if __name__ == "__main__":
    print("🚀 서버 시작: http://localhost:5100")
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5100")).start()
    app.run(port=5100, debug=False)
