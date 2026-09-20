const token = document.getElementById("token");
const serverUrl = document.getElementById("serverUrl");
const projectId = document.getElementById("projectId");
const status = document.getElementById("status");

chrome.storage.local.get({ token: "", projectId: "proj_default", serverUrl: "http://127.0.0.1:8000" }, (settings) => {
  token.value = settings.token;
  serverUrl.value = settings.serverUrl;
  projectId.value = settings.projectId;
});

document.getElementById("save").addEventListener("click", () => {
  const url = serverUrl.value.trim().replace(/\/+$/, "");
  chrome.storage.local.set({
    token: token.value.trim(),
    serverUrl: url || "http://127.0.0.1:8000",
    projectId: projectId.value.trim() || "proj_default",
  }, () => {
    status.textContent = "Saved";
    setTimeout(() => { status.textContent = ""; }, 1500);
  });
});
