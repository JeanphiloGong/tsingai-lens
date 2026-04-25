import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type EvidenceSourceType = 'figure' | 'table' | 'method' | 'text' | 'abstract';
export type TraceabilityStatus = 'direct' | 'partial' | 'missing' | 'indirect' | 'none';
export type LocatorType = 'char_range' | 'bbox' | 'section';
export type LocatorConfidence = 'high' | 'medium' | 'low';
export type TracebackStatus = 'ready' | 'partial' | 'unavailable';
export type EvidenceTypeFilter =
	| ''
	| 'process'
	| 'method'
	| 'material'
	| 'property'
	| 'result'
	| 'condition'
	| 'other';
export type EvidenceTraceabilityFilter = '' | 'direct' | 'indirect' | 'none';
export type EvidenceSourceFilter = '' | EvidenceSourceType;
export type EvidenceConfidenceLevel = 'high' | 'medium' | 'low' | 'unknown';
export type EvidenceConfidenceFilter = '' | 'high' | 'medium' | 'low';
export type EvidenceComparabilityStatus =
	| 'joinable'
	| 'needs_context'
	| 'not_recommended'
	| 'added';
export type EvidenceComparabilityFilter = '' | EvidenceComparabilityStatus;
export type EvidenceSortMode = 'confidence_desc' | 'confidence_asc' | 'recent' | 'document';
export type EvidenceActionKey =
	| 'view_source'
	| 'add_to_comparison'
	| 'view_comparison'
	| 'mark_issue'
	| 'mark_trusted'
	| 'view_reason';
export type EvidenceTone = 'brand' | 'success' | 'warning' | 'danger' | 'neutral' | 'purple';

export type EvidenceFilters = {
	search: string;
	type: EvidenceTypeFilter;
	traceability: EvidenceTraceabilityFilter;
	source: EvidenceSourceFilter;
	confidence: EvidenceConfidenceFilter;
	comparability: EvidenceComparabilityFilter;
};

export type EvidenceBadge = {
	label: string;
	labelKey?: string;
	tone: EvidenceTone;
	icon: string;
};

export type EvidenceQualitySummaryItem = {
	key: 'total' | 'traceable' | 'needs_review' | 'comparable' | 'unusable';
	labelKey: string;
	value: number;
	percent: number | null;
	tone: EvidenceTone;
	icon: string;
};

export type EvidenceAction = {
	key: EvidenceActionKey;
	labelKey: string;
	tone: 'primary' | 'ghost';
};

export type EvidenceQuote = {
	text: string;
	citation: string;
};

export type EvidenceSourceLocation = {
	documentLabel: string;
	sourceType: EvidenceSourceType;
	location: string;
	materials: string[];
	parameters: string[];
	tags: string[];
};

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
	source_document_title: string | null;
	materials: string[];
	parameters: string[];
	tags: string[];
	comparable: boolean | null;
	comparison_status: EvidenceComparabilityStatus | null;
	review_status: string | null;
	extracted_at: string | null;
	updated_at: string | null;
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

function toOptionalBoolean(value: unknown): boolean | null {
	if (typeof value === 'boolean') return value;
	if (typeof value === 'string') {
		const normalized = value.trim().toLowerCase();
		if (['true', 'yes', '1', 'comparable'].includes(normalized)) return true;
		if (['false', 'no', '0', 'not_comparable', 'not-comparable'].includes(normalized)) return false;
	}
	return null;
}

function normalizeEvidenceSourceType(value: unknown): EvidenceSourceType {
	const sourceType = String(value ?? 'text')
		.trim()
		.toLowerCase();
	return ['figure', 'table', 'method', 'text', 'abstract'].includes(sourceType)
		? (sourceType as EvidenceSourceType)
		: 'text';
}

function normalizeTraceabilityStatus(value: unknown): TraceabilityStatus {
	const traceability = String(value ?? 'missing')
		.trim()
		.toLowerCase();
	if (traceability === 'direct') return 'direct';
	if (traceability === 'partial' || traceability === 'indirect')
		return traceability as TraceabilityStatus;
	if (traceability === 'missing' || traceability === 'none' || traceability === 'unavailable') {
		return traceability === 'none' ? 'none' : 'missing';
	}
	return 'missing';
}

