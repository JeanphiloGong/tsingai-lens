import type { Collection } from './collections';
import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';
import { isTaskActive, type Task } from './tasks';

export type WorkspaceArtifactStatus = {
	output_path: string;
	documents_generated: boolean;
	documents_ready: boolean;
	document_profiles_generated: boolean;
	document_profiles_ready: boolean;
	evidence_cards_generated: boolean;
	evidence_cards_ready: boolean;
	comparable_results_generated: boolean;
	comparable_results_ready: boolean;
	collection_comparable_results_generated: boolean;
	collection_comparable_results_ready: boolean;
	collection_comparable_results_stale: boolean;
	comparison_rows_generated: boolean;
	comparison_rows_ready: boolean;
	comparison_rows_stale: boolean;
	graph_generated: boolean;
	graph_ready: boolean;
	graph_stale: boolean;
	procedure_blocks_generated: boolean;
	procedure_blocks_ready: boolean;
	protocol_steps_generated: boolean;
	protocol_steps_ready: boolean;
	updated_at: string;
};

export type WorkflowStageStatus =
	| 'not_started'
	| 'processing'
	| 'ready'
	| 'limited'
	| 'not_applicable'
	| 'failed';

export type WorkspaceWorkflow = {
	documents: WorkflowStageStatus;
	results: WorkflowStageStatus;
	evidence: WorkflowStageStatus;
	comparisons: WorkflowStageStatus;
	protocol: WorkflowStageStatus;
};

export type WorkspaceDocumentSummary = {
	total_documents: number;
	doc_type_counts: Record<'experimental' | 'review' | 'mixed' | 'uncertain', number>;
	protocol_extractable_counts: Record<'yes' | 'partial' | 'no' | 'uncertain', number>;
	warnings: string[];
};

export type WorkspaceLinks = {
	workspace: string;
	documents: string;
	results: string;
	evidence: string;
	comparisons: string;
	protocol: string;
	graph: string;
};

export type WorkspaceCapabilities = {
	can_view_documents: boolean;
	can_view_results: boolean;
	can_view_evidence: boolean;
	can_view_comparisons: boolean;
	can_view_graph: boolean;
	can_download_graphml: boolean;
	can_view_protocol_steps: boolean;
	can_search_protocol: boolean;
	can_generate_sop: boolean;
};

export type WorkspaceOverview = {
	collection: Collection;
	file_count: number;
	status_summary: string;
	workflow: WorkspaceWorkflow;
	document_summary: WorkspaceDocumentSummary;
	warnings: string[];
	artifacts: WorkspaceArtifactStatus;
	latest_task: Task | null;
	recent_tasks: Task[];
	capabilities: WorkspaceCapabilities;
	links: WorkspaceLinks;
};

export type CollectionWorkspaceState =
	| 'empty'
	| 'ready_to_process'
	| 'processing'
	| 'ready'
	| 'ready_with_limits'
	| 'failed';

export type WorkspaceSurfaceState =
	| 'empty'
	| 'ready_to_process'
	| 'processing'
	| 'ready'
	| 'limited'
	| 'not_applicable'
	| 'failed';

export type WorkspaceSurfaceKey = keyof WorkspaceWorkflow | 'graph';

export type OverviewReadinessState =
	| 'empty'
	| 'ready_to_process'
	| 'processing'
	| 'ready'
	| 'failed';

export type OverviewPipelineStepKey = 'upload' | 'parse' | 'evidence' | 'comparisons' | 'graph';

export type OverviewPipelineStatus = 'completed' | 'processing' | 'pending' | 'failed';

export type OverviewPipelineStep = {
	key: OverviewPipelineStepKey;
	status: OverviewPipelineStatus;
};

const PRIMARY_WORKFLOW_KEYS = ['comparisons', 'documents'] as const;

const DEFAULT_DOC_TYPE_COUNTS = {
	experimental: 0,
	review: 0,
	mixed: 0,
	uncertain: 0
};

const DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS = {
	yes: 0,
	partial: 0,
	no: 0,
	uncertain: 0
};

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function toNumber(value: unknown, fallback = 0) {
	return typeof value === 'number' && Number.isFinite(value) ? value : Number(value ?? fallback);
}

function toStringList(value: unknown): string[] {
	if (Array.isArray(value)) {
		return value
			.map((item) => {
				if (typeof item === 'string') return item;
				const record = asRecord(item);
				if (!record) return '';
				return String(record.message ?? record.label ?? record.code ?? '').trim();
			})
			.filter((item) => item !== '');
	}

	if (typeof value === 'string' && value.trim() !== '') {
		return [value.trim()];
	}

	return [];
}

function normalizeStageStatus(value: unknown, fallback: WorkflowStageStatus): WorkflowStageStatus {
	const status = String(value ?? '').trim() as WorkflowStageStatus;
	return ['not_started', 'processing', 'ready', 'limited', 'not_applicable', 'failed'].includes(
		status
	)
		? status
		: fallback;
}

function normalizeStageEntry(value: unknown, fallback: WorkflowStageStatus): WorkflowStageStatus {
	const record = asRecord(value);
	return normalizeStageStatus(record?.status ?? value, fallback);
}

function defaultLinks(collectionId: string): WorkspaceLinks {
	const encoded = encodeURIComponent(collectionId);
	return {
		workspace: `/collections/${encoded}`,
		documents: `/collections/${encoded}/documents`,
		results: `/collections/${encoded}/results`,
		evidence: `/collections/${encoded}/evidence`,
		comparisons: `/collections/${encoded}/comparisons`,
		protocol: `/collections/${encoded}/protocol`,
		graph: `/collections/${encoded}/graph`
	};
}

function normalizeWorkspaceRoute(
	value: unknown,
	fallback: string,
	collectionId: string,
	surface: 'workspace' | 'documents' | 'results' | 'evidence' | 'comparisons' | 'protocol' | 'graph'
) {
	if (typeof value !== 'string' || !value.trim()) return fallback;

	const normalized = value.trim();
	const encoded = encodeURIComponent(collectionId);
	const apiPrefix = `/api/v1/collections/${encoded}`;
	const routeMap = {
		workspace: `/collections/${encoded}`,
		documents: `/collections/${encoded}/documents`,
		results: `/collections/${encoded}/results`,
		evidence: `/collections/${encoded}/evidence`,
		comparisons: `/collections/${encoded}/comparisons`,
		protocol: `/collections/${encoded}/protocol`,
		graph: `/collections/${encoded}/graph`
	} as const;

	if (surface === 'evidence') {
		return routeMap.evidence;
	}

	if (!normalized.startsWith('/api/')) {
		return normalized;
	}

	if (surface === 'workspace' && normalized === `${apiPrefix}/workspace`) {
		return routeMap.workspace;
	}
	if (surface === 'documents' && normalized === `${apiPrefix}/documents/profiles`) {
		return routeMap.documents;
	}
	if (
		surface === 'results' &&
		(normalized === `${apiPrefix}/results` ||
			normalized === `/api/v1/comparable-results?collection_id=${encoded}`)
	) {
		return routeMap.results;
	}
	if (surface === 'comparisons' && normalized === `${apiPrefix}/comparisons`) {
		return routeMap.comparisons;
	}
	if (surface === 'protocol' && normalized.startsWith(`${apiPrefix}/protocol/`)) {
		return routeMap.protocol;
	}
	if (surface === 'graph' && normalized.startsWith(`${apiPrefix}/graph`)) {
		return routeMap.graph;
	}

	return fallback;
}

