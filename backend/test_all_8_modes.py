"""Comprehensive test suite for all 8 retrieval paradigms in ContextForge.
Tests:
1. graph: 2-hop Dijkstra graph traversal + execution checklist
2. allowlist: strict tag boundary, zero fuzzy matching
3. denylist: rejected_facts capture, ingest conflict warnings, guardrail alert retrieval
4. keyword: literal technical string matching (FlatStore)
5. keyvalue: canonical key lookup returning direct answers
6. ruleset: conditional branching (condition -> outcome)
7. versioned: temporal knowledge with superseded_by linking and history chain
8. rag: hybrid retrieval (Flat + Vector + Graph) synthesis
9. dynamic LLM classification + manual override via PUT /api/projects/{id}/mode
"""
import os
import sys
import unittest

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.db import run, rows
from app.factory import get_fact_repository, get_llm_provider
from app.structuring import structure_doc, retrieve, search_facts
from app.providers.llm import heuristic_classify_structure_mode


class TestAll8RetrievalModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force SQLite DB for testing
        os.environ["DB_PROVIDER"] = "sqlite"
        cls.repo = get_fact_repository()
        cls.llm = get_llm_provider()

    def setUp(self):
        # Clean test tables
        run("DELETE FROM rejected_facts")
        run("DELETE FROM facts")
        run("DELETE FROM sources")
        run("DELETE FROM edges")
        run("DELETE FROM vecs")
        run("DELETE FROM projects WHERE id NOT IN ('proj_default')")

    def test_01_dynamic_classification(self):
        """Test classification heuristics and reason storage."""
        cases = [
            ("Refund Policy & Eligibility Rules", "If purchase > 30 days then no refund.", "ruleset"),
            ("Production Anti-Patterns & Banned Tools", "Do not use MongoDB for transactions.", "denylist"),
            ("Service Ports & Environment Variables", "DATABASE_PORT=5432\nAPI_HOST=0.0.0.0", "keyvalue"),
            ("Pricing Version History & Changelog", "Version 2.0 updated Pro Tier pricing.", "versioned"),
            ("Release Deployment Runbook", "Step 1: Build docker image after PR approval.", "graph"),
            ("API Secrets & Permission Scopes", "RESTRICTED secret tokens allowlist only.", "allowlist"),
            ("Server Error Codes and Log Tracebacks", "Error ERR_SOCKET_TIMEOUT at /var/log/syslog", "keyword"),
            ("Platform Architectural Overview", "General system design and narrative docs.", "rag"),
        ]
        for name, sample, expected_mode in cases:
            res = self.llm.classify_structure_mode(name, sample)
            self.assertEqual(res["mode"], expected_mode, f"Failed for {name}: got {res['mode']}")
            self.assertTrue(len(res["reason"]) > 5)

    def test_02_project_creation_and_mode_override(self):
        """Test project creation with auto classification and manual mode override."""
        # Create project with auto-classification
        p = self.repo.create_project(
            name="Cloud Environment Settings",
            created_by="admin",
            structure_mode="keyvalue",
            classification_reason="User specified key-value config",
        )
        self.assertEqual(p["structure_mode"], "keyvalue")

        # Override mode via repo method
        updated = self.repo.update_project_mode(p["id"], "ruleset", "Switched to conditional rules")
        self.assertEqual(updated["structure_mode"], "ruleset")
        self.assertEqual(updated["classification_reason"], "Switched to conditional rules")

    def test_03_graph_mode_execution(self):
        """Test Graph mode: dependencies, procedural fields, and checklist runbook."""
        p = self.repo.create_project("Release Pipeline", "admin", project_type="process", structure_mode="graph")
        sid = self.repo.put_source("text", "Deploy Guide", None, "static", project_id=p["id"])

        text = (
            "Step 1: Build docker image owned by @devops.\n"
            "Step 2: Run database migrations after Build docker image owned by @dba.\n"
            "Step 3: Restart backend service after Run database migrations owned by @lead."
        )
        res = structure_doc(text, sid, ["graph", "flat", "vector"], project_id=p["id"], structure_mode="graph")
        self.assertGreaterEqual(int(res), 2)

        ret = retrieve("How to deploy?", allowed=["*"], project_id=p["id"])
        self.assertEqual(ret["structure_mode"], "graph")
        self.assertGreater(len(ret["facts"]), 0)

        # Verify answer formatting produces execution checklist
        ans = self.llm.answer("How to deploy?", ret["facts"], is_process=True, structure_mode="graph")
        self.assertIn("Step", ans)

    def test_04_allowlist_mode(self):
        """Test Allowlist mode: strict tag membership, zero fuzzy matching."""
        p = self.repo.create_project("Restricted Vault", "admin", structure_mode="allowlist")
        sid = self.repo.put_source("text", "Secrets", None, "static", project_id=p["id"])

        # Fact with 'database' tag
        structure_doc("DB_ADMIN_TOKEN = secret_token_9999", sid, ["flat"], extra_tags=["database"], project_id=p["id"], structure_mode="allowlist")
        # Fact with 'frontend' tag
        structure_doc("PUBLIC_ANALYTICS_KEY = pk_live_1234", sid, ["flat"], extra_tags=["frontend"], project_id=p["id"], structure_mode="allowlist")

        # Developer with only 'frontend' scope queries permitted key -> finds it
        ret_frontend = retrieve("ANALYTICS", allowed=["frontend"], project_id=p["id"])
        texts = [f["text"] for f in ret_frontend["facts"]]
        self.assertTrue(any("PUBLIC_ANALYTICS_KEY" in t for t in texts))
        self.assertFalse(any("DB_ADMIN_TOKEN" in t for t in texts))

        # Developer with only 'frontend' scope queries secret key -> 0 facts returned
        ret_secret = retrieve("DB_ADMIN_TOKEN", allowed=["frontend"], project_id=p["id"])
        self.assertEqual(len(ret_secret["facts"]), 0)

    def test_05_denylist_guardrail_mode(self):
        """Test Denylist mode: rejected_facts capture, conflict warnings on ingest, guardrail alert retrieval."""
        p_guard = self.repo.create_project("Architecture Guardrails", "admin", structure_mode="denylist")
        sid_guard = self.repo.put_source("text", "Banned Tech", None, "static", project_id=p_guard["id"])

        # Ingest anti-pattern into denylist project
        guard_text = "Do not use MongoDB for billing transactions due to lack of multi-table ACID isolation."
        res = structure_doc(guard_text, sid_guard, ["flat"], project_id=p_guard["id"], structure_mode="denylist")
        self.assertGreater(res.rejected, 0)

        # Check rejected facts table
        rejected_list = self.repo.get_rejected_facts()
        self.assertTrue(any("mongodb" in rf["text"].lower() for rf in rejected_list))

        # Ingest new doc into another project mentioning the forbidden pattern -> must trigger warning!
        p_billing = self.repo.create_project("Billing Service", "admin", structure_mode="rag")
        sid_billing = self.repo.put_source("text", "Billing Proposal", None, "static", project_id=p_billing["id"])
        res2 = structure_doc("We propose using MongoDB for billing storage.", sid_billing, ["flat"], project_id=p_billing["id"], structure_mode="rag")
        self.assertGreater(len(res2.warnings), 0)
        self.assertIn("MongoDB", res2.warnings[0]["warning"])

        # Retrieve in denylist project triggers warning
        ret = retrieve("Can we use MongoDB for billing?", allowed=["*"], project_id=p_guard["id"])
        self.assertGreater(len(ret["warnings"]), 0)
        ans = self.llm.answer("Can we use MongoDB for billing?", ret["facts"], structure_mode="denylist")
        self.assertIn("Guardrail Alert", ans)

    def test_06_keyword_mode(self):
        """Test Keyword mode: literal technical string matching."""
        p = self.repo.create_project("System Error Codes", "admin", structure_mode="keyword")
        sid = self.repo.put_source("text", "Nginx Errors", None, "static", project_id=p["id"])

        structure_doc("ERR_NGINX_502_BAD_GATEWAY: upstream server failed to respond on socket /tmp/app.sock", sid, ["flat"], project_id=p["id"], structure_mode="keyword")
        structure_doc("ERR_AUTH_401_UNAUTHORIZED: missing JWT bearer token in Authorization header", sid, ["flat"], project_id=p["id"], structure_mode="keyword")

        ret = retrieve("ERR_NGINX_502_BAD_GATEWAY", allowed=["*"], project_id=p["id"])
        self.assertEqual(len(ret["facts"]), 1)
        self.assertIn("ERR_NGINX_502_BAD_GATEWAY", ret["facts"][0]["text"])

    def test_07_keyvalue_mode(self):
        """Test Keyvalue mode: canonical key lookup returning direct answers."""
        p = self.repo.create_project("App Config", "admin", structure_mode="keyvalue")
        sid = self.repo.put_source("text", "Env Config", None, "static", project_id=p["id"])

        text = "DATABASE_PORT: 5432\nREDIS_HOST: redis.internal.net\nMAX_WORKERS: 8"
        structure_doc(text, sid, ["flat"], project_id=p["id"], structure_mode="keyvalue")

        ret = retrieve("DATABASE_PORT", allowed=["*"], project_id=p["id"])
        self.assertGreater(len(ret["facts"]), 0)
        self.assertEqual(ret["facts"][0]["key"], "DATABASE_PORT")

        ans = self.llm.answer("DATABASE_PORT", ret["facts"], structure_mode="keyvalue")
        self.assertIn("The value is:", ans)
        self.assertIn("5432", ans)

    def test_08_ruleset_mode(self):
        """Test Ruleset mode: conditional logic (condition -> outcome)."""
        p = self.repo.create_project("Refund Policy", "admin", structure_mode="ruleset")
        sid = self.repo.put_source("text", "Policy Document", None, "static", project_id=p["id"])

        text = (
            "If refund_amount > 500 then Requires VP approval.\n"
            "If refund_amount <= 500 then Auto-approved by system.\n"
            "If account_age < 30_days then Reject refund."
        )
        structure_doc(text, sid, ["flat"], project_id=p["id"], structure_mode="ruleset")

        ret = retrieve("What happens if refund_amount > 500?", allowed=["*"], project_id=p["id"])
        self.assertGreater(len(ret["facts"]), 0)
        ans = self.llm.answer("What happens if refund_amount > 500?", ret["facts"], structure_mode="ruleset")
        self.assertTrue("outcome is" in ans.lower() or "because" in ans.lower() or "decision" in ans.lower())

    def test_09_versioned_mode_and_history(self):
        """Test Versioned mode: automatic supersession linking and history chain."""
        p = self.repo.create_project("Pricing Tiers", "admin", structure_mode="versioned")
        sid1 = self.repo.put_source("text", "Pricing 2024", None, "static", project_id=p["id"])
        sid2 = self.repo.put_source("text", "Pricing 2025", None, "static", project_id=p["id"])

        # v1 fact
        structure_doc("pro_tier_price: $29/mo in 2024", sid1, ["flat"], project_id=p["id"], structure_mode="versioned")
        facts_v1 = self.repo.get_all_facts_with_sources(project_id=p["id"])
        fid1 = facts_v1[0]["id"]

        # v2 fact with same key -> should supersede v1
        structure_doc("pro_tier_price: $49/mo in 2025", sid2, ["flat"], project_id=p["id"], structure_mode="versioned")

        # Standard query should ONLY return active v2 ($49/mo)
        ret_active = retrieve("pro_tier_price", allowed=["*"], project_id=p["id"], include_history=False)
        self.assertEqual(len(ret_active["facts"]), 1)
        self.assertIn("$49/mo", ret_active["facts"][0]["text"])

        # History query should return both v1 and v2
        ret_hist = retrieve("pro_tier_price history", allowed=["*"], project_id=p["id"], include_history=True)
        self.assertEqual(len(ret_hist["facts"]), 2)

        # Fact history chain from repository
        history = self.repo.get_fact_history(fid1)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["id"], fid1)

    def test_10_rag_hybrid_mode(self):
        """Test RAG mode: multi-index hybrid scoring."""
        p = self.repo.create_project("Architecture Docs", "admin", structure_mode="rag")
        sid = self.repo.put_source("text", "Overview", None, "static", project_id=p["id"])

        doc = "ContextForge provides enterprise knowledge retrieval across graph, vector, and flat stores with tag-based access control."
        structure_doc(doc, sid, ["flat", "vector", "graph"], project_id=p["id"], structure_mode="rag")

        ret = retrieve("enterprise knowledge retrieval", allowed=["*"], project_id=p["id"])
        self.assertEqual(ret["structure_mode"], "rag")
        self.assertGreater(len(ret["facts"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