function normalizeComparisonStatus(value: unknown): EvidenceComparabilityStatus | null {
	const status = String(value ?? '')
		.trim()
		.toLowerCase();
	if (!status) return null;
	if (['added', 'joined', 'in_comparison', 'in-comparison'].includes(status)) return 'added';
	if (['joinable', 'comparable', 'can_compare', 'can-compare'].includes(status)) return 'joinable';
	if (['needs_context', 'limited', 'needs_conditions', 'needs-condition'].includes(status)) {
		return 'needs_context';
	}
	if (['not_recommended', 'not_comparable', 'review_only', 'unusable'].includes(status)) {
		return 'not_recommended';
	}
	return null;
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
					deep_link: buildTracebackLink(
						collectionId,
						documentId,
						evidenceId,
						`anchor_${index + 1}`
					),
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
	const source_type = normalizeEvidenceSourceType(
		record.source_type ?? record.anchor_type ?? record.type
	);
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
		source_type,
		section_id: toOptionalText(record.section_id),
		char_range,
		bbox,
		page: Number.isFinite(toNumber(record.page)) ? toNumber(record.page) : null,
		quote,
		deep_link:
			toOptionalText(record.deep_link) ??
			buildTracebackLink(collectionId, anchorDocumentId, evidenceId, anchor_id),
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
	const evidence_source_type = normalizeEvidenceSourceType(
		record.evidence_source_type ?? record.source_type ?? record.anchor_type
	);
	const traceability_status = normalizeTraceabilityStatus(record.traceability_status);

	return {
		evidence_id,
		document_id: String(record.document_id ?? '').trim(),
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		claim_text: String(record.claim_text ?? '').trim(),
		claim_type: String(record.claim_type ?? 'claim').trim(),
		evidence_source_type,
		evidence_anchors: normalizeAnchors(
			record.evidence_anchors,
			collectionId,
			String(record.document_id ?? '').trim(),
			evidence_id
		),
		material_system: normalizeMaterialSystem(record.material_system),
		condition_context: normalizeConditionContext(record.condition_context),
		confidence: Number.isFinite(confidence) ? confidence : null,
		traceability_status,
		source_document_title:
			toOptionalText(record.source_document_title) ??
			toOptionalText(record.document_title) ??
			toOptionalText(record.source_title) ??
			toOptionalText(record.source_document) ??
			toOptionalText(record.source_filename),
		materials: toStringList(record.materials ?? record.material_entities),
		parameters: toStringList(record.parameters ?? record.parameter_entities ?? record.properties),
		tags: toStringList(record.tags ?? record.keywords),
		comparable: toOptionalBoolean(record.comparable ?? record.can_compare),
		comparison_status: normalizeComparisonStatus(
			record.comparison_status ?? record.comparability_status
		),
		review_status: toOptionalText(record.review_status ?? record.status),
		extracted_at: toOptionalText(record.extracted_at ?? record.created_at),
		updated_at: toOptionalText(record.updated_at)
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
			traceability_status: 'direct',
			source_document_title: 'AI alloys',
			materials: ['High-entropy oxide'],
			parameters: ['cycle retention', 'oxygen partial pressure', 'annealing'],
			tags: ['cycle retention', 'anneal'],
			comparable: true,
			comparison_status: null,
			review_status: null,
			extracted_at: '2026-04-25T04:38:00.000Z',
			updated_at: '2026-04-25T04:41:00.000Z'
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
			traceability_status: 'partial',
			source_document_title: 'Layered oxide impedance study',
			materials: ['Layered oxide'],
			parameters: ['impedance', 'carbon coating', 'EIS'],
			tags: ['impedance', 'coating'],
			comparable: true,
			comparison_status: 'needs_context',
			review_status: null,
			extracted_at: '2026-04-25T04:34:00.000Z',
			updated_at: '2026-04-25T04:40:00.000Z'
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
		? record.items
				.map((item) => normalizeCard(item, collectionId))
				.filter((item): item is EvidenceCard => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		total: typeof record.total === 'number' ? record.total : items.length,
		count: typeof record.count === 'number' ? record.count : items.length,
		items
	};
}

function clampPercent(value: number) {
	return Math.max(0, Math.min(100, Math.round(value)));
}

function percentOf(count: number, total: number) {
	if (total < 1) return null;
	return clampPercent((count / total) * 100);
}

function normalizedConfidence(confidence?: number | null) {
	if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return null;
	if (confidence <= 1) return Math.max(0, confidence);
	return Math.max(0, Math.min(1, confidence / 100));
}

function normalizedTraceabilityValue(
	traceability?: string | null
): Exclude<EvidenceTraceabilityFilter, ''> {
	const normalized = normalizeTraceabilityStatus(traceability);
	if (normalized === 'direct') return 'direct';
	if (normalized === 'partial' || normalized === 'indirect') return 'indirect';
	return 'none';
}

function normalizedEvidenceType(type?: string | null): Exclude<EvidenceTypeFilter, ''> {
	const normalized = String(type ?? '')
		.trim()
		.toLowerCase();
	if (['process', 'method', 'material', 'property', 'result', 'condition'].includes(normalized)) {
		return normalized as Exclude<EvidenceTypeFilter, ''>;
	}
	return 'other';
}

function usefulText(value?: string | null) {
	const text = typeof value === 'string' ? value.trim() : '';
	return text && text !== '--' ? text : '';
}

function uniqueNonEmpty(values: string[]) {
	return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function hasSource(evidence: EvidenceCard) {
	return Boolean(evidence.document_id || evidence.evidence_anchors.length);
}

function dateValue(value?: string | null) {
	if (!value) return 0;
	const parsed = new Date(value).getTime();
	return Number.isFinite(parsed) ? parsed : 0;
}

export function getConfidenceLevel(confidence?: number | null): EvidenceConfidenceLevel {
	const normalized = normalizedConfidence(confidence);
	if (normalized === null) return 'unknown';
	if (normalized >= 0.85) return 'high';
	if (normalized >= 0.65) return 'medium';
	return 'low';
}

export function formatConfidence(confidence?: number | null) {
	const normalized = normalizedConfidence(confidence);
	if (normalized === null) return '--';
	return `${clampPercent(normalized * 100)}%`;
}

export function getEvidenceTypeBadge(type?: string | null): EvidenceBadge {
	const normalized = normalizedEvidenceType(type);
	const badges: Record<Exclude<EvidenceTypeFilter, ''>, EvidenceBadge> = {
		process: { label: 'Process', tone: 'brand', icon: 'P' },
		method: { label: 'Method', tone: 'purple', icon: 'M' },
		material: { label: 'Material', tone: 'success', icon: 'M' },
		property: { label: 'Property', tone: 'neutral', icon: 'P' },
		result: { label: 'Result', tone: 'warning', icon: 'R' },
		condition: { label: 'Condition', tone: 'neutral', icon: 'C' },
		other: { label: 'Other', tone: 'neutral', icon: 'O' }
	};
	return badges[normalized];
}

export function getTraceabilityBadge(traceability?: string | null): EvidenceBadge {
	const normalized = normalizedTraceabilityValue(traceability);
	if (normalized === 'direct') {
		return {
			label: 'Directly traceable',
			labelKey: 'evidence.traceability.direct',
			tone: 'success',
			icon: 'OK'
		};
	}
	if (normalized === 'indirect') {
		return {
			label: 'Indirectly traceable',
			labelKey: 'evidence.traceability.indirect',
			tone: 'warning',
			icon: '~'
		};
	}
	return {
		label: 'Not traceable',
		labelKey: 'evidence.traceability.none',
		tone: 'danger',
		icon: '!'
	};
}

export function getComparabilityStatus(evidence: EvidenceCard): EvidenceComparabilityStatus {
	if (evidence.comparison_status) return evidence.comparison_status;

	const reviewStatus = evidence.review_status?.toLowerCase() ?? '';
	if (reviewStatus === 'review_only' || reviewStatus === 'unusable') return 'not_recommended';
	if (!hasSource(evidence)) return 'not_recommended';
	if (normalizedTraceabilityValue(evidence.traceability_status) === 'none')
		return 'not_recommended';
	if (getConfidenceLevel(evidence.confidence) === 'low') return 'not_recommended';
	if (evidence.comparable === false) return 'not_recommended';

	const missingCritical = [
		!usefulText(evidence.material_system) && evidence.materials.length < 1,
		evidence.condition_context.process.length < 1,
		evidence.condition_context.test.length < 1,
		evidence.condition_context.baseline.length < 1
	].filter(Boolean).length;

	if (missingCritical > 1) return 'needs_context';
	if (normalizedTraceabilityValue(evidence.traceability_status) === 'indirect')
		return 'needs_context';
	if (evidence.comparable === true && missingCritical <= 1) return 'joinable';
	return missingCritical ? 'needs_context' : 'joinable';
}

export function getEvidenceActions(evidence: EvidenceCard): EvidenceAction[] {
	const status = getComparabilityStatus(evidence);
	const base: EvidenceAction[] = [
		{ key: 'view_source', labelKey: 'evidence.actions.viewSource', tone: 'ghost' }
	];

	if (status === 'added') {
		base.push({
			key: 'view_comparison',
			labelKey: 'evidence.actions.viewComparison',
			tone: 'primary'
		});
	} else if (status === 'joinable') {
		base.push({
			key: 'add_to_comparison',
			labelKey: 'evidence.actions.addToComparison',
			tone: 'primary'
		});
	} else if (status === 'needs_context') {
		base.push({
			key: 'mark_trusted',
			labelKey: 'evidence.actions.markTrusted',
			tone: 'primary'
		});
	} else {
		base.push({
			key: 'view_reason',
			labelKey: 'evidence.actions.viewReason',
			tone: 'ghost'
		});
	}

	base.push({ key: 'mark_issue', labelKey: 'evidence.actions.markIssue', tone: 'ghost' });
	return base;
}

export function getEvidenceSourceLocation(evidence: EvidenceCard): EvidenceSourceLocation {
	const primaryAnchor = evidence.evidence_anchors[0] ?? null;
	const sourceType = primaryAnchor?.source_type ?? evidence.evidence_source_type;
	const section = usefulText(primaryAnchor?.section_id);
	const figureOrTable = usefulText(primaryAnchor?.figure_or_table);
	const locationParts = [
		typeof primaryAnchor?.page === 'number' ? `Page ${primaryAnchor.page}` : '',
		section ? (/^section\b/i.test(section) ? section : `Section ${section}`) : '',
		figureOrTable,
		usefulText(primaryAnchor?.block_id) ? `Block ${primaryAnchor?.block_id}` : ''
	].filter(Boolean);
	const contextValues = [
		...evidence.condition_context.process,
		...evidence.condition_context.baseline,
		...evidence.condition_context.test
	];
	const materials = uniqueNonEmpty([...evidence.materials, usefulText(evidence.material_system)]);
	const parameters = uniqueNonEmpty([...evidence.parameters, ...contextValues]);

	return {
		documentLabel:
			usefulText(evidence.source_document_title) ||
			usefulText(evidence.document_id) ||
			evidence.evidence_id,
		sourceType,
		location: locationParts.join(', ') || primaryAnchor?.label || '--',
		materials,
		parameters,
		tags: uniqueNonEmpty(evidence.tags.length ? evidence.tags : parameters.slice(0, 3))
	};
}

export function getEvidenceQuote(evidence: EvidenceCard): EvidenceQuote {
	const anchor =
		evidence.evidence_anchors.find(
			(item) => usefulText(item.quote) || usefulText(item.quote_span)
		) ??
		evidence.evidence_anchors[0] ??
		null;
	const location = getEvidenceSourceLocation(evidence);
	const text =
		usefulText(anchor?.quote) ||
		usefulText(anchor?.quote_span) ||
		usefulText(anchor?.label) ||
		usefulText(evidence.claim_text) ||
		'--';
	const citationParts = [location.documentLabel, location.location].filter(
		(item) => item && item !== '--'
	);

	return {
		text,
		citation: citationParts.join(', ')
	};
}

export function buildEvidenceQualitySummary(
	evidenceItems: EvidenceCard[]
): EvidenceQualitySummaryItem[] {
	const total = evidenceItems.length;
	const traceable = evidenceItems.filter(
		(item) => normalizedTraceabilityValue(item.traceability_status) !== 'none'
	).length;
	const needsReview = evidenceItems.filter((item) => {
		const status = getComparabilityStatus(item);
		return (
			status === 'needs_context' ||
			normalizedTraceabilityValue(item.traceability_status) === 'indirect' ||
			getConfidenceLevel(item.confidence) === 'low'
		);
	}).length;
	const comparable = evidenceItems.filter((item) =>
		['joinable', 'added'].includes(getComparabilityStatus(item))
	).length;
	const unusable = evidenceItems.filter(
		(item) => getComparabilityStatus(item) === 'not_recommended'
	).length;

	return [
		{
			key: 'total',
			labelKey: 'evidence.review.total',
			value: total,
			percent: null,
			tone: 'brand',
			icon: 'T'
		},
		{
			key: 'traceable',
			labelKey: 'evidence.review.traceable',
			value: traceable,
			percent: percentOf(traceable, total),
			tone: 'success',
			icon: 'OK'
		},
		{
			key: 'needs_review',
			labelKey: 'evidence.review.needsReview',
			value: needsReview,
			percent: percentOf(needsReview, total),
			tone: 'warning',
			icon: '!'
		},
		{
			key: 'comparable',
			labelKey: 'evidence.review.comparable',
			value: comparable,
			percent: percentOf(comparable, total),
			tone: 'purple',
			icon: 'C'
		},
		{
			key: 'unusable',
			labelKey: 'evidence.review.unusable',
			value: unusable,
			percent: percentOf(unusable, total),
			tone: 'danger',
			icon: 'X'
		}
	];
}

export function filterEvidenceItems(
	evidenceItems: EvidenceCard[],
	filters: EvidenceFilters
): EvidenceCard[] {
	const query = filters.search.trim().toLowerCase();

	return evidenceItems.filter((item) => {
		if (filters.type && normalizedEvidenceType(item.claim_type) !== filters.type) return false;
		if (
			filters.traceability &&
			normalizedTraceabilityValue(item.traceability_status) !== filters.traceability
		) {
			return false;
		}
		if (filters.source && item.evidence_source_type !== filters.source) return false;
		if (filters.confidence && getConfidenceLevel(item.confidence) !== filters.confidence) {
			return false;
		}
		if (filters.comparability && getComparabilityStatus(item) !== filters.comparability) {
			return false;
		}
		if (!query) return true;

		const location = getEvidenceSourceLocation(item);
		const quote = getEvidenceQuote(item);
		const searchableText = [
			item.evidence_id,
			item.claim_text,
			item.claim_type,
			item.material_system,
			location.documentLabel,
			location.location,
			quote.text,
			...location.materials,
			...location.parameters,
			...location.tags,
			...item.evidence_anchors.flatMap((anchor) => [
				anchor.label,
				anchor.quote ?? '',
				anchor.quote_span ?? '',
				anchor.figure_or_table ?? ''
			])
		]
			.join(' ')
			.toLowerCase();
		return searchableText.includes(query);
	});
}

export function sortEvidenceItems(
	evidenceItems: EvidenceCard[],
	sortMode: EvidenceSortMode
): EvidenceCard[] {
	return [...evidenceItems].sort((a, b) => {
		if (sortMode === 'confidence_asc') {
			const aConfidence = normalizedConfidence(a.confidence);
			const bConfidence = normalizedConfidence(b.confidence);
			return (aConfidence ?? Number.POSITIVE_INFINITY) - (bConfidence ?? Number.POSITIVE_INFINITY);
		}
		if (sortMode === 'recent') {
			return (
				Math.max(dateValue(b.updated_at), dateValue(b.extracted_at)) -
				Math.max(dateValue(a.updated_at), dateValue(a.extracted_at))
			);
		}
		if (sortMode === 'document') {
			return getEvidenceSourceLocation(a).documentLabel.localeCompare(
				getEvidenceSourceLocation(b).documentLabel
			);
		}

		const aConfidence = normalizedConfidence(a.confidence);
		const bConfidence = normalizedConfidence(b.confidence);
		return (bConfidence ?? Number.NEGATIVE_INFINITY) - (aConfidence ?? Number.NEGATIVE_INFINITY);
	});
}

export async function fetchEvidenceCards(collectionId: string): Promise<EvidenceCardsResponse> {
	if (USE_API_FIXTURES) {
		return buildFixture(collectionId);
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/evidence/cards`,
		{
			method: 'GET'
		}
	);
	return normalizeResponse(data, collectionId);
}

export async function fetchEvidenceCard(
	collectionId: string,
	evidenceId: string
): Promise<EvidenceCard> {
	if (USE_API_FIXTURES) {
		const fixture = buildFixture(collectionId).items.find(
			(item) => item.evidence_id === evidenceId
		);
		if (fixture) {
			return fixture;
		}
		throw new Error('Evidence card fixture is missing.');
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/evidence/${encodeURIComponent(evidenceId)}`,
		{
			method: 'GET'
		}
	);
	const card = normalizeCard(data, collectionId);
	if (!card) {
		throw new Error('Evidence card response is invalid.');
	}
	return card;
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
				.map((item, index) =>
					normalizeAnchor(item, collectionId, documentId, normalizedEvidenceId, index)
				)
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
