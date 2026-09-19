import { useEffect, useRef, useState } from "react";
import call, { store } from "./api";

const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

function Login({ onDone }) {
  const [reg, setReg] = useState(false);
  const [f, setF] = useState({ username: "", password: "" });
  const [err, setErr] = useState("");
  const go = async (e) => {
    e.preventDefault();
    try {
      const r = await call(reg ? "/auth/register" : "/auth/login", "POST", f);
      localStorage.setItem("cf_token", r.token);
      store.token = r.token;
      onDone();
    } catch (x) { setErr(x.message); }
  };
  return (
    <div className="login">
      <form className="card" onSubmit={go}>
        <div className="mark" />
        <h1>ContextForge</h1>
        <p className="sub">Everything your team knows, ready for any AI or new teammate.</p>
        <input placeholder="Username" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <input type="password" placeholder="Password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        {err && <p className="err">{err}</p>}
        <button className="primary wide">{reg ? "Create account" : "Sign in"}</button>
        <button type="button" className="link" onClick={() => { setReg(!reg); setErr(""); }}>
          {reg ? "I already have an account" : "New here? Create an account (the first one becomes admin)"}
        </button>
      </form>
    </div>
  );
}

function ScreenWatch({ log }) {
  const [on, setOn] = useState(false);
  const ref = useRef({});
  const stop = () => {
    clearInterval(ref.current.timer);
    ref.current.stream?.getTracks().forEach((t) => t.stop());
    setOn(false);
  };
  useEffect(() => stop, []);
  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const { source_id } = await call("/sessions", "POST", { title: "Screen capture " + new Date().toLocaleString() });
      const v = document.createElement("video");
      v.srcObject = stream;
      await v.play();
      const c = document.createElement("canvas");
      const tick = async () => {
        const w = Math.min(1600, v.videoWidth);
        c.width = w;
        c.height = (w * v.videoHeight) / v.videoWidth;
        c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
        try {
          const r = await call(`/sessions/${source_id}/screen`, "POST", { image: c.toDataURL("image/jpeg", 0.7).split(",")[1] });
          log(r.skipped ? "Screen unchanged, nothing new" : `Read your screen and learned ${r.facts} facts`);
        } catch (e) { log(e.message, true); }
      };
      ref.current = { stream, timer: setInterval(tick, 20000) };
      stream.getVideoTracks()[0].onended = stop;
      setOn(true);
      tick();
    } catch (e) { log(e.message, true); }
  };
  return (
    <div className="card">
      <h3>Watch my screen</h3>
      <p className="sub">Pick a window or your whole screen. Every 20 seconds it is read and any new knowledge is saved. Great for meetings, calls and AI chats.</p>
      <button className={on ? "" : "primary"} onClick={on ? stop : start}>{on ? "Stop watching" : "Start watching"}</button>
      {on && <span className="live">live</span>}
    </div>
  );
}

function Capture({ log, logs }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (p) => {
    setBusy(true);
    try {
      const r = await call("/ingest", "POST", p);
      log(`Learned ${r.facts} new facts from ${p.title || p.url || "your note"}`);
    } catch (e) { log(e.message, true); }
    setBusy(false);
  };
  const submit = () => {
    const t = text.trim();
    if (!t) return;
    /^https?:\/\/\S+$/.test(t) ? send({ kind: "url", url: t }) : send({ kind: "text", text: t, title: "Pasted note" });
    setText("");
  };
  const drop = async (files) => { for (const f of files) await send({ kind: "text", text: await f.text(), title: f.name }); };
  return (
    <>
      <h2>Capture</h2>
      <p className="sub">Knowledge flows in from wherever your team works. Everything is split into facts, indexed three ways, and linked to its source.</p>
      <div className="grid">
        <div className="card wide2" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); drop(e.dataTransfer.files); }}>
          <h3>Drop a file, paste a link, or write a note</h3>
          <textarea rows={4} placeholder="https://docs.yourcompany.com/architecture  or drop .md / .txt files here" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="primary" disabled={busy} onClick={submit}>{busy ? "Reading..." : "Add to knowledge"}</button>
        </div>
        <ScreenWatch log={log} />
        <div className="card">
          <h3>Browser chats and pages</h3>
          <p className="sub">Load the <code>extension/</code> folder in Chrome (chrome://extensions, Developer mode, Load unpacked) and paste your token into <code>background.js</code>. ChatGPT, Claude, Gemini and GitHub pages are then captured as you read.</p>
          <button onClick={() => navigator.clipboard.writeText(store.token)}>Copy my token</button>
        </div>
        <div className="card">
          <h3>Watch a folder</h3>
          <p className="sub">Set <code>WATCH_DIR</code> in <code>backend/.env</code>. New and changed notes, docs and logs in that folder are ingested automatically.</p>
        </div>
      </div>
      <div className="card feed">
        <h3>Activity</h3>
        {logs.length === 0 && <p className="sub">Nothing yet. Add a source above.</p>}
        {logs.map((l, i) => <p key={i} className={l.err ? "err" : ""}>{l.msg}</p>)}
      </div>
    </>
  );
}

