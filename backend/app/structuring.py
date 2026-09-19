"""Storage + retrieval. Three pluggable indexes (keyword, vector, graph) behind one interface.
put_fact() enforces provenance and search_facts() enforces access control for EVERY index."""
import itertools
import json
import logging
import re
from abc import ABC, abstractmethod

import networkx as nx

from .factory import get_embedding_provider, get_fact_repository, get_llm_provider

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
def extract(text: str, is_process: bool = False) -> list[dict]:
    llm_prov = get_llm_provider()
    if llm_prov.enabled():
        try:
            facts = llm_prov.extract_facts(text, is_process=is_process)
            if facts:
                return [
                    {
                        "text": f.text,
                        "tags": f.tags or tag(f.text),
                        "rels": f.rels,
                        "action": f.action,
                        "owner": f.owner,
                        "depends_on": f.depends_on,
                    }
                    for f in facts
                ]
        except Exception as e:
            print("LLM extraction failed, using heuristics:", e)
    return [
        {
            "text": f,
            "tags": tag(f),
            "rels": [[a, "related_to", b] for a, b in itertools.combinations(ents(f), 2)],
            "action": None,
            "owner": None,
            "depends_on": None,
        }
        for f in chunk(text)
    ]


# ---------- indexes ----------
class Store(ABC):
    name = ""

    def index(self, fid: int, text: str, rels: list[list[str]]):
        pass

    def prepare(self, query: str):
        return None

    @abstractmethod
    def score(self, query: str, fact: dict, ctx: any) -> float:
        ...


class FlatStore(Store):
    name = "flat"

    def score(self, query: str, fact: dict, ctx: any) -> float:
        return float(len(set(tok(query)) & set(tok(fact["text"]))))


class VectorStore(Store):
    name = "vector"

    def index(self, fid: int, text: str, rels: list[list[str]]):
        repo = get_fact_repository()
        emb_prov = get_embedding_provider()
        v = emb_prov.embed([text])[0]
        repo.put_vector(fid, v.tobytes())

    def prepare(self, query: str):
        emb_prov = get_embedding_provider()
        repo = get_fact_repository()
        q_vec = emb_prov.embed([query])[0]
        all_vecs = repo.get_all_vectors()
        return q_vec, all_vecs

    def score(self, query: str, fact: dict, ctx: any) -> float:
        if ctx is None or fact["id"] not in ctx[1]:
            return 0.0
        doc_vec = ctx[1][fact["id"]]
        if len(ctx[0]) != len(doc_vec):
            return 0.0  # Safe guard against mismatched dimensions
        return float(ctx[0] @ doc_vec)


class GraphStore(Store):
    """Facts contribute (subject, relation, object) edges; a query walks up to 2 hops from entities it mentions."""
    name = "graph"

    def index(self, fid: int, text: str, rels: list[list[str]]):
        repo = get_fact_repository()
        repo.put_edges(fid, rels)

    def prepare(self, query: str):
        repo = get_fact_repository()
        E = repo.get_all_edges()
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


def put_fact(
    text: str,
    tags: list[str],
    source_id: str,
    structures: list[str],
    rels: list[list[str]] = (),
    action: str | None = None,
    owner: str | None = None,
    depends_on: str | None = None,
):
    repo = get_fact_repository()
    # PROVENANCE: no valid source, no fact. Same text is never stored twice (keeps live capture clean).
    if not repo.source_exists(source_id):
        raise ValueError("every fact needs a valid source_id")
    if repo.fact_exists_by_text(text):
        return None

    fid = repo.put_fact(text, tags, source_id, structures, rels, action=action, owner=owner, depends_on=depends_on)
    if fid is not None:
        for s in structures:
            if s in STORES:
                STORES[s].index(fid, text, rels)
    return fid


def structure_doc(text: str, source_id: str, structures: list[str], extra_tags: list[str] = (), is_process: bool = False):
    n = 0
    for f in extract(text, is_process=is_process):
        combined_tags = sorted(set(f["tags"]) | set(extra_tags))
        if put_fact(
            f["text"],
            combined_tags,
            source_id,
            structures,
            f["rels"],
            action=f.get("action"),
            owner=f.get("owner"),
            depends_on=f.get("depends_on"),
        ):
            n += 1
    return n


def search_facts(query: str, allowed: list[str], want: list[str] | None = None, boost: tuple[str, ...] = (), project_id: str | None = None):
    repo = get_fact_repository()
    live = bool(query.strip())
    ctx = {n: (s.prepare(query) if live else None) for n, s in STORES.items()}
    out = []
    for r in repo.get_all_facts_with_sources(project_id=project_id):
        t = set(json.loads(r["tags"]))
        # ACCESS CONTROL: invisible facts never reach ranking, whatever index they live in.
        if "*" not in allowed and not t & set(allowed):
            continue
        if want and not t & set(want):
            continue
        via = [s for s in json.loads(r["structure"]) if s in STORES]
        f = {
            "id": r["id"],
            "text": r["text"],
            "tags": sorted(t),
            "via": via,
            "source": {"id": r["source_id"], "title": r["title"], "uri": r["uri"], "project_id": r.get("project_id")},
            "action": r.get("action"),
            "owner": r.get("owner"),
            "depends_on": r.get("depends_on"),
        }
        f["score"] = round(
            sum(WEIGHT[s] * STORES[s].score(query, f, ctx[s]) for s in via) + (0.4 if t & set(boost) else 0),
            3,
        )
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
            print("LLM inference failed, using rules:", e)
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
):
    want = list(scope) or None
    inferred = {}
    if mode == "dynamic" and query.strip():
        inferred = {t: w for t, w in infer_tags(query).items() if "*" in allowed or t in allowed}
    res = search_facts(query, allowed, want, tuple(inferred.keys()), project_id=project_id)
    if res and not want and query.strip():
        top = max(f["score"] for f in res)
        res = [f for f in res if f["score"] >= 0.6 * top or set(f["tags"]) & set(inferred)]
    res.sort(key=lambda f: -f["score"])
    return {"facts": res[:limit], "inferred": inferred}


def export_md(result: dict, role: str, mode: str, query: str) -> str:
    lines = [
        "# Context Pack",
        f"_view: {role} | mode: {mode}" + (f" | query: {query}" if query else "") + "_",
        "",
        "Treat the facts below as authoritative project context. [n] refers to the sources list.",
        "",
    ]
    srcs, meta, by = {}, {}, {}
    for f in result["facts"]:
        n = srcs.setdefault(f["source"]["id"], len(srcs) + 1)
        meta[f["source"]["id"]] = f["source"]
        by.setdefault(f["tags"][0], []).append(f"- {f['text']} [{n}]")
    for t, items in sorted(by.items()):
        lines += [f"## {t}", *items, ""]
    lines.append("## Sources")
    for sid, n in srcs.items():
        m = meta[sid]
        lines.append(f"{n}. {m['title']}" + (f" ({m['uri']})" if m["uri"] else ""))
    return "\n".join(lines)

