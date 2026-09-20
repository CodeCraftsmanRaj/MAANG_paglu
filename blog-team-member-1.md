---
title: "The Hardest Part Was Explaining What We Built"
description: "Coordinating a four-person hackathon team taught me that the gap between building ContextForge and making it understandable was a project of its own."
tags:
  - hackathon
  - project-management
  - documentation
  - technical-writing
  - demo
---

# The Hardest Part Was Explaining What We Built

## Four people, three codebases, one story

ContextForge was built in parallel tracks: a FastAPI backend, a React + Electron frontend, an AWS deployment stack, and a browser extension. Each track had an owner, and each owner could demo their own piece without hesitation. The problem nobody owned was the seam between the pieces. When one of us described the project, we described our track. Judges don't evaluate tracks — they evaluate a product.

Early on I wrote the one-line version we all agreed to repeat: ContextForge captures what a team knows, stores every fact with its source and access rules, and answers questions with cited, permission-aware answers. Every document, demo, and decision got checked against that sentence.

## Documentation as translation, not transcription

The root README went through the most rewrites of anything in the repo. The first versions narrated the code. What finally worked was a plain ASCII diagram — capture sources on the left, the store in the middle, retrieval on the right — followed by a table that turned out to be the most useful thing I wrote all weekend:

| Component | Default Local Provider | Production AWS Cloud Provider |
|---|---|---|
| LLM Provider | `groq` | `bedrock` (Claude) |
| Embedding Provider | `fastembed` | `bedrock` (Titan) |
| Fact Repository | `sqlite` | `dynamodb` |

That table gave the team a shared vocabulary. When our backend developer said "repository" and our AWS person said "table," they were suddenly talking about the same thing. It also let me explain the architecture honestly in one breath: the same code runs on a laptop or on Lambda, selected by environment variables — no rewrite, no fork.

## The runbook nobody had to ask about

The deployment guide in `infra/README.md` I structured as a fixed sequence: prerequisites, one deploy command, a smoke test, pointing clients at the API, teardown, and costs. Two details mattered more than the rest:

- **The cost table.** Judges and teammates both ask "what does this cost to run?" Answering it in the doc — Lambda and DynamoDB effectively free at demo scale, Bedrock pay-per-token — removed the biggest unspoken objection.
- **The troubleshooting section.** Every real failure we hit became an entry. That section later became the checklist for the demo video, because it captured the things that actually go wrong, like cold starts.

## The smoke test was the demo script

Our smoke test script registers a user, creates a project, ingests a fact, embeds it, and asks a question — six numbered steps with readable output. I started using it as the demo narration because it tells the whole story in under a minute: identity, projects, ingestion, embeddings, retrieval, synthesis. It doubled as our regression check; after every deploy, green output meant the story still worked.

For the video, one practical lesson came straight from our own troubleshooting notes: the first request after idle hits a Lambda cold start of a couple of seconds. The guide says to send a warm-up request before recording. Small thing, but it's the difference between a demo that looks broken and one that doesn't.

## Coordination that the repo can prove

I kept coordination boring and visible. Milestone commits marked checkpoints. Environment templates (`.env.example` files) were whitelisted in `.gitignore` so new contributors could onboard without anyone pasting secrets into chat — the ignore rules explicitly allow the templates while blocking every real env file. And I enforced one rule that saved us repeatedly: local development must keep working exactly as before while the AWS stack changed underneath it. That rule kept two tracks from breaking each other.

The deep technical reference in `backend/BACKEND_ARCHITECTURE.md` exists for a different audience than the README — judges or engineers who want the eight retrieval modes and the RBAC semantics in full. Two documents, two reading depths, one story.

## What I learned

Building the project and explaining the project are different deliverables, and the second one doesn't happen by accident. The test I learned to apply: could a stranger read the README alone and correctly describe what we built? If not, the story wasn't done — and no amount of working code fixes that.

The reflection I'd leave another team with: your smoke test is your demo, your troubleshooting notes are your video checklist, and your architecture table is your team's shared language. Write those three things well and the coordination mostly does itself.
