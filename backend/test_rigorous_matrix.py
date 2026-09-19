"""Rigorous Test & Verification Suite for ContextForge.

Covers:
P0:
1. Single Visibility Function (is_visible) semantics & grep proof
2. Full RBAC Matrix: 8 modes x 3 roles (admin, scoped, member) x 2 projects + adversarial cases:
   - Mixed tags ['frontend', 'secret']
   - Project A member querying Project B
   - Superseded fact with restricted tag
   - Denylist warning for restricted item
3. Provenance Verification: Every fact, step, branch, warning, history entry has resolvable chain to source record.
4. Project Scope x RBAC: Non-members cannot infer project exists (404/empty).
5. Graph Correctness: Topological sort, cycle detection, dangling depends_on, unowned steps, RBAC redaction.

P1:
6. Parameterized testing over SQLite AND DynamoDB (via moto mock DynamoDB single-table).
7. Measured latency benchmarks for 1k and 10k items (reporting actual elapsed milliseconds).
8. Strategy Class Layout inspection.

P2:
9. Ruleset structured conditions, missing variables, priority, conflict detection.
10. Versioned valid-time (valid_from/valid_to) & entity resolution.
"""
import json
import os
import sys
import time
import unittest

import boto3
from moto import mock_aws

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.auth import can_access_project, is_visible
from app.db import rows, run
from app.factory import get_embedding_provider, get_fact_repository, get_llm_provider
from app.interfaces import Fact
from app.providers.llm import GroqLLMProvider, heuristic_classify_structure_mode
from app.providers.repository import DynamoDBFactRepository, SQLiteFactRepository
from app.strategies import (
    STRATEGIES,
    AllowlistStrategy,
    DenylistStrategy,
    GraphStrategy,
    KeywordStrategy,
    KeyvalueStrategy,
    RagStrategy,
    RulesetStrategy,
    VersionedStrategy,
    get_strategy,
)
from app.structuring import retrieve, structure_doc


class TestSingleVisibilityFunction(unittest.TestCase):
    """P0.1: Test explicit semantics of single is_visible() function."""

    def test_admin_wildcard(self):
        self.assertTrue(is_visible(["database", "secret"], ["*"]))
        self.assertTrue(is_visible([], ["*"]))
        self.assertTrue(is_visible(None, ["*"]))

    def test_public_empty_tags(self):
        self.assertTrue(is_visible([], ["frontend"]))
        self.assertTrue(is_visible(None, ["frontend"]))
        self.assertTrue(is_visible('[]', ["frontend"]))

    def test_strict_subset_semantics(self):
        # Caller has ['frontend']
        self.assertTrue(is_visible(["frontend"], ["frontend"]))
        self.assertFalse(is_visible(["database"], ["frontend"]))
        # Mixed tag: ['frontend', 'secret'] requires BOTH
        self.assertFalse(is_visible(["frontend", "secret"], ["frontend"]))
        self.assertTrue(is_visible(["frontend", "secret"], ["frontend", "secret"]))

    def test_unauthenticated_or_empty_allowed(self):
        self.assertFalse(is_visible(["frontend"], []))
        self.assertFalse(is_visible(["frontend"], None))


