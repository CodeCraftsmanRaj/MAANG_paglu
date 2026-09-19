# ContextForge

Capture what your team knows automatically, then export it as context for any AI (or a new hire).
Built for the First Commit hackathon (Amazon x WeMakeDevs).

```
 CAPTURE (automatic)            STORE (every fact: provenance + access control)      RETRIEVE
 links, files, notes            keyword index                                        explicit scope
 screen watcher (Groq vision)   vector index  (local fastembed embeddings)           dynamic inference (Groq)
 browser extension (AI chats)   graph index   (networkx, 2-hop walk)                 Ask and cite (RAG)
 watched folder                 Groq extracts atomic facts + relations               Markdown context pack
```

## Run it
**Backend** (Python 3.10+, [uv](https://docs.astral.sh/uv/))
```bash
cd backend
cp .env.example .env      # add GROQ_API_KEY (free at console.groq.com/keys)
uv add -r requirements.txt
uv run main.py            # http://127.0.0.1:8000  (docs at /docs)
```
The first ingest downloads a ~130 MB embedding model (needs internet once). Without a Groq key everything still runs on keyword rules; screen reading and Ask need the key.

**Frontend** (Node 18+)
```bash
cd frontend
npm install
npm run dev               # http://localhost:5173
npm run desktop           # optional Electron window (run `npm run dev` first)
```
Delete `backend/contextforge2.db` to reset.

## LLM: Groq
`GROQ_MODEL` (default `llama-3.3-70b-versatile`) extracts facts/relations, infers what a question needs, and answers with citations. `GROQ_VISION_MODEL` (default `meta-llama/llama-4-scout-17b-16e-instruct`) reads screenshots.

## Auth and "Viewing as"
- Register in the UI. **The first account becomes admin**; later sign-ups are `member` (sees nothing) until an admin assigns a role in **Team**.
- Passwords are salted PBKDF2; sessions are bearer tokens.
- Roles map to allowed tags. Every search filters by the caller's tags **on the server**, in every index.
- Admins can preview any role with "Viewing as" (sent as `X-View-As`; the server rejects it from non-admins). Only admins can ingest or edit roles.

## Automatic capture
| Source | How |
|---|---|
| Screen / meetings | Capture > Watch my screen (screenshot every 20 s, read by Groq vision, deduplicated) |
| AI chats and pages | Load `extension/` in Chrome, paste your token (Capture > Copy my token) into `extension/background.js` |
| Folder | Set `WATCH_DIR` in `.env` |
| Links, files, notes | Drop or paste in Capture |

## Extending
- New structure: subclass `Store` in `structuring.py` (`index`, `prepare`, `score`), add to `STORES` and `WEIGHT`.
- New ingestor: `@ingestor("pdf")` in `ingestion.py`, return `{title, uri, text}`.
- Inference rules without an LLM: edit `IMPLIES`.

## Demo script
1. Sign up (you are admin), add your docs URL, start the screen watcher on a chat.
2. Team: create a `backend` role. Sign up a second user, assign `backend`.
3. Sign in as them (or "Viewing as backend") and ask "How do I deploy this?". Database and backend facts appear with a note on why.
4. Build a context pack and paste it into any AI.
