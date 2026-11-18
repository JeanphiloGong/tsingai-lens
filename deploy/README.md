# TsingAI-Lens Deploy Bundle

This is the repository's Docker Compose entrypoint. One version selects the
frontend, backend/worker and user-service images. PostgreSQL hosts separate
`lens` and `lens_users` databases with separate application roles. Only the
frontend publishes host ports; it terminates HTTPS and routes `/api/` to Lens
and `/user-api/` to user-service. Lens uses mTLS for identity RPC.

Use Docker Engine with Compose v2. `scripts/lens` calls `docker compose`.
Podman users can issue the same Compose commands through a compatible Podman
API socket. Source development remains in the module READMEs.

## Install the bundle

Select a stable version whose **three-image release workflow has succeeded**.
The older v0.13.14 image set does not contain the new user-service. Replace the
version below with the actual released tag; installation downloads the bundle
from that same tag.

```bash
version=vX.Y.Z
curl -fsSL "https://raw.githubusercontent.com/JeanphiloGong/tsingai-lens/$version/deploy/install.sh" \
  | sh -s -- --version "$version" --dir lens-deploy
cd lens-deploy
```

The installer preserves existing `.env`, `backend.env` and `user-service.env`.
It creates missing files privately, but does not initialize databases, import
accounts, grant permissions or start applications.

## Runtime configuration

Set these values in `.env`:

| Setting | Purpose |
| --- | --- |
| `LENS_VERSION` | One published stable tag for all three images |
| `POSTGRES_PASSWORD` | Existing Lens database password, or a new 64-character hexadecimal value for a fresh volume |
| `LENS_USERS_PASSWORD` | Separate 64-character hexadecimal identity database password |
| `LENS_PUBLIC_URL` | Exact HTTPS origin, for example `https://lens.example.com` or `https://localhost:8443`; no path or trailing slash |
| `LENS_HTTP_PORT`, `LENS_HTTPS_PORT` | Host ports mapped to HTTP redirect and HTTPS; default 8080/8443 |
| `LENS_PROXY_IP`, `LENS_NETWORK_SUBNET` | Fixed frontend address and private subnet; change together if the default network overlaps another deployment |

Generate each new password with `openssl rand -hex 32`. Changing `.env` does
not rotate an existing PostgreSQL role's password. The preparation script keeps
existing roles and databases unchanged. Compose injects database URLs, public
origin and trusted proxy address; do not duplicate them in service env files.

`backend.env` owns worker LLM and embedding settings. Chat model credentials use
the database and the separate [model master-key file](../backend/docs/runbooks/model-key-operations.md).
`user-service.env` owns SMTP, the challenge secret and registration availability.
Keep registration disabled until an active administrator and actual SMTP
configuration are verified. Use a stable random `CHALLENGE_SECRET` of at least
32 bytes. Set `SMTP_TLS_MODE=tls` for implicit TLS, such as `smtp.qq.com:465`,
or `SMTP_TLS_MODE=starttls` for SMTP upgraded to TLS, usually on port 587.
Both modes verify the server certificate and hostname. Replace the former
`SMTP_TLS` boolean in existing env files with the appropriate mode. Plaintext
`none` is limited to literal loopback addresses; the development mailbox is
not part of this production bundle. For QQ Mail, use the authorized QQ address
as both `SMTP_USER` and `SMTP_FROM` (optionally with a display name), and its
mailbox authorization code as `SMTP_PASSWORD`. Keep that code in the private
`user-service.env`; the website domain needs no mail DNS changes for this sender.

Secrets and private keys belong on the host, outside Git and image layers.
Compose `config` includes environment values: use `config -q` for validation and
never publish rendered configuration output.

## Certificates and request boundaries

Provision these files before startup:

```text
public-tls/tls.crt              public HTTPS certificate chain
public-tls/tls.key              matching HTTPS private key
identity-certs/ca.crt           trusted identity CA certificate
identity-certs/server.crt       user-service certificate; SAN includes DNS:user-service
identity-certs/server.key       user-service private key
identity-certs/client.crt       Lens client certificate with clientAuth usage
identity-certs/client.key       Lens client private key
```

