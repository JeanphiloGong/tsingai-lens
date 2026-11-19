# Model Connection API

Manage system-wide model connections and processing assignments through the
catalog, administrator endpoints, and audit history. Table and credential
formats are defined in the [model connection data model](data-model.md).

## Model Connection Conventions

- Paths include the `/api/v1` prefix and use the same browser origin.
- The `lens_session` cookie identifies the actor. Administrator endpoints
  require `models.manage`; requests cannot select an acting `user_id` or
  `actor_id`.
- Administrative writes require an Origin that exactly matches the configured
  `BROWSER_ORIGIN`, using the public HTTPS origin in production.
- JSON requests use `application/json`. Responses use
  `{code,message,data,meta}` with `code=200` for success; business errors and
  HTTP statuses follow the table below. Timestamps use UTC RFC3339.
- Administrative responses use `Cache-Control: no-store` and never return an
  API key, ciphertext, or master key.

## User Model Catalog

- **URL:** `/api/v1/model-connections`
- **Method:** `GET`
- **Description:** List enabled Chat connections for the authenticated user,
  ordered by `priority DESC, display_name ASC, connection_id ASC`.

No JSON request body.

**Response example**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "connection_id": "lab-a",
        "display_name": "Lab A",
        "model": "lab-chat-a"
      }
    ]
  },
  "meta": null
}
```

No available connection returns `items=[]`. A new question without an explicit
selection uses the first catalog entry. Selecting a disabled or nonexistent
connection returns an unavailable-selection error.

## Administrator Model Connections

Every endpoint in this section requires `models.manage`.

### Administrator Connection Response

The administrator endpoints share the following connection representation.

| Field | Type | Description |
| --- | --- | --- |
| `connection_id` | string | Stable connection ID |
| `display_name` | string | Display name |
| `base_url` | string | API base visible to administrators |
| `model` | string | Fixed model identifier |
| `kind` | string | Immutable capability, either `chat` or `embedding`. Defaults to `chat` at creation |
| `api_key_configured` | boolean | Whether ciphertext is present; does not establish that the credential is valid |
| `enabled` | boolean | Whether new questions and processing assignments may select this connection |
| `priority` | integer | Default selection order |
| `context_window_tokens` | integer / null | Positive limit or inheritance |
| `max_output_tokens` | integer / null | Positive limit or inheritance |
| `request_timeout_seconds` | number / null | Finite positive timeout or inheritance |
| `version` | integer | Concurrency version retained internally by the frontend; no visible field is required |
| `created_at`, `updated_at` | string | UTC RFC3339 timestamps |

Detail, create, and update operations return this object directly in `data`.
List responses use it for each item in `data.items`. A connection test returns
its own result object.

The frontend retains `version` in memory and submits it automatically as
`expected_version` for updates and tests. Administrators do not view or enter
it. After a successful write, retain the returned version. On
`model_connection_version_conflict`, prompt the administrator to reload the
configuration before saving again; do not overwrite or retry automatically.

### 1. List Model Connections

- **URL:** `/api/v1/admin/model-connections`
- **Method:** `GET`
- **Description:** Read a page of enabled and disabled model connections.

| Query parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `limit` | integer | 50 | 1–100 |
| `offset` | integer | 0 | At least 0 |

Order by `priority DESC, display_name ASC, connection_id ASC`. Read `items` and
`total` from the same database snapshot.

**Response example**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "connection_id": "lab-a",
        "display_name": "Lab A",
        "base_url": "https://model.example.invalid/v1",
        "model": "lab-chat-a",
        "kind": "chat",
        "api_key_configured": true,
        "enabled": false,
        "priority": 0,
        "context_window_tokens": 65536,
        "max_output_tokens": 8192,
        "request_timeout_seconds": 30,
        "version": 1,
        "created_at": "2026-11-14T00:00:00Z",
        "updated_at": "2026-11-14T00:00:00Z"
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  },
  "meta": null
}
```

An empty result returns `items=[]` and `total=0`.

### 2. Read a Model Connection

- **URL:** `/api/v1/admin/model-connections/{connection_id}`
- **Method:** `GET`
- **Description:** Read the complete administrative configuration for one
  connection.

No JSON request body. `connection_id` is a path parameter. Return the
administrator connection object; a missing connection returns
`200201/model_connection_not_found`.

### 3. Create a Model Connection

- **URL:** `/api/v1/admin/model-connections`
- **Method:** `POST`
- **Description:** Save a disabled model connection with an optional API key.

