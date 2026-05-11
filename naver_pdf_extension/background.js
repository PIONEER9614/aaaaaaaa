const SERVER = "http://localhost:5100";

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== "savePdf") return;

  fetch(`${SERVER}/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: msg.url }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.ok) {
        chrome.downloads.download({
          url: `${SERVER}/download/${data.filename}`,
          filename: data.filename,
        });
        sendResponse({ ok: true, title: data.title });
      } else {
        sendResponse({ ok: false, error: data.error });
      }
    })
    .catch((e) => {
      sendResponse({ ok: false, error: "서버 연결 실패 — python naver_blog_pdf.py 를 먼저 실행해주세요." });
    });

  return true; // 비동기 응답 유지
});