Only the owning service's private key is mounted into it. The CA private key
stays with the issuer. User-service runs as UID/GID 65532; give that identity
read access to its mounted certificate/key, for example group 65532 with mode
0640 for `server.key` and traversable parent directories. Keep the remaining
private keys readable only by their operators/owning services. SELinux mounts
use `:z` for the shared CA and `:Z` for private mounts and backend data.

Nginx replaces `X-Real-IP` with its actual TCP peer; user-service trusts that
header only from `LENS_PROXY_IP`. Direct connections cannot nominate a new IP.
`COOKIE_SECURE=true` and the exact public origin apply to browser writes.
`/user-api/ready` checks database connectivity, without sending email or
creating sessions. `doctor --running` also verifies mTLS from the backend.
Public certificate issuance/renewal and real SMTP delivery remain operator
responsibilities.

## Fresh installation

Use this path only for an empty Lens database and an empty identity account
table. Existing accounts require the cutover procedure below.

Create the [model master-key file](../backend/docs/runbooks/model-key-operations.md#prepare-a-deployment)
before starting the backend.

```bash
docker compose --env-file .env -f compose.yml up -d postgres
./scripts/prepare-identity.sh

set -a
. ./.env
set +a
export GOOSE_DRIVER=postgres
export GOOSE_DBSTRING="postgres://lens_users:$LENS_USERS_PASSWORD@postgres:5432/lens_users"
docker compose --env-file .env -f compose.yml run --rm --no-deps \
  -e GOOSE_DRIVER -e GOOSE_DBSTRING --entrypoint goose user-service -dir /app/migrations up
docker compose --env-file .env -f compose.yml run --rm --no-deps backend alembic upgrade head
```

In a Bash terminal, create and authorize the first account without putting its
password in shell history:

```bash
read -r -p 'Initial account email: ' BOOTSTRAP_EMAIL
read -r -s -p 'Initial password (at least 12 bytes): ' BOOTSTRAP_PASSWORD
printf '\n'
export BOOTSTRAP_EMAIL BOOTSTRAP_PASSWORD
docker compose --env-file .env -f compose.yml run --rm --no-deps \
  -e BOOTSTRAP_EMAIL -e BOOTSTRAP_PASSWORD user-service bootstrap
docker compose --env-file .env -f compose.yml run --rm --no-deps \
  -e BOOTSTRAP_EMAIL user-service grant-initial-admin
unset BOOTSTRAP_EMAIL BOOTSTRAP_PASSWORD GOOSE_DBSTRING
./scripts/lens up
./scripts/lens doctor --running
```

`bootstrap` creates an account; `grant-initial-admin` assigns an existing active
account only when no effective administrator exists. Normal startup never
restores revoked grants. Enable registration in `user-service.env` only after
SMTP verification, then recreate user-service to load the configuration. Check
registration, login, personal resources, administration and logout through the
actual HTTPS origin before opening access.

## First upgrade from legacy Lens identity

This is a maintenance-window operation performed once, before routine upgrades.
The CI deployment workflow refuses to run while `auth_users` remains in Lens.
Do not run migration 0099 on the only old database before verifying import:
0099 removes its password/session tables and cannot reconstruct them on downgrade.

1. Keep the old code/images and configuration. Stop frontend, Web and **every**
   worker or other write source. Keep only PostgreSQL available. Registration
   stays disabled and the new identity account table must be empty.
2. Save a custom-format archive of the old `lens` database and matching
   `data/backend`, configuration, and keys in a private backup directory.
   Restore a copy into an isolated database and verify the original user IDs,
   hashes and resource ownership before continuing.
3. Stage this release's bundle, preserve the private runtime files, configure
   certificates and the new identity password, then run
   `prepare-identity.sh` and the Goose command from fresh installation.
   **Do not bootstrap the target identity database.**
4. Export `OLD_IDENTITY_DATABASE_URL` for the stopped old Lens database and
   `USER_DATABASE_URL` for `lens_users` in the operator terminal. These are
   regular PostgreSQL DSNs, held privately; pass them by environment:

   ```bash
   docker compose --env-file .env -f compose.yml run --rm --no-deps \
     -e OLD_IDENTITY_DATABASE_URL -e USER_DATABASE_URL backend \
     python scripts/import_legacy_users.py
   ```

   The importer reads a consistent old snapshot, locks the empty destination,
   imports and compares IDs, email/name, password hashes and creation times in
   one transaction. An invalid row rolls back the entire target import.
   It copies no old sessions and makes no email-verification claims. It does
   not assign groups. A non-empty destination is rejected.
5. After verified import, execute `backend alembic upgrade head`, authorize the
   intended imported account with `grant-initial-admin`, then start the new
   stack. Verify original-password login, original `user_id`, original
   Collection ownership, denial for a second user and rejection of an old
   session before reopening registration and scientific writes.

The old account's stable hash must use the password format supported by the
current identity service. Existing unverified accounts retain password login;
email recovery is available only to accounts with recorded verified email.
If any cutover check fails, keep maintenance mode and restore the verified old
database, resources, code and configuration together. New writes in the new
system are not automatically merged into the old system.

## Routine upgrade

Before the first upgrade to encrypted Chat model credentials, follow the
[credential cutover](../backend/docs/runbooks/model-key-operations.md#first-cutover-of-an-existing-database)
and back up the master key separately. The routine upgrade command cannot
import existing environment references.

After the first identity cutover, use the manual **Deploy Production** workflow
or the server command:

```bash
./scripts/lens upgrade vX.Y.Z
```

The command fetches the selected tag's bundle into a temporary directory while
preserving private runtime configuration. The candidate upgrade then:

1. Rejects an unsafe tag or remaining legacy identity tables and pulls the
   candidate images before interrupting the running stack.
2. Stops all application/worker write sources. Saves both databases, runtime
   configuration/keys and file resources in a private `backups/` directory;
   checks that database archives can be read before starting migrations.
3. Installs the selected bundle's maintained files, preserves secrets, prepares
   the identity role if needed, then explicitly runs Goose and Alembic.
4. Starts the selected image version, waits for health and runs the HTTPS,
   migration-head, worker and mTLS doctor checks. Only then persists the new
   `LENS_VERSION`.

A pull failure leaves the old stack running. A backup failure starts no
migration. A later failure stops candidate application services in maintenance
mode, retains the old version setting and backup location, and returns failure.
It never treats an old image tag as a schema rollback. Applications may accept
new writes during final public smoke checks; preserve the failure state and
consider those writes before restoring a backup.

Before using this on real data, rehearse it with a restored copy. A readable
archive is not proof that every scientific resource has been restored correctly.

## CI, image publication and production deployment

- [CI](../.github/workflows/ci.yml) runs on PRs, main pushes and reusable calls.
  Go uses real PostgreSQL migrations and race tests; Python verifies identity,
  ownership, import and PostgreSQL cutover; frontend runs lint, types, unit tests
  and the full browser suite/build. Deployment sequencing and documentation
  contracts also run. CI test databases use disposable localhost-only data.
- [Release Docker Images](../.github/workflows/release-images.yml) runs the same
  CI for a stable tag before publishing backend, frontend and user-service
  images with that tag. Production uses version tags rather than `latest`.
- [Deploy Production](../.github/workflows/deploy.yml) is manually dispatched
  with a stable version. It requires a successful publication run for that exact
  tag/commit, transfers that tag's deployment bundle over verified SSH, then
  invokes its upgrade script against private host configuration. Deployments
  are serialized. The first legacy import remains a separate operator step.

Configure Docker Hub repository secrets:

| Name | Value |
| --- | --- |
| `DOCKERHUB_USERNAME` | Image publisher account |
| `DOCKERHUB_TOKEN` | Token allowed to publish the three Lens image repositories |

Create the GitHub `production` environment and configure:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `DEPLOY_HOST` | SSH server hostname |
| Secret | `DEPLOY_USER` | Operator with access to the deployment directory and Docker |
| Secret | `DEPLOY_SSH_KEY` | Dedicated SSH private key |
| Secret | `DEPLOY_KNOWN_HOSTS` | Host key verified independently and pinned in known_hosts format |
| Variable | `DEPLOY_PATH` | Absolute existing runtime directory, e.g. `/opt/lens-deploy`; use letters, digits, `_`, `.`, `-` and `/` |

SMTP, HMAC/database secrets and certificate private keys remain on the server;
CI does not need them. Configure required CI status checks in branch protection
through the GitHub repository settings. All release gates remain blocking;
checks are not skipped or marked non-blocking. Local workflow validation is
distinct from a successful hosted Actions run.

## Backup and restore

Routine upgrades retain `lens.dump`, `lens_users.dump`, `runtime.tgz` and
`resources.tgz` together. Move copies to independent protected storage and
exercise recovery before relying on them. Runtime archives contain credentials
and keys; do not upload them to Actions artifacts or Git.

For recovery, stop all application and worker containers. Keep PostgreSQL
running. Restore the matching old bundle/configuration from `runtime.tgz` and
resource files from `resources.tgz`. Using the old configuration, restore each
trusted database archive into a fresh replacement database, verify it, and
switch to those databases, or replace the stopped original databases during
an explicit maintenance window. Example replacement, after verifying backup
copies and preserving the failure state:

```bash
# Destructive: every application/worker must remain stopped.
docker compose --env-file .env -f compose.yml exec -T postgres \
  psql -U lens -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE lens WITH (FORCE)' \
  -c 'CREATE DATABASE lens OWNER lens TEMPLATE template0' \
  -c 'DROP DATABASE lens_users WITH (FORCE)' \
  -c 'CREATE DATABASE lens_users OWNER lens_users TEMPLATE template0'
docker compose --env-file .env -f compose.yml exec -T postgres \
  pg_restore --exit-on-error --single-transaction -U lens -d lens < backups/SELECTED/lens.dump
docker compose --env-file .env -f compose.yml exec -T postgres \
  pg_restore --exit-on-error --single-transaction -U lens -d lens_users < backups/SELECTED/lens_users.dump
```

Compare migration versions, account IDs, permission catalogs/associations/audit,
session revocations, email proof/rate-limit state and Collection ownership.
Use the matching old images and configuration; do not run `alembic downgrade`
to recover removed credentials. The PostgreSQL volume and `data/backend`
survive normal `docker compose down`; `down --volumes` deletes database state.

## Research workers and model configuration
`./scripts/lens up` starts the backend, frontend, user-service, PostgreSQL, three research
Workers and four feedback analysis Workers together. The Workers are
long-running processes built from the backend image; they do not expose HTTP
ports. HTTP and Agent requests queue work. Research Workers prepare documents,
discover Objectives and analyze Objectives; feedback Workers claim pending
`analysis_jobs` and write analysis results or dataset samples.

The expected service names are:

```text
postgres
user-service
backend
frontend
document-preparation-worker
objective-discovery-worker
objective-analysis-worker
feedback-analysis-worker
correction-signal-analysis-worker
tool-failure-analysis-worker
dataset-sample-worker
```

Inspect a particular Worker when a job remains pending:

```bash
./scripts/lens logs document-preparation-worker
./scripts/lens logs objective-discovery-worker
./scripts/lens logs objective-analysis-worker
./scripts/lens logs feedback-analysis-worker
./scripts/lens logs correction-signal-analysis-worker
./scripts/lens logs tool-failure-analysis-worker
./scripts/lens logs dataset-sample-worker
```

Stopping a Worker leaves newly created jobs in `pending`; starting the service
again lets it continue polling. Docker's `restart: unless-stopped` restarts a
Worker container after a process failure. Each claimed job has a database lease
(`worker_id`, `lease_expires_at`, `heartbeat_at`, and `lease_version`). When a
Worker exits, the next Worker pass returns an expired `running` job to
`pending`; dataset sample jobs also return from `building` to `pending`.


Research Agent Chat requires an enabled model connection in PostgreSQL; the
registry is not populated from `LLM_MODEL`. Follow the
[model connection setup and recovery runbook](../backend/docs/runbooks/backend-ops.md#chat-binding-and-operational-recovery)
for selection and recovery. The browser lets each new question select an
enabled connection. Available connections sort
by `priority` descending (default `0`), then name and ID; both the browser and
clients that omit a choice use the first entry. Set the preferred connection's
priority higher in PostgreSQL and remove the obsolete
`LENS_DEFAULT_MODEL_CONNECTION_ID` from `backend.env`. Finish or explicitly
interrupt old unbound approvals before upgrading.

Useful commands remain `./scripts/lens logs`, `ps`, `pull`, `down` and `url`.
`doctor --running` performs strict checks; `doctor` before startup reports missing
runtime prerequisites. Do not publish `lens config` output because it includes
connection credentials.
