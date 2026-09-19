"""Embedding Provider implementations: FastEmbed, Bedrock Titan, Gemini, and Hashed fallback."""
import json
import logging
import os
import re
import time
import zlib
from typing import Any

import numpy as np
import requests

from ..interfaces import EmbeddingProvider

logger = logging.getLogger("contextforge.embeddings")


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class HashedEmbeddingProvider(EmbeddingProvider):
    """Fallback zero-dependency embedding provider using CRC32 hashed bag-of-words."""

    def __init__(self, dim: int | None = None):
        self.dimension = dim or int(os.getenv("EMBEDDING_DIM", "384"))
        self.model_name = "hashed"

    def _hash_vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dimension, dtype=np.float32)
        for w in _tok(text):
            v[zlib.crc32(w.encode()) % self.dimension] += 1
        norm = np.linalg.norm(v) + 1e-9
        return v / norm

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._hash_vec(t) for t in texts]

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._hash_vec(text)


class FastEmbedProvider(EmbeddingProvider):
    """Local embedding provider using fastembed BAAI/bge-small-en-v1.5."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self.dimension = 384
        self._model = None
        self._fallback = HashedEmbeddingProvider(dim=self.dimension)

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(self.model_name)
            except Exception as e:
                logger.warning(f"fastembed unavailable ({e}), using hashed vectors fallback.")
                self._model = False
        return self._model

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        model = self._get_model()
        if model:
            try:
                vs = [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]
                return [v / (np.linalg.norm(v) + 1e-9) for v in vs]
            except Exception as e:
                logger.warning(f"Error during fastembed inference: {e}")
        return self._fallback.embed(texts)

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock Titan Text Embeddings provider."""

    def __init__(
        self,
        region_name: str | None = None,
        model_id: str | None = None,
    ):
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.model_name = model_id or os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
        self.model_id = self.model_name
        self.dimension = 1536

        self._client = None
        self._fallback = HashedEmbeddingProvider(dim=self.dimension)

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region_name)
        return self._client

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        client = self._get_client()
        out: list[np.ndarray] = []
        for text in texts:
            try:
                body = json.dumps({"inputText": text})
                response = client.invoke_model(
                    modelId=self.model_name,
                    contentType="application/json",
                    accept="application/json",
                    body=body,
                )
                res_data = json.loads(response["body"].read().decode("utf-8"))
                v = np.asarray(res_data["embedding"], dtype=np.float32)
                norm = np.linalg.norm(v) + 1e-9
                out.append(v / norm)
            except Exception as e:
                logger.warning(f"Bedrock Titan embedding error for text ({e}), using fallback.")
                out.append(self._fallback.embed([text])[0])
        return out

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini Embedding Provider with task-type differentiation, dimensionality control, and retry backoff."""

    BATCH_SIZE = 100
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        dimension: int | None = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        raw_model = model_name or os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
        self.model_name = raw_model.removeprefix("models/")
        self.dimension = int(dimension or os.getenv("GEMINI_EMBED_DIM", "768"))

    def _normalize(self, vec: list[float] | np.ndarray) -> np.ndarray:
        v = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(v) + 1e-9
        return v / norm

    def _call_api_with_retry(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("GeminiEmbeddingProvider error: GEMINI_API_KEY is not set.")

        url = f"{self.BASE_URL}/models/{self.model_name}:{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    delay = 1.0 * (1.5 ** attempt)
                    if resp.status_code == 429:
                        try:
                            err_data = resp.json()
                            for d in err_data.get("error", {}).get("details", []):
                                if "retryDelay" in d:
                                    m = re.search(r"(\d+(\.\d+)?)", str(d["retryDelay"]))
                                    if m:
                                        delay = min(float(m.group(1)), 15.0)
                        except Exception:
                            pass
                    logger.warning(f"Gemini API returned {resp.status_code}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
                else:
                    raise RuntimeError(f"GeminiEmbeddingProvider error: HTTP {resp.status_code} - {resp.text}")
            except requests.RequestException as e:
                last_error = str(e)
                delay = 1.0 * (1.5 ** attempt)
                logger.warning(f"Gemini API request failed ({e}), retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)

        raise RuntimeError(f"GeminiEmbeddingProvider failed after {max_retries} retries: {last_error}")

    def embed_documents(self, texts: list[str]) -> list[np.ndarray]:
        """Embed document texts at ingest with taskType=RETRIEVAL_DOCUMENT and batching."""
        if not texts:
            return []

        results: list[np.ndarray] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            requests_list = [
                {
                    "model": f"models/{self.model_name}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                    "outputDimensionality": self.dimension,
                }
                for t in batch
            ]
            data = self._call_api_with_retry("batchEmbedContents", {"requests": requests_list})
            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(batch):
                raise RuntimeError(
                    f"GeminiEmbeddingProvider error: expected {len(batch)} embeddings, got {len(embeddings)}"
                )
            for emb in embeddings:
                results.append(self._normalize(emb["values"]))

        return results

    def embed_query(self, text: str) -> np.ndarray:
        """Embed search query with taskType=RETRIEVAL_QUERY."""
        payload = {
            "model": f"models/{self.model_name}",
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_QUERY",
            "outputDimensionality": self.dimension,
        }
        data = self._call_api_with_retry("embedContent", payload)
        emb = data.get("embedding", {})
        if "values" not in emb:
            raise RuntimeError(f"GeminiEmbeddingProvider error: unexpected response format: {data}")
        return self._normalize(emb["values"])

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Default batch embedding delegation to embed_documents."""
        return self.embed_documents(texts)
