"""Storage + retrieval. Three pluggable indexes (keyword, vector, graph) behind one interface.
put_fact() enforces provenance and search_facts() enforces access control for EVERY index."""
import itertools
import json
import logging
import re
from abc import ABC, abstractmethod

import networkx as nx
from typing import Any


from .auth import is_visible
from .factory import get_embedding_provider, get_fact_repository, get_llm_provider
from .strategies import get_strategy

logger = logging.getLogger("contextforge")

TAXONOMY = {
    "backend": ["server", "backend", "service", "worker", "queue", "fastapi", "django", "flask", "node", "cache"],
    "frontend": ["frontend", "react", "vue", "css", "component", "ui", "browser", "vite"],
    "database": ["postgres", "postgresql", "mysql", "sql", "redis", "mongodb", "schema", "migration", "database", "db"],
    "deploy": ["deploy", "deployment", "docker", "kubernetes", "ci", "cd", "aws", "terraform", "nginx", "pipeline", "staging", "production"],
    "api": ["api", "endpoint", "rest", "graphql", "route", "http", "auth", "jwt", "oauth", "webhook"],
    "process": ["workflow", "review", "sprint", "policy", "onboarding", "meeting", "standup", "release", "owner"],
}
IMPLIES = {
    "deploy": ["database", "backend"],
    "api": ["backend", "database"],
    "backend": ["database"],
    "frontend": ["api"],
    "database": ["backend"],
}
VOCAB = {w for ws in TAXONOMY.values() for w in ws}


def tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def tag(text: str) -> list[str]:
    return [t for t, k in TAXONOMY.items() if set(tok(text)) & set(k)] or ["general"]


def ents(text: str) -> list[str]:
    return sorted(set(tok(text)) & VOCAB)