| Request field | Type | Required | Description |
| --- | --- | --- | --- |
| `display_name` | string | Yes | 1–100 characters after trimming surrounding whitespace |
| `base_url` | string | Yes | At most 2048 characters; complete http/https API base without userinfo, query, fragment, or whitespace |
| `model` | string | Yes | 1–200 characters after trimming surrounding whitespace |
| `kind` | string | No | `chat` or `embedding`. Defaults to `chat` |
| `api_key` | string / null | No | Omitted or null means no key; a string contains 1–8192 UTF-8 bytes without CR/LF and is not trimmed; empty strings are invalid |
| `priority` | integer | No | PostgreSQL int32 range; defaults to 0 |
| `context_window_tokens` | integer / null | No | 1–2147483647; defaults to null |
| `max_output_tokens` | integer / null | No | 1–2147483647; defaults to null |
| `request_timeout_seconds` | number / null | No | Finite positive number; defaults to null |

Create with `enabled=false` and `version=1`; generate the ID on the server.
Requests cannot supply `enabled`. Test the saved connection and enable it
explicitly. Display names need not be unique.

**Request example**

```json
{
  "display_name": "Lab A",
  "base_url": "https://model.example.invalid/v1",
  "model": "lab-chat-a",
  "api_key": "example-only-provider-token",
  "priority": 100,
  "context_window_tokens": 65536,
  "max_output_tokens": 8192,
  "request_timeout_seconds": 30
}
```

Return the administrator connection object. The example supplies a key, so
`api_key_configured=true`. A connection created without a key returns false.
Saving does not send a model request.
Successful creation records the initial configuration in one `action=create`
audit entry.

### 4. Update a Model Connection

- **URL:** `/api/v1/admin/model-connections/{connection_id}`
- **Method:** `PATCH`
- **Description:** Save connection settings and an optional API key together.

| Request field | Type | Required | Description |
| --- | --- | --- | --- |
| `expected_version` | integer | Yes | Frontend submits the version it read; no administrator input or display is required |
| `display_name` | string | No | New display name; cannot be null |
| `enabled` | boolean | No | Explicit true/false; omission does not default to false |
| `priority` | integer | No | Ordering value; cannot be null |
| `context_window_tokens` | integer / null | No | Null restores inheritance; omission preserves the value |
| `max_output_tokens` | integer / null | No | Null restores inheritance; omission preserves the value |
| `request_timeout_seconds` | number / null | No | Null restores inheritance; omission preserves the value |
| `api_key` | string / null | No | Omit to preserve the key, send a nonempty string to encrypt and replace it, or send explicit null to clear it; empty strings are invalid |

Send ordinary settings and the key in one request. At least one editable field
is required, using the creation constraints. Connection ID, address, model, and kind
cannot be changed.

| Submitted `api_key` | Server behavior | Frontend behavior |
| --- | --- | --- |
| Field omitted | Preserve the ciphertext | Omit the field when the key input is blank |
| Nonempty string | Encrypt and replace using a fresh nonce | Submit the new key with the other changes |
| Explicit null | Clear the ciphertext and return `api_key_configured=false` | Submit only after the administrator explicitly confirms clearing the saved key |

A blank input must not become null automatically. Clearing changes the local
edit draft and takes effect with the same Save operation as other settings;
canceling the clear action restores omission. Clearing does not revoke the
provider-side key or affect requests already dispatched.

**Request example: enable and reorder, preserving the key**

```json
{
  "expected_version": 1,
  "enabled": true,
  "priority": 100
}
```

**Request example: rename and replace the key**

```json
{
  "expected_version": 2,
  "display_name": "Lab A Updated",
  "api_key": "example-only-replacement-token"
}
```

**Request example: clear the key, preserving other fields**

```json
{
  "expected_version": 3,
  "api_key": null
}
```

Return the latest administrator connection object, without the old key, new
key, or ciphertext. All submitted fields and their redacted audit record commit
in one transaction; a version conflict, encryption failure, or failed write
rolls back the entire operation.

One effective update increments `version` once and writes one `action=update`
audit entry. The entry's `changes` object records the before and after values
of the fields that changed. The `api_key` entry holds only the credential state
and operation. Submitting the same nonempty key still replaces it with a fresh
nonce. Clearing an already-empty
key with no other effective changes returns the original version without an
audit. Clear the frontend key input after success or failure; do not retry
failed submissions automatically.

### 5. Test a Saved Connection

- **URL:** `/api/v1/admin/model-connections/{connection_id}/test`
- **Method:** `POST`
- **Description:** Make one model call with fixed content using the saved
  configuration, without changing settings or enabled state.

**Request example**

```json
{
  "expected_version": 4
}
```

Only saved connections can be tested, including disabled connections. The
request accepts no draft address, arbitrary messages, custom test text, or
temporary API key. After authorization and version checks, use the read
configuration for one request according to `kind`.