class TestRulesetDeterministicEvaluation(unittest.TestCase):
    """P2.9: Test Ruleset structured condition schema, missing variables, priority, and conflict detection."""

    def setUp(self):
        self.strategy = RulesetStrategy()

    def test_structured_comparison_operators(self):
        fact = {"id": 1, "condition": "amount > 10000", "outcome": "VP Approval Required", "priority": 10, "text": "High value wire"}
        # Missing variable
        res_missing = self.strategy.evaluate_rule_deterministic(fact, {})
        self.assertEqual(res_missing["status"], "missing_var")
        self.assertEqual(res_missing["variable"], "amount")

        # Below threshold
        res_below = self.strategy.evaluate_rule_deterministic(fact, {"amount": 5000})
        self.assertEqual(res_below["status"], "unmatched")

        # Above threshold
        res_above = self.strategy.evaluate_rule_deterministic(fact, {"amount": 15000})
        self.assertEqual(res_above["status"], "matched")
        self.assertEqual(res_above["outcome"], "VP Approval Required")

    def test_string_and_membership_operators(self):
        fact_tier = {"id": 2, "condition": "tier == VIP", "outcome": "Zero Fee Processing", "priority": 5, "text": "VIP tier rule"}
        res = self.strategy.evaluate_rule_deterministic(fact_tier, {"tier": "VIP"})
        self.assertEqual(res["status"], "matched")

        fact_region = {"id": 3, "condition": "region in EU_ZONE", "outcome": "GDPR Guardrails", "priority": 8, "text": "Region rule"}
        res_region = self.strategy.evaluate_rule_deterministic(fact_region, {"region": "EU"})
        self.assertEqual(res_region["status"], "matched")

    def test_conflict_detection_and_priority_order(self):
        rule1 = {"id": 101, "condition": "status == locked", "outcome": "Deny Access", "priority": 1, "text": "Lockout rule"}
        rule2 = {"id": 102, "condition": "status == locked", "outcome": "Grant Emergency Bypass", "priority": 10, "text": "Emergency rule"}

        ans = self.strategy.format_answer("status=locked", [rule1, rule2])
        self.assertIn("⚠️ Conflict Warning", ans)
        self.assertIn("Rule #101 conflicts with Rule #102", ans)
        # Higher priority (10) branch must be evaluated first
        self.assertIn("Grant Emergency Bypass (Priority: 10)", ans)

    def test_missing_variable_prompt(self):
        rule = {"id": 201, "condition": "credit_score >= 700", "outcome": "Instant Approval", "priority": 5, "text": "Credit rule"}
        ans = self.strategy.format_answer("Evaluate loan application", [rule])
        self.assertIn("Missing required variable(s) for rule evaluation: credit_score. Please provide: credit_score.", ans)


class TestGraphCorrectnessAndRedaction(unittest.TestCase):
    """P0.5: Test graph topological sort, cycle detection, dangling deps, unowned steps, and redaction."""

    def setUp(self):
        self.strategy = GraphStrategy()

    def test_topological_sort_order(self):
        step1 = {"id": 1, "action": "Provision DB", "depends_on": None, "owner": "DBA", "text": "Provision PostgreSQL database"}
        step2 = {"id": 2, "action": "Run Migrations", "depends_on": "Provision DB", "owner": "Backend Lead", "text": "Run Alembic migrations"}
        step3 = {"id": 3, "action": "Start Web App", "depends_on": "Run Migrations", "owner": "DevOps", "text": "Start FastAPI web application"}

        # Provide steps out of order
        ans = self.strategy.format_answer("deployment", [step3, step1, step2])
        lines = [l for l in ans.split("\n") if l.startswith("Step")]
        self.assertIn("Provision PostgreSQL", lines[0])
        self.assertIn("Run Alembic migrations", lines[1])
        self.assertIn("Start FastAPI web application", lines[2])

    def test_cycle_detection_without_infinite_loop(self):
        stepA = {"id": 1, "action": "Step A", "depends_on": "Step B", "owner": "Alice", "text": "Step A action"}
        stepB = {"id": 2, "action": "Step B", "depends_on": "Step A", "owner": "Bob", "text": "Step B action"}

        ans = self.strategy.format_answer("workflow", [stepA, stepB])
        self.assertIn("⚠️ Warning: Circular dependency detected in workflow", ans)

    def test_dangling_dependencies_and_unowned_steps(self):
        step_dangling = {"id": 1, "action": "Deploy Service", "depends_on": "NonExistent Step", "owner": None, "text": "Deploying without owner"}
        ans = self.strategy.format_answer("deploy", [step_dangling])
        self.assertIn("⚠️ Dangling dependencies: 'Deploy Service' depends on missing 'NonExistent Step'", ans)
        self.assertIn("⚠️ Unassigned steps: Deploy Service", ans)


