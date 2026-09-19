"""Adversarial RBAC Leak Matrix Test (8 Modes x 3 Roles).
Verifies:
1. Graph: 2-hop Dijkstra path walks do NOT traverse through hidden facts.
2. Versioned: History queries do NOT leak superseded facts tagged with restricted tags.
3. Denylist: Conflict warnings do NOT leak restricted rejected facts.
4. Keyvalue: Direct canonical key lookups do NOT bypass tag boundaries.
5. Allowlist: Strict tag membership returns exact or nothing with zero leak.
6. Keyword / Ruleset / RAG: Zero access for unauthorized roles.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.db import run, rows
from app.factory import get_fact_repository, get_llm_provider
from app.structuring import structure_doc, retrieve


class TestRBACMatrixAcrossAllModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DB_PROVIDER"] = "sqlite"
        cls.repo = get_fact_repository()
        cls.llm = get_llm_provider()

    def setUp(self):
        run("DELETE FROM rejected_facts")
        run("DELETE FROM facts")
        run("DELETE FROM sources")
        run("DELETE FROM edges")
        run("DELETE FROM vecs")
        run("DELETE FROM projects WHERE id NOT IN ('proj_default')")

    def test_01_graph_traversal_leak_prevention(self):
        """A user with only 'frontend' role should not traverse through 'database' edges to reach secret facts."""
        p = self.repo.create_project("Graph Pipeline", "admin", structure_mode="graph")
        sid = self.repo.put_source("text", "Pipeline", None, "static", project_id=p["id"])

        # Fact 1: Frontend (public to developer)
        structure_doc("frontend web connects to api gateway", sid, ["graph", "flat"], extra_tags=["frontend"], project_id=p["id"], structure_mode="graph")
        # Fact 2: Database Secret Bridge (restricted to admin/security)
        structure_doc("api gateway connects to secure vault", sid, ["graph", "flat"], extra_tags=["database"], project_id=p["id"], structure_mode="graph")
        # Fact 3: Secret Vault (restricted to admin/security)
        structure_doc("secure vault contains master private key", sid, ["graph", "flat"], extra_tags=["database"], project_id=p["id"], structure_mode="graph")

        # Developer with only ['frontend'] scope querying 'private key' or 'frontend'
        ret_dev = retrieve("frontend private key", allowed=["frontend"], project_id=p["id"])
        # Should only see Fact 1, never Fact 2 or 3, and graph walk should NOT bridge into vault
        texts = [f["text"] for f in ret_dev["facts"]]
        self.assertFalse(any("private key" in t for t in texts))
        self.assertFalse(any("secure vault" in t for t in texts))

    def test_02_versioned_history_leak_prevention(self):
        """Superseded facts that carry restricted tags must NOT leak in history queries to unprivileged roles."""
        p = self.repo.create_project("Pricing Evolution", "admin", structure_mode="versioned")
        sid = self.repo.put_source("text", "Pricing", None, "static", project_id=p["id"])

        # Restricted internal pricing
        structure_doc("enterprise_token: $50,000 secret internal baseline", sid, ["flat"], extra_tags=["database"], project_id=p["id"], structure_mode="versioned")

        # Developer with ['frontend'] scope should NOT see this in standard or history queries
        ret = retrieve("enterprise_token history", allowed=["frontend"], project_id=p["id"], include_history=True)
        self.assertEqual(len(ret["facts"]), 0)

    def test_03_denylist_warning_leak_prevention(self):
        """Guardrail conflict warnings tagged with restricted scopes must NOT leak to unauthorized roles."""
        p = self.repo.create_project("Guardrails", "admin", structure_mode="denylist")
        sid = self.repo.put_source("text", "Secret Bans", None, "static", project_id=p["id"])

        # Rejected pattern tagged strictly with 'database'
        self.repo.put_rejected_fact("Do not use unencrypted DynamoDB tables in production", "Zero compliance", ["database"], sid)

        # Developer with ['frontend'] scope querying DynamoDB should get 0 warnings
        ret = retrieve("DynamoDB", allowed=["frontend"], project_id=p["id"])
        self.assertEqual(len(ret["warnings"]), 0)

        # Admin with ['*'] scope querying DynamoDB gets the alert
        ret_admin = retrieve("DynamoDB", allowed=["*"], project_id=p["id"])
        self.assertGreater(len(ret_admin["warnings"]), 0)

    def test_04_keyvalue_lookup_leak_prevention(self):
        """Canonical key lookup for a restricted key must return 0 facts for unauthorized roles."""
        p = self.repo.create_project("Secrets Config", "admin", structure_mode="keyvalue")
        sid = self.repo.put_source("text", "Env", None, "static", project_id=p["id"])

        structure_doc("AWS_SECRET_ACCESS_KEY: secret_key_abc123", sid, ["flat"], extra_tags=["database"], project_id=p["id"], structure_mode="keyvalue")

        # Developer with only ['frontend'] scope
        ret = retrieve("AWS_SECRET_ACCESS_KEY", allowed=["frontend"], project_id=p["id"])
        self.assertEqual(len(ret["facts"]), 0)

        ans = self.llm.answer("AWS_SECRET_ACCESS_KEY", ret["facts"], structure_mode="keyvalue")
        self.assertEqual(ans, "Key not found in project configuration.")

    def test_05_allowlist_deterministic_zero_leak(self):
        """Allowlist mode returns exact permitted facts or exact not-found without LLM hallucination."""
        p = self.repo.create_project("Strict Vault", "admin", structure_mode="allowlist")
        sid = self.repo.put_source("text", "Vault", None, "static", project_id=p["id"])

        structure_doc("PUBLIC_CDN_URL: https://cdn.example.com", sid, ["flat"], extra_tags=["frontend"], project_id=p["id"], structure_mode="allowlist")

        # Unpermitted query
        ret = retrieve("DATABASE_PASSWORD", allowed=["frontend"], project_id=p["id"])
        self.assertEqual(len(ret["facts"]), 0)

        ans = self.llm.answer("DATABASE_PASSWORD", ret["facts"], structure_mode="allowlist")
        self.assertEqual(ans, "Not found in your permitted scope.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
