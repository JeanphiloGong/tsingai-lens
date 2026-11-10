# User service

V1 provides a standalone HTTP identity service backed by PostgreSQL. It creates
the initial account locally and supports password login, session lookup and
logout. Lens and browser integration, password changes, registration and
permissions belong to later tutorial versions.

The service stores PBKDF2-SHA256 password hashes and SHA-256 session-token
digests. Sessions expire after 24 hours; revoked sessions and disabled accounts
cannot authenticate. The `lens_session` cookie is HttpOnly, SameSite=Lax and
Secure unless local HTTP development explicitly disables Secure.

## Generate and build

Run from `user-service/` with the Go version declared in `go.mod`, sqlc v1.30.0
and Goose v3.24.3 available:

```sh
sqlc generate
go mod download
go build -o /tmp/lens-user-service ./cmd/user-service
```

`internal/db/` is generated from `migrations/` and `db/queries/`; regenerate it
instead of editing or committing the generated files.

## Run locally

Use a separate database owned by this service. Set `USER_DATABASE_URL`, then
apply its migration:

```sh
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
Routes are `POST /v1/login`, `GET /v1/me`, and `POST /v1/logout`.
This V1 checkpoint is for local use; login throttling and public HTTPS setup
are introduced in later versions. SIGINT/SIGTERM starts graceful HTTP shutdown
with a five-second timeout.

## Test

Set `TEST_USER_DATABASE_URL` to a **disposable database whose name ends in
`_test`**, separate from the running service database. Integration tests clear
its account/session data. Apply migrations and run packages serially:

```sh
goose -dir migrations postgres "$TEST_USER_DATABASE_URL" up
go test -race -p 1 ./... -count=1
go vet ./...
```

Without `TEST_USER_DATABASE_URL`, database tests explicitly skip; the domain,
password and error-contract unit tests still run. A configured database with a
different naming suffix is rejected before clearing data. The suite exercises
initial-account concurrency, password verification, token-digest persistence,
login/current-user/logout, session expiry and revocation, disabled accounts,
Cookie/Origin rules, strict JSON parsing and dependency/internal error handling.