function normalizeLinks(value: unknown, collectionId: string): WorkspaceLinks {
	const defaults = defaultLinks(collectionId);
	const record = asRecord(value);
	if (!record) return defaults;

	return {
		workspace: normalizeWorkspaceRoute(
			record.workspace,
			defaults.workspace,
			collectionId,
			'workspace'
		),
		documents: normalizeWorkspaceRoute(
			record.documents ?? record.documents_profiles,
			defaults.documents,
			collectionId,
			'documents'
		),
		results: normalizeWorkspaceRoute(
			record.results ?? record.comparable_results,
			defaults.results,
			collectionId,
			'results'
		),
		evidence: normalizeWorkspaceRoute(
			record.evidence ?? record.evidence_cards,
			defaults.evidence,
			collectionId,
			'evidence'
		),
		comparisons: normalizeWorkspaceRoute(
			record.comparisons,
			defaults.comparisons,
			collectionId,
			'comparisons'
		),
		protocol: normalizeWorkspaceRoute(
			record.protocol ?? record.protocol_steps,
			defaults.protocol,
			collectionId,
			'protocol'
		),
		graph: normalizeWorkspaceRoute(record.graph, defaults.graph, collectionId, 'graph')
	};
}

export function stageIsActionable(
	status: WorkflowStageStatus | WorkspaceSurfaceState | null | undefined
) {
	return status === 'ready' || status === 'limited';
}

export function countActionablePrimaryViews(workspace: WorkspaceOverview | null | undefined) {
	if (!workspace) return 0;
	return PRIMARY_WORKFLOW_KEYS.filter((key) => stageIsActionable(workspace.workflow[key])).length;
}

export function getCollectionWorkspaceState(
	workspace: WorkspaceOverview | null | undefined
): CollectionWorkspaceState {
	if (!workspace || workspace.file_count < 1) {
		return 'empty';
	}

	if (isTaskActive(workspace.latest_task)) {
		return 'processing';
	}

	const actionablePrimaryViews = countActionablePrimaryViews(workspace);
	const failedPrimaryViews = PRIMARY_WORKFLOW_KEYS.filter(
		(key) => workspace.workflow[key] === 'failed'
	).length;

	if (actionablePrimaryViews === 0) {
		return failedPrimaryViews > 0 || workspace.latest_task?.status === 'failed'
			? 'failed'
			: 'ready_to_process';
	}

	const hasLimits =
		Object.values(workspace.workflow).some((status) =>
			['limited', 'not_applicable', 'failed'].includes(status)
		) || workspace.warnings.length > 0;

	return hasLimits ? 'ready_with_limits' : 'ready';
}

export function getWorkspaceSurfaceState(
	workspace: WorkspaceOverview | null | undefined,
	surface: WorkspaceSurfaceKey
): WorkspaceSurfaceState {
	if (!workspace || workspace.file_count < 1) {
		return 'empty';
	}

	if (surface === 'graph') {
		if (workspace.artifacts.graph_stale) {
			return 'limited';
		}

		// Graph readiness is semantic-artifact-driven. Do not fall back to row cache here.
		if (
			workspace.capabilities.can_view_graph ||
			workspace.capabilities.can_download_graphml ||
			workspace.artifacts.graph_ready
		) {
			return 'ready';
		}

		if (isTaskActive(workspace.latest_task)) {
			return 'processing';
		}

		if (workspace.latest_task?.status === 'failed') {
			return 'failed';
		}

		return countActionablePrimaryViews(workspace) > 0 ? 'not_applicable' : 'ready_to_process';
	}

	const stage = workspace.workflow[surface];
	if (stage === 'not_started') {
		return isTaskActive(workspace.latest_task) ? 'processing' : 'ready_to_process';
	}

	return stage;
}

export function getOverviewReadinessState(
	workspace: WorkspaceOverview | null | undefined
): OverviewReadinessState {
	const workspaceState = getCollectionWorkspaceState(workspace);

	if (workspaceState === 'ready' || workspaceState === 'ready_with_limits') {
		return 'ready';
	}

	return workspaceState;
}

