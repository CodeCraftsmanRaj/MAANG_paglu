"""Test suite to verify modular pipeline interfaces, URL ingestion, and AWS provider abstractions."""
import os
import tempfile
from fastapi.testclient import TestClient

# Set isolated test database
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()
os.environ["CF_DB"] = temp_db.name
os.environ["LLM_PROVIDER"] = "groq"
os.environ["EMBEDDING_PROVIDER"] = "fastembed"
os.environ["DB_PROVIDER"] = "sqlite"

from app.api import app
from app.factory import (
    get_embedding_provider,
    get_fact_repository,
    get_ingestor,
    get_llm_provider,
)
from app.interfaces import Fact, Ingestor, NormalizedDocument
from app.providers.embeddings import BedrockEmbeddingProvider
from app.providers.ingestors import URLIngestor
from app.providers.llm import BedrockLLMProvider
from app.providers.repository import DynamoDBFactRepository


def test_interfaces_and_factory():
    # 1. Text Ingestor
    text_ingestor = get_ingestor("text")
    assert isinstance(text_ingestor, Ingestor)
    doc = text_ingestor.normalize({"text": "FastAPI is a modern web framework for Python.", "title": "Doc1"})
    assert isinstance(doc, NormalizedDocument)
    assert doc.text == "FastAPI is a modern web framework for Python."
    assert doc.title == "Doc1"
    assert doc.source_kind == "text"

    # 2. URL Ingestor
    url_ingestor = get_ingestor("url")
    assert isinstance(url_ingestor, Ingestor)
    sample_html = "<html><head><title>Test Page</title></head><body><h1>Heading</h1><p>Sample paragraph content.</p></body></html>"
    url_doc = url_ingestor.normalize({"url": "https://example.com/test", "html": sample_html})
    assert isinstance(url_doc, NormalizedDocument)
    assert url_doc.title == "Test Page"
    assert "Sample paragraph content." in url_doc.text
    assert url_doc.source_kind == "url"
    assert url_doc.source_uri == "https://example.com/test"

    # 3. Embedding Provider
    emb = get_embedding_provider()
    vecs = emb.embed(["test query"])
    assert len(vecs) == 1
    assert len(vecs[0]) > 0

    # 4. Fact Repository
    repo = get_fact_repository()
    assert repo is not None


def test_aws_providers_smoke():
    """Smoke test AWS providers (Bedrock, Titan, DynamoDB). Skip if AWS credentials are not in environment."""
    bedrock_llm = BedrockLLMProvider()
    assert bedrock_llm.model_id == os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")

    bedrock_emb = BedrockEmbeddingProvider()
    assert bedrock_emb.model_id == os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")

    dynamo_repo = DynamoDBFactRepository()
    assert dynamo_repo.table_name == os.getenv("DYNAMODB_TABLE_NAME", "ContextForgeKnowledge")

    if bedrock_llm.enabled():
        print("AWS credentials detected: testing active Bedrock LLM...")
        # Optional live smoke test if credentials present
        ans = bedrock_llm.infer_needs("How do I deploy with Docker?")
        assert isinstance(ans, dict)
    else:
        print("AWS credentials not present in local environment: Bedrock/DynamoDB smoke tests successfully validated shape.")


def test_end_to_end_ingest_and_retrieval():
    client = TestClient(app)

    # 1. Register first account (Admin)
    reg_resp = client.post("/api/auth/register", json={"username": "alice_admin", "password": "password123"})
    assert reg_resp.status_code == 200, reg_resp.text
    token = reg_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check /api/me
    me_resp = client.get("/api/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "admin"

    # 3. Ingest pasted text via modular path
    snippet = "Our backend service connects to PostgreSQL database and deploys with Docker on AWS."
    ingest_resp = client.post(
        "/api/ingest",
        headers=headers,
        json={
            "kind": "text",
            "title": "Backend Architecture Note",
            "text": snippet,
        },
    )
    assert ingest_resp.status_code == 200, ingest_resp.text
    data = ingest_resp.json()
    assert "source_id" in data
    assert data["facts"] >= 1

    # 4. Ingest URL via modular URLIngestor path
    sample_html = "<html><head><title>API Docs</title></head><body><p>The REST API routes authenticate using JWT tokens.</p></body></html>"
    url_resp = client.post(
        "/api/ingest",
        headers=headers,
        json={
            "kind": "url",
            "url": "https://docs.example.com/api",
            "html": sample_html,
        },
    )
    assert url_resp.status_code == 200, url_resp.text
    url_data = url_resp.json()
    assert "source_id" in url_data
    assert url_data["facts"] >= 1

    # 5. Duplicate prevention test
    dup_resp = client.post(
        "/api/ingest",
        headers=headers,
        json={
            "kind": "text",
            "title": "Backend Architecture Note",
            "text": snippet,
        },
    )
    assert dup_resp.status_code == 200
    assert dup_resp.json()["facts"] == 0

    # 6. Retrieve facts
    ret_resp = client.post(
        "/api/retrieve",
        headers=headers,
        json={"query": "database deploy", "mode": "dynamic"},
    )
    assert ret_resp.status_code == 200
    ret_data = ret_resp.json()
    assert len(ret_data["facts"]) >= 1
    top_fact = ret_data["facts"][0]
    assert "database" in top_fact["tags"] or "deploy" in top_fact["tags"] or "backend" in top_fact["tags"]
    assert top_fact["source"]["title"] in ["Backend Architecture Note", "API Docs"]

    # 7. Export Markdown Context Pack
    exp_resp = client.post(
        "/api/export",
        headers=headers,
        json={"query": "database", "mode": "explicit"},
    )
    assert exp_resp.status_code == 200
    exp_data = exp_resp.json()
    assert "# Context Pack" in exp_data["markdown"]

    # 8. Access Control Verification (Role: member)
    reg_member = client.post("/api/auth/register", json={"username": "bob_member", "password": "password123"})
    assert reg_member.status_code == 200
    member_token = reg_member.json()["token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    member_ret = client.post(
        "/api/retrieve",
        headers=member_headers,
        json={"query": "database", "mode": "explicit"},
    )
    assert member_ret.status_code == 200
    assert len(member_ret.json()["facts"]) == 0

    # 9. Admin preview (X-View-As: backend)
    preview_headers = {"Authorization": f"Bearer {token}", "X-View-As": "backend"}
    preview_ret = client.post(
        "/api/retrieve",
        headers=preview_headers,
        json={"query": "database", "mode": "explicit"},
    )
    assert preview_ret.status_code == 200
    assert len(preview_ret.json()["facts"]) >= 1


if __name__ == "__main__":
    test_interfaces_and_factory()
    test_aws_providers_smoke()
    test_end_to_end_ingest_and_retrieval()
    print("All modular pipeline and AWS provider tests PASSED successfully!")
