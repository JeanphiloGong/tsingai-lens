# Retire legacy Chat storage

Revision `b71000000007` removes the old tool-call table, response snapshots,
linear message positions, Fork columns, permission settings, and Feedback
analysis storage. Conversation messages, answer ratings, Agent Tasks and
Operations, and internal ModelCall records carry forward.

1. Stop application writes during the cutover. On the existing database, apply
   revisions through `b71000000006` so that the backfill scripts have both
   schemas available.
2. Use `pg_dump --format=custom` to archive that database. Restore the archive
   with `pg_restore` into a separate database. Compare Conversation, message,
   tool-call, ModelCall, and Feedback counts and sample their original IDs.
3. Set `LENS_DATABASE_URL` to the database being migrated. From `backend/`,
   run the history backfill for Conversation IDs with linear history, then run
   the Agent backfill. Keep the JSON output with the archive.
4. Review unresolved responses, Operations, Feedback, and Fork provenance.
   Complete any provable links before retirement. Keep records of ambiguous
   lineage in the archive and report. A running legacy tool call with an
   unknown outcome requires reconciliation.
5. Apply the retirement revision and start the updated application. Check the
   current revision, selected paths, Task and Operation reads, and a saved
   rating. Restore the verified archive to recover the dropped schema.

```bash
alembic upgrade b71000000006
python scripts/backfill_conversations.py conv_id_1 conv_id_2 > conversation-backfill.json
python scripts/backfill_agent_tasks.py > agent-backfill.json
alembic -x chat_history_archived=true upgrade head
alembic current --check-heads
```

The retirement migration rejects populated legacy execution or analysis data
until the operator acknowledges the reviewed archive. An empty database can
upgrade directly to head. The removal uses PostgreSQL `RESTRICT` to detect
references from surviving tables.