function Find({ tags, role, llmOn }) {
  const [mode, setMode] = useState("dynamic");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState([]);
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState("");
  const [md, setMd] = useState("");
  const body = { query, mode, scope: mode === "explicit" ? scope : [] };
  const guard = (fn) => async () => { try { await fn(); } catch (e) { setRes({ error: e.message, facts: [] }); } };
  const search = guard(async () => { setAnswer(""); setMd(""); setRes(await call("/retrieve", "POST", body)); });
  const ask = guard(async () => { setMd(""); const r = await call("/ask", "POST", body); setAnswer(r.answer); setRes(r); });
  const pack = guard(async () => setMd((await call("/export", "POST", body)).markdown));
  const toggle = (t) => setScope(scope.includes(t) ? scope.filter((x) => x !== t) : [...scope, t]);
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = "context-pack.md";
    a.click();
  };
  return (
    <>
      <h2>Find context</h2>
      <p className="sub">Searching as <b>{role}</b>. You only ever see what this role is allowed to see.</p>
      <div className="card">
        <div className="seg">
          <button className={mode === "dynamic" ? "on" : ""} onClick={() => setMode("dynamic")}>Understand my question</button>
          <button className={mode === "explicit" ? "on" : ""} onClick={() => setMode("explicit")}>Pick a scope</button>
        </div>
        {mode === "explicit" && (
          <div className="chips">
            {tags.map((t) => <button key={t} className={scope.includes(t) ? "chip on" : "chip"} onClick={() => toggle(t)}>{t}</button>)}
          </div>
        )}
        <input placeholder={mode === "dynamic" ? "How do I deploy the payments service?" : "Optional: narrow the scope with a question"}
          value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        <div className="row">
          <button className="primary" onClick={search}>Search</button>
          {llmOn && <button onClick={ask}>Ask and cite</button>}
          <button onClick={pack}>Build context pack</button>
        </div>
      </div>
      {res?.error && <p className="err">{res.error}</p>}
      {answer && <div className="card answer">{answer}</div>}
      {res?.inferred && Object.entries(res.inferred).map(([t, why]) => <p key={t} className="infer"><b>{t}</b> added: {why}</p>)}
      {res?.facts && (res.facts.length === 0 && !res.error
        ? <p className="sub">Nothing visible to {role} matches yet. Capture more knowledge, or ask an admin for access.</p>
        : res.facts.map((f) => (
          <article key={f.id} className="fact">
            <p>{f.text}</p>
            <small>
              {f.tags.map((t) => <span key={t} className="tag">{t}</span>)}
              {f.via.map((v) => <span key={v} className="tag alt">{v}</span>)}
              from {f.source.uri?.startsWith("http") ? <a href={f.source.uri} target="_blank" rel="noreferrer">{f.source.title}</a> : f.source.title}
            </small>
          </article>
        )))}
      {md && (
        <div className="card">
          <div className="row"><button onClick={() => navigator.clipboard.writeText(md)}>Copy</button><button onClick={download}>Download .md</button></div>
          <pre>{md}</pre>
        </div>
      )}
    </>
  );
}