function workflowToPipelineStatus(
	status: WorkflowStageStatus | WorkspaceSurfaceState | null | undefined,
	latestTask: Task | null | undefined
): OverviewPipelineStatus {
	if (status === 'ready' || status === 'limited') return 'completed';
	if (status === 'failed') return 'failed';
	if (status === 'processing' || isTaskActive(latestTask)) return 'processing';
	return 'pending';
}

export function buildOverviewPipelineSteps(
	workspace: WorkspaceOverview | null | undefined,
	latestTask: Task | null | undefined = workspace?.latest_task
): OverviewPipelineStep[] {
	if (!workspace) {
		return [
			{ key: 'upload', status: 'pending' },
			{ key: 'parse', status: 'pending' },
			{ key: 'evidence', status: 'pending' },
			{ key: 'comparisons', status: 'pending' },
			{ key: 'graph', status: 'pending' }
		];
	}

	const hasFiles = workspace.file_count > 0;
	const graphState = getWorkspaceSurfaceState(workspace, 'graph');

	return [
		{ key: 'upload', status: hasFiles ? 'completed' : 'pending' },
		{
			key: 'parse',
			status: hasFiles ? workflowToPipelineStatus(workspace.workflow.documents, latestTask) : 'pending'
		},
		{
			key: 'evidence',
			status: hasFiles ? workflowToPipelineStatus(workspace.workflow.evidence, latestTask) : 'pending'
		},
		{
			key: 'comparisons',
			status: hasFiles
				? workflowToPipelineStatus(workspace.workflow.comparisons, latestTask)
				: 'pending'
		},
		{
			key: 'graph',
			status:
				graphState === 'ready' || graphState === 'limited'
					? 'completed'
					: graphState === 'failed'
						? 'failed'
						: graphState === 'processing'
							? 'processing'
							: 'pending'
		}
	];
}

function normalizeCollection(item: unknown): Collection | null {
	if (!item || typeof item !== 'object') return null;
	const record = item as Record<string, unknown>;
	const collectionId = String(record.collection_id ?? record.id ?? '').trim();
	if (!collectionId) return null;
	return {
		id: collectionId,
		collection_id: collectionId,
		name: typeof record.name === 'string' ? record.name : null,
		description: typeof record.description === 'string' ? record.description : null,
		status: typeof record.status === 'string' ? record.status : null,
		paper_count:
			typeof record.paper_count === 'number'
				? record.paper_count
				: typeof record.document_count === 'number'
					? record.document_count
					: null,
		entity_count: typeof record.entity_count === 'number' ? record.entity_count : null,
		created_at: typeof record.created_at === 'string' ? record.created_at : undefined,
		updated_at: typeof record.updated_at === 'string' ? record.updated_at : undefined
	};
}

function normalizeTask(item: unknown): Task | null {
	if (!item || typeof item !== 'object') return null;
	const record = item as Record<string, unknown>;
	const taskId = String(record.task_id ?? '').trim();
	if (!taskId) return null;
	return {
		task_id: taskId,
		collection_id: String(record.collection_id ?? ''),
		task_type: String(record.task_type ?? 'build'),
		status: String(record.status ?? 'queued') as Task['status'],
		current_stage: String(record.current_stage ?? 'queued') as Task['current_stage'],
		progress_percent:
			typeof record.progress_percent === 'number'
				? record.progress_percent
				: Number(record.progress_percent ?? 0),
		output_path: typeof record.output_path === 'string' ? record.output_path : null,
		errors: Array.isArray(record.errors) ? record.errors.map((value) => String(value)) : [],
		warnings: Array.isArray(record.warnings) ? record.warnings.map((value) => String(value)) : [],
		created_at: String(record.created_at ?? ''),
		updated_at: String(record.updated_at ?? ''),
		started_at: typeof record.started_at === 'string' ? record.started_at : null,
		finished_at: typeof record.finished_at === 'string' ? record.finished_at : null
	};
}

