# ContextForge — 3-Minute Demo Video Script

Target: **≤ 3 minutes**. Voiceover below is ~440 words ≈ 2:45 at a natural pace, leaving buffer for pauses. Record section by section; it cuts together cleanly.

## Before you hit record

- [ ] Send one warm-up request first (`GET https://8lfedsiw1k.execute-api.us-east-1.amazonaws.com/api/status`) — Lambda cold start is 2–4 s after idle; don't open the video on a spinner.
- [ ] Pre-open: terminal in `~/MAANG_paglu`, `infra/README.md` architecture diagram scrolled into view, the web UI logged out (show the login screen fresh).
- [ ] Have a test project with a couple of ingested notes ready so the Ask step answers instantly.
- [ ] Close notifications; use 1080p; keep the terminal font large.

---

## [0:00–0:25] About the project

**Screen:** Web UI login screen → log in live.

> "Every team's knowledge is scattered — across chat threads, docs, screenshots, and people's heads. ContextForge fixes that. You capture what your team knows — links, files, notes, even your screen — and it becomes a searchable knowledge base where every fact keeps its source and its access rules. Then you just ask questions in plain language, and get answers with citations you can click."

**Do:** log in, land on the Capture view.

## [0:25–0:55] Tech stack and architecture

**Screen:** `infra/README.md` architecture diagram, then `backend/BACKEND_ARCHITECTURE.md` briefly.

> "The backend is FastAPI, with a pluggable provider architecture: the same code runs locally on SQLite with FastEmbed, or in production on AWS — chosen by environment variables, no rewrites. Ingestion runs through a unified pipeline that extracts atomic facts, then indexes them three ways at once: keyword, vector, and a graph of relations. Projects auto-classify into one of eight retrieval modes — RAG, rulesets, key-value, runbooks, and more — so answers match the kind of knowledge you stored. Everything is role-based: what you can't see, you can't retrieve — enforced on the server, in every index."

## [0:55–1:45] Live demo: capture → ask

**Screen:** the actual UI, one continuous flow.

> "Here's the whole loop. I create a project — ContextForge classifies it automatically. I paste a note about our deployment config. The LLM extracts atomic facts, embeds them, and indexes them. Now I ask: 'What is the production API timeout?' The retrieval pipeline finds the relevant facts across indexes, and Bedrock's Claude synthesizes a cited answer. And every answer shows provenance — which source, which project, when it was recorded. If a fact is restricted for my role, I get redacted provenance instead — that's the access control working live."

**Do:** create project (show auto-classify reason), paste text, ask the question, hover a provenance sentence. Optionally switch "Viewing as" to member to show results change.

## [1:45–2:30] How you have used AWS

**Screen:** `infra/template.yaml` (scroll), then terminal running `./smoke_test.sh <ApiUrl>` output (pre-captured or live if fast).

> "On AWS, the whole backend is one SAM/CloudFormation stack: API Gateway HTTP API in front of a Lambda running our FastAPI app via Mangum, DynamoDB single-table for users, projects, facts, and indexes, and Amazon Bedrock doing the AI heavy lifting — Titan Text v2 for embeddings and Claude for extraction and cited answers. IAM scopes the Lambda role to exactly one table and model invocation. One command deploys it — `deploy.sh` — and a smoke test proves the full path end to end: register, create project, ingest, embed, ask. The web UI ships from S3 static hosting, and the same app runs as an Electron desktop build."

## [2:30–2:50] Learning and growth

> "Three things taught us the most: an app that works locally makes silent promises — a file that persists, SQL that exists — and serverless revokes them, so we designed one repository interface and made SQLite and DynamoDB pass the same tests. CloudFormation rollback is unforgiving: a failed stack is evidence to delete and a template to fix. And the product only became real when the UI made security visible — provenance and role switching turned 'trust us' into 'see for yourself.'"

## [2:50–3:00] Close

**Screen:** repo URL + deployed UI side by side.

> "ContextForge — capture what your team knows, retrieve it with citations. Repo and live demo linked below. Thanks for watching."

---

## Recording tips

- Zoom browser to 110–125% so the UI is readable at 1080p.
- If any request is slow, cut it in the edit — the smoke test output is your proof of speed, not the cold start.
- End the ask-demo on the provenance line; it's the most memorable detail.
