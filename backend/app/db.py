import json, os, sqlite3, threading, time, uuid

_lock = threading.Lock()
_c = sqlite3.connect(os.environ.get("CF_DB", "contextforge2.db"), check_same_thread=False)
_c.row_factory = sqlite3.Row
_c.executescript("""
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL, project_type TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, kind TEXT, title TEXT, uri TEXT, mode TEXT, created REAL, project_id TEXT);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, tags TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id), structure TEXT NOT NULL, created REAL,
  action TEXT, owner TEXT, depends_on TEXT);
CREATE TABLE IF NOT EXISTS edges(fact_id INTEGER, a TEXT, rel TEXT, b TEXT);
CREATE TABLE IF NOT EXISTS vecs(fact_id INTEGER PRIMARY KEY, v BLOB);
CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, tags TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pw TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, username TEXT NOT NULL);
""")

# Migrate existing schema if columns were missing
with _lock:
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

    # Ensure default "Untitled project" exists
    _c.execute(
        "INSERT OR IGNORE INTO projects (id, name, created_by, created_at, project_type) VALUES (?, ?, ?, ?, ?)",
        ("proj_default", "Untitled project", "system", time.time(), "general"),
    )
    # Migrate any orphan sources without project_id
    _c.execute("UPDATE sources SET project_id = 'proj_default' WHERE project_id IS NULL OR project_id = ''")
    _c.commit()

for n, t in [("admin", ["*"]), ("backend", ["backend", "database", "deploy", "api"]),
             ("frontend", ["frontend", "api", "design"]), ("member", [])]:
    _c.execute("INSERT OR IGNORE INTO roles VALUES(?,?)", (n, json.dumps(t)))
_c.commit()


def run(sql, args=()):
    with _lock:
        cur = _c.execute(sql, args)
        _c.commit()
        return cur.lastrowid


def rows(sql, args=()):
    with _lock:
        return [dict(r) for r in _c.execute(sql, args).fetchall()]

