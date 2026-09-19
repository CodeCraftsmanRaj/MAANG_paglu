"""Storage + retrieval. Any structure inherits mandatory provenance and access control from Store."""
import itertools, json, re, time
from abc import ABC, abstractmethod

from .db import rows, run

TAXONOMY = {
    "backend": ["server", "backend", "service", "worker", "queue", "fastapi", "django", "flask", "node", "cache"],
    "frontend": ["frontend", "react", "vue", "css", "component", "ui", "browser", "vite"],
    "database": ["postgres", "postgresql", "mysql", "sql", "redis", "mongodb", "schema", "migration", "database", "db"],
    "deploy": ["deploy", "deployment", "docker", "kubernetes", "ci", "cd", "aws", "terraform", "nginx", "pipeline", "staging", "production"],
    "api": ["api", "endpoint", "rest", "graphql", "route", "http", "auth", "jwt", "oauth", "webhook"],
    "process": ["workflow", "review", "sprint", "policy", "onboarding", "meeting", "standup", "release", "owner"],
}
# Retrieval-time inference: a question about X usually also needs Y.
IMPLIES = {"deploy": ["database", "backend"], "api": ["backend", "database"], "backend": ["database"],
           "frontend": ["api"], "database": ["backend"]}
VOCAB = {w for ws in TAXONOMY.values() for w in ws}


def tok(s): return re.findall(r"[a-z0-9]+", s.lower())
def tag(text): return [t for t, k in TAXONOMY.items() if set(tok(text)) & set(k)] or ["general"]
def ents(text): return sorted(set(tok(text)) & VOCAB)
def chunk(text): return [s.strip() for s in re.split(r"\n+|(?<=[.!?])\s+", text) if len(s.strip()) > 15]


class Store(ABC):
    name = ""

    def put(self, text, tags, source_id):
        # PROVENANCE LAYER: no valid source, no fact.
        if not source_id or not rows("SELECT 1 FROM sources WHERE id=?", (source_id,)):
            raise ValueError("every fact needs a valid source_id")
        fid = run("INSERT INTO facts(text,tags,source_id,structure,created) VALUES(?,?,?,?,?)",
                  (text, json.dumps(tags), source_id, self.name, time.time()))
        self.index(fid, text)
        return fid

    def search(self, query, allowed, want=None, boost=()):
        # ACCESS-CONTROL LAYER: filter by allowed tags before anything is ranked.
        ctx, out = self.prepare(query), []
        for r in rows("SELECT f.id,f.text,f.tags,f.source_id,s.title,s.uri FROM facts f "
                      "JOIN sources s ON s.id=f.source_id WHERE f.structure=?", (self.name,)):
            t = set(json.loads(r["tags"]))
            if "*" not in allowed and not t & set(allowed):
                continue
            if want and not t & set(want):
                continue
            f = {"id": r["id"], "text": r["text"], "tags": sorted(t),
                 "source": {"id": r["source_id"], "title": r["title"], "uri": r["uri"]}}
            f["score"] = self.score(query, f, ctx) + (0.75 if t & set(boost) else 0)
            out.append(f)
        return out

    def index(self, fid, text): pass
    def prepare(self, query): return None

    @abstractmethod
    def score(self, query, fact, ctx): ...


class FlatStore(Store):
    name = "flat"
    def score(self, query, fact, ctx): return len(set(tok(query)) & set(tok(fact["text"])))


class GraphStore(Store):
    """Entities that co-occur in a fact are linked; a query also matches one hop away."""
    name = "graph"

    def index(self, fid, text):
        for a, b in itertools.combinations(ents(text), 2):
            run("INSERT INTO edges VALUES(?,?,?)", (fid, a, b))

    def prepare(self, query):
        qe = set(ents(query))
        near = set()
        if qe:
            ph = ",".join("?" * len(qe))
            for e in rows(f"SELECT a,b FROM edges WHERE a IN ({ph}) OR b IN ({ph})", (*qe, *qe)):
                near |= {e["a"], e["b"]}
        return qe, near - qe

    def score(self, query, fact, ctx):
        qe, near = ctx
        e = set(ents(fact["text"]))
        return len(set(tok(query)) & set(tok(fact["text"]))) + len(e & qe) + 0.4 * len(e & near)


STORES = {s.name: s() for s in (FlatStore, GraphStore)}


def structure_doc(text, source_id, structure, extra_tags=()):
    n = 0
    for f in chunk(text):
        STORES[structure].put(f, sorted(set(tag(f)) | set(extra_tags)), source_id)
        n += 1
    return n


def retrieve(query, allowed, mode="explicit", scope=(), limit=15):
    want, inferred = list(scope) or None, {}
    if mode == "dynamic":
        for t in tag(query):
            if t == "general":
                continue
            inferred.setdefault(t, "mentioned in your question")
            for imp in IMPLIES.get(t, []):
                inferred.setdefault(imp, f"'{t}' questions usually need '{imp}' context")
        inferred = {t: why for t, why in inferred.items() if "*" in allowed or t in allowed}
    res = [f for s in STORES.values() for f in s.search(query, allowed, want, set(inferred))]
    if not want and tok(query):
        res = [f for f in res if f["score"] > 0]
    res.sort(key=lambda f: -f["score"])
    return {"facts": res[:limit], "inferred": inferred}


def export_md(result, role, mode, query):
    head = f"_role: {role} | mode: {mode}" + (f" | query: {query}" if query else "") + "_"
    lines = ["# Context Pack", head, "",
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
