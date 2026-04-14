import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type LocatorType = 'char_range' | 'bbox' | 'section';
export type LocatorConfidence = 'high' | 'medium' | 'low';
export type TracebackStatus = 'ready' | 'partial' | 'unavailable';

export type TracebackCharRange = {
  start: number;
  end: number;
};

export type TracebackBoundingBox = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type TracebackAnchor = {
  anchor_id: string;
  document_id: string;
  locator_type: LocatorType;
  locator_confidence: LocatorConfidence;
  page: number | null;
  quote: string | null;
  section_id: string | null;
  char_range: TracebackCharRange | null;
  bbox: TracebackBoundingBox | null;
  deep_link: string | null;
};

export type EvidenceTracebackResponse = {
  collection_id: string;
  evidence_id: string;
  traceback_status: TracebackStatus;
  anchors: TracebackAnchor[];
};

export type DocumentContentSection = {
  section_id: string;
  title: string | null;
  section_type: string | null;
  text: string;
  page: number | null;
  order: number | null;
  start_offset: number | null;
  end_offset: number | null;
  text_unit_ids: string[];
};

export type DocumentContentResponse = {
  collection_id: string;
  document_id: string;
  title: string | null;
  source_filename: string | null;
  page_count: number | null;
  content_text: string;
  sections: DocumentContentSection[];
  warnings: string[];
};

type BuildViewerHrefOptions = {
  evidenceId?: string | null;
  anchorId?: string | null;
  returnTo?: string | null;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function toOptionalText(value: unknown) {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? text : null;
}

function toOptionalNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function normalizeLocatorType(value: unknown, anchor: Record<string, unknown>): LocatorType {
  const locatorType = String(value ?? '').trim();
  if (locatorType === 'char_range' || locatorType === 'bbox' || locatorType === 'section') {
    return locatorType;
  }
  if (asRecord(anchor.char_range)) return 'char_range';
  if (asRecord(anchor.bbox)) return 'bbox';
  return 'section';
}

function normalizeLocatorConfidence(value: unknown, locatorType: LocatorType): LocatorConfidence {
  const confidence = String(value ?? '').trim();
  if (confidence === 'high' || confidence === 'medium' || confidence === 'low') {
    return confidence;
  }
  if (locatorType === 'char_range') return 'high';
  if (locatorType === 'bbox') return 'medium';
  return 'low';
}

function normalizeCharRange(value: unknown): TracebackCharRange | null {
  const record = asRecord(value);
  if (!record) return null;

  const start = toOptionalNumber(record.start ?? record.offset_start ?? record.span_start);
  const end = toOptionalNumber(record.end ?? record.offset_end ?? record.span_end);
  if (start === null || end === null) return null;

  return {
    start,
    end
  };
}

function normalizeBoundingBox(value: unknown): TracebackBoundingBox | null {
  const record = asRecord(value);
  if (!record) return null;

  const x0 = toOptionalNumber(record.x0 ?? record.x ?? record.left);
  const y0 = toOptionalNumber(record.y0 ?? record.y ?? record.top);
  const x1 =
    toOptionalNumber(record.x1) ??
    (() => {
      const width = toOptionalNumber(record.width ?? record.w);
      return x0 !== null && width !== null ? x0 + width : null;
    })();
  const y1 =
    toOptionalNumber(record.y1) ??
    (() => {
      const height = toOptionalNumber(record.height ?? record.h);
      return y0 !== null && height !== null ? y0 + height : null;
    })();
  if (x0 === null || y0 === null || x1 === null || y1 === null) return null;

  return {
    x0,
    y0,
    x1,
    y1
  };
}

function normalizeAnchor(
  value: unknown,
  collectionId: string,
  evidenceId: string,
  fallbackDocumentId: string
): TracebackAnchor | null {
  const record = asRecord(value);
  if (!record) return null;

  const anchor_id = String(record.anchor_id ?? record.id ?? '').trim();
  if (!anchor_id) return null;

  const locator_type = normalizeLocatorType(record.locator_type, record);
  const locator_confidence = normalizeLocatorConfidence(record.locator_confidence, locator_type);
  const document_id = String(record.document_id ?? fallbackDocumentId).trim() || fallbackDocumentId;

  return {
    anchor_id,
    document_id,
    locator_type,
    locator_confidence,
    page: toOptionalNumber(record.page),
    quote: toOptionalText(record.quote ?? record.quote_span ?? record.label),
    section_id: toOptionalText(record.section_id),
    char_range: normalizeCharRange(record.char_range),
    bbox: normalizeBoundingBox(record.bbox),
    deep_link:
      toOptionalText(record.deep_link) ??
      buildDocumentViewerHref(collectionId, document_id, {
        evidenceId,
        anchorId: anchor_id
      })
  };
}

function normalizeTracebackResponse(
  value: unknown,
  collectionId: string,
  evidenceId: string
): EvidenceTracebackResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Traceback response is invalid.');
  }

  const anchors = Array.isArray(record.anchors)
    ? record.anchors
        .map((item) => normalizeAnchor(item, collectionId, evidenceId, ''))
        .filter((item): item is TracebackAnchor => item !== null)
    : [];

  const tracebackStatus = String(record.traceback_status ?? '').trim();

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    evidence_id: String(record.evidence_id ?? evidenceId).trim() || evidenceId,
    traceback_status: ['ready', 'partial', 'unavailable'].includes(tracebackStatus)
      ? (tracebackStatus as TracebackStatus)
      : anchors.length
        ? 'ready'
        : 'unavailable',
    anchors
  };
}

