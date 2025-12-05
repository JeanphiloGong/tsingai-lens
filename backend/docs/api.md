# API Reference

Base URL: `http://localhost:8010` (adjust as needed). Endpoints currently have no auth.

## Health
- **GET** `/health` — service liveness.
  ```bash
  curl http://localhost:8010/health
  ```

## Documents
- **GET** `/documents` — list registered documents.
  ```bash
  curl http://localhost:8010/documents
  ```

- **POST** `/documents` — upload a document and ingest it into the graph.
  - Form data:
    - `file` (required): the file to upload.
    - `tags` (optional): comma-separated tags, e.g. `tag1,tag2`.
    - `metadata` (optional): JSON string for extra metadata, e.g. `{"source":"manual"}`.
  - Response (`DocumentUploadResponse`): `id`, `keywords`, `graph`, `mindmap`, `summary`.
  ```bash
  curl -X POST http://localhost:8010/documents \
    -F "file=@/path/to/document.pdf" \
    -F "tags=research,finance" \
    -F 'metadata={"source":"manual"}'
  ```

- **GET** `/documents/{doc_id}` — fetch a document record plus stored metadata (keywords, graph snapshot, mindmap, summary, etc.).
  ```bash
  curl http://localhost:8010/documents/<doc_id>
  ```

- **GET** `/documents/{doc_id}/keywords` — get extracted keywords.
  ```bash
  curl http://localhost:8010/documents/<doc_id>/keywords
  ```

- **GET** `/documents/{doc_id}/graph` — get graph snapshot and mindmap (if any).
  ```bash
  curl http://localhost:8010/documents/<doc_id>/graph
  ```

## Query
- **POST** `/query` — query the graph and retrieve answers with sources.
  - JSON body:
    - `query` (required): the question.
    - `mode` (optional, default `optimize`): retrieval mode.
    - `top_k_cards` (optional, default `5`): number of cards to retrieve.
    - `max_edges` (optional, default `80`): maximum graph edges considered.
  - Response (`QueryResponse`): `answer` text and `sources` array (each source may include `doc_id`, `source`, `page`, `chunk_id`, `snippet`, `edge_id`, `community_id`, `head`, `tail`, `relation`, `score`).
  ```bash
  curl -X POST http://localhost:8010/query \
    -H "Content-Type: application/json" \
    -d '{"query":"What does the report say about market trends?","mode":"optimize","top_k_cards":5,"max_edges":80}'
  ```
