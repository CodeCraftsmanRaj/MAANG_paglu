import json, time, uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .db import rows, run
from .ingestion import INGESTORS, normalize
from .structuring import STORES, TAXONOMY, export_md, retrieve, structure_doc

app = FastAPI(title="ContextForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class IngestIn(BaseModel):
    kind: str = "text"
    text: str | None = None
    url: str | None = None
    title: str | None = None
    structure: str = "flat"
    tags: list[str] = []


class SessionIn(BaseModel):
    title: str = "Live session"


class ChunkIn(BaseModel):
    text: str
    structure: str = "flat"
    tags: list[str] = []


class RoleIn(BaseModel):
    tags: list[str]


class QueryIn(BaseModel):
    query: str = ""
    mode: str = "explicit"
    scope: list[str] = []


def allowed_for(role):
    r = rows("SELECT tags FROM roles WHERE name=?", (role,))
    if not r:
        raise HTTPException(403, f"unknown role '{role}'")
    return json.loads(r[0]["tags"])


def admin(role):
    if "*" not in allowed_for(role):
        raise HTTPException(403, "admin role required")


def check_structure(s):
    if s not in STORES:
        raise HTTPException(400, f"structure must be one of {list(STORES)}")


@app.post("/api/ingest")
def ingest(b: IngestIn, x_role: str = Header("admin")):
    admin(x_role)
    check_structure(b.structure)
    if b.kind not in INGESTORS:
        raise HTTPException(400, f"kind must be one of {list(INGESTORS)}")
    try:
        doc = normalize(b.kind, b.model_dump())
    except Exception as e:
        raise HTTPException(422, f"could not ingest: {e}")
    sid = uuid.uuid4().hex[:8]
    run("INSERT INTO sources VALUES(?,?,?,?,?,?)", (sid, b.kind, b.title or doc["title"], doc["uri"], "static", time.time()))
    return {"source_id": sid, "facts": structure_doc(doc["text"], sid, b.structure, b.tags)}


@app.post("/api/sessions")
def new_session(b: SessionIn, x_role: str = Header("admin")):
    admin(x_role)
    sid = uuid.uuid4().hex[:8]
    run("INSERT INTO sources VALUES(?,?,?,?,?,?)", (sid, "session", b.title, None, "live", time.time()))
    return {"source_id": sid}


@app.post("/api/sessions/{sid}/chunk")
def session_chunk(sid: str, b: ChunkIn, x_role: str = Header("admin")):
    admin(x_role)
    check_structure(b.structure)
    if not rows("SELECT 1 FROM sources WHERE id=? AND mode='live'", (sid,)):
        raise HTTPException(404, "session not found")
    return {"facts": structure_doc(b.text, sid, b.structure, b.tags)}


@app.get("/api/roles")
def roles():
    return [{"name": r["name"], "tags": json.loads(r["tags"])} for r in rows("SELECT * FROM roles ORDER BY name")]


@app.put("/api/roles/{name}")
def put_role(name: str, b: RoleIn, x_role: str = Header("admin")):
    admin(x_role)
    if name == "admin":
        raise HTTPException(400, "the admin role cannot be changed")
    run("INSERT OR REPLACE INTO roles VALUES(?,?)", (name, json.dumps(b.tags)))
    return {"ok": True}


@app.get("/api/tags")
def tags():
    return [*TAXONOMY, "general"]


@app.post("/api/retrieve")
def do_retrieve(b: QueryIn, x_role: str = Header("admin")):
    return retrieve(b.query, allowed_for(x_role), b.mode, b.scope)


@app.post("/api/export")
def do_export(b: QueryIn, x_role: str = Header("admin")):
    res = retrieve(b.query, allowed_for(x_role), b.mode, b.scope, limit=300)
    return {"markdown": export_md(res, x_role, b.mode, b.query), "count": len(res["facts"])}
