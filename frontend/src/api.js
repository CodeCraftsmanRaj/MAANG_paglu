const BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000/api" : "/api";
let role = "admin";
export const setRole = (r) => (role = r);

export default async function call(path, method = "GET", body) {
  const r = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Role": role },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
