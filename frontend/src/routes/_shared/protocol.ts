import { requestJson } from './api';

export type NormalizedValueItem = {
  value?: number | null;
  unit?: string | null;
  raw_value?: string | null;
  operator?: string | null;
  min_value?: number | null;
  max_value?: number | null;
  status?: string | null;
};

export type ConditionItem = {
  temperature?: NormalizedValueItem | null;
  duration?: NormalizedValueItem | null;
  pressure?: NormalizedValueItem | null;
  heating_rate?: NormalizedValueItem | null;
  cooling_rate?: NormalizedValueItem | null;
  ph?: NormalizedValueItem | null;
  atmosphere?: string | null;
  environment?: string | null;
  raw_text?: string | null;
};

export type MaterialRefItem = {
  name?: string | null;
  formula?: string | null;
  role?: string | null;
  amount?: string | null;
  composition_note?: string | null;
  grade?: string | null;
  source_text?: string | null;
};

export type MeasurementSpecItem = {
  method?: string | null;
  instrument?: string | null;
  target_property?: string | null;
  metrics?: string[] | null;
  conditions?: Record<string, unknown> | null;
  output_ref?: string | null;
  source_text?: string | null;
};

export type ControlSpecItem = {
  control_type?: string | null;
  description?: string | null;
  rationale?: string | null;
  source_text?: string | null;
};

export type EvidenceRefItem = {
  paper_id?: string | null;
  section_id?: string | null;
  block_id?: string | null;
  snippet_id?: string | null;
  section_type?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  figure_or_table?: string | null;
  quote_span?: string | null;
  source_text?: string | null;
  confidence_score?: number | null;
};

export type ProtocolStepItem = {
  step_id: string;
  paper_id: string;
  paper_title?: string | null;
  order?: number | null;
  action: string;
  section_id?: string | null;
  block_id?: string | null;
  phase?: string | null;
  materials: MaterialRefItem[];
  conditions?: ConditionItem | null;
  purpose?: string | null;
  expected_output?: string | null;
  characterization: MeasurementSpecItem[];
  controls: ControlSpecItem[];
  evidence_refs: EvidenceRefItem[];
  confidence_score?: number | null;
};

export type ProtocolStepListResponse = {
  collection_id?: string;
  output_path?: string;
  count: number;
  items: ProtocolStepItem[];
};

export type ProtocolSearchHit = {
  step_id: string;
  paper_id: string;
  paper_title?: string | null;
  section_id?: string | null;
  block_id?: string | null;
  action: string;
  matched_fields: string[];
  excerpt?: string | null;
  score?: number | null;
};

export type ProtocolSearchResponse = {
  collection_id?: string;
  query: string;
  output_path?: string;
  count: number;
  items: ProtocolSearchHit[];
};

export type SOPDraftItem = {
  sop_id?: string | null;
  objective?: string | null;
  hypothesis?: string | null;
  variables?: Record<string, unknown> | null;
  constraints?: Record<string, unknown> | null;
  controls: ControlSpecItem[];
  steps: ProtocolStepItem[];
  measurement_plan: MeasurementSpecItem[];
  acceptance_criteria: string[];
  risks: string[];
  open_questions: string[];
  review_status?: string | null;
};

export type SOPDraftResponse = {
  collection_id?: string;
  output_path?: string;
  sop_draft: SOPDraftItem;
  warnings: string[];
};

function normalizeStep(item: unknown): ProtocolStepItem | null {
  if (!item || typeof item !== 'object') return null;
  const record = item as Record<string, unknown>;
  const stepId = String(record.step_id ?? '').trim();
  const paperId = String(record.paper_id ?? '').trim();
  const action = String(record.action ?? '').trim();
  if (!stepId || !paperId || !action) return null;

  return {
    step_id: stepId,
    paper_id: paperId,
    paper_title: typeof record.paper_title === 'string' ? record.paper_title : null,
    order: typeof record.order === 'number' ? record.order : Number(record.order ?? 0),
    action,
    section_id: typeof record.section_id === 'string' ? record.section_id : null,
    block_id: typeof record.block_id === 'string' ? record.block_id : null,
    phase: typeof record.phase === 'string' ? record.phase : null,
    materials: Array.isArray(record.materials) ? (record.materials as MaterialRefItem[]) : [],
    conditions: record.conditions && typeof record.conditions === 'object' ? (record.conditions as ConditionItem) : null,
    purpose: typeof record.purpose === 'string' ? record.purpose : null,
    expected_output: typeof record.expected_output === 'string' ? record.expected_output : null,
    characterization: Array.isArray(record.characterization)
      ? (record.characterization as MeasurementSpecItem[])
      : [],
    controls: Array.isArray(record.controls) ? (record.controls as ControlSpecItem[]) : [],
    evidence_refs: Array.isArray(record.evidence_refs) ? (record.evidence_refs as EvidenceRefItem[]) : [],
    confidence_score:
      typeof record.confidence_score === 'number'
        ? record.confidence_score
        : Number(record.confidence_score ?? 0)
  };
}

