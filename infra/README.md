# Deploying the ContextForge backend on AWS

One command deploys the whole backend. Everything is pay-per-use and covered by the
AWS Free Tier — nothing runs when nobody is using it, and there is nothing to shut
down at the end of the weekend except the stack itself (`sam delete`).

## Architecture (Ship It track)

```
 Browser / Electron UI / Chrome extension
        │  HTTPS (JSON + bearer token)
        ▼
 Amazon API Gateway (HTTP API, CORS enabled)     ← the public URL you hand in
        ▼
 AWS Lambda  (python3.12, FastAPI via Mangum)
        ▼                    ▼                     ▼
 Amazon DynamoDB         Amazon Bedrock        (optional) Groq
 single table            Claude (LLM)          for OCR/LLM if configured
 PK/SK design            Titan (embeddings)    via GROQ_API_KEY
```

Also deployed: a **Lambda Function URL** for the same function — identical API with no
API Gateway 29-second cap, useful if a very large URL ingest would time out.

Everything lives in one CloudFormation stack: table, IAM role, Lambda, API, outputs.

---

## 1. Prerequisites (one-time, ~10 minutes)

### a. AWS credentials
```bash
aws configure          # paste Access Key ID + Secret Access Key, region: us-east-1
aws sts get-caller-identity   # sanity check
```

No other tools needed — `deploy.sh` uses only the AWS CLI (`aws cloudformation
package/deploy`). The AWS SAM CLI is *optional* if you prefer `sam build`.

### b. AWS SAM CLI
```bash
# macOS: brew install aws-sam-cli   |   Windows: winget install Amazon.SAM-CLI
# Linux: pip install aws-sam-cli (or the AWS installer script)
sam --version
```

### c. Enable Bedrock model access (required for the LLM)

Titan embeddings and the stack are ready to go, but **Anthropic models need a
one-time opt-in** per account:

1. Open the AWS Console → **Bedrock → Model access**
2. **Modify model access** → check **Anthropic** (Claude Haiku 4.5 or the Claude family)
3. Submit (instant for most accounts)

Without this step, `/api/ask` and `/api/ingest` will return errors from Bedrock.

---

## 2. Deploy

```bash
cd infra
./deploy.sh contextforge          # stack name; any name works
```

The script stages a slim Lambda package (`backend/lambda-build/`, built for the
python3.12 x86_64 runtime — no fastembed/uvicorn), packages it to S3, creates the
stack, and prints the outputs:

| Output       | Meaning                                                      |
|--------------|--------------------------------------------------------------|
| `ApiUrl`     | **The URL you submit to the hackathon**                      |
| `FunctionUrl`| Direct Lambda URL (no 29 s cap — escape hatch for big ingests) |
| `TableName`  | DynamoDB single table                                        |

Deploy takes ~2–3 minutes. Redeploying after code changes is the same command.

> Build it on any Linux/macOS/WSL machine: the script creates an isolated build
> venv and installs wheels for the Lambda runtime explicitly, so your host Python
> version and OS do not matter.

---

## 3. Smoke test

```bash
./smoke_test.sh "<ApiUrl>"
```

It registers a user, creates a project, ingests a fact (Titan embedding through
Bedrock), and asks a question (Claude through Bedrock). All green = deployment works.

> **Important:** on a fresh stack, the **first registered account becomes admin**.
> Register your real admin user immediately — the URL is public.

---

## 4. Point the clients at it

- **Web/Electron UI:** build with the API URL baked in —
  `cd frontend && VITE_API_URL="<ApiUrl>" npm run build`
- **Chrome extension:** Options → paste your bearer token and set
  *Server URL* to `<ApiUrl>`
- **Local dev stays exactly as before** (SQLite + localhost) — nothing about the
  local workflow changed.

## 5. Update / teardown

```bash
./deploy.sh contextforge        # redeploy after backend code changes
sam delete --stack-name contextforge   # remove everything ( DynamoDB data is deleted)
```

## 6. What it costs

| Service       | Free tier coverage (new-ish accounts)          |
|---------------|------------------------------------------------|
| Lambda        | 1M requests + 400,000 GB-s / month — a demo is noise |
| API Gateway   | 1M calls / month (12 months)                   |
| DynamoDB      | 25 GB + 25 WCU/RCU on-demand, effectively free at demo scale |
| Bedrock       | pay-per-token. Default LLM is **Claude Haiku 4.5** (~$1/$5 per 1M tokens — a weekend demo costs cents). Want stronger answers? Pass `BEDROCK_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v1:0 ./deploy.sh contextforge` (Sonnet 3.5 v2). Embeddings use Amazon Titan (~$0.02/1M tokens). |

Nothing runs when idle; there are no servers to pay for between demos.

## 7. Troubleshooting

- **`AccessDeniedException` from Bedrock** → Anthropic model access not enabled (§1c).
- **502/timeout on a very large URL ingest** → the API Gateway integration caps at
  ~29 s. Use the `FunctionUrl` output for that request (same API, no cap), or paste
  the text instead of the URL.
- **401 after redeploy** → tokens live in DynamoDB, so they survive redeploys; make
  sure you are pointing at the same stack's URL.
- **Cold start ~2–4 s** after minutes idle — normal for Lambda; consider this when
  recording the demo video (send a warm-up request first).
