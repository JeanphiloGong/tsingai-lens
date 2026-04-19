import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type EvidenceSourceType = 'figure' | 'table' | 'method' | 'text';
export type TraceabilityStatus = 'direct' | 'partial' | 'missing';
export type LocatorType = 'char_range' | 'bbox' | 'section';
export type LocatorConfidence = 'high' | 'medium' | 'low';
export type TracebackStatus = 'ready' | 'partial' | 'unavailable';

export type EvidenceCharRange = {
  start: number;
  end: number;
};

export type EvidenceBoundingBox = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type EvidenceAnchor = {
  anchor_id: string;
  document_id: string;
  locator_type: LocatorType;
  locator_confidence: LocatorConfidence;
  source_type: EvidenceSourceType;
  section_id: string | null;
  char_range: EvidenceCharRange | null;
  bbox: EvidenceBoundingBox | null;
  page: number | null;
  quote: string | null;
  deep_link: string | null;
  block_id: string | null;
  snippet_id: string | null;
  figure_or_table: string | null;
  quote_span: string | null;
  anchor_type: string;
  label: string;
};

export type ConditionContext = {
  process: string[];
  baseline: string[];
  test: string[];
};

export type EvidenceCard = {
  evidence_id: string;
  document_id: string;
  collection_id: string;
  claim_text: string;
  claim_type: string;
  evidence_source_type: EvidenceSourceType;
  evidence_anchors: EvidenceAnchor[];
  material_system: string;
  condition_context: ConditionContext;
  confidence: number | null;
  traceability_status: TraceabilityStatus;
};

export type EvidenceCardsResponse = {
  collection_id: string;
  total: number;
  count: number;
  items: EvidenceCard[];
};

export type EvidenceTracebackResponse = {
  collection_id: string;
  evidence_id: string;
  traceback_status: TracebackStatus;
  anchors: EvidenceAnchor[];
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

function toNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : Number(value ?? NaN);
}

function toOptionalText(value: unknown) {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? text : null;
}

function normalizeCharRange(value: unknown): EvidenceCharRange | null {
  const record = asRecord(value);
  if (!record) return null;
  const start = toNumber(record.start);
  const end = toNumber(record.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return { start, end };
}

function normalizeBbox(value: unknown): EvidenceBoundingBox | null {
  const record = asRecord(value);
  if (!record) return null;
  const x0 = toNumber(record.x0);
  const y0 = toNumber(record.y0);
  const x1 = toNumber(record.x1);
  const y1 = toNumber(record.y1);
  if (![x0, y0, x1, y1].every((item) => Number.isFinite(item))) return null;
  return { x0, y0, x1, y1 };
}

function buildTracebackLink(
  collectionId: string,
  documentId: string,
  evidenceId: string,
  anchorId: string
) {
  if (!documentId) return null;
  return `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}?evidence_id=${encodeURIComponent(evidenceId)}&anchor_id=${encodeURIComponent(anchorId)}`;
}

function normalizeAnchor(
  value: unknown,
  collectionId: string,
  documentId: string,
  evidenceId: string,
  index: number
): EvidenceAnchor | null {
  const record = asRecord(value);
  if (!record) {
    const label = String(value ?? '').trim();
    return label
      ? {
          anchor_id: `anchor_${index + 1}`,
          document_id: documentId,
          locator_type: 'section',
          locator_confidence: 'low',
          source_type: 'text',
          section_id: null,
          char_range: null,
          bbox: null,
          page: null,
          quote: label,
          deep_link: buildTracebackLink(collectionId, documentId, evidenceId, `anchor_${index + 1}`),
          block_id: null,
          snippet_id: null,
          figure_or_table: null,
          quote_span: label,
          anchor_type: 'text',
          label
        }
      : null;
  }

  const anchor_id = String(record.anchor_id ?? record.id ?? `anchor_${index + 1}`);
  const anchorDocumentId = String(record.document_id ?? documentId ?? '').trim();
  const char_range = normalizeCharRange(record.char_range);
  const bbox = normalizeBbox(record.bbox);
  const rawLocatorType = String(record.locator_type ?? '').trim() as LocatorType;
  const locator_type: LocatorType = ['char_range', 'bbox', 'section'].includes(rawLocatorType)
    ? rawLocatorType
    : char_range
      ? 'char_range'
      : bbox
        ? 'bbox'
        : 'section';
  const rawConfidence = String(record.locator_confidence ?? '').trim() as LocatorConfidence;
  const locator_confidence: LocatorConfidence = ['high', 'medium', 'low'].includes(rawConfidence)
    ? rawConfidence
    : char_range || bbox
      ? 'medium'
      : 'low';
  const source_type = String(record.source_type ?? record.anchor_type ?? record.type ?? 'text') as EvidenceSourceType;
  const quote = toOptionalText(record.quote) ?? toOptionalText(record.quote_span);
  const label = String(
    record.label ??
      quote ??
      record.figure_or_table ??
      record.section_id ??
      record.snippet_id ??
      record.value ??
      source_type
  ).trim();

  return {
    anchor_id,
    document_id: anchorDocumentId,
    locator_type,
    locator_confidence,
    source_type: ['figure', 'table', 'method', 'text'].includes(source_type) ? source_type : 'text',
    section_id: toOptionalText(record.section_id),
    char_range,
    bbox,
    page: Number.isFinite(toNumber(record.page)) ? toNumber(record.page) : null,
    quote,
    deep_link:
      toOptionalText(record.deep_link) ?? buildTracebackLink(collectionId, anchorDocumentId, evidenceId, anchor_id),
    block_id: toOptionalText(record.block_id),
    snippet_id: toOptionalText(record.snippet_id),
    figure_or_table: toOptionalText(record.figure_or_table),
    quote_span: quote,
    anchor_type: String(record.anchor_type ?? record.type ?? source_type ?? 'text'),
    label: label || quote || anchor_id
  };
}

function normalizeAnchors(
  value: unknown,
  collectionId: string,
  documentId: string,
  evidenceId: string
): EvidenceAnchor[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item, index) => normalizeAnchor(item, collectionId, documentId, evidenceId, index))
    .filter((item): item is EvidenceAnchor => item !== null);
}

