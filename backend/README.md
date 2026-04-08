# TsingAI-Lens Backend

FastAPI backend for collection ingestion, indexing, graph/report browsing, protocol extraction, and query.

## Public HTTP Contract

- Business APIs: `/api/v1/*`
- Docs/OpenAPI/Static: `/api/*`
  - `/api/docs`
  - `/api/redoc`
  - `/api/openapi.json`
  - `/api/static/*`

## Core Endpoints

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/files`
- `POST /api/v1/collections/{collection_id}/tasks/index`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/collections/{collection_id}/workspace`
- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`
- `POST /api/v1/query`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`

## Local Development

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local

uvicorn main:app --reload --port 8010
```

## Notes

- Public query and reports routes live under `api/routes/*`.
- Public protocol browsing is collection-scoped under `/api/v1/collections/{collection_id}/protocol/*`.
- See `backend/docs/api.md` for detailed contract notes.
