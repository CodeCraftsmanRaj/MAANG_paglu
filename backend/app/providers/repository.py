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
    """SQLite-backed implementation for persistent projects, sources, facts, vecs, edges, and rejected guardrails."""

    def create_project(
        self,
        name: str,
        created_by: str,
        project_type: str = "general",
        structure_mode: str = "rag",
        classification_reason: str | None = None,
        members: list[str] | None = None,
    ) -> dict[str, Any]:
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        now = time.time()
        reason = classification_reason or f"Project initialized in {structure_mode} mode"
        m_list = members or ["*"]
        run(
            "INSERT INTO projects(id, name, created_by, created_at, project_type, structure_mode, classification_reason, members) VALUES(?,?,?,?,?,?,?,?)",
            (pid, name, created_by, now, project_type, structure_mode, reason, json.dumps(m_list)),
        )
        return {
            "id": pid,
            "name": name,
            "created_by": created_by,
            "created_at": now,
            "project_type": project_type,
            "structure_mode": structure_mode,
            "classification_reason": reason,
            "members": m_list,
        }

    def update_project_mode(self, project_id: str, structure_mode: str, reason: str | None = None) -> dict[str, Any] | None:
        r = rows("SELECT * FROM projects WHERE id=?", (project_id,))
        if not r:
            return None
        cur_reason = reason or f"Structure mode manually set to {structure_mode}"
        run("UPDATE projects SET structure_mode=?, classification_reason=? WHERE id=?", (structure_mode, cur_reason, project_id))
        return self.get_project(project_id)

    def get_projects(self, username: str | None = None) -> list[dict[str, Any]]:
        res = rows("SELECT * FROM projects ORDER BY created_at ASC")
        out = []
        for r in res:
            m = r.get("members", '["*"]')
            out.append({
                **dict(r),
                "members": json.loads(m) if isinstance(m, str) else m,
            })
        return out

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        r = rows("SELECT * FROM projects WHERE id=?", (project_id,))
        if not r:
            return None
        item = dict(r[0])
        m = item.get("members", '["*"]')
        item["members"] = json.loads(m) if isinstance(m, str) else m
        return item

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
        key: str | None = None,
        condition: str | None = None,
        outcome: str | None = None,
        superseded_by: int | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
        priority: int = 0,
    ) -> int | None:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every fact requires an existing source.")
        if self.fact_exists_by_text(text):
            return None

        fid = run(
            "INSERT INTO facts(text,tags,source_id,structure,created,action,owner,depends_on,key,condition,outcome,superseded_by,valid_from,valid_to,priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (text, json.dumps(tags), source_id, json.dumps(structures), time.time(), action, owner, depends_on, key, condition, outcome, superseded_by, valid_from, valid_to, priority),
        )
        return fid

    def supersede_fact(self, old_fact_id: int, new_fact_id: int) -> None:
        run("UPDATE facts SET superseded_by=? WHERE id=?", (new_fact_id, old_fact_id))

    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return rows(
                "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.action, f.owner, f.depends_on, "
                "f.key, f.condition, f.outcome, f.superseded_by, f.valid_from, f.valid_to, f.priority, f.created, "
                "s.kind as source_kind, s.title, s.uri, s.mode as source_mode, s.created as source_created, s.project_id, "
                "p.name as project_name "
                "FROM facts f JOIN sources s ON s.id=f.source_id LEFT JOIN projects p ON p.id=s.project_id WHERE s.project_id=?",
                (project_id,),
            )
        return rows(
            "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.action, f.owner, f.depends_on, "
            "f.key, f.condition, f.outcome, f.superseded_by, f.valid_from, f.valid_to, f.priority, f.created, "
            "s.kind as source_kind, s.title, s.uri, s.mode as source_mode, s.created as source_created, s.project_id, "
            "p.name as project_name "
            "FROM facts f JOIN sources s ON s.id=f.source_id LEFT JOIN projects p ON p.id=s.project_id"
        )

    def put_rejected_fact(self, text: str, reason: str, tags: list[str], source_id: str) -> int:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every rejected fact requires an existing source.")
        return run(
            "INSERT INTO rejected_facts(text,reason,tags,source_id,created_at) VALUES(?,?,?,?,?)",
            (text, reason, json.dumps(tags), source_id, time.time()),
        )

    def get_rejected_facts(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return rows(
                "SELECT rf.id, rf.text, rf.reason, rf.tags, rf.source_id, rf.created_at, s.title, s.uri, s.project_id "
                "FROM rejected_facts rf JOIN sources s ON s.id=rf.source_id WHERE s.project_id=? ORDER BY rf.created_at DESC",
                (project_id,),
            )
        return rows(
            "SELECT rf.id, rf.text, rf.reason, rf.tags, rf.source_id, rf.created_at, s.title, s.uri, s.project_id "
            "FROM rejected_facts rf JOIN sources s ON s.id=rf.source_id ORDER BY rf.created_at DESC"
        )

    def get_fact_history(self, fact_id_or_key: str | int, project_id: str | None = None) -> list[dict[str, Any]]:
        target_key = None
        if isinstance(fact_id_or_key, int) or (isinstance(fact_id_or_key, str) and fact_id_or_key.isdigit()):
            f = rows("SELECT key FROM facts WHERE id=?", (int(fact_id_or_key),))
            target_key = f[0]["key"] if f and f[0].get("key") else None
        else:
            target_key = str(fact_id_or_key).strip()

        if target_key:
            if project_id:
                return rows(
                    "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.key, f.condition, f.outcome, f.superseded_by, f.created, s.title, s.uri, s.project_id "
                    "FROM facts f JOIN sources s ON s.id=f.source_id WHERE s.project_id=? AND f.key=? ORDER BY f.created ASC",
                    (project_id, target_key),
                )
            return rows(
                "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.key, f.condition, f.outcome, f.superseded_by, f.created, s.title, s.uri, s.project_id "
                "FROM facts f JOIN sources s ON s.id=f.source_id WHERE f.key=? ORDER BY f.created ASC",
                (target_key,),
            )
        return rows(
            "SELECT f.id, f.text, f.tags, f.structure, f.source_id, f.key, f.condition, f.outcome, f.superseded_by, f.created, s.title, s.uri, s.project_id "
            "FROM facts f JOIN sources s ON s.id=f.source_id WHERE f.id=?",
            (fact_id_or_key,),
        )

    def put_vector(self, fact_id: int, vector_bytes: bytes, model_name: str | None = None, dim: int | None = None) -> None:
        if model_name is None or dim is None:
            from ..factory import get_embedding_provider
            prov = get_embedding_provider()
            model_name = model_name or prov.model_name
            dim = dim or prov.dimension
        run("INSERT OR REPLACE INTO vecs (fact_id, v, model_name, dim) VALUES(?,?,?,?)", (fact_id, vector_bytes, model_name, dim))

    def get_all_vectors(self, model_name: str | None = None, dim: int | None = None) -> dict[int, np.ndarray]:
        if model_name is not None and dim is not None:
            res = rows("SELECT fact_id, v FROM vecs WHERE model_name=? AND dim=?", (model_name, dim))
        else:
            res = rows("SELECT fact_id, v FROM vecs")
        return {r["fact_id"]: np.frombuffer(r["v"], dtype=np.float32) for r in res}

    def get_project_vectors_metadata(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return rows(
                "SELECT DISTINCT v.model_name, v.dim, COUNT(v.fact_id) as count "
                "FROM vecs v JOIN facts f ON f.id = v.fact_id JOIN sources s ON s.id = f.source_id "
                "WHERE s.project_id=? GROUP BY v.model_name, v.dim",
                (project_id,),
            )
        return rows("SELECT DISTINCT model_name, dim, COUNT(fact_id) as count FROM vecs GROUP BY model_name, dim")


    def put_edges(self, fact_id: int, rels: list[list[str]]) -> None:
        for r in rels:
            if len(r) == 3:
                run("INSERT INTO edges VALUES(?,?,?,?)", (fact_id, r[0], r[1], r[2]))

    def get_all_edges(self) -> list[dict[str, Any]]:
        return rows("SELECT fact_id, a, b FROM edges")


class DynamoDBFactRepository(FactRepository):
    """AWS DynamoDB single-table implementation for persistent sources, facts, vecs, relations, and rejected items.

    Table Key Design:
      - Project Item:    PK = "PROJECT#<id>",  SK = "METADATA"
      - Source Metadata: PK = "SOURCE#<id>",   SK = "METADATA"
      - URI Lookup:      PK = "URI#<uri>",     SK = "METADATA"
      - Fact Item:       PK = "FACT#<id>",     SK = "METADATA"
      - Rejected Item:   PK = "REJECTED#<id>", SK = "METADATA"
      - Fact Text Hash:  PK = "HASH#<md5>",    SK = "FACT#<id>"
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

    def create_project(
        self,
        name: str,
        created_by: str,
        project_type: str = "general",
        structure_mode: str = "rag",
        classification_reason: str | None = None,
        members: list[str] | None = None,
    ) -> dict[str, Any]:
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        now = time.time()
        reason = classification_reason or f"Project initialized in {structure_mode} mode"
        m_list = members or ["*"]
        table = self._get_table()
        item = {
            "PK": f"PROJECT#{pid}",
            "SK": "METADATA",
            "id": pid,
            "name": name,
            "created_by": created_by,
            "created_at": str(now),
            "project_type": project_type,
            "structure_mode": structure_mode,
            "classification_reason": reason,
            "members": json.dumps(m_list),
        }
        table.put_item(Item=item)
        return {
            "id": pid,
            "name": name,
            "created_by": created_by,
            "created_at": now,
            "project_type": project_type,
            "structure_mode": structure_mode,
            "classification_reason": reason,
            "members": m_list,
        }

    def update_project_mode(self, project_id: str, structure_mode: str, reason: str | None = None) -> dict[str, Any] | None:
        table = self._get_table()
        cur_reason = reason or f"Structure mode manually set to {structure_mode}"
        table.update_item(
            Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"},
            UpdateExpression="SET structure_mode = :sm, classification_reason = :cr",
            ExpressionAttributeValues={":sm": structure_mode, ":cr": cur_reason},
        )
        return self.get_project(project_id)

    def get_projects(self, username: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
                         ExpressionAttributeValues={":sk": "METADATA", ":prefix": "PROJECT#"})
        projects = []
        for item in res.get("Items", []):
            m = item.get("members", '["*"]')
            projects.append({
                "id": item["id"],
                "name": item["name"],
                "created_by": item["created_by"],
                "created_at": float(item.get("created_at", 0)),
                "project_type": item.get("project_type", "general"),
                "structure_mode": item.get("structure_mode", "rag"),
                "classification_reason": item.get("classification_reason", ""),
                "members": json.loads(m) if isinstance(m, str) else m,
            })
        if not projects:
            projects = [{
                "id": "proj_default",
                "name": "Untitled project",
                "created_by": "system",
                "created_at": 0.0,
                "project_type": "general",
                "structure_mode": "rag",
                "classification_reason": "Default general project with hybrid RAG retrieval",
                "members": ["*"],
            }]
        projects.sort(key=lambda x: x["created_at"])
        return projects

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        table = self._get_table()
        res = table.get_item(Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"})
        item = res.get("Item")
        if not item:
            if project_id == "proj_default":
                return {
                    "id": "proj_default",
                    "name": "Untitled project",
                    "created_by": "system",
                    "created_at": 0.0,
                    "project_type": "general",
                    "structure_mode": "rag",
                    "classification_reason": "Default general project with hybrid RAG retrieval",
                    "members": ["*"],
                }
            return None
        m = item.get("members", '["*"]')
        return {
            "id": item["id"],
            "name": item["name"],
            "created_by": item["created_by"],
            "created_at": float(item.get("created_at", 0)),
            "project_type": item.get("project_type", "general"),
            "structure_mode": item.get("structure_mode", "rag"),
            "classification_reason": item.get("classification_reason", ""),
            "members": json.loads(m) if isinstance(m, str) else m,
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
        key: str | None = None,
        condition: str | None = None,
        outcome: str | None = None,
        superseded_by: int | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
        priority: int = 0,
    ) -> int | None:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every fact requires an existing source.")
        if self.fact_exists_by_text(text):
            return None

        fid = int(time.time() * 1000) % 1_000_000_000
        table = self._get_table()
        now = time.time()
        h = self._hash_text(text)

        src_res = table.get_item(Key={"PK": f"SOURCE#{source_id}", "SK": "METADATA"})
        src_res = table.get_item(Key={"PK": f"SOURCE#{source_id}", "SK": "METADATA"})
        src_item = src_res.get("Item", {})
        proj_id = src_item.get("project_id", "proj_default")
        proj_res = table.get_item(Key={"PK": f"PROJECT#{proj_id}", "SK": "METADATA"})
        proj_name = proj_res.get("Item", {}).get("name", "Default Workspace")

        fact_item = {
            "PK": f"FACT#{fid}",
            "SK": "METADATA",
            "id": fid,
            "text": text,
            "tags": json.dumps(tags),
            "source_id": source_id,
            "project_id": proj_id,
            "project_name": proj_name,
            "source_kind": src_item.get("kind", "text"),
            "source_mode": src_item.get("mode", "static"),
            "source_created": src_item.get("created", str(now)),
            "structure": json.dumps(structures),
            "title": src_item.get("title", "Unknown"),
            "uri": src_item.get("uri", ""),
            "created": str(now),
            "rels": json.dumps(rels),
            "action": action or "",
            "owner": owner or "",
            "depends_on": depends_on or "",
            "key": key or "",
            "condition": condition or "",
            "outcome": outcome or "",
            "superseded_by": str(superseded_by) if superseded_by is not None else "",
            "valid_from": str(valid_from) if valid_from is not None else "",
            "valid_to": str(valid_to) if valid_to is not None else "",
            "priority": int(priority),
        }
        table.put_item(Item=fact_item)
        table.put_item(Item={"PK": f"HASH#{h}", "SK": f"FACT#{fid}"})
        return fid

    def supersede_fact(self, old_fact_id: int, new_fact_id: int) -> None:
        table = self._get_table()
        table.update_item(
            Key={"PK": f"FACT#{old_fact_id}", "SK": "METADATA"},
            UpdateExpression="SET superseded_by = :s",
            ExpressionAttributeValues={":s": str(new_fact_id)},
        )

    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
                         ExpressionAttributeValues={":sk": "METADATA", ":prefix": "FACT#"})
        out = []
        for item in res.get("Items", []):
            item_proj = item.get("project_id", "proj_default")
            if project_id and item_proj != project_id:
                continue
            sup = item.get("superseded_by")
            vf = item.get("valid_from")
            vt = item.get("valid_to")
            out.append({
                "id": int(item["id"]),
                "text": item["text"],
                "tags": item["tags"],
                "structure": item["structure"],
                "source_id": item["source_id"],
                "project_id": item_proj,
                "project_name": item.get("project_name", "Default Workspace"),
                "source_kind": item.get("source_kind", "text"),
                "source_mode": item.get("source_mode", "static"),
                "source_created": float(item.get("source_created", item.get("created", 0))),
                "title": item.get("title", ""),
                "uri": item.get("uri") or None,
                "action": item.get("action") or None,
                "owner": item.get("owner") or None,
                "depends_on": item.get("depends_on") or None,
                "key": item.get("key") or None,
                "condition": item.get("condition") or None,
                "outcome": item.get("outcome") or None,
                "superseded_by": int(sup) if sup and str(sup).isdigit() else None,
                "valid_from": float(vf) if vf and str(vf).replace(".", "", 1).isdigit() else None,
                "valid_to": float(vt) if vt and str(vt).replace(".", "", 1).isdigit() else None,
                "priority": int(item.get("priority", 0)),
                "created": float(item.get("created", 0)),
            })
        return out

    def put_rejected_fact(self, text: str, reason: str, tags: list[str], source_id: str) -> int:
        if not self.source_exists(source_id):
            raise ValueError(f"Invalid source_id '{source_id}': every rejected fact requires an existing source.")
        rid = int(time.time() * 1000) % 1_000_000_000
        table = self._get_table()
        now = time.time()
        src_res = table.get_item(Key={"PK": f"SOURCE#{source_id}", "SK": "METADATA"})
        src_item = src_res.get("Item", {})

        item = {
            "PK": f"REJECTED#{rid}",
            "SK": "METADATA",
            "id": rid,
            "text": text,
            "reason": reason,
            "tags": json.dumps(tags),
            "source_id": source_id,
            "project_id": src_item.get("project_id", "proj_default"),
            "created_at": str(now),
            "title": src_item.get("title", ""),
            "uri": src_item.get("uri", ""),
        }
        table.put_item(Item=item)
        return rid

    def get_rejected_facts(self, project_id: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(FilterExpression="SK = :sk AND begins_with(PK, :prefix)",
                         ExpressionAttributeValues={":sk": "METADATA", ":prefix": "REJECTED#"})
        out = []
        for item in res.get("Items", []):
            item_proj = item.get("project_id", "proj_default")
            if project_id and item_proj != project_id:
                continue
            out.append({
                "id": int(item["id"]),
                "text": item["text"],
                "reason": item["reason"],
                "tags": item["tags"],
                "source_id": item["source_id"],
                "project_id": item_proj,
                "title": item.get("title", ""),
                "uri": item.get("uri") or None,
                "created_at": float(item.get("created_at", 0)),
            })
        return out

    def get_fact_history(self, fact_id_or_key: str | int, project_id: str | None = None) -> list[dict[str, Any]]:
        all_facts = self.get_all_facts_with_sources(project_id=project_id)
        target_key = str(fact_id_or_key).strip()
        filtered = [f for f in all_facts if f.get("key") == target_key or str(f["id"]) == target_key]
        filtered.sort(key=lambda x: x.get("created", 0))
        return filtered

    def put_vector(self, fact_id: int, vector_bytes: bytes, model_name: str | None = None, dim: int | None = None) -> None:
        if model_name is None or dim is None:
            from ..factory import get_embedding_provider
            prov = get_embedding_provider()
            model_name = model_name or prov.model_name
            dim = dim or prov.dimension
        table = self._get_table()
        b64_vec = base64.b64encode(vector_bytes).decode("ascii")
        table.update_item(
            Key={"PK": f"FACT#{fact_id}", "SK": "METADATA"},
            UpdateExpression="SET vec_b64 = :v, vec_model = :m, vec_dim = :d",
            ExpressionAttributeValues={":v": b64_vec, ":m": model_name, ":d": dim},
        )

    def get_all_vectors(self, model_name: str | None = None, dim: int | None = None) -> dict[int, np.ndarray]:
        table = self._get_table()
        if model_name is not None and dim is not None:
            res = table.scan(
                FilterExpression="attribute_exists(vec_b64) AND vec_model = :m AND vec_dim = :d",
                ExpressionAttributeValues={":m": model_name, ":d": dim},
                ProjectionExpression="id, vec_b64",
            )
        else:
            res = table.scan(
                FilterExpression="attribute_exists(vec_b64)",
                ProjectionExpression="id, vec_b64",
            )
        out = {}
        for item in res.get("Items", []):
            raw = base64.b64decode(item["vec_b64"].encode("ascii"))
            out[int(item["id"])] = np.frombuffer(raw, dtype=np.float32)
        return out

    def get_project_vectors_metadata(self, project_id: str | None = None) -> list[dict[str, Any]]:
        table = self._get_table()
        res = table.scan(
            FilterExpression="attribute_exists(vec_b64)",
            ProjectionExpression="id, vec_model, vec_dim, project_id",
        )
        counts = {}
        for item in res.get("Items", []):
            if project_id and item.get("project_id") != project_id:
                continue
            m = item.get("vec_model", "unknown")
            d = int(item.get("vec_dim", 0))
            k = (m, d)
            counts[k] = counts.get(k, 0) + 1
        return [{"model_name": k[0], "dim": k[1], "count": cnt} for k, cnt in counts.items()]


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


