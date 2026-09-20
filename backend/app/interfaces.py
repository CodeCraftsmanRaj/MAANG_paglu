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
    key: str | None = None
    condition: str | None = None
    outcome: str | None = None
    superseded_by: int | None = None
    valid_from: float | None = None
    valid_to: float | None = None
    priority: int = 0


class Ingestor(ABC):
    """Normalizes raw input (text, files, urls, etc.) into a NormalizedDocument."""

    @abstractmethod
    def normalize(self, raw_input: Any, **kwargs: Any) -> NormalizedDocument:
        """Parse raw content into normalized document structure."""
        ...


class LLMProvider(ABC):
    """Abstract interface for LLM operations (extraction, inference, Q&A, vision, classification)."""

    @abstractmethod
    def enabled(self) -> bool:
        """Returns True if the provider has necessary credentials and is active."""
        ...

    @abstractmethod
    def classify_structure_mode(self, project_name: str, sample_text: str = "") -> dict[str, str]:
        """Classify project structure mode ('graph','allowlist','denylist','keyword','keyvalue','ruleset','versioned','rag')."""
        ...

    @abstractmethod
    def extract_facts(self, text: str, is_process: bool = False, structure_mode: str = "rag") -> list[Fact]:
        """Extract atomic facts, tags, and structure-mode specific fields from text."""
        ...

    @abstractmethod
    def infer_needs(self, query: str) -> dict[str, str]:
        """Infer implicit context needs/tags for a user question."""
        ...

    @abstractmethod
    def answer(self, query: str, context: list[dict[str, Any]], is_process: bool = False, structure_mode: str = "rag") -> str:
        """Answer a query using only provided context formatted specifically for the active structure mode."""
        ...

    @abstractmethod
    def ocr(self, jpeg_b64: str) -> str:
        """Extract text from screenshot image base64."""
        ...


class EmbeddingProvider(ABC):
    """Abstract interface for vector embedding generation."""
    model_name: str = "unknown"
    dimension: int = 384

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Any]:
        """Generates normalized vector embeddings for a list of texts."""
        ...

    def embed_documents(self, texts: list[str]) -> list[Any]:
        """Generates normalized vector embeddings for document/fact storage (RETRIEVAL_DOCUMENT)."""
        return self.embed(texts)

    def embed_query(self, text: str) -> Any:
        """Generates normalized vector embedding for a search query (RETRIEVAL_QUERY)."""
        return self.embed([text])[0]



class FactRepository(ABC):
    """Persistence interface for projects, sources, facts, vector embeddings, and graph relations."""

    @abstractmethod
    def create_project(
        self,
        name: str,
        created_by: str,
        project_type: str = "general",
        structure_mode: str = "rag",
        classification_reason: str | None = None,
        members: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new project."""
        ...

    @abstractmethod
    def update_project_mode(self, project_id: str, structure_mode: str, reason: str | None = None) -> dict[str, Any] | None:
        """Update structure mode and reasoning for project."""
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
        key: str | None = None,
        condition: str | None = None,
        outcome: str | None = None,
        superseded_by: int | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
        priority: int = 0,
    ) -> int | None:
        """Insert fact with provenance. Returns fact_id or None if duplicate."""
        ...

    @abstractmethod
    def supersede_fact(self, old_fact_id: int, new_fact_id: int) -> None:
        """Mark old fact as superseded by new fact."""
        ...

    @abstractmethod
    def get_all_facts_with_sources(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all facts joined with their source metadata."""
        ...

    @abstractmethod
    def put_rejected_fact(self, text: str, reason: str, tags: list[str], source_id: str) -> int:
        """Save rejected guardrail item."""
        ...

    @abstractmethod
    def get_rejected_facts(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch all rejected guardrail facts for project."""
        ...

    @abstractmethod
    def get_fact_history(self, fact_id_or_key: str | int, project_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch version history chain for a fact or canonical key."""
        ...

    @abstractmethod
    def put_vector(self, fact_id: int, vector_bytes: bytes, model_name: str | None = None, dim: int | None = None) -> None:
        """Save vector blob with model_name and dimension for fact."""
        ...

    @abstractmethod
    def get_all_vectors(self, model_name: str | None = None, dim: int | None = None) -> dict[int, Any]:
        """Return mapping of fact_id to numpy vector array matching model and dim if provided."""
        ...


    @abstractmethod
    def put_edges(self, fact_id: int, rels: list[list[str]]) -> None:
        """Save graph relation edges for fact."""
        ...

    @abstractmethod
    def get_all_edges(self) -> list[dict[str, Any]]:
        """Fetch all graph edges."""
        ...

    # ----- accounts, tokens & roles (deployable backends must not rely on local SQLite) -----
    # Default implementations raise NotImplementedError; SQLite and DynamoDB repositories override them.

    def create_user(self, username: str, pw: str, role: str) -> None:
        """Store a user with a pre-hashed password and an assigned role."""
        raise NotImplementedError

    def get_user(self, username: str) -> dict[str, Any] | None:
        """Return {username, pw, role} for a user, or None."""
        raise NotImplementedError

    def has_any_user(self) -> bool:
        """True if at least one user is registered (first user becomes admin)."""
        raise NotImplementedError

    def list_users(self) -> list[dict[str, Any]]:
        """Return [{username, role}] for every registered user."""
        raise NotImplementedError

    def update_user_role(self, username: str, role: str) -> None:
        """Assign a role to a user."""
        raise NotImplementedError

    def create_token(self, token: str, username: str) -> None:
        """Issue a bearer token for a user."""
        raise NotImplementedError

    def get_token_user(self, token: str) -> dict[str, Any] | None:
        """Resolve a bearer token to {username, role}, or None if invalid."""
        raise NotImplementedError

    def list_roles(self) -> list[dict[str, Any]]:
        """Return [{name, tags(list[str])}] for every role, sorted by name."""
        raise NotImplementedError

    def get_role_tags(self, name: str) -> list[str] | None:
        """Return the tag list for a role, or None if the role does not exist."""
        raise NotImplementedError

    def upsert_role(self, name: str, tags: list[str]) -> None:
        """Create or replace a role and its tags."""
        raise NotImplementedError

    def role_exists(self, name: str) -> bool:
        """True if the role name is registered."""
        raise NotImplementedError

    def all_fact_tags(self) -> set[str]:
        """Union of tags across all facts (used for tag-taxonomy validation)."""
        raise NotImplementedError

    def get_source_detail(self, source_id: str) -> dict[str, Any] | None:
        """Return a source row enriched with project_name, or None."""
        raise NotImplementedError

    def get_source_project_id(self, source_id: str) -> str | None:
        """Return the project_id a source belongs to, or None."""
        raise NotImplementedError


