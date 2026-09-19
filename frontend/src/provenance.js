/**
 * Provenance Formatter for ContextForge
 * Generates natural-language provenance sentences adhering to the Ledger design system.
 */

export function extractDomain(uri) {
  if (!uri || typeof uri !== "string") return null;
  try {
    const url = new URL(uri);
    return url.hostname.replace(/^www\./, "");
  } catch {
    const m = uri.match(/^https?:\/\/([^/:]+)/i);
    return m ? m[1].replace(/^www\./, "") : null;
  }
}

export function formatKindLabel(kind) {
  const k = (kind || "text").toLowerCase().trim();
  const map = {
    text: "a pasted note",
    url: "a web page",
    screenshot: "a screenshot (OCR)",
    file: "a file",
    directory: "a file",
    page: "a page captured with the browser extension",
    extension: "a page captured with the browser extension",
    session: "a live session",
    live: "a live session",
  };
  return map[k] || `a ${k}`;
}

export function getRelativeTimeHint(ts, now = Date.now()) {
  if (!ts) return "";
  const diffSec = Math.floor((now - ts) / 1000);
  if (diffSec < 0) return "just now";
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} ${diffMin === 1 ? "min" : "mins"} ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours} ${diffHours === 1 ? "hour" : "hours"} ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} ${Math.floor(diffDays / 7) === 1 ? "week" : "weeks"} ago`;
  return "";
}

export function formatRecordedDate(recordedAt, created, locale = undefined, now = Date.now()) {
  let ts = null;
  if (recordedAt) {
    ts = new Date(recordedAt).getTime();
  } else if (created) {
    ts = Number(created) * 1000;
  }
  if (!ts || isNaN(ts)) return "";

  const d = new Date(ts);
  const formatted = d.toLocaleString(locale || undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

  const relative = getRelativeTimeHint(ts, now);
  return relative ? `${formatted} (${relative})` : formatted;
}

/**
 * Formats a source object into a natural-language provenance sentence:
 * "From {source description}, {project context}, {when}."
 *
 * @param {Object} source - Source metadata object
 * @param {Object|string|null} currentProject - Currently active project or project name/id
 * @param {string|undefined} locale - Optional locale for testing / internationalization
 * @param {number|undefined} now - Optional timestamp override for deterministic tests
 * @returns {string} Natural-language sentence
 */
export function formatProvenance(source, currentProject = null, locale = undefined, now = Date.now()) {
  if (!source) return "";

  if (source.is_restricted || source.kind === "restricted") {
    return "From a restricted source.";
  }

  // 1. Source description
  let sourceDesc = "";
  const kindLabel = source.source_kind_label || formatKindLabel(source.kind);
  const label = source.source_label !== undefined ? source.source_label : (source.title ? `"${source.title}"` : "");
  const uri = source.uri;
  const domain = source.source_domain || extractDomain(uri);
  const mode = source.source_mode || source.mode;

  if (domain) {
    if (label && !label.includes(domain) && !label.startsWith("starting")) {
      sourceDesc = `${kindLabel} on ${domain} (${label})`;
    } else {
      sourceDesc = `${kindLabel} on ${domain}`;
    }
  } else if (label) {
    if (label.startsWith("starting") || label.startsWith('"')) {
      sourceDesc = `${kindLabel} ${label}`;
    } else {
      sourceDesc = `${kindLabel} "${label.replace(/^"|"$/g, "")}"`;
    }
  } else {
    sourceDesc = kindLabel;
  }

  if (mode === "live" && !sourceDesc.includes("live session") && !sourceDesc.includes("synced live")) {
    sourceDesc += " (synced live)";
  } else if (mode === "live" && sourceDesc.includes("live session")) {
    sourceDesc += " (synced live)";
  }

  // 2. Project context (Omit entirely when viewing that same project)
  let projectCtx = "";
  const projName = source.project_name || "";
  const curProjId = typeof currentProject === "object" ? currentProject?.id : currentProject;
  const curProjName = typeof currentProject === "object" ? currentProject?.name : (typeof currentProject === "string" ? currentProject : null);
  const sourceProjId = source.project_id;

  if (projName) {
    const isSameProject =
      (curProjId && sourceProjId && curProjId === sourceProjId) ||
      (curProjName && curProjName.toLowerCase() === projName.toLowerCase());

    if (!isSameProject && (!curProjId || sourceProjId !== curProjId)) {
      projectCtx = `in ${projName}`;
    }
  }

  // 3. When
  const whenStr = formatRecordedDate(source.recorded_at, source.created, locale, now);

  // Combine into sentence
  const parts = [`From ${sourceDesc}`, projectCtx, whenStr].filter(Boolean);
  return parts.join(", ") + ".";
}
