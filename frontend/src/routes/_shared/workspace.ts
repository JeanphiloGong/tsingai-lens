import type { Collection } from './collections';
import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';
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

export type WorkflowStageStatus =
  | 'not_started'
  | 'processing'
  | 'ready'
  | 'limited'
  | 'not_applicable'
  | 'failed';

export type WorkspaceWorkflow = {
  documents: WorkflowStageStatus;
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
  evidence: string;
  comparisons: string;
  protocol: string;
  graph: string;
};

export type WorkspaceCapabilities = {
  can_view_documents: boolean;
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
  return ['not_started', 'processing', 'ready', 'limited', 'not_applicable', 'failed'].includes(status)
    ? status
    : fallback;
}

function defaultLinks(collectionId: string): WorkspaceLinks {
  const encoded = encodeURIComponent(collectionId);
  return {
    workspace: `/collections/${encoded}`,
    documents: `/collections/${encoded}/documents`,
    evidence: `/collections/${encoded}/evidence`,
    comparisons: `/collections/${encoded}/comparisons`,
    protocol: `/collections/${encoded}/protocol`,
    graph: `/collections/${encoded}/graph`
  };
}

function normalizeLinks(value: unknown, collectionId: string): WorkspaceLinks {
  const defaults = defaultLinks(collectionId);
  const record = asRecord(value);
  if (!record) return defaults;

  return {
    workspace: typeof record.workspace === 'string' ? record.workspace : defaults.workspace,
    documents: typeof record.documents === 'string' ? record.documents : defaults.documents,
    evidence: typeof record.evidence === 'string' ? record.evidence : defaults.evidence,
    comparisons: typeof record.comparisons === 'string' ? record.comparisons : defaults.comparisons,
    protocol: typeof record.protocol === 'string' ? record.protocol : defaults.protocol,
    graph: typeof record.graph === 'string' ? record.graph : defaults.graph
  };
}

export function stageIsActionable(status: WorkflowStageStatus | null | undefined) {
  return status === 'ready' || status === 'limited';
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

function deriveLegacyWorkflow(
  collectionId: string,
  fileCount: number,
  latestTask: Task | null,
  artifacts: WorkspaceArtifactStatus
): WorkspaceWorkflow {
  const activeTask =
    latestTask?.status === 'queued' || latestTask?.status === 'running' ? latestTask : null;
  const failedTask = latestTask?.status === 'failed';

  const documents =
    fileCount < 1
      ? 'not_started'
      : artifacts.documents_ready
        ? 'ready'
        : activeTask
          ? 'processing'
          : failedTask
            ? 'failed'
            : 'not_started';

  const fixtureBackboneReady = USE_API_FIXTURES && documents === 'ready';

  return {
    documents,
    evidence:
      fixtureBackboneReady || artifacts.protocol_steps_ready
        ? 'ready'
        : activeTask
          ? 'processing'
          : failedTask
            ? 'failed'
            : 'not_started',
    comparisons:
      fixtureBackboneReady || artifacts.protocol_steps_ready
        ? 'ready'
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
    documents: normalizeStageStatus(record.documents, fallback.documents),
    evidence: normalizeStageStatus(record.evidence, fallback.evidence),
    comparisons: normalizeStageStatus(record.comparisons, fallback.comparisons),
    protocol: normalizeStageStatus(record.protocol, fallback.protocol)
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
    doc_type_counts: normalizeCountRecord(record.doc_type_counts, DEFAULT_DOC_TYPE_COUNTS),
    protocol_extractable_counts: normalizeCountRecord(
      record.protocol_extractable_counts,
      DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS
    ),
    warnings: toStringList(record.warnings)
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

  const file_count = typeof data.file_count === 'number' ? data.file_count : Number(data.file_count ?? 0);
  const artifacts: WorkspaceArtifactStatus = {
    output_path: String((data.artifacts as Record<string, unknown> | undefined)?.output_path ?? ''),
    documents_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.documents_ready),
    graph_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.graph_ready),
    sections_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.sections_ready),
    procedure_blocks_ready: Boolean(
      (data.artifacts as Record<string, unknown> | undefined)?.procedure_blocks_ready
    ),
    protocol_steps_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.protocol_steps_ready),
    graphml_ready: Boolean((data.artifacts as Record<string, unknown> | undefined)?.graphml_ready),
    updated_at: String((data.artifacts as Record<string, unknown> | undefined)?.updated_at ?? '')
  };

  const latest_task = normalizeTask(data.latest_task) ?? null;
  const workflow = normalizeWorkflow(data.workflow, collectionId, file_count, latest_task, artifacts);
  const document_summary = normalizeDocumentSummary(data.document_summary, file_count);
  const warnings = [
    ...document_summary.warnings,
    ...toStringList(data.warnings)
  ].filter((item, index, items) => items.indexOf(item) === index);
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
      ? data.recent_tasks.map((item) => normalizeTask(item)).filter((item): item is Task => item !== null)
      : [],
    capabilities: {
      can_view_documents:
        Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_documents) ||
        stageIsActionable(workflow.documents),
      can_view_evidence:
        Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_evidence) ||
        stageIsActionable(workflow.evidence),
      can_view_comparisons:
        Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_comparisons) ||
        stageIsActionable(workflow.comparisons),
      can_view_graph: Boolean((data.capabilities as Record<string, unknown> | undefined)?.can_view_graph),
      can_download_graphml: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_download_graphml
      ),
      can_view_protocol_steps: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_view_protocol_steps
      ) || stageIsActionable(workflow.protocol),
      can_search_protocol: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_search_protocol
      ) || stageIsActionable(workflow.protocol),
      can_generate_sop: Boolean(
        (data.capabilities as Record<string, unknown> | undefined)?.can_generate_sop
      ) || stageIsActionable(workflow.protocol)
    },
    links
  } satisfies WorkspaceOverview;
}
