import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type ComparabilityStatus = 'comparable' | 'limited' | 'not_comparable' | 'insufficient';

export type ComparisonRow = {
  row_id: string;
  collection_id: string;
  source_document_id: string;
  supporting_evidence_ids: string[];
  material_system_normalized: string;
  process_normalized: string;
  property_normalized: string;
  baseline_normalized: string;
  test_condition_normalized: string;
  comparability_status: ComparabilityStatus;
  comparability_warnings: string[];
};

export type ComparisonsResponse = {
  collection_id: string;
  total: number;
  count: number;
  items: ComparisonRow[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? '').trim()).filter((item) => item !== '');
  }
  if (typeof value === 'string' && value.trim() !== '') {
    return [value.trim()];
  }
  return [];
}

function normalizeRow(value: unknown, collectionId: string): ComparisonRow | null {
  const record = asRecord(value);
  if (!record) return null;

  const row_id = String(record.row_id ?? record.id ?? '').trim();
  if (!row_id) return null;

  const comparability_status = String(record.comparability_status ?? 'insufficient') as ComparabilityStatus;

  return {
    row_id,
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    source_document_id: String(record.source_document_id ?? record.document_id ?? '').trim(),
    supporting_evidence_ids: toStringList(record.supporting_evidence_ids),
    material_system_normalized: String(record.material_system_normalized ?? '--').trim() || '--',
    process_normalized: String(record.process_normalized ?? '--').trim() || '--',
    property_normalized: String(record.property_normalized ?? '--').trim() || '--',
    baseline_normalized: String(record.baseline_normalized ?? '--').trim() || '--',
    test_condition_normalized: String(record.test_condition_normalized ?? '--').trim() || '--',
    comparability_status: ['comparable', 'limited', 'not_comparable', 'insufficient'].includes(
      comparability_status
    )
      ? comparability_status
      : 'insufficient',
    comparability_warnings: toStringList(record.comparability_warnings)
  };
}

function buildFixture(collectionId: string): ComparisonsResponse {
  const items: ComparisonRow[] = [
    {
      row_id: 'cmp_1',
      collection_id: collectionId,
      source_document_id: 'doc_a',
      supporting_evidence_ids: ['ev_1'],
      material_system_normalized: 'High-entropy oxide',
      process_normalized: 'Reduced oxygen anneal',
      property_normalized: 'Cycle retention',
      baseline_normalized: 'Air annealed sample',
      test_condition_normalized: '200 cycles',
      comparability_status: 'comparable',
      comparability_warnings: []
    },
    {
      row_id: 'cmp_2',
      collection_id: collectionId,
      source_document_id: 'doc_c',
      supporting_evidence_ids: ['ev_2'],
      material_system_normalized: 'Layered oxide',
      process_normalized: 'Carbon coating',
      property_normalized: 'Impedance',
      baseline_normalized: 'Reference not fully specified',
      test_condition_normalized: 'EIS after 50 cycles',
      comparability_status: 'limited',
      comparability_warnings: ['Baseline is only partially aligned across documents.']
    },
    {
      row_id: 'cmp_3',
      collection_id: collectionId,
      source_document_id: 'doc_b',
      supporting_evidence_ids: [],
      material_system_normalized: 'Interface strategy review',
      process_normalized: 'Narrative survey',
      property_normalized: 'Cycle stability',
      baseline_normalized: '--',
      test_condition_normalized: '--',
      comparability_status: 'not_comparable',
      comparability_warnings: ['Review-only source; not a directly comparable experiment row.']
    }
  ];

  return {
    collection_id: collectionId,
    total: items.length,
    count: items.length,
    items
  };
}

function normalizeResponse(value: unknown, collectionId: string): ComparisonsResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Comparisons response is invalid.');
  }

  const items = Array.isArray(record.items)
    ? record.items.map((item) => normalizeRow(item, collectionId)).filter((item): item is ComparisonRow => item !== null)
    : [];

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    total: typeof record.total === 'number' ? record.total : items.length,
    count: typeof record.count === 'number' ? record.count : items.length,
    items
  };
}

export async function fetchComparisons(collectionId: string): Promise<ComparisonsResponse> {
  if (USE_API_FIXTURES) {
    return buildFixture(collectionId);
  }

  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/comparisons`, {
    method: 'GET'
  });
  return normalizeResponse(data, collectionId);
}
