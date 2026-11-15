# User service

V1 provides a standalone HTTP identity service backed by PostgreSQL. It creates
the initial account locally and supports password login, session lookup and
logout. V2 adds authenticated self-service password changes and revokes all
existing sessions for that account. V3 adds email-verified registration,
email-based password recovery, SMTP delivery and persistent rate limits. V4
adds the mTLS gRPC Resolve endpoint for Lens and same-origin browser login
through `/user-api`. V6 adds permission reads, user activation and group
memberships, group/permission catalog management, first-administrator setup
and the gRPC Check implementation.

The service stores PBKDF2-SHA256 password hashes and SHA-256 session-token
digests. Sessions expire after 24 hours; revoked sessions and disabled accounts
cannot authenticate. The `lens_session` cookie is HttpOnly, SameSite=Lax and
Secure unless local HTTP development explicitly disables Secure.

## Generate and build

Run from `user-service/` with the Go version declared in `go.mod`:

```sh
go mod download
go build -o /tmp/lens-user-service ./cmd/user-service
```

Generated Protobuf sources are committed in `internal/gen/userv1/` and in
`../backend/lens/user/v1/`. After changing `proto/lens/user/v1/auth.proto`, run
from the repository root with protoc 29.3, protoc-gen-go 1.36.6 and
protoc-gen-go-grpc 1.5.1 available:

```sh
protoc -I user-service/proto \
  --go_out=user-service --go_opt=module=github.com/JeanphiloGong/tsingai-lens/user-service \
  --go-grpc_out=user-service --go-grpc_opt=module=github.com/JeanphiloGong/tsingai-lens/user-service \
  user-service/proto/lens/user/v1/auth.proto
backend/.venv/bin/python -m grpc_tools.protoc -I user-service/proto \
  --python_out=backend --grpc_python_out=backend \
  user-service/proto/lens/user/v1/auth.proto
```

`internal/db/` is generated from `migrations/` and `db/queries/` and committed
to Git. Building a checkout does not require sqlc. After changing SQL sources,
regenerate the Go files with sqlc v1.30.0:

```sh
sqlc generate
```

Commit the SQL sources and generated Go changes together. Do not hand-edit
generated files.

## Run locally

Use a separate PostgreSQL instance for this local tutorial. The default
`127.0.0.1:55447` port keeps it separate from other Lens development databases.
Create the instance and its two databases once:

```sh
podman run -d --name lens-user-tutorial-local --security-opt label=disable -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1:55447:5432 docker.io/library/postgres:18-bookworm
podman exec lens-user-tutorial-local pg_isready -U postgres
podman exec lens-user-tutorial-local createdb -U postgres lens_users_test
podman exec lens-user-tutorial-local createdb -U postgres lens_users_demo
```

Wait until `pg_isready` reports that PostgreSQL accepts connections before
running `createdb`. These defaults use passwordless authentication for local
tutorial use on the loopback interface. To restart an existing stopped
container, run `podman start lens-user-tutorial-local`.

Copy `.env.example` to `.env` once, keeping any existing local configuration:

```sh
cp -n .env.example .env
```

The Go entrypoint reads process environment variables; neither it nor the
Goose commands below automatically load this file. Load it in each terminal
before using the service or its database commands:

```sh
set -a
. ./.env
set +a
```

With Goose v3.24.3 available, apply pending migrations to both databases:

```sh
goose -dir migrations postgres "$TEST_USER_DATABASE_URL" up
goose -dir migrations postgres "$USER_DATABASE_URL" up
```

Set `BOOTSTRAP_EMAIL` and `BOOTSTRAP_PASSWORD` locally, then initialize the
empty database once:

```sh
/tmp/lens-user-service bootstrap
/tmp/lens-user-service grant-initial-admin
unset BOOTSTRAP_EMAIL BOOTSTRAP_PASSWORD
```

Before starting the server, configure the mTLS material described below; then
run `HTTP_ADDR=127.0.0.1:8097 BROWSER_ORIGIN=http://127.0.0.1:5196 COOKIE_SECURE=false /tmp/lens-user-service`.

