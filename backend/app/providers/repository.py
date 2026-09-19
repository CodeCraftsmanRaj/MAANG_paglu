"""Fact Repository implementations: SQLite repository and AWS DynamoDB single-table repository."""
import base64
import hashlib
import json
import os
import time
import uuid
from typing import Any

import numpy as np

from ..db import rows, run
from ..interfaces import FactRepository


class SQLiteFactRepository(FactRepository):
    """SQLite-backed implementation for persistent projects, sources, facts, vecs, and edges."""

    def create_project(self, name: str, created_by: str, project_type: str = "general") -> dict[str, Any]:
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        now = time.time()
        run("INSERT INTO projects VALUES(?,?,?,?,?)", (pid, name, created_by, now, project_type))
        return {"id": pid, "name": name, "created_by": created_by, "created_at": now, "project_type": project_type}

    def get_projects(self, username: str | None = None) -> list[dict[str, Any]]:
        return rows("SELECT * FROM projects ORDER BY created_at ASC")

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        r = rows("SELECT * FROM projects WHERE id=?", (project_id,))
        return r[0] if r else None

    def put_source(self, kind: str, title: str, uri: str | None, mode: str, project_id: str = "proj_default") -> str:
        sid = uuid.uuid4().hex[:8]
        run("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (sid, kind, title, uri, mode, time.time(), project_id))
        return sid

    def get_source_by_uri(self, uri: str, project_id: str | None = None) -> dict[str, Any] | None:
        if project_id:
            r = rows("SELECT * FROM sources WHERE uri=? AND project_id=?", (uri, project_id))
        else:
            r = rows("SELECT * FROM sources WHERE uri=?", (uri,))
        return r[0] if r else None

    def source_exists(self, source_id: str, mode: str | None = None) -> bool:
        if mode:
            return bool(rows("SELECT 1 FROM sources WHERE id=? AND mode=?", (source_id, mode)))
        return bool(rows("SELECT 1 FROM sources WHERE id=?", (source_id,)))

    def fact_exists_by_text(self, text: str, source_id: str | None = None) -> bool:
        if source_id:
            return bool(rows("SELECT 1 FROM facts WHERE text=? AND source_id=?", (text, source_id)))
        return bool(rows("SELECT 1 FROM facts WHERE text=?", (text,)))

    def put_fact(
        self,
        text: str,
        tags: list[str],
        source_id: str,
        structures: list[str],
        rels: list[list[str]] = (),
        action: str | None = None,
        owner: str | None = None,
        depends_on: str | None = None,
    ) -> int | None:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every fact requires an existing source.")
        if self.fact_exists_by_text(text):
            return None

        fid = run(
            "INSERT INTO facts(text,tags,source_id,structure,created,action,owner,depends_on) VALUES(?,?,?,?,?,?,?,?)",
            (text, json.dumps(tags), source_id, json.dumps(structures), time.time(), action, owner, depends_on),
        )
        return fid

    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return rows(
                "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.action, f.owner, f.depends_on, "
                "s.title, s.uri, s.project_id "
                "FROM facts f JOIN sources s ON s.id=f.source_id WHERE s.project_id=?",
                (project_id,),
            )
        return rows(
            "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.action, f.owner, f.depends_on, "
            "s.title, s.uri, s.project_id "
            "FROM facts f JOIN sources s ON s.id=f.source_id"
        )

    def put_vector(self, fact_id: int, vector_bytes: bytes) -> None:
        run("INSERT OR REPLACE INTO vecs VALUES(?,?)", (fact_id, vector_bytes))

    def get_all_vectors(self) -> dict[int, np.ndarray]:
        res = rows("SELECT fact_id, v FROM vecs")
        return {r["fact_id"]: np.frombuffer(r["v"], dtype=np.float32) for r in res}

    def put_edges(self, fact_id: int, rels: list[list[str]]) -> None:
        for r in rels:
            if len(r) == 3:
                run("INSERT INTO edges VALUES(?,?,?,?)", (fact_id, r[0], r[1], r[2]))

    def get_all_edges(self) -> list[dict[str, Any]]:
        return rows("SELECT fact_id, a, b FROM edges")


class DynamoDBFactRepository(FactRepository):
    """AWS DynamoDB single-table implementation for persistent sources, facts, vecs, and relations.

    Table Key Design:
      - Project Item:    PK = "PROJECT#<id>", SK = "METADATA"
      - Source Metadata: PK = "SOURCE#<id>",  SK = "METADATA"
      - URI Lookup:      PK = "URI#<uri>",    SK = "METADATA"
      - Fact Item:       PK = "FACT#<id>",    SK = "METADATA"
      - Fact Text Hash:  PK = "HASH#<md5>",   SK = "FACT#<id>"
      - Vector / Edges:  Stored directly as binary/JSON attributes on Fact Item
    """

    def __init__(self, table_name: str | None = None, region_name: str | None = None):
        self.table_name = table_name or os.getenv("DYNAMODB_TABLE_NAME", "ContextForgeKnowledge")
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self._table = None

    def _get_table(self) -> Any:
        if self._table is None:
            import boto3
            dynamodb = boto3.resource("dynamodb", region_name=self.region_name)
            self._table = dynamodb.Table(self.table_name)
        return self._table

    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.strip().encode()).hexdigest()

    def create_project(self, name: str, created_by: str, project_type: str = "general") -> dict[str, Any]:
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        now = time.time()
        table = self._get_table()
        item = {
            "PK": f"PROJECT#{pid}",
            "SK": "METADATA",
            "id": pid,
            "name": name,
            "created_by": created_by,
            "created_at": str(now),
            "project_type": project_type,
        }
        table.put_item(Item=item)
        return {"id": pid, "name": name, "created_by": created_by, "created_at": now, "project_type": project_type}

    def get_projects(self, username: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
                         ExpressionAttributeValues={":sk": "METADATA", ":prefix": "PROJECT#"})
        projects = []
        for item in res.get("Items", []):
            projects.append({
                "id": item["id"],
                "name": item["name"],
                "created_by": item["created_by"],
                "created_at": float(item.get("created_at", 0)),
                "project_type": item.get("project_type", "general"),
            })
        if not projects:
            # Fallback default project
            projects = [{"id": "proj_default", "name": "Untitled project", "created_by": "system", "created_at": 0.0, "project_type": "general"}]
        projects.sort(key=lambda x: x["created_at"])
        return projects

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        table = self._get_table()
        res = table.get_item(Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"})
        item = res.get("Item")
        if not item:
            if project_id == "proj_default":
                return {"id": "proj_default", "name": "Untitled project", "created_by": "system", "created_at": 0.0, "project_type": "general"}
            return None
        return {
            "id": item["id"],
            "name": item["name"],
            "created_by": item["created_by"],
            "created_at": float(item.get("created_at", 0)),
            "project_type": item.get("project_type", "general"),
        }

    def put_source(self, kind: str, title: str, uri: str | None, mode: str, project_id: str = "proj_default") -> str:
        sid = uuid.uuid4().hex[:8]
        now = time.time()
        table = self._get_table()
        item = {
            "PK": f"SOURCE#{sid}",
            "SK": "METADATA",
            "id": sid,
            "kind": kind,
            "title": title,
            "uri": uri or "",
            "mode": mode,
            "created": str(now),
            "project_id": project_id,
        }
        table.put_item(Item=item)
        if uri:
            table.put_item(Item={"PK": f"URI#{uri}", "SK": "METADATA", "source_id": sid, "title": title, "kind": kind, "mode": mode, "project_id": project_id})
        return sid

    def get_source_by_uri(self, uri: str, project_id: str | None = None) -> dict[str, Any] | None:
        table = self._get_table()
        res = table.get_item(Key={"PK": f"URI#{uri}", "SK": "METADATA"})
        item = res.get("Item")
        if not item:
            return None
        if project_id and item.get("project_id") != project_id:
            return None
        sid = item["source_id"]
        src_res = table.get_item(Key={"PK": f"SOURCE#{sid}", "SK": "METADATA"})
        return src_res.get("Item")

    def source_exists(self, source_id: str, mode: str | None = None) -> bool:
        table = self._get_table()
        res = table.get_item(Key={"PK": f"SOURCE#{source_id}", "SK": "METADATA"})
        item = res.get("Item")
        if not item:
            return False
        if mode and item.get("mode") != mode:
            return False
        return True

    def fact_exists_by_text(self, text: str, source_id: str | None = None) -> bool:
        h = self._hash_text(text)
        table = self._get_table()
        res = table.query(KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": f"HASH#{h}"})
        return bool(res.get("Items"))

    def put_fact(
        self,
        text: str,
        tags: list[str],
        source_id: str,
        structures: list[str],
        rels: list[list[str]] = (),
        action: str | None = None,
        owner: str | None = None,
        depends_on: str | None = None,
    ) -> int | None:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every fact requires an existing source.")
        if self.fact_exists_by_text(text):
            return None

        fid = int(time.time() * 1000) % 1_000_000_000
        table = self._get_table()
        now = time.time()
        h = self._hash_text(text)

        # Retrieve source metadata for denormalized fast query
        src_res = table.get_item(Key={"PK": f"SOURCE#{source_id}", "SK": "METADATA"})
        src_item = src_res.get("Item", {})

        fact_item = {
            "PK": f"FACT#{fid}",
            "SK": "METADATA",
            "id": fid,
            "text": text,
            "tags": json.dumps(tags),
            "source_id": source_id,
            "project_id": src_item.get("project_id", "proj_default"),
            "structure": json.dumps(structures),
            "title": src_item.get("title", "Unknown"),
            "uri": src_item.get("uri", ""),
            "created": str(now),
            "rels": json.dumps(rels),
            "action": action or "",
            "owner": owner or "",
            "depends_on": depends_on or "",
        }
        table.put_item(Item=fact_item)
        table.put_item(Item={"PK": f"HASH#{h}", "SK": f"FACT#{fid}"})
        return fid

    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        # Scan fact items
        res = table.scan(FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
                         ExpressionAttributeValues={":sk": "METADATA", ":prefix": "FACT#"})
        out = []
        for item in res.get("Items", []):
            item_proj = item.get("project_id", "proj_default")
            if project_id and item_proj != project_id:
                continue
            out.append({
                "id": int(item["id"]),
                "text": item["text"],
                "tags": item["tags"],
                "structure": item["structure"],
                "source_id": item["source_id"],
                "project_id": item_proj,
                "title": item.get("title", ""),
                "uri": item.get("uri") or None,
                "action": item.get("action") or None,
                "owner": item.get("owner") or None,
                "depends_on": item.get("depends_on") or None,
            })
        return out

    def put_vector(self, fact_id: int, vector_bytes: bytes) -> None:
        table = self._get_table()
        b64_vec = base64.b64encode(vector_bytes).decode("ascii")
        table.update_item(
            Key={"PK": f"FACT#{fact_id}", "SK": "METADATA"},
            UpdateExpression="SET vec_b64 = :v",
            ExpressionAttributeValues={":v": b64_vec},
        )

    def get_all_vectors(self) -> dict[int, np.ndarray]:
        table = self._get_table()
        res = table.scan(FilterExpression="attribute_exists(vec_b64)",
                         ProjectionExpression="id, vec_b64")
        out = {}
        for item in res.get("Items", []):
            raw = base64.b64decode(item["vec_b64"].encode("ascii"))
            out[int(item["id"])] = np.frombuffer(raw, dtype=np.float32)
        return out

    def put_edges(self, fact_id: int, rels: list[list[str]]) -> None:
        table = self._get_table()
        table.update_item(
            Key={"PK": f"FACT#{fact_id}", "SK": "METADATA"},
            UpdateExpression="SET rels = :r",
            ExpressionAttributeValues={":r": json.dumps(rels)},
        )

    def get_all_edges(self) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(FilterExpression="attribute_exists(rels)",
                         ProjectionExpression="id, rels")
        out = []
        for item in res.get("Items", []):
            fid = int(item["id"])
            rels = json.loads(item.get("rels", "[]"))
            for r in rels:
                if len(r) == 3:
                    out.append({"fact_id": fid, "a": r[0], "b": r[2]})
        return out

