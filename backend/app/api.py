import hashlib
import json
import os
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")


from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import can_access_project, current, is_visible, login, register, require_admin
from .db import rows, run
from .factory import get_fact_repository, get_ingestor, get_llm_provider
from .ingestion import INGESTORS, normalize, watch
from .strategies import get_strategy
from .structuring import (
    STORES,
    TAXONOMY,
    check_embedding_dimension_consistency,
    export_md,
    retrieve,
    structure_doc,
)

app = FastAPI(title="ContextForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ALL = list(STORES)
_seen: dict = {}


class AuthIn(BaseModel):
    username: str
    password: str


class ProjectIn(BaseModel):
    name: str
    project_type: str = "general"
    structure_mode: str | None = None
    sample_text: str | None = None


class ProjectModeUpdateIn(BaseModel):
    structure_mode: str
    classification_reason: str | None = "Manual override by user"


class IngestIn(BaseModel):
    kind: str = "text"
    text: str | None = None
    url: str | None = None
    title: str | None = None
    html: str | None = None
    structures: list[str] = ALL
    tags: list[str] = []
    project_id: str = "proj_default"


class SessionIn(BaseModel):
    title: str = "Live session"
    project_id: str = "proj_default"


class ChunkIn(BaseModel):
    text: str
    tags: list[str] = []


class ShotIn(BaseModel):
    image: str


class PageIn(BaseModel):
    url: str
    title: str = ""
    text: str
    project_id: str = "proj_default"


class CreateRoleIn(BaseModel):
    name: str
    tags: list[str] = []
    allow_new: bool = False
    create_new_tag: bool = False


class RoleIn(BaseModel):
    tags: list[str]
    allow_new: bool = False
    create_new_tag: bool = False


class UserRoleIn(BaseModel):
    role: str


class QueryIn(BaseModel):
    query: str = ""
    mode: str = "explicit"
    scope: list[str] = []
    project_id: str | None = None
    is_process: bool = False
    include_history: bool = False


def new_source(kind: str, title: str, uri: str | None, mode: str, project_id: str = "proj_default") -> str:
    repo = get_fact_repository()
    return repo.put_source(kind, title, uri, mode, project_id=project_id)


def source_for_uri(kind: str, title: str, uri: str, mode: str = "live", project_id: str = "proj_default") -> str:
    repo = get_fact_repository()
    existing = repo.get_source_by_uri(uri, project_id=project_id)
    return existing["id"] if existing else new_source(kind, title, uri, mode, project_id=project_id)


def fresh(key: str, text: str) -> bool:
    h = hashlib.md5(text.encode()).hexdigest()
    if _seen.get(key) == h:
        return False
    _seen[key] = h
    return True


def live(sid: str):
    repo = get_fact_repository()
    if not repo.source_exists(sid, mode="live"):
        raise HTTPException(404, "Session not found")


@app.on_event("startup")
def _startup():
    check_embedding_dimension_consistency()
    d = os.getenv("WATCH_DIR")
    if d and os.path.isdir(d):
        watch(d, lambda name, path, text: structure_doc(text, source_for_uri("file", name, path, "static", "proj_default"), ALL))
        print("Watching folder:", d)


@app.get("/api/status")
def status():
    return {
        "llm": os.getenv("LLM_PROVIDER", "groq").lower(),
        "embedding": os.getenv("EMBEDDING_PROVIDER", "fastembed").lower(),
        "db": os.getenv("DB_PROVIDER", "sqlite").lower(),
    }


# ----- projects -----
@app.get("/api/projects")
def get_projects(c=Depends(current)):
    repo = get_fact_repository()
    all_projs = repo.get_projects(username=c["user"])
    return [p for p in all_projs if can_access_project(c["user"], c["role"], p)]


@app.post("/api/projects")
def create_project(b: ProjectIn, c=Depends(current)):
    name = b.name.strip()
    if not name:
        raise HTTPException(422, "Project name cannot be empty")
    ptype = b.project_type.strip().lower()
    if ptype not in ("general", "process"):
        raise HTTPException(422, "project_type must be 'general' or 'process'")

    repo = get_fact_repository()
    llm_prov = get_llm_provider()

    structure_mode = (b.structure_mode or "").strip().lower()
    reason = "User specified structure mode"

    if structure_mode:
        if structure_mode not in ("graph", "allowlist", "denylist", "keyword", "keyvalue", "ruleset", "versioned", "rag"):
            raise HTTPException(422, f"Invalid structure_mode '{structure_mode}'.")
    else:
        # Auto-classify structure mode via LLM provider (or heuristic fallback)
        classification = llm_prov.classify_structure_mode(name, b.sample_text or "")
        structure_mode = classification.get("mode", "rag")
        reason = classification.get("reason", "Auto-classified via LLM analysis")

    return repo.create_project(
        name=name,
        created_by=c["user"],
        project_type=ptype,
        structure_mode=structure_mode,
        classification_reason=reason,
        members=[c["user"], "admin"],
    )


@app.put("/api/projects/{project_id}/mode")
def update_project_mode(project_id: str, b: ProjectModeUpdateIn, c=Depends(current)):
    mode = b.structure_mode.strip().lower()
    if mode not in ("graph", "allowlist", "denylist", "keyword", "keyvalue", "ruleset", "versioned", "rag"):
        raise HTTPException(422, f"Invalid structure_mode '{mode}'")
    repo = get_fact_repository()
    proj = repo.get_project(project_id)
    if not proj or not can_access_project(c["user"], c["role"], proj):
        raise HTTPException(404, "Project not found")
    res = repo.update_project_mode(project_id, mode, b.classification_reason or "Manual override by user")
    return res


@app.post("/api/projects/{project_id}/reembed")
def reembed_project(project_id: str, c=Depends(current)):
    repo = get_fact_repository()
    proj = repo.get_project(project_id)
    if not proj or not can_access_project(c["user"], c["role"], proj):
        raise HTTPException(404, "Project not found")

    from .factory import get_embedding_provider
    emb_prov = get_embedding_provider()
    facts = repo.get_all_facts_with_sources(project_id=project_id)
    if not facts:
        return {
            "ok": True,
            "project_id": project_id,
            "reembedded_facts": 0,
            "model": emb_prov.model_name,
            "dim": emb_prov.dimension,
        }

    texts = [f["text"] for f in facts]
    vectors = emb_prov.embed_documents(texts)
    for f, v in zip(facts, vectors):
        repo.put_vector(f["id"], v.tobytes(), model_name=emb_prov.model_name, dim=emb_prov.dimension)

    return {
        "ok": True,
        "project_id": project_id,
        "reembedded_facts": len(facts),
        "model": emb_prov.model_name,
        "dim": emb_prov.dimension,
    }



@app.get("/api/rejected_facts")
def get_rejected_facts(c=Depends(current)):
    repo = get_fact_repository()
    return repo.get_rejected_facts()


@app.get("/api/sources/{source_id}")
def get_source_detail(source_id: str, c=Depends(current)):
    repo = get_fact_repository()
    r = rows("SELECT s.*, p.name as project_name FROM sources s LEFT JOIN projects p ON p.id=s.project_id WHERE s.id=?", (source_id,))
    if not r:
        raise HTTPException(404, "Source not found")
    src = dict(r[0])

    pid = src.get("project_id", "proj_default")
    proj = repo.get_project(pid)
    if proj and not can_access_project(c["user"], c["role"], proj):
        raise HTTPException(404, "Source not found")

    from .structuring import make_source_display
    return make_source_display(
        source_id=src["id"],
        title=src.get("title"),
        uri=src.get("uri"),
        kind=src.get("kind"),
        mode=src.get("mode"),
        created=src.get("created"),
        project_id=pid,
        project_name=src.get("project_name") or (proj.get("name") if proj else "Default Workspace"),
        allowed=c["allowed"],
    )


# ----- auth -----
@app.post("/api/auth/register")
def reg(b: AuthIn):
    return register(b.username.strip(), b.password)


@app.post("/api/auth/login")
def signin(b: AuthIn):
    return login(b.username.strip(), b.password)


@app.get("/api/me")
def me(c=Depends(current)):
    return {
        "user": c["user"],
        "role": c["role"],
        "view": c["view"],
        "llm": get_llm_provider().enabled(),
        "allowed": c["allowed"],
        "can_modify_own_role": False,
    }


@app.get("/api/roles")
def roles(c=Depends(current)):
    return [{"name": r["name"], "tags": json.loads(r["tags"])} for r in rows("SELECT * FROM roles ORDER BY name")]


@app.post("/api/roles")
def create_role(b: CreateRoleIn, c=Depends(require_admin)):
    name = b.name.strip().lower()
    if not name:
        raise HTTPException(422, "Role name is required")
    if name == "admin":
        raise HTTPException(400, "The admin role is reserved and cannot be created")
    if rows("SELECT 1 FROM roles WHERE name=?", (name,)):
        raise HTTPException(409, f"Role '{name}' already exists")

    known_tags = set(TAXONOMY.keys()) | {"general"}
    for r in rows("SELECT tags FROM roles"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    known_tags.add(t)
        except Exception:
            pass
    for r in rows("SELECT tags FROM facts"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    known_tags.add(t)
        except Exception:
            pass

    unknown = [t for t in b.tags if t != "*" and t not in known_tags and t.split("/", 1)[0] not in known_tags]
    if unknown and not (b.allow_new or b.create_new_tag):
        raise HTTPException(
            422,
            f"Unknown tags: {unknown}. Set allow_new=True (or create_new_tag=True) to register new tags intentionally.",
        )

    run("INSERT INTO roles VALUES(?,?)", (name, json.dumps(b.tags)))
    return {"ok": True, "name": name, "tags": b.tags}


@app.put("/api/roles/{name}")
def put_role(name: str, b: RoleIn, c=Depends(require_admin)):
    if name == "admin":
        raise HTTPException(400, "The admin role cannot be changed")

    # Validate tags against known taxonomy unless explicitly allowed
    known_tags = set(TAXONOMY.keys()) | {"general"}
    for r in rows("SELECT tags FROM roles"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    known_tags.add(t)
        except Exception:
            pass
    for r in rows("SELECT tags FROM facts"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    known_tags.add(t)
        except Exception:
            pass

    unknown = [t for t in b.tags if t != "*" and t not in known_tags and t.split("/", 1)[0] not in known_tags]
    if unknown and not (b.allow_new or b.create_new_tag):
        raise HTTPException(
            422,
            f"Unknown tags: {unknown}. Set allow_new=True (or create_new_tag=True) to register new tags intentionally.",
        )

    run("INSERT OR REPLACE INTO roles VALUES(?,?)", (name, json.dumps(b.tags)))
    return {"ok": True}


@app.get("/api/users")
def users(c=Depends(require_admin)):
    return rows("SELECT username, role FROM users ORDER BY username")


@app.put("/api/users/{name}/role")
def set_user_role(name: str, b: UserRoleIn, c=Depends(require_admin)):
    if name == c["user"]:
        raise HTTPException(400, "You cannot change your own role")
    if not rows("SELECT 1 FROM roles WHERE name=?", (b.role,)):
        raise HTTPException(404, "Unknown role")
    run("UPDATE users SET role=? WHERE username=?", (b.role, name))
    return {"ok": True}


@app.get("/api/tags")
def tags(c=Depends(current)):
    all_tags = set(TAXONOMY.keys()) | {"general"}
    for r in rows("SELECT tags FROM roles"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    all_tags.add(t)
        except Exception:
            pass

    for r in rows("SELECT tags FROM facts"):
        try:
            for t in json.loads(r["tags"]):
                if t and t != "*":
                    all_tags.add(t)
        except Exception:
            pass

    tree: dict[str, list[str]] = {}
    for t in sorted(all_tags):
        if "/" in t:
            p = t.split("/", 1)[0]
            if p not in tree:
                tree[p] = []
            if t not in tree[p]:
                tree[p].append(t)
        else:
            if t not in tree:
                tree[t] = []

    for k in tree:
        tree[k].sort()

    all_sorted = sorted(set(tree.keys()) | set(t for children in tree.values() for t in children))
    return {
        "tree": tree,
        "tags": all_sorted,
        **tree,
    }


# ----- sources -----
@app.get("/api/sources/{sid}")
def get_source(sid: str, c=Depends(current)):
    r = rows("SELECT id, kind, title, uri, mode, created, project_id FROM sources WHERE id=?", (sid,))
    if not r:
        raise HTTPException(404, "Source not found")
    return r[0]


# ----- ingestion (manual + automatic) -----
@app.post("/api/ingest")
def ingest(b: IngestIn, c=Depends(require_admin)):
    if b.kind not in INGESTORS or any(s not in STORES for s in b.structures):
        raise HTTPException(400, f"kind must be one of {list(INGESTORS)}; structures one of {ALL}")

    repo = get_fact_repository()
    project_id = b.project_id or "proj_default"
    proj = repo.get_project(project_id)
    is_process = bool(proj and proj.get("project_type") == "process")
    structure_mode = proj.get("structure_mode", "rag") if proj else "rag"

    if b.kind in ("text", "url"):
        # Unified modular path: Ingestor -> NormalizedDocument -> FactRepository + Extraction/Embedding
        try:
            ingestor = get_ingestor(b.kind)
            doc = ingestor.normalize(b.model_dump())
        except Exception as e:
            raise HTTPException(422, f"Could not read that source: {e}")

        title = b.title or doc.title
        sid = (
            source_for_uri(doc.source_kind, title, doc.source_uri, "static", project_id=project_id)
            if doc.source_uri
            else repo.put_source(doc.source_kind, title, None, "static", project_id=project_id)
        )
        count = structure_doc(doc.text, sid, b.structures, b.tags, is_process=is_process, project_id=project_id, structure_mode=structure_mode)
        warnings = getattr(count, "warnings", [])
        return {"source_id": sid, "facts": int(count), "warnings": warnings, "project_id": project_id, "structure_mode": structure_mode}

    # Other sources stay on their current code path
    try:
        doc = normalize(b.kind, b.model_dump())
    except Exception as e:
        raise HTTPException(422, f"Could not read that source: {e}")
    title = b.title or doc["title"]
    sid = (
        source_for_uri(b.kind, title, doc["uri"], "static", project_id=project_id)
        if doc["uri"]
        else new_source(b.kind, title, None, "static", project_id=project_id)
    )
    count = structure_doc(doc["text"], sid, b.structures, b.tags, is_process=is_process, project_id=project_id, structure_mode=structure_mode)
    warnings = getattr(count, "warnings", [])
    return {"source_id": sid, "facts": int(count), "warnings": warnings, "project_id": project_id, "structure_mode": structure_mode}


@app.post("/api/sessions")
def new_session(b: SessionIn, c=Depends(require_admin)):
    pid = b.project_id or "proj_default"
    return {"source_id": new_source("session", b.title, None, "live", project_id=pid)}


@app.post("/api/sessions/{sid}/chunk")
def chunk_in(sid: str, b: ChunkIn, c=Depends(require_admin)):
    live(sid)
    repo = get_fact_repository()
    # Check project type and mode from source
    r = rows("SELECT project_id FROM sources WHERE id=?", (sid,))
    pid = r[0]["project_id"] if r else "proj_default"
    proj = repo.get_project(pid)
    is_process = bool(proj and proj.get("project_type") == "process")
    structure_mode = proj.get("structure_mode", "rag") if proj else "rag"
    count = structure_doc(b.text, sid, ALL, b.tags, is_process=is_process, project_id=pid, structure_mode=structure_mode)
    return {"facts": int(count), "warnings": getattr(count, "warnings", [])}


@app.post("/api/sessions/{sid}/screen")
def screen_in(sid: str, b: ShotIn, c=Depends(require_admin)):
    live(sid)
    llm_prov = get_llm_provider()
    if not llm_prov.enabled():
        raise HTTPException(400, "Screen reading needs GROQ_API_KEY in backend/.env")
    try:
        text = llm_prov.ocr(b.image)
    except Exception as e:
        raise HTTPException(502, f"Vision model failed: {e}")
    if len(text.strip()) < 25 or not fresh(sid, text):
        return {"facts": 0, "skipped": True}
    repo = get_fact_repository()
    r = rows("SELECT project_id FROM sources WHERE id=?", (sid,))
    pid = r[0]["project_id"] if r else "proj_default"
    proj = repo.get_project(pid)
    is_process = bool(proj and proj.get("project_type") == "process")
    structure_mode = proj.get("structure_mode", "rag") if proj else "rag"
    count = structure_doc(text, sid, ALL, is_process=is_process, project_id=pid, structure_mode=structure_mode)
    return {"facts": int(count), "warnings": getattr(count, "warnings", [])}


@app.post("/api/capture/page")  # used by the browser extension (ChatGPT, Claude, Gemini, GitHub, ...)
def capture_page(b: PageIn, c=Depends(require_admin)):
    if not fresh(b.url, b.text):
        return {"facts": 0, "skipped": True}
    pid = b.project_id or "proj_default"
    repo = get_fact_repository()
    proj = repo.get_project(pid)
    is_process = bool(proj and proj.get("project_type") == "process")
    structure_mode = proj.get("structure_mode", "rag") if proj else "rag"
    count = structure_doc(
        b.text[:30000],
        source_for_uri("page", b.title or b.url, b.url, project_id=pid),
        ALL,
        is_process=is_process,
        project_id=pid,
        structure_mode=structure_mode,
    )
    return {
        "facts": int(count),
        "warnings": getattr(count, "warnings", []),
    }


# ----- retrieval -----
@app.post("/api/retrieve")
def do_retrieve(b: QueryIn, c=Depends(current)):
    if b.project_id:
        repo = get_fact_repository()
        proj = repo.get_project(b.project_id)
        if not proj or not can_access_project(c["user"], c["role"], proj):
            raise HTTPException(404, "Project not found")
    return retrieve(
        b.query,
        c["allowed"],
        b.mode,
        b.scope,
        project_id=b.project_id,
        include_history=b.include_history,
    )


@app.post("/api/export")
def do_export(b: QueryIn, c=Depends(current)):
    if b.project_id:
        repo = get_fact_repository()
        proj = repo.get_project(b.project_id)
        if not proj or not can_access_project(c["user"], c["role"], proj):
            raise HTTPException(404, "Project not found")
    res = retrieve(
        b.query,
        c["allowed"],
        b.mode,
        b.scope,
        limit=300,
        project_id=b.project_id,
        include_history=b.include_history,
    )
    return {"markdown": export_md(res, c["view"], b.mode, b.query), "count": len(res.get("facts", []))}


@app.post("/api/ask")
def ask(b: QueryIn, c=Depends(current)):
    repo = get_fact_repository()
    proj = None
    if b.project_id:
        proj = repo.get_project(b.project_id)
        if not proj or not can_access_project(c["user"], c["role"], proj):
            raise HTTPException(404, "Project not found")
    llm_prov = get_llm_provider()
    res = retrieve(
        b.query,
        c["allowed"],
        "dynamic",
        b.scope,
        12,
        project_id=b.project_id,
        include_history=b.include_history,
    )
    is_process = b.is_process or bool(proj and proj.get("project_type") == "process")
    structure_mode = proj.get("structure_mode", "rag") if proj else "rag"

    if not res.get("facts") and structure_mode not in ("allowlist", "keyvalue", "denylist"):
        return {"answer": "Nothing visible to this role covers that yet.", **res}

    try:
        ans = llm_prov.answer(b.query, res.get("facts", []), is_process=is_process, structure_mode=structure_mode)
    except Exception as e:
        strat = get_strategy(structure_mode)
        ans = strat.format_answer(b.query, res.get("facts", []), llm_provider=None)
    return {"answer": ans, **res}

