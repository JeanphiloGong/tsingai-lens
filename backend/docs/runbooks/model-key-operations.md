# Model Credential Operations

The Web process reads a stable 32-byte master key from `LENS_MODEL_KEY_FILE`.
Chat model connections use it to decrypt provider API keys. Keep it outside Git,
images and database dumps. See the [model connection data contract](../specs/model-connections/data-model.md).

## Prepare a deployment

From the Compose deployment directory, create the master key once:

```sh
mkdir -p model-secrets
(umask 077; set -C; openssl rand 32 > model-secrets/model-key)
```

The backend Web container mounts this file read-only at
`/run/lens-secrets/model-key`. For a local Web process, set `LENS_MODEL_KEY_FILE`
to the absolute file path. Startup rejects missing or invalid files and existing
credentials that fail decryption.

## First cutover of an existing database

Schedule a maintenance window. Stop application writes, running generations and
approval continuations. Keep the old image and configuration, back up the
database and research files, and back up the new master key separately.

Use the new backend code with the previous provider environment variables
available to the importer. From the backend project directory, run:

```sh
alembic upgrade 20261114_0100
python scripts/import_model_connection_keys.py
alembic upgrade 20261114_0101
```

In a Compose installation, run each command through
`docker compose --env-file .env -f compose.yml run --rm --no-deps backend`
using the new image. Its `backend.env` must still provide the legacy references'
values for the import. A fresh database can upgrade directly to head.

The importer writes all encrypted keys in one transaction. A missing reference
aborts the import. After the final migration, start the Web process and verify
a Chat request against an existing connection. Remove environment variables
used exclusively by old Chat references after verification. Retain variables
used by research and feedback workers.

## Backup, recovery and key changes

Keep matched database and master-key backups in separately controlled
locations. The routine upgrade backup excludes the master-key file. Rehearse
restoring both into an isolated environment and use a model request to verify
recovery. If cutover fails, restore the matching pre-cutover database and old
application configuration. Schema downgrade cannot restore the old references.
