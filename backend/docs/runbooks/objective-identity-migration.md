# Objective Identity Offline Migration

This runbook covers the one-way import from the retained Goal-era SQLite
snapshot to the PostgreSQL Objective identity model. The importer is an
operator-only script. It is not part of the backend request path and it never
modifies or deletes the SQLite source.

Do not apply this migration to a real database until the active operator has
approved the maintenance window, the database backup, the frozen source
snapshot, and the reviewed dry-run report.

## Preconditions

1. Stop backend processes, analysis workers, evaluation tools, and any other
   writer for the source collection data.
2. Create and verify a PostgreSQL backup. Record its operator-visible backup
   identifier; do not put credentials in the identifier or report.
3. Copy `backend/data/lens.sqlite` to the approved read-only rollback location.
   Compute its SHA-256 independently and make the copy read-only.
4. Upgrade an isolated migration target to Alembic head and verify that it
   contains the same Objective and source-build snapshot expected by the
   SQLite Goal records.
5. Set `LENS_DATABASE_URL` to the isolated PostgreSQL target. Keep credentials
   in the environment or an approved secret provider, not in shell history or
   attached reports.

The migration does not create schema. Alembic must be at revision
`20260720_0013` before dry-run or apply.

## Dry Run

From `backend/`:

```bash
./.venv/bin/python scripts/persistence/migrate_goal_identity.py \
  --source /absolute/path/to/read-only/lens.sqlite \
  --report /absolute/path/to/objective-identity-dry-run.json
```

Dry-run opens SQLite with `mode=ro&immutable=1` and performs no PostgreSQL
write. Review all of the following before apply:

- `status` is `dry_run_ready`
- `blockers` is empty
- every Goal appears exactly once in `mappings`
- linked and standalone mapping kinds are expected
- family record counts match the frozen inventory
- family content hashes and `manifest_sha256` are recorded
- `evidence_link_count` matches the frozen Understanding baseline
- the independently computed SQLite SHA-256 matches `source_sha256`

Any running Goal or Objective, missing Goal/Objective/session/message
reference, non-equivalent duplicate, conflicting Understanding, embedded Goal
URL, missing Source document/paper fact/Evidence anchor, source snapshot drift,
or target-content conflict blocks apply. Resolve the source or target
deliberately and create a new backup and dry-run. Do not bypass a blocker by
editing the report.

## Apply

Use the exact hash from the reviewed dry-run and the verified backup reference:

```bash
./.venv/bin/python scripts/persistence/migrate_goal_identity.py \
  --source /absolute/path/to/read-only/lens.sqlite \
  --report /absolute/path/to/objective-identity-apply.json \
  --apply \
  --expected-source-sha256 <reviewed-64-character-sha256> \
  --backup-reference <verified-backup-id>
```

Apply repeats the complete dry-run validation and writes all families in one
PostgreSQL transaction. It materializes deterministic Objective rows only for
standalone historical Goals, writes Objective lifecycle state, normalizes
Understanding and review identities, and imports Objective sessions, messages,
and experiment plans. The final target contains no Goal identity column or
Goal-scoped Understanding.

The same source snapshot can be applied again safely. A successful repeat
returns `already_applied` and creates no duplicate rows. A changed source hash
or different target content is rejected.

## Post-Write Validation

Before runtime cutover, compare the apply report with the reviewed dry-run:

- `source_sha256`, `manifest_sha256`, mappings, counts, content hashes, and
  Evidence-link count are identical
- PostgreSQL foreign-key checks report no invalid references
- each ready Objective has at least one persisted reviewable Finding
- feedback and curation resolve to the exact Understanding, claim, and optional
  Finding
- message order is continuous within each session
- each experiment plan resolves to its Objective and optional source message
- representative Evidence links still reach the expected collection source

The runtime switch to these tables is a separate implementation slice. Do not
start mixed SQLite/PostgreSQL runtime reads after a successful import.

## Recovery

If apply raises before commit, PostgreSQL rolls back the entire transaction and
the SQLite source remains unchanged.

If post-write or runtime acceptance fails after commit:

1. Keep writers stopped.
2. Restore the verified PostgreSQL backup identified in the apply report.
3. Restore the application version that predates runtime cutover.
4. Retain the unchanged SQLite snapshot read-only for diagnosis.
5. Record the failed manifest hash and validation difference before another
   attempt.

Do not merge records from the failed target back into SQLite, enable a runtime
fallback, or delete the rollback snapshot as part of recovery. Destructive
legacy cleanup requires a separate operator approval after the rollback window.
