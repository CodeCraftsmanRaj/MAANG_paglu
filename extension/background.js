const DEFAULT_API = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((msg) => {
  chrome.storage.local.get({ token: "", projectId: "proj_default", serverUrl: DEFAULT_API }, ({ token, projectId, serverUrl }) => {
    if (!token) {
      console.warn("ContextForge: configure the token in the extension options");
      return;
    }
    const API = (serverUrl || DEFAULT_API).replace(/\/+$/, "");
    fetch(API + "/api/capture/page", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ ...msg, project_id: projectId }),
    }).then((response) => {
      if (!response.ok) throw new Error(`capture failed (${response.status})`);
    }).catch((e) => console.warn("ContextForge:", e));
  });
});
