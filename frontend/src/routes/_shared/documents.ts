import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type DocumentType = 'experimental' | 'review' | 'mixed' | 'uncertain';
export type ProtocolExtractable = 'yes' | 'partial' | 'no' | 'uncertain';

export type DocumentProfile = {
  document_id: string;
  collection_id: string;
  title: string | null;
  source_filename: string | null;
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

export type DocumentContentSection = {
  section_id: string;
  heading: string | null;
  section_type: string | null;
  order: number;
  text: string;
  text_unit_ids: string[];
  start_offset: number | null;
  end_offset: number | null;
};

export type DocumentContentResponse = {
  collection_id: string;
  document_id: string;
  title: string | null;
  source_filename: string | null;
  content_text: string;
  sections: DocumentContentSection[];
  warnings: string[];
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

function toOptionalText(value: unknown) {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? text : null;
}

function normalizeContentSection(value: unknown): DocumentContentSection | null {
  const record = asRecord(value);
  if (!record) return null;

  const section_id = String(record.section_id ?? '').trim();
  if (!section_id) return null;

  const startOffset = toNumber(record.start_offset);
  const endOffset = toNumber(record.end_offset);

  return {
    section_id,
    heading: toOptionalText(record.heading),
    section_type: toOptionalText(record.section_type),
    order: Number.isFinite(toNumber(record.order)) ? toNumber(record.order) : 0,
    text: String(record.text ?? '').trim(),
    text_unit_ids: toStringList(record.text_unit_ids),
    start_offset: Number.isFinite(startOffset) ? startOffset : null,
    end_offset: Number.isFinite(endOffset) ? endOffset : null
  };
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
    title: toOptionalText(record.title) ?? toOptionalText(record.document_title),
    source_filename:
      toOptionalText(record.source_filename) ??
      toOptionalText(record.original_filename) ??
      toOptionalText(record.source_file_name),
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
      source_filename: 'high-entropy-oxide-cycling-study.pdf',
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
      source_filename: 'interface-engineering-review.pdf',
      doc_type: 'review',
      protocol_extractable: 'no',
      protocol_extractability_signals: ['review contamination'],
      parsing_warnings: ['Weak procedural continuity'],
      confidence: 0.93
    },
    {
      document_id: 'doc_c',
      collection_id: collectionId,
      title: null,
      source_filename: 'mixed-experimental-survey-benchmark.txt',
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

function normalizeDocumentContent(value: unknown, collectionId: string, documentId: string): DocumentContentResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Document content response is invalid.');
  }

  const sections = Array.isArray(record.sections)
    ? record.sections
        .map((item) => normalizeContentSection(item))
        .filter((item): item is DocumentContentSection => item !== null)
    : [];

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    document_id: String(record.document_id ?? documentId).trim() || documentId,
    title: toOptionalText(record.title),
    source_filename: toOptionalText(record.source_filename),
    content_text: String(record.content_text ?? '').trim(),
    sections,
    warnings: toStringList(record.warnings)
  };
}

export async function fetchDocumentContent(
  collectionId: string,
  documentId: string
): Promise<DocumentContentResponse> {
  if (USE_API_FIXTURES) {
    return {
      collection_id: collectionId,
      document_id: documentId,
      title: 'Fixture document viewer',
      source_filename: 'fixture-paper.txt',
      content_text:
        'Experimental Section\nThe precursor powders were mixed in ethanol and stirred for 2 h.\nCharacterization\nXRD and SEM were used to characterize the powders.',
      sections: [
        {
          section_id: 'methods',
          heading: 'Experimental Section',
          section_type: 'methods',
          order: 1,
          text: 'The precursor powders were mixed in ethanol and stirred for 2 h.',
          text_unit_ids: ['tu-1'],
          start_offset: 21,
          end_offset: 84
        },
        {
          section_id: 'characterization',
          heading: 'Characterization',
          section_type: 'characterization',
          order: 2,
          text: 'XRD and SEM were used to characterize the powders.',
          text_unit_ids: ['tu-2'],
          start_offset: 102,
          end_offset: 153
        }
      ],
      warnings: []
    };
  }

  const data = await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/content`,
    {
      method: 'GET'
    }
  );
  return normalizeDocumentContent(data, collectionId, documentId);
}
