import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type EvidenceSourceType = 'figure' | 'table' | 'method' | 'text';
export type TraceabilityStatus = 'direct' | 'partial' | 'missing';

export type EvidenceAnchor = {
  anchor_id: string;
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

function normalizeAnchors(value: unknown): EvidenceAnchor[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item, index) => {
      const record = asRecord(item);
      if (!record) {
        const label = String(item ?? '').trim();
        return label
          ? {
              anchor_id: `anchor_${index + 1}`,
              anchor_type: 'text',
              label
            }
          : null;
      }

      const label = String(record.label ?? record.value ?? record.anchor ?? '').trim();
      if (!label) return null;

      return {
        anchor_id: String(record.anchor_id ?? record.id ?? `anchor_${index + 1}`),
        anchor_type: String(record.anchor_type ?? record.type ?? 'text'),
        label
      };
    })
    .filter((item): item is EvidenceAnchor => item !== null);
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
    process: toStringList(record.process),
    baseline: toStringList(record.baseline),
    test: toStringList(record.test)
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
    evidence_anchors: normalizeAnchors(record.evidence_anchors),
    material_system: String(record.material_system ?? '--').trim() || '--',
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
        { anchor_id: 'a1', anchor_type: 'figure', label: 'Figure 3b' },
        { anchor_id: 'a2', anchor_type: 'text', label: 'Results section paragraph 4' }
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
      evidence_anchors: [{ anchor_id: 'a3', anchor_type: 'table', label: 'Table 2' }],
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
