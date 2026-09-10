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

function normalizePipelineRunSummary(item: unknown): PipelineRunSummary | null {
	if (!item || typeof item !== 'object') return null;
	const record = item as Record<string, unknown>;
	const runId = String(record.run_id ?? '').trim();
	if (!runId) return null;

	return {
		run_id: runId,
		pipeline_name: String(record.pipeline_name ?? 'document_preparation'),
		scope_type: String(record.scope_type ?? ''),
		scope_id: String(record.scope_id ?? ''),
		status: String(record.status ?? 'queued') as PipelineRunStatus,
		current_node: typeof record.current_node === 'string' ? record.current_node : null,
		progress_percent:
			typeof record.progress_percent === 'number'
				? record.progress_percent
				: Number(record.progress_percent ?? 0),
		progress_detail: normalizeProgressDetail(record.progress_detail),
		errors: Array.isArray(record.errors) ? record.errors.map((item) => String(item)) : [],
		warnings: Array.isArray(record.warnings) ? record.warnings.map((item) => String(item)) : [],
		updated_at: String(record.updated_at ?? '')
	};
}

function normalizePipelineRun(item: unknown): PipelineRun | null {
	const summary = normalizePipelineRunSummary(item);
	if (!summary || !item || typeof item !== 'object') return null;
	const record = item as Record<string, unknown>;
	const collectionId = String(record.collection_id ?? '').trim();
	if (!collectionId) return null;

	return {
		...summary,
		collection_id: collectionId,
		mode: String(record.mode ?? 'standard'),
		input_fingerprint:
			typeof record.input_fingerprint === 'string' ? record.input_fingerprint : null,
		nodes:
			record.nodes && typeof record.nodes === 'object' && !Array.isArray(record.nodes)
				? (record.nodes as Record<string, unknown>)
				: {},
		stats:
			record.stats && typeof record.stats === 'object' && !Array.isArray(record.stats)
				? (record.stats as Record<string, unknown>)
				: {},
		context:
			record.context && typeof record.context === 'object' && !Array.isArray(record.context)
				? (record.context as Record<string, unknown>)
				: {},
		resumed_from_run_id:
			typeof record.resumed_from_run_id === 'string' ? record.resumed_from_run_id : null,
		created_at: String(record.created_at ?? ''),
		started_at: typeof record.started_at === 'string' ? record.started_at : null,
		finished_at: typeof record.finished_at === 'string' ? record.finished_at : null
	};
}

function normalizeProgressDetail(value: unknown): PipelineRunProgressDetail | null {
	if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
	const record = value as Record<string, unknown>;
	const phase = String(record.phase ?? '').trim();
	if (!phase) return null;
	return {
		phase,
		current: normalizeOptionalNumber(record.current),
		total: normalizeOptionalNumber(record.total),
		unit: typeof record.unit === 'string' ? record.unit : null,
		message: typeof record.message === 'string' ? record.message : null,
		active_document_id:
			typeof record.active_document_id === 'string' ? record.active_document_id : null,
		active_objective_id:
			typeof record.active_objective_id === 'string' ? record.active_objective_id : null
	};
}

function normalizeOptionalNumber(value: unknown) {
	if (value === null || value === undefined || value === '') return null;
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

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

	const run = normalizePipelineRun(data);
	if (!run) {
		throw new Error('PipelineRun response is missing run_id.');
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

	const run = normalizePipelineRun(data);
	if (!run) {
		throw new Error('PipelineRun response is missing run_id.');
	}
	return run;
}

export async function getPipelineRun(runId: string) {
	const data = await requestJson(`/pipeline-runs/${encodeURIComponent(runId)}`, { method: 'GET' });
	const run = normalizePipelineRun(data);
	if (!run) {
		throw new Error('PipelineRun response is missing run_id.');
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

	const record = data as Record<string, unknown>;
	const items = Array.isArray(record?.items)
		? record.items
				.map((item) => normalizePipelineRunSummary(item))
				.filter((item): item is PipelineRunSummary => item !== null)
		: [];

	return {
		collection_id: String(record?.collection_id ?? collectionId),
		count: typeof record?.count === 'number' ? record.count : items.length,
		items
	} satisfies PipelineRunListResponse;
}
