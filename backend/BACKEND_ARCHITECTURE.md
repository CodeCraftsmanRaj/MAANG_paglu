# ContextForge Backend Architecture & Logic Reference

A complete, exhaustive technical reference for the ContextForge backend engine, covering architecture, data models, 8 dynamic retrieval paradigms, RBAC security semantics, vector-space compatibility guards, pluggable provider ecosystems, and API endpoints.

---

## 1. High-Level Architecture Overview

ContextForge is a knowledge plane engineered with cryptographic provenance, tag-based role access control (RBAC), multi-project scoping, and 8 dynamic retrieval modes.

```mermaid
graph TD
    Client["Frontend UI (Ledger Design) / API Clients"] --> API["FastAPI Application Layer (api.py)"]
    
    subgraph Security & Access Control
        API --> Auth["Authentication & RBAC (auth.py)"]
        Auth --> SingleVis["Single Visibility Function: is_visible(tags, allowed)"]
        Auth --> ProjectGuard["Project Scoping: can_access_project(user, role, project)"]
    end
    
    subgraph Ingestion & Structuring Pipeline
        API --> Ingest["Ingestion Subsystem (ingestion.py)"]
        Ingest --> Structuring["Extraction & Normalization (structuring.py)"]
        Structuring --> Modes["8 Structure Modes & Strategies (strategies.py)"]
    end

    subgraph Pluggable Storage & Multi-Index Engine
        Structuring --> FlatStore["FlatStore (Keyword / Token Overlap)"]
        Structuring --> VectorStore["VectorStore (Cosine Similarity + Space Guard + Batching)"]
        Structuring --> GraphStore["GraphStore (NetworkX Relational Edges + RBAC Walk)"]
    end

    subgraph Storage Repositories
        FlatStore --> Repo["FactRepository (repository.py)"]
        VectorStore --> Repo
        GraphStore --> Repo
        Repo --> SQLite["SQLite Database (db.py)"]
        Repo --> DynamoDB["AWS DynamoDB Single-Table"]
    end

    subgraph Pluggable AI Providers (factory.py)
        Structuring --> LLMProv["LLMProvider (Gemini / Groq / Bedrock / Heuristic)"]
        Structuring --> EmbedProv["EmbeddingProvider (Gemini / FastEmbed / Bedrock / Hashed)"]
    end
```

---

## 2. Directory & Module Map

| File Path | Core Responsibility | Key Components |
| :--- | :--- | :--- |
| **`app/interfaces.py`** | Abstract base classes (ABCs) and dataclasses | `NormalizedDocument`, `Fact`, `Ingestor`, `LLMProvider`, `EmbeddingProvider`, `FactRepository` |
| **`app/factory.py`** | Environment-driven dependency injection container | `get_fact_repository()`, `get_llm_provider()`, `get_embedding_provider()`, `get_ingestor()` |
| **`app/auth.py`** | Authentication, password hashing, and RBAC visibility | `is_visible()`, `can_access_project()`, `login()`, `register()`, `current()`, `require_admin()` |
| **`app/db.py`** | SQLite connection, table schemas, automatic migrations & admin seeding | SQLite tables (`projects`, `sources`, `facts`, `rejected_facts`, `vecs`, `edges`, `roles`, `users`, `tokens`) |
| **`app/providers/repository.py`** | Storage repository implementations | `SQLiteFactRepository`, `DynamoDBFactRepository` |
| **`app/providers/embeddings.py`** | Vector embedding providers with batching & retry backoff | `GeminiEmbeddingProvider`, `FastEmbedProvider`, `BedrockEmbeddingProvider`, `HashedEmbeddingProvider` |
| **`app/providers/llm.py`** | LLM text extraction, classification, Q&A, and OCR | `GeminiLLMProvider`, `GroqLLMProvider`, `BedrockLLMProvider`, heuristic fallbacks |
| **`app/providers/ingestors.py`** | Content intake and normalization | `TextIngestor`, `URLIngestor` |
| **`app/strategies.py`** | Implementation of all 8 dynamic retrieval paradigms | `RagStrategy`, `RulesetStrategy`, `KeyvalueStrategy`, `DenylistStrategy`, `VersionedStrategy`, `GraphStrategy`, `AllowlistStrategy`, `KeywordStrategy` |
| **`app/structuring.py`** | Hybrid indexing, scoring, search, provenance, and pack export | `FlatStore`, `VectorStore`, `GraphStore`, `search_facts()`, `retrieve()`, `make_source_display()`, `export_md()` |
| **`app/ingestion.py`** | Ingestion pipeline orchestration and directory watcher | `normalize()`, `watch()`, `source_for_uri()`, `INGESTORS` |
| **`app/api.py`** | FastAPI routing and REST endpoint controllers | All `/api/*` HTTP routes |
| **`main.py`** | Application bootstrap and Uvicorn server launcher | `uvicorn.run("app.api:app")` |

