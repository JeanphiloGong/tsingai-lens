import type { Collection } from './collections';
import { requestJson } from './api';
import { isTaskActive, type Task } from './tasks';

export type WorkspaceArtifactStatus = {
	source_documents_ready: boolean;
	document_profiles_ready: boolean;
	objective_candidates_ready: boolean;
	updated_at: string;
};

export type WorkflowStageStatus = 'not_started' | 'processing' | 'ready' | 'failed';

export type WorkspaceWorkflow = {
	documents: WorkflowStageStatus;
	objectives: WorkflowStageStatus;
};

export type WorkspaceDocumentSummary = {
	total_documents: number;
	doc_type_counts: Record<'experimental' | 'review' | 'mixed' | 'uncertain', number>;
	warnings: string[];
};

export type WorkspaceLinks = {
	workspace: string;
	documents: string;
	objectives: string;
	comparisons: string;
};

export type WorkspaceCapabilities = {
	can_view_documents: boolean;
	can_view_objectives: boolean;
	can_view_comparisons: boolean;
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
	| 'failed';

export type WorkspaceSurfaceKey = 'documents' | 'objectives' | 'comparisons';

export type OverviewReadinessState =
	| 'empty'
	| 'ready_to_process'
	| 'processing'
	| 'ready'
	| 'failed';

export type OverviewPipelineStepKey = 'upload' | 'documents' | 'objectives';
export type OverviewPipelineStatus = 'completed' | 'processing' | 'pending' | 'failed';

export type OverviewPipelineStep = {
	key: OverviewPipelineStepKey;
	status: OverviewPipelineStatus;
};

const DEFAULT_DOC_TYPE_COUNTS = {
	experimental: 0,
	review: 0,
	mixed: 0,
	uncertain: 0
};

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function toNumber(value: unknown, fallback = 0) {
	const parsed = typeof value === 'number' ? value : Number(value ?? fallback);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function toStringList(value: unknown): string[] {
	if (!Array.isArray(value)) return [];
	return value
		.map((item) => {
			if (typeof item === 'string') return item.trim();
			const record = asRecord(item);
			return String(record?.message ?? '').trim();
		})
		.filter(Boolean);
}

function normalizeCollection(value: unknown): Collection | null {
	const record = asRecord(value);
	const collectionId = String(record?.collection_id ?? record?.id ?? '').trim();
	if (!record || !collectionId) return null;
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

function normalizeOptionalTaskProgressNumber(value: unknown) {
	if (value === null || value === undefined || value === '') return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function normalizeTask(item: unknown): Task | null {
	const record = asRecord(item);
	const taskId = String(record?.task_id ?? '').trim();
	if (!record || !taskId) return null;
	const progress = asRecord(record.progress_detail);
	const phase = String(progress?.phase ?? '').trim();
	return {
		task_id: taskId,
		collection_id: String(record.collection_id ?? ''),
		task_type: String(record.task_type ?? 'build'),
		status: String(record.status ?? 'queued') as Task['status'],
		current_stage: String(record.current_stage ?? 'queued') as Task['current_stage'],
		progress_percent: toNumber(record.progress_percent),
		progress_detail: phase
			? {
					phase,
					current: normalizeOptionalTaskProgressNumber(progress?.current),
					total: normalizeOptionalTaskProgressNumber(progress?.total),
					unit: typeof progress?.unit === 'string' ? progress.unit : null,
					message: typeof progress?.message === 'string' ? progress.message : null,
					active_document_id:
						typeof progress?.active_document_id === 'string'
							? progress.active_document_id
							: null,
					active_objective_id:
						typeof progress?.active_objective_id === 'string'
							? progress.active_objective_id
							: null
				}
			: null,
		output_path: typeof record.output_path === 'string' ? record.output_path : null,
		errors: Array.isArray(record.errors) ? record.errors.map(String) : [],
		warnings: Array.isArray(record.warnings) ? record.warnings.map(String) : [],
		created_at: String(record.created_at ?? ''),
		updated_at: String(record.updated_at ?? ''),
		started_at: typeof record.started_at === 'string' ? record.started_at : null,
		finished_at: typeof record.finished_at === 'string' ? record.finished_at : null
	};
}

function normalizeStage(value: unknown, fallback: WorkflowStageStatus): WorkflowStageStatus {
	const record = asRecord(value);
	const status = String(record?.status ?? value ?? '') as WorkflowStageStatus;
	return ['not_started', 'processing', 'ready', 'failed'].includes(status) ? status : fallback;
}

function deriveWorkflow(
	fileCount: number,
	latestTask: Task | null,
	artifacts: WorkspaceArtifactStatus
): WorkspaceWorkflow {
	const taskActive = isTaskActive(latestTask);
	const taskFailed = latestTask?.status === 'failed' || latestTask?.status === 'partial_success';
	const documents = artifacts.document_profiles_ready
		? 'ready'
		: taskActive
			? 'processing'
			: taskFailed
				? 'failed'
				: 'not_started';
	const objectives = artifacts.objective_candidates_ready
		? 'ready'
		: taskActive && documents === 'ready'
			? 'processing'
			: taskFailed && documents === 'ready'
				? 'failed'
				: 'not_started';
	return fileCount > 0 ? { documents, objectives } : { documents: 'not_started', objectives: 'not_started' };
}

function defaultLinks(collectionId: string): WorkspaceLinks {
	const encoded = encodeURIComponent(collectionId);
	const base = `/collections/${encoded}`;
	return {
		workspace: base,
		documents: `${base}/documents`,
		objectives: `${base}/objectives`,
		comparisons: `${base}/comparisons`
	};
}

function normalizeLinks(value: unknown, collectionId: string): WorkspaceLinks {
	const defaults = defaultLinks(collectionId);
	const record = asRecord(value);
	return {
		workspace: typeof record?.workspace === 'string' ? record.workspace : defaults.workspace,
		documents: typeof record?.documents === 'string' ? record.documents : defaults.documents,
		objectives: typeof record?.objectives === 'string' ? record.objectives : defaults.objectives,
		comparisons:
			typeof record?.comparisons === 'string' ? record.comparisons : defaults.comparisons
	};
}

export function getCollectionWorkspaceState(
	workspace: WorkspaceOverview | null | undefined
): CollectionWorkspaceState {
	if (!workspace || workspace.file_count < 1) return 'empty';
	if (isTaskActive(workspace.latest_task)) return 'processing';
	if (workspace.workflow.objectives !== 'ready') {
		return workspace.workflow.objectives === 'failed' ||
			workspace.latest_task?.status === 'failed' ||
			workspace.latest_task?.status === 'partial_success'
			? 'failed'
			: 'ready_to_process';
	}
	return workspace.warnings.length > 0 || workspace.latest_task?.status === 'partial_success'
		? 'ready_with_limits'
		: 'ready';
}

export function getWorkspaceSurfaceState(
	workspace: WorkspaceOverview | null | undefined,
	surface: WorkspaceSurfaceKey
): WorkspaceSurfaceState {
	if (!workspace || workspace.file_count < 1) return 'empty';
	const stage = surface === 'comparisons' ? workspace.workflow.objectives : workspace.workflow[surface];
	if (stage === 'not_started') return isTaskActive(workspace.latest_task) ? 'processing' : 'ready_to_process';
	return stage;
}

export function getOverviewReadinessState(
	workspace: WorkspaceOverview | null | undefined
): OverviewReadinessState {
	const state = getCollectionWorkspaceState(workspace);
	return state === 'ready_with_limits' ? 'ready' : state;
}

function workflowToPipelineStatus(
	status: WorkflowStageStatus,
	latestTask: Task | null | undefined
): OverviewPipelineStatus {
	if (status === 'ready') return 'completed';
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
			{ key: 'documents', status: 'pending' },
			{ key: 'objectives', status: 'pending' }
		];
	}
	const hasFiles = workspace.file_count > 0;
	return [
		{ key: 'upload', status: hasFiles ? 'completed' : 'pending' },
		{
			key: 'documents',
			status: hasFiles ? workflowToPipelineStatus(workspace.workflow.documents, latestTask) : 'pending'
		},
		{
			key: 'objectives',
			status: hasFiles ? workflowToPipelineStatus(workspace.workflow.objectives, latestTask) : 'pending'
		}
	];
}

export async function fetchWorkspaceOverview(collectionId: string): Promise<WorkspaceOverview> {
	const data = (await requestJson(`/collections/${encodeURIComponent(collectionId)}/workspace`, {
		method: 'GET'
	})) as Record<string, unknown>;
	const collection = normalizeCollection(data.collection);
	if (!collection) throw new Error('Workspace response is missing collection metadata.');

	const fileCount = toNumber(data.file_count);
	const artifactRecord = asRecord(data.artifacts);
	const artifacts: WorkspaceArtifactStatus = {
		source_documents_ready: Boolean(artifactRecord?.source_documents_ready),
		document_profiles_ready: Boolean(artifactRecord?.document_profiles_ready),
		objective_candidates_ready: Boolean(artifactRecord?.objective_candidates_ready),
		updated_at: String(artifactRecord?.updated_at ?? '')
	};
	const latestTask = normalizeTask(data.latest_task);
	const derivedWorkflow = deriveWorkflow(fileCount, latestTask, artifacts);
	const workflowRecord = asRecord(data.workflow);
	const workflow: WorkspaceWorkflow = {
		documents: normalizeStage(workflowRecord?.documents, derivedWorkflow.documents),
		objectives: normalizeStage(workflowRecord?.objectives, derivedWorkflow.objectives)
	};
	const documentRecord = asRecord(data.document_summary);
	const countRecord = asRecord(documentRecord?.by_doc_type);
	const documentSummary: WorkspaceDocumentSummary = {
		total_documents: toNumber(documentRecord?.total_documents, fileCount),
		doc_type_counts: {
			experimental: toNumber(countRecord?.experimental),
			review: toNumber(countRecord?.review),
			mixed: toNumber(countRecord?.mixed),
			uncertain: toNumber(countRecord?.uncertain)
		},
		warnings: []
	};
	const capabilityRecord = asRecord(data.capabilities);
	return {
		collection,
		file_count: fileCount,
		status_summary: String(data.status_summary ?? 'empty'),
		workflow,
		document_summary: documentSummary,
		warnings: toStringList(data.warnings),
		artifacts,
		latest_task: latestTask,
		recent_tasks: Array.isArray(data.recent_tasks)
			? data.recent_tasks.map(normalizeTask).filter((task): task is Task => task !== null)
			: [],
		capabilities: {
			can_view_documents:
				Boolean(capabilityRecord?.can_view_documents) || workflow.documents === 'ready',
			can_view_objectives:
				Boolean(capabilityRecord?.can_view_objectives) || workflow.objectives === 'ready',
			can_view_comparisons:
				Boolean(capabilityRecord?.can_view_comparisons) || workflow.objectives === 'ready'
		},
		links: normalizeLinks(data.links, collectionId)
	};
}
