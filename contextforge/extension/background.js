const API = "http://127.0.0.1:8000";
const TOKEN = "PASTE_YOUR_TOKEN_FROM_THE_CAPTURE_TAB"; // ContextForge > Capture > Browser extension

chrome.runtime.onMessage.addListener((msg) => {
  fetch(API + "/api/capture/page", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
    body: JSON.stringify(msg),
  }).catch((e) => console.warn("ContextForge:", e));
});