function Team({ roles, reload }) {
  const [users, setUsers] = useState([]);
  const [draft, setDraft] = useState({});
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => call("/users").then(setUsers).catch((e) => setMsg(e.message));
  useEffect(() => { load(); }, []);
  const guard = async (fn, ok) => { try { await fn(); setMsg(ok); } catch (e) { setMsg(e.message); } };
  const saveRole = (n, t) => guard(async () => { await call(`/roles/${n}`, "PUT", { tags: csv(t) }); reload(); }, `Saved ${n}`);
  const setRole = (u, role) => guard(async () => { await call(`/users/${u}/role`, "PUT", { role }); load(); }, `${u} is now ${role}`);
  return (
    <>
      <h2>Team</h2>
      <p className="sub">A role can read facts that carry at least one of its tags. Use * for everything. New sign-ups start as <b>member</b> and see nothing until you assign a role.</p>
      <div className="card">
        <h3>Roles</h3>
        {roles.map((r) => (
          <div className="row" key={r.name}>
            <b className="rname">{r.name}</b>
            <input value={draft[r.name] ?? r.tags.join(", ")} disabled={r.name === "admin"} onChange={(e) => setDraft({ ...draft, [r.name]: e.target.value })} />
            {r.name !== "admin" && <button onClick={() => saveRole(r.name, draft[r.name] ?? r.tags.join(", "))}>Save</button>}
          </div>
        ))}
        <div className="row">
          <input placeholder="New role, e.g. intern" value={name} onChange={(e) => setName(e.target.value)} />
          <button onClick={() => { if (name.trim()) { saveRole(name.trim(), ""); setName(""); } }}>Add role</button>
        </div>
      </div>
      <div className="card">
        <h3>People</h3>
        {users.map((u) => (
          <div className="row" key={u.username}>
            <b className="rname">{u.username}</b>
            <select value={u.role} onChange={(e) => setRole(u.username, e.target.value)}>{roles.map((r) => <option key={r.name}>{r.name}</option>)}</select>
          </div>
        ))}
      </div>
      {msg && <p className="sub">{msg}</p>}
    </>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("capture");
  const [roles, setRoles] = useState([]);
  const [tags, setTags] = useState([]);
  const [view, setView] = useState("");
  const [logs, setLogs] = useState([]);
  const log = (msg, err) => setLogs((l) => [{ msg, err }, ...l].slice(0, 12));
  const loadRoles = () => call("/roles").then(setRoles);
  const boot = async () => {
    try { const m = await call("/me"); setMe(m); setTab(m.role === "admin" ? "capture" : "find"); await loadRoles(); setTags(await call("/tags")); }
    catch { setMe(null); }
    setReady(true);
  };
  useEffect(() => { boot(); }, []);
  if (!ready) return null;
  if (!me) return <Login onDone={boot} />;
  const admin = me.role === "admin";
  const pick = (v) => { store.view = v === me.role ? "" : v; setView(store.view); };
  const out = () => { localStorage.removeItem("cf_token"); store.token = ""; store.view = ""; setView(""); setMe(null); };
  const nav = [admin && ["capture", "Capture"], ["find", "Find"], admin && ["team", "Team"]].filter(Boolean);
  return (
    <div className="shell">
      <aside>
        <div className="brand"><span className="mark" />ContextForge</div>
        {nav.map(([k, l]) => <button key={k} className={"nav" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>)}
        <div className="grow" />
        {admin && (
          <label className="viewas">Viewing as
            <select value={view || me.role} onChange={(e) => pick(e.target.value)}>{roles.map((r) => <option key={r.name}>{r.name}</option>)}</select>
          </label>
        )}
        <div className="me"><span className="avatar">{me.user[0].toUpperCase()}</span><span>{me.user}<small>{me.role}</small></span></div>
        <button className="link" onClick={out}>Sign out</button>
      </aside>
      <main>
        {view && <div className="banner">Previewing as <b>{view}</b>. This is exactly what that role can see.</div>}
        {tab === "capture" && admin && <Capture log={log} logs={logs} />}
        {tab === "find" && <Find key={view} tags={tags} role={view || me.role} llmOn={me.llm} />}
        {tab === "team" && admin && <Team roles={roles} reload={loadRoles} />}
        {admin && !me.llm && <p className="sub">Add GROQ_API_KEY to backend/.env to unlock smart extraction, screen reading and Ask.</p>}
      </main>
    </div>
  );
}