function deriveLegacyWorkflow(
	collectionId: string,
	fileCount: number,
	latestTask: Task | null,
	artifacts: WorkspaceArtifactStatus
): WorkspaceWorkflow {
	const activeTask = isTaskActive(latestTask) ? latestTask : null;
	const failedTask = latestTask?.status === 'failed';

	const documents =
		fileCount < 1
			? 'not_started'
			: artifacts.document_profiles_ready || artifacts.documents_ready
				? 'ready'
				: activeTask
					? 'processing'
					: failedTask
						? 'failed'
						: 'not_started';

	return {
		documents,
		results:
			artifacts.collection_comparable_results_ready || (USE_API_FIXTURES && documents === 'ready')
				? 'ready'
				: artifacts.collection_comparable_results_stale
					? 'limited'
					: activeTask
						? 'processing'
						: failedTask
							? 'failed'
							: 'not_started',
		evidence:
			artifacts.evidence_cards_ready || (USE_API_FIXTURES && documents === 'ready')
				? 'ready'
				: activeTask
					? 'processing'
					: failedTask
						? 'failed'
						: 'not_started',
		// The comparisons page is still row-facing in the current frontend.
		// Keep that fallback local to workflow/comparison UI; graph readiness is separate.
		comparisons:
			artifacts.collection_comparable_results_ready ||
			artifacts.comparison_rows_ready ||
			(USE_API_FIXTURES && documents === 'ready')
				? 'ready'
				: artifacts.collection_comparable_results_stale || artifacts.comparison_rows_stale
					? 'limited'
					: activeTask
						? 'processing'
						: failedTask
							? 'failed'
							: 'not_started',
		protocol: artifacts.protocol_steps_ready
			? 'ready'
			: activeTask
				? 'processing'
				: fileCount > 0 && collectionId
					? 'limited'
					: 'not_started'
	};
}

function normalizeWorkflow(
	value: unknown,
	collectionId: string,
	fileCount: number,
	latestTask: Task | null,
	artifacts: WorkspaceArtifactStatus
): WorkspaceWorkflow {
	const record = asRecord(value);
	const fallback = deriveLegacyWorkflow(collectionId, fileCount, latestTask, artifacts);
	if (!record) return fallback;

	return {
		documents: normalizeStageEntry(record.documents, fallback.documents),
		results: normalizeStageEntry(record.results, fallback.results),
		evidence: normalizeStageEntry(record.evidence, fallback.evidence),
		comparisons: normalizeStageEntry(record.comparisons, fallback.comparisons),
		protocol: normalizeStageEntry(record.protocol, fallback.protocol)
	};
}

function normalizeCountRecord<T extends string>(
	value: unknown,
	defaults: Record<T, number>
): Record<T, number> {
	const record = asRecord(value);
	if (!record) return { ...defaults };

	const output = { ...defaults };
	for (const key of Object.keys(defaults) as T[]) {
		output[key] = toNumber(record[key], defaults[key]);
	}
	return output;
}

function normalizeDocumentSummary(value: unknown, fileCount: number): WorkspaceDocumentSummary {
	const record = asRecord(value);
	if (!record) {
		return {
			total_documents: fileCount,
			doc_type_counts: { ...DEFAULT_DOC_TYPE_COUNTS },
			protocol_extractable_counts: { ...DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS },
			warnings: []
		};
	}

	return {
		total_documents: toNumber(record.total_documents ?? record.total, fileCount),
		doc_type_counts: normalizeCountRecord(
			record.doc_type_counts ?? record.by_doc_type,
			DEFAULT_DOC_TYPE_COUNTS
		),
		protocol_extractable_counts: normalizeCountRecord(
			record.protocol_extractable_counts ?? record.by_protocol_extractable,
			DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS
		),
		warnings: toStringList(record.warnings)
	};
}

