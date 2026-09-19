"""Storage + retrieval. Three pluggable indexes (keyword, vector, graph) behind one interface.
put_fact() enforces provenance and search_facts() enforces access control for EVERY index."""
import itertools, json, re, time, zlib
from abc import ABC, abstractmethod

import networkx as nx
import numpy as np

from . import llm
from .db import rows, run

TAXONOMY = {
    "backend": ["server", "backend", "service", "worker", "queue", "fastapi", "django", "flask", "node", "cache"],
    "frontend": ["frontend", "react", "vue", "css", "component", "ui", "browser", "vite"],
    "database": ["postgres", "postgresql", "mysql", "sql", "redis", "mongodb", "schema", "migration", "database", "db"],
    "deploy": ["deploy", "deployment", "docker", "kubernetes", "ci", "cd", "aws", "terraform", "nginx", "pipeline", "staging", "production"],
    "api": ["api", "endpoint", "rest", "graphql", "route", "http", "auth", "jwt", "oauth", "webhook"],
    "process": ["workflow", "review", "sprint", "policy", "onboarding", "meeting", "standup", "release", "owner"],
}
IMPLIES = {"deploy": ["database", "backend"], "api": ["backend", "database"], "backend": ["database"],
           "frontend": ["api"], "database": ["backend"]}
VOCAB = {w for ws in TAXONOMY.values() for w in ws}


def tok(s): return re.findall(r"[a-z0-9]+", s.lower())
def tag(text): return [t for t, k in TAXONOMY.items() if set(tok(text)) & set(k)] or ["general"]
def ents(text): return sorted(set(tok(text)) & VOCAB)
def chunk(text): return [s.strip() for s in re.split(r"\n+|(?<=[.!?])\s+", text) if len(s.strip()) > 15]


# ---------- extraction: Groq LLM, with a heuristic fallback ----------
EXTRACT = ("Extract atomic, self-contained facts a new teammate or an AI coding assistant would need from the text. "
           'Return JSON {"facts":[{"text":str,"tags":[str],"rels":[[subject,relation,object]]}]}. '
           f"Tags come from: {', '.join(TAXONOMY)}, general. Entities in rels are short lowercase names. Max 25 facts.")


def extract(text):
    if llm.enabled():
        try:
            out = []
            for i in range(0, min(len(text), 24000), 6000):
                for f in llm.jchat(EXTRACT, text[i:i + 6000])["facts"]:
                    tags = [t for t in f.get("tags", []) if t in TAXONOMY or t == "general"]
                    rels = [[str(x).lower() for x in r] for r in f.get("rels", []) if isinstance(r, list) and len(r) == 3]
                    out.append({"text": str(f["text"]), "tags": tags or tag(f["text"]), "rels": rels})
            if out:
                return out
        except Exception as e:
            print("LLM extraction failed, using heuristics:", e)
    return [{"text": f, "tags": tag(f), "rels": [[a, "related_to", b] for a, b in itertools.combinations(ents(f), 2)]}
            for f in chunk(text)]


# ---------- embeddings: local fastembed, hashed fallback ----------
_model = None


def _hash_vec(t):
    v = np.zeros(384, np.float32)
    for w in tok(t):
        v[zlib.crc32(w.encode()) % 384] += 1
    return v


def embed(texts):
    global _model
    if _model is None:
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding("BAAI/bge-small-en-v1.5")
        except Exception as e:
            print("fastembed unavailable, using hashed vectors:", e)
            _model = False
    vs = [np.asarray(v, np.float32) for v in _model.embed(texts)] if _model else [_hash_vec(t) for t in texts]
    return [v / (np.linalg.norm(v) + 1e-9) for v in vs]


# ---------- indexes ----------
class Store(ABC):
    name = ""
    def index(self, fid, text, rels): pass
    def prepare(self, query): return None
    @abstractmethod
    def score(self, query, fact, ctx): ...


class FlatStore(Store):
    name = "flat"
    def score(self, query, fact, ctx): return len(set(tok(query)) & set(tok(fact["text"])))


class VectorStore(Store):
    name = "vector"

    def index(self, fid, text, rels):
        run("INSERT OR REPLACE INTO vecs VALUES(?,?)", (fid, embed([text])[0].tobytes()))

    def prepare(self, query):
        return embed([query])[0], {r["fact_id"]: np.frombuffer(r["v"], np.float32) for r in rows("SELECT fact_id, v FROM vecs")}

    def score(self, query, fact, ctx):
        if ctx is None or fact["id"] not in ctx[1]:
            return 0.0
        return float(ctx[0] @ ctx[1][fact["id"]])


