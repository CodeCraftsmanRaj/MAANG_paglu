"""Provider factory for env/config-driven dependency injection."""
import os
from functools import lru_cache

from .interfaces import EmbeddingProvider, FactRepository, Ingestor, LLMProvider
from .providers.embeddings import (
    BedrockEmbeddingProvider,
    FastEmbedProvider,
    GeminiEmbeddingProvider,
    HashedEmbeddingProvider,
)
from .providers.ingestors import TextIngestor, URLIngestor
from .providers.llm import BedrockLLMProvider, GeminiLLMProvider, GroqLLMProvider
from .providers.repository import DynamoDBFactRepository, SQLiteFactRepository


@lru_cache(maxsize=1)
def get_fact_repository() -> FactRepository:
    provider = os.getenv("DB_PROVIDER", "sqlite").lower()
    if provider == "sqlite":
        return SQLiteFactRepository()
    elif provider == "dynamodb":
        return DynamoDBFactRepository()
    raise ValueError(f"Unknown DB_PROVIDER: {provider}. Supported: ['sqlite', 'dynamodb']")


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        return GroqLLMProvider()
    elif provider == "gemini":
        return GeminiLLMProvider()
    elif provider == "bedrock":
        return BedrockLLMProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Supported: ['groq', 'gemini', 'bedrock']")


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "fastembed").lower()
    if provider == "fastembed":
        return FastEmbedProvider()
    elif provider == "gemini":
        return GeminiEmbeddingProvider()
    elif provider == "bedrock":
        return BedrockEmbeddingProvider()
    elif provider == "hashed":
        return HashedEmbeddingProvider()
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}. Supported: ['fastembed', 'gemini', 'bedrock', 'hashed']")


_INGESTORS: dict[str, Ingestor] = {
    "text": TextIngestor(),
    "url": URLIngestor(),
}


def get_ingestor(kind: str) -> Ingestor:
    if kind not in _INGESTORS:
        raise ValueError(f"No Ingestor registered for kind '{kind}'. Available: {list(_INGESTORS)}")
    return _INGESTORS[kind]
