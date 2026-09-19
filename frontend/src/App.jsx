import { useEffect, useRef, useState } from "react";
import call, { store } from "./api";
import { formatProvenance, formatRecordedDate } from "./provenance";


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
  const pMode = currentProject?.structure_mode || "rag";

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
          <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
            <span className={`project-badge ${pMode}`} title={`Structure Mode: ${pMode}`}>[{pMode}]</span>
            {pType === "process" && <span className="project-badge process">[process]</span>}
          </div>
        </div>
        <span className="mono" style={{ fontSize: "10px", color: "var(--ink-muted)" }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="project-dropdown">
          <div className="project-dropdown-list">
            {projects.map((p) => {
              const isSel = p.id === currentProject?.id;
              const mode = p.structure_mode || "rag";
              return (
                <div
                  key={p.id}
                  className={`project-option ${isSel ? "selected" : ""}`}
                  onClick={() => {
                    onSelect(p);
                    setOpen(false);
                  }}
                  title={p.classification_reason || `Project mode: ${mode}`}
                >
                  <div className="project-option-left">
                    <span className="project-option-name" title={p.name}>{p.name}</span>
                    <span className={`project-badge ${mode}`}>[{mode}]</span>
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

// Modal for creating new Project with LLM classification or manual mode
function NewProjectModal({ isOpen, onClose, onCreate }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("general");
  const [mode, setMode] = useState("auto");
  const [sampleText, setSampleText] = useState("");
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
      await onCreate(clean, type, mode === "auto" ? null : mode, sampleText.trim());
      setName("");
      setType("general");
      setMode("auto");
      setSampleText("");
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
        <h3>Create new project workspace</h3>
        <p className="sub" style={{ margin: "2px 0 14px" }}>
          Scope documents, facts, and retrieval paradigms to a dedicated knowledge domain.
        </p>

        <form onSubmit={submit}>
          <div style={{ marginBottom: "12px" }}>
            <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "4px" }}>
              Project Name:
            </span>
            <input
              placeholder="e.g. Refund Policy, Cloud Infra Config, or Release Ops"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              style={{ margin: 0 }}
            />
          </div>

          <div style={{ marginBottom: "12px" }}>
            <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "4px" }}>
              Sample Content / Purpose (for AI classification):
            </span>
            <textarea
              placeholder="Describe what kind of knowledge this project holds (e.g. 'If refund > 500 then approve...')"
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              rows={2}
              style={{ margin: 0, width: "100%", fontFamily: "var(--font-sans)", fontSize: "12.5px" }}
            />
          </div>

          <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "6px" }}>
            Execution Type:
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
                Procedural workflows with Action, Owner, and Dependency runbook checklists.
              </div>
            </div>
          </div>

          <div style={{ marginBottom: "16px" }}>
            <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", display: "block", marginBottom: "4px" }}>
              Retrieval Paradigm:
            </span>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="mode-override-select"
              style={{ width: "100%", padding: "6px 8px" }}
            >
              <option value="auto">✨ Auto-classify dynamically via AI (Recommended)</option>
              <option value="rag">RAG — Open-ended hybrid multi-index synthesis</option>
              <option value="ruleset">Ruleset — Conditional logic (if/then branches, policy thresholds)</option>
              <option value="keyvalue">Key-Value — Direct configuration lookup & parameters</option>
              <option value="denylist">Denylist — Anti-patterns, rejected tools & guardrails</option>
              <option value="versioned">Versioned — Temporal evolution, pricing tiers & history</option>
              <option value="graph">Graph — Sequential dependencies & execution checklists</option>
              <option value="allowlist">Allowlist — Strict tag membership, zero fuzzy matching</option>
              <option value="keyword">Keyword — Literal error codes, configs & path lookups</option>
            </select>
          </div>

          {err && <p className="err" style={{ marginBottom: "12px" }}>{err}</p>}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
            <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Creating & Classifying..." : "Create project"}
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

