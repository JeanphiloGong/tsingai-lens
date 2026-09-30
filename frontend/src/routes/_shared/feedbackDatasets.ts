import { downloadBlob, requestJson } from './api';

export type FeedbackDatasetTaskType = 'sft' | 'preference' | 'evaluation';
export type DatasetExportFormat = 'jsonl' | 'json' | 'provenance' | 'manifest';

export type FeedbackDataset = {
	dataset_id: string;
	collection_id: string;
	name: string;
	task_type: FeedbackDatasetTaskType;
	construction_spec: Record<string, unknown>;
	spec_version: number;
	created_by: string;
	created_at: string;
	updated_at: string;
};

export type SftMessage = { role: 'system' | 'user' | 'assistant'; content: string };
export type SftText = { document_title: string; text: string };
export type SftRevisionContent = {
	schema_version: 'literature-sft.v1';
	messages: SftMessage[];
	context: SftText[];
	target: string;
	evidence: SftText[];
};
export type PreferenceChoice = 'a' | 'b' | 'tie' | 'unclear';
export type PreferenceRevisionContent = {
	schema_version: 'literature-preference.v1';
	messages: SftMessage[];
	context: SftText[];
	response_a: string;
	response_b: string;
	suggested_preference: PreferenceChoice | null;
	rationale: string;
	evidence: SftText[];
	human_preference: PreferenceChoice | null;
};
export type EvaluationRevisionContent = {
	schema_version: 'literature-evaluation.v1';
	messages: SftMessage[];
	context: SftText[];
	reference: string;
	criteria: string[];
	evaluation_mode: 'reference' | 'rubric';
	evidence: SftText[];
};
export type RevisionContent = SftRevisionContent | PreferenceRevisionContent | EvaluationRevisionContent;

export type DatasetSample = {
	sample_id: string;
	dataset_id: string;
	source_case_id: string;
	status: string;
	current_revision_id: string | null;
	confirmed_revision_id: string | null;
	generation: number;
	missing_reasons: string[];
	created_at: string;
	updated_at: string;
	confirmed_by: string | null;
	confirmed_at: string | null;
};

export type DatasetSampleAction = 'rebuild' | 'retry' | 'discard' | 'restore';

export type DatasetSampleRevision = {
	revision_id: string;
	sample_id: string;
	revision_no: number;
	author_kind: 'worker' | 'human';
	content: RevisionContent;
	content_digest: string;
	input_digest: string;
	construction_spec_version: number;
	provenance: Record<string, unknown>;
	created_at: string;
	created_by: string | null;
	job_id: string | null;
};

export type DatasetSampleSourceCase = {
	case_id: string;
	collection_id: string;
	session_id: string;
	anchor_message_id: string;
	status: string;
	question: string;
	answer: string;
	requested_scope: Array<Record<string, unknown>>;
	inspected_sources: Array<Record<string, unknown>>;
	omitted_candidates: Array<Record<string, unknown>>;
	gaps: string[];
	context_snapshot: Record<string, unknown>;
};

export type DatasetSampleDetail = {
	sample: DatasetSample;
	source_case: DatasetSampleSourceCase;
	current_revision: DatasetSampleRevision | null;
	confirmed_revision: DatasetSampleRevision | null;
};

export type DatasetExportIssue = {
	sample_id: string;
	revision_id: string | null;
	code: string;
	message: string;
	question: string;
};

export type DatasetExportPreviewRow = {
	sample_id: string;
	question: string;
	schema_version: string;
	target_preview: string;
	response_a_preview: string;
	response_b_preview: string;
	reference_preview: string;
	human_preference: PreferenceChoice | null;
	evidence_count: number;
	issue_codes: string[];
};

export type DatasetExportPreview = {
	preview_id: string;
	dataset_id: string;
	requested_count: number;
	exportable_count: number;
	issues: DatasetExportIssue[];
	sample_rows: DatasetExportPreviewRow[];
	preview_digest: string;
	created_at: string;
	expires_at: string;
};

export type DatasetExportSummary = {
	export_id: string;
	dataset_id: string;
	export_no: number;
	schema_version: string;
	row_count: number;
	content_digest: string;
	provenance_digest: string;
	manifest_digest: string;
	created_at: string;
	download_formats: DatasetExportFormat[];
};

function datasetPath(datasetId = '') {
	return `/feedback-datasets${datasetId ? `/${encodeURIComponent(datasetId)}` : ''}`;
}