export async function listProtocolSteps(
  collectionId: string,
  options: { paperId?: string; blockType?: string; limit?: number; offset?: number } = {}
) {
  const params = new URLSearchParams();
  if (options.paperId?.trim()) params.set('paper_id', options.paperId.trim());
  if (options.blockType?.trim()) params.set('block_type', options.blockType.trim());
  params.set('limit', String(options.limit ?? 20));
  params.set('offset', String(options.offset ?? 0));

  const data = (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/protocol/steps?${params.toString()}`,
    { method: 'GET' }
  )) as Record<string, unknown>;

  const items = Array.isArray(data.items)
    ? data.items.map((item) => normalizeStep(item)).filter((item): item is ProtocolStepItem => item !== null)
    : [];

  return {
    collection_id: typeof data.collection_id === 'string' ? data.collection_id : collectionId,
    output_path: typeof data.output_path === 'string' ? data.output_path : undefined,
    count: typeof data.count === 'number' ? data.count : items.length,
    items
  } satisfies ProtocolStepListResponse;
}

export async function searchProtocolSteps(
  collectionId: string,
  options: { query: string; paperId?: string; limit?: number }
) {
  const params = new URLSearchParams({ q: options.query.trim(), limit: String(options.limit ?? 10) });
  if (options.paperId?.trim()) params.set('paper_id', options.paperId.trim());

  const data = (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/protocol/search?${params.toString()}`,
    { method: 'GET' }
  )) as Record<string, unknown>;

  return {
    collection_id: typeof data.collection_id === 'string' ? data.collection_id : collectionId,
    query: String(data.query ?? options.query),
    output_path: typeof data.output_path === 'string' ? data.output_path : undefined,
    count: typeof data.count === 'number' ? data.count : 0,
    items: Array.isArray(data.items)
      ? data.items.map((item) => {
          const record = item as Record<string, unknown>;
          return {
            step_id: String(record.step_id ?? ''),
            paper_id: String(record.paper_id ?? ''),
            paper_title: typeof record.paper_title === 'string' ? record.paper_title : null,
            section_id: typeof record.section_id === 'string' ? record.section_id : null,
            block_id: typeof record.block_id === 'string' ? record.block_id : null,
            action: String(record.action ?? ''),
            matched_fields: Array.isArray(record.matched_fields)
              ? record.matched_fields.map((value) => String(value))
              : Array.isArray(record.matched_terms)
                ? record.matched_terms.map((value) => String(value))
                : [],
            excerpt: typeof record.excerpt === 'string' ? record.excerpt : null,
            score:
              typeof record.score === 'number' ? record.score : Number.isFinite(Number(record.score)) ? Number(record.score) : null
          } satisfies ProtocolSearchHit;
        })
      : []
  } satisfies ProtocolSearchResponse;
}

export async function generateProtocolSop(
  collectionId: string,
  payload: {
    goal: string;
    targetProperties?: string[];
    paperIds?: string[];
    maxSteps?: number;
  }
) {
  const data = (await requestJson(`/collections/${encodeURIComponent(collectionId)}/protocol/sop`, {
    method: 'POST',
    body: JSON.stringify({
      goal: payload.goal,
      target_properties: payload.targetProperties ?? [],
      paper_ids: payload.paperIds ?? [],
      max_steps: payload.maxSteps ?? 8
    })
  })) as Record<string, unknown>;

  return {
    collection_id: typeof data.collection_id === 'string' ? data.collection_id : collectionId,
    output_path: typeof data.output_path === 'string' ? data.output_path : undefined,
    sop_draft: (data.sop_draft as SOPDraftItem | undefined) ?? {
      controls: [],
      steps: [],
      measurement_plan: [],
      acceptance_criteria: [],
      risks: [],
      open_questions: []
    },
    warnings: Array.isArray(data.warnings) ? data.warnings.map((item) => String(item)) : []
  } satisfies SOPDraftResponse;
}
