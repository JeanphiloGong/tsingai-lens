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
export CORE_EXTRACTION_MAX_CONCURRENCY=4
```

`CORE_EXTRACTION_MAX_CONCURRENCY` is optional. When unset, Core extraction uses
`4`.

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
- Public HTTP paths are split between `/api/*` for docs and static assets and
  `/api/v1/*` for business APIs.
- Collection artifact readiness should be checked before calling graph or
  protocol endpoints from clients.
