"""Frozen table definitions used by revision 20260827_0038.

This captures the schema supplied by the repository's pre-durable-Chat
metadata at 1cab1c79. Later revisions own all changes to these definitions.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import conv

metadata = sa.MetaData()
_JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

sa.Table(
    'analysis_jobs',
    metadata,
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('job_type', sa.String(length=64), nullable=False),
    sa.Column('payload_version', sa.Integer(), nullable=False),
    sa.Column('payload', _JSON_DOCUMENT, nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result_id', sa.String(length=64), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('worker_id', sa.String(length=100), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lease_version', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name='ck_analysis_jobs_analysis_job_status_valid'),
    sa.CheckConstraint('finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at', name='ck_analysis_jobs_analysis_job_timestamps_valid'),
    sa.CheckConstraint('payload_version >= 1', name='ck_analysis_jobs_analysis_job_payload_version_positive'),
    sa.PrimaryKeyConstraint('job_id', name='pk_analysis_jobs'),
    sa.UniqueConstraint('idempotency_key', name='uq_analysis_jobs_idempotency_key')
)

sa.Table(
    'feedback_dataset_migration_runs',
    metadata,
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('migration_version', sa.String(length=32), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('summary', _JSON_DOCUMENT, nullable=False),
    sa.Column('items', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("mode IN ('dry_run', 'apply')", name=conv('ck_feedback_dataset_migration_runs_feedback_dataset_migration_run_mode_valid')),
    sa.CheckConstraint("status IN ('planned', 'applied', 'failed')", name=conv('ck_feedback_dataset_migration_runs_feedback_dataset_migration_run_status_valid')),
    sa.PrimaryKeyConstraint('run_id', name='pk_feedback_dataset_migration_runs')
)

sa.Table(
    'collections',
    metadata,
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('owner_user_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('discovery_ready', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('discovery_document_inputs', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('discovery_objective_ids', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('discovery_study_dispositions', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('discovery_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('agent_default_permission', _JSON_DOCUMENT, nullable=True),
    sa.CheckConstraint('updated_at >= created_at', name='ck_collections_valid_timestamps'),
    sa.PrimaryKeyConstraint('collection_id', name='pk_collections')
)

sa.Table(
    'finding_feedback_records',
    metadata,
    sa.Column('feedback_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('review_status', sa.String(length=64), nullable=False),
    sa.Column('issue_type', sa.String(length=64), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewer', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('feedback_id', name='pk_finding_feedback_records')
)

sa.Table(
    'finding_curation_records',
    metadata,
    sa.Column('curation_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('curated_status', sa.String(length=64), nullable=False),
    sa.Column('curated_finding', _JSON_DOCUMENT, nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewer', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('curation_id', name='pk_finding_curation_records')
)

sa.Table(
    'objective_analysis_legacy_checkpoints',
    metadata,
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('legacy_key', sa.String(length=400), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=True),
    sa.Column('input_fingerprint', sa.String(length=128), nullable=True),
    sa.Column('checkpoint_status', sa.String(length=32), nullable=True),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('classification', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name='pk_objective_analysis_legacy_checkpoints'),
    sa.UniqueConstraint('collection_id', 'objective_id', 'analysis_version', 'legacy_key', name='uq_objective_analysis_legacy_checkpoint_key')
)

sa.Table(
    'pipeline_runs',
    metadata,
    sa.Column('worker_id', sa.String(length=255), nullable=True),
    sa.Column('lease_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('pipeline_name', sa.String(length=64), nullable=False),
    sa.Column('scope_type', sa.String(length=32), nullable=False),
    sa.Column('scope_id', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=64), nullable=False),
    sa.Column('input_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('record_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("pipeline_name <> ''", name='ck_pipeline_runs_pipeline_name_not_empty'),
    sa.CheckConstraint("scope_id <> ''", name='ck_pipeline_runs_scope_id_not_empty'),
    sa.CheckConstraint("scope_type <> ''", name='ck_pipeline_runs_scope_type_not_empty'),
    sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial_success', 'failed')", name='ck_pipeline_runs_valid_status'),
    sa.CheckConstraint('updated_at >= created_at', name='ck_pipeline_runs_valid_timestamps'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_pipeline_runs_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('run_id', name='pk_pipeline_runs')
)

sa.Table(
    'chat_sessions',
    metadata,
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_pinned', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('root_session_id', sa.String(length=128), nullable=True),
    sa.Column('parent_session_id', sa.String(length=128), nullable=True),
    sa.Column('fork_message_id', sa.String(length=128), nullable=True),
    sa.Column('fork_position', sa.Integer(), nullable=True),
    sa.Column('fork_content', sa.Text(), nullable=True),
    sa.Column('response_snapshot', _JSON_DOCUMENT, nullable=True),
    sa.Column('operation_permission', _JSON_DOCUMENT, nullable=True),
    sa.CheckConstraint('updated_at >= created_at', name='ck_chat_sessions_valid_timestamps'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_chat_sessions_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id', name='pk_chat_sessions')
)

sa.Table(
    'feedback_dataset_snapshots',
    metadata,
    sa.Column('dataset_id', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_type', sa.String(length=16), nullable=False),
    sa.Column('rows', _JSON_DOCUMENT, nullable=False),
    sa.Column('exclusions', _JSON_DOCUMENT, nullable=False),
    sa.Column('provenance', _JSON_DOCUMENT, nullable=False),
    sa.Column('manifest', _JSON_DOCUMENT, nullable=False),
    sa.Column('manifest_digest', sa.String(length=64), nullable=False),
    sa.Column('provenance_digest', sa.String(length=64), nullable=False),
    sa.Column('content_digest', sa.String(length=64), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('excluded_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("dataset_type IN ('evaluation', 'sft', 'preference')", name='ck_feedback_dataset_snapshots_feedback_dataset_type_valid'),
    sa.CheckConstraint('excluded_count >= 0', name=conv('ck_feedback_dataset_snapshots_feedback_dataset_excluded_count_non_negative')),
    sa.CheckConstraint('length(content_digest) = 64', name=conv('ck_feedback_dataset_snapshots_feedback_dataset_content_digest_length')),
    sa.CheckConstraint('length(manifest_digest) = 64', name=conv('ck_feedback_dataset_snapshots_feedback_dataset_manifest_digest_length')),
    sa.CheckConstraint('length(provenance_digest) = 64', name=conv('ck_feedback_dataset_snapshots_feedback_dataset_provenance_digest_length')),
    sa.CheckConstraint('row_count >= 0', name=conv('ck_feedback_dataset_snapshots_feedback_dataset_row_count_non_negative')),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_feedback_dataset_snapshots_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', name='pk_feedback_dataset_snapshots'),
    sa.UniqueConstraint('owner_id', 'manifest_digest', name='uq_feedback_dataset_owner_manifest')
)

sa.Table(
    'feedback_datasets',
    metadata,
    sa.Column('dataset_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('task_type', sa.String(length=16), nullable=False),
    sa.Column('construction_spec', _JSON_DOCUMENT, nullable=False),
    sa.Column('spec_version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("task_type IN ('sft', 'preference', 'evaluation')", name='ck_feedback_datasets_feedback_dataset_task_type_valid'),
    sa.CheckConstraint('spec_version >= 1', name='ck_feedback_datasets_feedback_dataset_spec_version_positive'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_feedback_datasets_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id', name='pk_feedback_datasets')
)

sa.Table(
    'documents',
    metadata,
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('original_filename', sa.Text(), nullable=False),
    sa.Column('stored_filename', sa.Text(), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('media_type', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('document_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('document_order >= 0', name='ck_documents_document_order_non_negative'),
    sa.CheckConstraint('length(sha256) = 64', name='ck_documents_sha256_length'),
    sa.CheckConstraint('sha256 = lower(sha256)', name='ck_documents_sha256_lowercase'),
    sa.CheckConstraint('size_bytes >= 0', name='ck_documents_size_bytes_non_negative'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_documents_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', name='pk_documents'),
    sa.UniqueConstraint('collection_id', 'document_order', name='uq_documents_collection_order'),
    sa.UniqueConstraint('collection_id', 'sha256', name='uq_documents_collection_content'),
    sa.UniqueConstraint('storage_key', name='uq_documents_storage_key')
)

sa.Table(
    'evaluation_gold_sets',
    metadata,
    sa.Column('gold_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('target_layer', sa.String(length=32), nullable=False),
    sa.Column('metric_profile', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('metadata_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('items', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_evaluation_gold_sets_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('gold_id', name='pk_evaluation_gold_sets')
)

sa.Table(
    'evaluation_prediction_snapshots',
    metadata,
    sa.Column('snapshot_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('target_layer', sa.String(length=32), nullable=False),
    sa.Column('fact_source', sa.String(length=64), nullable=False),
    sa.Column('system_context', _JSON_DOCUMENT, nullable=False),
    sa.Column('artifact_counts', _JSON_DOCUMENT, nullable=False),
    sa.Column('items', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_evaluation_prediction_snapshots_collection_id_collections', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id', name='pk_evaluation_prediction_snapshots')
)

sa.Table(
    'research_objectives',
    metadata,
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(length=32), nullable=False),
    sa.Column('created_by_tool_call_id', sa.String(length=128), nullable=True),
    sa.Column('payload', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_research_objectives_collection', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', name='pk_research_objectives'),
    sa.UniqueConstraint('created_by_tool_call_id', name='uq_research_objectives_created_by_tool_call')
)

sa.Table(
    'chat_messages',
    metadata,
    sa.Column('message_id', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tool_call_id', sa.String(length=128), nullable=True),
    sa.Column('source_contexts', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('user', 'assistant', 'tool')", name='ck_chat_messages_role_valid'),
    sa.CheckConstraint('position >= 0', name='ck_chat_messages_position_non_negative'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_chat_messages_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', name='pk_chat_messages'),
    sa.UniqueConstraint('session_id', 'position', name='uq_chat_messages_position')
)

sa.Table(
    'chat_model_calls',
    metadata,
    sa.Column('call_id', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('trigger_message_id', sa.String(length=128), nullable=True),
    sa.Column('response_message_id', sa.String(length=128), nullable=True),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('model_connection_id', sa.String(length=64), nullable=True),
    sa.Column('request', _JSON_DOCUMENT, nullable=False),
    sa.Column('request_digest', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('provider_confirmed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.CheckConstraint("purpose IN ('decision', 'compaction', 'finalization')", name='ck_chat_model_calls_chat_model_call_purpose_valid'),
    sa.CheckConstraint("status IN ('recorded', 'provider_succeeded', 'provider_failed', 'response_invalid', 'cancelled')", name='ck_chat_model_calls_chat_model_call_status_valid'),
    sa.CheckConstraint('finished_at IS NULL OR finished_at >= started_at', name='ck_chat_model_calls_chat_model_call_timestamps_valid'),
    sa.CheckConstraint('length(request_digest) = 64', name='ck_chat_model_calls_chat_model_call_digest_length'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_chat_model_calls_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('call_id', name='pk_chat_model_calls')
)

sa.Table(
    'feedback_analysis_results',
    metadata,
    sa.Column('result_id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('feedback_id', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('anchor_message_id', sa.String(length=128), nullable=False),
    sa.Column('problem_type', sa.String(length=64), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('related_message_ids', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_evidence', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_target', sa.Text(), nullable=True),
    sa.Column('evidence_coverage', _JSON_DOCUMENT, nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('input_digest', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', 'retrieval_failure', 'tool_failure', 'intent_mismatch', 'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')", name=conv('ck_feedback_analysis_results_feedback_analysis_problem_type_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=conv('ck_feedback_analysis_results_feedback_analysis_confidence_range')),
    sa.CheckConstraint('length(input_digest) = 64', name=conv('ck_feedback_analysis_results_feedback_analysis_input_digest_length')),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_feedback_analysis_results_collection_id_collections', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.job_id'], name='fk_feedback_analysis_results_job_id_analysis_jobs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_feedback_analysis_results_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('result_id', name='pk_feedback_analysis_results'),
    sa.UniqueConstraint('job_id', name='uq_feedback_analysis_results_job_id')
)

sa.Table(
    'feedback_signal_analysis_results',
    metadata,
    sa.Column('result_id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('signal_id', sa.String(length=160), nullable=False),
    sa.Column('signal_type', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('anchor_message_id', sa.String(length=128), nullable=False),
    sa.Column('trigger_message_id', sa.String(length=128), nullable=False),
    sa.Column('problem_type', sa.String(length=64), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('related_message_ids', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_evidence', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_target', sa.Text(), nullable=True),
    sa.Column('evidence_coverage', _JSON_DOCUMENT, nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('input_digest', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', 'retrieval_failure', 'tool_failure', 'intent_mismatch', 'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')", name=conv('ck_feedback_signal_analysis_results_feedback_signal_analysis_problem_type_valid')),
    sa.CheckConstraint("signal_type IN ('natural_language_correction')", name=conv('ck_feedback_signal_analysis_results_feedback_signal_analysis_type_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=conv('ck_feedback_signal_analysis_results_feedback_signal_analysis_confidence_range')),
    sa.CheckConstraint('length(input_digest) = 64', name=conv('ck_feedback_signal_analysis_results_feedback_signal_analysis_input_digest_length')),
    sa.CheckConstraint('suggested_target IS NULL', name=conv('ck_feedback_signal_analysis_results_feedback_signal_analysis_target_absent')),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_feedback_signal_analysis_results_collection_id_collections', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.job_id'], name='fk_feedback_signal_analysis_results_job_id_analysis_jobs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_feedback_signal_analysis_results_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('result_id', name='pk_feedback_signal_analysis_results'),
    sa.UniqueConstraint('job_id', name='uq_feedback_signal_analysis_results_job_id')
)

sa.Table(
    'tool_failure_analysis_results',
    metadata,
    sa.Column('result_id', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('signal_id', sa.String(length=320), nullable=False),
    sa.Column('signal_type', sa.String(length=32), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('tool_call_id', sa.String(length=128), nullable=False),
    sa.Column('assistant_message_id', sa.String(length=128), nullable=False),
    sa.Column('result_message_id', sa.String(length=128), nullable=False),
    sa.Column('tool_name', sa.String(length=128), nullable=False),
    sa.Column('error_code', sa.String(length=128), nullable=False),
    sa.Column('problem_type', sa.String(length=64), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('related_message_ids', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_evidence', _JSON_DOCUMENT, nullable=False),
    sa.Column('suggested_target', sa.Text(), nullable=True),
    sa.Column('evidence_coverage', _JSON_DOCUMENT, nullable=False),
    sa.Column('model', sa.String(length=255), nullable=False),
    sa.Column('input_digest', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("problem_type = 'tool_failure'", name=conv('ck_tool_failure_analysis_results_tool_failure_analysis_problem_type_valid')),
    sa.CheckConstraint("signal_type IN ('tool_failure')", name=conv('ck_tool_failure_analysis_results_tool_failure_analysis_signal_type_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=conv('ck_tool_failure_analysis_results_tool_failure_analysis_confidence_range')),
    sa.CheckConstraint('length(input_digest) = 64', name=conv('ck_tool_failure_analysis_results_tool_failure_analysis_input_digest_length')),
    sa.CheckConstraint('suggested_target IS NULL', name=conv('ck_tool_failure_analysis_results_tool_failure_analysis_target_absent')),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_tool_failure_analysis_results_collection_id_collections', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.job_id'], name='fk_tool_failure_analysis_results_job_id_analysis_jobs', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_tool_failure_analysis_results_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('result_id', name='pk_tool_failure_analysis_results'),
    sa.UniqueConstraint('job_id', name='uq_tool_failure_analysis_results_job_id'),
    sa.UniqueConstraint('tool_call_id', 'result_message_id', name='uq_tool_failure_analysis_results_observation')
)

sa.Table(
    'feedback_cases',
    metadata,
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('anchor_message_id', sa.String(length=128), nullable=False),
    sa.Column('source_signal_ids', _JSON_DOCUMENT, nullable=False),
    sa.Column('analysis_result_ids', _JSON_DOCUMENT, nullable=False),
    sa.Column('signal_analysis_result_ids', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('tool_failure_analysis_result_ids', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('context_snapshot', _JSON_DOCUMENT, nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('annotation_digest', sa.String(length=64), nullable=True),
    sa.CheckConstraint("status IN ('detected', 'collecting_context', 'needs_annotation', 'ready_for_review', 'rejected', 'insufficient', 'accepted', 'withdrawn')", name='ck_feedback_cases_feedback_case_status_valid'),
    sa.CheckConstraint('updated_at >= created_at', name='ck_feedback_cases_feedback_case_timestamps_valid'),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_feedback_cases_collection_id_collections', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_feedback_cases_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('case_id', name='pk_feedback_cases'),
    sa.UniqueConstraint('session_id', 'anchor_message_id', name='uq_feedback_cases_session_anchor')
)

sa.Table(
    'feedback_export_previews',
    metadata,
    sa.Column('preview_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_id', sa.String(length=64), nullable=False),
    sa.Column('members', _JSON_DOCUMENT, nullable=False),
    sa.Column('issues', _JSON_DOCUMENT, nullable=False),
    sa.Column('preview_digest', sa.String(length=64), nullable=False),
    sa.Column('requested_count', sa.Integer(), nullable=False),
    sa.Column('exportable_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('length(preview_digest) = 64', name='ck_feedback_export_previews_feedback_export_preview_digest_len'),
    sa.ForeignKeyConstraint(['dataset_id'], ['feedback_datasets.dataset_id'], name='fk_feedback_export_previews_dataset_id_feedback_datasets', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('preview_id', name='pk_feedback_export_previews')
)

sa.Table(
    'document_preparations',
    metadata,
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('source_format', sa.String(length=32), nullable=True),
    sa.Column('parser_name', sa.String(length=128), nullable=True),
    sa.Column('parser_version', sa.String(length=128), nullable=True),
    sa.Column('source_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('artifact_json', _JSON_DOCUMENT, nullable=True),
    sa.Column('profile_json', _JSON_DOCUMENT, nullable=True),
    sa.Column('paper_map_payload', _JSON_DOCUMENT, nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.document_id'], name='fk_document_preparations_document_id_documents', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('document_id', name='pk_document_preparations')
)

sa.Table(
    'evaluation_runs',
    metadata,
    sa.Column('evaluation_run_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('gold_id', sa.String(length=128), nullable=False),
    sa.Column('prediction_snapshot_id', sa.String(length=128), nullable=False),
    sa.Column('target_layer', sa.String(length=32), nullable=False),
    sa.Column('fact_source', sa.String(length=64), nullable=False),
    sa.Column('metric_profile', sa.String(length=128), nullable=False),
    sa.Column('status', sa.String(length=64), nullable=False),
    sa.Column('summary', _JSON_DOCUMENT, nullable=False),
    sa.Column('scores', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('failures', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.collection_id'], name='fk_evaluation_runs_collection_id_collections', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['gold_id'], ['evaluation_gold_sets.gold_id'], name='fk_evaluation_runs_gold_id_evaluation_gold_sets', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prediction_snapshot_id'], ['evaluation_prediction_snapshots.snapshot_id'], name=conv('fk_evaluation_runs_prediction_snapshot_id_evaluation_prediction_snapshots'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('evaluation_run_id', name='pk_evaluation_runs')
)

sa.Table(
    'objective_analyses',
    metadata,
    sa.Column('worker_id', sa.String(length=255), nullable=True),
    sa.Column('lease_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('payload', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id'], ['research_objectives.collection_id', 'research_objectives.objective_id'], name='fk_objective_analyses_objective', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('collection_id', 'objective_id', 'analysis_version', name='pk_objective_analyses')
)

sa.Table(
    'paper_experiment',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('experiment_id', sa.String(length=120), nullable=False),
    sa.Column('experiment_version', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.String(length=64), nullable=False),
    sa.Column('source_fingerprint', sa.String(length=200), nullable=False),
    sa.Column('label', sa.String(length=500), nullable=False),
    sa.Column('scope_description', sa.Text(), nullable=False),
    sa.Column('design_type', sa.String(length=40), nullable=False),
    sa.Column('identity_status', sa.String(length=20), nullable=False),
    sa.Column('binding_status', sa.String(length=20), nullable=False),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('unresolved_issues_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=100), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("binding_status IN ('draft', 'partial', 'bound')", name='ck_paper_experiment_binding_status_valid'),
    sa.CheckConstraint("design_type IN ('parallel', 'factorial', 'dose_response', 'observational', 'unknown')", name='ck_paper_experiment_design_type_valid'),
    sa.CheckConstraint("identity_status IN ('identified', 'partial', 'unknown')", name='ck_paper_experiment_identity_status_valid'),
    sa.CheckConstraint('experiment_version >= 1', name='ck_paper_experiment_version_positive'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.document_id'], name='fk_paper_experiment_document_id_documents', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_paper_experiment'),
    sa.UniqueConstraint('experiment_id', 'experiment_version', name='uq_paper_experiment_identity_version')
)

sa.Table(
    'chat_tool_calls',
    metadata,
    sa.Column('tool_call_id', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('assistant_message_id', sa.String(length=128), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('arguments', _JSON_DOCUMENT, nullable=False),
    sa.Column('arguments_digest', sa.String(length=64), nullable=False),
    sa.Column('risk', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('decision_user_id', sa.String(length=64), nullable=True),
    sa.Column('decision_arguments_digest', sa.String(length=64), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result_status', sa.String(length=32), nullable=True),
    sa.Column('decision_basis', sa.String(length=32), server_default='explicit', nullable=False),
    sa.Column('authorization_revision', sa.Integer(), nullable=True),
    sa.Column('proposed_permission_revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('result_data', _JSON_DOCUMENT, nullable=True),
    sa.Column('result_resource_refs', _JSON_DOCUMENT, nullable=True),
    sa.Column('result_warnings', _JSON_DOCUMENT, nullable=True),
    sa.Column('result_error_code', sa.String(length=128), nullable=True),
    sa.Column('result_error_message', sa.Text(), nullable=True),
    sa.CheckConstraint("risk IN ('unknown', 'read', 'draft', 'write')", name='ck_chat_tool_calls_risk_valid'),
    sa.CheckConstraint("status IN ('requested', 'approval_required', 'approved', 'running', 'succeeded', 'failed', 'rejected')", name='ck_chat_tool_calls_status_valid'),
    sa.CheckConstraint('position >= 0', name='ck_chat_tool_calls_position_non_negative'),
    sa.ForeignKeyConstraint(['assistant_message_id'], ['chat_messages.message_id'], name='fk_chat_tool_calls_assistant_message_id_chat_messages', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.session_id'], name='fk_chat_tool_calls_session_id_chat_sessions', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tool_call_id', name='pk_chat_tool_calls'),
    sa.UniqueConstraint('assistant_message_id', 'position', name='uq_chat_tool_calls_assistant_position')
)

sa.Table(
    'feedback_annotations',
    metadata,
    sa.Column('annotation_id', sa.String(length=64), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('problem_type', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('support_source_refs', _JSON_DOCUMENT, nullable=False),
    sa.Column('dataset_uses', _JSON_DOCUMENT, nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('annotation_digest', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("problem_type IN ('fact_error', 'source_missing', 'evidence_mismatch', 'retrieval_failure', 'tool_failure', 'intent_mismatch', 'incomplete_answer', 'style_or_format', 'undetermined_dissatisfaction')", name='ck_feedback_annotations_feedback_annotation_problem_type_valid'),
    sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name='ck_feedback_annotations_feedback_annotation_severity_valid'),
    sa.CheckConstraint('length(annotation_digest) = 64', name='ck_feedback_annotations_feedback_annotation_digest_length'),
    sa.CheckConstraint('version >= 1', name='ck_feedback_annotations_feedback_annotation_version_positive'),
    sa.ForeignKeyConstraint(['case_id'], ['feedback_cases.case_id'], name='fk_feedback_annotations_case_id_feedback_cases', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('annotation_id', name='pk_feedback_annotations'),
    sa.UniqueConstraint('case_id', 'version', name='uq_feedback_annotations_case_version')
)

sa.Table(
    'feedback_review_decisions',
    metadata,
    sa.Column('decision_id', sa.String(length=64), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('annotation_digest', sa.String(length=64), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('accept', 'reject', 'insufficient', 'withdraw')", name='ck_feedback_review_decisions_feedback_review_decision_valid'),
    sa.CheckConstraint('length(annotation_digest) = 64', name='ck_feedback_review_decisions_feedback_review_digest_length'),
    sa.CheckConstraint('seq >= 1', name='ck_feedback_review_decisions_feedback_review_seq_positive'),
    sa.ForeignKeyConstraint(['case_id'], ['feedback_cases.case_id'], name='fk_feedback_review_decisions_case_id_feedback_cases', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('decision_id', name='pk_feedback_review_decisions'),
    sa.UniqueConstraint('case_id', 'seq', name='uq_feedback_review_case_seq')
)

sa.Table(
    'feedback_dataset_samples',
    metadata,
    sa.Column('sample_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_id', sa.String(length=64), nullable=False),
    sa.Column('source_case_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('current_revision_id', sa.String(length=64), nullable=True),
    sa.Column('confirmed_revision_id', sa.String(length=64), nullable=True),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('source_digest', sa.String(length=64), nullable=False),
    sa.Column('active_job_id', sa.String(length=64), nullable=True),
    sa.Column('missing_reasons', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_by', sa.String(length=64), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'building', 'needs_confirmation', 'needs_input', 'confirmed', 'discarded', 'build_failed')", name=conv('ck_feedback_dataset_samples_feedback_dataset_sample_status_valid')),
    sa.CheckConstraint('generation >= 1', name=conv('ck_feedback_dataset_samples_feedback_dataset_sample_generation_positive')),
    sa.CheckConstraint('length(source_digest) = 64', name=conv('ck_feedback_dataset_samples_feedback_dataset_sample_source_digest_length')),
    sa.ForeignKeyConstraint(['active_job_id'], ['analysis_jobs.job_id'], name='fk_feedback_dataset_samples_active_job_id_analysis_jobs', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['confirmed_revision_id'], ['feedback_sample_revisions.revision_id'], name='fk_feedback_dataset_samples_confirmed_revision', ondelete='RESTRICT', use_alter=True),
    sa.ForeignKeyConstraint(['current_revision_id'], ['feedback_sample_revisions.revision_id'], name='fk_feedback_dataset_samples_current_revision', ondelete='RESTRICT', use_alter=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['feedback_datasets.dataset_id'], name='fk_feedback_dataset_samples_dataset_id_feedback_datasets', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_case_id'], ['feedback_cases.case_id'], name='fk_feedback_dataset_samples_source_case_id_feedback_cases', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('sample_id', name='pk_feedback_dataset_samples'),
    sa.UniqueConstraint('dataset_id', 'source_case_id', name='uq_feedback_dataset_samples_dataset_source_case')
)

sa.Table(
    'feedback_dataset_exports',
    metadata,
    sa.Column('export_id', sa.String(length=64), nullable=False),
    sa.Column('dataset_id', sa.String(length=64), nullable=False),
    sa.Column('export_no', sa.Integer(), nullable=False),
    sa.Column('schema_version', sa.String(length=64), nullable=False),
    sa.Column('rows', _JSON_DOCUMENT, nullable=False),
    sa.Column('provenance', _JSON_DOCUMENT, nullable=False),
    sa.Column('manifest', _JSON_DOCUMENT, nullable=False),
    sa.Column('preview_id', sa.String(length=64), nullable=False),
    sa.Column('preview_digest', sa.String(length=64), nullable=False),
    sa.Column('member_digest', sa.String(length=64), nullable=False),
    sa.Column('content_digest', sa.String(length=64), nullable=False),
    sa.Column('provenance_digest', sa.String(length=64), nullable=False),
    sa.Column('manifest_digest', sa.String(length=64), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('export_no >= 1', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_number_positive')),
    sa.CheckConstraint('length(content_digest) = 64', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_content_len')),
    sa.CheckConstraint('length(manifest_digest) = 64', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_manifest_len')),
    sa.CheckConstraint('length(preview_digest) = 64', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_preview_len')),
    sa.CheckConstraint('length(provenance_digest) = 64', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_provenance_len')),
    sa.CheckConstraint('row_count > 0', name=conv('ck_feedback_dataset_exports_feedback_dataset_export_rows_positive')),
    sa.ForeignKeyConstraint(['dataset_id'], ['feedback_datasets.dataset_id'], name='fk_feedback_dataset_exports_dataset_id_feedback_datasets', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['preview_id'], ['feedback_export_previews.preview_id'], name=conv('fk_feedback_dataset_exports_preview_id_feedback_export_previews'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('export_id', name='pk_feedback_dataset_exports'),
    sa.UniqueConstraint('dataset_id', 'export_no', name='uq_feedback_dataset_exports_number'),
    sa.UniqueConstraint('dataset_id', 'idempotency_key', name='uq_feedback_dataset_exports_idempotency')
)

sa.Table(
    'finding',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('factors_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('outcome', sa.String(length=300), nullable=False),
    sa.Column('direction', sa.String(length=20), nullable=False),
    sa.Column('assertion_strength', sa.String(length=20), nullable=False),
    sa.Column('attribution_scope', sa.String(length=30), nullable=False),
    sa.Column('synthesis_status', sa.String(length=40), nullable=False),
    sa.Column('certainty', sa.Float(), nullable=False),
    sa.Column('display_rank', sa.Integer(), nullable=False),
    sa.Column('mechanisms_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('scientific_context_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('limitations_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('origin', sa.String(length=32), nullable=False),
    sa.Column('source_analysis_version', sa.Integer(), nullable=True),
    sa.Column('parent_finding_id', sa.String(length=128), nullable=True),
    sa.Column('created_by_user_id', sa.String(length=128), nullable=True),
    sa.Column('created_by_tool_call_id', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('warnings_json', _JSON_DOCUMENT, nullable=False),
    sa.CheckConstraint('analysis_version > 0', name='ck_finding_finding_analysis_version_positive'),
    sa.CheckConstraint('certainty >= 0 AND certainty <= 1', name='ck_finding_finding_certainty_range'),
    sa.CheckConstraint('display_rank >= 0', name='ck_finding_finding_display_rank_non_negative'),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_finding_objective_analysis', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_finding'),
    sa.UniqueConstraint('finding_id', name='uq_finding_identity')
)

sa.Table(
    'objective_experiment_selection',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('selection_id', sa.String(length=120), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('experiment_id', sa.String(length=120), nullable=False),
    sa.Column('experiment_version', sa.Integer(), nullable=False),
    sa.Column('revision_id', sa.BigInteger(), nullable=False),
    sa.Column('outcome', sa.String(length=300), nullable=False),
    sa.Column('missing_context_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('reasons_json', _JSON_DOCUMENT, nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_selection_objective_analysis', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['paper_experiment.id'], name='fk_selection_paper_experiment_revision', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name='pk_objective_experiment_selection'),
    sa.UniqueConstraint('selection_id', name='uq_selection_identity')
)

sa.Table(
    'comparison_group',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('group_id', sa.String(length=120), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('analysis_version', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=300), nullable=False),
    sa.Column('comparison_target', sa.String(length=40), nullable=False),
    sa.Column('comparison_basis_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('normalizations_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('limitations_json', _JSON_DOCUMENT, nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id', 'analysis_version'], ['objective_analyses.collection_id', 'objective_analyses.objective_id', 'objective_analyses.analysis_version'], name='fk_comparison_group_objective_analysis', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_comparison_group'),
    sa.UniqueConstraint('group_id', name='uq_comparison_group_identity')
)

sa.Table(
    'objective_experiment_plans',
    metadata,
    sa.Column('plan_id', sa.String(length=128), nullable=False),
    sa.Column('collection_id', sa.String(length=64), nullable=False),
    sa.Column('objective_id', sa.String(length=128), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=64), nullable=False),
    sa.Column('source_message_id', sa.String(length=128), nullable=True),
    sa.Column('source_links', _JSON_DOCUMENT, nullable=False),
    sa.Column('metadata_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('plan_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('parent_plan_id', sa.String(length=128), nullable=True),
    sa.Column('structured_plan', _JSON_DOCUMENT, nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['collection_id', 'objective_id'], ['research_objectives.collection_id', 'research_objectives.objective_id'], name='fk_objective_experiment_plans_objective', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_plan_id'], ['objective_experiment_plans.plan_id'], name='fk_objective_experiment_plans_parent_plan_id', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_message_id'], ['chat_messages.message_id'], name='fk_objective_experiment_plans_source_message_id_chat_messages', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('plan_id', name='pk_objective_experiment_plans'),
    sa.UniqueConstraint('parent_plan_id', name='uq_objective_experiment_plans_parent_plan_id')
)

sa.Table(
    'experimental_variant',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('variant_key', sa.String(length=100), nullable=False),
    sa.Column('variant_label', sa.String(length=300), nullable=False),
    sa.Column('subject_attributes_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('intervention_attributes_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('state_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('population_scope_json', _JSON_DOCUMENT, nullable=True),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_status', sa.String(length=20), nullable=False),
    sa.Column('notes_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('identity_specificity', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('missing_dimensions_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('identity_evidence_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.CheckConstraint("binding_status IN ('direct', 'derived', 'uncertain', 'conflict')", name='ck_experimental_variant_binding_status_valid'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name='fk_experimental_variant_paper_experiment_id_paper_experiment', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_experimental_variant'),
    sa.UniqueConstraint('paper_experiment_id', 'position', name='uq_experimental_variant_revision_position'),
    sa.UniqueConstraint('paper_experiment_id', 'variant_key', name='uq_experimental_variant_revision_key')
)

sa.Table(
    'test_condition',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('test_key', sa.String(length=100), nullable=False),
    sa.Column('test_type', sa.String(length=200), nullable=False),
    sa.Column('parameters_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('population_scope_json', _JSON_DOCUMENT, nullable=True),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_status', sa.String(length=20), nullable=False),
    sa.Column('notes_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('protocol_specificity', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('test_identity_status', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('protocol_completeness', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('missing_parameters_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('method', sa.Text(), nullable=True),
    sa.Column('standard', sa.String(length=200), nullable=True),
    sa.Column('outcome_scope_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('binding_source_refs_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.Column('protocol_evidence_json', _JSON_DOCUMENT, server_default='[]', nullable=False),
    sa.CheckConstraint("binding_status IN ('direct', 'derived', 'uncertain', 'conflict')", name='ck_test_condition_binding_status_valid'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name='fk_test_condition_paper_experiment_id_paper_experiment', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_test_condition'),
    sa.UniqueConstraint('paper_experiment_id', 'position', name='uq_test_condition_revision_position'),
    sa.UniqueConstraint('paper_experiment_id', 'test_key', name='uq_test_condition_revision_key')
)

sa.Table(
    'reported_interpretation',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('statement', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('measurement_keys_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('comparison_keys_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.CheckConstraint("kind IN ('result_summary', 'mechanism_hypothesis', 'limitation')", name='ck_reported_interpretation_kind_valid'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name=conv('fk_reported_interpretation_paper_experiment_id_paper_experiment'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_reported_interpretation'),
    sa.UniqueConstraint('paper_experiment_id', 'position', name='uq_reported_interpretation_revision_position')
)

sa.Table(
    'feedback_sample_revisions',
    metadata,
    sa.Column('revision_id', sa.String(length=64), nullable=False),
    sa.Column('sample_id', sa.String(length=64), nullable=False),
    sa.Column('revision_no', sa.Integer(), nullable=False),
    sa.Column('author_kind', sa.String(length=16), nullable=False),
    sa.Column('content', _JSON_DOCUMENT, nullable=False),
    sa.Column('content_digest', sa.String(length=64), nullable=False),
    sa.Column('input_digest', sa.String(length=64), nullable=False),
    sa.Column('construction_spec_version', sa.Integer(), nullable=False),
    sa.Column('provenance', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('job_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("author_kind IN ('worker', 'human')", name=conv('ck_feedback_sample_revisions_feedback_sample_revision_author_kind_valid')),
    sa.CheckConstraint('construction_spec_version >= 1', name=conv('ck_feedback_sample_revisions_feedback_sample_revision_spec_version_positive')),
    sa.CheckConstraint('length(content_digest) = 64', name=conv('ck_feedback_sample_revisions_feedback_sample_revision_content_digest_length')),
    sa.CheckConstraint('length(input_digest) = 64', name=conv('ck_feedback_sample_revisions_feedback_sample_revision_input_digest_length')),
    sa.CheckConstraint('revision_no >= 1', name=conv('ck_feedback_sample_revisions_feedback_sample_revision_number_positive')),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.job_id'], name='fk_feedback_sample_revisions_job_id_analysis_jobs', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['sample_id'], ['feedback_dataset_samples.sample_id'], name=conv('fk_feedback_sample_revisions_sample_id_feedback_dataset_samples'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('revision_id', name='pk_feedback_sample_revisions'),
    sa.UniqueConstraint('sample_id', 'revision_no', name='uq_feedback_sample_revisions_sample_number')
)

sa.Table(
    'feedback_sample_actions',
    metadata,
    sa.Column('action_id', sa.String(length=64), nullable=False),
    sa.Column('sample_id', sa.String(length=64), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('request_digest', sa.String(length=64), nullable=False),
    sa.Column('expected_revision_id', sa.String(length=64), nullable=True),
    sa.Column('previous_status', sa.String(length=32), nullable=False),
    sa.Column('next_status', sa.String(length=32), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('job_id', sa.String(length=64), nullable=True),
    sa.Column('result_sample', _JSON_DOCUMENT, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("action IN ('rebuild', 'retry', 'discard', 'restore')", name='ck_feedback_sample_actions_feedback_sample_action_type_valid'),
    sa.CheckConstraint('generation >= 1', name=conv('ck_feedback_sample_actions_feedback_sample_action_generation_positive')),
    sa.CheckConstraint('length(request_digest) = 64', name=conv('ck_feedback_sample_actions_feedback_sample_action_digest_length')),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.job_id'], name='fk_feedback_sample_actions_job_id_analysis_jobs', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['sample_id'], ['feedback_dataset_samples.sample_id'], name='fk_feedback_sample_actions_sample_id_feedback_dataset_samples', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('action_id', name='pk_feedback_sample_actions'),
    sa.UniqueConstraint('sample_id', 'idempotency_key', name='uq_feedback_sample_actions_key')
)

sa.Table(
    'finding_selection',
    metadata,
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('selection_id', sa.String(length=120), nullable=False),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.finding_id'], name='fk_finding_selection_finding', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['selection_id'], ['objective_experiment_selection.selection_id'], name='fk_finding_selection_selection', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('finding_id', 'selection_id', name='pk_finding_selection')
)

sa.Table(
    'finding_comparison_group',
    metadata,
    sa.Column('finding_id', sa.String(length=128), nullable=False),
    sa.Column('group_id', sa.String(length=120), nullable=False),
    sa.ForeignKeyConstraint(['finding_id'], ['finding.finding_id'], name='fk_finding_comparison_group_finding', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['comparison_group.group_id'], name='fk_finding_comparison_group_group', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('finding_id', 'group_id', name='pk_finding_comparison_group')
)

sa.Table(
    'comparison_group_member',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('group_id', sa.String(length=120), nullable=False),
    sa.Column('selection_id', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('comparability', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['comparison_group.group_id'], name='fk_comparison_group_member_group', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['selection_id'], ['objective_experiment_selection.selection_id'], name='fk_comparison_group_member_selection', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name='pk_comparison_group_member'),
    sa.UniqueConstraint('group_id', 'selection_id', name='uq_comparison_group_member_identity')
)

sa.Table(
    'measurement_result',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('measurement_key', sa.String(length=100), nullable=False),
    sa.Column('variant_key', sa.String(length=100), nullable=True),
    sa.Column('test_key', sa.String(length=100), nullable=True),
    sa.Column('outcome', sa.String(length=300), nullable=False),
    sa.Column('value_numeric', sa.Numeric(), nullable=True),
    sa.Column('value_text', sa.Text(), nullable=True),
    sa.Column('result_text', sa.Text(), nullable=True),
    sa.Column('unit', sa.String(length=100), nullable=True),
    sa.Column('statistics_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('measurement_scope_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('result_kind', sa.String(length=30), nullable=False),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_status', sa.String(length=20), nullable=False),
    sa.Column('notes_json', _JSON_DOCUMENT, nullable=False),
    sa.CheckConstraint("binding_status IN ('direct', 'derived', 'uncertain', 'conflict')", name='ck_measurement_result_binding_status_valid'),
    sa.CheckConstraint("result_kind IN ('measured', 'observed', 'simulated', 'predicted', 'unknown')", name='ck_measurement_result_result_kind_valid'),
    sa.CheckConstraint('value_numeric IS NOT NULL OR value_text IS NOT NULL OR result_text IS NOT NULL', name='ck_measurement_result_value_present'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'test_key'], ['test_condition.paper_experiment_id', 'test_condition.test_key'], name='fk_measurement_result_revision_test', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'variant_key'], ['experimental_variant.paper_experiment_id', 'experimental_variant.variant_key'], name='fk_measurement_result_revision_variant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name='fk_measurement_result_paper_experiment_id_paper_experiment', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_measurement_result'),
    sa.UniqueConstraint('paper_experiment_id', 'measurement_key', name='uq_measurement_result_revision_key'),
    sa.UniqueConstraint('paper_experiment_id', 'position', name='uq_measurement_result_revision_position')
)

sa.Table(
    'experiment_comparison',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('comparison_key', sa.String(length=100), nullable=False),
    sa.Column('baseline_variant_key', sa.String(length=100), nullable=False),
    sa.Column('target_variant_key', sa.String(length=100), nullable=False),
    sa.Column('outcome', sa.String(length=300), nullable=False),
    sa.Column('changed_variables_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('matched_conditions_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('basis', sa.String(length=20), nullable=False),
    sa.Column('direction', sa.String(length=20), nullable=False),
    sa.Column('reported_statement', sa.Text(), nullable=True),
    sa.Column('attribution_scope', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('reasons_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('binding_source_refs_json', _JSON_DOCUMENT, nullable=False),
    sa.Column('relation_status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("basis IN ('reported', 'derived')", name='ck_experiment_comparison_basis_valid'),
    sa.CheckConstraint("direction IN ('increase', 'decrease', 'no_change', 'mixed', 'unknown')", name='ck_experiment_comparison_direction_valid'),
    sa.CheckConstraint("relation_status IN ('direct', 'derived', 'uncertain', 'conflict')", name='ck_experiment_comparison_relation_status_valid'),
    sa.CheckConstraint("status IN ('ready', 'insufficient_context', 'non_comparable')", name='ck_experiment_comparison_status_valid'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'baseline_variant_key'], ['experimental_variant.paper_experiment_id', 'experimental_variant.variant_key'], name='fk_experiment_comparison_revision_baseline_variant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'target_variant_key'], ['experimental_variant.paper_experiment_id', 'experimental_variant.variant_key'], name='fk_experiment_comparison_revision_target_variant', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name='fk_experiment_comparison_paper_experiment_id_paper_experiment', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_experiment_comparison'),
    sa.UniqueConstraint('paper_experiment_id', 'comparison_key', name='uq_experiment_comparison_revision_key'),
    sa.UniqueConstraint('paper_experiment_id', 'position', name='uq_experiment_comparison_revision_position')
)

sa.Table(
    'feedback_export_members',
    metadata,
    sa.Column('export_id', sa.String(length=64), nullable=False),
    sa.Column('row_key', sa.String(length=64), nullable=False),
    sa.Column('sample_id', sa.String(length=64), nullable=False),
    sa.Column('revision_id', sa.String(length=64), nullable=False),
    sa.Column('content_digest', sa.String(length=64), nullable=False),
    sa.Column('input_digest', sa.String(length=64), nullable=False),
    sa.Column('provenance_digest', sa.String(length=64), nullable=False),
    sa.CheckConstraint('length(content_digest) = 64', name='ck_feedback_export_members_feedback_export_member_content_len'),
    sa.CheckConstraint('length(input_digest) = 64', name='ck_feedback_export_members_feedback_export_member_input_len'),
    sa.CheckConstraint('length(row_key) = 64', name='ck_feedback_export_members_feedback_export_member_row_key_len'),
    sa.ForeignKeyConstraint(['export_id'], ['feedback_dataset_exports.export_id'], name='fk_feedback_export_members_export_id_feedback_dataset_exports', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['feedback_sample_revisions.revision_id'], name=conv('fk_feedback_export_members_revision_id_feedback_sample_revisions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sample_id'], ['feedback_dataset_samples.sample_id'], name='fk_feedback_export_members_sample_id_feedback_dataset_samples', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('export_id', 'row_key', name='pk_feedback_export_members')
)

sa.Table(
    'selection_measurement',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('selection_id', sa.String(length=120), nullable=False),
    sa.Column('revision_id', sa.BigInteger(), nullable=False),
    sa.Column('measurement_id', sa.BigInteger(), nullable=False),
    sa.Column('measurement_key', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['revision_id', 'measurement_key'], ['measurement_result.paper_experiment_id', 'measurement_result.measurement_key'], name='fk_selection_measurement_measurement', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['selection_id'], ['objective_experiment_selection.selection_id'], name='fk_selection_measurement_selection', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_selection_measurement'),
    sa.UniqueConstraint('selection_id', 'measurement_key', name='uq_selection_measurement_member')
)

sa.Table(
    'selection_comparison',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('selection_id', sa.String(length=120), nullable=False),
    sa.Column('revision_id', sa.BigInteger(), nullable=False),
    sa.Column('comparison_id', sa.BigInteger(), nullable=False),
    sa.Column('comparison_key', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['revision_id', 'comparison_key'], ['experiment_comparison.paper_experiment_id', 'experiment_comparison.comparison_key'], name='fk_selection_comparison_comparison', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['selection_id'], ['objective_experiment_selection.selection_id'], name='fk_selection_comparison_selection', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_selection_comparison'),
    sa.UniqueConstraint('selection_id', 'comparison_key', name='uq_selection_comparison_member')
)

sa.Table(
    'experiment_comparison_measurement',
    metadata,
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('paper_experiment_id', sa.BigInteger(), nullable=False),
    sa.Column('comparison_key', sa.String(length=100), nullable=False),
    sa.Column('side', sa.String(length=20), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('measurement_key', sa.String(length=100), nullable=False),
    sa.CheckConstraint("side IN ('baseline', 'target')", name='ck_experiment_comparison_measurement_side_valid'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'comparison_key'], ['experiment_comparison.paper_experiment_id', 'experiment_comparison.comparison_key'], name='fk_experiment_comparison_measurement_comparison', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id', 'measurement_key'], ['measurement_result.paper_experiment_id', 'measurement_result.measurement_key'], name='fk_experiment_comparison_measurement_measurement', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['paper_experiment_id'], ['paper_experiment.id'], name='fk_experiment_comparison_measurement_experiment', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name='pk_experiment_comparison_measurement'),
    sa.UniqueConstraint('paper_experiment_id', 'comparison_key', 'side', 'measurement_key', name='uq_experiment_comparison_measurement_member'),
    sa.UniqueConstraint('paper_experiment_id', 'comparison_key', 'side', 'position', name='uq_experiment_comparison_measurement_position')
)

sa.Index('ix_analysis_jobs_available_at', metadata.tables['analysis_jobs'].c.available_at, unique=False)
sa.Index('ix_analysis_jobs_claim', metadata.tables['analysis_jobs'].c.status, metadata.tables['analysis_jobs'].c.available_at, metadata.tables['analysis_jobs'].c.created_at, unique=False)
sa.Index('ix_analysis_jobs_job_type', metadata.tables['analysis_jobs'].c.job_type, unique=False)
sa.Index('ix_analysis_jobs_lease_expires_at', metadata.tables['analysis_jobs'].c.lease_expires_at, unique=False)
sa.Index('ix_analysis_jobs_status', metadata.tables['analysis_jobs'].c.status, unique=False)
sa.Index('ix_analysis_jobs_worker_id', metadata.tables['analysis_jobs'].c.worker_id, unique=False)
sa.Index('ix_feedback_dataset_migration_runs_created', metadata.tables['feedback_dataset_migration_runs'].c.created_at, unique=False)
sa.Index('ix_collections_owner_user_id', metadata.tables['collections'].c.owner_user_id, unique=False)
sa.Index('ix_finding_feedback_records_collection_id', metadata.tables['finding_feedback_records'].c.collection_id, unique=False)
sa.Index('ix_finding_feedback_records_objective_id', metadata.tables['finding_feedback_records'].c.objective_id, unique=False)
sa.Index('ix_finding_curation_records_collection_id', metadata.tables['finding_curation_records'].c.collection_id, unique=False)
sa.Index('ix_finding_curation_records_objective_id', metadata.tables['finding_curation_records'].c.objective_id, unique=False)
sa.Index('ix_objective_analysis_legacy_checkpoints_objective', metadata.tables['objective_analysis_legacy_checkpoints'].c.collection_id, metadata.tables['objective_analysis_legacy_checkpoints'].c.objective_id, metadata.tables['objective_analysis_legacy_checkpoints'].c.analysis_version, unique=False)
sa.Index('ix_pipeline_runs_collection_id', metadata.tables['pipeline_runs'].c.collection_id, unique=False)
sa.Index('ix_pipeline_runs_pipeline_name', metadata.tables['pipeline_runs'].c.pipeline_name, unique=False)
sa.Index('ix_pipeline_runs_scope_id', metadata.tables['pipeline_runs'].c.scope_id, unique=False)
sa.Index('ix_pipeline_runs_scope_type', metadata.tables['pipeline_runs'].c.scope_type, unique=False)
sa.Index('ix_pipeline_runs_status', metadata.tables['pipeline_runs'].c.status, unique=False)
sa.Index('ix_pipeline_runs_worker_claim', metadata.tables['pipeline_runs'].c.pipeline_name, metadata.tables['pipeline_runs'].c.status, metadata.tables['pipeline_runs'].c.lease_expires_at, metadata.tables['pipeline_runs'].c.created_at, unique=False)
sa.Index('uq_pipeline_runs_active_scope', metadata.tables['pipeline_runs'].c.pipeline_name, metadata.tables['pipeline_runs'].c.scope_type, metadata.tables['pipeline_runs'].c.scope_id, unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"), sqlite_where=sa.text("status IN ('queued', 'running')"))
sa.Index('ix_chat_sessions_collection_id', metadata.tables['chat_sessions'].c.collection_id, unique=False)
sa.Index('ix_chat_sessions_root_session_id', metadata.tables['chat_sessions'].c.root_session_id, unique=False)
sa.Index('ix_chat_sessions_user_collection_updated', metadata.tables['chat_sessions'].c.user_id, metadata.tables['chat_sessions'].c.collection_id, metadata.tables['chat_sessions'].c.updated_at, metadata.tables['chat_sessions'].c.session_id, unique=False)
sa.Index('ix_chat_sessions_user_id', metadata.tables['chat_sessions'].c.user_id, unique=False)
sa.Index('ix_feedback_dataset_collection_created', metadata.tables['feedback_dataset_snapshots'].c.collection_id, metadata.tables['feedback_dataset_snapshots'].c.created_at, unique=False)
sa.Index('ix_feedback_dataset_snapshots_collection_id', metadata.tables['feedback_dataset_snapshots'].c.collection_id, unique=False)
sa.Index('ix_feedback_dataset_snapshots_content_digest', metadata.tables['feedback_dataset_snapshots'].c.content_digest, unique=False)
sa.Index('ix_feedback_dataset_snapshots_dataset_type', metadata.tables['feedback_dataset_snapshots'].c.dataset_type, unique=False)
sa.Index('ix_feedback_dataset_snapshots_manifest_digest', metadata.tables['feedback_dataset_snapshots'].c.manifest_digest, unique=False)
sa.Index('ix_feedback_dataset_snapshots_owner_id', metadata.tables['feedback_dataset_snapshots'].c.owner_id, unique=False)
sa.Index('ix_feedback_dataset_snapshots_provenance_digest', metadata.tables['feedback_dataset_snapshots'].c.provenance_digest, unique=False)
sa.Index('ix_feedback_datasets_collection_created', metadata.tables['feedback_datasets'].c.collection_id, metadata.tables['feedback_datasets'].c.created_at, unique=False)
sa.Index('ix_feedback_datasets_collection_id', metadata.tables['feedback_datasets'].c.collection_id, unique=False)
sa.Index('ix_feedback_datasets_created_by', metadata.tables['feedback_datasets'].c.created_by, unique=False)
sa.Index('ix_documents_collection_id', metadata.tables['documents'].c.collection_id, unique=False)
sa.Index('ix_evaluation_gold_sets_collection_id', metadata.tables['evaluation_gold_sets'].c.collection_id, unique=False)
sa.Index('ix_evaluation_snapshots_collection', metadata.tables['evaluation_prediction_snapshots'].c.collection_id, metadata.tables['evaluation_prediction_snapshots'].c.fact_source, unique=False)
sa.Index('ix_chat_messages_session_id', metadata.tables['chat_messages'].c.session_id, unique=False)
sa.Index('ix_chat_messages_session_role_position', metadata.tables['chat_messages'].c.session_id, metadata.tables['chat_messages'].c.role, metadata.tables['chat_messages'].c.position, unique=False)
sa.Index('ix_chat_model_calls_response_message_id', metadata.tables['chat_model_calls'].c.response_message_id, unique=False)
sa.Index('ix_chat_model_calls_session_id', metadata.tables['chat_model_calls'].c.session_id, unique=False)
sa.Index('ix_chat_model_calls_status', metadata.tables['chat_model_calls'].c.status, unique=False)
sa.Index('ix_chat_model_calls_trigger_message_id', metadata.tables['chat_model_calls'].c.trigger_message_id, unique=False)
sa.Index('ix_feedback_analysis_results_anchor_message_id', metadata.tables['feedback_analysis_results'].c.anchor_message_id, unique=False)
sa.Index('ix_feedback_analysis_results_collection_id', metadata.tables['feedback_analysis_results'].c.collection_id, unique=False)
sa.Index('ix_feedback_analysis_results_feedback_id', metadata.tables['feedback_analysis_results'].c.feedback_id, unique=False)
sa.Index('ix_feedback_analysis_results_job_id', metadata.tables['feedback_analysis_results'].c.job_id, unique=False)
sa.Index('ix_feedback_analysis_results_problem_type', metadata.tables['feedback_analysis_results'].c.problem_type, unique=False)
sa.Index('ix_feedback_analysis_results_session_id', metadata.tables['feedback_analysis_results'].c.session_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_anchor_message_id', metadata.tables['feedback_signal_analysis_results'].c.anchor_message_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_collection_id', metadata.tables['feedback_signal_analysis_results'].c.collection_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_job_id', metadata.tables['feedback_signal_analysis_results'].c.job_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_problem_type', metadata.tables['feedback_signal_analysis_results'].c.problem_type, unique=False)
sa.Index('ix_feedback_signal_analysis_results_session_id', metadata.tables['feedback_signal_analysis_results'].c.session_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_signal_id', metadata.tables['feedback_signal_analysis_results'].c.signal_id, unique=False)
sa.Index('ix_feedback_signal_analysis_results_signal_type', metadata.tables['feedback_signal_analysis_results'].c.signal_type, unique=False)
sa.Index('ix_feedback_signal_analysis_results_trigger_message_id', metadata.tables['feedback_signal_analysis_results'].c.trigger_message_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_assistant_message_id', metadata.tables['tool_failure_analysis_results'].c.assistant_message_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_collection_id', metadata.tables['tool_failure_analysis_results'].c.collection_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_job_id', metadata.tables['tool_failure_analysis_results'].c.job_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_problem_type', metadata.tables['tool_failure_analysis_results'].c.problem_type, unique=False)
sa.Index('ix_tool_failure_analysis_results_result_message_id', metadata.tables['tool_failure_analysis_results'].c.result_message_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_session_id', metadata.tables['tool_failure_analysis_results'].c.session_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_signal_id', metadata.tables['tool_failure_analysis_results'].c.signal_id, unique=False)
sa.Index('ix_tool_failure_analysis_results_signal_type', metadata.tables['tool_failure_analysis_results'].c.signal_type, unique=False)
sa.Index('ix_tool_failure_analysis_results_tool_call_id', metadata.tables['tool_failure_analysis_results'].c.tool_call_id, unique=False)
sa.Index('ix_feedback_cases_anchor_message_id', metadata.tables['feedback_cases'].c.anchor_message_id, unique=False)
sa.Index('ix_feedback_cases_collection_id', metadata.tables['feedback_cases'].c.collection_id, unique=False)
sa.Index('ix_feedback_cases_collection_status', metadata.tables['feedback_cases'].c.collection_id, metadata.tables['feedback_cases'].c.status, metadata.tables['feedback_cases'].c.created_at, unique=False)
sa.Index('ix_feedback_cases_session_id', metadata.tables['feedback_cases'].c.session_id, unique=False)
sa.Index('ix_feedback_cases_status', metadata.tables['feedback_cases'].c.status, unique=False)
sa.Index('ix_feedback_export_previews_dataset_created', metadata.tables['feedback_export_previews'].c.dataset_id, metadata.tables['feedback_export_previews'].c.created_at, unique=False)
sa.Index('ix_feedback_export_previews_dataset_id', metadata.tables['feedback_export_previews'].c.dataset_id, unique=False)
sa.Index('ix_evaluation_runs_collection', metadata.tables['evaluation_runs'].c.collection_id, metadata.tables['evaluation_runs'].c.created_at, unique=False)
sa.Index('ix_objective_analyses_status', metadata.tables['objective_analyses'].c.status, unique=False)
sa.Index('ix_objective_analyses_worker_claim', metadata.tables['objective_analyses'].c.status, metadata.tables['objective_analyses'].c.lease_expires_at, metadata.tables['objective_analyses'].c.created_at, unique=False)
sa.Index('ix_paper_experiment_document_id', metadata.tables['paper_experiment'].c.document_id, unique=False)
sa.Index('ix_paper_experiment_experiment_id', metadata.tables['paper_experiment'].c.experiment_id, unique=False)
sa.Index('ix_chat_tool_calls_session_id', metadata.tables['chat_tool_calls'].c.session_id, unique=False)
sa.Index('ix_feedback_annotations_annotation_digest', metadata.tables['feedback_annotations'].c.annotation_digest, unique=False)
sa.Index('ix_feedback_annotations_case_created', metadata.tables['feedback_annotations'].c.case_id, metadata.tables['feedback_annotations'].c.created_at, unique=False)
sa.Index('ix_feedback_annotations_case_id', metadata.tables['feedback_annotations'].c.case_id, unique=False)
sa.Index('ix_feedback_annotations_created_by', metadata.tables['feedback_annotations'].c.created_by, unique=False)
sa.Index('ix_feedback_review_case_created', metadata.tables['feedback_review_decisions'].c.case_id, metadata.tables['feedback_review_decisions'].c.created_at, unique=False)
sa.Index('ix_feedback_review_decisions_annotation_digest', metadata.tables['feedback_review_decisions'].c.annotation_digest, unique=False)
sa.Index('ix_feedback_review_decisions_case_id', metadata.tables['feedback_review_decisions'].c.case_id, unique=False)
sa.Index('ix_feedback_review_decisions_created_by', metadata.tables['feedback_review_decisions'].c.created_by, unique=False)
sa.Index('ix_feedback_dataset_samples_active_job_id', metadata.tables['feedback_dataset_samples'].c.active_job_id, unique=False)
sa.Index('ix_feedback_dataset_samples_confirmed_by', metadata.tables['feedback_dataset_samples'].c.confirmed_by, unique=False)
sa.Index('ix_feedback_dataset_samples_dataset_id', metadata.tables['feedback_dataset_samples'].c.dataset_id, unique=False)
sa.Index('ix_feedback_dataset_samples_dataset_status', metadata.tables['feedback_dataset_samples'].c.dataset_id, metadata.tables['feedback_dataset_samples'].c.status, metadata.tables['feedback_dataset_samples'].c.updated_at, unique=False)
sa.Index('ix_feedback_dataset_samples_source_case_id', metadata.tables['feedback_dataset_samples'].c.source_case_id, unique=False)
sa.Index('ix_feedback_dataset_samples_status', metadata.tables['feedback_dataset_samples'].c.status, unique=False)
sa.Index('ix_feedback_dataset_exports_dataset_created', metadata.tables['feedback_dataset_exports'].c.dataset_id, metadata.tables['feedback_dataset_exports'].c.created_at, unique=False)
sa.Index('ix_feedback_dataset_exports_dataset_id', metadata.tables['feedback_dataset_exports'].c.dataset_id, unique=False)
sa.Index('ix_feedback_dataset_exports_preview_id', metadata.tables['feedback_dataset_exports'].c.preview_id, unique=False)
sa.Index('ix_finding_collection_id', metadata.tables['finding'].c.collection_id, unique=False)
sa.Index('ix_finding_objective_id', metadata.tables['finding'].c.objective_id, unique=False)
sa.Index('ix_objective_experiment_selection_collection_id', metadata.tables['objective_experiment_selection'].c.collection_id, unique=False)
sa.Index('ix_objective_experiment_selection_objective_id', metadata.tables['objective_experiment_selection'].c.objective_id, unique=False)
sa.Index('ix_objective_experiment_selection_revision_id', metadata.tables['objective_experiment_selection'].c.revision_id, unique=False)
sa.Index('ix_comparison_group_collection_id', metadata.tables['comparison_group'].c.collection_id, unique=False)
sa.Index('ix_comparison_group_objective_id', metadata.tables['comparison_group'].c.objective_id, unique=False)
sa.Index('ix_objective_experiment_plans_collection_id', metadata.tables['objective_experiment_plans'].c.collection_id, unique=False)
sa.Index('ix_objective_experiment_plans_objective_id', metadata.tables['objective_experiment_plans'].c.objective_id, unique=False)
sa.Index('ix_experimental_variant_paper_experiment_id', metadata.tables['experimental_variant'].c.paper_experiment_id, unique=False)
sa.Index('ix_test_condition_paper_experiment_id', metadata.tables['test_condition'].c.paper_experiment_id, unique=False)
sa.Index('ix_reported_interpretation_paper_experiment_id', metadata.tables['reported_interpretation'].c.paper_experiment_id, unique=False)
sa.Index('ix_feedback_sample_revisions_created_by', metadata.tables['feedback_sample_revisions'].c.created_by, unique=False)
sa.Index('ix_feedback_sample_revisions_job_id', metadata.tables['feedback_sample_revisions'].c.job_id, unique=False)
sa.Index('ix_feedback_sample_revisions_sample_created', metadata.tables['feedback_sample_revisions'].c.sample_id, metadata.tables['feedback_sample_revisions'].c.created_at, unique=False)
sa.Index('ix_feedback_sample_revisions_sample_id', metadata.tables['feedback_sample_revisions'].c.sample_id, unique=False)
sa.Index('ix_feedback_sample_actions_sample_created', metadata.tables['feedback_sample_actions'].c.sample_id, metadata.tables['feedback_sample_actions'].c.created_at, unique=False)
sa.Index('ix_measurement_result_outcome', metadata.tables['measurement_result'].c.outcome, unique=False)
sa.Index('ix_measurement_result_paper_experiment_id', metadata.tables['measurement_result'].c.paper_experiment_id, unique=False)
sa.Index('ix_experiment_comparison_paper_experiment_id', metadata.tables['experiment_comparison'].c.paper_experiment_id, unique=False)
sa.Index('ix_feedback_export_members_revision', metadata.tables['feedback_export_members'].c.revision_id, unique=False)
sa.Index('ix_feedback_export_members_sample', metadata.tables['feedback_export_members'].c.sample_id, unique=False)
sa.Index('ix_experiment_comparison_measurement_paper_experiment_id', metadata.tables['experiment_comparison_measurement'].c.paper_experiment_id, unique=False)
