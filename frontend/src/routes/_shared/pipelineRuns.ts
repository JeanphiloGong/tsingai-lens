import { requestJson } from './api';

export type PipelineRunStatus = 'queued' | 'running' | 'completed' | 'partial_success' | 'failed';

export type PipelineRunProgressDetail = {
	phase: string;
	current?: number | null;
	total?: number | null;
	unit?: string | null;
	message?: string | null;
	active_document_id?: string | null;
	active_objective_id?: string | null;
};

export type PipelineRunSummary = {
	run_id: string;
	pipeline_name: string;
	scope_type: string;
	scope_id: string;
	status: PipelineRunStatus;
	current_node: string | null;
	progress_percent: number;
	progress_detail?: PipelineRunProgressDetail | null;
	errors: string[];
	warnings: string[];
	updated_at: string;
};

export type PipelineRun = PipelineRunSummary & {
	collection_id: string;
	mode: string;
	input_fingerprint: string | null;
	nodes: Record<string, unknown>;
	stats: Record<string, unknown>;
	context: Record<string, unknown>;
	resumed_from_run_id?: string | null;
	created_at: string;
	started_at?: string | null;
	finished_at?: string | null;
};

export type PipelineRunListResponse = {
	collection_id: string;
	count: number;
	items: PipelineRunSummary[];
};

export function isPipelineRunActive(run: PipelineRunSummary | null | undefined) {
	if (!run) return false;
	return run.status === 'queued' || run.status === 'running';
}

export function isPipelineRunFinished(run: PipelineRunSummary | null | undefined) {
	if (!run) return false;
	return run.status === 'completed' || run.status === 'partial_success' || run.status === 'failed';
}

export async function prepareCollectionDocument(collectionId: string, documentId: string) {
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/preparation`,
		{
			method: 'POST'
		}
	);

	const run = data as PipelineRun;
	if (run.collection_id !== collectionId || run.scope_id !== documentId) {
		throw new Error('PipelineRun response does not match the requested document.');
	}
	return run;
}

export async function formCollectionResearchQuestions(collectionId: string, documentIds: string[]) {
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/objective-discovery`,
		{
			method: 'POST',
			body: JSON.stringify({ document_ids: documentIds })
		}
	);

	const run = data as PipelineRun;
	if (run.collection_id !== collectionId) {
		throw new Error('PipelineRun response does not match collection_id.');
	}
	return run;
}

export async function getPipelineRun(runId: string) {
	const data = await requestJson(`/pipeline-runs/${encodeURIComponent(runId)}`, { method: 'GET' });
	const run = data as PipelineRun;
	if (run.run_id !== runId) {
		throw new Error('PipelineRun response does not match run_id.');
	}
	return run;
}

export async function listCollectionPipelineRuns(
	collectionId: string,
	options: { status?: string; limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams();
	if (options.status?.trim()) params.set('status', options.status.trim());
	params.set('limit', String(options.limit ?? 20));
	params.set('offset', String(options.offset ?? 0));

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/pipeline-runs?${params.toString()}`,
		{ method: 'GET' }
	);

	const record = data as PipelineRunListResponse;
	if (record.collection_id !== collectionId) {
		throw new Error('PipelineRun list response does not match collection_id.');
	}
	return record;
}
