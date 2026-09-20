// Send an initial capture, then only send changed visible text every 20 seconds.
let last = "";
let pending = false;
const capture = () => {
  if (pending) return;
  const text = (document.querySelector("main") || document.body).innerText.trim();
  if (text.length < 200 || text === last) return;
  last = text;
  pending = true;
  chrome.runtime.sendMessage({ url: location.origin + location.pathname, title: document.title, text: text.slice(0, 40000) });
  setTimeout(() => { pending = false; }, 1000);
};

capture();
setInterval(capture, 20000);
