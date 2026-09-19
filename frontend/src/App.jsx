import { useEffect, useState } from "react";
import call, { setRole } from "./api";

const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

function Ingest() {
  const [f, setF] = useState({ kind: "text", text: "", url: "", title: "", tags: "", structure: "flat" });
  const [session, setSession] = useState(null);
  const [msg, setMsg] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    try {
      let r;
      if (f.kind === "live") {
        let id = session;
        if (!id) {
          id = (await call("/sessions", "POST", { title: f.title || "Live session" })).source_id;
          setSession(id);
        }
        r = await call(`/sessions/${id}/chunk`, "POST", { text: f.text, structure: f.structure, tags: csv(f.tags) });
        setF({ ...f, text: "" });
      } else {
        r = await call("/ingest", "POST", { ...f, tags: csv(f.tags) });
      }
      setMsg(`Stored ${r.facts} facts, each linked to its source.`);
    } catch (e) {
      setMsg(e.message);
    }
  };
  const readFile = async (e) => {
    const file = e.target.files[0];
    if (file) setF({ ...f, kind: "text", text: await file.text(), title: file.name });
  };

  return (
    <section>
      <h2>Add knowledge</h2>
      <div className="seg">
        {["text", "url", "live"].map((k) => (
          <button key={k} className={f.kind === k ? "on" : ""} onClick={() => { setF({ ...f, kind: k }); setSession(null); }}>
            {{ text: "Paste text", url: "Web page", live: "Live session" }[k]}
          </button>
        ))}
      </div>
      {f.kind === "url" ? (
        <input placeholder="https://docs.example.com/architecture" value={f.url} onChange={set("url")} />
      ) : (
        <textarea rows={9} placeholder={f.kind === "live" ? "Paste or type what was just said. Send as often as you like." : "Paste docs, notes, or an AI chat transcript"} value={f.text} onChange={set("text")} />
      )}
      <div className="row">
        <input placeholder="Title (optional)" value={f.title} onChange={set("title")} disabled={!!session} />
        <input placeholder="Extra tags, comma separated" value={f.tags} onChange={set("tags")} />
        <select value={f.structure} onChange={set("structure")}>
          <option value="flat">Flat facts</option>
          <option value="graph">Knowledge graph</option>
        </select>
      </div>
      <div className="row">
        <button className="primary" onClick={submit}>{f.kind === "live" ? (session ? "Send chunk" : "Start session and send") : "Ingest"}</button>
        {f.kind === "text" && <input type="file" accept=".txt,.md,.json,.log" onChange={readFile} />}
        {session && <span className="note">Session {session} is live</span>}
      </div>
      {msg && <p className="note">{msg}</p>}
    </section>
  );
}

function Retrieve({ tags, role }) {
  const [mode, setMode] = useState("explicit");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState([]);
  const [res, setRes] = useState(null);
  const [md, setMd] = useState("");
  const body = { query, mode, scope: mode === "explicit" ? scope : [] };

  const go = async () => {
    try { setRes(await call("/retrieve", "POST", body)); setMd(""); } catch (e) { setRes({ error: e.message }); }
  };
  const pack = async () => {
    try { setMd((await call("/export", "POST", body)).markdown); } catch (e) { setMd(e.message); }
  };
  const toggle = (t) => setScope(scope.includes(t) ? scope.filter((x) => x !== t) : [...scope, t]);
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = "context-pack.md";
    a.click();
  };

  return (
    <section>
      <h2>Find context</h2>
      <div className="seg">
        <button className={mode === "explicit" ? "on" : ""} onClick={() => setMode("explicit")}>Pick a scope</button>
        <button className={mode === "dynamic" ? "on" : ""} onClick={() => setMode("dynamic")}>Infer from question</button>
      </div>
      {mode === "explicit" && (
        <div className="chips">
          {tags.map((t) => (
            <button key={t} className={scope.includes(t) ? "chip on" : "chip"} onClick={() => toggle(t)}>{t}</button>
          ))}
        </div>
      )}
      <input
        placeholder={mode === "dynamic" ? "e.g. How do I deploy this service?" : "Optional: narrow the scope with a question"}
        value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()}
      />
      <div className="row">
        <button className="primary" onClick={go}>Search as {role}</button>
        <button onClick={pack}>Build context pack</button>
      </div>
      {res?.error && <p className="note err">{res.error}</p>}
      {res?.inferred && Object.entries(res.inferred).map(([t, why]) => (
        <p key={t} className="infer"><b>{t}</b> added: {why}</p>
      ))}
      {res?.facts && (res.facts.length === 0
        ? <p className="note">Nothing visible to {role} matches. Ingest more, or try another scope.</p>
        : res.facts.map((f) => (
          <article key={f.id} className="fact">
            <p>{f.text}</p>
            <small>{f.tags.join(", ")} from {f.source.uri ? <a href={f.source.uri} target="_blank" rel="noreferrer">{f.source.title}</a> : f.source.title}</small>
          </article>
        )))}
      {md && (
        <div className="pack">
          <div className="row">
            <button onClick={() => navigator.clipboard.writeText(md)}>Copy</button>
            <button onClick={download}>Download .md</button>
          </div>
          <pre>{md}</pre>
        </div>
      )}
    </section>
  );
}

function Access({ roles, reload }) {
  const [draft, setDraft] = useState({});
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const save = async (n, t) => {
    try { await call(`/roles/${n}`, "PUT", { tags: csv(t) }); setMsg(`Saved ${n}.`); reload(); } catch (e) { setMsg(e.message); }
  };
  return (
    <section>
      <h2>Who sees what</h2>
      <p className="note">A role can only read facts carrying at least one of its tags. Use * for everything.</p>
      {roles.map((r) => (
        <div className="row" key={r.name}>
          <b className="rname">{r.name}</b>
          <input value={draft[r.name] ?? r.tags.join(", ")} disabled={r.name === "admin"} onChange={(e) => setDraft({ ...draft, [r.name]: e.target.value })} />
          {r.name !== "admin" && <button onClick={() => save(r.name, draft[r.name] ?? r.tags.join(", "))}>Save</button>}
        </div>
      ))}
      <div className="row">
        <input placeholder="New role, e.g. intern" value={name} onChange={(e) => setName(e.target.value)} />
        <button onClick={() => { if (name) { save(name, ""); setName(""); } }}>Add role</button>
      </div>
      {msg && <p className="note">{msg}</p>}
    </section>
  );
}

export default function App() {
  const [tab, setTab] = useState("Add");
  const [role, setRoleState] = useState("admin");
  const [roles, setRoles] = useState([]);
  const [tags, setTags] = useState([]);
  const [offline, setOffline] = useState(false);
  const reload = () => call("/roles").then(setRoles);

  useEffect(() => {
    Promise.all([reload(), call("/tags").then(setTags)]).catch(() => setOffline(true));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>ContextForge</h1>
        <nav>
          {["Add", "Find", "Access"].map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
        <label>Viewing as
          <select value={role} onChange={(e) => { setRole(e.target.value); setRoleState(e.target.value); }}>
            {(roles.length ? roles : [{ name: "admin" }]).map((r) => <option key={r.name}>{r.name}</option>)}
          </select>
        </label>
      </header>
      {offline && <p className="note err">Cannot reach the backend. Start it with: uv run main.py</p>}
      <main>
        {tab === "Add" && <Ingest />}
        {tab === "Find" && <Retrieve tags={tags} role={role} />}
        {tab === "Access" && <Access roles={roles} reload={reload} />}
      </main>
    </div>
  );
}
