// Every 20s, send the visible page text if it changed. Edit "matches" in manifest.json to add sites.
let last = "";
setInterval(() => {
  const text = (document.querySelector("main") || document.body).innerText.trim();
  if (text.length < 200 || text === last) return;
  last = text;
  chrome.runtime.sendMessage({ url: location.origin + location.pathname, title: document.title, text: text.slice(0, 40000) });
}, 20000);
