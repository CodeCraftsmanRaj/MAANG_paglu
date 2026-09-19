import hashlib
import json
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import current, login, register, require_admin
from .db import rows, run
from .factory import get_fact_repository, get_ingestor, get_llm_provider
from .ingestion import INGESTORS, normalize, watch
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
    return repo.get_projects(username=c["user"])


@app.post("/api/projects")
def create_project(b: ProjectIn, c=Depends(current)):
    name = b.name.strip()
    if not name:
        raise HTTPException(422, "Project name cannot be empty")
    ptype = b.project_type.strip().lower()
    if ptype not in ("general", "process"):
        raise HTTPException(422, "project_type must be 'general' or 'process'")
    repo = get_fact_repository()
    return repo.create_project(name=name, created_by=c["user"], project_type=ptype)


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
        count = structure_doc(doc.text, sid, b.structures, b.tags, is_process=is_process)
        return {"source_id": sid, "facts": count, "project_id": project_id}

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
    return {"source_id": sid, "facts": structure_doc(doc["text"], sid, b.structures, b.tags, is_process=is_process), "project_id": project_id}


@app.post("/api/sessions")
def new_session(b: SessionIn, c=Depends(require_admin)):
    pid = b.project_id or "proj_default"
    return {"source_id": new_source("session", b.title, None, "live", project_id=pid)}


@app.post("/api/sessions/{sid}/chunk")
def chunk_in(sid: str, b: ChunkIn, c=Depends(require_admin)):
    live(sid)
    repo = get_fact_repository()
    src = repo.get_all_facts_with_sources()
    # Check project type from source
    r = rows("SELECT project_id FROM sources WHERE id=?", (sid,))
    pid = r[0]["project_id"] if r else "proj_default"
    proj = repo.get_project(pid)
    is_process = bool(proj and proj.get("project_type") == "process")
    return {"facts": structure_doc(b.text, sid, ALL, b.tags, is_process=is_process)}


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
    return {"facts": structure_doc(text, sid, ALL, is_process=is_process)}


@app.post("/api/capture/page")  # used by the browser extension (ChatGPT, Claude, Gemini, GitHub, ...)
def capture_page(b: PageIn, c=Depends(require_admin)):
    if not fresh(b.url, b.text):
        return {"facts": 0, "skipped": True}
    pid = b.project_id or "proj_default"
    repo = get_fact_repository()
    proj = repo.get_project(pid)
    is_process = bool(proj and proj.get("project_type") == "process")
    return {
        "facts": structure_doc(
            b.text[:30000],
            source_for_uri("page", b.title or b.url, b.url, project_id=pid),
            ALL,
            is_process=is_process,
        )
    }


# ----- retrieval -----
@app.post("/api/retrieve")
def do_retrieve(b: QueryIn, c=Depends(current)):
    return retrieve(b.query, c["allowed"], b.mode, b.scope, project_id=b.project_id)


@app.post("/api/export")
def do_export(b: QueryIn, c=Depends(current)):
    res = retrieve(b.query, c["allowed"], b.mode, b.scope, limit=300, project_id=b.project_id)
    return {"markdown": export_md(res, c["view"], b.mode, b.query), "count": len(res["facts"])}


@app.post("/api/ask")
def ask(b: QueryIn, c=Depends(current)):
    llm_prov = get_llm_provider()
    if not llm_prov.enabled():
        raise HTTPException(400, "Ask needs GROQ_API_KEY or AWS Bedrock in backend/.env")
    res = retrieve(b.query, c["allowed"], "dynamic", b.scope, 12, project_id=b.project_id)
    if not res["facts"]:
        return {"answer": "Nothing visible to this role covers that yet.", **res}
    repo = get_fact_repository()
    proj = repo.get_project(b.project_id) if b.project_id else None
    is_process = b.is_process or bool(proj and proj.get("project_type") == "process")
    ans = llm_prov.answer(b.query, res["facts"], is_process=is_process)
    return {"answer": ans, **res}