function HistoryModal({ factId, isOpen, onClose }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && factId) {
      setLoading(true);
      call(`/facts/${factId}/history`)
        .then((data) => setHistory(data))
        .catch(() => setHistory([]))
        .finally(() => setLoading(false));
    }
  }, [isOpen, factId]);

  if (!isOpen) return null;

  return (
    <div className="project-modal-backdrop" onClick={onClose}>
      <div className="project-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Fact Evolution & Version History</h3>
        <p className="sub" style={{ margin: "2px 0 14px" }}>
          Chronological chain of superseded and active versions for this record.
        </p>
        {loading ? (
          <p className="mono">Loading history chain...</p>
        ) : history.length === 0 ? (
          <p className="sub">No prior versions found for this fact.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {history.map((h, idx) => (
              <div
                key={h.id}
                style={{
                  border: "1px solid var(--rule)",
                  borderLeft: h.superseded_by ? "3px solid var(--ink-muted)" : "3px solid var(--accent-stamp)",
                  padding: "8px 10px",
                  background: h.superseded_by ? "var(--bg-canvas)" : "var(--bg-panel)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                  <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)" }}>
                    Version {idx + 1} (Fact #{h.id})
                  </span>
                  <span className={`project-badge ${h.superseded_by ? "rag" : "versioned"}`}>
                    {h.superseded_by ? `superseded by #${h.superseded_by}` : "active (current)"}
                  </span>
                </div>
                <div style={{ fontSize: "13px" }}>{h.text}</div>
                {h.created && (
                  <div className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)", marginTop: "4px" }}>
                    Recorded: {formatRecordedDate(null, h.created)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "16px" }}>
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function FactCard({ fact, currentProject }) {
  const [showSource, setShowSource] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [sourceData, setSourceData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const toggleSource = async () => {
    if (!showSource && !sourceData && fact.source?.id) {
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
  const hasRuleMeta = Boolean(fact.condition || fact.outcome);
  const hasKeyMeta = Boolean(fact.key);
  const isSuperseded = fact.superseded_by !== null && fact.superseded_by !== undefined;

  const rawSentence = formatProvenance(fact.source, currentProject);
  const domain = fact.source?.source_domain;
  const uri = fact.source?.uri;

  // Render sentence with clickable domain link if uri and domain are present
  const renderProvenanceSentence = () => {
    if (domain && uri && rawSentence.includes(domain)) {
      const parts = rawSentence.split(domain);
      return (
        <span
          className="provenance-sentence"
          onClick={toggleSource}
          role="button"
          tabIndex={0}
          title="Click to inspect source details"
        >
          {parts[0]}
          <a
            href={uri}
            target="_blank"
            rel="noreferrer"
            className="provenance-domain-link"
            onClick={(e) => e.stopPropagation()}
            title={`Open ${uri}`}
          >
            {domain}
          </a>
          {parts.slice(1).join(domain)}
        </span>
      );
    }

    return (
      <span
        className="provenance-sentence"
        onClick={toggleSource}
        role="button"
        tabIndex={0}
        title="Click to inspect source details"
      >
        {rawSentence}
      </span>
    );
  };

  return (
    <article className="fact">
      <p>{fact.text}</p>

      {/* Ruleset mode structured conditional block */}
      {hasRuleMeta && (
        <div className="fact-rule-block mono">
          {fact.condition && (
            <span>
              <b style={{ color: "#5D3B8E" }}>Condition:</b> {fact.condition}
            </span>
          )}
          {fact.condition && fact.outcome && <span className="process-sep">→</span>}
          {fact.outcome && (
            <span>
              <b style={{ color: "#5D3B8E" }}>Outcome:</b> {fact.outcome}
            </span>
          )}
        </div>
      )}

      {/* Key-Value mode canonical key block */}
      {hasKeyMeta && (
        <div className="fact-kv-block mono">
          <b style={{ color: "#2B547E" }}>Canonical Key:</b> <code>{fact.key}</code>
        </div>
      )}

      {/* Versioned mode supersession indicator */}
      {isSuperseded && (
        <div className="fact-version-block mono">
          <span>⚠️ <b>Superseded:</b> Replaced by newer Fact #{fact.superseded_by}</span>
        </div>
      )}

      {/* Graph / Process operational block */}
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

      <div className="fact-footer">
        <div className="fact-tags-row">
          {fact.tags.map((t) => <span key={t} className="tag">{t}</span>)}
          {fact.via.map((v) => <span key={v} className="tag alt">{v}</span>)}
        </div>

        <div className="fact-provenance-row">
          {renderProvenanceSentence()}

          <div className="fact-provenance-actions">
            <button type="button" className="btn-source-action" onClick={toggleSource}>
              {loading ? "loading..." : showSource ? "Hide source" : "Show source"}
            </button>
            {(fact.key || isSuperseded) && (
              <button type="button" className="btn-source-action" onClick={() => setShowHistory(true)}>
                History chain
              </button>
            )}
          </div>
        </div>
      </div>

      {showSource && (
        <div className="source-detail-card">
          <div className="source-detail-grid">
            <div className="source-detail-row">
              <span className="source-detail-label">Source</span>
              <div className="source-detail-val">
                {sourceData?.uri ? (
                  <a
                    href={sourceData.uri}
                    target="_blank"
                    rel="noreferrer"
                    className="source-uri-link"
                  >
                    {sourceData.title || sourceData.uri} ↗
                  </a>
                ) : (
                  <span>{sourceData?.title || fact.source?.title || "Pasted note"}</span>
                )}
                {sourceData?.mode && sourceData.mode !== "static" && (
                  <span className="source-mode-pill">({sourceData.mode})</span>
                )}
              </div>
            </div>

            <div className="source-detail-row">
              <span className="source-detail-label">Added</span>
              <div className="source-detail-val">
                {formatRecordedDate(sourceData?.recorded_at, sourceData?.created) || "Timestamp unavailable"}
              </div>
            </div>

            <div className="source-detail-row">
              <span className="source-detail-label">Project</span>
              <div className="source-detail-val">
                <span>{sourceData?.project_name || fact.source?.project_name || "Default Workspace"}</span>
              </div>
            </div>

            <div className="source-detail-row">
              <span className="source-detail-label">Reference</span>
              <div className="source-detail-val ref-cell">
                <code className="source-ref-code">{sourceData?.id || fact.source?.id}</code>
                <button
                  type="button"
                  className="btn-copy-ref"
                  onClick={() => {
                    navigator.clipboard.writeText(sourceData?.id || fact.source?.id || "");
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  title="Copy raw reference ID for tracing"
                >
                  {copied ? "✓ Copied" : "Copy reference"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <HistoryModal
        factId={fact.id}
        isOpen={showHistory}
        onClose={() => setShowHistory(false)}
      />
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
      if (r.warnings && r.warnings.length > 0) {
        r.warnings.forEach((w) => log(w.warning || w, true));
      }
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
  const pMode = currentProject?.structure_mode || "rag";

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
        <h2>Ingest & capture</h2>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <span className={`project-badge ${pMode}`}>[{pMode}]</span>
          <span className={`project-badge ${pType}`} style={{ fontSize: "11px", padding: "2px 6px" }}>
            scoped to: {pName}
          </span>
        </div>
      </div>
      <p className="sub">
        Normalize unstructured documentation, configs, and notes into atomic structured facts
        {pMode === "ruleset" ? " (conditional rules & outcomes)"
          : pMode === "keyvalue" ? " (canonical key-value configs)"
          : pMode === "denylist" ? " (anti-pattern guardrails)"
          : pMode === "versioned" ? " (temporal version evolution)"
          : pMode === "graph" || pType === "process" ? " (procedural action/owner/prerequisite checklists)"
          : " (hybrid multi-index graph/vector/flat)."}
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
          placeholder={pMode === "ruleset"
            ? "e.g. If refund_amount > 500 then Requires VP approval. If account_age < 30_days then Reject refund..."
            : pMode === "keyvalue"
            ? "e.g. DATABASE_PORT: 5432\nREDIS_HOST: redis.internal.net\nMAX_WORKERS: 8..."
            : pMode === "denylist"
            ? "e.g. Do not use MongoDB for billing transactions due to lack of multi-table ACID isolation..."
            : pMode === "versioned"
            ? "e.g. pro_tier_price: $49/mo in 2025 (updated from $29/mo)..."
            : pType === "process" || pMode === "graph"
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

function Find({ tags, role, allowed, llmOn, currentProject, onUpdateProjectMode }) {
  const [mode, setMode] = useState("dynamic");
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState([]);
  const [includeHistory, setIncludeHistory] = useState(false);
  const [res, setRes] = useState(null);
  const [answer, setAnswer] = useState("");
  const [isExecutionPlan, setIsExecutionPlan] = useState(false);
  const [md, setMd] = useState("");

  const hasNoScope = role === "member" || (role !== "admin" && Array.isArray(allowed) && allowed.length === 0);
  const isProcessProject = currentProject?.project_type === "process";
  const pName = currentProject?.name || "Untitled project";
  const pType = currentProject?.project_type || "general";
  const pMode = currentProject?.structure_mode || "rag";

  const getBody = (isProcessFlag = false) => ({
    query,
    mode,
    scope: mode === "explicit" ? scope : [],
    project_id: currentProject?.id || "proj_default",
    is_process: isProcessFlag,
    include_history: includeHistory,
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px", flexWrap: "wrap", gap: "8px" }}>
        <h2>Find & query</h2>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          {/* Manual Mode Override Dropdown */}
          <div className="mode-override-wrap">
            <span className="mono" style={{ fontSize: "11px", color: "var(--ink-muted)" }}>Mode:</span>
            <select
              value={pMode}
              onChange={(e) => onUpdateProjectMode && onUpdateProjectMode(e.target.value)}
              className="mode-override-select"
              title="Change project retrieval mode override"
            >
              <option value="rag">RAG (Hybrid multi-index)</option>
              <option value="ruleset">Ruleset (Conditional logic)</option>
              <option value="keyvalue">Key-Value (Config parameters)</option>
              <option value="denylist">Denylist (Anti-patterns & guardrails)</option>
              <option value="versioned">Versioned (Temporal pricing/spec)</option>
              <option value="graph">Graph (Sequential runbooks)</option>
              <option value="allowlist">Allowlist (Strict tag scope)</option>
              <option value="keyword">Keyword (Literal error & paths)</option>
            </select>
          </div>

          {currentProject?.classification_reason && (
            <span className="mode-reason-tooltip" title={`Classification: ${currentProject.classification_reason}`}>
              ℹ️ {currentProject.classification_reason.length > 28 ? currentProject.classification_reason.substring(0, 26) + "..." : currentProject.classification_reason}
            </span>
          )}

          <span className={`project-badge ${pType}`} style={{ fontSize: "11px", padding: "2px 6px" }}>
            {pName}
          </span>
        </div>
      </div>
      <p className="sub">
        Searching records under security boundary <b>{role}</b> in project <b>{pName}</b> (operating in <b>{pMode}</b> mode).
      </p>

      {hasNoScope && (
        <div className="banner warning">
          <span className="mono">access boundary:</span> Your account has no assigned scope yet — ask an admin to assign you a role in Team.
        </div>
      )}

      {/* Guardrail Violation Warnings if returned */}
      {res?.warnings && res.warnings.length > 0 && (
        <div className="guardrail-alert-box">
          <div className="guardrail-alert-title">
            <span>⚠️ Guardrail Violation Warning</span>
          </div>
          {res.warnings.map((w, idx) => (
            <div key={idx} style={{ marginTop: "2px" }}>{w.warning || w}</div>
          ))}
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
            pMode === "ruleset"
              ? "Ask a policy/rule question (e.g. What happens if refund_amount > 500?)"
              : pMode === "keyvalue"
              ? "Enter canonical key to lookup (e.g. DATABASE_PORT or REDIS_HOST)"
              : pMode === "denylist"
              ? "Check a proposed approach for guardrails (e.g. Can we use MongoDB for billing?)"
              : pMode === "versioned"
              ? "Query pricing tier or spec (e.g. pro_tier_price)"
              : isProcessProject || pMode === "graph"
              ? "Ask how to execute a process (e.g. How do we deploy database migrations?)"
              : mode === "dynamic"
              ? "Ask a question (e.g. How is deployment configured for payments?)"
              : "Optional filter within selected scope..."
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (isProcessProject || pMode === "graph" ? askAndExecute() : pMode === "keyvalue" || pMode === "ruleset" ? ask() : search())}
        />

        {/* Versioned Mode History Toggle */}
        {pMode === "versioned" && (
          <div style={{ margin: "4px 0 8px" }}>
            <label className="mono" style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "11.5px", cursor: "pointer", color: "var(--ink-muted)" }}>
              <input
                type="checkbox"
                checked={includeHistory}
                onChange={(e) => setIncludeHistory(e.target.checked)}
              />
              <span>Include prior superseded version history</span>
            </label>
          </div>
        )}

        {/* Mode-Adaptive Action Buttons */}
        <div className="row" style={{ marginTop: "4px", gap: "8px", flexWrap: "wrap" }}>
          <button className="primary" onClick={search}>Search index</button>

          {pMode === "ruleset" && (
            <button type="button" className="btn-execute" onClick={ask} title="Evaluate conditional rule branches">
              ⚖️ Evaluate ruleset
            </button>
          )}

          {pMode === "keyvalue" && (
            <button type="button" className="btn-execute" onClick={ask} title="Direct canonical key lookup">
              🔑 Lookup key value
            </button>
          )}

          {llmOn && pMode !== "ruleset" && pMode !== "keyvalue" && (
            <button onClick={ask}>Synthesize answer & cite</button>
          )}

          {(isProcessProject || pMode === "graph") && (
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
          {pMode === "ruleset" && (
            <h4 style={{ color: "#5D3B8E", marginBottom: "6px" }}>⚖️ Policy Ruleset Decision</h4>
          )}
          {pMode === "denylist" && (
            <h4 style={{ color: "var(--accent-flag)", marginBottom: "6px" }}>⚠️ Architectural Guardrail Evaluation</h4>
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
        : res.facts.map((f) => <FactCard key={f.id} fact={f} currentProject={currentProject} />))}


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

  const handleCreateProject = async (name, project_type, structure_mode, sample_text) => {
    const payload = { name, project_type };
    if (structure_mode) payload.structure_mode = structure_mode;
    if (sample_text) payload.sample_text = sample_text;
    const created = await call("/projects", "POST", payload);
    await loadProjects();
    handleSelectProject(created);
    log(`Created project '${created.name}' [mode: ${created.structure_mode || "rag"}]`);
  };

  const handleUpdateProjectMode = async (newMode) => {
    if (!currentProject) return;
    try {
      const updated = await call(`/projects/${currentProject.id}/mode`, "PUT", {
        structure_mode: newMode,
        classification_reason: "Manual override by user",
      });
      setCurrentProject(updated);
      setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      log(`Switched project '${updated.name}' to [${updated.structure_mode}] mode`);
    } catch (e) {
      log(`Failed to update mode: ${e.message}`, true);
    }
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
            key={(view || me.role) + "_" + (currentProject?.id || "") + "_" + (currentProject?.structure_mode || "")}
            tags={tagsData}
            role={view || me.role}
            allowed={me.allowed}
            llmOn={me.llm}
            currentProject={currentProject}
            onUpdateProjectMode={handleUpdateProjectMode}
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