The initial password must contain at least 12 bytes. Bootstrap creates an
account; the second command assigns the built-in admin group to that existing
active account. A second bootstrap is rejected, and first-administrator setup
is rejected once an effective administrator already exists. Browser writes must include an Origin matching `BROWSER_ORIGIN`.
Account routes are `POST /v1/login`, `GET /v1/me`, `POST /v1/logout`, and
`POST /v1/me/password`. The password endpoint accepts `old_password` and
`password`, requires the current session, and clears the current cookie after
success; the database revokes every older session for that account.
Login throttling applies even when registration is disabled. IP limits use the
direct TCP peer by default. When `TRUSTED_PROXY_IP` names that exact peer, a
single valid `X-Real-IP` value is accepted; the deployment Nginx overwrites this
header. Never trust arbitrary clients' forwarded headers. SIGINT/SIGTERM starts
graceful HTTP shutdown with a five-second timeout and stops the gRPC server.

`GET /ready` pings PostgreSQL and returns `{"ok":true}` on success or HTTP 503
when the database is unavailable. It does not require or create a session.
The [deployment bundle](../deploy/README.md) owns production HTTPS, certificate
mounts, the user-service image, explicit migrations, backups and CI/CD setup.

## V4 mTLS and Lens integration

The HTTP and gRPC listeners share one Service and PostgreSQL pool. Set
`RPC_ADDR`, `RPC_CERT`, `RPC_KEY` and `RPC_CA` before starting the server.
The certificate and matching key identify this service; the CA pool verifies
client certificates. TLS 1.3 and a trusted client certificate are required.
No permission tables or Check requests are required for login or Resolve.

For disposable local development, create certificates outside the repository.
Run these commands in the same shell before starting either service:

```sh
CERT_DIR=$(mktemp -d /tmp/lens-identity-certs.XXXXXX)
chmod 700 "$CERT_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=lens-dev-ca -keyout "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt"
openssl req -newkey rsa:2048 -nodes -subj /CN=localhost -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.csr"
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' > "$CERT_DIR/server.ext"
openssl x509 -req -days 2 -in "$CERT_DIR/server.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial -extfile "$CERT_DIR/server.ext" -out "$CERT_DIR/server.crt"
openssl req -newkey rsa:2048 -nodes -subj /CN=lens-backend -keyout "$CERT_DIR/client.key" -out "$CERT_DIR/client.csr"
printf 'extendedKeyUsage=clientAuth\n' > "$CERT_DIR/client.ext"
openssl x509 -req -days 2 -in "$CERT_DIR/client.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial -extfile "$CERT_DIR/client.ext" -out "$CERT_DIR/client.crt"
chmod 600 "$CERT_DIR/"*.key
export RPC_ADDR=127.0.0.1:50057
export RPC_CERT="$CERT_DIR/server.crt" RPC_KEY="$CERT_DIR/server.key" RPC_CA="$CERT_DIR/ca.crt"
export USER_RPC_TARGET=localhost:50057
export USER_RPC_CERT="$CERT_DIR/client.crt" USER_RPC_KEY="$CERT_DIR/client.key" USER_RPC_CA="$CERT_DIR/ca.crt"
```

Pass the `USER_RPC_*` variables to Lens. Its Web lifespan owns the asynchronous
channel and closes it on shutdown. Each protected Lens request resolves the
cookie through gRPC, then retains its resource ownership checks. Missing or
revoked sessions return HTTP 401; identity dependency failures return 503.
The old Lens `/api/v1/auth/*` endpoints and local identity tables are removed.
Browser login, current-user and logout use `/user-api/v1/*`, proxied to this
service with `USER_SERVICE_ORIGIN=http://127.0.0.1:8097` in frontend development.

Development certificates expire after two days. Production certificate
issuance/rotation and HTTPS ingress belong to the later launch checkpoint.
Existing Lens databases require stopped writes, verified account import and a
recoverable backup before migration 0099; this development checkpoint only
replays fresh synthetic databases. Keep V1–V3 demo data separate.