export async function createFeedbackDataset(
	collectionId: string,
	name: string,
	taskType: FeedbackDatasetTaskType = 'sft',
	constructionSpec: Record<string, unknown> = {}
) {
	return (await requestJson(datasetPath(), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			collection_id: collectionId,
			name,
			task_type: taskType,
			construction_spec: constructionSpec
		})
	})) as FeedbackDataset;
}

export async function fetchFeedbackDatasets(
	collectionId: string,
	options: { limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams({
		collection_id: collectionId,
		limit: String(options.limit ?? 50),
		offset: String(options.offset ?? 0)
	});
	return (await requestJson(`${datasetPath()}?${params.toString()}`, { method: 'GET' })) as {
		items: FeedbackDataset[];
		limit: number;
		offset: number;
	};
}

export async function fetchFeedbackDataset(datasetId: string) {
	return (await requestJson(datasetPath(datasetId), { method: 'GET' })) as FeedbackDataset;
}

function samplePath(datasetId: string, suffix = '') {
	return `${datasetPath(datasetId)}/samples${suffix}`;
}

export async function collectDatasetCases(datasetId: string, sourceCaseIds: string[]) {
	return await requestJson(`${datasetPath(datasetId)}/collections`, {
		method: 'POST', headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ source_case_ids: sourceCaseIds })
	}) as { created_count: number; existing_count: number };
}

export async function fetchDatasetSamples(
	datasetId: string,
	options: { status?: string; limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams({
		limit: String(options.limit ?? 100),
		offset: String(options.offset ?? 0)
	});
	if (options.status) params.set('status', options.status);
	return (await requestJson(`${samplePath(datasetId)}?${params.toString()}`, { method: 'GET' })) as {
		items: DatasetSample[];
		total: number;
		limit: number;
		offset: number;
	};
}

export async function fetchDatasetSample(datasetId: string, sampleId: string) {
	return (await requestJson(`${samplePath(datasetId)}/${encodeURIComponent(sampleId)}`, {
		method: 'GET'
	})) as DatasetSampleDetail;
}

export async function updateDatasetSample(
	datasetId: string,
	sampleId: string,
	input: { expected_revision_id: string; content: RevisionContent }
) {
	return (await requestJson(`${samplePath(datasetId)}/${encodeURIComponent(sampleId)}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(input)
	})) as DatasetSample;
}

export async function confirmDatasetSample(
	datasetId: string,
	sampleId: string,
	expectedRevisionId: string
) {
	return (await requestJson(
		`${samplePath(datasetId)}/${encodeURIComponent(sampleId)}/confirm`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ expected_revision_id: expectedRevisionId })
		}
	)) as DatasetSample;
}

export async function actOnDatasetSample(
	datasetId: string,
	sampleId: string,
	input: {
		action: DatasetSampleAction;
		expected_revision_id: string | null;
		reason?: string;
	},
	idempotencyKey: string
) {
	return (await requestJson(
		`${samplePath(datasetId)}/${encodeURIComponent(sampleId)}/actions`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
			body: JSON.stringify(input)
		}
	)) as DatasetSample;
}

export async function previewFeedbackDatasetExport(datasetId: string, sampleIds?: string[]) {
	return (await requestJson(`${datasetPath(datasetId)}/export-previews`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ sample_ids: sampleIds })
	})) as DatasetExportPreview;
}

export async function publishFeedbackDatasetExport(
	datasetId: string,
	input: { preview_id: string; preview_digest: string; allow_partial: boolean },
	idempotencyKey: string
) {
	return (await requestJson(`${datasetPath(datasetId)}/exports`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
		body: JSON.stringify(input)
	})) as DatasetExportSummary;
}

export async function fetchFeedbackDatasetExports(
	datasetId: string,
	options: { limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams({
		limit: String(options.limit ?? 50),
		offset: String(options.offset ?? 0)
	});
	return (await requestJson(`${datasetPath(datasetId)}/exports?${params.toString()}`, {
		method: 'GET'
	})) as { items: DatasetExportSummary[]; limit: number; offset: number };
}

export async function downloadFeedbackDatasetExport(
	datasetId: string,
	exportItem: DatasetExportSummary,
	format: DatasetExportFormat
) {
	const extension = format === 'provenance' ? 'jsonl' : format === 'jsonl' ? 'jsonl' : 'json';
	const suffix = format === 'provenance' ? 'provenance' : format === 'manifest' ? 'manifest' : 'data';
	await downloadBlob(
		`${datasetPath(datasetId)}/exports/${encodeURIComponent(exportItem.export_id)}/download?format=${format}`,
		`${datasetId}-v${exportItem.export_no}-${suffix}.${extension}`
	);
}
