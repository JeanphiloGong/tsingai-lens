# User service

V1 provides a standalone HTTP identity service backed by PostgreSQL. It creates
the initial account locally and supports password login, session lookup and
logout. V2 adds authenticated self-service password changes and revokes all
existing sessions for that account. V3 adds email-verified registration,
email-based password recovery, SMTP delivery and persistent rate limits. Lens,
browser integration and permissions belong to later tutorial versions.

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
unset BOOTSTRAP_EMAIL BOOTSTRAP_PASSWORD
HTTP_ADDR=127.0.0.1:8097 BROWSER_ORIGIN=http://127.0.0.1:5196 COOKIE_SECURE=false /tmp/lens-user-service
```

The initial password must contain at least 12 bytes. A second bootstrap is
rejected. Browser writes must include an Origin matching `BROWSER_ORIGIN`.
Account routes are `POST /v1/login`, `GET /v1/me`, `POST /v1/logout`, and
`POST /v1/me/password`. The password endpoint accepts `old_password` and
`password`, requires the current session, and clears the current cookie after
success; the database revokes every older session for that account.
Login throttling applies even when registration is disabled. This checkpoint
uses the direct TCP peer for IP limits and ignores forwarded IP headers; public
HTTPS and trusted-proxy setup belong to later versions. SIGINT/SIGTERM starts graceful HTTP shutdown
with a five-second timeout.

## V3 email registration and recovery

Registration is disabled by default. For a local SMTP receiver listening on
`127.0.0.1:1025`, set these process variables before starting the service:

```sh
export REGISTRATION_ENABLED=true
export SMTP_ADDR=127.0.0.1:1025
export SMTP_FROM='Lens <noreply@example.test>'
export SMTP_TLS=false
read -r -s -p 'Challenge secret (at least 32 bytes): ' CHALLENGE_SECRET
printf '\n'
export CHALLENGE_SECRET
/tmp/lens-user-service
```

Keep `CHALLENGE_SECRET` stable across restarts and outside Git. Use a private
local configuration value rather than a committed example secret. Plaintext
SMTP is allowed only for literal loopback addresses. External SMTP requires
STARTTLS; `SMTP_USER` and `SMTP_PASSWORD` are optional provider credentials.
Neither the example configuration nor the service starts a mail receiver.

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
initial-account concurrency, password verification, token-digest persistence,
login/current-user/logout, self-service password changes, session expiry and
revocation, disabled accounts, Cookie/Origin rules, strict JSON parsing and
dependency/internal error handling.

V3 tests start their own loopback SMTP receivers using the Go standard library;
they require no external mail provider or extra test dependency. They exercise
real PostgreSQL transactions, concurrent one-time consumption, wrong-attempt
persistence, replacement/expiry, SMTP rejection, recovery revocation, disabled
registration, login throttling, and rollback when proof consumption fails.