- `chat` calls `/chat/completions` with `Reply with OK.` and no tools. The
  first choice must contain nonempty text. The output cap is the smaller of
  128 tokens and the configured output limit.
- `embedding` calls `/embeddings` with one fixed synthetic input. The
  response must contain one nonempty vector of finite values at index 0.

Both probes cap total time at the smaller of 10 seconds and the configured
timeout, use no research data, and close the client after one attempt.
Redirects are disabled.

**Response example: successful test**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "connection_id": "lab-a",
    "tested_version": 4,
    "success": true,
    "latency_ms": 312,
    "reason": null
  },
  "meta": null
}
```

**Response example: provider call failed**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "connection_id": "lab-a",
    "tested_version": 4,
    "success": false,
    "latency_ms": 10002,
    "reason": "provider_timeout"
  },
  "meta": null
}
```

Failure `reason` is one of `provider_auth_failed`, `provider_unreachable`,
`provider_timeout`, `provider_rate_limited`, `provider_response_invalid`, or
`provider_rejected`. Return no provider message, response text, or request
headers. Map rate limits, 4xx/5xx, transport, and decoding failures at the probe
boundary. Master-key and database failures use the business errors below.

Testing changes no configuration or version, writes no configuration-change
audit, and persists no last-success flag. Concurrent edits do not alter a probe
already in flight. Its result identifies `tested_version`; the frontend
ignores results for a different known version. Canceling the browser request
does not guarantee that a dispatched probe incurs no provider cost.

### 6. List Model Connection Audit Records

- **URL:** `/api/v1/admin/model-connection-audit`
- **Method:** `GET`
- **Description:** Read successful creation and update records across enabled
  and disabled connections. An optional filter selects one connection.

| Query parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `connection_id` | string | Omitted | Optional stable connection ID, 1–64 characters |
| `limit` | integer | 50 | Page size, 1–100 |
| `offset` | integer | 0 | Number of records to skip, at least 0 |

The request has no JSON body. Sort by `created_at DESC, id DESC` and read the
page and total from the same database snapshot. An omitted `connection_id`
matches all records. A filter with no matches, including an unknown connection
ID, returns `items=[]` and `total=0`. An offset beyond the last record returns
an empty page with the matching total. Invalid parameters return
`200100/invalid_request`.

| Response field | Type | Description |
| --- | --- | --- |
| `data.items[].connection_id` | string | Connection affected by the operation |
| `data.items[].actor_id` | string | Stable user ID from the authenticated session |
| `data.items[].actor_display_name` | string / null | Display name at the time of the operation, or null when unavailable |
| `data.items[].action` | string | `create` or `update` |
| `data.items[].version` | integer | Configuration version after the successful write |
| `data.items[].changes` | object | Field names mapped to changes containing `before` and `after` |
| `data.items[].created_at` | string | Operation time in UTC RFC3339 |
| `data.total` | integer | Number of records matching the filter |
| `data.limit`, `data.offset` | integer | Effective pagination parameters |

Update records include only changed fields. The before and after values for
ordinary fields use the configuration field types. A null limit represents
inheritance. For a creation, the ordinary fields have `before=null` and
`after` set to the saved initial values, including defaults.

When the credential changes, `changes.api_key` contains only the configuration
states and an `operation`.

| `operation` | `before` | `after` | Display label |
| --- | --- | --- | --- |
| `set` | `unconfigured` | `configured` | Set |
| `replace` | `configured` | `configured` | Replaced |
| `clear` | `configured` | `unconfigured` | Cleared |

**Request examples**

```http
GET /api/v1/admin/model-connection-audit?limit=20&offset=0
GET /api/v1/admin/model-connection-audit?connection_id=lab-a&limit=20&offset=0
```

