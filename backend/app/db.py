import json, os, sqlite3, threading

_lock = threading.Lock()
_c = sqlite3.connect(os.environ.get("CF_DB", "contextforge.db"), check_same_thread=False)
_c.row_factory = sqlite3.Row
_c.executescript("""
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, kind TEXT, title TEXT, uri TEXT, mode TEXT, created REAL);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, tags TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id), structure TEXT NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS edges(fact_id INTEGER, a TEXT, b TEXT);
CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, tags TEXT NOT NULL);
""")
for n, t in [("admin", ["*"]), ("backend", ["backend", "database", "deploy", "api"]), ("frontend", ["frontend", "api"])]:
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
