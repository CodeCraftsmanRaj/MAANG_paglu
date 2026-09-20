const token = document.getElementById("token");
const projectId = document.getElementById("projectId");
const status = document.getElementById("status");

chrome.storage.local.get({ token: "", projectId: "proj_default" }, (settings) => {
  token.value = settings.token;
  projectId.value = settings.projectId;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.local.set({ token: token.value.trim(), projectId: projectId.value.trim() || "proj_default" }, () => {
    status.textContent = "Saved";
    setTimeout(() => { status.textContent = ""; }, 1500);
  });
});
