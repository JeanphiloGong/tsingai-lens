# Model Connection Data Model

Store system-wide model connections, encrypted credentials, and administrative
change records. Connections and audit records belong to the Lens PostgreSQL
database; user-service owns accounts and permissions. See the
[model connection HTTP contract](api.md).

- [Model Connections: `model_connections`](#model-connections-model_connections)
- [Ciphertext Format](#ciphertext-format)
- [Administrative Audit: `model_connection_audit`](#administrative-audit-model_connection_audit)
- [Model Management Permission](#model-management-permission)

## Model Connections: `model_connections`

Each row stores one system-wide model connection and its encrypted credential.
Connections have no owning user.

| Field | PostgreSQL type | Nullable | Purpose |
| --- | --- | --- | --- |
| `connection_id` | varchar(64) | No | Primary key, generated as `model_` followed by a UUID in hexadecimal; immutable after creation |
| `display_name` | text | No | Display name, 1–100 characters after trimming surrounding whitespace |
| `base_url` | text | No | Complete OpenAI-compatible API base, at most 2048 characters; immutable after creation |
| `model` | text | No | Provider model identifier, 1–200 characters after trimming surrounding whitespace; immutable after creation |
| `api_key_ciphertext` | bytea | Yes | Authenticated AES-GCM ciphertext; NULL means this connection requires no API key |
| `enabled` | boolean | No | Defaults to false; disabling prevents selection for new questions |
| `priority` | integer | No | Defaults to 0; higher values sort first |
| `context_window_tokens` | integer | Yes | Positive connection context limit; NULL inherits the Agent limit |
| `max_output_tokens` | integer | Yes | Positive connection output limit; NULL inherits the Agent limit |
| `request_timeout_seconds` | double precision | Yes | Finite positive timeout in seconds; NULL uses the Agent/SDK timeout rules |
| `version` | bigint | No | Positive concurrency version, initially 1; increases once per effective update |
| `created_at` | timestamptz | No | Creation time in UTC |
| `updated_at` | timestamptz | No | Most recent effective update time in UTC |

Constraints and indexes:

```text
PRIMARY KEY (connection_id)
CHECK (length(connection_id) BETWEEN 1 AND 64)
CHECK (length(btrim(display_name)) BETWEEN 1 AND 100)
CHECK (length(base_url) BETWEEN 1 AND 2048)
CHECK (length(btrim(model)) BETWEEN 1 AND 200)
CHECK (version > 0)
CHECK (context_window_tokens IS NULL OR context_window_tokens > 0)
CHECK (max_output_tokens IS NULL OR max_output_tokens > 0)
CHECK (request_timeout_seconds IS NULL OR
       (request_timeout_seconds > 0 AND request_timeout_seconds < 'Infinity'::float8))
CHECK (api_key_ciphertext IS NULL OR
       (octet_length(api_key_ciphertext) BETWEEN 30 AND 8221 AND
        get_byte(api_key_ciphertext, 0) = 1))
INDEX ix_model_connections_enabled (enabled)
```

## Ciphertext Format

| Part | Format | Rule |
| --- | --- | --- |
| Format version | First byte `0x01` | Identifies the AES-256-GCM encoding version |
| Nonce | Next 12 bytes | Generate a fresh nonce from a cryptographically secure random source for every encryption; never reuse one under the same master key |
| Encryption result | Remaining bytes | Ciphertext and the 16-byte authentication tag returned by `AESGCM.encrypt` |
| Plaintext | UTF-8 API key, 1–8192 bytes | Reject CR/LF; do not trim, truncate, or substitute a masked placeholder |
| AAD | UTF-8 `lens:model-connection:<connection_id>:api-key:v1` | Binds ciphertext to its connection; swapping ciphertext between rows fails authentication |

The master key consists of 32 random bytes supplied through a private server
file and is never stored in the database. NULL ciphertext means no API key is
required. A malformed encoding, invalid authentication tag, or mismatched
master key causes decryption to fail.

## Administrative Audit: `model_connection_audit`

Record successful administrative connection changes in the same transaction as
the configuration update. Failed tests or database operations do not produce a
successful-change record.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `id` | bigint identity | No | Primary key |
| `connection_id` | varchar(64) | No | References `model_connections.connection_id`; no cascading deletion |
| `actor_id` | text | No | Stable acting-user ID resolved by user-service; no cross-database foreign key |
| `action` | text | No | `create` or `update`; credential changes belong to the combined configuration update |
| `version` | bigint | No | Connection version after this successful write |
| `changed_fields` | jsonb | No | Field-name array only, for example `["enabled", "priority"]` |
| `created_at` | timestamptz | No | Operation time in UTC |

```text
PRIMARY KEY (id)
FOREIGN KEY (connection_id) REFERENCES model_connections(connection_id) ON DELETE RESTRICT
CHECK (length(actor_id) BETWEEN 1 AND 64)
CHECK (action IN ('create', 'update'))
CHECK (version > 0)
CHECK (jsonb_typeof(changed_fields) = 'array')
UNIQUE (connection_id, version)
```

Generate `changed_fields` from a fixed set of field names. A credential change
records only `api_key`, never its value, ciphertext, master-key path, request
body, or SDK error. Saving a name and credential together creates one
`action=update` record, for example
`changed_fields=["display_name", "api_key"]`.

Configuration, credentials, and audit commit atomically. One effective update
increments the version once. A version conflict or failed write rolls back the
entire operation. An update with no effective changes increments no version
and writes no audit; submitting a nonempty API key always counts as a
replacement.

## Model Management Permission

`models.manage` permits management of system-wide model connections and API
keys. User-service stores the following permission and built-in administrator
group association:

| Table | Field | Value |
| --- | --- | --- |
| `permissions` | `code` | `models.manage` |
| `permissions` | `name` | `Model administration` |
| `permissions` | `description` | `Manage shared model connections and provider credentials` |
| `permissions` | `is_system` | `true` |
| `group_permissions` | `group_code`, `permission_code` | `admin`, `models.manage` |

Association constraints:

```text
permissions: PRIMARY KEY (code)
group_permissions: PRIMARY KEY (group_code, permission_code)
group_permissions: FOREIGN KEY (group_code) REFERENCES groups(code)
group_permissions: FOREIGN KEY (permission_code) REFERENCES permissions(code)
```

Custom groups receive `models.manage` through permission-group administration.
Holding `users.manage` alone does not imply model-management access. Audit
`actor_id` identifies the operator and has no cross-database user foreign key.