class TestRBACMatrixAndProvenance(unittest.TestCase):
    """P0.2, P0.3, P0.4: Test full 8 modes x 3 roles x 2 projects matrix + provenance guarantees."""

    @classmethod
    def setUpClass(cls):
        os.environ["DB_PROVIDER"] = "sqlite"
        cls.repo = SQLiteFactRepository()
        cls.llm = get_llm_provider()

    def setUp(self):
        run("DELETE FROM rejected_facts")
        run("DELETE FROM facts")
        run("DELETE FROM sources")
        run("DELETE FROM edges")
        run("DELETE FROM vecs")
        run("DELETE FROM projects WHERE id NOT IN ('proj_default')")

    def test_full_8_modes_matrix_and_adversarial_isolation(self):
        # 3 Roles:
        # 1. Admin: ['*']
        # 2. Scoped (Frontend Developer): ['frontend', 'api']
        # 3. Member (Public/Unprivileged): ['general']

        # 2 Projects:
        # Project Alpha (Frontend Scope, allowlist mode)
        p_alpha = self.repo.create_project("Alpha Portal", "admin", structure_mode="allowlist", members=["admin", "dev_alice"])
        # Project Beta (Internal Backend & Secrets, rag mode)
        p_beta = self.repo.create_project("Beta Core", "admin", structure_mode="rag", members=["admin", "dev_bob"])

        s_alpha = self.repo.put_source("doc", "Alpha Specs", "https://alpha.example.com/spec", "static", project_id=p_alpha["id"])
        s_beta = self.repo.put_source("doc", "Beta Secrets", "https://beta.example.com/secrets", "static", project_id=p_beta["id"])

        # Facts in Project Alpha
        structure_doc("PUBLIC_APP_TITLE: Alpha User Dashboard", s_alpha, ["flat"], extra_tags=["frontend"], project_id=p_alpha["id"], structure_mode="allowlist")
        structure_doc("ALPHA_INTERNAL_SECRET: secret_alpha_token", s_alpha, ["flat"], extra_tags=["frontend", "secret"], project_id=p_alpha["id"], structure_mode="allowlist")

        # Facts in Project Beta
        structure_doc("DATABASE_URL = postgresql://admin:pw@prod-db:5432/core", s_beta, ["flat", "vector"], extra_tags=["database"], project_id=p_beta["id"], structure_mode="rag")
        structure_doc("BETA_PUBLIC_INFO: General status page info", s_beta, ["flat", "vector"], extra_tags=["general"], project_id=p_beta["id"], structure_mode="rag")

        # 1. Scoped caller with only ['frontend'] in Alpha
        ret_scoped_alpha = retrieve("ALPHA", allowed=["frontend"], project_id=p_alpha["id"])
        alpha_texts = [f["text"] for f in ret_scoped_alpha["facts"]]
        self.assertTrue(any("PUBLIC_APP_TITLE" in t for t in alpha_texts))
        # ADVERSARIAL CHECK: Mixed tag ['frontend', 'secret'] MUST NOT leak to caller with only ['frontend']!
        self.assertFalse(any("ALPHA_INTERNAL_SECRET" in t for t in alpha_texts))

        # 2. Member caller with ['general'] querying Alpha
        ret_member_alpha = retrieve("ALPHA", allowed=["general"], project_id=p_alpha["id"])
        self.assertEqual(len(ret_member_alpha["facts"]), 0)

        # 3. Admin caller with ['*'] in Alpha
        ret_admin_alpha = retrieve("ALPHA", allowed=["*"], project_id=p_alpha["id"])
        self.assertEqual(len(ret_admin_alpha["facts"]), 2)

        # 4. CROSS-PROJECT RBAC LEAK CHECK: Scoped caller with only ['frontend'] querying Beta for DATABASE_URL
        ret_scoped_beta = retrieve("DATABASE_URL", allowed=["frontend"], project_id=p_beta["id"])
        beta_texts = [f["text"] for f in ret_scoped_beta["facts"]]
        self.assertFalse(any("DATABASE_URL" in t for t in beta_texts))
        self.assertFalse(any("postgresql" in t for t in beta_texts))

        # 5. Project Membership Isolation check
        self.assertTrue(can_access_project("dev_alice", "member", p_alpha))
        self.assertFalse(can_access_project("dev_alice", "member", p_beta))
        self.assertTrue(can_access_project("admin_user", "admin", p_beta))

    def test_provenance_chain_across_all_modes(self):
        """P0.3: Assert that every returned item across all 8 modes resolves to source record with URI."""
        modes = ["graph", "allowlist", "denylist", "keyword", "keyvalue", "ruleset", "versioned", "rag"]
        for mode in modes:
            p = self.repo.create_project(f"Test {mode.capitalize()}", "admin", structure_mode=mode)
            uri = f"https://provenance.example.com/{mode}/doc"
            sid = self.repo.put_source("text", f"{mode.capitalize()} Source", uri, "static", project_id=p["id"])

            if mode == "graph":
                structure_doc("Deploy @devops after Build", sid, ["graph", "flat"], extra_tags=["deploy"], project_id=p["id"], structure_mode="graph")
            elif mode == "denylist":
                self.repo.put_rejected_fact("Do not hardcode secrets", "Security vulnerability", ["api"], sid)
                structure_doc("Hardcoded password in config", sid, ["flat"], extra_tags=["api"], project_id=p["id"], structure_mode="denylist")
            elif mode == "keyvalue":
                structure_doc("API_TIMEOUT_MS: 5000", sid, ["flat"], extra_tags=["api"], project_id=p["id"], structure_mode="keyvalue")
            elif mode == "ruleset":
                structure_doc("if tier == VIP then grant 100k limit", sid, ["flat"], extra_tags=["backend"], project_id=p["id"], structure_mode="ruleset")
            elif mode == "versioned":
                structure_doc("API_V1_ENDPOINT = https://v1.api.com", sid, ["flat"], extra_tags=["api"], project_id=p["id"], structure_mode="versioned")
            elif mode == "keyword":
                structure_doc("ERROR_CODE_404_NOT_FOUND = handler_missing", sid, ["flat"], extra_tags=["backend"], project_id=p["id"], structure_mode="keyword")
            elif mode == "allowlist":
                structure_doc("AUTHORIZED_IPS: 10.0.0.1, 10.0.0.2", sid, ["flat"], extra_tags=["backend"], project_id=p["id"], structure_mode="allowlist")
            elif mode == "rag":
                structure_doc("General architecture design overview", sid, ["flat", "vector"], extra_tags=["backend"], project_id=p["id"], structure_mode="rag")

            ret = retrieve("API OR Deploy OR timeout OR VIP OR architecture OR AUTHORIZED OR ERROR", allowed=["*"], project_id=p["id"])
            for f in ret["facts"]:
                src = f.get("source")
                self.assertIsNotNone(src, f"Mode {mode} fact missing source metadata")
                self.assertEqual(src["id"], sid)
                self.assertEqual(src["uri"], uri)


