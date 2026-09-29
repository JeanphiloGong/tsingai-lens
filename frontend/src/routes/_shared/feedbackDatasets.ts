import { requestJson } from './api';

export type FeedbackDatasetTaskType = 'sft' | 'preference' | 'evaluation';

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
	content: SftRevisionContent;
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

function datasetPath(datasetId = '') {
	return `/feedback-datasets${datasetId ? `/${encodeURIComponent(datasetId)}` : ''}`;
}

export async function createFeedbackDataset(
	collectionId: string,
	name: string,
	constructionSpec: Record<string, unknown> = {}
) {
	return (await requestJson(datasetPath(), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			collection_id: collectionId,
			name,
			task_type: 'sft',
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
	input: { expected_revision_id: string; content: SftRevisionContent }
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