function flattenContextValues(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) {
    return Array.from(
      new Set(value.flatMap((item) => flattenContextValues(item)).filter((item) => item !== ''))
    );
  }
  if (typeof value === 'string') {
    const normalized = value.trim();
    return normalized ? [normalized] : [];
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return [String(value)];
  }

  const record = asRecord(value);
  if (!record) return [];

  return Array.from(
    new Set(
      Object.values(record)
        .flatMap((item) => flattenContextValues(item))
        .filter((item) => item !== '')
    )
  );
}

function normalizeMaterialSystem(value: unknown): string {
  const record = asRecord(value);
  if (!record) {
    return String(value ?? '--').trim() || '--';
  }

  const family = String(record.family ?? '').trim();
  const composition = String(record.composition ?? '').trim();
  if (family && composition && family !== composition) {
    return `${family} (${composition})`;
  }
  return family || composition || '--';
}

function normalizeConditionContext(value: unknown): ConditionContext {
  const record = asRecord(value);
  if (!record) {
    return {
      process: [],
      baseline: [],
      test: []
    };
  }

  return {
    process: flattenContextValues(record.process),
    baseline: flattenContextValues(record.baseline),
    test: flattenContextValues(record.test)
  };
}

function normalizeCard(value: unknown, collectionId: string): EvidenceCard | null {
  const record = asRecord(value);
  if (!record) return null;

  const evidence_id = String(record.evidence_id ?? record.id ?? '').trim();
  if (!evidence_id) return null;

  const confidence = toNumber(record.confidence);
  const evidence_source_type = String(record.evidence_source_type ?? 'text') as EvidenceSourceType;
  const traceability_status = String(record.traceability_status ?? 'missing') as TraceabilityStatus;

  return {
    evidence_id,
    document_id: String(record.document_id ?? '').trim(),
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    claim_text: String(record.claim_text ?? '').trim(),
    claim_type: String(record.claim_type ?? 'claim').trim(),
    evidence_source_type: ['figure', 'table', 'method', 'text'].includes(evidence_source_type)
      ? evidence_source_type
      : 'text',
    evidence_anchors: normalizeAnchors(record.evidence_anchors, collectionId, String(record.document_id ?? '').trim(), evidence_id),
    material_system: normalizeMaterialSystem(record.material_system),
    condition_context: normalizeConditionContext(record.condition_context),
    confidence: Number.isFinite(confidence) ? confidence : null,
    traceability_status: ['direct', 'partial', 'missing'].includes(traceability_status)
      ? traceability_status
      : 'missing'
  };
}