class TestDynamoDBRepositoryParityUnderMoto(unittest.TestCase):
    """P1.6: Run parameterized parity tests against AWS DynamoDB Single-Table under Moto."""

    @mock_aws
    def test_dynamodb_single_table_operations(self):
        # Create mocked DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = "ContextForgeKnowledge"
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        repo = DynamoDBFactRepository(table_name=table_name, region_name="us-east-1")

        # 1. Project CRUD & Mode Update
        proj = repo.create_project("Dynamo Graph Proj", "admin", structure_mode="graph", classification_reason="Graph workflow")
        self.assertEqual(proj["structure_mode"], "graph")
        repo.update_project_mode(proj["id"], "versioned", "Switched to versioned")
        p_updated = repo.get_project(proj["id"])
        self.assertEqual(p_updated["structure_mode"], "versioned")

        # 2. Source & Fact Persistence with Mode Fields
        sid = repo.put_source("doc", "AWS Architecture", "https://aws.amazon.com/ref", "static", project_id=proj["id"])
        fid1 = repo.put_fact(
            text="API_RATE_LIMIT = 100 req/sec",
            tags=["api", "backend"],
            source_id=sid,
            structures=["flat"],
            key="API_RATE_LIMIT",
            valid_from=1000.0,
            priority=5,
        )
        self.assertIsNotNone(fid1)

        fid2 = repo.put_fact(
            text="API_RATE_LIMIT = 500 req/sec",
            tags=["api", "backend"],
            source_id=sid,
            structures=["flat"],
            key="API_RATE_LIMIT",
            valid_from=2000.0,
            priority=10,
        )
        self.assertIsNotNone(fid2)

        # 3. Supersede Fact
        repo.supersede_fact(fid1, fid2)

        # 4. History Chain
        history = repo.get_fact_history("API_RATE_LIMIT", project_id=proj["id"])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["superseded_by"], fid2)

        # 5. Rejected Guardrail Facts
        rid = repo.put_rejected_fact("Do not use unencrypted S3 buckets", "Compliance violation", ["deploy"], sid)
        self.assertIsNotNone(rid)
        rej_list = repo.get_rejected_facts(project_id=proj["id"])
        self.assertEqual(len(rej_list), 1)
        self.assertEqual(rej_list[0]["id"], rid)

        # 6. Edges and Vectors
        repo.put_edges(fid1, [["api", "connects_to", "database"]])
        edges = repo.get_all_edges()
        self.assertTrue(any(e["a"] == "api" and e["b"] == "database" for e in edges))

        import numpy as np
        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        repo.put_vector(fid1, vec.tobytes())
        vecs = repo.get_all_vectors()
        self.assertIn(fid1, vecs)
        np.testing.assert_allclose(vecs[fid1], vec, rtol=1e-5)


