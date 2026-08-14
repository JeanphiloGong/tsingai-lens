import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type TracebackStatus = 'ready' | 'partial' | 'unavailable';

export type TracebackAnchor = {
	anchor_id: string;
	document_id: string;
	source_kind: string;
	source_ref: string;
	source_type: string;
	page: number | null;
	quote: string | null;
	deep_link: string | null;
};

export type EvidenceTracebackResponse = {
	collection_id: string;
	evidence_id: string;
	traceback_status: TracebackStatus;
	anchors: TracebackAnchor[];
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

	const document_id = String(record.document_id ?? fallbackDocumentId).trim() || fallbackDocumentId;
	const source_kind = String(record.source_kind ?? '').trim();
	const source_ref = String(record.source_ref ?? '').trim();
	if (!source_kind || !source_ref) return null;

	return {
		anchor_id,
		document_id,
		source_kind,
		source_ref,
		source_type: String(record.source_type ?? 'text').trim() || 'text',
		page: toOptionalNumber(record.page),
		quote: toOptionalText(record.quote),
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
					source_kind: 'block',
					source_ref: 'results',
					source_type: 'text',
					page: 4,
					quote:
						'Annealing at lower oxygen partial pressure improved cycle retention by stabilizing the structure.',
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
					source_kind: 'block',
					source_ref: 'discussion',
					source_type: 'text',
					page: null,
					quote:
						'Carbon coating reduced impedance, but the baseline reference was only partially specified.',
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
