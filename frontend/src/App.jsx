import { useEffect, useRef, useState } from "react";
import call, { store } from "./api";

const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

// Parse tags into hierarchical groups (parent -> children), safe for array or {tree, tags} object
function buildScopeTree(tagsData) {
  const groups = {};
  if (tagsData && typeof tagsData === "object" && !Array.isArray(tagsData) && tagsData.tree) {
    for (const [parent, children] of Object.entries(tagsData.tree)) {
      groups[parent] = { isGroup: (children && children.length > 0), children: children || [] };
    }
    return groups;
  }
  const tagList = Array.isArray(tagsData) ? tagsData : (tagsData?.tags || []);
  for (const t of tagList) {
    if (typeof t !== "string") continue;
    if (t.includes("/")) {
      const [parent, child] = t.split("/");
      if (!groups[parent]) groups[parent] = { isGroup: true, children: [] };
      groups[parent].children.push(t);
    } else {
      if (!groups[t]) groups[t] = { isGroup: false, children: [] };
    }
  }
  return groups;
}

// Custom-built stamped permission slip dropdown (zero native select)
function CustomRoleDropdown({ roles, currentRole, onSelect, isSimulating, disabled = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={ref} style={{ position: "relative", width: "auto" }}>
      <button
        type="button"
        disabled={disabled}
        className={`slip-trigger ${isSimulating ? "active-preview" : ""}`}
        onClick={() => !disabled && setOpen(!open)}
        aria-label="Select role"
      >
        <span>{currentRole}</span>
        <span style={{ fontSize: "10px" }}>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="slip-menu">
          {roles.map((r) => (
            <div
              key={r.name}
              className={`slip-option ${r.name === currentRole ? "selected" : ""}`}
              onClick={() => {
                onSelect(r.name);
                setOpen(false);
              }}
            >
              <span>{r.name}</span>
              {r.name === currentRole && <span>✓</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Project Switcher dropdown in Zone A (Ledger design system)
function ProjectSwitcher({ projects, currentProject, onSelect, onOpenNewModal }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const pName = currentProject?.name || "Untitled project";
  const pType = currentProject?.project_type || "general";

  return (
    <div className="project-switcher-wrap" ref={ref}>
      <span className="project-switcher-label">Project Scope</span>
      <button
        type="button"
        className="project-trigger"
        onClick={() => setOpen(!open)}
        aria-label="Select active project"
      >
        <div className="project-trigger-content">
          <span className="project-trigger-name" title={pName}>{pName}</span>
          <span className={`project-badge ${pType}`}>[{pType}]</span>
        </div>
        <span className="mono" style={{ fontSize: "10px", color: "var(--ink-muted)" }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="project-dropdown">
          <div className="project-dropdown-list">
            {projects.map((p) => {
              const isSel = p.id === currentProject?.id;
              return (
                <div
                  key={p.id}
                  className={`project-option ${isSel ? "selected" : ""}`}
                  onClick={() => {
                    onSelect(p);
                    setOpen(false);
                  }}
                >
                  <div className="project-option-left">
                    <span className="project-option-name" title={p.name}>{p.name}</span>
                    <span className={`project-badge ${p.project_type}`}>[{p.project_type}]</span>
                  </div>
                  {isSel && <span className="mono" style={{ color: "var(--accent-stamp)", fontSize: "11px" }}>✓</span>}
                </div>
              );
            })}
          </div>
          <div className="project-dropdown-footer">
            <button
              type="button"
              className="project-add-btn"
              onClick={() => {
                setOpen(false);
                onOpenNewModal();
              }}
            >
              + New project
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Modal for creating new General / Process project
function NewProjectModal({ isOpen, onClose, onCreate }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("general");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!isOpen) return null;

  const submit = async (e) => {
    e.preventDefault();
    const clean = name.trim();
    if (!clean) {
      setErr("Project name is required");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await onCreate(clean, type);
      setName("");
      setType("general");
      onClose();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Create new project</h3>
        <p className="sub" style={{ margin: "2px 0 14px" }}>
          Scope documents, facts, and execution checklists to a distinct organizational workspace.
        </p>

        <form onSubmit={submit}>
          <div style={{ marginBottom: "12px" }}>
            <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "4px" }}>
              Project Name:
            </span>
            <input
              placeholder="e.g. Payment Gateway or Release Ops"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              style={{ margin: 0 }}
            />
          </div>

          <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "6px" }}>
            Project Type:
          </span>
          <div className="project-type-choice-group">
            <div
              className={`project-type-card ${type === "general" ? "selected" : ""}`}
              onClick={() => setType("general")}
            >
              <div className="project-type-card-title">
                <span>General</span>
                <span className="project-badge general">[general]</span>
              </div>
              <div className="project-type-card-desc">
                Standard knowledge base with facts, tags, RAG Q&A, and documentation synthesis.
              </div>
            </div>

            <div
              className={`project-type-card ${type === "process" ? "selected" : ""}`}
              onClick={() => setType("process")}
            >
              <div className="project-type-card-title">
                <span>Process</span>
                <span className="project-badge process">[process]</span>
              </div>
              <div className="project-type-card-desc">
                Procedural workflows with Action, Owner, and Dependency structuring & execution checklists.
              </div>
            </div>
          </div>

          {err && <p className="err" style={{ marginBottom: "12px" }}>{err}</p>}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Creating..." : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Multi-select TagPicker with archival ledger taxonomy dropdown
function TagPicker({ selectedTags = [], onChange, tagsData, placeholder = "+ select scope tags" }) {
  const [open, setOpen] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [newTagInput, setNewTagInput] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
        setFilterQuery("");
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const scopeTree = buildScopeTree(tagsData);

  const toggle = (t) => {
    if (selectedTags.includes(t)) {
      onChange(selectedTags.filter((x) => x !== t), false);
    } else {
      onChange([...selectedTags, t], false);
    }
  };

  const remove = (t, e) => {
    if (e) e.stopPropagation();
    onChange(selectedTags.filter((x) => x !== t), false);
  };

  const addNewTag = (e) => {
    if (e) e.stopPropagation();
    const clean = newTagInput.trim().toLowerCase();
    if (!clean) return;
    if (!selectedTags.includes(clean)) {
      onChange([...selectedTags, clean], true);
    }
    setNewTagInput("");
  };

  const q = filterQuery.trim().toLowerCase();
  const entries = Object.entries(scopeTree);
  const filteredEntries = entries.filter(([parent, info]) => {
    if (!q) return true;
    if (parent.toLowerCase().includes(q)) return true;
    if (info.children && info.children.some((c) => c.toLowerCase().includes(q))) return true;
    return false;
  });

  return (
    <div className="tag-picker-container" ref={ref}>
      <div
        className={`tag-picker-field ${open ? "is-open" : ""}`}
        onClick={() => setOpen(!open)}
      >
        <div className="tag-picker-chips">
          {selectedTags.length === 0 ? (
            <span className="tag-picker-placeholder mono">
              {placeholder}
            </span>
          ) : (
            selectedTags.map((t) => (
              <span key={t} className="ledger-chip" onClick={(e) => e.stopPropagation()}>
                <span>{t}</span>
                <button
                  type="button"
                  className="ledger-chip-remove"
                  onClick={(e) => remove(t, e)}
                  title="Remove tag"
                >
                  &times;
                </button>
              </span>
            ))
          )}
        </div>
        <span className="tag-picker-chevron">{open ? "▲" : "▼"}</span>
      </div>

      {open && (
        <div className="tag-picker-dropdown" onClick={(e) => e.stopPropagation()}>
          <div className="tag-picker-header">
            <span className="mono">Taxonomy Registry</span>
            <button
              type="button"
              className="tag-picker-close-btn"
              onClick={() => {
                setOpen(false);
                setFilterQuery("");
              }}
            >
              &times; close
            </button>
          </div>

          <div className="tag-picker-filter-wrap">
            <input
              type="text"
              className="tag-picker-filter-input"
              placeholder="Filter taxonomy scopes..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              autoFocus
            />
          </div>

          <div className="tag-picker-list">
            {filteredEntries.length === 0 ? (
              <div style={{ padding: "12px", textAlign: "center", color: "var(--ink-muted)", fontSize: "11px" }} className="mono">
                No matching taxonomy scopes found.
              </div>
            ) : (
              filteredEntries.map(([parent, info]) => {
                const isParentSelected = selectedTags.includes(parent);
                const matchingChildren = info.children
                  ? info.children.filter((c) => !q || c.toLowerCase().includes(q) || parent.toLowerCase().includes(q))
                  : [];

                return (
                  <div key={parent}>
                    <div
                      className={`tag-picker-row ${isParentSelected ? "selected" : ""}`}
                      onClick={() => toggle(parent)}
                    >
                      <div className="tag-picker-row-left">
                        <span className="tag-checkbox-glyph">{isParentSelected ? "✓" : "○"}</span>
                        <span>{parent}</span>
                      </div>
                      {isParentSelected && (
                        <span className="mono" style={{ fontSize: "10.5px", color: "var(--accent-stamp)" }}>active</span>
                      )}
                    </div>
                    {matchingChildren.map((child) => {
                      const isChildSelected = selectedTags.includes(child);
                      const subName = child.includes("/") ? child.split("/")[1] : child;
                      return (
                        <div
                          key={child}
                          className={`tag-picker-row child ${isChildSelected ? "selected" : ""}`}
                          onClick={() => toggle(child)}
                        >
                          <div className="tag-picker-row-left">
                            <span className="tag-checkbox-glyph">{isChildSelected ? "✓" : "↳"}</span>
                            <span>{subName}</span>
                          </div>
                          {isChildSelected && (
                            <span className="mono" style={{ fontSize: "10.5px", color: "var(--accent-stamp)" }}>active</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })
            )}
          </div>

          <div className="tag-picker-footer">
            <div className="new-tag-form">
              <span className="new-tag-prompt mono">+ new:</span>
              <input
                type="text"
                className="new-tag-input"
                placeholder="e.g. backend/cache..."
                value={newTagInput}
                onChange={(e) => setNewTagInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addNewTag(e))}
              />
              <button type="button" className="new-tag-add-btn" onClick={addNewTag}>
                Add
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProviderRecordCard({ status }) {
  if (!status) return null;
  const isAws = (v) => ["bedrock", "dynamodb", "titan"].includes(v.toLowerCase());
  return (
    <div className="record-card">
      <div className="record-title">
        <span>System record</span>
        <span className={`square-marker ${isAws(status.llm) || isAws(status.db) ? "" : "local"}`} />
      </div>
      <div className="record-row">
        <span>llm:</span>
        <span className={`record-val ${isAws(status.llm) ? "aws" : ""}`}>{status.llm}</span>
      </div>
      <div className="record-row">
        <span>embedding:</span>
        <span className={`record-val ${isAws(status.embedding) ? "aws" : ""}`}>{status.embedding}</span>
      </div>
      <div className="record-row">
        <span>database:</span>
        <span className={`record-val ${isAws(status.db) ? "aws" : ""}`}>{status.db}</span>
      </div>
    </div>
  );
}

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
      <form className="card primary-canvas" onSubmit={go}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
          <div className="brand-glyph" />
          <h1>ContextForge</h1>
        </div>
        <p className="sub">Knowledge plane with cryptographic provenance and tag-based access control.</p>
        <input placeholder="Username" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <input type="password" placeholder="Password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        {err && <p className="err">{err}</p>}
        <button className="primary" style={{ width: "100%", marginTop: "6px" }}>{reg ? "Create account" : "Sign in"}</button>
        <button type="button" className="link" onClick={() => { setReg(!reg); setErr(""); }} style={{ marginTop: "10px", textAlign: "center", width: "100%" }}>
          {reg ? "Already registered? Sign in" : "New operator? Create account (first is admin)"}
        </button>
      </form>
    </div>
  );
}

function FactCard({ fact }) {
  const [showSource, setShowSource] = useState(false);
  const [sourceData, setSourceData] = useState(null);
  const [loading, setLoading] = useState(false);

  const toggleSource = async () => {
    if (!showSource && !sourceData) {
      setLoading(true);
      try {
        const s = await call(`/sources/${fact.source.id}`);
        setSourceData(s);
      } catch {
        setSourceData(fact.source);
      }
      setLoading(false);
    }
    setShowSource(!showSource);
  };

  const hasProcessMeta = Boolean(fact.action || fact.owner || fact.depends_on);

  return (
    <article className="fact">
      <p>{fact.text}</p>
      {hasProcessMeta && (
        <div className="fact-process-block mono">
          {fact.action && (
            <span>
              <b className="process-label">Action:</b> {fact.action}
            </span>
          )}
          {fact.action && (fact.owner || fact.depends_on) && <span className="process-sep">·</span>}
          {fact.owner && (
            <span>
              <b className="process-label">Owner:</b> {fact.owner}
            </span>
          )}
          {fact.owner && fact.depends_on && <span className="process-sep">·</span>}
          {fact.depends_on && (
            <span>
              <b className="process-label">Requires:</b> {fact.depends_on} first
            </span>
          )}
        </div>
      )}
      <small>
        {fact.tags.map((t) => <span key={t} className="tag">{t}</span>)}
        {fact.via.map((v) => <span key={v} className="tag alt">{v}</span>)}
        <span>
          from {fact.source.uri?.startsWith("http")
            ? <a href={fact.source.uri} target="_blank" rel="noreferrer">{fact.source.title}</a>
            : fact.source.title}
        </span>
        <button type="button" className="btn-source" onClick={toggleSource}>
          {loading ? "loading..." : showSource ? "[hide source details]" : "[inspect source record]"}
        </button>
      </small>
      {showSource && (
        <div className="source-details">
          <b>source id:</b> <span>{fact.source.id}</span>
          <b>kind:</b> <span>{sourceData?.kind || "unknown"}</span>
          <b>title:</b> <span>{sourceData?.title || fact.source.title}</span>
          {sourceData?.uri && <><b>uri:</b> <span>{sourceData.uri}</span></>}
          <b>mode:</b> <span>{sourceData?.mode || "static"}</span>
          {sourceData?.project_id && <><b>project:</b> <span>{sourceData.project_id}</span></>}
          {sourceData?.created && <><b>recorded:</b> <span>{new Date(Number(sourceData.created) * 1000).toISOString().replace("T", " ").substring(0, 19)} UTC</span></>}
        </div>
      )}
    </article>
  );
}

function ScreenWatch({ log, currentProject, disabled = false }) {
  const [on, setOn] = useState(false);
  const ref = useRef({});
  const stop = () => {
    clearInterval(ref.current.timer);
    ref.current.stream?.getTracks().forEach((t) => t.stop());
    setOn(false);
  };
  useEffect(() => stop, []);
  const start = async () => {
    if (disabled) return;
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const { source_id } = await call("/sessions", "POST", {
        title: "Screen capture " + new Date().toLocaleString(),
        project_id: currentProject?.id || "proj_default",
      });
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
          log(r.skipped ? "screen unchanged" : `extracted ${r.facts} facts from screen`);
        } catch (e) { log(e.message, true); }
      };
      ref.current = { stream, timer: setInterval(tick, 20000) };
      stream.getVideoTracks()[0].onended = stop;
      setOn(true);
      tick();
    } catch (e) { log(e.message, true); }
  };
  return (
    <div className={`card secondary ${disabled ? "roster-disabled" : ""}`}>
      <h3>Screen capture watcher</h3>
      <p className="sub">Every 20 seconds the selected window is transcribed via Vision OCR.</p>
      <button className={on ? "" : "primary"} disabled={disabled} onClick={on ? stop : start}>
        {on ? "Stop watcher" : "Start watcher"}
      </button>
      {on && <span className="mono" style={{ marginLeft: "8px", color: "var(--accent-stamp)" }}>■ recording active</span>}
    </div>
  );
}

function Capture({ log, logs, tagsData, currentProject, disabled = false }) {
  const [text, setText] = useState("");
  const [manualTags, setManualTags] = useState([]);
  const [busy, setBusy] = useState(false);

  const send = async (p) => {
    if (disabled) return;
    setBusy(true);
    try {
      const payload = { ...p, tags: manualTags, project_id: currentProject?.id || "proj_default" };
      const r = await call("/ingest", "POST", payload);
      log(`Learned ${r.facts} atomic facts for project '${currentProject?.name || "Untitled"}' from ${p.title || p.url || "pasted note"}`);
    } catch (e) { log(e.message, true); }
    setBusy(false);
  };

  const submit = () => {
    if (disabled) return;
    const t = text.trim();
    if (!t) return;
    /^https?:\/\/\S+$/.test(t) ? send({ kind: "url", url: t }) : send({ kind: "text", text: t, title: "Pasted note" });
    setText("");
  };

  const drop = async (files) => {
    if (disabled) return;
    for (const f of files) await send({ kind: "text", text: await f.text(), title: f.name });
  };

  const pName = currentProject?.name || "Untitled project";
  const pType = currentProject?.project_type || "general";

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
        <h2>Ingest & capture</h2>
        <span className={`project-badge ${pType}`} style={{ fontSize: "11px", padding: "2px 6px" }}>
          scoped to: {pName} [{pType}]
        </span>
      </div>
      <p className="sub">
        Normalize unstructured documentation, web pages, and developer notes into atomic structured records
        {pType === "process" ? " (with automatic procedural action/owner/prerequisite structuring)." : "."}
      </p>

      {disabled && (
        <div className="banner warning">
          <span className="mono">access boundary:</span> Capture requires admin access. Ingestion controls are disabled in preview/member mode.
        </div>
      )}

      {/* Primary Ingestion Canvas */}
      <div className={`card primary-canvas ${disabled ? "roster-disabled" : ""}`} onDragOver={(e) => !disabled && e.preventDefault()} onDrop={(e) => { !disabled && e.preventDefault(); drop(e.dataTransfer.files); }}>
        <h3>Direct source intake</h3>
        <p className="sub">Paste an architecture URL, raw text, or drop <code>.md</code> / <code>.txt</code> files directly into the repository.</p>
        <textarea
          rows={5}
          disabled={disabled}
          placeholder={pType === "process"
            ? "e.g. DevOps engineer deploys database migrations after QA lead approves release..."
            : "https://docs.company.internal/deploy  or drop notes here..."}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        {/* Optional Tag Override */}
        <div style={{ marginTop: "6px", marginBottom: "12px" }}>
          <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "4px" }}>
            Tag assignment (optional override / supplement):
          </span>
          <TagPicker
            selectedTags={manualTags}
            onChange={(newTags) => setManualTags(newTags)}
            tagsData={tagsData}
            placeholder="+ assign tags to intake"
          />
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button className="primary" disabled={disabled || busy} onClick={submit}>
            {busy ? "Normalizing & indexing..." : "Add to knowledge"}
          </button>
        </div>
      </div>

      {/* Secondary Integrations Grid */}
      <div className="grid">
        <div className={`card secondary ${disabled ? "roster-disabled" : ""}`}>
          <h3>Browser extension intake</h3>
          <p className="sub">Load <code>extension/</code> in Chrome and paste your bearer token into <code>background.js</code> to record AI chat sessions and GitHub docs.</p>
          <button disabled={disabled} onClick={() => navigator.clipboard.writeText(store.token)}>Copy session token</button>
        </div>
        <div className={`card secondary ${disabled ? "roster-disabled" : ""}`}>
          <h3>Local folder poller</h3>
          <p className="sub">Set <code>WATCH_DIR</code> in environment to monitor local repositories for automated background indexing.</p>
        </div>
      </div>

      {/* Collapsible Ancillary Sources */}
      <details className="more-sources">
        <summary>Additional ingestion channels (screen capture)</summary>
        <div style={{ marginTop: "10px" }}>
          <ScreenWatch log={log} currentProject={currentProject} disabled={disabled} />
        </div>
      </details>

      {/* Telemetry Activity Feed */}
      <div className="card secondary" style={{ marginTop: "14px" }}>
        <h3>Intake log</h3>
        <div className="feed">
          {logs.length === 0 && <p className="sub" style={{ margin: 0 }}>No recent ingestion activity recorded in this session.</p>}
          {logs.map((l, i) => (
            <p key={i} className={l.err ? "err mono" : "mono"}>
              <span style={{ color: "var(--ink-muted)" }}>[{new Date().toISOString().substring(11, 19)}]</span> {l.msg}
            </p>
          ))}
        </div>
      </div>
    </>
  );
}

function Find({ tags, role, allowed, llmOn, currentProject }) {
  const [mode, setMode] = useState("dynamic");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState([]);
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState("");
  const [isExecutionPlan, setIsExecutionPlan] = useState(false);
  const [md, setMd] = useState("");

  const hasNoScope = role === "member" || (role !== "admin" && Array.isArray(allowed) && allowed.length === 0);
  const isProcessProject = currentProject?.project_type === "process";
  const pName = currentProject?.name || "Untitled project";
  const pType = currentProject?.project_type || "general";

  const getBody = (isProcessFlag = false) => ({
    query,
    mode,
    scope: mode === "explicit" ? scope : [],
    project_id: currentProject?.id || "proj_default",
    is_process: isProcessFlag,
  });

  const guard = (fn) => async () => { try { await fn(); } catch (e) { setRes({ error: e.message, facts: [] }); } };
  const search = guard(async () => {
    setAnswer("");
    setIsExecutionPlan(false);
    setMd("");
    setRes(await call("/retrieve", "POST", getBody(false)));
  });
  const ask = guard(async () => {
    setMd("");
    setIsExecutionPlan(false);
    const r = await call("/ask", "POST", getBody(false));
    setAnswer(r.answer);
    setRes(r);
  });
  const askAndExecute = guard(async () => {
    setMd("");
    setIsExecutionPlan(true);
    const r = await call("/ask", "POST", getBody(true));
    setAnswer(r.answer);
    setRes(r);
  });
  const pack = guard(async () => setMd((await call("/export", "POST", getBody(false))).markdown));

  const toggleTag = (t, children = []) => {
    if (scope.includes(t)) {
      setScope(scope.filter((x) => x !== t && !children.includes(x)));
    } else {
      setScope([...scope, t, ...children]);
    }
  };

  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = `context-pack-${currentProject?.name ? currentProject.name.toLowerCase().replace(/\s+/g, "-") : "all"}.md`;
    a.click();
  };

  const scopeTree = buildScopeTree(tags);

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
        <h2>Find & query</h2>
        <span className={`project-badge ${pType}`} style={{ fontSize: "11px", padding: "2px 6px" }}>
          scoped to: {pName} [{pType}]
        </span>
      </div>
      <p className="sub">Searching records under security boundary <b>{role}</b> in project <b>{pName}</b>.</p>

      {hasNoScope && (
        <div className="banner warning">
          <span className="mono">access boundary:</span> Your account has no assigned scope yet — ask an admin to assign you a role in Team.
        </div>
      )}

      {/* Primary Query Canvas */}
      <div className="card primary-canvas">
        <div className="mode-toggle">
          <span className="mode-toggle-label">Scope:</span>
          <button className={`mode-btn ${mode === "explicit" ? "on" : ""}`} onClick={() => setMode("explicit")}>
            Explicit (select tags)
          </button>
          <button className={`mode-btn ${mode === "dynamic" ? "on" : ""}`} onClick={() => setMode("dynamic")}>
            Dynamic (infer needs)
          </button>
        </div>

        {mode === "explicit" && (
          <div className="scope-tree">
            {Object.entries(scopeTree).map(([parent, info]) => {
              const allSelected = scope.includes(parent) && info.children.every((c) => scope.includes(c));
              return (
                <div key={parent} className="scope-group">
                  <div className="scope-parent">
                    <button
                      type="button"
                      className={`chip ${allSelected || scope.includes(parent) ? "on" : ""}`}
                      onClick={() => toggleTag(parent, info.children)}
                    >
                      {parent} {info.children.length > 0 && `(all ${info.children.length + 1})`}
                    </button>
                  </div>
                  {info.children.length > 0 && (
                    <div className="scope-children">
                      {info.children.map((child) => (
                        <button
                          key={child}
                          type="button"
                          className={`chip ${scope.includes(child) ? "on" : ""}`}
                          onClick={() => toggleTag(child)}
                        >
                          {child.split("/")[1]}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <input
          placeholder={
            isProcessProject
              ? "Ask how to execute a process (e.g. How do we deploy database migrations?)"
              : mode === "dynamic"
              ? "Ask a question (e.g. How is deployment configured for payments?)"
              : "Optional filter within selected scope..."
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (isProcessProject ? askAndExecute() : search())}
        />

        <div className="row" style={{ marginTop: "4px", gap: "8px", flexWrap: "wrap" }}>
          <button className="primary" onClick={search}>Search index</button>
          {llmOn && <button onClick={ask}>Synthesize answer & cite</button>}
          {llmOn && isProcessProject && (
            <button type="button" className="btn-execute" onClick={askAndExecute} title="Generate ordered step-by-step checklist runbook">
              ⚡ Ask & execute (runbook)
            </button>
          )}
          <button onClick={pack}>Generate context pack</button>
        </div>
      </div>

      {res?.error && <p className="err">{res.error}</p>}
      {answer && (
        <div className={`card answer ${isExecutionPlan ? "execution-plan" : ""}`}>
          {isExecutionPlan && (
            <h4>⚡ Operational Execution Checklist (Runbook)</h4>
          )}
          <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{answer}</div>
        </div>
      )}

      {/* Inferred tags chip list */}
      {res?.inferred && Object.keys(res.inferred).length > 0 && (
        <div style={{ display: "flex", gap: "6px", alignItems: "center", marginBottom: "10px", flexWrap: "wrap" }}>
          <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)" }}>Inferred context:</span>
          {Object.entries(res.inferred).map(([t, why]) => (
            <span key={t} className="chip inferred" title={why}>
              +{t} (inferred)
            </span>
          ))}
        </div>
      )}

      {/* Facts results list */}
      {res?.facts && (res.facts.length === 0 && !res.error
        ? <p className="sub">No facts visible to role <b>{role}</b> matched the current query in project <b>{pName}</b>.</p>
        : res.facts.map((f) => <FactCard key={f.id} fact={f} />))}

      {/* Context pack export */}
      {md && (
        <div className="card">
          <div className="row" style={{ marginBottom: "8px" }}>
            <button onClick={() => navigator.clipboard.writeText(md)}>Copy markdown</button>
            <button onClick={download}>Download context-pack.md</button>
          </div>
          <pre>{md}</pre>
        </div>
      )}
    </>
  );
}

function Team({ roles, reload, tagsData, me }) {
  const [users, setUsers] = useState([]);
  const [draftTags, setDraftTags] = useState({});
  const [hasNewTag, setHasNewTag] = useState({});
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleTags, setNewRoleTags] = useState([]);
  const [newRoleHasCustomTag, setNewRoleHasCustomTag] = useState(false);
  const [showAddRole, setShowAddRole] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => call("/users").then(setUsers).catch((e) => setMsg(e.message));
  useEffect(() => { load(); }, []);

  const guard = async (fn, ok) => {
    try {
      await fn();
      setMsg(ok);
    } catch (e) {
      setMsg(e.message);
    }
  };

  const saveRole = (rName) => {
    const tags = draftTags[rName] ?? (roles.find((x) => x.name === rName)?.tags || []);
    const isNew = hasNewTag[rName] || false;
    guard(async () => {
      await call(`/roles/${rName}`, "PUT", { tags, allow_new: isNew });
      reload();
    }, `Saved role policy: ${rName}`);
  };

  const handleCreateRole = () => {
    const cleanName = newRoleName.trim().toLowerCase();
    if (!cleanName) return;
    guard(async () => {
      await call("/roles", "POST", { name: cleanName, tags: newRoleTags, allow_new: newRoleHasCustomTag });
      setNewRoleName("");
      setNewRoleTags([]);
      setShowAddRole(false);
      reload();
    }, `Created new role: ${cleanName}`);
  };

  const setRole = (uName, newRole) => {
    guard(async () => {
      await call(`/users/${uName}/role`, "PUT", { role: newRole });
      load();
    }, `Assigned ${uName} -> ${newRole}`);
  };

  const getRoleBadge = (r) => {
    if (r.name === "admin") return <span className="badge admin">admin (unrestricted)</span>;
    if (r.tags.length === 0) return <span className="badge member">member (empty scope)</span>;
    return <span className="badge scoped">scoped ({r.tags.length} tags)</span>;
  };

  return (
    <>
      <h2>Team & access policies</h2>
      <p className="sub">Define tag permissions per role. The <code>*</code> wildcard grants global visibility across all facts.</p>

      <div className="card">
        <h3>Role specifications</h3>
        {roles.map((r) => {
          const currentTags = draftTags[r.name] ?? r.tags;
          const isAdminRole = r.name === "admin";
          return (
            <div key={r.name} style={{ borderBottom: "1px solid var(--rule-subtle)", padding: "10px 0" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <b className="mono" style={{ fontSize: "13px" }}>{r.name}</b>
                  {getRoleBadge(r)}
                </div>
                {!isAdminRole && (
                  <button type="button" onClick={() => saveRole(r.name)}>Save policy</button>
                )}
              </div>

              {isAdminRole ? (
                <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)" }}>
                  Global wildcard (*) — unrestricted access to all knowledge categories.
                </span>
              ) : (
                <TagPicker
                  selectedTags={currentTags}
                  tagsData={tagsData}
                  onChange={(newT, isNew) => {
                    setDraftTags({ ...draftTags, [r.name]: newT });
                    if (isNew) setHasNewTag({ ...hasNewTag, [r.name]: true });
                  }}
                  placeholder="+ assign scope tags"
                />
              )}
            </div>
          );
        })}

        {/* Inline One-Step Role Creator */}
        <div style={{ marginTop: "14px" }}>
          {!showAddRole ? (
            <button type="button" onClick={() => setShowAddRole(true)}>+ add new role</button>
          ) : (
            <div style={{ background: "var(--bg-canvas)", border: "1px solid var(--rule)", padding: "12px", borderRadius: "2px" }}>
              <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "6px" }}>
                New role policy:
              </span>
              <div style={{ display: "flex", gap: "8px", marginBottom: "10px" }}>
                <input
                  placeholder="Role identifier (e.g. platform-eng, qa-lead)"
                  value={newRoleName}
                  onChange={(e) => setNewRoleName(e.target.value)}
                  style={{ margin: 0, flex: 1 }}
                />
              </div>
              <div style={{ marginBottom: "10px" }}>
                <TagPicker
                  selectedTags={newRoleTags}
                  tagsData={tagsData}
                  onChange={(newT, isNew) => {
                    setNewRoleTags(newT);
                    if (isNew) setNewRoleHasCustomTag(true);
                  }}
                  placeholder="+ select initial scope tags"
                />
              </div>
              <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                <button type="button" onClick={() => setShowAddRole(false)}>Cancel</button>
                <button type="button" className="primary" onClick={handleCreateRole}>Create role</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card secondary">
        <h3>Operator roster</h3>
        {users.map((u) => {
          const isSelf = u.username === me?.user;
          return (
            <div
              key={u.username}
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--rule-subtle)" }}
              className={isSelf ? "roster-disabled" : ""}
            >
              <div style={{ display: "flex", alignItems: "center" }}>
                <b className="mono" style={{ width: "160px" }}>{u.username}</b>
                {isSelf && <span className="note-disabled">(Cannot change your own role)</span>}
              </div>
              <CustomRoleDropdown
                roles={roles}
                currentRole={u.role}
                disabled={isSelf}
                onSelect={(newRole) => setRole(u.username, newRole)}
              />
            </div>
          );
        })}
      </div>
      {msg && <p className="mono" style={{ color: "var(--accent-stamp)", fontSize: "12px", marginTop: "8px" }}>{msg}</p>}
    </>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("capture");
  const [roles, setRoles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [currentProject, setCurrentProject] = useState(null);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [tagsData, setTagsData] = useState({ tree: {}, tags: [] });
  const [status, setStatus] = useState(null);
  const [view, setView] = useState("");
  const [logs, setLogs] = useState([]);
  const log = (msg, err) => setLogs((l) => [{ msg, err }, ...l].slice(0, 12));
  const loadRoles = () => call("/roles").then(setRoles);
  const loadProjects = async () => {
    try {
      const pList = await call("/projects");
      setProjects(pList);
      const savedPid = localStorage.getItem("cf_project_id");
      const matched = pList.find((p) => p.id === savedPid);
      if (matched) {
        setCurrentProject(matched);
      } else if (pList.length > 0) {
        setCurrentProject(pList[0]);
      }
    } catch {
      setProjects([]);
    }
  };

  const handleSelectProject = (proj) => {
    setCurrentProject(proj);
    localStorage.setItem("cf_project_id", proj.id);
  };

  const handleCreateProject = async (name, project_type) => {
    const created = await call("/projects", "POST", { name, project_type });
    await loadProjects();
    handleSelectProject(created);
    log(`Created project '${created.name}' [${created.project_type}]`);
  };

  const boot = async () => {
    try {
      const [m, s, rList, tData, pList] = await Promise.all([
        call("/me"),
        call("/status").catch(() => null),
        call("/roles").catch(() => []),
        call("/tags").catch(() => ({ tree: {}, tags: [] })),
        call("/projects").catch(() => []),
      ]);
      setMe(m);
      setStatus(s);
      setRoles(rList);
      setTagsData(tData);
      setProjects(pList);
      const savedPid = localStorage.getItem("cf_project_id");
      const matched = pList.find((p) => p.id === savedPid);
      if (matched) {
        setCurrentProject(matched);
      } else if (pList.length > 0) {
        setCurrentProject(pList[0]);
      }
      setTab(m.role === "admin" ? "capture" : "find");
    } catch {
      setMe(null);
    }
    setReady(true);
  };

  useEffect(() => { boot(); }, []);

  if (!ready) return null;
  if (!me) return <Login onDone={boot} />;

  const admin = me.role === "admin";
  const isSimulating = Boolean(view && view !== me.role);
  const isNonAdminPreview = isSimulating || !admin;
  const pick = (v) => { store.view = v === me.role ? "" : v; setView(store.view); };
  const out = () => { localStorage.removeItem("cf_token"); store.token = ""; store.view = ""; setView(""); setMe(null); };
  const nav = [admin && ["capture", "Capture"], ["find", "Find"], admin && ["team", "Team"]].filter(Boolean);

  return (
    <div className="shell">
      <aside>
        {/* Zone A: Brand, Project Switcher & Catalog Navigation */}
        <div className="sidebar-zone">
          <div className="brand">
            <div className="brand-glyph" />
            <span className="brand-title">ContextForge</span>
          </div>

          <ProjectSwitcher
            projects={projects}
            currentProject={currentProject}
            onSelect={handleSelectProject}
            onOpenNewModal={() => setIsProjectModalOpen(true)}
          />

          <div className="nav-index">
            {nav.map(([k, l]) => (
              <button
                key={k}
                className={`nav-item ${tab === k ? "on" : ""}`}
                onClick={() => setTab(k)}
              >
                <span>{l}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Zone B: Stamped Record Card for Active Providers */}
        <div className="sidebar-zone">
          <ProviderRecordCard status={status} />
        </div>

        {/* Zone C: Stamped Role Preview Slip */}
        {admin && (
          <div className="sidebar-zone preview-control-zone">
            <span className="preview-label">Preview as</span>
            <CustomRoleDropdown
              roles={roles}
              currentRole={view || me.role}
              onSelect={pick}
              isSimulating={isSimulating}
            />
          </div>
        )}

        <div className="sidebar-zone grow" />

        {/* Zone D: Identity Slip (Pinned to bottom) */}
        <div className="sidebar-zone">
          <div className="identity-slip">
            <div className="user-record">
              <span className="avatar-initial">{me.user[0].toUpperCase()}</span>
              <div className="user-meta">
                <span className="user-handle">{me.user}</span>
                <span className="user-role-tag">{me.role}</span>
              </div>
            </div>
            <button type="button" className="btn-signout" onClick={out} title="Sign out">
              Sign out →
            </button>
          </div>
        </div>
      </aside>

      <main>
        {isSimulating && (
          <div className="banner simulating">
            <span>[previewing as: <b>{view}</b>]</span>
            <span style={{ color: "var(--ink-primary)" }}>Active access boundary preview. Queries only return records visible to this role.</span>
          </div>
        )}
        {tab === "capture" && admin && (
          <Capture
            log={log}
            logs={logs}
            tagsData={tagsData}
            currentProject={currentProject}
            disabled={isNonAdminPreview}
          />
        )}
        {tab === "find" && (
          <Find
            key={(view || me.role) + "_" + (currentProject?.id || "")}
            tags={tagsData}
            role={view || me.role}
            allowed={me.allowed}
            llmOn={me.llm}
            currentProject={currentProject}
          />
        )}
        {tab === "team" && admin && (
          <Team
            roles={roles}
            reload={loadRoles}
            tagsData={tagsData}
            me={me}
          />
        )}
      </main>

      <NewProjectModal
        isOpen={isProjectModalOpen}
        onClose={() => setIsProjectModalOpen(false)}
        onCreate={handleCreateProject}
      />
    </div>
  );
}