---

## 3. Configuration, Environment Variables & Git Hygiene

### A. Environment Configuration Matrix

| Variable | Allowed Values | Default | Description |
| :--- | :--- | :--- | :--- |
| `CF_DB` | File path string | `contextforge2.db` | Local SQLite database file location. |
| `REPO_PROVIDER` | `sqlite`, `dynamodb` | `sqlite` | Selects backend persistence layer. |
| `EMBEDDING_PROVIDER` | `gemini`, `fastembed`, `bedrock`, `hashed` | `gemini` | Active embedding vector provider. |
| `GEMINI_API_KEY` | String (AI Studio) | `None` | Google Gemini API key. |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | `gemini-embedding-001` | Google Gemini embedding model. |
| `GEMINI_EMBED_DIM` | `768`, `1536`, `3072` | `768` | Output vector dimension ($L_2$ normalized). |
| `GEMINI_LLM_MODEL` | `gemini-2.5-flash` | `gemini-2.5-flash` | Google Gemini LLM generation model. |
| `LLM_PROVIDER` | `gemini`, `groq`, `bedrock`, `heuristic` | `gemini` | Generative LLM for extraction, Q&A, and OCR. |
| `GROQ_API_KEY` | String (`gsk_...`) | `None` | Groq Cloud API key. |
| `GROQ_MODEL` | String | `qwen/qwen3.8-27b` | Groq active model (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, `groq/compound`). |
| `GROQ_VISION_MODEL` | String | `meta-llama/llama-4-scout-17b-16e-instruct` | Groq vision model for screenshot OCR. |
| `AWS_REGION` | AWS region string | `us-east-1` | AWS region for Bedrock & DynamoDB. |
| `DYNAMODB_TABLE` | String | `contextforge` | AWS DynamoDB single-table name. |
| `BEDROCK_EMBEDDING_MODEL_ID`| String | `amazon.titan-embed-text-v1`| Bedrock embedding model (1536 dimensions). |
| `BEDROCK_MODEL_ID` | String | `anthropic.claude-3-5-sonnet-20240620-v1:0`| Bedrock Claude generation model. |

