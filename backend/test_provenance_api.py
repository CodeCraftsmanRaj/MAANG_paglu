"""Test provenance fields returned by /api/retrieve and /api/sources endpoints."""
import json
import sqlite3
import time
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000/api"

def make_req(path, data=None, token=None, method=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def get_or_create_admin_token():
    conn = sqlite3.connect("contextforge2.db")
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE role='admin' LIMIT 1")
    row = c.fetchone()
    if row:
        admin_user = row[0]
    else:
        import hashlib
        pw_hash = hashlib.sha256("password123".encode()).hexdigest()
        c.execute("INSERT OR REPLACE INTO users (username, pw, role) VALUES ('admin', ?, 'admin')", (pw_hash,))
        admin_user = 'admin'
    
    c.execute("UPDATE projects SET name='Default Workspace' WHERE id='proj_default'")
    token = "test_admin_token_" + admin_user

    c.execute("INSERT OR REPLACE INTO tokens (token, username) VALUES (?, ?)", (token, admin_user))
    conn.commit()
    conn.close()
    return token

def seed_url_fact_directly():
    conn = sqlite3.connect("contextforge2.db")
    c = conn.cursor()
    sid = "src_notion_test_123"
    now = time.time()
    c.execute(
        "INSERT OR REPLACE INTO sources (id, kind, title, uri, mode, created, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, "url", "Engineering Runbook", "https://notion.so/engineering/runbook", "static", now, "proj_default"),
    )
    c.execute(
        "INSERT INTO facts (text, tags, source_id, structure, created) VALUES (?, ?, ?, ?, ?)",
        (
            "Incident runbook: in case of high redis latency, flush stale cache keys and rotate connection pool.",
            json.dumps(["database", "backend"]),
            sid,
            json.dumps(["flat", "vector"]),
            now,
        ),
    )
    conn.commit()
    conn.close()

def main():
    print("--- 1. Authenticate as Admin ---")
    token = get_or_create_admin_token()
    print(f"Token created for admin: {token[:15]}...")

    print("\n--- 2. Ingest Sample Note with Generic Title ---")
    status, ingest_res = make_req("/ingest", {
        "kind": "text",
        "text": "Deploy checklist for database cluster: execute schema migrations before promoting replica nodes.",
        "title": "Pasted note",
        "project_id": "proj_default",
    }, token=token)
    print(f"Ingest Status: {status} | Facts added: {ingest_res.get('facts')}")
    assert status == 200, f"Ingest failed: {ingest_res}"

    print("\n--- 3. Seed URL Source Directly into DB ---")
    seed_url_fact_directly()
    print("Seeded URL fact with domain notion.so.")

    print("\n--- 4. Retrieve Facts and Verify Display-Ready Source Fields ---")
    status, retrieve_res = make_req("/retrieve", {
        "query": "",
        "project_id": "proj_default",
    }, token=token)
    assert status == 200, f"Retrieve failed: {retrieve_res}"
    facts = retrieve_res.get("facts", [])
    print(f"Retrieved {len(facts)} facts.")
    assert len(facts) > 0, "Expected facts in retrieve response"
    
    found_generic_note = False
    found_url_source = False

    for idx, f in enumerate(facts):
        src = f["source"]
        print(f"\nFact [{idx + 1}]: {f['text']}")
        print(f"  source_label:      {src.get('source_label')}")
        print(f"  source_kind_label: {src.get('source_kind_label')}")
        print(f"  source_domain:     {src.get('source_domain')}")
        print(f"  project_name:      {src.get('project_name')}")
        print(f"  recorded_at:       {src.get('recorded_at')}")
        print(f"  is_restricted:     {src.get('is_restricted')}")
        assert "source_label" in src
        assert "source_kind_label" in src
        assert "project_name" in src
        assert "recorded_at" in src

        if src.get("source_domain") == "notion.so":
            found_url_source = True
            assert src.get("source_kind_label") == "a web page"
            assert src.get("source_label") == '"Engineering Runbook"'

        if src.get("source_kind_label") == "a pasted note" and "Deploy checklist" in src.get("source_label", ""):
            found_generic_note = True

    assert found_generic_note, "Expected to find generic pasted note with snippet"
    assert found_url_source, "Expected to find URL source with domain notion.so"

    print("\n--- 5. Verify GET /api/sources/{source_id} Detail Endpoint ---")
    first_src_id = facts[0]["source"]["id"]
    status, src_detail = make_req(f"/sources/{first_src_id}", token=token)
    print(f"Source Detail for {first_src_id} (Status {status}):")
    print(json.dumps(src_detail, indent=2))
    assert status == 200, f"Failed to get source detail: {src_detail}"
    assert src_detail["source_kind_label"] in ["a pasted note", "a web page", "a file", "a live session", "a screenshot (OCR)"]
    assert src_detail["project_name"] == "Default Workspace"

    print("\nALL API PROVENANCE VERIFICATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
