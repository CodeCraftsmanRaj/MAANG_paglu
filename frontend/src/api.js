// API base URL resolution order:
// 1. VITE_API_URL build-time env var  -> absolute deployed backend (e.g. AWS API Gateway URL)
// 2. file:// (Electron dev shell)     -> local backend
// 3. anything else (vite dev / hosted) -> same-origin /api (vite proxies it locally)
const ENV_BASE = import.meta.env?.VITE_API_URL ? String(import.meta.env.VITE_API_URL).replace(/\/+$/, "") : "";

const BASE = ENV_BASE
  ? `${ENV_BASE}/api`
  : (window.location.protocol === "file:" ? "http://127.0.0.1:8000/api" : "/api");

export const store = { token: localStorage.getItem("cf_token") || "", view: "" };

export default async function call(path, method = "GET", body) {
  const headers = { "Content-Type": "application/json" };
  if (store.token) headers.Authorization = "Bearer " + store.token;
  if (store.view) headers["X-View-As"] = store.view;
  const r = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
