# ContextForge

A modular knowledge base you can **export as context** for any AI (or a new hire).
Built for the First Commit hackathon (Amazon x WeMakeDevs).

```
 Ingestion (pluggable)  ->  Storage (pluggable structure)  ->  Retrieval (pluggable)
 text | url | live       flat facts | knowledge graph        explicit | dynamic
                         + ACCESS CONTROL + PROVENANCE       -> Markdown context pack
                           (mandatory, enforced in the base class)
```

## Run it

**Backend** (Python 3.10+, [uv](https://docs.astral.sh/uv/))
```bash
cd backend
uv add -r requirements.txt
uv run main.py            # http://127.0.0.1:8000  (docs at /docs)
```

**Frontend** (Node 18+)
```bash
cd frontend
npm install
npm run dev               # http://localhost:5173 (proxies /api to :8000)
npm run desktop           # optional: Electron window (run `npm run dev` first)
```

## 2-minute demo
1. **Ingest** a URL (your docs), paste a README, then start a **Live session** and send chunks (simulates a meeting / AI chat).
2. **Access**: the seed roles are `admin`, `backend`, `frontend`. Switch "Viewing as" to `backend`.
3. **Retrieve** > *Dynamic*: ask "how do I deploy this?". Database and backend facts are pulled in even though you never asked (see the amber notes).
4. **Export context pack** > paste into any AI to continue where you left off.

## How the guarantees work (`backend/app/structuring.py`)
- `Store.put()` refuses any fact without a valid `source_id` -> **provenance** for every structure.
- `Store.search()` filters by the caller's allowed tags *before* ranking -> **access control** for every structure.
- Add a structure: subclass `Store`, implement `score()` (and optionally `index()` / `prepare()`), register it in `STORES`.
- Add an ingestor: decorate a function with `@ingestor("pdf")` in `ingestion.py`; it must return `{title, uri, text}`.
- Add inference rules: edit `IMPLIES` (query about X also needs Y).

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingest` | static ingest (`kind`: text/url, `structure`: flat/graph, `tags`) |
| POST | `/api/sessions`, `/api/sessions/{id}/chunk` | live ingest, streamed in chunks |
| POST | `/api/retrieve` | `mode`: explicit (`scope` tags) or dynamic (inferred from `query`) |
| POST | `/api/export` | same as retrieve, returns a Markdown context pack |
| GET/PUT | `/api/roles`, `/api/roles/{name}` | role -> allowed tags (`*` = all). Header `X-Role` picks the caller |

## Notes
Extraction is heuristic (keyword tags + co-occurrence graph), so it runs with no API key.
The natural upgrade is an LLM extractor (e.g. Amazon Bedrock) behind `structure_doc()`.
Data lives in `backend/contextforge.db` (SQLite). Delete it to reset.