function normalizeSection(value: unknown, index: number): DocumentContentSection | null {
  const record = asRecord(value);
  if (!record) return null;

  const text = String(record.text ?? record.content ?? '').trim();
  const section_id = String(record.section_id ?? record.id ?? `section_${index + 1}`).trim();
  if (!text || !section_id) return null;

  return {
    section_id,
    title: toOptionalText(record.title ?? record.heading ?? record.name),
    section_type: toOptionalText(record.section_type ?? record.type),
    text,
    page: toOptionalNumber(record.page ?? record.page_start),
    order: toOptionalNumber(record.order),
    start_offset: toOptionalNumber(record.start_offset),
    end_offset: toOptionalNumber(record.end_offset),
    text_unit_ids: Array.isArray(record.text_unit_ids)
      ? record.text_unit_ids.map((item) => String(item ?? '').trim()).filter((item) => item !== '')
      : []
  };
}

function normalizeDocumentContent(
  value: unknown,
  collectionId: string,
  documentId: string
): DocumentContentResponse {
  const record = asRecord(value);
  if (!record) {
    throw new Error('Document content response is invalid.');
  }

  const rawSections = Array.isArray(record.sections)
    ? record.sections
    : Array.isArray(record.items)
      ? record.items
      : [];

  const sections = rawSections
    .map((item, index) => normalizeSection(item, index))
    .filter((item): item is DocumentContentSection => item !== null);

  return {
    collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
    document_id: String(record.document_id ?? documentId).trim() || documentId,
    title: toOptionalText(record.title ?? record.document_title),
    source_filename:
      toOptionalText(record.source_filename) ??
      toOptionalText(record.original_filename) ??
      toOptionalText(record.source_file_name),
    page_count: toOptionalNumber(record.page_count),
    content_text: String(record.content_text ?? '').trim(),
    sections,
    warnings: Array.isArray(record.warnings)
      ? record.warnings.map((item) => String(item ?? '').trim()).filter((item) => item !== '')
      : []
  };
}

function fixtureTraceback(collectionId: string, evidenceId: string): EvidenceTracebackResponse {
  const fixtures: Record<string, EvidenceTracebackResponse> = {
    ev_1: {
      collection_id: collectionId,
      evidence_id: evidenceId,
      traceback_status: 'ready',
      anchors: [
        {
          anchor_id: 'anc_ev_1',
          document_id: 'doc_a',
          locator_type: 'char_range',
          locator_confidence: 'high',
          page: 4,
          quote: 'Annealing at lower oxygen partial pressure improved cycle retention by stabilizing the structure.',
          section_id: 'results',
          char_range: { start: 214, end: 324 },
          bbox: null,
          deep_link: buildDocumentViewerHref(collectionId, 'doc_a', {
            evidenceId,
            anchorId: 'anc_ev_1'
          })
        }
      ]
    },
    ev_2: {
      collection_id: collectionId,
      evidence_id: evidenceId,
      traceback_status: 'partial',
      anchors: [
        {
          anchor_id: 'anc_ev_2',
          document_id: 'doc_c',
          locator_type: 'section',
          locator_confidence: 'low',
          page: null,
          quote: 'Carbon coating reduced impedance, but the baseline reference was only partially specified.',
          section_id: 'discussion',
          char_range: null,
          bbox: null,
          deep_link: buildDocumentViewerHref(collectionId, 'doc_c', {
            evidenceId,
            anchorId: 'anc_ev_2'
          })
        }
      ]
    }
  };

  return (
    fixtures[evidenceId] ?? {
      collection_id: collectionId,
      evidence_id: evidenceId,
      traceback_status: 'unavailable',
      anchors: []
    }
  );
}

