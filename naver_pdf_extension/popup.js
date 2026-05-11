const SERVER = "http://localhost:5100";
let currentUrl = "";

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  currentUrl = tabs[0]?.url || "";
  document.getElementById("urlBox").textContent = currentUrl;

  const isNaver  = currentUrl.includes("blog.naver.com") || currentUrl.includes("cafe.naver.com");
  const isValley = currentUrl.includes("valley.town");
  const supported = isNaver || isValley;

  if (!supported) {
    document.getElementById("btn").disabled = true;
    document.getElementById("warn").textContent = "네이버 블로그/카페 또는 valley.town 페이지에서 사용 가능합니다.";
  }

  if (isValley) {
    document.getElementById("siteLabel").textContent = "🏔 Valley.town";
  } else if (isNaver) {
    document.getElementById("siteLabel").textContent = "🟢 네이버";
  }
});

async function savePdf() {
  const btn = document.getElementById("btn");
  btn.disabled = true;
  showStatus("loading", '<span class="spinner"></span>변환 중... 창 닫지 마세요 (10~30초)');

  try {
    const isValley = currentUrl.includes("valley.town");

    if (isValley) {
      // Valley.town: 브라우저에서 직접 HTML 추출 (로그인 세션 포함)
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => ({
          html:  document.documentElement.outerHTML,
          title: document.title,
          url:   location.href,
        }),
      });

      const { html, title, url } = results[0].result;
      const res = await fetch(`${SERVER}/convert-html`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html, title, url, site: "valley" }),
      });
      const data = await res.json();
      if (data.ok) {
        await chrome.tabs.create({ url: `${SERVER}/download/${data.filename}`, active: false });
        showStatus("success", `✅ 저장 완료!<br><b>${data.title}</b>`);
      } else {
        showStatus("error", "❌ " + data.error);
      }
    } else {
      // 네이버: 기존 서버 스크래핑
      const res = await fetch(`${SERVER}/convert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: currentUrl }),
      });
      const data = await res.json();
      if (data.ok) {
        await chrome.tabs.create({ url: `${SERVER}/download/${data.filename}`, active: false });
        showStatus("success", `✅ 저장 완료!<br><b>${data.title}</b>`);
      } else {
        showStatus("error", "❌ " + data.error);
      }
    }
  } catch (e) {
    showStatus("error", "❌ 서버 연결 실패<br><small>python naver_blog_pdf.py 를 먼저 실행해주세요.</small>");
  }

  btn.disabled = false;
}

function showStatus(type, msg) {
  const el = document.getElementById("status");
  el.className = "status " + type;
  el.innerHTML = msg;
}

document.getElementById("btn").addEventListener("click", savePdf);
