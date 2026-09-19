import json, os, sqlite3, threading, time, uuid

_lock = threading.Lock()
_c = sqlite3.connect(os.environ.get("CF_DB", "contextforge2.db"), check_same_thread=False)
_c.row_factory = sqlite3.Row
_c.executescript("""
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at REAL NOT NULL,
  project_type TEXT NOT NULL,
  structure_mode TEXT NOT NULL DEFAULT 'rag',
  classification_reason TEXT,
  members TEXT NOT NULL DEFAULT '["*"]'
);
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY,
  kind TEXT,
  title TEXT,
  uri TEXT,
  mode TEXT,
  created REAL,
  project_id TEXT
);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  tags TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id),
  structure TEXT NOT NULL,
  created REAL,
  action TEXT,
  owner TEXT,
  depends_on TEXT,
  key TEXT,
  condition TEXT,
  outcome TEXT,
  superseded_by INTEGER REFERENCES facts(id),
  valid_from REAL,
  valid_to REAL,
  priority INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rejected_facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  reason TEXT NOT NULL,
  tags TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id),
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS edges(fact_id INTEGER, a TEXT, rel TEXT, b TEXT);
CREATE TABLE IF NOT EXISTS vecs(fact_id INTEGER PRIMARY KEY, v BLOB);
CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, tags TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pw TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, username TEXT NOT NULL);
""")

# Migrate existing schema if columns were missing
with _lock:
    proj_cols = [r["name"] for r in _c.execute("PRAGMA table_info(projects)").fetchall()]
    if "structure_mode" not in proj_cols:
        _c.execute("ALTER TABLE projects ADD COLUMN structure_mode TEXT NOT NULL DEFAULT 'rag'")
    if "classification_reason" not in proj_cols:
        _c.execute("ALTER TABLE projects ADD COLUMN classification_reason TEXT")
    if "members" not in proj_cols:
        _c.execute("ALTER TABLE projects ADD COLUMN members TEXT NOT NULL DEFAULT '[\"*\"]'")

    source_cols = [r["name"] for r in _c.execute("PRAGMA table_info(sources)").fetchall()]
    if "project_id" not in source_cols:
        _c.execute("ALTER TABLE sources ADD COLUMN project_id TEXT REFERENCES projects(id)")

    fact_cols = [r["name"] for r in _c.execute("PRAGMA table_info(facts)").fetchall()]
    if "action" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN action TEXT")
    if "owner" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN owner TEXT")
    if "depends_on" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN depends_on TEXT")
    if "key" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN key TEXT")
    if "condition" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN condition TEXT")
    if "outcome" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN outcome TEXT")
    if "superseded_by" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN superseded_by INTEGER REFERENCES facts(id)")
    if "valid_from" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN valid_from REAL")
    if "valid_to" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN valid_to REAL")
    if "priority" not in fact_cols:
        _c.execute("ALTER TABLE facts ADD COLUMN priority INTEGER DEFAULT 0")

    # Ensure default "Default Workspace" exists
    _c.execute(
        "INSERT OR IGNORE INTO projects (id, name, created_by, created_at, project_type, structure_mode, classification_reason, members) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("proj_default", "Default Workspace", "system", time.time(), "general", "rag", "Default general project with hybrid RAG retrieval", '["*"]'),
    )
    _c.execute("UPDATE projects SET name = 'Default Workspace' WHERE id = 'proj_default' AND (name = 'Untitled project' OR name = 'Untitled')")

    vec_cols = [r["name"] for r in _c.execute("PRAGMA table_info(vecs)").fetchall()]
    if "model_name" not in vec_cols:
        _c.execute("ALTER TABLE vecs ADD COLUMN model_name TEXT DEFAULT 'BAAI/bge-small-en-v1.5'")
    if "dim" not in vec_cols:
        _c.execute("ALTER TABLE vecs ADD COLUMN dim INTEGER DEFAULT 384")

    # Migrate any orphan sources without project_id
    _c.execute("UPDATE sources SET project_id = 'proj_default' WHERE project_id IS NULL OR project_id = ''")
    _c.commit()


for n, t in [("admin", ["*"]), ("backend", ["backend", "database", "deploy", "api"]),
             ("frontend", ["frontend", "api", "design"]), ("member", [])]:
    _c.execute("INSERT OR IGNORE INTO roles VALUES(?,?)", (n, json.dumps(t)))

# Ensure default admin account exists if no users are registered
import hashlib, secrets
if not _c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
    salt = secrets.token_bytes(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", "admin123".encode(), salt, 120_000).hex()
    _c.execute("INSERT INTO users VALUES (?, ?, ?)", ("admin", salt.hex() + "$" + pw_hash, "admin"))

_c.commit()


def run(sql, args=()):
    with _lock:
        cur = _c.execute(sql, args)
        _c.commit()
        return cur.lastrowid


def rows(sql, args=()):
    with _lock:
        return [dict(r) for r in _c.execute(sql, args).fetchall()]