### B. Environment Templates & Git Hygiene
- `.gitignore` enforces recursive ignore rules (`**/.env*`, `**/.env.*`, `*.env*`) to guarantee that private API keys and environment files are **never committed**.
- Clean template files are whitelisted and tracked for easy onboarding:
  - [`backend/.env.local.example`](file:///c:/Users/SHIVSHARN/Documents/RAJ/MAANG_paglu/backend/.env.local.example) — Local dev template (Gemini / Groq / SQLite).
  - [`backend/.env.production.example`](file:///c:/Users/SHIVSHARN/Documents/RAJ/MAANG_paglu/backend/.env.production.example) — Cloud production template (Bedrock / DynamoDB).
  - [`backend/.env.example`](file:///c:/Users/SHIVSHARN/Documents/RAJ/MAANG_paglu/backend/.env.example) — Comprehensive general template.

---

## 4. Multi-Index Coexistence & Orthogonal RBAC

A fundamental architectural principle in ContextForge is the clear separation between **Storage Multi-Indexing**, **Orthogonal Security Scoping**, and **Strategy Output Formatting**.

```
                        ┌───► vecs table & VectorStore (Dense Embeddings)
                        │
Incoming Ingested Fact  ├───► FlatStore (Literal Token & Key Index)
                        │
                        ├───► edges table & GraphStore (Entity Relational DAG)
                        │
                        └───► Structured Columns (action, owner, key, condition, tags)
```

### 1. Simultaneous Storage Multi-Indexing
When data is ingested, ContextForge does **not** choose only one index. It writes to all indexes concurrently:
- **`vecs` & `VectorStore`**: Dense float embeddings for semantic cosine similarity.
- **`FlatStore`**: Tokenized keyword sets for exact identifier and code lookup.
- **`edges` & `GraphStore`**: Entity relational triplets $(a, \text{rel}, b)$ for 2-hop topological traversal.
- **Relational Columns**: `action`, `owner`, `depends_on`, `key`, `condition`, `outcome`, `valid_from`, and `priority`.

### 2. Orthogonal Allowlist & RBAC Enforcement (Active in ALL Modes)
Allowlists and RBAC tags are **never disabled** by any mode:
- Every fact carries a tag array (`tags`).
- The **Single Global Visibility Function** (`is_visible(fact.tags, caller.allowed)`) evaluates every fact before scoring or formatting.
- **Graph Pruning Guard**: In graph walks and runbook sequencing, any step or bridge node requiring permissions outside the caller's role is strictly dropped. The traversal will **never jump through or expose restricted steps**.

### 3. Strategy Modes = Output Formatting & Execution Lifecycle
The project's `structure_mode` determines how the underlying multi-index facts are synthesized for the user:
- **`rag` Mode**: Blends vector, keyword, and 2-hop graph relations into a **narrative cited answer** (`[1]`, `[2]`).
- **`graph` Mode**: Builds a NetworkX `DiGraph`, runs topological DAG sorting, flags cycles, and outputs a **Step-by-Step Runbook Checklist** with owners and prerequisites.
- **`ruleset` Mode**: Parses input variables, evaluates comparison operators (`==`, `>`, `in`), and formats **Decision Branches**.

---

## 5. Authentication, RBAC & Auto-Seeding

### A. Default Admin Account & Auto-Seeding
- **Default Credentials**: Username `admin`, Password `admin123`.
- **Auto-Seeding**: In [`app/db.py`](file:///c:/Users/SHIVSHARN/Documents/RAJ/MAANG_paglu/backend/app/db.py), if `contextforge2.db` is initialized from scratch (or deleted and recreated), the system automatically seeds the `admin` user with the `admin` role (`*` wildcard clearance) so operators are never locked out.
- **First-User Rule**: In `app/auth.py:register()`, the first registered account is assigned `admin`; all subsequent accounts are assigned `member`.

### B. Single Global Visibility Function (`is_visible`)
All visibility logic across all 8 modes, graph walks, history modals, and context exports is evaluated through **one deterministic function**:

```python
def is_visible(fact_tags: list[str] | set[str] | str | None, allowed: list[str] | set[str] | None) -> bool:
```

#### Mathematical Invariants:
1. **Admin Clearance (`*` or `admin`)**: Returns `True` unconditionally.
2. **Untagged / Public Facts**: Empty tags `[]` are public and return `True`.
3. **Empty Caller Clearance**: If caller has no tags (`[]` or `None`), tagged facts return `False`.
4. **Strict Subset Semantics**: A fact carrying tags $T_{\text{fact}}$ is visible if and only if $T_{\text{fact}} \subseteq \text{Allowed}$. A user with `["frontend"]` cannot see a fact tagged `["frontend", "secret"]`.

### C. Project Isolation & Anti-Leakage
- Every source and fact belongs to a `project_id`.
- Access is permitted only if caller is `admin` or listed in the project's `members` list.
- Unauthorized project queries return `HTTP 404 Not Found` rather than `403 Forbidden` to prevent project existence enumeration.

---

## 6. The 8 Dynamic Retrieval Paradigms

| Mode | Classification Domain | Ingestion & Extraction Logic | Storage Layout | Retrieval & Scoring Algorithm | Special Response Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`rag`** | General architecture, narrative guides. | Normal atomic facts with tags. | Hybrid (Vector + Keyword). | Vector cosine similarity + token overlap scoring. | Synthesizes open-ended referenced answers with `[n]` citations. |
| **`ruleset`** | Policy branches, approval limits, discount thresholds. | Extracts `condition`, `outcome`, `priority`. | Relational columns (`condition`, `outcome`). | Rule trigger evaluation + keyword match. | Deterministic rule execution (`==`, `>`, `in`), missing variable alerts, conflict detection. |
| **`keyvalue`** | Technical configurations, ports, endpoints, constants. | Extracts canonical `key` and configuration `value`. | Relational `key` column + flat store. | Exact/normalized key match; bypasses fuzzy drift. | Direct configuration lookup card. |
| **`denylist`** | Rejected designs, forbidden tools, anti-patterns. | Extracts `text` (forbidden action) and `reason`. | `rejected_facts` table + fact index. | Flagging recurrence when user queries approach rejected items. | Returns `⚠️ Guardrail Violation Warning` banner. |
| **`versioned`** | Temporal evolution, pricing tiers, API version histories. | Extracts topic `key` and links supersession chain (`superseded_by`). | Relational `superseded_by`, `valid_from`, `valid_to`. | Filters out superseded versions by default; exposes them when `include_history=True`. | Displays version badges (`active` vs `superseded by #N`) and history modal. |
| **`graph`** | Sequential runbooks, procedural checklists, workflows. | Extracts `action`, `owner`, and `depends_on` prerequisite steps. | `edges` table + relational task columns. | Topological sort on dependency DAG with cycle detection. | Formats step-by-step checklist runbooks with Owner, Action, and Prerequisites. |
| **`allowlist`** | Credentials, strictly-scoped access tokens, secrets. | Enforces strict scope tags. | Multi-index with zero fuzzy vector scoring. | Strict tag match only. | Restricts results to exact explicit tag clearance. |
| **`keyword`** | Error codes, stack traces, literal file paths, regexes. | Literal text strings. | `FlatStore` (token / literal match). | Exact token overlap without vector distortion. | Returns literal error and configuration strings. |

---

## 7. Storage Engine, Vector-Space Guard & Batching

### A. Batch Vector Embedding (`VectorStore.index_batch`)
To optimize API quota consumption (such as Google Gemini's 100 Requests Per Minute free tier limit):
- During document ingestion in `app/structuring.py:structure_doc()`, individual vector indexing is deferred (`defer_vector=True`).
- All newly extracted facts are batched into a **single HTTP batch request** via `VectorStore.index_batch()`. Ingesting 25 facts uses **1 API call** instead of 25 separate calls.
- `GeminiEmbeddingProvider` parses `retryDelay` from Google's `RetryInfo` response on HTTP 429 quota exhaustion and applies intelligent exponential backoff.

### B. Vector-Space Compatibility Guard
When vector embedding models or dimensions change (e.g. FastEmbed 384d $\rightarrow$ Gemini 768d $\rightarrow$ Bedrock 1536d):
1. **Storage Metadata**: `vecs` table stores `(fact_id, v, model_name, dim)`.
2. **Query-Time Filter**: `VectorStore.prepare()` queries only vectors where `model_name` and `dim` match the active provider.
3. **Mismatch Detection Notice**: `retrieve()` warns if a project contains older vectors:
   `"Project was embedded with X (384d); re-embed to use Y (768d). Use POST /api/projects/{id}/reembed to upgrade."`
4. **One-Click Re-Embedding**: `POST /api/projects/{id}/reembed` recomputes all vectors in a single atomic transaction.

---

## 8. Natural-Language Provenance Engine

ContextForge replaces raw debug dumps with natural-language sentences conforming to the Ledger design system:

$$\text{"From } \{\text{source description}\} \text{, } \{\text{project context}\} \text{, } \{\text{when}\} \text{."}$$

- **Kind Mapping**: `text` $\rightarrow$ `"a pasted note"`, `url` $\rightarrow$ `"a web page"`, `screenshot` $\rightarrow$ `"a screenshot (OCR)"`, `file` $\rightarrow$ `"a file"`.
- **Title Heuristic**: Meaningful titles in quotes (`"Engineering Runbook"`). Empty/generic titles use the first ~6 words: `starting "Deploy checklist for..."`.
- **Domain Link**: Web URLs render active domain links (`notion.so`) pointing to the target URL.
- **RBAC Redaction**: If caller lacks clearance for a source's tags, `make_source_display()` redacts title and URL: `"From a restricted source."`

---

## 9. Complete REST API Reference

| Method | Endpoint | Access | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Public | Register user account (first user becomes `admin`). |
| `POST` | `/api/auth/login` | Public | Authenticate and receive bearer token. |
| `GET` | `/api/me` | Authenticated | Return identity, role, and permission tags. |
| `GET` | `/api/roles` | Authenticated | List all defined roles and assigned tag boundaries. |
| `POST` | `/api/roles` | Admin Only | Create new role with assigned tags. |
| `PUT` | `/api/roles/{name}` | Admin Only | Update tag assignments for a role. |
| `GET` | `/api/users` | Admin Only | List operator roster. |
| `PUT` | `/api/users/{username}/role` | Admin Only | Assign role to user. |
| `GET` | `/api/projects` | Authenticated | List accessible projects with mode and stats. |
| `POST` | `/api/projects` | Authenticated | Create project with auto-classified or explicit structure mode. |
| `PUT` | `/api/projects/{id}/mode` | Authenticated | Override project structure mode. |
| `POST` | `/api/projects/{id}/reembed` | Authenticated | Re-embed all facts in project using active provider. |
| `POST` | `/api/ingest` | Admin Only | Ingest document, extract facts, batch vector embed, sync indexes. |
| `POST` | `/api/sessions` | Authenticated | Start live screen capture session. |
| `POST` | `/api/sessions/{sid}/screen` | Authenticated | Transcribe screenshot via Vision OCR and ingest facts. |
| `POST` | `/api/retrieve` | Authenticated | Search facts under caller's RBAC scope with guardrail checks. |
| `POST` | `/api/ask` | Authenticated | Synthesize cited answer, DAG runbook, or decision branch. |
| `POST` | `/api/export` | Authenticated | Export Markdown context pack with natural-language citations. |
| `GET` | `/api/tags` | Authenticated | Return taxonomy tree and registered permission tags. |
| `GET` | `/api/rejected_facts` | Authenticated | Return rejected anti-patterns for guardrail inspection. |
| `GET` | `/api/facts/{id}/history` | Authenticated | Chronological version chain for a fact. |
| `GET` | `/api/sources/{id}` | Authenticated | Fetch full metadata for source inspection. |
| `GET` | `/api/status` | Authenticated | Return active LLM, embedding, and database provider telemetry. |
