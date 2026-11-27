# Document V2 HTTP API

## Conventions

Routes use the `/api/v1` prefix, the existing authentication context, and the
`code/message/data/meta` response envelope. This cutover changes document field
names and preserves existing error semantics.

## Workspace document routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/workspaces` | Workspace picker and compact Document rows |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents` | Upload a Document |
| `GET` | `/api/v1/workspaces/{workspace_id}` | Workspace detail |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents` | Current Document list |
| `DELETE` | `/api/v1/workspaces/{workspace_id}` | Delete Workspace and owned objects |
| `POST` | `/api/v1/workspaces/{workspace_id}/source-archives` | Archive selected Documents |

## Compact Document row

Workspace lists return only display and state fields.

| Field | Type | Meaning |
| --- | --- | --- |
| `document_id` | string | Stable identity |
| `filename` | string | User-visible filename |
| `media_type` | string or null | Media type |
| `status` | string | Preparation status projection |
| `size_bytes` | integer | Original size |
| `created_at` | string | Creation time |
| `updated_at` | string | Last update |

## Document detail

A detail response includes the opaque server-owned `storage_key` used internally
for file access and may add the current `source_version` used for Source reads.
It does not expose `sha256`, `parser_version`, `profile_version`,
`source_fingerprint`, or `profile_fingerprint`.

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "document_id": "doc_123",
    "filename": "paper.pdf",
    "storage_key": "workspace-123/input/doc_123",
    "media_type": "application/pdf",
    "status": "ready",
    "size_bytes": 123456,
    "created_at": "2026-11-27T00:00:00Z",
    "updated_at": "2026-11-27T00:05:00Z",
    "source_version": "source-digest"
  },
  "meta": null
}
```

## Upload

`POST /api/v1/workspaces/{workspace_id}/documents` accepts the existing multipart
file request. The cleaned client filename is stored as `filename`. The server
creates `storage_key` from the Document identity. Clients do not submit or compose
storage keys. Content deduplication continues to use Workspace-scoped SHA-256.

## Archive and Source access

Archive, original-file access, deletion, and Source reads use `document_id`. The
server resolves `storage_key` internally. Existing Source locator, version, and
stable error contracts remain unchanged.

## Stable errors

- `document_not_found`
- `document_content_already_exists`
- `document_sources_not_ready`
- `source_version_changed`
- `source_not_found`
- `upload_invalid`
- `upload_too_large`
