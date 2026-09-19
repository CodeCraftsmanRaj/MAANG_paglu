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
```

**Frontend** (Node 18+)
```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
npm run desktop              # optional Electron window (run `npm run dev` first)
```

---

## Deploying on AWS (Bedrock + DynamoDB + Lambda)
To switch to AWS cloud services, set your `.env` to match `.env.production`:

```env
LLM_PROVIDER=bedrock
EMBEDDING_PROVIDER=bedrock
DB_PROVIDER=dynamodb

AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v1
DYNAMODB_TABLE_NAME=ContextForgeKnowledge
```

### Serverless Lambda Deployment
Wrap with Mangum via `backend/lambda_handler.py`:
- Handler: `lambda_handler.handler`
- Runtime: `python3.11`
- Attach IAM permissions for `bedrock:InvokeModel` and `dynamodb:*` on your table.

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
