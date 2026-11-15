# User Service Data Model

- [Accounts: `users`](#accounts-users)
- [Login Sessions: `sessions`](#login-sessions-sessions)
- [Email Verification Challenges: `email_challenges`](#email-verification-challenges-email_challenges)
- [Shared Rate Limit Windows: `auth_rate_limits`](#shared-rate-limit-windows-auth_rate_limits)
- [Permission Codes: `permissions`](#permission-codes-permissions)
- [Permission Groups: `groups`](#permission-groups-groups)
- [Group Permissions: `group_permissions`](#group-permissions-group_permissions)
- [User Group Memberships: `user_groups`](#user-group-memberships-user_groups)
- [Administrative Audit: `auth_audit`](#administrative-audit-auth_audit)
- [Initial Built-in Groups and Permissions](#initial-built-in-groups-and-permissions)
- [Transaction and Migration Conventions](#transaction-and-migration-conventions)

user-service uses its own PostgreSQL database for identity and permissions; the Lens research database stores business resources. The two databases have no cross-database user foreign keys. Research database schemas for shared annotation and dataset publishing are maintained separately.

## Accounts: `users`

Store stable accounts. New accounts normally register by email and record the verification time; administrators manage existing accounts without creating accounts on users' behalf. Imported accounts retain their user_id and password hash without fabricated email verification records. Local bootstrap remains available.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `user_id` | text | No | Primary key; new accounts use the user_ prefix, with a length of 1-64 characters |
| `email` | text | No | Unique email address; the application trims whitespace and lowercases it |
| `display_name` | text | No | Display name; defaults to an empty string |
| `password_hash` | text | No | PBKDF2-SHA256 encoding; plaintext is not stored |
| `active` | boolean | No | Whether the account is enabled; defaults to true |
| `created_at` | timestamptz | No | Creation time; defaults to now() |
| `email_verified_at` | timestamptz | Yes | Email verification time; NULL for imported and bootstrap accounts |

Constraints and indexes:

```text
PRIMARY KEY (user_id)
UNIQUE (email)
CHECK (length(user_id) BETWEEN 1 AND 64)
CHECK (email = lower(email))
```

Passwords use `pbkdf2_sha256:600000:<base64 salt>:<base64 digest>`, with a 16-byte salt and a 32-byte digest. Account activity and email verification are checked separately. Unverified accounts can log in with their existing password and change their own password, but cannot use email-based password recovery. This design removes administrator password resets; unverified accounts that lose their password have no recovery entry point in this scope.

## Login Sessions: `sessions`

Create one row for each successful login. A user may have multiple sessions.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `token_hash` | text | No | Primary key; hexadecimal SHA-256 digest of the raw session token |
| `user_id` | text | No | Account that owns the session |
| `expires_at` | timestamptz | No | Set to now() + 24 hours on creation; no sliding renewal |
| `revoked_at` | timestamptz | Yes | Revocation time; NULL means not revoked |

Constraints and indexes:

```text
PRIMARY KEY (token_hash)
FOREIGN KEY (user_id) REFERENCES users(user_id)
INDEX sessions_user_idx (user_id)
```

The raw token is generated from 32 cryptographically secure random bytes, encoded as 64 hexadecimal characters and delivered only through the browser cookie. Authentication requires an active account and an unrevoked, unexpired session; finding a session row does not by itself establish a valid login. Logout revokes only the current session. Password changes, email-based password recovery and account disabling revoke all existing sessions for that user. Re-enabling an account does not restore its old sessions.

## Email Verification Challenges: `email_challenges`

Store the current verification challenge for each email address and purpose, without plaintext verification codes or challenge history.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `challenge_id` | text | No | Primary key; resending generates a new challenge ID that replaces the old one |
| `email` | text | No | Normalized email address; a challenge can exist before the account does |
| `purpose` | text | No | register or password_reset |
| `code_digest` | bytea | No | HMAC-SHA256 digest of the verification code |
| `state` | text | No | pending/sent/consumed/failed |
| `expires_at` | timestamptz | No | Initially 10 minutes; reset to 10 minutes after SMTP accepts the email |
| `attempts` | integer | No | Number of failed digest comparisons; defaults to 0 and consumption is rejected at 5 |
| `created_at` | timestamptz | No | Current challenge creation time; defaults to now() and is updated on resend |

Constraints and indexes:

```text
PRIMARY KEY (challenge_id)
UNIQUE (email, purpose)
CHECK (purpose IN ('register', 'password_reset'))
CHECK (state IN ('pending', 'sent', 'consumed', 'failed'))
CHECK (attempts BETWEEN 0 AND 5)
```

The verification code is a six-digit string that preserves leading zeros. The digest input consists of challenge_id, email, purpose and the verification code, separated by zero bytes. CHALLENGE_SECRET must contain at least 32 bytes and is stored only in runtime configuration; comparison uses hmac.Equal. States progress from pending to sent to consumed; sending failures are marked failed on a best-effort basis. Consumption requires state sent, an unexpired challenge and attempts < 5. Expiry and exhausted attempts do not introduce additional states. Resending replaces the digest, expiry, attempt count and state; a late result from an older send cannot activate a newer challenge.

## Shared Rate Limit Windows: `auth_rate_limits`

Store rate limit reservations shared across processes and instances.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `key` | text | No | Primary key; rule prefix plus an IP address, email address or purpose |
| `used` | integer | No | Number of committed reservations in the window |
| `reset_at` | timestamptz | No | Window end time |

Constraints and indexes:

```text
PRIMARY KEY (key)
```

An atomic upsert sets used = 1 for a new or expired window. Within the window, it increments used by 1 and preserves reset_at. If any rule exceeds its limit, all reservations in that attempt are rolled back. Login rate limits commit independently before password verification and count both successful and failed attempts. See [HTTP rate limits](http-api.md#rate-limits) for each rule's quota.

## Permission Codes: `permissions`

Store built-in and administrator-registered action permissions. Business endpoints and gRPC Check use code; the management UI displays name and description. This metadata does not participate in authorization decisions.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `code` | text | No | Primary key; stable permission code, 1-128 characters, with at least two dot-separated segments |
| `name` | text | No | Display name; 1-100 characters after trimming |
| `description` | text | No | Description; at most 1000 characters, defaults to an empty string |
| `is_system` | boolean | No | Whether the permission is built in; defaults to false and is set only by migrations |

Constraints and indexes:

```text
PRIMARY KEY (code)
CHECK (length(code) BETWEEN 1 AND 128)
CHECK (code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$')
CHECK (length(trim(name)) BETWEEN 1 AND 100)
CHECK (length(description) <= 1000)
```

The API cannot change code after creation, preventing mismatches with business code. Built-in codes cannot be deleted; custom codes cannot be deleted while referenced by any group. New codes can participate in Check, but business entry points must actually check them. Registering a row does not automatically create a business capability.

## Permission Groups: `groups`

Store built-in and custom groups. Groups combine permissions, and users gain capabilities through group membership.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `code` | text | No | Primary key; stable group code, 1-64 characters |
| `name` | text | No | Display name; 1-100 characters after trimming |
| `description` | text | No | Description; at most 1000 characters, defaults to an empty string |
| `is_system` | boolean | No | Whether the group is built in; defaults to false and is set only by migrations |

Constraints and indexes:

```text
PRIMARY KEY (code)
CHECK (length(code) BETWEEN 1 AND 64)
CHECK (code ~ '^[a-z][a-z0-9_]*$')
CHECK (length(trim(name)) BETWEEN 1 AND 100)
CHECK (length(description) <= 1000)
```

Built-in groups cannot be deleted or have their code changed, but their names, descriptions and permission associations can be edited. Deletion of a custom group is rejected while it has user memberships. Deleting an unused custom group first removes its group_permissions associations in the same transaction; it does not cascade to users or permission codes.

## Group Permissions: `group_permissions`

A group can contain multiple permissions, and a permission can belong to multiple groups. Administrators use separate association endpoints to add or remove them; repeated requests do not create duplicate rows.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `group_code` | text | No | Group code; part of the composite primary key |
| `permission_code` | text | No | Permission code; part of the composite primary key |

Constraints and indexes:

```text
PRIMARY KEY (group_code, permission_code)
FOREIGN KEY (group_code) REFERENCES groups(code)
FOREIGN KEY (permission_code) REFERENCES permissions(code)
INDEX ix_group_permissions_permission (permission_code)
```

## User Group Memberships: `user_groups`

Store the many-to-many relationship between users and groups. Regular users may have no groups.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `user_id` | text | No | User ID; part of the composite primary key |
| `group_code` | text | No | Group code; part of the composite primary key |

Constraints and indexes:

```text
PRIMARY KEY (user_id, group_code)
FOREIGN KEY (user_id) REFERENCES users(user_id)
FOREIGN KEY (group_code) REFERENCES groups(code)
INDEX ix_user_groups_group (group_code)
```

Composite primary keys imply NOT NULL and prevent duplicate associations. Permission queries use only the current associations of enabled users and return deduplicated, sorted results. There is no permission cache across requests.

## Administrative Audit: `auth_audit`

Save audit events in the same transaction as successful management changes, covering accounts, group memberships, groups, permission codes and group permission mappings. Initial administrator setup also records an event.

| Field | Type | Nullable | Purpose |
| --- | --- | --- | --- |
| `id` | bigint | No | Primary key; GENERATED ALWAYS AS IDENTITY |
| `actor_id` | text | No | Stable operator ID; no user foreign key |
| `target_type` | text | No | user/group/permission; distinguishes target types |
| `target_id` | text | No | Target user_id, group.code or permission.code; no foreign key, preserving traceability after deletion |
| `action` | text | No | initialize_admin or an operation on a user/group/permission |
| `details` | jsonb | No | Defaults to {}; records applicable group_code, permission_code, active or changed metadata |
| `created_at` | timestamptz | No | Creation time; defaults to now() |

Constraints and indexes:

```text
PRIMARY KEY (id)
CHECK (target_type IN ('user', 'group', 'permission'))
```

Actions include user.status.update, user.group.grant/revoke, group.create/update/delete, group.permission.grant/revoke and permission.create/update/delete. details must not contain passwords, tokens or verification codes. The target type and details support the new management operations, avoiding confusion between group codes and user IDs or packing every change into the action string.

This design adds no audit query API or dedicated query index. User database foreign keys do not declare ON DELETE CASCADE. There is no user deletion API or background task to automatically clean up sessions, challenges or rate limit windows.

## Initial Built-in Groups and Permissions

| Group Code | Permission Codes |
| --- | --- |
| `admin` | users.manage |
| `annotator` | research.read_all, annotation.annotate |
| `reviewer` | research.read_all, annotation.review |
| `publisher` | research.read_all, dataset.publish, dataset.download |

These are initial seed mappings; group permissions can subsequently be adjusted in the management UI. Newly registered users receive no groups automatically. The admin group initially has no research read permission and gains it only through an explicit grant. Administrators can create other groups with users.manage. Last-administrator checks count all enabled users with effective management permission, regardless of whether their group is named admin.

Disabling a user, revoking a membership, removing users.manage from a group, or deleting a group or permission code uses the same management lock and checks before commit that at least one enabled administrator remains. No alternative management path may bypass this protection. The built-in marker protects stable identifiers, cannot be forged by a request and does not make built-in group permissions immutable.

Research reading, annotation and publishing groups and permissions remain in the permission catalog. Their business design is maintained separately and these business capabilities are outside the current delivery scope.

## Transaction and Migration Conventions

| Operation | Atomic Scope / Failure Handling |
| --- | --- |
| bootstrap | Initialization lock, empty-database check and first-account creation share one transaction. A nonempty database is rejected; the display name Administrator does not imply membership in the admin group. |
| Login | Lock the user, verify the password and active status, then save the session. Failure creates no session; previously committed rate limit reservations remain. |
| Change own password | Read the session to identify the account, lock the account, re-read and authenticate the session, verify the old password, write the hash and revoke all sessions. Any write failure rolls back the transaction. |
| Send verification code | Commit rate limit reservations and pending state before calling SMTP. SMTP and the database are not atomic; if the email is accepted but marking sent fails, the challenge remains unusable and must be resent. |
| Failed verification | Commit the failed-code count and verification rate limit usage before returning the business error. Missing, expired or replaced challenges do not increment failed digest comparisons. |
| Registration / recovery | Consume a valid challenge and create the account or update the password and revoke sessions in the same transaction. Any write failure rolls back the transaction. |
| Account / group / permission management | Share the management lock. Re-authentication, authorization, reference checks, changes, last-administrator protection and audit writes occur in one transaction; failure rolls back everything. |

Acquire rate limit row locks in IP, email, then cooldown order before taking the email business lock. Account changes use the user row lock. There are no distributed transactions between the database and SMTP or between the user and research databases. A request that has already authenticated is not guaranteed to be automatically canceled when another request revokes its session.

| Migration | Change |
| --- | --- |
| Goose00001 | users, sessions |
| Goose00002 | email_verified_at, email_challenges, auth_rate_limits |
| Goose00003 | Initial permissions, groups, user memberships, audit and seed authorization data |
| Goose00004 | Group/permission name, description, is_system and constraints; reverse lookup indexes for both associations; audit target_type/details |
| Lens0098 -> 0099 | Back up, import and verify the original IDs/hashes before dropping auth_users/auth_sessions and user foreign keys from the Collection, Chat, Feedback, FeedbackDataset and ExperimentPlan models; retain business user_id values |

The user service uses Goose, and the research database uses Alembic; sqlc only generates query calls. Existing sessions are not migrated. The 0099 identity cutover has no automatic downgrade; rollback uses the backup taken before cutover. Research database owner_user_id, created_by and confirmed_by fields retain stable user IDs without physical foreign keys to the user database.

Migration 00004 first backfills names for existing groups and permissions from their codes, then fills in display metadata for the initial built-in entries and marks them is_system=true. Existing audit rows are backfilled with target_type=user and details={} according to their original user-management semantics; historical action values remain unchanged. NOT NULL and length constraints are applied afterward. Migration 00003 retains the initial code-only catalogs and audit shape. Migration 00004 supplies the metadata and audit extensions as a separate upgrade for both fresh and existing databases.
