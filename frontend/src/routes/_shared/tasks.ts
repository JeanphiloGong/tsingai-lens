import { requestJson } from './api';

export type TaskStatus = 'queued' | 'running' | 'completed' | 'partial_success' | 'failed';

export type TaskStage =
  | 'queued'
  | 'files_registered'
  | 'source_artifacts_started'
  | 'source_artifacts_completed'
  | 'document_profiles_started'
  | 'paper_facts_started'
  | 'comparison_rows_started'
  | 'protocol_artifacts_started'
  | 'artifacts_ready'
  | 'failed';

export type Task = {
  task_id: string;
  collection_id: string;
  task_type: string;
  status: TaskStatus;
  current_stage: TaskStage;
  progress_percent: number;
  output_path?: string | null;
  errors: string[];
  warnings: string[];
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type TaskListResponse = {
  collection_id: string;
  count: number;
  items: Task[];
};

export type CreateBuildTaskPayload = {
  additionalContext?: Record<string, unknown> | null;
};

function normalizeTask(item: unknown): Task | null {
  if (!item || typeof item !== 'object') return null;
  const record = item as Record<string, unknown>;
  const taskId = String(record.task_id ?? '').trim();
  const collectionId = String(record.collection_id ?? '').trim();
  if (!taskId || !collectionId) return null;

  return {
    task_id: taskId,
    collection_id: collectionId,
    task_type: String(record.task_type ?? 'build'),
    status: String(record.status ?? 'queued') as TaskStatus,
    current_stage: String(record.current_stage ?? 'queued') as TaskStage,
    progress_percent:
      typeof record.progress_percent === 'number'
        ? record.progress_percent
        : Number(record.progress_percent ?? 0),
    output_path: typeof record.output_path === 'string' ? record.output_path : null,
    errors: Array.isArray(record.errors) ? record.errors.map((item) => String(item)) : [],
    warnings: Array.isArray(record.warnings) ? record.warnings.map((item) => String(item)) : [],
    created_at: String(record.created_at ?? ''),
    updated_at: String(record.updated_at ?? ''),
    started_at: typeof record.started_at === 'string' ? record.started_at : null,
    finished_at: typeof record.finished_at === 'string' ? record.finished_at : null
  };
}

export function isTaskActive(task: Task | null | undefined) {
  if (!task) return false;
  return task.status === 'queued' || task.status === 'running';
}

export function isTaskFinished(task: Task | null | undefined) {
  if (!task) return false;
  return task.status === 'completed' || task.status === 'partial_success' || task.status === 'failed';
}

export async function createBuildTask(collectionId: string, payload: CreateBuildTaskPayload = {}) {
  const body: Record<string, unknown> = {};

  if (payload.additionalContext !== undefined) {
    body.additional_context = payload.additionalContext ?? null;
  }

  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/tasks/build`, {
    method: 'POST',
    body: JSON.stringify(body)
  });

  const task = normalizeTask(data);
  if (!task) {
    throw new Error('Task response is missing task_id.');
  }
  return task;
}

export async function getTask(taskId: string) {
  const data = await requestJson(`/tasks/${encodeURIComponent(taskId)}`, { method: 'GET' });
  const task = normalizeTask(data);
  if (!task) {
    throw new Error('Task response is missing task_id.');
  }
  return task;
}

export async function listCollectionTasks(
  collectionId: string,
  options: { status?: string; limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams();
  if (options.status?.trim()) params.set('status', options.status.trim());
  params.set('limit', String(options.limit ?? 20));
  params.set('offset', String(options.offset ?? 0));

  const data = await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/tasks?${params.toString()}`,
    { method: 'GET' }
  );

  const record = data as Record<string, unknown>;
  const items = Array.isArray(record?.items)
    ? record.items.map((item) => normalizeTask(item)).filter((item): item is Task => item !== null)
    : [];

  return {
    collection_id: String(record?.collection_id ?? collectionId),
    count: typeof record?.count === 'number' ? record.count : items.length,
    items
  } satisfies TaskListResponse;
}