class GraphStore(Store):
    """Facts contribute (subject, relation, object) edges; a query walks up to 2 hops from entities it mentions."""
    name = "graph"

    def index(self, fid, text, rels):
        for a, r, b in rels:
            run("INSERT INTO edges VALUES(?,?,?,?)", (fid, a, r, b))

    def prepare(self, query):
        E = rows("SELECT fact_id, a, b FROM edges")
        if not E:
            return None
        G, by = nx.Graph(), {}
        for e in E:
            G.add_edge(e["a"], e["b"])
            by.setdefault(e["fact_id"], set()).update((e["a"], e["b"]))
        q = query.lower()
        seeds = [n for n in G if len(n) > 2 and n in q]
        return by, (nx.multi_source_dijkstra_path_length(G, seeds, cutoff=2) if seeds else {})

    def score(self, query, fact, ctx):
        if not ctx:
            return 0.0
        by, dist = ctx
        return max((1 / (1 + dist[n]) for n in by.get(fact["id"], ()) if n in dist), default=0.0)


STORES = {s.name: s() for s in (FlatStore, VectorStore, GraphStore)}
WEIGHT = {"flat": 0.12, "vector": 1.0, "graph": 0.6}


def put_fact(text, tags, source_id, structures, rels=()):
    # PROVENANCE: no valid source, no fact. Same text is never stored twice (keeps live capture clean).
    if not rows("SELECT 1 FROM sources WHERE id=?", (source_id,)):
        raise ValueError("every fact needs a valid source_id")
    if rows("SELECT 1 FROM facts WHERE text=?", (text,)):
        return None
    fid = run("INSERT INTO facts(text,tags,source_id,structure,created) VALUES(?,?,?,?,?)",
              (text, json.dumps(tags), source_id, json.dumps(structures), time.time()))
    for s in structures:
        STORES[s].index(fid, text, rels)
    return fid


def structure_doc(text, source_id, structures, extra_tags=()):
    n = 0
    for f in extract(text):
        if put_fact(f["text"], sorted(set(f["tags"]) | set(extra_tags)), source_id, structures, f["rels"]):
            n += 1
    return n


def search_facts(query, allowed, want=None, boost=()):
    live = bool(query.strip())
    ctx = {n: (s.prepare(query) if live else None) for n, s in STORES.items()}
    out = []
    for r in rows("SELECT f.id,f.text,f.tags,f.structure,f.source_id,s.title,s.uri FROM facts f JOIN sources s ON s.id=f.source_id"):
        t = set(json.loads(r["tags"]))
        # ACCESS CONTROL: invisible facts never reach ranking, whatever index they live in.
        if "*" not in allowed and not t & set(allowed):
            continue
        if want and not t & set(want):
            continue
        via = [s for s in json.loads(r["structure"]) if s in STORES]
        f = {"id": r["id"], "text": r["text"], "tags": sorted(t), "via": via,
             "source": {"id": r["source_id"], "title": r["title"], "uri": r["uri"]}}
        f["score"] = round(sum(WEIGHT[s] * STORES[s].score(query, f, ctx[s]) for s in via) + (0.4 if t & set(boost) else 0), 3)
        out.append(f)
    return out


def infer_tags(query):
    """Dynamic retrieval: what does this question need, even if it did not say so?"""
    if llm.enabled():
        try:
            out = llm.jchat("A teammate asks a question. Return JSON {\"needs\":[{\"tag\":str,\"why\":str}]}: the context areas from "
                            + ", ".join(TAXONOMY) + " needed to answer well, including ones they did not mention "
                            "(a deploy question also needs database config). Max 5. Keep 'why' under 12 words.", query)
            need = {n["tag"]: n.get("why", "") for n in out["needs"] if n.get("tag") in TAXONOMY}
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


def retrieve(query, allowed, mode="explicit", scope=(), limit=15):
    want = list(scope) or None
    inferred = {}
    if mode == "dynamic" and query.strip():
        inferred = {t: w for t, w in infer_tags(query).items() if "*" in allowed or t in allowed}
    res = search_facts(query, allowed, want, set(inferred))
    if res and not want and query.strip():
        top = max(f["score"] for f in res)
        res = [f for f in res if f["score"] >= 0.6 * top or set(f["tags"]) & set(inferred)]
    res.sort(key=lambda f: -f["score"])
    return {"facts": res[:limit], "inferred": inferred}


def export_md(result, role, mode, query):
    lines = ["# Context Pack", f"_view: {role} | mode: {mode}" + (f" | query: {query}" if query else "") + "_", "",
             "Treat the facts below as authoritative project context. [n] refers to the sources list.", ""]
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