function normalizeArtifacts(value: unknown): WorkspaceArtifactStatus {
	const record = asRecord(value);

	return {
		output_path: String(record?.output_path ?? ''),
		documents_generated: Boolean(record?.documents_generated),
		documents_ready: Boolean(record?.documents_ready),
		document_profiles_generated: Boolean(record?.document_profiles_generated),
		document_profiles_ready: Boolean(record?.document_profiles_ready),
		evidence_cards_generated: Boolean(record?.evidence_cards_generated),
		evidence_cards_ready: Boolean(record?.evidence_cards_ready),
		comparable_results_generated: Boolean(record?.comparable_results_generated),
		comparable_results_ready: Boolean(record?.comparable_results_ready),
		collection_comparable_results_generated: Boolean(
			record?.collection_comparable_results_generated
		),
		collection_comparable_results_ready: Boolean(record?.collection_comparable_results_ready),
		collection_comparable_results_stale: Boolean(record?.collection_comparable_results_stale),
		comparison_rows_generated: Boolean(record?.comparison_rows_generated),
		comparison_rows_ready: Boolean(record?.comparison_rows_ready),
		comparison_rows_stale: Boolean(record?.comparison_rows_stale),
		graph_generated: Boolean(record?.graph_generated),
		graph_ready: Boolean(record?.graph_ready),
		graph_stale: Boolean(record?.graph_stale),
		procedure_blocks_generated: Boolean(record?.procedure_blocks_generated),
		procedure_blocks_ready: Boolean(record?.procedure_blocks_ready),
		protocol_steps_generated: Boolean(record?.protocol_steps_generated),
		protocol_steps_ready: Boolean(record?.protocol_steps_ready),
		updated_at: String(record?.updated_at ?? '')
	};
}

export async function fetchWorkspaceOverview(collectionId: string) {
	const data = (await requestJson(`/collections/${encodeURIComponent(collectionId)}/workspace`, {
		method: 'GET'
	})) as Record<string, unknown>;

	const collection = normalizeCollection(data.collection);
	if (!collection) {
		throw new Error('Workspace response is missing collection metadata.');
	}

	const file_count =
		typeof data.file_count === 'number' ? data.file_count : Number(data.file_count ?? 0);
	const artifacts = normalizeArtifacts(data.artifacts);

	const latest_task = normalizeTask(data.latest_task) ?? null;
	const workflow = normalizeWorkflow(
		data.workflow,
		collectionId,
		file_count,
		latest_task,
		artifacts
	);
	const document_summary = normalizeDocumentSummary(data.document_summary, file_count);
	const warnings = [...document_summary.warnings, ...toStringList(data.warnings)].filter(
		(item, index, items) => items.indexOf(item) === index
	);
	const links = normalizeLinks(data.links, collectionId);

	return {
		collection,
		file_count,
		status_summary: String(data.status_summary ?? 'empty'),
		workflow,
		document_summary,
		warnings,
		artifacts,
		latest_task,
		recent_tasks: Array.isArray(data.recent_tasks)
			? data.recent_tasks
					.map((item) => normalizeTask(item))
					.filter((item): item is Task => item !== null)
			: [],
		capabilities: {
			can_view_documents:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_documents) ||
				stageIsActionable(workflow.documents),
			can_view_results:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_results) ||
				stageIsActionable(workflow.results),
			can_view_evidence:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_evidence) ||
				stageIsActionable(workflow.evidence),
			can_view_comparisons:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_comparisons) ||
				stageIsActionable(workflow.comparisons),
			can_view_graph: Boolean(
				(data.capabilities as Record<string, unknown> | undefined)?.can_view_graph
			),
			can_download_graphml: Boolean(
				(data.capabilities as Record<string, unknown> | undefined)?.can_download_graphml
			),
			can_view_protocol_steps:
				Boolean(
					(data.capabilities as Record<string, unknown> | undefined)?.can_view_protocol_steps
				) || stageIsActionable(workflow.protocol),
			can_search_protocol:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_search_protocol) ||
				stageIsActionable(workflow.protocol),
			can_generate_sop:
				Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_generate_sop) ||
				stageIsActionable(workflow.protocol)
		},
		links
	} satisfies WorkspaceOverview;
}
