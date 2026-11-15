# User Identity gRPC API

- [General Information](#general-information)
- [1. Resolve the Current Identity: Resolve](#1-resolve-the-current-identity-resolve)
- [2. Check an Action Permission: Check](#2-check-an-action-permission-check)
- [Error Results](#error-results)
- [Protobuf Definition](#protobuf-definition)

## General Information

- Service: `lens.user.v1.Identity`; the caller is the Lens backend. Browsers use the [HTTP API](http-api.md).
- Connection: mTLS with a minimum of TLS 1.3. Verify both parties' certificates and the server target name; connections without a trusted client certificate are rejected.
- Timeout: Lens sets a one-second deadline for each call, with no automatic retries or local permission cache.
- Server configuration: `RPC_ADDR`, `RPC_CERT`, `RPC_KEY`, `RPC_CA`; Lens configuration: `USER_RPC_TARGET`, `USER_RPC_CA`, `USER_RPC_CERT`, `USER_RPC_KEY`.
- Resolve looks up an existing session and does not create a login. Check evaluates one permission code; use HTTP to retrieve all permissions for display.

## 1. Resolve the Current Identity: Resolve

- **Method**: `/lens.user.v1.Identity/Resolve`
- **Description**: Authenticate the session and return a trusted user identity. Lens then checks resource ownership and business state.

| Request Field | Protobuf Type / Field Number | Required | Description |
| --- | --- | --- | --- |
| session_token | string / 1 | Yes | Raw random token from the cookie, not the database digest |

**Request Example**

```json
{
  "session_token": "example-session-token"
}
```

**Response Example**

```json
{
  "user_id": "user_example",
  "email": "researcher@example.test",
  "display_name": "Researcher"
}
```

| Response Field | Protobuf Type / Field Number | Description |
| --- | --- | --- |
| user_id | string / 1 | Trusted subject; nonempty on success |
| email | string / 2 | Public email address |
| display_name | string / 3 | Display name |

JSON examples use the original field names for readability; actual transport uses Protobuf. The service checks required fields; an omitted proto3 string defaults to an empty string. A missing token, unknown session, expired or revoked session, or disabled account returns Unauthenticated.

## 2. Check an Action Permission: Check

- **Method**: `/lens.user.v1.Identity/Check`
- **Description**: Authenticate the current session again and check whether its user has the specified permission. A separate subject_id or user_id is not accepted.

| Request Field | Protobuf Type / Field Number | Required | Description |
| --- | --- | --- | --- |
| session_token | string / 1 | Yes | Current session token |
| permission_code | string / 2 | Yes | Action permission code to check |

**Request Example**

```json
{
  "session_token": "example-session-token",
  "permission_code": "research.read_all"
}
```

**Response Example**

```json
{
  "allowed": true
}
```

| Response Field | Protobuf Type / Field Number | Description |
| --- | --- | --- |
| allowed | bool / 1 | true when currently authorized; false when unauthorized or the permission code does not exist |

allowed=false is a normal result, not a dependency failure. An invalid session returns Unauthenticated; returning false must not hide an authentication failure. After a group membership is revoked, the next Check reads the current associations. Lens still determines Collection ownership, the assignee and revision state. The two RPCs do not guarantee a distributed permission snapshot or automatically cancel business requests that have already started.

## Error Results

| Result | gRPC Status / Code | Lens Boundary |
| --- | --- | --- |
| Invalid session | Unauthenticated / authentication_required | HTTP 401, business code 200301 |
| Valid session without the permission | OK / allowed=false | Operations requiring the permission return HTTP 403 / 200203; optional access to all research data also considers ownership |
| Known dependency failure | Unavailable / identity_unavailable | HTTP 503 / 200205 |
| Unknown internal failure | Internal / internal_error | Lens maps RPC failures other than authentication failures to HTTP 503 / 200205 |
| Timeout, certificate or connection failure | No trusted result | HTTP 503; do not guess the identity or grant permission |

## Protobuf Definition

The complete target protocol follows. V4 introduces only Resolve and its request and reply messages; V6 adds Check. Go and Python stubs are generated from the protocol. Do not change field numbers arbitrarily or call methods that are not yet provided in V4.

```proto
syntax = "proto3";
package lens.user.v1;
option go_package = "github.com/JeanphiloGong/tsingai-lens/user-service/internal/gen/userv1";
service Identity {
  rpc Resolve(ResolveRequest) returns (ResolveReply);
  rpc Check(CheckRequest) returns (CheckReply);
}
message ResolveRequest { string session_token = 1; }
message ResolveReply { string user_id = 1; string email = 2; string display_name = 3; }
// Resolve the session again on Check; clients cannot nominate another subject.
message CheckRequest { string session_token = 1; string permission_code = 2; }
message CheckReply { bool allowed = 1; }
```
