import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type DocumentType = 'experimental' | 'review' | 'mixed' | 'uncertain';
export type ProtocolExtractable = 'yes' | 'partial' | 'no' | 'uncertain';

export type DocumentProfile = {
  document_id: string;
  collection_id: string;
  title: string | null;
  doc_type: DocumentType;
  protocol_extractable: ProtocolExtractable;
  protocol_extractability_signals: string[];
  parsing_warnings: string[];
  confidence: number | null;
};

export type DocumentProfilesResponse = {
  collection_id: string;
  total: number;
  count: number;
  summary: {
    total_documents: number;
    doc_type_counts: Record<DocumentType, number>;
    protocol_extractable_counts: Record<ProtocolExtractable, number>;
    warnings: string[];
  };
  items: DocumentProfile[];
};

const DEFAULT_DOC_TYPE_COUNTS: Record<DocumentType, number> = {
  experimental: 0,
  review: 0,
  mixed: 0,
  uncertain: 0
};

const DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS: Record<ProtocolExtractable, number> = {
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

function normalizeProfile(value: unknown, collectionId: string): DocumentProfile | null {
  const record = asRecord(value);
  if (!record) return null;

  const document_id = String(record.document_id ?? record.id ?? '').trim();
  if (!document_id) return null;

  const doc_type = String(record.doc_type ?? 'uncertain').trim() as DocumentType;
  const protocol_extractable = String(record.protocol_extractable ?? 'uncertain').trim() as ProtocolExtractable;
  const confidence = toNumber(record.confidence);

  return {
    document_id,
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    title:
      typeof record.title === 'string'
        ? record.title
        : typeof record.document_title === 'string'
          ? record.document_title
          : null,
    doc_type: ['experimental', 'review', 'mixed', 'uncertain'].includes(doc_type) ? doc_type : 'uncertain',
    protocol_extractable: ['yes', 'partial', 'no', 'uncertain'].includes(protocol_extractable)
      ? protocol_extractable
      : 'uncertain',
    protocol_extractability_signals: toStringList(record.protocol_extractability_signals),
    parsing_warnings: toStringList(record.parsing_warnings),
    confidence: Number.isFinite(confidence) ? confidence : null
  };
}

function buildFixture(collectionId: string): DocumentProfilesResponse {
  const items: DocumentProfile[] = [
    {
      document_id: 'doc_a',
      collection_id: collectionId,
      title: 'High-entropy oxide cycling study',
      doc_type: 'experimental',
      protocol_extractable: 'partial',
      protocol_extractability_signals: ['methods density', 'condition completeness'],
      parsing_warnings: [],
      confidence: 0.88
    },
    {
      document_id: 'doc_b',
      collection_id: collectionId,
      title: 'Review of interface engineering strategies',
      doc_type: 'review',
      protocol_extractable: 'no',
      protocol_extractability_signals: ['review contamination'],
      parsing_warnings: ['Weak procedural continuity'],
      confidence: 0.93
    },
    {
      document_id: 'doc_c',
      collection_id: collectionId,
      title: 'Mixed experimental and survey benchmark',
      doc_type: 'mixed',
      protocol_extractable: 'uncertain',
      protocol_extractability_signals: ['critical parameter missingness'],
      parsing_warnings: ['Baseline definition varies across sections'],
      confidence: 0.64
    }
  ];

  return {
    collection_id: collectionId,
    total: items.length,
    count: items.length,
    summary: {
      total_documents: items.length,
      doc_type_counts: {
        experimental: 1,
        review: 1,
        mixed: 1,
        uncertain: 0
      },
      protocol_extractable_counts: {
        yes: 0,
        partial: 1,
        no: 1,
        uncertain: 1
      },
      warnings: ['Fixture mode is enabled for document profiles.']
    },
    items
  };
}

function normalizeResponse(value: unknown, collectionId: string): DocumentProfilesResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Document profiles response is invalid.');
  }

  const items = Array.isArray(record.items)
    ? record.items.map((item) => normalizeProfile(item, collectionId)).filter((item): item is DocumentProfile => item !== null)
    : [];

  const summaryRecord = asRecord(record.summary);

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    total: typeof record.total === 'number' ? record.total : items.length,
    count: typeof record.count === 'number' ? record.count : items.length,
    summary: {
      total_documents:
        typeof summaryRecord?.total_documents === 'number'
          ? summaryRecord.total_documents
          : typeof record.total === 'number'
            ? record.total
            : items.length,
      doc_type_counts: {
        ...DEFAULT_DOC_TYPE_COUNTS,
        ...((summaryRecord?.doc_type_counts ?? summaryRecord?.by_doc_type) as
          | Record<DocumentType, number>
          | undefined)
      },
      protocol_extractable_counts: {
        ...DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS,
        ...((summaryRecord?.protocol_extractable_counts ?? summaryRecord?.by_protocol_extractable) as
          | Record<ProtocolExtractable, number>
          | undefined)
      },
      warnings: toStringList(summaryRecord?.warnings)
    },
    items
  };
}

export async function fetchDocumentProfiles(collectionId: string): Promise<DocumentProfilesResponse> {
  if (USE_API_FIXTURES) {
    return buildFixture(collectionId);
  }

  const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/documents/profiles`, {
    method: 'GET'
  });
  return normalizeResponse(data, collectionId);
}