function buildFixture(collectionId: string): EvidenceCardsResponse {
  const items: EvidenceCard[] = [
    {
      evidence_id: 'ev_1',
      document_id: 'doc_a',
      collection_id: collectionId,
      claim_text: 'Annealing at lower oxygen partial pressure improved cycle retention.',
      claim_type: 'property',
      evidence_source_type: 'figure',
      evidence_anchors: [
        {
          anchor_id: 'a1',
          document_id: 'doc_a',
          locator_type: 'section',
          locator_confidence: 'low',
          source_type: 'figure',
          section_id: 'results',
          char_range: null,
          bbox: null,
          page: null,
          quote: 'Figure 3b',
          deep_link: `/collections/${collectionId}/documents/doc_a?evidence_id=ev_1&anchor_id=a1`,
          block_id: null,
          snippet_id: null,
          figure_or_table: 'Figure 3b',
          quote_span: 'Figure 3b',
          anchor_type: 'figure',
          label: 'Figure 3b'
        },
        {
          anchor_id: 'a2',
          document_id: 'doc_a',
          locator_type: 'char_range',
          locator_confidence: 'medium',
          source_type: 'text',
          section_id: 'results',
          char_range: { start: 120, end: 188 },
          bbox: null,
          page: null,
          quote: 'Results section paragraph 4',
          deep_link: `/collections/${collectionId}/documents/doc_a?evidence_id=ev_1&anchor_id=a2`,
          block_id: null,
          snippet_id: null,
          figure_or_table: null,
          quote_span: 'Results section paragraph 4',
          anchor_type: 'text',
          label: 'Results section paragraph 4'
        }
      ],
      material_system: 'High-entropy oxide',
      condition_context: {
        process: ['900 C anneal', 'reduced oxygen partial pressure'],
        baseline: ['air annealed sample'],
        test: ['200 charge/discharge cycles']
      },
      confidence: 0.91,
      traceability_status: 'direct'
    },
    {
      evidence_id: 'ev_2',
      document_id: 'doc_c',
      collection_id: collectionId,
      claim_text: 'Carbon coating reduced impedance but baseline reporting is incomplete.',
      claim_type: 'property',
      evidence_source_type: 'table',
      evidence_anchors: [
        {
          anchor_id: 'a3',
          document_id: 'doc_c',
          locator_type: 'section',
          locator_confidence: 'low',
          source_type: 'table',
          section_id: 'results',
          char_range: null,
          bbox: null,
          page: null,
          quote: 'Table 2',
          deep_link: `/collections/${collectionId}/documents/doc_c?evidence_id=ev_2&anchor_id=a3`,
          block_id: null,
          snippet_id: null,
          figure_or_table: 'Table 2',
          quote_span: 'Table 2',
          anchor_type: 'table',
          label: 'Table 2'
        }
      ],
      material_system: 'Layered oxide',
      condition_context: {
        process: ['carbon coating'],
        baseline: ['uncoated reference mentioned'],
        test: ['EIS after 50 cycles']
      },
      confidence: 0.73,
      traceability_status: 'partial'
    }
  ];

  return {
    collection_id: collectionId,
    total: items.length,
    count: items.length,
    items
  };
}

function normalizeResponse(value: unknown, collectionId: string): EvidenceCardsResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Evidence cards response is invalid.');
  }

  const items = Array.isArray(record.items)
    ? record.items.map((item) => normalizeCard(item, collectionId)).filter((item): item is EvidenceCard => item !== null)
    : [];

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    total: typeof record.total === 'number' ? record.total : items.length,
    count: typeof record.count === 'number' ? record.count : items.length,
    items
  };
}

export async function fetchEvidenceCards(collectionId: string): Promise<EvidenceCardsResponse> {
  if (USE_API_FIXTURES) {
    return buildFixture(collectionId);
  }

  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/evidence/cards`, {
    method: 'GET'
  });
  return normalizeResponse(data, collectionId);
}

function normalizeTracebackResponse(
  value: unknown,
  collectionId: string,
  evidenceId: string
): EvidenceTracebackResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Evidence traceback response is invalid.');
  }

  const rawStatus = String(record.traceback_status ?? 'unavailable').trim() as TracebackStatus;
  const normalizedEvidenceId = String(record.evidence_id ?? evidenceId).trim() || evidenceId;
  const documentId = String(record.document_id ?? '').trim();
  const anchors = Array.isArray(record.anchors)
    ? record.anchors
        .map((item, index) => normalizeAnchor(item, collectionId, documentId, normalizedEvidenceId, index))
        .filter((item): item is EvidenceAnchor => item !== null)
    : [];

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    evidence_id: normalizedEvidenceId,
    traceback_status: ['ready', 'partial', 'unavailable'].includes(rawStatus)
      ? rawStatus
      : 'unavailable',
    anchors
  };
}

export async function fetchEvidenceTraceback(
  collectionId: string,
  evidenceId: string
): Promise<EvidenceTracebackResponse> {
  if (USE_API_FIXTURES) {
    return {
      collection_id: collectionId,
      evidence_id: evidenceId,
      traceback_status: evidenceId === 'ev_2' ? 'partial' : 'ready',
      anchors:
        evidenceId === 'ev_2'
          ? normalizeAnchors(
              [
                {
                  anchor_id: 'a3',
                  document_id: 'doc_c',
                  locator_type: 'section',
                  locator_confidence: 'low',
                  source_type: 'table',
                  section_id: 'results',
                  quote: 'Table 2'
                }
              ],
              collectionId,
              'doc_c',
              evidenceId
            )
          : normalizeAnchors(
              [
                {
                  anchor_id: 'a2',
                  document_id: 'doc_a',
                  locator_type: 'char_range',
                  locator_confidence: 'medium',
                  source_type: 'text',
                  section_id: 'results',
                  char_range: { start: 120, end: 188 },
                  quote: 'Results section paragraph 4'
                }
              ],
              collectionId,
              'doc_a',
              evidenceId
            )
    };
  }

  const data = await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/evidence/${encodeURIComponent(evidenceId)}/traceback`,
    {
      method: 'GET'
    }
  );
  return normalizeTracebackResponse(data, collectionId, evidenceId);
}
