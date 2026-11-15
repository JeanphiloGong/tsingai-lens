# User Service HTTP API

- [General Information](#general-information)
  - [Public User Information](#public-user-information)
- [Account Endpoints](#account-endpoints)
  - [1. Log In](#1-log-in)
  - [2. Get the Current User](#2-get-the-current-user)
  - [3. Log Out](#3-log-out)
  - [4. Change Your Password](#4-change-your-password)
- [Email Registration and Password Recovery](#email-registration-and-password-recovery)
  - [5. Send an Email Verification Code](#5-send-an-email-verification-code)
  - [6. Register an Account](#6-register-an-account)
  - [7. Reset a Forgotten Password](#7-reset-a-forgotten-password)
- [Current User Permissions](#current-user-permissions)
  - [8. Get the Current User's Permissions](#8-get-the-current-users-permissions)
- [User Administration](#user-administration)
  - [List Parameters and Common Responses](#list-parameters-and-common-responses)
  - [9. List Users](#9-list-users)
  - [10. Enable or Disable an Account](#10-enable-or-disable-an-account)
- [User Group Memberships](#user-group-memberships)
  - [11. List a User's Groups](#11-list-a-users-groups)
  - [12. Assign a Group to a User](#12-assign-a-group-to-a-user)
  - [13. Remove a User's Group Membership](#13-remove-a-users-group-membership)
- [Permission Groups](#permission-groups)
  - [14. List Permission Groups](#14-list-permission-groups)
  - [15. Create a Permission Group](#15-create-a-permission-group)
  - [16. Update a Permission Group](#16-update-a-permission-group)
  - [17. Delete a Permission Group](#17-delete-a-permission-group)
- [Group Permission Associations](#group-permission-associations)
  - [18. List a Group's Permissions](#18-list-a-groups-permissions)
  - [19. Add a Permission to a Group](#19-add-a-permission-to-a-group)
  - [20. Remove a Permission from a Group](#20-remove-a-permission-from-a-group)
- [Permission Management](#permission-management)
  - [21. List Permissions](#21-list-permissions)
  - [22. Create a Permission](#22-create-a-permission)
  - [23. Update a Permission](#23-update-a-permission)
  - [24. Delete a Permission](#24-delete-a-permission)
- [Health Check](#health-check)
  - [25. Check User Database Availability](#25-check-user-database-availability)
- [Rate Limits](#rate-limits)
- [Error Responses](#error-responses)

## General Information

- Base URL: `$BASE_URL`. The URLs below are same-origin browser paths. The gateway removes the `/user-api` prefix when forwarding requests.
- Authentication: the browser sends the `lens_session` cookie automatically. The acting user comes from the session; request bodies cannot select the acting `user_id`. Every `/user-api/v1/admin/*` endpoint requires `users.manage`.
- Write requests must include an `Origin` that exactly matches `BROWSER_ORIGIN`, including login and anonymous verification-code requests. A missing or mismatched origin returns HTTP 403.
- JSON request bodies use `application/json`, contain one object and are limited to 8192 bytes. Unknown fields, parsing failures or trailing data return HTTP 422. Responses use `Cache-Control: no-store`.

### Public User Information

| Field | Type | Description |
| --- | --- | --- |
| `user_id` | string | Stable user ID |
| `email` | string | Normalized email address |
| `display_name` | string | Display name; may be empty |

Successful user-information responses return this object directly, without a `user` wrapper, password hash or session token. The cookie uses `HttpOnly`, `Path=/` and `SameSite=Lax`. Public HTTPS uses `Secure` and `Max-Age=86400`, with no sliding renewal.

"Required" in parameter tables describes what callers must submit. The separate account-status endpoint must detect whether `active` is present and must not treat omission or `null` as `false`. Other retained endpoints apply their own business input checks. Passwords are not trimmed; email addresses are trimmed and lowercased. Endpoints without a body do not require JSON.

## Account Endpoints

### 1. Log In

- **URL**: `/user-api/v1/login`
- **Method**: `POST`
- **Description**: Validate the email address, password and account status. On success, create a 24-hour session and set the cookie.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | Yes | Account email address |
| `password` | string | Yes | Account password |

**Request Example**

```json
{
  "email": "researcher@example.test",
  "password": "example-only-password"
}
```

**Response Example (HTTP 200)**

```json
{
  "user_id": "user_example",
  "email": "researcher@example.test",
  "display_name": "Researcher"
}
```

An unknown email address, incorrect password or disabled account returns HTTP 401 / `invalid_credentials`. Login rate limits apply independently of the registration switch and count both successful and failed attempts.

### 2. Get the Current User

- **URL**: `/user-api/v1/me`
- **Method**: `GET`
- **Description**: Read public user information using the session in the current cookie.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "user_id": "user_example",
  "email": "researcher@example.test",
  "display_name": "Researcher"
}
```

A missing, expired or revoked session, or a disabled account, returns HTTP 401 / `authentication_required`.

### 3. Log Out

- **URL**: `/user-api/v1/logout`
- **Method**: `POST`
- **Description**: Revoke the current session and clear the cookie with the same name and path, using `MaxAge=-1`.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

An empty or already revoked token can also log out successfully. A database failure returns an error rather than claiming revocation succeeded. Sessions on other devices remain valid.

### 4. Change Your Password

- **URL**: `/user-api/v1/me/password`
- **Method**: `POST`
- **Description**: Use the current session and old password to change your own password, revoke all existing sessions for the account and clear the cookie.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `old_password` | string | Yes | Current password |
| `password` | string | Yes | New password, at least 12 bytes |

**Request Example**

```json
{
  "old_password": "example-only-password",
  "password": "example-replacement-password"
}
```

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

The frontend checks that the two new-password entries match; the API receives `password` once. A failed session or old-password check returns HTTP 401 / `authentication_required`. After success, all devices must log in again.

## Email Registration and Password Recovery

### 5. Send an Email Verification Code

- **URL**: `/user-api/v1/email-challenges`
- **Method**: `POST`
- **Description**: An anonymous caller requests a registration or password-recovery code. `REGISTRATION_ENABLED` must be enabled.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `email` | string | Yes | Valid email address, at most 254 bytes after normalization |
| `purpose` | string | Yes | `register` or `password_reset` |

**Request Example**

```json
{
  "email": "researcher@example.test",
  "purpose": "register"
}
```

**Response Example (HTTP 202)**

```json
{
  "challenge_id": "opaque-example",
  "expires_in": 600,
  "retry_after": 60
}
```

`challenge_id` identifies this verification task. `expires_in` and `retry_after` give the validity-period and resend-delay hints in seconds. Eligible addresses receive an email, and the task must reach `sent` before verification. Ineligible addresses receive the same HTTP 202 structure, but no usable proof is created and no email is sent. HTTP 202 does not guarantee inbox delivery; an SMTP failure returns an error.

### 6. Register an Account

- **URL**: `/user-api/v1/register`
- **Method**: `POST`
- **Description**: Consume a valid `register` proof to create an ordinary account with a verified email address. Registration does not assign groups or log the user in.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `challenge_id` | string | Yes | Task ID returned by the latest code request |
| `email` | string | Yes | Email address matching the task |
| `code` | string | Yes | Six-digit verification code; preserve leading zeros |
| `password` | string | Yes | 12-256 bytes |
| `display_name` | string | No | At most 200 bytes; trimmed before storage; defaults to an empty string |

**Request Example**

```json
{
  "challenge_id": "opaque-example",
  "email": "researcher@example.test",
  "code": "001234",
  "password": "example-only-password",
  "display_name": "Researcher"
}
```

**Response Example (HTTP 201)**

```json
{
  "user_id": "user_example",
  "email": "researcher@example.test",
  "display_name": "Researcher"
}
```

Success sets no cookie; the user logs in separately. The proof must be `sent`, unexpired, unconsumed and have `attempts < 5`. Resending replaces the previous task. An invalid proof returns HTTP 422 / `invalid_email_proof`; a valid proof racing with an existing email address returns HTTP 409 / `operation_conflict`.

### 7. Reset a Forgotten Password

- **URL**: `/user-api/v1/password-resets`
- **Method**: `POST`
- **Description**: Consume a `password_reset` proof, save the new password and revoke all existing sessions for that user.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `challenge_id` | string | Yes | Password-reset task ID |
| `email` | string | Yes | Task email address; the account must be active and email-verified |
| `code` | string | Yes | Six-digit verification code; preserve leading zeros |
| `password` | string | Yes | New password, 12-256 bytes |

**Request Example**

```json
{
  "challenge_id": "reset-task-example",
  "email": "researcher@example.test",
  "code": "005678",
  "password": "example-replacement-password"
}
```

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

No old session or password is required, and success does not create a session. Administrators do not set replacement passwords for users. Imported and bootstrapped accounts without verified email addresses can still log in with their original passwords and use authenticated password changes, but this scope provides no recovery entrypoint if they forget those passwords; email verification must not be bypassed. Disabling `REGISTRATION_ENABLED` disables code requests, registration and email recovery, while login and authenticated password changes remain available. Enabling public registration also requires an active administrator.

## Current User Permissions

### 8. Get the Current User's Permissions

- **URL**: `/user-api/v1/me/permissions`
- **Method**: `GET`
- **Description**: Authenticate the current session and return sorted, distinct permission codes granted by the active user's current group memberships.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "permission_codes": [
    "annotation.annotate",
    "research.read_all"
  ]
}
```

No additional permissions returns `permission_codes=[]`. A query failure returns an error, not a successful empty array. The frontend uses this result to display entrypoints; the backend still authorizes operations independently.

## User Administration

Ordinary new accounts use email registration. Annotation staff register first and administrators then assign their groups. Every administration endpoint below requires a valid session and `users.manage`, whether that permission comes from a built-in or custom group. Writes reauthenticate and authorize inside the administration transaction, then save the change and audit record; failures roll back. Disabling accounts, removing memberships or removing group permissions must leave at least one active account with `users.manage`.

### List Parameters and Common Responses

User, group, permission and both association lists accept these query parameters. The current user's `GET /me/permissions` still returns the complete effective permission-code set without pagination.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `limit` (query) | integer | No | Defaults to 50; range 1-200 |
| `offset` (query) | integer | No | Defaults to 0; must be at least 0 |

Paginated responses contain `items`, `total`, `limit` and `offset`. `total` counts matching records rather than records on this page. Users are sorted by `email`; other lists are sorted by `code`. Offset pagination does not provide a snapshot across requests.

Group responses contain `code`, `name`, `description` and `is_system`; permission objects use the same fields. Only migrations set `is_system`; callers cannot submit it. The four built-in groups and six built-in permissions have `is_system=true`; new entries have `false`. `code` is stable and cannot be renamed through update endpoints. A nonexistent user returns HTTP 422 / `invalid_request`; a nonexistent group or permission returns HTTP 422 / `invalid_reference`. Callers without authorization receive HTTP 403 before directory data can disclose whether a target exists.

### 9. List Users

- **URL**: `/user-api/v1/admin/users`
- **Method**: `GET`
- **Description**: Read user accounts. Group directories and membership associations are queried through their own endpoints.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "items": [
    {
      "user_id": "user_annotator",
      "email": "annotator@example.test",
      "display_name": "Annotator",
      "active": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Each item contains only `user_id`, `email`, `display_name` and `active`. Use the common pagination parameters above. No results returns `items=[]` and `total=0`; group memberships are queried separately.

### 10. Enable or Disable an Account

- **URL**: `/user-api/v1/admin/users/{user_id}/status`
- **Method**: `PATCH`
- **Description**: Change only the specified user's active status.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` (path) | string | Yes | Target stable user ID, 1-64 characters |
| `active` | boolean | Yes | Explicit `true` or `false`; omission or `null` returns HTTP 422 / `invalid_request` |

**Request Example**

```json
{
  "active": false
}
```

**Response Example (HTTP 200)**

```json
{
  "user_id": "user_annotator",
  "email": "annotator@example.test",
  "display_name": "Annotator",
  "active": false
}
```

Disabling the account and revoking all its existing sessions occur in one transaction. Reenabling it does not restore old sessions; the user must log in again. Disabling the last active administrator returns HTTP 409 / `operation_conflict`. This endpoint accepts only `active`; it cannot also change passwords, email addresses or groups.

## User Group Memberships

### 11. List a User's Groups

- **URL**: `/user-api/v1/admin/users/{user_id}/groups`
- **Method**: `GET`
- **Description**: Read the specified user's current group memberships.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` (path) | string | Yes | Target stable user ID, 1-64 characters |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "items": [
    {
      "code": "annotator",
      "name": "Annotator",
      "description": "Read all research data and revise shared samples",
      "is_system": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

Use the common administration pagination parameters; the result contains group objects. No memberships returns `items=[]` and `total=0`, which does not mean the account is missing. A nonexistent user returns HTTP 422 / `invalid_request`. The current user's effective permissions are still obtained through `GET /user-api/v1/me/permissions`.

### 12. Assign a Group to a User

- **URL**: `/user-api/v1/admin/users/{user_id}/groups/{group_code}`
- **Method**: `PUT`
- **Description**: Create an association between a user and an existing built-in or custom group.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` (path) | string | Yes | Target stable user ID, 1-64 characters |
| `group_code` (path) | string | Yes | Existing built-in or custom group code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

Repeated assignment succeeds without creating duplicate associations. A nonexistent user returns HTTP 422 / `invalid_request`; a nonexistent group returns HTTP 422 / `invalid_reference`. The group code is in the path rather than a `group` or `action` request body; the acting user comes from the session.

### 13. Remove a User's Group Membership

- **URL**: `/user-api/v1/admin/users/{user_id}/groups/{group_code}`
- **Method**: `DELETE`
- **Description**: Remove one existing group association from a user.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `user_id` (path) | string | Yes | Target stable user ID, 1-64 characters |
| `group_code` (path) | string | Yes | Existing built-in or custom group code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

If the user and group exist, the operation succeeds even when the association is already absent. A nonexistent user returns HTTP 422 / `invalid_request`; a nonexistent group returns HTTP 422 / `invalid_reference`. Removing the last active administrator's management capability returns HTTP 409 / `operation_conflict`. After success, the next permission check reads the updated associations; revoking every session is unnecessary.

## Permission Groups

Administrators can create custom groups, edit names and descriptions, and delete custom groups that no users belong to. Built-in groups allow metadata and permission-association changes, but cannot be deleted or have their codes changed. Separate endpoints add and remove group permissions; creating or editing a group does not silently replace its permission set.

### 14. List Permission Groups

- **URL**: `/user-api/v1/admin/groups`
- **Method**: `GET`
- **Description**: Read a page of built-in and custom groups for assigning user access.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "items": [
    {
      "code": "admin",
      "name": "System administrator",
      "description": "Manage accounts, permission groups and permissions",
      "is_system": true
    }
  ],
  "total": 4,
  "limit": 1,
  "offset": 0
}
```

The example uses `limit=1` and `offset=0`, with `total=4` for the initial four built-in groups. The common `limit` and `offset` parameters are supported.

### 15. Create a Permission Group

- **URL**: `/user-api/v1/admin/groups`
- **Method**: `POST`
- **Description**: Create a custom group with no initial permissions or members.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | Yes | 1-64 characters; starts with a lowercase letter and contains only lowercase letters, digits and underscores |
| `name` | string | Yes | 1-100 characters after trimming |
| `description` | string | No | At most 1000 characters; defaults to an empty string |

**Request Example**

```json
{
  "code": "senior_annotator",
  "name": "Senior annotator",
  "description": "Handle complex shared annotation tasks"
}
```

**Response Example (HTTP 201)**

```json
{
  "code": "senior_annotator",
  "name": "Senior annotator",
  "description": "Handle complex shared annotation tasks",
  "is_system": false
}
```

A duplicate `code` returns HTTP 409 / `already_exists`. `is_system` cannot be submitted. Creating a group does not assign the creator to it or add any permissions.

### 16. Update a Permission Group

- **URL**: `/user-api/v1/admin/groups/{group_code}`
- **Method**: `PATCH`
- **Description**: Change a group's name or description, updating only submitted fields.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `group_code` (path) | string | Yes | Target group code |
| `name` | string | No | If submitted, 1-100 characters after trimming |
| `description` | string | No | At most 1000 characters; an empty string clears the description |

**Request Example**

```json
{
  "name": "Advanced annotator"
}
```

**Response Example (HTTP 200)**

```json
{
  "code": "senior_annotator",
  "name": "Advanced annotator",
  "description": "Handle complex shared annotation tasks",
  "is_system": false
}
```

Submit at least one of `name` or `description`. `null` and unknown fields return HTTP 422 / `invalid_request`. Built-in groups also allow metadata changes; this endpoint does not modify `code`, `is_system`, members or group permissions.

### 17. Delete a Permission Group

- **URL**: `/user-api/v1/admin/groups/{group_code}`
- **Method**: `DELETE`
- **Description**: Delete a custom group that no users belong to, removing its permission associations in the same transaction.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `group_code` (path) | string | Yes | Target group code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

A built-in group returns HTTP 403 / `permission_denied`. Existing `user_groups` associations return HTTP 409 / `operation_conflict`: administrators must explicitly remove memberships first rather than silently revoke access in bulk by deleting a group. A nonexistent group returns HTTP 422 / `invalid_reference`. Deletion and auditing share one transaction; users and permissions are not cascade-deleted.

## Group Permission Associations

Administrators can change the permissions in a group. A user's effective permissions are the union of the permissions in all their groups, with duplicate codes removed.

### 18. List a Group's Permissions

- **URL**: `/user-api/v1/admin/groups/{group_code}/permissions`
- **Method**: `GET`
- **Description**: Read a page of permissions granted by the specified group.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `group_code` (path) | string | Yes | Target group code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "items": [
    {
      "code": "annotation.annotate",
      "name": "Shared annotation",
      "description": "Claim samples and save shared revisions",
      "is_system": true
    },
    {
      "code": "research.read_all",
      "name": "Read all research data",
      "description": "Read research data from all Collections",
      "is_system": true
    }
  ],
  "total": 2,
  "limit": 50,
  "offset": 0
}
```

The example is for `annotator`. Use the common `limit` and `offset` parameters. An existing group with no permissions returns an empty list; a nonexistent group returns HTTP 422 / `invalid_reference`.

### 19. Add a Permission to a Group

- **URL**: `/user-api/v1/admin/groups/{group_code}/permissions/{permission_code}`
- **Method**: `PUT`
- **Description**: Create an association between a group and an existing permission.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `group_code` (path) | string | Yes | Target group code |
| `permission_code` (path) | string | Yes | Target permission code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

There is no JSON body. Repeated addition succeeds without creating duplicate rows. A nonexistent group or permission returns HTTP 422 / `invalid_reference`. Built-in groups allow permission changes; active users belonging to the group receive the updated set on their next permission check.

### 20. Remove a Permission from a Group

- **URL**: `/user-api/v1/admin/groups/{group_code}/permissions/{permission_code}`
- **Method**: `DELETE`
- **Description**: Remove one permission association while retaining both the group and permission.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `group_code` (path) | string | Yes | Target group code |
| `permission_code` (path) | string | Yes | Target permission code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

If both resources exist, an already absent association succeeds. If removing `users.manage` would leave every active account without administration access, return HTTP 409 / `operation_conflict` and roll back; counting only members of the group named `admin` is insufficient. A nonexistent group or permission returns HTTP 422 / `invalid_reference`.

## Permission Management

Administrators can register permissions, edit their names and descriptions, and delete custom permissions that no groups reference. A new code can participate in group grants and `Check`, but only constrains a business operation after that operation's entrypoint explicitly checks it. Registering a permission does not automatically create an endpoint, button or business capability.

The six built-in permission codes are used by the associated business operations and cannot be deleted or renamed. Their names and descriptions can be edited. New permissions should use the stable codes agreed by the operations that check them.

### 21. List Permissions

- **URL**: `/user-api/v1/admin/permissions`
- **Method**: `GET`
- **Description**: Read a page of built-in and custom permissions.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "items": [
    {
      "code": "annotation.annotate",
      "name": "Shared annotation",
      "description": "Claim samples and save shared revisions",
      "is_system": true
    },
    {
      "code": "annotation.assign",
      "name": "Assign annotation tasks",
      "description": "Action permission for annotation task assignment",
      "is_system": false
    }
  ],
  "total": 7,
  "limit": 2,
  "offset": 0
}
```

The example uses `limit=2` and `offset=0`, with `total=7` for six built-in permissions plus one new permission. The common pagination parameters are supported. This directory is not the caller's granted permissions; obtain the current user's effective permissions through `GET /user-api/v1/me/permissions`.

### 22. Create a Permission

- **URL**: `/user-api/v1/admin/permissions`
- **Method**: `POST`
- **Description**: Register a custom action permission without automatically granting it to any group or user.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `code` | string | Yes | 1-128 characters with at least two dot-separated segments; each segment starts with a lowercase letter and may contain digits and underscores |
| `name` | string | Yes | 1-100 characters after trimming |
| `description` | string | No | At most 1000 characters; defaults to an empty string |

**Request Example**

```json
{
  "code": "annotation.assign",
  "name": "Assign annotation tasks",
  "description": "Action permission for annotation task assignment"
}
```

**Response Example (HTTP 201)**

```json
{
  "code": "annotation.assign",
  "name": "Assign annotation tasks",
  "description": "Action permission for annotation task assignment",
  "is_system": false
}
```

A duplicate `code` returns HTTP 409 / `already_exists`. The example `annotation.assign` represents a capability awaiting business integration. The existing tutorial has no annotation-assignment endpoint; registering this code does not implement that feature. Requests cannot set `is_system`.

### 23. Update a Permission

- **URL**: `/user-api/v1/admin/permissions/{permission_code}`
- **Method**: `PATCH`
- **Description**: Change only a permission's name or description.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `permission_code` (path) | string | Yes | Target permission code |
| `name` | string | No | If submitted, 1-100 characters after trimming |
| `description` | string | No | At most 1000 characters; an empty string clears the description |

**Request Example**

```json
{
  "description": "Allow task assignment in the annotation assignment workflow"
}
```

**Response Example (HTTP 200)**

```json
{
  "code": "annotation.assign",
  "name": "Assign annotation tasks",
  "description": "Allow task assignment in the annotation assignment workflow",
  "is_system": false
}
```

Submit at least one field. `null`, `code`, `is_system` and other unknown fields return HTTP 422 / `invalid_request`. Metadata changes do not change the code checked by business entrypoints or its group associations.

### 24. Delete a Permission

- **URL**: `/user-api/v1/admin/permissions/{permission_code}`
- **Method**: `DELETE`
- **Description**: Delete a custom permission that no groups reference.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `permission_code` (path) | string | Yes | Target permission code |

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

A built-in permission returns HTTP 403 / `permission_denied`. Existing `group_permissions` references return HTTP 409 / `operation_conflict`; remove those associations explicitly first. A nonexistent permission returns HTTP 422 / `invalid_reference`. Deletion does not remove checks from business code; subsequent `Check` calls for the missing code return `false`.

## Health Check

### 25. Check User Database Availability

- **URL**: `/user-api/ready`
- **Method**: `GET`
- **Description**: Confirm that the user database is accessible. Login is not required.

No JSON request body.

**Response Example (HTTP 200)**

```json
{
  "ok": true
}
```

Dependency failures follow the error table. A successful readiness check does not prove SMTP, Lens or all application operations are available.

## Rate Limits

| Operation | IP Limit | Email Limit | Additional Cooldown |
| --- | --- | --- | --- |
| Login | 60 requests / 900 seconds | 10 requests / 900 seconds | None |
| Send a code | 20 requests / 3600 seconds | 5 requests / 3600 seconds | 1 request / 60 seconds per email and purpose |
| Verify a code | 60 requests / 900 seconds | 20 requests / 900 seconds | None |

Counters are shared through the database and survive process restarts. `X-Real-IP` is accepted only when the direct peer matches `TRUSTED_PROXY_IP`; other callers cannot override their source IP. Exceeding a limit rolls back that request's reservations. Committed successful and failed login attempts count without changing the account's `active` flag. HTTP 429 includes both a `Retry-After` header and a `retry_after` response field, in seconds and at least 1.

## Error Responses

Ordinary errors contain only a top-level `code`:

```json
{
  "code": "authentication_required"
}
```

Rate-limit example: HTTP 429, `Retry-After: 60`:

```json
{
  "code": "rate_limited",
  "retry_after": 60
}
```

| HTTP | code | Meaning |
| --- | --- | --- |
| 401 | invalid_credentials | Login email unknown, password incorrect or account disabled |
| 401 | authentication_required | Other session or old-password authentication failure |
| 403 | permission_denied | Origin, permission, registration-switch or built-in group/permission deletion rejected |
| 422 | invalid_request | Invalid JSON or business input |
| 422 | invalid_email_proof | Incorrect, replaced, consumed, expired or ineligible email proof |
| 422 | invalid_reference | An administration request references a nonexistent group or permission |
| 409 | operation_conflict | Proof race, last-administrator protection or deletion of a referenced group/permission |
| 409 | already_exists | The group or permission code being created already exists |
| 429 | rate_limited | Rate window or cooldown exceeded |
| 503 | identity_unavailable | Recognized connection, network or temporary SMTP dependency failure |
| 500 | internal_error | Unknown internal failure or an unclassified database error |

Application errors do not expose SQL, passwords, tokens, verification codes or SMTP diagnostics. The default chi 404/405 responses are not guaranteed to use this JSON format. User-service HTTP endpoints do not define `Idempotency-Key`. For both association types, repeated `PUT`/`DELETE` requests succeed when the target association is already present/absent; a network retry does not establish whether another write succeeded previously.