function fixtureDocumentContent(collectionId: string, documentId: string): DocumentContentResponse {
  const fixtures: Record<string, DocumentContentResponse> = {
    doc_a: {
      collection_id: collectionId,
      document_id: 'doc_a',
      title: 'High-entropy oxide cycling study',
      source_filename: 'high-entropy-oxide-cycling-study.pdf',
      page_count: 8,
      content_text:
        'This study examines high-entropy oxide cathodes and the relationship between annealing atmosphere and cycle performance.\nPowders were mixed, dried, and annealed under controlled oxygen partial pressure before electrochemical evaluation.\nAnnealing at lower oxygen partial pressure improved cycle retention by stabilizing the structure. The treated sample retained more capacity after extended cycling than the air-annealed baseline.',
      sections: [
        {
          section_id: 'intro',
          title: 'Introduction',
          section_type: 'background',
          page: 1,
          text: 'This study examines high-entropy oxide cathodes and the relationship between annealing atmosphere and cycle performance.',
          order: 1,
          start_offset: 0,
          end_offset: 114,
          text_unit_ids: []
        },
        {
          section_id: 'methods',
          title: 'Methods',
          section_type: 'methods',
          page: 2,
          text: 'Powders were mixed, dried, and annealed under controlled oxygen partial pressure before electrochemical evaluation.',
          order: 2,
          start_offset: 115,
          end_offset: 223,
          text_unit_ids: []
        },
        {
          section_id: 'results',
          title: 'Results',
          section_type: 'results',
          page: 4,
          text: 'Annealing at lower oxygen partial pressure improved cycle retention by stabilizing the structure. The treated sample retained more capacity after extended cycling than the air-annealed baseline.',
          order: 3,
          start_offset: 224,
          end_offset: 421,
          text_unit_ids: []
        }
      ],
      warnings: []
    },
    doc_c: {
      collection_id: collectionId,
      document_id: 'doc_c',
      title: 'Mixed experimental survey benchmark',
      source_filename: 'mixed-experimental-survey-benchmark.txt',
      page_count: null,
      content_text:
        'This mixed document contains both survey-style framing and experimental observations about coating strategies.\nCarbon coating reduced impedance, but the baseline reference was only partially specified. Additional controls would be required for a stronger cross-paper comparison.',
      sections: [
        {
          section_id: 'overview',
          title: 'Overview',
          section_type: 'background',
          page: null,
          text: 'This mixed document contains both survey-style framing and experimental observations about coating strategies.',
          order: 1,
          start_offset: 0,
          end_offset: 101,
          text_unit_ids: []
        },
        {
          section_id: 'discussion',
          title: 'Discussion',
          section_type: 'discussion',
          page: null,
          text: 'Carbon coating reduced impedance, but the baseline reference was only partially specified. Additional controls would be required for a stronger cross-paper comparison.',
          order: 2,
          start_offset: 102,
          end_offset: 267,
          text_unit_ids: []
        }
      ],
      warnings: []
    }
  };

  return (
    fixtures[documentId] ?? {
      collection_id: collectionId,
      document_id: documentId,
      title: null,
      source_filename: null,
      page_count: null,
      content_text: '',
      sections: [],
      warnings: []
    }
  );
}

export function buildDocumentViewerHref(
  collectionId: string,
  documentId: string,
  options: BuildViewerHrefOptions = {}
) {
  const params = new URLSearchParams();

  if (options.evidenceId) params.set('evidence_id', options.evidenceId);
  if (options.anchorId) params.set('anchor_id', options.anchorId);
  if (options.returnTo) params.set('return_to', options.returnTo);

  const query = params.toString();
  const path = `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}`;
  return query ? `${path}?${query}` : path;
}

export async function fetchEvidenceTraceback(
  collectionId: string,
  evidenceId: string
): Promise<EvidenceTracebackResponse> {
  if (USE_API_FIXTURES) {
    return fixtureTraceback(collectionId, evidenceId);
  }

  const data = await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/evidence/${encodeURIComponent(evidenceId)}/traceback`,
    {
      method: 'GET'
    }
  );

  return normalizeTracebackResponse(data, collectionId, evidenceId);
}

export async function fetchDocumentContent(
  collectionId: string,
  documentId: string
): Promise<DocumentContentResponse> {
  if (USE_API_FIXTURES) {
    return fixtureDocumentContent(collectionId, documentId);
  }

  const data = await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/content`,
    {
      method: 'GET'
    }
  );

  return normalizeDocumentContent(data, collectionId, documentId);
}
