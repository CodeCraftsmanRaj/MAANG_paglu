"""Unit and integration test suite for Gemini EmbeddingProvider and Vector-Space Guard."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv(".env")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))


from app.interfaces import EmbeddingProvider
from app.providers.embeddings import GeminiEmbeddingProvider, HashedEmbeddingProvider
from app.providers.repository import SQLiteFactRepository
from app.structuring import VectorStore, retrieve


class TestGeminiEmbeddingProviderMocked(unittest.TestCase):
    """Requirement 8.1: Unit test with mocked HTTP calls for task type, batching, retry, and normalization."""

    def setUp(self):
        self.provider = GeminiEmbeddingProvider(
            api_key="test_mock_gemini_api_key",
            model_name="gemini-embedding-001",
            dimension=768,
        )

    @patch("requests.post")
    def test_task_type_and_normalization(self, mock_post):
        # Unnormalized mock embedding vector of magnitude != 1.0
        raw_vec = [2.0] * 768
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": [{"values": raw_vec}]
        }
        mock_post.return_value = mock_response

        # 1. Test embed_documents uses RETRIEVAL_DOCUMENT
        docs = ["Postgres configuration note"]
        vectors = self.provider.embed_documents(docs)

        self.assertEqual(len(vectors), 1)
        self.assertEqual(len(vectors[0]), 768)
        # Verify L2 normalization: norm must equal 1.0
        norm = np.linalg.norm(vectors[0])
        self.assertAlmostEqual(norm, 1.0, places=5)

        # Verify taskType in request payload
        called_payload = mock_post.call_args[1]["json"]
        self.assertEqual(called_payload["requests"][0]["taskType"], "RETRIEVAL_DOCUMENT")
        self.assertEqual(called_payload["requests"][0]["outputDimensionality"], 768)

        # 2. Test embed_query uses RETRIEVAL_QUERY
        mock_query_resp = MagicMock()
        mock_query_resp.status_code = 200
        mock_query_resp.json.return_value = {
            "embedding": {"values": raw_vec}
        }
        mock_post.return_value = mock_query_resp

        q_vec = self.provider.embed_query("search query")
        self.assertEqual(len(q_vec), 768)
        self.assertAlmostEqual(np.linalg.norm(q_vec), 1.0, places=5)

        called_query_payload = mock_post.call_args[1]["json"]
        self.assertEqual(called_query_payload["taskType"], "RETRIEVAL_QUERY")
        self.assertEqual(called_query_payload["outputDimensionality"], 768)

    @patch("requests.post")
    def test_batching_over_100_items(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200

        def side_effect(url, json, headers, timeout):
            req_count = len(json.get("requests", []))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "embeddings": [{"values": [0.1] * 768} for _ in range(req_count)]
            }
            return resp

        mock_post.side_effect = side_effect

        # 250 items should produce 3 batches: 100, 100, 50
        texts = [f"Text item #{i}" for i in range(250)]
        results = self.provider.embed_documents(texts)

        self.assertEqual(len(results), 250)
        self.assertEqual(mock_post.call_count, 3)
        batch1_len = len(mock_post.call_args_list[0][1]["json"]["requests"])
        batch2_len = len(mock_post.call_args_list[1][1]["json"]["requests"])
        batch3_len = len(mock_post.call_args_list[2][1]["json"]["requests"])
        self.assertEqual(batch1_len, 100)
        self.assertEqual(batch2_len, 100)
        self.assertEqual(batch3_len, 50)

    @patch("time.sleep", return_value=None)
    @patch("requests.post")
    def test_retry_exponential_backoff_on_429_and_5xx(self, mock_post, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Too Many Requests"

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.text = "Internal Server Error"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "embedding": {"values": [0.1] * 768}
        }

        # First 429, then 500, then 200 success
        mock_post.side_effect = [resp_429, resp_500, resp_200]

        v = self.provider.embed_query("test query")
        self.assertEqual(len(v), 768)
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep", return_value=None)
    @patch("requests.post")
    def test_failure_raises_clear_error_without_silent_fallback(self, mock_post, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Quota exceeded"

        mock_post.return_value = resp_429

        with self.assertRaises(RuntimeError) as ctx:
            self.provider.embed_query("failing query")

        self.assertIn("GeminiEmbeddingProvider", str(ctx.exception))
        self.assertIn("failed after 3 retries", str(ctx.exception))


class TestVectorSpaceGuard(unittest.TestCase):
    """Requirement 8.2 & 5: Guard test: vectors from model A are never scored against a query embedded by model B."""

    def setUp(self):
        self.repo = SQLiteFactRepository()
        self.store = VectorStore()

    def test_model_mismatch_prevents_corrupted_scoring_and_warns(self):
        from app.db import run

        # Clean up any existing test records
        proj_id = "proj_vector_guard_test"
        run("DELETE FROM vecs WHERE fact_id IN (SELECT f.id FROM facts f JOIN sources s ON s.id = f.source_id WHERE s.project_id=?)", (proj_id,))
        run("DELETE FROM facts WHERE source_id IN (SELECT id FROM sources WHERE project_id=?)", (proj_id,))
        run("DELETE FROM sources WHERE project_id=?", (proj_id,))
        run("DELETE FROM projects WHERE id=?", (proj_id,))

        # Create isolated test project and source
        run("INSERT OR REPLACE INTO projects (id, name, created_by, created_at, project_type, structure_mode) VALUES (?, ?, ?, ?, ?, ?)",
            (proj_id, "Guard Test Project", "system", 0.0, "general", "rag"))
        run("INSERT OR REPLACE INTO sources (id, kind, title, mode, project_id) VALUES (?, ?, ?, ?, ?)",
            ("src_guard_1", "text", "Guard Note", "static", proj_id))


        # Insert fact
        fid = self.repo.put_fact(
            text="Relational database connection parameters for billing postgres cluster.",
            tags=["database"],
            source_id="src_guard_1",
            structures=["vector", "flat"],
        )

        # Store vector as Model A (384d, BAAI/bge-small-en-v1.5)
        vec_384 = np.random.randn(384).astype(np.float32)
        vec_384 /= np.linalg.norm(vec_384)
        self.repo.put_vector(fid, vec_384.tobytes(), model_name="BAAI/bge-small-en-v1.5", dim=384)

        # Set active embedding provider to Model B (768d, Gemini)
        mock_gemini = GeminiEmbeddingProvider(api_key="mock_key", model_name="gemini-embedding-001", dimension=768)
        mock_gemini.embed_query = MagicMock(return_value=np.random.randn(768).astype(np.float32))

        with patch("app.structuring.get_embedding_provider", return_value=mock_gemini):
            with patch("app.factory.get_embedding_provider", return_value=mock_gemini):
                # 1. VectorStore.prepare: should return EMPTY vectors for Model B because stored vector is Model A
                q_vec, loaded_vecs = self.store.prepare("database config")
                self.assertEqual(len(q_vec), 768)
                self.assertNotIn(fid, loaded_vecs, "384d vector from Model A must not be loaded for 768d Model B query")

                # 2. retrieve(): should include vector mismatch warning
                ret_res = retrieve(
                    query="database config",
                    allowed=["*"],
                    project_id=proj_id,
                )
                warnings = [w.get("warning", "") for w in ret_res.get("warnings", [])]
                self.assertTrue(
                    any("Project was embedded with BAAI/bge-small-en-v1.5" in w for w in warnings),
                    f"Expected vector space mismatch warning, got: {warnings}",
                )

                # 3. Re-embed project facts using current provider (768d)
                mock_gemini.embed_documents = MagicMock(return_value=[np.random.randn(768).astype(np.float32)])
                from app.api import reembed_project
                reembed_res = reembed_project(proj_id, c={"user": "admin", "role": "admin", "allowed": ["*"]})
                self.assertTrue(reembed_res["ok"])
                self.assertEqual(reembed_res["model"], "gemini-embedding-001")
                self.assertEqual(reembed_res["dim"], 768)

                # Now prepare() loads the re-embedded 768d vector
                q_vec2, loaded_vecs2 = self.store.prepare("database config")
                self.assertIn(fid, loaded_vecs2)
                self.assertEqual(len(loaded_vecs2[fid]), 768)


class TestGeminiLiveSmokeTest(unittest.TestCase):
    """Requirement 8.3: Live smoke test, skipped unless GEMINI_API_KEY is set in environment."""

    def test_live_gemini_embeddings(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise unittest.SkipTest("Skipping live smoke test: GEMINI_API_KEY is not set.")

        dim = int(os.getenv("GEMINI_EMBED_DIM", "768"))
        model = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
        provider = GeminiEmbeddingProvider(api_key=api_key, model_name=model, dimension=dim)

        text_db1 = "PostgreSQL relational database connection pool configuration and connection limits."
        text_db2 = "Database query performance, index optimization, and SQL execution plans."
        text_css = "Frontend CSS styles for button hover effects and modal transitions."

        docs = [text_db1, text_db2, text_css]
        vectors = provider.embed_documents(docs)

        # 1. Assert correct count and dimension
        self.assertEqual(len(vectors), 3)
        for v in vectors:
            self.assertEqual(len(v), dim)
            # Normalized length == 1.0
            self.assertAlmostEqual(np.linalg.norm(v), 1.0, places=4)

        # 2. Query embedding with RETRIEVAL_QUERY
        q_vec = provider.embed_query("How do I tune postgres database connections?")
        self.assertEqual(len(q_vec), dim)
        self.assertAlmostEqual(np.linalg.norm(q_vec), 1.0, places=4)

        # 3. Assert semantic similarity: related database pairs score higher than unrelated CSS pair
        score_db1 = float(q_vec @ vectors[0])
        score_db2 = float(q_vec @ vectors[1])
        score_css = float(q_vec @ vectors[2])

        print(f"\n[LIVE SMOKE TEST SCORES] DB1: {score_db1:.4f} | DB2: {score_db2:.4f} | CSS: {score_css:.4f}")
        self.assertGreater(score_db1, score_css, "Database query should score higher on database text than on CSS text")
        self.assertGreater(score_db2, score_css, "Database query should score higher on database text than on CSS text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
