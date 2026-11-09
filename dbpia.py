"""
DBpia(dbpia.co.kr) 논문 검색 · DBpia AI 답변 · 원문 내려받기 → 참고 자료실 등록

전용 브라우저 프로필에 학교(기관) 로그인을 한 번 해 두면 이후엔 창 없이 돈다.

사용:
  python dbpia.py login                      # 창이 열리면 직접 로그인(기관 로그인 → 소속 학교), 끝나면 창 닫기
  python dbpia.py me                         # 로그인 상태 확인
  python dbpia.py search 메이지 문명개화 [--n 20] [--sort RANK|PUBLISH_DESC|USE_DESC] [--ai]
  python dbpia.py ai 메이지 문명개화          # DBpia AI 짧은 답변 + 이어서 물어볼 질문
  python dbpia.py get NODE07432550 [NODE...] # 원문 PDF → 바탕 화면\\클로드 참고 자료\\DBpia\\ 저장 후 자료실 등록
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
PROFILE_DIR = Path.home() / ".claude-code-secrets" / "dbpia_profile"
SAVE_DIR = BASE.parent / "클로드 참고 자료" / "DBpia"
SITE = "https://www.dbpia.co.kr"
GAP_MS = 3000  # 여러 편을 받을 때 사람 속도로 간격


def open_context(p, headless=True):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kw = dict(user_data_dir=str(PROFILE_DIR), headless=headless, accept_downloads=True)
    if headless:
        kw["viewport"] = {"width": 1280, "height": 900}
    else:
        kw["no_viewport"] = True
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **kw)
    except Exception:
        return p.chromium.launch_persistent_context(**kw)


def strip_tags(s):
    return re.sub(r"<!H[SE]>|<[^>]+>", "", s or "").strip()


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = open_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SITE, wait_until="domcontentloaded")
        print("  [로그인] 창에서 로그인 → '기관 로그인'(또는 기관인증)에서 소속 학교 선택 → 학교 아이디로 로그인")
        print("  [로그인] 끝나면 브라우저 창을 닫아 주세요.")
        # 창을 닫으면 끝. sync API는 time.sleep 중엔 이벤트를 못 받으므로 wait_for_timeout으로 돈다
        try:
            while [pg for pg in ctx.pages if not pg.is_closed()]:
                ctx.pages[0].wait_for_timeout(1000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    me()


def fetch_me(page):
    return page.evaluate("""async () => { const r = await fetch('/member/me', {credentials:'include'});
        return {status: r.status, body: await r.text()}; }""")


def me():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = open_context(p)
        page = ctx.new_page()
        page.goto(SITE, wait_until="domcontentloaded")
        r = fetch_me(page)
        ctx.close()
    print(f"  [상태] {r['status']} {r['body'][:600]}")


def run_search(query, n=20, sort="RANK", want_ai=False):
    """검색 페이지를 열어 사이트가 부르는 결과 JSON을 그대로 받는다."""
    from playwright.sync_api import sync_playwright
    got = {}

    def on_resp(r):
        try:
            if "/api/search/list" in r.url and r.request.method == "POST":
                got["list"] = r.json()
            elif "short-answer-v5/brief" in r.url:
                got["brief"] = r.json()
            elif "short-answer-v5/general-questions" in r.url:
                got["questions"] = r.json()
        except Exception:
            pass

    url = f"{SITE}/search/topSearch?searchOption=all&query={quote(query)}"
    if sort != "RANK":
        url += f"&sort={sort}"
    with sync_playwright() as p:
        ctx = open_context(p)
        page = ctx.new_page()
        page.on("response", on_resp)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        deadline = time.time() + (25 if want_ai else 15)
        while time.time() < deadline:
            if "list" in got and (not want_ai or ("brief" in got and "questions" in got)):
                break
            page.wait_for_timeout(500)
        ctx.close()
    return got


def show_results(got, n):
    items = (got.get("list") or {}).get("list") or []
    total = (got.get("list") or {}).get("totalCount") or (got.get("list") or {}).get("total")
    print(f"  [검색] {len(items)}건 표시" + (f" / 전체 {total}건" if total else ""))
    for i, it in enumerate(items[:n], 1):
        authors = ", ".join(a.get("autrNm", "") for a in it.get("authors") or [])
        title = strip_tags(it.get("nodeTitle"))
        venue = f"{strip_tags(it.get('plctNm'))} {it.get('vois') or ''}호".strip()
        flags = []
        if it.get("dmstLstdInfo"):
            flags.append(it["dmstLstdInfo"])
        if it.get("svcAvblYn") != "Y":
            flags.append("원문없음")
        print(f"\n{i}. {title}")
        print(f"   {authors} | {venue} | {it.get('publishYymm','')} | 이용 {it.get('useCnt',0)}회"
              f" | {it.get('totalPageCnt','?')}쪽 | {it.get('nodeId')}" + (f" | {' '.join(flags)}" if flags else ""))
        ab = strip_tags(it.get("abstractText"))
        if ab:
            print(f"   초록: {ab[:260]}{'…' if len(ab) > 260 else ''}")


def show_ai(got):
    b = ((got.get("brief") or {}).get("data") or {}).get("intro")
    if b:
        print(f"\n  [DBpia AI] {b}")
    qs = (got.get("questions") or {}).get("data") or []
    if qs:
        print("  [이어서 물어볼 질문]")
        for q in qs:
            print(f"   - {q.get('question')}")
    if not b and not qs:
        print("  [DBpia AI] 답변을 받지 못했습니다.")


def dedupe_tail(t):
    """'제목 : 부제 부제'처럼 부제가 두 번 붙는 경우 한 번만 남긴다."""
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split(" ")
    for k in range(len(words) // 2, 0, -1):
        if words[-k:] == words[-2 * k:-k]:
            return " ".join(words[:-k])
    return t


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", s)
    return re.sub(r"\s+", " ", s).strip()[:120]


def get(node_ids):
    """논문 상세 화면의 '다운받기'를 눌러 원문을 받는다(기관 인증 필요)."""
    from playwright.sync_api import sync_playwright
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    with sync_playwright() as p:
        ctx = open_context(p)
        page = ctx.new_page()
        page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
        try:
            who = json.loads(fetch_me(page)["body"] or "{}")
        except Exception:
            who = {}
        if not who.get("b2bName"):
            ctx.close()
            print("  [원문] 기관 인증이 풀렸습니다. `python dbpia.py login`으로 다시 학교 로그인해 주세요.")
            return []
        print(f"  [원문] 기관 인증: {who['b2bName']}")
        for i, nid in enumerate(node_ids):
            nid = nid.strip().upper()
            if not nid.startswith("NODE"):
                nid = "NODE" + nid
            if i:
                page.wait_for_timeout(GAP_MS)
            page.goto(f"{SITE}/journal/articleDetail?nodeId={nid}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            meta = page.evaluate("""() => {
                const m = n => [...document.querySelectorAll(`meta[name="${n}"]`)].map(e => e.content);
                return {title: (m('citation_title')[0] || document.title.split(' - ')[0] || '').trim(),
                        authors: m('citation_author'), date: (m('citation_publication_date')[0] || m('citation_date')[0] || '')};
            }""")
            if not page.query_selector("#downloadNodeButton_detail"):
                print(f"  [원문] {nid}: 내려받기 버튼이 없습니다(원문 미제공·외부 링크일 수 있음) → {SITE}/journal/articleDetail?nodeId={nid}")
                continue
            try:
                with page.expect_download(timeout=40000) as d:
                    page.evaluate("() => document.querySelector('#downloadNodeButton_detail').click()")
                dl = d.value
            except Exception as e:
                print(f"  [원문] {nid}: 내려받기 실패 ({str(e)[:120]})")
                continue
            title = meta.get("title") or re.sub(r"(\.pdf)+$", "", dl.suggested_filename, flags=re.I)
            au = (meta.get("authors") or [""])[0]
            title = dedupe_tail(title)
            m = re.search(r"(?:19|20)\d\d", meta.get("date") or "")
            yr = m.group(0) if m else ""
            name = safe_name(f"{title}" + (f" - {au}" if au else "") + (f" ({yr})" if yr else "")) + ".pdf"
            dest = SAVE_DIR / name
            dl.save_as(str(dest))
            saved.append(dest)
            print(f"  [원문] 저장: {dest.name} ({dest.stat().st_size // 1024}KB)")
        ctx.close()
    if saved:
        print("  [자료실] /책검색에 등록 중...")
        subprocess.run([sys.executable, str(BASE / "book_library.py"), "ingest"], check=False)
    return saved


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("me")
    s = sub.add_parser("search"); s.add_argument("q", nargs="+"); s.add_argument("--n", type=int, default=20)
    s.add_argument("--sort", default="RANK"); s.add_argument("--ai", action="store_true")
    a = sub.add_parser("ai"); a.add_argument("q", nargs="+")
    g = sub.add_parser("get"); g.add_argument("ids", nargs="+")
    args = ap.parse_args()

    if args.cmd == "login":
        login()
    elif args.cmd == "me":
        me()
    elif args.cmd == "search":
        got = run_search(" ".join(args.q), args.n, args.sort, args.ai)
        if args.ai:
            show_ai(got)
        show_results(got, args.n)
    elif args.cmd == "ai":
        got = run_search(" ".join(args.q), want_ai=True)
        show_ai(got)
    elif args.cmd == "get":
        get(args.ids)


if __name__ == "__main__":
    main()
