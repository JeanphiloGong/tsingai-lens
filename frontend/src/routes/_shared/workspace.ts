import type { Collection } from './collections';
import { requestJson } from './api';
import type { Task } from './tasks';

export type WorkspaceArtifactStatus = {
  output_path: string;
  documents_ready: boolean;
  graph_ready: boolean;
  sections_ready: boolean;
  procedure_blocks_ready: boolean;
  protocol_steps_ready: boolean;
  graphml_ready: boolean;
  updated_at: string;
};

export type WorkspaceCapabilities = {
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
  artifacts: WorkspaceArtifactStatus;
  latest_task: Task | null;
  recent_tasks: Task[];
  capabilities: WorkspaceCapabilities;
};

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
    default_method: typeof record.default_method === 'string' ? record.default_method : null,
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
    task_type: String(record.task_type ?? 'index'),
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

export async function fetchWorkspaceOverview(collectionId: string) {
  const data = (await requestJson(`/collections/${encodeURIComponent(collectionId)}/workspace`, {
    method: 'GET'
  })) as Record<string, unknown>;

  const collection = normalizeCollection(data.collection);
  if (!collection) {
    throw new Error('Workspace response is missing collection metadata.');
  }

  return {
    collection,
    file_count: typeof data.file_count === 'number' ? data.file_count : Number(data.file_count ?? 0),
    status_summary: String(data.status_summary ?? 'empty'),
    artifacts: {
      output_path: String((data.artifacts as Record<string, unknown> | undefined)?.output_path ?? ''),
      documents_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.documents_ready),
      graph_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.graph_ready),
      sections_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.sections_ready),
      procedure_blocks_ready: Boolean(
        (data.artifacts as Record<string, unknown> | undefined)?.procedure_blocks_ready
      ),
      protocol_steps_ready: Boolean(
        (data.artifacts as Record<string, unknown> | undefined)?.protocol_steps_ready
      ),
      graphml_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.graphml_ready),
      updated_at: String((data.artifacts as Record<string, unknown> | undefined)?.updated_at ?? '')
    },
    latest_task: normalizeTask(data.latest_task) ?? null,
    recent_tasks: Array.isArray(data.recent_tasks)
      ? data.recent_tasks.map((item) => normalizeTask(item)).filter((item): item is Task => item !== null)
      : [],
    capabilities: {
      can_view_graph: Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_graph),
      can_download_graphml: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_download_graphml
      ),
      can_view_protocol_steps: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_view_protocol_steps
      ),
      can_search_protocol: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_search_protocol
      ),
      can_generate_sop: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_generate_sop
      )
    }
  } satisfies WorkspaceOverview;
}
