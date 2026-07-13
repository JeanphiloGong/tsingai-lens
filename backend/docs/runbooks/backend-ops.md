# Backend Local Development and Operations

## Environment Setup

```bash
cd backend
uv venv .venv
source .venv/bin/activate
uv sync
```

## Required Runtime Variables

Set backend LLM runtime variables before local runs:

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local
export CORE_LLM_EXTRACTION_MODE=json_text
export CORE_EXTRACTION_MAX_CONCURRENCY=4
```

`CORE_EXTRACTION_MAX_CONCURRENCY` is optional. When unset, Core extraction uses
`4`.
`CORE_LLM_EXTRACTION_MODE` is optional. Supported values are `json_text` and
`provider_parse`. When unset, Core extraction uses `json_text`.

## Start the Backend

```bash
uvicorn main:app --reload --port 8010
```

Primary local endpoints:

- API docs: `http://localhost:8010/api/docs`
- OpenAPI: `http://localhost:8010/api/openapi.json`

## Common Verification Commands

```bash
pytest -q
python3 ../scripts/check_docs_governance.py
```

## Operational Notes

- Backend data persists under `backend/data`.
- The Source runtime default config is packaged at
  `backend/infra/source/config/default.yaml`; do not require
  `backend/data/configs/default.yaml` in Docker volumes.
- Public HTTP paths are split between `/api/*` for docs and static assets and
  `/api/v1/*` for business APIs.
- Collection artifact readiness should be checked before calling graph
  endpoints from clients.
- Collection build tasks run in a dedicated single-worker thread inside the
  backend process. The task creation request returns after queueing, and
  clients should poll `GET /api/v1/tasks/{task_id}` for progress.
