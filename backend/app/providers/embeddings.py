"""Embedding Provider implementations: FastEmbed, Bedrock Titan, and Hashed fallback."""
import json
import os
import re
import zlib
from typing import Any

import numpy as np

from ..interfaces import EmbeddingProvider


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class HashedEmbeddingProvider(EmbeddingProvider):
    """Fallback zero-dependency embedding provider using CRC32 hashed bag-of-words."""

    def __init__(self, dim: int | None = None):
        self.dim = dim or int(os.getenv("EMBEDDING_DIM", "384"))

    def _hash_vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in _tok(text):
            v[zlib.crc32(w.encode()) % self.dim] += 1
        norm = np.linalg.norm(v) + 1e-9
        return v / norm

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._hash_vec(t) for t in texts]


class FastEmbedProvider(EmbeddingProvider):
    """Local embedding provider using fastembed BAAI/bge-small-en-v1.5."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None
        self._fallback = HashedEmbeddingProvider()

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(self.model_name)
            except Exception as e:
                print(f"fastembed unavailable ({e}), using hashed vectors fallback.")
                self._model = False
        return self._model

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        model = self._get_model()
        if model:
            try:
                vs = [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]
                return [v / (np.linalg.norm(v) + 1e-9) for v in vs]
            except Exception as e:
                print(f"Error during fastembed inference: {e}")
        return self._fallback.embed(texts)


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock Titan Text Embeddings provider."""

    def __init__(
        self,
        region_name: str | None = None,
        model_id: str | None = None,
    ):
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.model_id = model_id or os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
        self._client = None
        self._fallback = HashedEmbeddingProvider()

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
                    modelId=self.model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=body,
                )
                res_data = json.loads(response["body"].read().decode("utf-8"))
                v = np.asarray(res_data["embedding"], dtype=np.float32)
                norm = np.linalg.norm(v) + 1e-9
                out.append(v / norm)
            except Exception as e:
                print(f"Bedrock Titan embedding error for text ({e}), using fallback.")
                out.append(self._fallback.embed([text])[0])
        return out
