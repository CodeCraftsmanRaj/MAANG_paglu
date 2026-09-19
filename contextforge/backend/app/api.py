import hashlib, json, os, time, uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import llm
from .auth import current, login, register, require_admin
from .db import rows, run
from .ingestion import INGESTORS, normalize, watch
from .structuring import STORES, TAXONOMY, export_md, retrieve, structure_doc

app = FastAPI(title="ContextForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ALL = list(STORES)
_seen: dict = {}


class AuthIn(BaseModel):
    username: str
    password: str

class IngestIn(BaseModel):
    kind: str = "text"
    text: str | None = None
    url: str | None = None
    title: str | None = None
    structures: list[str] = ALL
    tags: list[str] = []

class SessionIn(BaseModel):
    title: str = "Live session"

class ChunkIn(BaseModel):
    text: str
    tags: list[str] = []

class ShotIn(BaseModel):
    image: str

class PageIn(BaseModel):
    url: str
    title: str = ""
    text: str

class RoleIn(BaseModel):
    tags: list[str]

class UserRoleIn(BaseModel):
    role: str

class QueryIn(BaseModel):
    query: str = ""
    mode: str = "explicit"
    scope: list[str] = []


def new_source(kind, title, uri, mode):
    sid = uuid.uuid4().hex[:8]
    run("INSERT INTO sources VALUES(?,?,?,?,?,?)", (sid, kind, title, uri, mode, time.time()))
    return sid


def source_for_uri(kind, title, uri, mode="live"):
    r = rows("SELECT id FROM sources WHERE uri=?", (uri,))
    return r[0]["id"] if r else new_source(kind, title, uri, mode)


def fresh(key, text):
    h = hashlib.md5(text.encode()).hexdigest()
    if _seen.get(key) == h:
        return False
    _seen[key] = h
    return True


def live(sid):
    if not rows("SELECT 1 FROM sources WHERE id=? AND mode='live'", (sid,)):
        raise HTTPException(404, "Session not found")


@app.on_event("startup")
def _startup():
    d = os.getenv("WATCH_DIR")
    if d and os.path.isdir(d):
        watch(d, lambda name, path, text: structure_doc(text, source_for_uri("file", name, path, "static"), ALL))
        print("Watching folder:", d)


# ----- auth -----
@app.post("/api/auth/register")
def reg(b: AuthIn): return register(b.username.strip(), b.password)

@app.post("/api/auth/login")
def signin(b: AuthIn): return login(b.username.strip(), b.password)

@app.get("/api/me")
def me(c=Depends(current)): return {"user": c["user"], "role": c["role"], "view": c["view"], "llm": llm.enabled()}

@app.get("/api/roles")
def roles(c=Depends(current)):
    return [{"name": r["name"], "tags": json.loads(r["tags"])} for r in rows("SELECT * FROM roles ORDER BY name")]

@app.put("/api/roles/{name}")
def put_role(name: str, b: RoleIn, c=Depends(require_admin)):
    if name == "admin":
        raise HTTPException(400, "The admin role cannot be changed")
    run("INSERT OR REPLACE INTO roles VALUES(?,?)", (name, json.dumps(b.tags)))
    return {"ok": True}

@app.get("/api/users")
def users(c=Depends(require_admin)): return rows("SELECT username, role FROM users ORDER BY username")

@app.put("/api/users/{name}/role")
def set_user_role(name: str, b: UserRoleIn, c=Depends(require_admin)):
    if name == c["user"]:
        raise HTTPException(400, "You cannot change your own role")
    if not rows("SELECT 1 FROM roles WHERE name=?", (b.role,)):
        raise HTTPException(404, "Unknown role")
    run("UPDATE users SET role=? WHERE username=?", (b.role, name))
    return {"ok": True}

@app.get("/api/tags")
def tags(c=Depends(current)): return [*TAXONOMY, "general"]


# ----- ingestion (manual + automatic) -----
@app.post("/api/ingest")
def ingest(b: IngestIn, c=Depends(require_admin)):
    if b.kind not in INGESTORS or any(s not in STORES for s in b.structures):
        raise HTTPException(400, f"kind must be one of {list(INGESTORS)}; structures one of {ALL}")
    try:
        doc = normalize(b.kind, b.model_dump())
    except Exception as e:
        raise HTTPException(422, f"Could not read that source: {e}")
    title = b.title or doc["title"]
    sid = source_for_uri(b.kind, title, doc["uri"], "static") if doc["uri"] else new_source(b.kind, title, None, "static")
    return {"source_id": sid, "facts": structure_doc(doc["text"], sid, b.structures, b.tags)}

@app.post("/api/sessions")
def new_session(b: SessionIn, c=Depends(require_admin)): return {"source_id": new_source("session", b.title, None, "live")}

@app.post("/api/sessions/{sid}/chunk")
def chunk_in(sid: str, b: ChunkIn, c=Depends(require_admin)):
    live(sid)
    return {"facts": structure_doc(b.text, sid, ALL, b.tags)}

@app.post("/api/sessions/{sid}/screen")
def screen_in(sid: str, b: ShotIn, c=Depends(require_admin)):
    live(sid)
    if not llm.enabled():
        raise HTTPException(400, "Screen reading needs GROQ_API_KEY in backend/.env")
    try:
        text = llm.ocr(b.image)
    except Exception as e:
        raise HTTPException(502, f"Vision model failed: {e}")
    if len(text.strip()) < 25 or not fresh(sid, text):
        return {"facts": 0, "skipped": True}
    return {"facts": structure_doc(text, sid, ALL)}

@app.post("/api/capture/page")  # used by the browser extension (ChatGPT, Claude, Gemini, GitHub, ...)
def capture_page(b: PageIn, c=Depends(require_admin)):
    if not fresh(b.url, b.text):
        return {"facts": 0, "skipped": True}
    return {"facts": structure_doc(b.text[:30000], source_for_uri("page", b.title or b.url, b.url), ALL)}


# ----- retrieval -----
@app.post("/api/retrieve")
def do_retrieve(b: QueryIn, c=Depends(current)): return retrieve(b.query, c["allowed"], b.mode, b.scope)

@app.post("/api/export")
def do_export(b: QueryIn, c=Depends(current)):
    res = retrieve(b.query, c["allowed"], b.mode, b.scope, limit=300)
    return {"markdown": export_md(res, c["view"], b.mode, b.query), "count": len(res["facts"])}

@app.post("/api/ask")
def ask(b: QueryIn, c=Depends(current)):
    if not llm.enabled():
        raise HTTPException(400, "Ask needs GROQ_API_KEY in backend/.env")
    res = retrieve(b.query, c["allowed"], "dynamic", b.scope, 12)
    if not res["facts"]:
        return {"answer": "Nothing visible to this role covers that yet.", **res}
    ctx = "\n".join(f"[{i + 1}] {f['text']} (source: {f['source']['title']})" for i, f in enumerate(res["facts"]))
    ans = llm.chat([{"role": "system", "content": "Answer using ONLY the numbered context and cite like [1]. If it is missing, say so."},
                    {"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {b.query}"}])
    return {"answer": ans, **res}