**Response example**

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [
      {
        "connection_id": "lab-a",
        "actor_id": "user_operator",
        "actor_display_name": "Model administrator",
        "action": "update",
        "version": 4,
        "changes": {
          "priority": { "before": 0, "after": 100 },
          "api_key": {
            "before": "configured",
            "after": "configured",
            "operation": "replace"
          }
        },
        "created_at": "2026-11-14T08:00:00Z"
      },
      {
        "connection_id": "lab-b",
        "actor_id": "user_reviewer",
        "actor_display_name": null,
        "action": "update",
        "version": 2,
        "changes": { "enabled": { "before": false, "after": true } },
        "created_at": "2026-11-14T07:30:00Z"
      }
    ],
    "total": 2,
    "limit": 20,
    "offset": 0
  },
  "meta": null
}
```

#### Audit List Display

The model dropdown defaults to **All models**. Load its options from the
[administrator connection list](#1-list-model-connections), using each
connection's `display_name` as the label and its `connection_id` as the value.
Reset `offset` to 0 when the selection changes.

Each row shows the time, model connection name, actor, action, and number of
keys in `changes`. Show the saved actor display name, falling back to
`actor_id` when it is null. **View details** expands the row to show each
field's before and after values. For example, show Priority as `0` and `100`,
and API key as **Configured** and **Replaced**. Render `enabled` as
**Enabled** or **Disabled**, null limits as **Inherited**, and ordinary
creation fields' old values as **No previous value**.

## Processing Model Assignments

All assignment endpoints require `models.manage`. Saving also requires the
configured browser Origin. The supported purposes are fixed by the processing
tasks that use them.

| Purpose | Required connection kind | Consumer |
| --- | --- | --- |
| `document_profile` | `chat` | Document preparation worker |
| `research_analysis` | `chat` | Objective discovery, Objective analysis and Finding summaries |
| `feedback` | `chat` | Correction-signal analysis and dataset sample construction |
| `embedding` | `embedding` | Source text-unit retrieval benchmark |

### Read an Assignment

`GET /api/v1/admin/model-assignments/{purpose}` returns the current
`connection_id` and assignment `version` in `data`. An unassigned purpose
returns `{"connection_id":null,"version":0}`.

### Save an Assignment

`PUT /api/v1/admin/model-assignments/{purpose}` saves an enabled connection
of the kind required by the selected purpose.

| Request field | Type | Description |
| --- | --- | --- |
| `connection_id` | string | Required, 1–64 characters |
| `expected_version` | integer | Required, 0–9223372036854775807 |

```json
{
  "connection_id": "lab-a",
  "expected_version": 0
}
```

Send zero for an initial assignment, or the version returned by the preceding
read or write. The first assignment returns version 1. Reassignment increments
the assignment version. Saving the current connection with the current version
returns the existing assignment. The response uses the same `data` fields
as the read endpoint. The assignment and connection have separate versions.

### List Eligible Connections

`GET /api/v1/admin/model-assignments/choices?kind=embedding` requires `kind`
to be `chat` or `embedding`. It returns `data.items` containing the enabled
connections of that kind. Each item contains `connection_id`, `display_name`,
and `model`. Items are ordered by
`priority DESC, display_name ASC, connection_id ASC`.

### Apply Assignments to Tasks

Document preparation uses the assignment to select a connection for new jobs.
When the purpose is unassigned, the request returns
`processing_model_unassigned` and creates no job.
An active job for the same document is reused until it finishes. Queued jobs
retain their recorded connection ID. The worker reads the current credential
for that connection when it needs to classify the document.

The other consumers read their current assignment when starting execution.
One execution uses the selected connection through completion. The retrieval
benchmark embeds the corpus and its queries using one selected connection
and includes that connection ID in its report.

## Model Connection Errors

| Condition | HTTP | `code` | `data.code` |
| --- | --- | --- | --- |
| Invalid session | 401 | 200301 | `authentication_required` |
| Missing management permission or mismatched write Origin | 403 | 200203 | `permission_denied` |
| Identity service unavailable | 503 | 200205 | `identity_unavailable` |
| Invalid JSON, type, field, length, or request size | 200 | 200100 | `invalid_request` |
| Connection not found | 200 | 200201 | `model_connection_not_found` |
| Stale configuration version | 200 | 200204 | `model_connection_version_conflict` |
| Stale assignment version | 200 | 200204 | `model_assignment_version_conflict` |
| Selected assignment connection is missing, disabled, or of the wrong kind | 200 | 200204 | `processing_model_unavailable` |
| Disabling a connection that is still assigned | 200 | 200204 | `model_connection_assigned` |
| Document preparation requested before an assignment exists | 200 | 200205 | `processing_model_unassigned` |
| Master key unavailable or decryption failed | 200 | 200205 | `model_credentials_unavailable` |
| Database unavailable | 200 | 200205 | `model_configuration_unavailable` |
| Unexpected failure | 200 | 200000 | `internal_error` |

Error messages are fixed text without credentials or other submitted values.
Validation errors may include
`errors:[{"loc":["body","api_key"],"type":"string_too_long"}]`, describing
only the field location and error type, with no raw input or exception context.

**Response example: version conflict**

```json
{
  "code": 200204,
  "message": "Configuration changed; reload before saving.",
  "data": {
    "code": "model_connection_version_conflict"
  },
  "meta": null
}
```

Chat response binding and approval continuation follow the
[Chat connection binding contract](../api.md#chat-connection-binding).
