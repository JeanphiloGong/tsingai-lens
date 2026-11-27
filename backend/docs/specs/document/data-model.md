# Document V2 Data Model

## Scope

`documents` owns uploaded-file identity and object-storage location.
`document_preparations` owns the current Source and Profile preparation aggregate.
The database stores metadata and object keys. File bytes remain in the object store.

## `documents`

| Column | Type | Meaning |
| --- | --- | --- |
| `document_id` | `varchar(64)` | Stable Document identity and primary key |
| `workspace_id` | `varchar(64)` | Workspace foreign key |
| `filename` | `text` | User-visible filename |
| `storage_key` | `text` | Server-generated object-store key, unique |
| `sha256` | `varchar(64)` | Digest of original bytes |
| `media_type` | `varchar(255)` nullable | Uploaded media type |
| `status` | `varchar(64)` | Preparation status projection |
| `size_bytes` | `bigint` | Original byte size |
| `document_order` | `integer` | Workspace ordering |
| `created_at` | `timestamptz` | Creation time |
| `updated_at` | `timestamptz` | Last state update |

The `(workspace_id, sha256)` and `(workspace_id, document_order)` unique constraints
remain. `workspace_id` references `workspaces.workspace_id` with cascade delete.

## `document_preparations`

`document_id` is both the primary key and a foreign key to `documents.document_id`.
There is one current preparation aggregate per Document.

| Column | Meaning |
| --- | --- |
| `source_format` | Source format |
| `parser_name` | Parser implementation |
| `parser_version` | Parser contract version |
| `source_fingerprint` | Current Source content version |
| `artifact_json` | Canonical Source artifact and tree |
| `profile_json` | Current DocumentProfile |
| `paper_map_payload` | Objective discovery input cache |
| `created_at`, `updated_at` | Preparation record timestamps |

The target `profile_json` contains `document_id`, `doc_type`, `description`,
`source_fingerprint`, `profile_fingerprint`, `profile_version`, and `generated_at`.
Confidence and model warnings are not part of the target Profile contract. Technical
profile failures belong to preparation and Pipeline state.

## Object-store namespace

Workspace is the logical storage boundary. Module-owned keys use server-generated
resource identities:

```text
{workspace_id}/input/{document_id}
{workspace_id}/documents/{document_id}/source/figures/{object_id}
{workspace_id}/memory/{memory_id}
{workspace_id}/integrations/obsidian/{object_id}
{workspace_id}/exports/{export_id}
```

Document V2 implements the first two categories. A module owns key generation for
its category. Callers cannot submit arbitrary paths. Resource ownership is checked
from database identities and authorization, not by parsing a key string.

Workspace-scoped keys do not include `user_id`. User-private resources that do not
belong to a Workspace may use a user-owned namespace.

## Migration

Alembic revision `20261127_0104` renames `original_filename` to `filename` and
drops `stored_filename`. Historical migration files remain unchanged. No runtime
code keeps a compatibility alias after the cutover.
