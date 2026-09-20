# ContextForge

Capture what your team knows automatically, then export it as context for any AI (or a new hire).
Built for the First Commit hackathon (Amazon x WeMakeDevs).

```
 CAPTURE (automatic)            STORE (every fact: provenance + access control)      RETRIEVE
 links, files, notes            keyword index                                        explicit scope
 screen watcher (Vision OCR)    vector index  (fastembed / Bedrock Titan)            dynamic inference (LLM)
 browser extension (AI chats)   graph index   (networkx, 2-hop walk)                 Ask and cite (RAG)
 watched folder                 LLM extracts atomic facts + relations                Markdown context pack
```

## Modular Provider Architecture
ContextForge supports modular, environment-driven provider swapping without any code modifications:

| Component | Default Local Provider | Production AWS Cloud Provider |
|---|---|---|
| **LLM Provider** (`LLM_PROVIDER`) | `groq` (Llama 3.3 70B) | `bedrock` (Claude 3.5 Sonnet) |
| **Embedding Provider** (`EMBEDDING_PROVIDER`) | `fastembed` (BGE-Small) | `bedrock` (Amazon Titan Text) |
| **Fact Repository** (`DB_PROVIDER`) | `sqlite` (`contextforge2.db`) | `dynamodb` (Single-table design) |
| **Hosting & API Entrypoint** | `uvicorn main:app` | `lambda_handler.py` (AWS Lambda + Mangum) |

---

## Run it Locally (Default Stack)
**Backend** (Python 3.10+, [uv](https://docs.astral.sh/uv/))
```bash
cd backend
cp .env.local .env           # or copy .env.example (Groq + FastEmbed + SQLite)
uv add -r requirements.txt
uv run main.py               # http://127.0.0.1:8000 (docs at /docs)

# tests (the DynamoDB parity suite needs moto)
uv add --dev moto
uv run python -m unittest discover -s . -p "test_*.py"
```

**Frontend** (Node 18+)
```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
npm run desktop              # optional Electron window (run `npm run dev` first)
```

---

## Deploying on AWS (Ship It track)

One command deploys the whole backend — **API Gateway → Lambda (FastAPI/Mangum) → DynamoDB (single table) + Bedrock (Claude LLM, Titan embeddings)** — all pay-per-use, free-tier friendly, with a public HTTPS URL as the output:

```bash
cd infra
./deploy.sh contextforge     # then: ./smoke_test.sh <ApiUrl>
```

The stack provisions the DynamoDB table, the Lambda function (slim package, no fastembed — Bedrock does embeddings), IAM roles, an HTTP API with CORS, and a Lambda Function URL (no 29 s API Gateway cap) as an escape hatch for very long ingests. Auth (users, tokens, roles) lives in DynamoDB on AWS and in SQLite locally — same code, selected by `DB_PROVIDER`.

Full guide (prerequisites, Bedrock model access, smoke test, teardown, costs, troubleshooting): **[infra/README.md](infra/README.md)**.

To run the backend against cloud services *without* Lambda (e.g. `uvicorn` on a box with AWS credentials), set:

```env
LLM_PROVIDER=bedrock
EMBEDDING_PROVIDER=bedrock
DB_PROVIDER=dynamodb

AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0   # cheap default; Sonnet: us.anthropic.claude-3-5-sonnet-20241022-v1:0
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
DYNAMODB_TABLE_NAME=<your table>
```

---

## Auth and "Viewing as"
- Register in the UI. **The first account becomes admin**; later sign-ups are `member` (sees nothing) until an admin assigns a role in **Team**.
- Passwords are salted PBKDF2; sessions are bearer tokens.
- Roles map to allowed tags. Every search filters by the caller's tags **on the server**, in every index.
- Admins can preview any role with "Viewing as" (sent as `X-View-As`; the server rejects it from non-admins). Only admins can ingest or edit roles.

## Automatic capture
| Source | How |
|---|---|
| Screen / meetings | Capture > Watch my screen (screenshot every 20 s, read by vision OCR, deduplicated) |
| AI chats and pages | Load `extension/` in Chrome, paste your token (Capture > Copy my token) into `extension/background.js` |
| Folder | Set `WATCH_DIR` in `.env` |
| Links, files, notes | Drop or paste in Capture (processed via unified `Ingestor` pipeline) |
