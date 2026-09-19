"""Core interfaces and domain models for ContextForge."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedDocument:
    """Standardized representation of ingested raw content."""
    text: str
    title: str
    source_kind: str
    source_uri: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fact:
    """Atomic unit of extracted knowledge."""
    text: str
    tags: list[str] = field(default_factory=list)
    rels: list[list[str]] = field(default_factory=list)
    id: int | None = None
    source_id: str | None = None
    source: dict[str, Any] | None = None
    via: list[str] = field(default_factory=list)
    score: float = 0.0
    action: str | None = None
    owner: str | None = None
    depends_on: str | None = None


class Ingestor(ABC):
    """Normalizes raw input (text, files, urls, etc.) into a NormalizedDocument."""

    @abstractmethod
    def normalize(self, raw_input: Any, **kwargs: Any) -> NormalizedDocument:
        """Parse raw content into normalized document structure."""
        ...


class LLMProvider(ABC):
    """Abstract interface for LLM operations (extraction, inference, Q&A, vision)."""

    @abstractmethod
    def enabled(self) -> bool:
        """Returns True if the provider has necessary credentials and is active."""
        ...

    @abstractmethod
    def extract_facts(self, text: str, is_process: bool = False) -> list[Fact]:
        """Extract atomic facts, tags, and entity relation triples from text."""
        ...

    @abstractmethod
    def infer_needs(self, query: str) -> dict[str, str]:
        """Infer implicit context needs/tags for a user question."""
        ...

    @abstractmethod
    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False) -> str:
        """Answer a query using only provided context with citations."""
        ...

    @abstractmethod
    def ocr(self, jpeg_b64: str) -> str:
        """Extract text from screenshot image base64."""
        ...


class EmbeddingProvider(ABC):
    """Abstract interface for vector embedding generation."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Any]:
        """Generates normalized vector embeddings for a list of texts."""
        ...


class FactRepository(ABC):
    """Persistence interface for projects, sources, facts, vector embeddings, and graph relations."""

    @abstractmethod
    def create_project(self, name: str, created_by: str, project_type: str = "general") -> dict[str, Any]:
        """Create a new project."""
        ...

    @abstractmethod
    def get_projects(self, username: str | None = None) -> list[dict[str, Any]]:
        """List accessible projects."""
        ...

    @abstractmethod
    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Retrieve project by ID."""
        ...

    @abstractmethod
    def put_source(self, kind: str, title: str, uri: str | None, mode: str, project_id: str = "proj_default") -> str:
        """Insert a source record and return the source id."""
        ...

    @abstractmethod
    def get_source_by_uri(self, uri: str, project_id: str | None = None) -> dict[str, Any] | None:
        """Retrieve existing source metadata by URI."""
        ...

    @abstractmethod
    def source_exists(self, source_id: str, mode: str | None = None) -> bool:
        """Check if source exists, optionally matching mode."""
        ...

    @abstractmethod
    def fact_exists_by_text(self, text: str, source_id: str | None = None) -> bool:
        """Check if identical fact text already exists."""
        ...

    @abstractmethod
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
        """Insert fact with provenance. Returns fact_id or None if duplicate."""
        ...

    @abstractmethod
    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all facts joined with their source metadata."""
        ...

    @abstractmethod
    def put_vector(self, fact_id: int, vector_bytes: bytes) -> None:
        """Save vector blob for fact."""
        ...

    @abstractmethod
    def get_all_vectors(self) -> dict[int, Any]:
        """Return mapping of fact_id to numpy vector array."""
        ...

    @abstractmethod
    def put_edges(self, fact_id: int, rels: list[list[str]]) -> None:
        """Save graph relation edges for fact."""
        ...

    @abstractmethod
    def get_all_edges(self) -> list[dict[str, Any]]:
        """Fetch all graph edges."""
        ...