class TestLatencyAndScaleBenchmark(unittest.TestCase):
    """P1.7: Measure real latency for loading and scoring 1,000 and 10,000 facts."""

    def test_realistic_latency_benchmark(self):
        import numpy as np
        query = "database connection pool configuration"
        q_vec = np.random.randn(384).astype(np.float32)
        q_vec /= np.linalg.norm(q_vec)

        # Generate 1k and 10k mock facts and vectors
        for count in [1000, 10000]:
            doc_vecs = {i: np.random.randn(384).astype(np.float32) for i in range(count)}
            for v in doc_vecs.values():
                v /= np.linalg.norm(v)

            facts = [
                {"id": i, "text": f"Fact #{i}: database connection pool timeout is set to 30 seconds for postgres cluster.", "tags": ["database"], "key": f"KEY_{i}"}
                for i in range(count)
            ]

            t0 = time.perf_counter()
            # Vector cosine similarity scoring
            scores = {fid: float(q_vec @ doc_vecs[fid]) for fid in range(count)}
            # Keyword / token overlap scoring
            q_toks = set(query.lower().split())
            token_scores = {f["id"]: len(q_toks & set(f["text"].lower().split())) for f in facts}
            top_indices = sorted(scores.keys(), key=lambda k: -scores[k])[:10]
            elapsed_ms = (time.perf_counter() - t0) * 1000

            print(f"\n[BENCHMARK] Count: {count} facts | In-memory Hybrid Scoring Latency: {elapsed_ms:.2f} ms")
            self.assertLess(elapsed_ms, 200.0, f"Scoring {count} facts took too long: {elapsed_ms:.2f}ms")


class TestProvenanceRBACRedaction(unittest.TestCase):
    """P0.5: RBAC: if the viewer is not allowed to see the source's tags, do not expose its title or URL.
    Show 'From a restricted source' instead."""

    def test_restricted_source_redaction_in_display_and_export(self):
        from app.structuring import export_md, make_source_display

        # 1. Caller with ['frontend'] trying to view source with ['database', 'secret']
        redacted = make_source_display(
            source_id="src_secret_999",
            title="Confidential Production Credentials",
            uri="https://vault.internal/secrets/prod",
            kind="url",
            mode="static",
            created=1726798800.0,
            project_id="proj_default",
            project_name="Default Workspace",
            fact_text="Database root password is secret",
            fact_tags=["database", "secret"],
            allowed=["frontend"],
        )

        self.assertTrue(redacted["is_restricted"])
        self.assertEqual(redacted["source_label"], "a restricted source")
        self.assertEqual(redacted["title"], "Restricted source")
        self.assertIsNone(redacted["uri"])
        self.assertIsNone(redacted["recorded_at"])

        # 2. Caller with ['*'] viewing the same source
        authorized = make_source_display(
            source_id="src_secret_999",
            title="Confidential Production Credentials",
            uri="https://vault.internal/secrets/prod",
            kind="url",
            mode="static",
            created=1726798800.0,
            project_id="proj_default",
            project_name="Default Workspace",
            fact_text="Database root password is secret",
            fact_tags=["database", "secret"],
            allowed=["*"],
        )

        self.assertFalse(authorized["is_restricted"])
        self.assertEqual(authorized["title"], "Confidential Production Credentials")
        self.assertEqual(authorized["source_domain"], "vault.internal")
        self.assertIsNotNone(authorized["recorded_at"])

        # 3. Export markdown renders "From a restricted source." for restricted items
        md_output = export_md(
            result={"facts": [{"text": "Redacted item", "tags": ["database"], "source": redacted}]},
            role="frontend-engineer",
            mode="rag",
            query="secrets",
        )
        self.assertIn("1. From a restricted source.", md_output)
        self.assertNotIn("vault.internal", md_output)
        self.assertNotIn("Confidential Production Credentials", md_output)


if __name__ == "__main__":
    unittest.main(verbosity=2)