## V6 permissions and administration

When upgrading a V5 database, apply pending Goose migrations and rebuild the
binary with the commands above. Set `BOOTSTRAP_EMAIL` to an existing active
account, then run `/tmp/lens-user-service grant-initial-admin` once. Existing
accounts do not need another `bootstrap`; it is only for an empty user database.

The [HTTP contract](docs/http-api.md#current-user-permissions) owns request and
response fields. `GET /v1/me/permissions` returns the current effective codes;
an ordinary registered account receives `{"permission_codes":[]}`. Management
routes under `/v1/admin/` require a valid session and `users.manage`:

- Users: paginated lists, enable/disable, and group membership reads/grants/removals.
- Groups and permissions: paginated catalogs, create, update display metadata,
  and delete unused custom entries; group permission associations are managed
  separately.

Group/permission codes are stable keys. PATCH changes name/description only;
clients cannot rename codes or set `is_system`. Built-in entries cannot be
deleted. Groups with members and permission codes still assigned to groups
return a conflict on deletion. Ordinary accounts use email registration;
there is no administrator account-creation or password-reset endpoint.

Migration 00003 seeds four groups and six permission codes; 00004 adds catalog
metadata and structured audit details while preserving existing associations.
The admin group initially grants only `users.manage`. Scientific read,
annotation and publication codes are registered for subsequent capabilities;
their business entrypoints are outside V6. Registering a code does not add an
automatic enforcement rule.

First-administrator setup uses the existing account specified by
`BOOTSTRAP_EMAIL`, requires an enabled account and no current effective
administrator, and records the grant atomically. It does not infer authority
from a display name. With `REGISTRATION_ENABLED=true`, startup refuses to serve
until an enabled account has `users.manage`; custom management groups count.
Normal startup does not grant or restore group memberships.

Every administrative write takes the shared administration lock, rechecks the
actor's current session and effective permission, and saves its audit in the
same transaction. Failures roll back the entire operation. Disabling an account
also revokes its sessions; enabling it does not revive them. Removing access
must leave at least one enabled account with `users.manage`, including access
from custom groups. The audit stores actor, target type/ID, action and changed
metadata, with no passwords or tokens.

The [gRPC contract](docs/grpc-api.md#2-check-an-action-permission-check) exposes
`Check(session_token, permission_code)`. The server resolves the session before
each check and returns `allowed=false` for missing permissions. Lens's
`IdentityClient.check` distinguishes that denial from authentication errors and
transport failures. There is no permission cache or caller-selected subject.
Lens's existing resource ownership checks continue to apply independently.
The administration browser UI belongs to V7.

## V3 email registration and recovery

Registration is disabled by default. For a local SMTP receiver listening on
`127.0.0.1:1025`, set these process variables before starting the service:

```sh
export REGISTRATION_ENABLED=true
export SMTP_ADDR=127.0.0.1:1025
export SMTP_FROM='Lens <noreply@example.test>'
export SMTP_TLS_MODE=none
read -r -s -p 'Challenge secret (at least 32 bytes): ' CHALLENGE_SECRET
printf '\n'
export CHALLENGE_SECRET
/tmp/lens-user-service
```

Keep `CHALLENGE_SECRET` stable across restarts and outside Git. Use a private
local configuration value rather than a committed example secret. Set
`SMTP_TLS_MODE=tls` for implicit TLS (usually port 465), `starttls` for an SMTP
connection upgraded to TLS (usually port 587), or `none` for plaintext on literal
loopback addresses only. If omitted, the entrypoint defaults to `starttls`;
unrecognized modes are rejected before connecting. Both encrypted modes verify
the server certificate and hostname and require TLS 1.2 or later, before sending
credentials. `SMTP_USER` and `SMTP_PASSWORD` are provider credentials when needed.
`SMTP_TLS_MODE` replaces the former `SMTP_TLS` boolean; update existing env files.
Neither the example configuration nor the service starts a mail receiver.

Verification emails include an origination `Date`, a unique `Message-ID` and
`MIME-Version`. After SMTP accepts DATA, the service logs the message ID and
purpose without the recipient address, verification code or credentials.
Acceptance and the challenge's `sent` state mean the provider queued the email;
they do not confirm delivery to the recipient's inbox. Use the message ID and
provider delivery reports or bounces when diagnosing missing mail.

For QQ Mail, enable SMTP in the mailbox settings and use:

```dotenv
SMTP_ADDR=smtp.qq.com:465
SMTP_TLS_MODE=tls
SMTP_FROM='Lens <your-account@qq.com>'
SMTP_USER=your-account@qq.com
SMTP_PASSWORD='replace-with-a-new-mailbox-authorization-code'
```

The sender must use the authorized QQ mailbox. Store the authorization code only
in private configuration; it is not the QQ login password. This sends from the QQ
address and does not require DNS changes to the Lens website domain.

The standalone HTTP routes are:

| Route | Result |
| --- | --- |
| `POST /v1/email-challenges` | Request a `register` or `password_reset` code; return `challenge_id`, `expires_in` and `retry_after` |
| `POST /v1/register` | Consume a sent, valid email proof; create a verified ordinary account without logging in |
| `POST /v1/password-resets` | Consume a recovery proof; replace the password and revoke all old sessions atomically |

The [HTTP contract](docs/http-api.md#email-registration-and-password-recovery)
defines their JSON fields. Direct service requests omit the gateway's
`/user-api` prefix. Anonymous writes still require the configured `Origin`.
Codes expire after ten minutes, permit five incorrect attempts and can succeed
only once. Resending replaces the previous challenge. SMTP failures cannot
produce a usable proof; ineligible addresses receive an opaque response without
mail delivery. Imported and bootstrap accounts have no verified email record
and cannot use email recovery.

Rate counters survive service restarts. Sending allows 20 requests per IP and
5 per email per hour, with a 60-second cooldown per email/purpose. Verification
allows 60 per IP and 20 per email per 15 minutes. Login allows 60 per IP and 10
per normalized email per 15 minutes, counting successful and failed logins.
HTTP 429 includes `Retry-After` and the matching JSON `retry_after` in seconds.

## Test

Set `TEST_USER_DATABASE_URL` to a **disposable database whose name ends in
`_test`**, separate from the running service database. Integration tests clear
its account, challenge and rate-limit data. Apply migrations and run packages serially:

```sh
goose -dir migrations postgres "$TEST_USER_DATABASE_URL" up
go test -race -p 1 ./... -count=1
go vet ./...
```

Without `TEST_USER_DATABASE_URL`, database tests explicitly skip; the domain,
password and error-contract unit tests still run. A configured database with a
different naming suffix is rejected before clearing data. The suite exercises
initial-account and administrator concurrency, password verification, token-digest persistence,
login/current-user/logout, self-service password changes, session expiry and
revocation, disabled accounts, Cookie/Origin rules, strict JSON parsing and
dependency/internal error handling.

V3 tests start their own loopback SMTP receivers using the Go standard library;
they require no external mail provider or extra test dependency. They exercise
real PostgreSQL transactions, concurrent one-time consumption, wrong-attempt
persistence, replacement/expiry, SMTP rejection, recovery revocation, disabled
registration, login throttling, and rollback when proof consumption fails.
Transport tests use temporary local certificates and SMTP receivers to verify
implicit TLS and STARTTLS delivery with authentication, certificate and hostname
rejection before credentials, lack of STARTTLS support and handshake deadlines.
They do not contact a provider or use real SMTP credentials.

V6 adds catalog, staff and administration transaction tests, including last
administrator races, rejected audit writes, immediate permission revocation,
protected built-in entries, credential-change reauthentication and concurrent
password recovery/disable. These tests use the same guarded disposable
`*_test` database; run packages serially as shown above.