def chunk(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n+|(?<=[.!?])\s+", text) if len(s.strip()) > 15]


def check_embedding_dimension_consistency():
    """Startup check: warns if switching embedding providers on a non-empty fact store with mismatched dimensions."""
    try:
        repo = get_fact_repository()
        emb_prov = get_embedding_provider()
        sample_vec = emb_prov.embed(["probe"])[0]
        current_dim = len(sample_vec)

        stored_vecs = repo.get_all_vectors()
        if stored_vecs:
            first_key = next(iter(stored_vecs))
            existing_dim = len(stored_vecs[first_key])
            if existing_dim != current_dim:
                logger.warning(
                    f"⚠️ EMBEDDING DIMENSION MISMATCH: Stored vectors have dimension {existing_dim}, "
                    f"but active provider '{emb_prov.__class__.__name__}' produces dimension {current_dim}. "
                    "Vector similarity calculations across mismatched dimensions will fail. "
                    "Please re-index or reset the database when switching embedding models."
                )
    except Exception as e:
        logger.debug(f"Could not verify embedding dimension consistency: {e}")


# ---------- extraction: LLM Provider with heuristic fallback ----------
# ---------- extraction: LLM Provider with heuristic fallback ----------
def extract(text: str, is_process: bool = False, structure_mode: str = "rag") -> list[dict]:
    llm_prov = get_llm_provider()
    if llm_prov.enabled():
        try:
            facts = llm_prov.extract_facts(text, is_process=is_process, structure_mode=structure_mode)
            if facts:
                return [
                    {
                        "text": f.text,
                        "tags": f.tags or tag(f.text),
                        "rels": f.rels,
                        "action": f.action,
                        "owner": f.owner,
                        "depends_on": f.depends_on,
                        "key": f.key,
                        "condition": f.condition,
                        "outcome": f.outcome,
                        "superseded_by": f.superseded_by,
                    }
                    for f in facts
                ]
        except Exception as e:
            logger.debug(f"LLM extraction failed, using heuristics: {e}")

    # Fallback heuristic extraction
    from .providers.llm import heuristic_extract_facts
    facts = heuristic_extract_facts(text, is_process=is_process, structure_mode=structure_mode)
    return [
        {
            "text": f.text,
            "tags": f.tags or tag(f.text),
            "rels": [[a, "related_to", b] for a, b in itertools.combinations(ents(f.text), 2)],
            "action": f.action,
            "owner": f.owner,
            "depends_on": f.depends_on,
            "key": f.key,
            "condition": f.condition,
            "outcome": f.outcome,
            "superseded_by": f.superseded_by,
        }
        for f in facts
    ]


# ---------- indexes ----------
class Store(ABC):
    name = ""

    def index(self, fid: int, text: str, rels: list[list[str]]):
        pass

    def prepare(self, query: str, allowed_fact_ids: set[int] | None = None):
        return None

    @abstractmethod
    def score(self, query: str, fact: dict, ctx: any) -> float:
        ...


class FlatStore(Store):
    name = "flat"

    def score(self, query: str, fact: dict, ctx: any) -> float:
        q_toks = set(tok(query))
        f_toks = set(tok(fact["text"]))
        if fact.get("key"):
            f_toks.update(tok(fact["key"]))
        return float(len(q_toks & f_toks))


class VectorStore(Store):
    name = "vector"

    def index(self, fid: int, text: str, rels: list[list[str]]):
        repo = get_fact_repository()
        emb_prov = get_embedding_provider()
        v = emb_prov.embed_documents([text])[0]
        repo.put_vector(fid, v.tobytes(), model_name=emb_prov.model_name, dim=emb_prov.dimension)

    def index_batch(self, items: list[tuple[int, str]]):
        if not items:
            return
        repo = get_fact_repository()
        emb_prov = get_embedding_provider()
        texts = [t for _, t in items]
        try:
            vecs = emb_prov.embed_documents(texts)
            for (fid, _), v in zip(items, vecs):
                repo.put_vector(fid, v.tobytes(), model_name=emb_prov.model_name, dim=emb_prov.dimension)
        except Exception as e:
            logger.warning(f"VectorStore index_batch failed: {e}")

    def prepare(self, query: str, allowed_fact_ids: set[int] | None = None):
        emb_prov = get_embedding_provider()
        repo = get_fact_repository()
        q_vec = emb_prov.embed_query(query)
        all_vecs = repo.get_all_vectors(model_name=emb_prov.model_name, dim=emb_prov.dimension)
        if allowed_fact_ids is not None:
            all_vecs = {fid: v for fid, v in all_vecs.items() if fid in allowed_fact_ids}
        return q_vec, all_vecs

    def score(self, query: str, fact: dict, ctx: any) -> float:
        if ctx is None or fact["id"] not in ctx[1]:
            return 0.0
        doc_vec = ctx[1][fact["id"]]
        if len(ctx[0]) != len(doc_vec):
            return 0.0  # Safe guard against mismatched dimensions
        return float(ctx[0] @ doc_vec)



class GraphStore(Store):
    """Facts contribute (subject, relation, object) edges; a query walks up to 2 hops from entities it mentions.
    RBAC LEAK PROTECTION: Edges from invisible/restricted facts are strictly excluded from graph construction."""
    name = "graph"

    def index(self, fid: int, text: str, rels: list[list[str]]):
        repo = get_fact_repository()
        repo.put_edges(fid, rels)

    def prepare(self, query: str, allowed_fact_ids: set[int] | None = None):
        repo = get_fact_repository()
        E = repo.get_all_edges()
        if not E:
            return None
        # Enforce RBAC boundary on graph connectivity: never build edges through unauthorized facts
        if allowed_fact_ids is not None:
            E = [e for e in E if e["fact_id"] in allowed_fact_ids]
            if not E:
                return None

        G, by = nx.Graph(), {}
        for e in E:
            G.add_edge(e["a"], e["b"])
            by.setdefault(e["fact_id"], set()).update((e["a"], e["b"]))
        q = query.lower()
        seeds = [n for n in G if len(n) > 2 and n in q]
        return by, (nx.multi_source_dijkstra_path_length(G, seeds, cutoff=2) if seeds else {})

    def score(self, query: str, fact: dict, ctx: any) -> float:
        if not ctx:
            return 0.0
        by, dist = ctx
        return max((1 / (1 + dist[n]) for n in by.get(fact["id"], ()) if n in dist), default=0.0)


STORES = {s.name: s() for s in (FlatStore, VectorStore, GraphStore)}
WEIGHT = {"flat": 0.12, "vector": 1.0, "graph": 0.6}


class StructureResult(int):
    """Subclass of int that carries structured metadata (warnings, rejected items) for backwards compatibility."""
    warnings: list[dict]
    rejected: int

    def __new__(cls, val: int, warnings: list[dict] | None = None, rejected: int = 0):
        obj = super().__new__(cls, val)
        obj.warnings = warnings or []
        obj.rejected = rejected
        return obj


def put_fact(
    text: str,
    tags: list[str],
    source_id: str,
    structures: list[str],
    rels: list[list[str]] = (),
    action: str | None = None,
    owner: str | None = None,
    depends_on: str | None = None,
    key: str | None = None,
    condition: str | None = None,
    outcome: str | None = None,
    superseded_by: int | None = None,
    defer_vector: bool = False,
):
    repo = get_fact_repository()
    # PROVENANCE: no valid source, no fact. Same text is never stored twice (keeps live capture clean).
    if not repo.source_exists(source_id):
        raise ValueError("every fact needs a valid source_id")
    if repo.fact_exists_by_text(text):
        return None

    fid = repo.put_fact(
        text,
        tags,
        source_id,
        structures,
        rels,
        action=action,
        owner=owner,
        depends_on=depends_on,
        key=key,
        condition=condition,
        outcome=outcome,
        superseded_by=superseded_by,
    )
    if fid is not None:
        for s in structures:
            if s in STORES:
                if s == "vector" and defer_vector:
                    continue
                STORES[s].index(fid, text, rels)
    return fid


def structure_doc(
    text: str,
    source_id: str,
    structures: list[str],
    extra_tags: list[str] = (),
    is_process: bool = False,
    project_id: str | None = None,
    structure_mode: str | None = None,
) -> StructureResult:
    repo = get_fact_repository()

    # Determine project structure mode if not passed explicitly
    if not structure_mode and project_id:
        p = repo.get_project(project_id)
        if p:
            structure_mode = p.get("structure_mode", "rag")
            if p.get("project_type") == "process":
                is_process = True
    if not structure_mode:
        structure_mode = "graph" if is_process else "rag"

    warnings = []
    # 1. Guardrail conflict check: check incoming text against existing rejected facts
    try:
        rejected_facts = repo.get_rejected_facts()
        text_lower = text.lower()
        text_toks = set(tok(text))
        stopwords = {"do", "not", "use", "for", "the", "a", "an", "in", "to", "of", "due", "and", "or", "is", "we", "be", "with", "lack"}
        for rf in rejected_facts:
            rf_text = rf.get("text", "").lower()
            rf_sig_toks = set(tok(rf_text)) - stopwords
            overlap = rf_sig_toks & text_toks
            is_match = False
            if rf_text and len(rf_text) > 4 and rf_text in text_lower:
                is_match = True
            elif len(rf_sig_toks) >= 2 and len(overlap) >= 2:
                is_match = True
            elif len(rf_sig_toks) == 1 and len(overlap) == 1:
                is_match = True

            if is_match:
                warnings.append({
                    "warning": f"⚠️ Ingested content mentions rejected pattern: '{rf['text']}' (Reason: {rf.get('reason', 'Anti-pattern')})",
                    "rejected_id": rf.get("id"),
                    "rejected_text": rf.get("text"),
                    "reason": rf.get("reason"),
                })
    except Exception as e:
        logger.debug(f"Guardrail check error: {e}")

    # 2. Extract facts according to structure mode
    extracted = extract(text, is_process=is_process, structure_mode=structure_mode)
    n = 0
    rejected_n = 0
    new_vector_items: list[tuple[int, str]] = []

    # 3. Mode-specific ingestion
    if structure_mode == "denylist":
        for f in extracted:
            combined_tags = sorted(set(f["tags"]) | set(extra_tags))
            reason = f.get("outcome") or f.get("reason") or "Prohibited approach / anti-pattern"
            repo.put_rejected_fact(f["text"], reason, combined_tags, source_id)
            rejected_n += 1
            # Also register in facts table for complete indexing if applicable
            fid = put_fact(
                f["text"],
                combined_tags,
                source_id,
                structures,
                f["rels"],
                action="rejected",
                outcome=reason,
                defer_vector=True,
            )
            if fid:
                n += 1
                new_vector_items.append((fid, f["text"]))
        if new_vector_items and "vector" in structures and "vector" in STORES:
            STORES["vector"].index_batch(new_vector_items)
        return StructureResult(n, warnings=warnings, rejected=rejected_n)

    for f in extracted:
        combined_tags = sorted(set(f["tags"]) | set(extra_tags))
        key = f.get("key")
        fid = put_fact(
            f["text"],
            combined_tags,
            source_id,
            structures,
            f["rels"],
            action=f.get("action"),
            owner=f.get("owner"),
            depends_on=f.get("depends_on"),
            key=key,
            condition=f.get("condition"),
            outcome=f.get("outcome"),
            superseded_by=f.get("superseded_by"),
            defer_vector=True,
        )
        if fid:
            n += 1
            new_vector_items.append((fid, f["text"]))
            # In versioned mode: auto-link supersession if a prior fact with the same key exists
            if structure_mode == "versioned" and key:
                existing_facts = repo.get_all_facts_with_sources(project_id=project_id)
                for ef in existing_facts:
                    if ef["id"] != fid and ef.get("key") == key and ef.get("superseded_by") is None:
                        repo.supersede_fact(ef["id"], fid)

    if new_vector_items and "vector" in structures and "vector" in STORES:
        STORES["vector"].index_batch(new_vector_items)

    return StructureResult(n, warnings=warnings, rejected=rejected_n)


def make_source_display(
    source_id: str,
    title: str | None,
    uri: str | None,
    kind: str | None,
    mode: str | None,
    created: float | None,
    project_id: str | None,
    project_name: str | None,
    fact_text: str = "",
    fact_tags: list[str] | None = None,
    allowed: list[str] | None = None,
) -> dict[str, Any]:
    # RBAC check: if viewer is not allowed to see the source/fact tags, redact details
    if allowed is not None and not is_visible(fact_tags, allowed):
        return {
            "id": source_id,
            "is_restricted": True,
            "title": "Restricted source",
            "uri": None,
            "kind": "restricted",
            "mode": "static",
            "created": None,
            "project_id": project_id,
            "project_name": project_name or "Restricted project",
            "source_label": "a restricted source",
            "source_kind_label": "a restricted source",
            "source_domain": None,
            "recorded_at": None,
        }

    k = (kind or "text").lower().strip()
    kind_map = {
        "text": "a pasted note",
        "url": "a web page",
        "screenshot": "a screenshot (OCR)",
        "file": "a file",
        "directory": "a file",
        "page": "a page captured with the browser extension",
        "extension": "a page captured with the browser extension",
        "session": "a live session",
        "live": "a live session",
    }
    source_kind_label = kind_map.get(k, f"a {k}")

    source_domain = None
    if uri and (uri.startswith("http://") or uri.startswith("https://")):
        try:
            from urllib.parse import urlparse
            netloc = urlparse(uri).netloc
            source_domain = netloc.removeprefix("www.") if netloc else None
        except Exception:
            pass

    t_clean = (title or "").strip()
    generic_titles = {"", "pasted note", "untitled", "untitled source", "text", "none", "null", "doc", "snippet"}
    is_generic = t_clean.lower() in generic_titles or t_clean.startswith("http://") or t_clean.startswith("https://")

    if not is_generic and t_clean:
        source_label = f'"{t_clean}"'
    else:
        words = (fact_text or t_clean).strip().split()
        if words:
            snippet = " ".join(words[:6])
            if len(words) > 6:
                snippet += "..."
            source_label = f'starting "{snippet}"'
        else:
            source_label = ""

    from datetime import datetime, timezone
    recorded_at = None
    if created:
        try:
            recorded_at = datetime.fromtimestamp(float(created), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    return {
        "id": source_id,
        "is_restricted": False,
        "title": title or "Untitled",
        "uri": uri,
        "kind": kind or "text",
        "mode": mode or "static",
        "created": float(created) if created else None,
        "project_id": project_id,
        "project_name": project_name or "Default Workspace",
        "source_label": source_label,
        "source_kind_label": source_kind_label,
        "source_domain": source_domain,
        "recorded_at": recorded_at,
    }


def search_facts(
    query: str,
    allowed: list[str],
    want: list[str] | None = None,
    boost: tuple[str, ...] = (),
    project_id: str | None = None,
    structure_mode: str | None = None,
    include_history: bool = False,
):
    repo = get_fact_repository()
    if not structure_mode and project_id:
        p = repo.get_project(project_id)
        if p:
            structure_mode = p.get("structure_mode", "rag")
    if not structure_mode:
        structure_mode = "rag"

    # In versioned mode: check if query asks for history/past versions
    q_lower = query.lower().strip()
    if structure_mode == "versioned" and any(k in q_lower for k in ["history", "past", "prior", "previous", "changelog", "v1", "v2"]):
        include_history = True

    live = bool(query.strip())
    # RBAC Pre-filter: get set of fact IDs strictly accessible to the caller via single is_visible() function
    all_raw_facts = repo.get_all_facts_with_sources(project_id=project_id)
    allowed_fact_ids = {
        r["id"] for r in all_raw_facts
        if is_visible(r.get("tags"), allowed)
    }

    ctx = {n: (s.prepare(query, allowed_fact_ids) if live else None) for n, s in STORES.items()}
    out = []

    strategy = get_strategy(structure_mode)

    for r in all_raw_facts:
        t = set(json.loads(r["tags"]))

        # Versioned mode: filter out superseded facts unless include_history is requested
        if structure_mode == "versioned" and not include_history and r.get("superseded_by") is not None:
            continue

        # SINGLE GLOBAL RBAC VISIBILITY CHECK
        if not is_visible(t, allowed):
            continue

        if want and not (t.issubset(set(want)) or (t & set(want))):
            continue

        via = [s for s in json.loads(r["structure"]) if s in STORES]

        source_dict = make_source_display(
            source_id=r["source_id"],
            title=r.get("title"),
            uri=r.get("uri"),
            kind=r.get("source_kind") or r.get("kind"),
            mode=r.get("source_mode") or r.get("mode"),
            created=r.get("source_created") or r.get("created"),
            project_id=r.get("project_id"),
            project_name=r.get("project_name"),
            fact_text=r.get("text", ""),
            fact_tags=t,
            allowed=allowed,
        )

        f = {
            "id": r["id"],
            "text": r["text"],
            "tags": sorted(t),
            "via": via,
            "source": source_dict,
            "action": r.get("action"),
            "owner": r.get("owner"),
            "depends_on": r.get("depends_on"),
            "key": r.get("key"),
            "condition": r.get("condition"),
            "outcome": r.get("outcome"),
            "superseded_by": r.get("superseded_by"),
            "valid_from": r.get("valid_from"),
            "valid_to": r.get("valid_to"),
            "priority": r.get("priority", 0),
        }

        # MODE STRATEGY SCORING
        score = strategy.score_fact(query, f, ctx, live)
        if score is None:
            continue
        f["score"] = score

        out.append(f)

    return out


def infer_tags(query: str) -> dict[str, str]:
    """Dynamic retrieval: what does this question need, even if it did not say so?"""
    llm_prov = get_llm_provider()
    if llm_prov.enabled():
        try:
            need = llm_prov.infer_needs(query)
            if need:
                return need
        except Exception as e:
            logger.debug(f"LLM inference failed, using rules: {e}")
    need = {}
    for t in tag(query):
        if t != "general":
            need.setdefault(t, "mentioned in your question")
            for i in IMPLIES.get(t, []):
                need.setdefault(i, f"'{t}' questions usually need '{i}' context")
    return need


def retrieve(
    query: str,
    allowed: list[str],
    mode: str = "explicit",
    scope: list[str] = (),
    limit: int = 15,
    project_id: str | None = None,
    include_history: bool = False,
):
    repo = get_fact_repository()
    structure_mode = "rag"
    if project_id:
        p = repo.get_project(project_id)
        if p:
            structure_mode = p.get("structure_mode", "rag")

    want = list(scope) or None
    inferred = {}
    if mode == "dynamic" and query.strip():
        inferred = {t: w for t, w in infer_tags(query).items() if is_visible([t], allowed)}

    res = search_facts(
        query,
        allowed,
        want,
        tuple(inferred.keys()),
        project_id=project_id,
        structure_mode=structure_mode,
        include_history=include_history,
    )

    # Denylist mode: check for any rejected patterns triggered by the query (enforce RBAC on alerts)
    warnings = []
    if structure_mode == "denylist" and query.strip():
        try:
            rej = repo.get_rejected_facts()
            q_toks = set(tok(query))
            for rf in rej:
                if not is_visible(rf.get("tags"), allowed):
                    continue
                rf_toks = set(tok(rf.get("text", "")))
                if rf_toks and (rf_toks & q_toks):
                    warnings.append({
                        "warning": f"⚠️ Query approaches rejected pattern: '{rf['text']}' (Reason: {rf.get('reason', 'Forbidden')})",
                        "rejected_id": rf.get("id"),
                        "rejected_text": rf.get("text"),
                        "reason": rf.get("reason"),
                    })
        except Exception as e:
            logger.debug(f"Denylist query warning error: {e}")

    # Vector Space Guard: Check for model/dimension mismatches in project vectors
    if project_id and hasattr(repo, "get_project_vectors_metadata"):
        try:
            emb_prov = get_embedding_provider()
            v_meta = repo.get_project_vectors_metadata(project_id)
            for vm in v_meta:
                if vm["model_name"] != emb_prov.model_name or int(vm["dim"]) != int(emb_prov.dimension):
                    warnings.append({
                        "warning": f"Project was embedded with {vm['model_name']} ({vm['dim']}d); re-embed to use {emb_prov.model_name} ({emb_prov.dimension}d). Use POST /api/projects/{project_id}/reembed to upgrade.",
                        "mismatch": True,
                        "stored_model": vm["model_name"],
                        "stored_dim": vm["dim"],
                        "current_model": emb_prov.model_name,
                        "current_dim": emb_prov.dimension,
                    })
        except Exception as e:
            logger.debug(f"Vector metadata check error: {e}")


    if res and not want and query.strip() and structure_mode not in ("allowlist", "keyvalue"):
        top = max(f["score"] for f in res)
        if top > 0:
            res = [f for f in res if f["score"] >= 0.6 * top or (inferred and is_visible(f["tags"], inferred))]
        else:
            res = []

    res.sort(key=lambda f: -f["score"])
    return {
        "facts": res[:limit],
        "inferred": inferred,
        "warnings": warnings,
        "structure_mode": structure_mode,
    }


def export_md(result: dict, role: str, mode: str, query: str) -> str:
    lines = [
        "# Context Pack",
        f"_view: {role} | mode: {mode}" + (f" | query: {query}" if query else "") + "_",
        "",
        "Treat the facts below as authoritative project context. [n] refers to the sources list.",
        "",
    ]
    srcs, meta, by = {}, {}, {}
    for f in result.get("facts", []):
        n = srcs.setdefault(f["source"]["id"], len(srcs) + 1)
        meta[f["source"]["id"]] = f["source"]
        by.setdefault(f["tags"][0], []).append(f"- {f['text']} [{n}]")
    for t, items in sorted(by.items()):
        lines += [f"## {t}", *items, ""]
    lines.append("## Sources & Provenance")
    for sid, n in srcs.items():
        m = meta[sid]
        if m.get("is_restricted"):
            lines.append(f"{n}. From a restricted source.")
        else:
            kind_lbl = m.get("source_kind_label", "a source")
            lbl = m.get("source_label", "")
            domain = m.get("source_domain")
            p_name = m.get("project_name", "")
            rec = m.get("recorded_at", "")

            desc = kind_lbl
            if domain:
                desc += f" on [{domain}]({m.get('uri', '')})"
            if lbl:
                desc += f" {lbl}"
            parts = [f"From {desc}"]
            if p_name:
                parts.append(f"in {p_name}")
            if rec:
                parts.append(rec)
            lines.append(f"{n}. {', '.join(parts)}.")
    return "\n".join(lines)

