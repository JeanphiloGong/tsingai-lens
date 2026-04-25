import { buildApiUrl, requestJson } from './api';
import { USE_API_FIXTURES } from './base';
import type { ResultListItem } from './results';

export type DocumentType =
	| 'experimental'
	| 'review'
	| 'method'
	| 'computational'
	| 'mixed'
	| 'uncertain';
export type ProtocolExtractable = 'yes' | 'partial' | 'no' | 'uncertain';
export type DocumentProcessingStatus =
	| 'pending'
	| 'processing'
	| 'completed'
	| 'failed'
	| 'unknown';

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
	page_count?: number | null;
	updated_at?: string | null;
	processing_status?: DocumentProcessingStatus;
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

export type TextCharRange = {
	start: number;
	end: number;
};

export type PdfBoundingBox = {
	x0: number;
	y0: number;
	x1: number;
	y1: number;
	coord_origin: string | null;
};

export type DocumentContentBlock = {
	block_id: string;
	block_type: string | null;
	heading_path: string | null;
	heading_level: number;
	order: number;
	text: string;
	text_unit_ids: string[];
	start_offset: number | null;
	end_offset: number | null;
	page: number | null;
	bbox: PdfBoundingBox | null;
	charRange: TextCharRange | null;
};

export type DocumentContentResponse = {
	collection_id: string;
	document_id: string;
	title: string | null;
	source_filename: string | null;
	content_text: string;
	blocks: DocumentContentBlock[];
	warnings: string[];
};

export type DocumentChainComparabilityStatus =
	| 'comparable'
	| 'limited'
	| 'not_comparable'
	| 'insufficient';

export type DocumentChainMaterial = {
	label: string;
	composition: string | null;
	host_material_system: Record<string, unknown> | null;
};

export type DocumentChainMeasurement = {
	property: string;
	value: number | null;
	unit: string | null;
	result_type: string;
	summary: string;
	statistic_type: string | null;
	uncertainty: string | null;
};

export type DocumentChainTestCondition = {
	test_method: string | null;
	test_temperature_c: number | null;
	strain_rate_s_1: string | number | null;
	loading_direction: string | null;
	sample_orientation: string | null;
	environment: string | null;
	frequency_hz: number | null;
	specimen_geometry: string | null;
	surface_state: string | null;
};

export type DocumentChainBaseline = {
	label: string | null;
	reference: string | null;
	baseline_type: string | null;
	resolved: boolean;
};

export type DocumentChainAssessment = {
	comparability_status: DocumentChainComparabilityStatus;
	warnings: string[];
	basis: string[];
	missing_context: string[];
	requires_expert_review: boolean;
	assessment_epistemic_status: string;
};

export type DocumentChainValueProvenance = {
	value_origin: string;
	source_value_text: string | null;
	source_unit_text: string | null;
	derivation_formula: string | null;
	derivation_inputs: Record<string, unknown> | null;
};

export type DocumentChainEvidence = {
	evidence_ids: string[];
	direct_anchor_ids: string[];
	contextual_anchor_ids: string[];
	structure_feature_ids: string[];
	characterization_observation_ids: string[];
	traceability_status: string;
};

export type DocumentResultChain = {
	result_id: string;
	source_result_id: string;
	measurement: DocumentChainMeasurement;
	test_condition: DocumentChainTestCondition;
	baseline: DocumentChainBaseline;
	assessment: DocumentChainAssessment;
	value_provenance: DocumentChainValueProvenance;
	evidence: DocumentChainEvidence;
};

export type DocumentResultSeries = {
	series_key: string;
	property_family: string;
	test_family: string;
	varying_axis: {
		axis_name: string | null;
		axis_unit: string | null;
	};
	chains: DocumentResultChain[];
};

export type DocumentVariantDossier = {
	variant_id: string | null;
	variant_label: string | null;
	material: DocumentChainMaterial;
	shared_process_state: Record<string, unknown>;
	shared_missingness: string[];
	series: DocumentResultSeries[];
};

export type DocumentComparisonSemanticsResponse = {
	collection_id: string;
	document_id: string;
	total: number;
	count: number;
	items: unknown[];
	variant_dossiers: DocumentVariantDossier[];
};

export type DocumentComparisonSemanticsOptions = {
	includeGroupedProjections?: boolean;
};

export type SourceTargetPrecision =
	| 'pdf-region'
	| 'text-range'
	| 'pdf-page'
	| 'section'
	| 'quote-search'
	| 'unavailable';

export type WorkbenchSourceTarget = {
	documentId: string;
	label: string;
	page: number | null;
	bbox: PdfBoundingBox | null;
	charRange: TextCharRange | null;
	sectionId: string | null;
	headingPath: string | null;
	quote: string | null;
	precision: SourceTargetPrecision;
	userMessage: string | null;
};

export type WorkbenchSourceSpan = {
	id: string;
	block_id: string | null;
	page: number;
	section: string;
	quote: string;
	evidence_id: string | null;
	target: WorkbenchSourceTarget;
};

export type WorkbenchPdfParagraph = {
	id: string;
	section: string | null;
	text: string;
	source_span_id: string | null;
};

export type WorkbenchPdfPage = {
	page_number: number;
	label: string;
	paragraphs: WorkbenchPdfParagraph[];
	source_span_ids: string[];
};

export type WorkbenchSummaryCard = {
	id: string;
	title: string;
	body: string;
	source_label: string;
	source_span_id: string;
};

export type WorkbenchMethodRow = {
	label: string;
	value: string;
	source_span_id: string;
};

export type WorkbenchKeyResultCard = {
	id: string;
	label: string;
	value: string;
	trend: string;
	source_label: string;
	source_span_id: string;
};

export type WorkbenchResultRow = {
	id: string;
	material_system: string;
	process: string;
	property: string;
	baseline: string;
	test_condition: string;
	comparability_status: string;
	warnings_count: number;
	warnings: string[];
	source_span_id: string;
	evidence_id: string | null;
	detail_href: string;
};

export type WorkbenchEvidenceCard = {
	id: string;
	claim: string;
	supporting_evidence: string;
	source_section: string;
	confidence: string;
	sufficiency: string;
	status: 'strong' | 'limited' | 'missing';
	source_span_id: string;
	result_id: string | null;
};

export type WorkbenchQaSuggestion = {
	id: string;
	text: string;
};

export type WorkbenchGraphNodeType =
	| 'task'
	| 'material'
	| 'method'
	| 'result'
	| 'scenario'
	| 'concept';
export type WorkbenchGraphNodePosition =
	| 'center'
	| 'top'
	| 'left'
	| 'right'
	| 'bottom-left'
	| 'bottom-right';

export type WorkbenchGraphNode = {
	id: string;
	label: string;
	type: WorkbenchGraphNodeType;
	position: WorkbenchGraphNodePosition;
	detail: string;
	source_item_id: string | null;
	source_span_id: string | null;
};

export type WorkbenchGraphEdge = {
	id: string;
	source: string;
	target: string;
	label: string;
};

export type WorkbenchLocalGraph = {
	id: string;
	title: string;
	focus_item_id: string;
	nodes: WorkbenchGraphNode[];
	edges: WorkbenchGraphEdge[];
};

export type WorkbenchSelectableItem = {
	id: string;
	kind: 'summary' | 'method' | 'result' | 'evidence' | 'paragraph';
	tab: WorkbenchTab;
	title: string;
	source_span_id: string;
	graph_id: string;
};

export type WorkbenchTab = 'summary' | 'methods' | 'results' | 'evidence' | 'qa';

export type DocumentWorkbenchModel = {
	collection_id: string;
	document_id: string;
	title: string;
	source_filename: string | null;
	sourceFileUrl: string;
	metadata: string[];
	pages: WorkbenchPdfPage[];
	source_spans: WorkbenchSourceSpan[];
	source_targets_by_span_id: Record<string, WorkbenchSourceTarget>;
	summary_cards: WorkbenchSummaryCard[];
	method_rows: WorkbenchMethodRow[];
	key_results: WorkbenchKeyResultCard[];
	result_rows: WorkbenchResultRow[];
	evidence_cards: WorkbenchEvidenceCard[];
	qa_suggestions: WorkbenchQaSuggestion[];
	selectable_items: WorkbenchSelectableItem[];
	graphs_by_item_id: Record<string, WorkbenchLocalGraph>;
	default_item_id: string;
};

const DEFAULT_DOC_TYPE_COUNTS: Record<DocumentType, number> = {
	experimental: 0,
	review: 0,
	method: 0,
	computational: 0,
	mixed: 0,
	uncertain: 0
};

const DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS: Record<ProtocolExtractable, number> = {
	yes: 0,
	partial: 0,
	no: 0,
	uncertain: 0
};

const DOCUMENT_TYPE_KEYS: DocumentType[] = [
	'review',
	'experimental',
	'method',
	'computational',
	'mixed',
	'uncertain'
];

const PROTOCOL_SUITABILITY_KEYS: ProtocolExtractable[] = ['yes', 'partial', 'no', 'uncertain'];

const DOCUMENT_TYPE_VALUES = new Set<DocumentType>(DOCUMENT_TYPE_KEYS);
const PROTOCOL_SUITABILITY_VALUES = new Set<ProtocolExtractable>(PROTOCOL_SUITABILITY_KEYS);

export type DocumentTypeStat = {
	key: DocumentType;
	labelKey: string;
	count: number;
	percent: number;
	dominant: boolean;
	tone: DocumentType;
};

export type ProtocolSuitabilityStat = {
	key: ProtocolExtractable;
	labelKey: string;
	count: number;
	percent: number;
	dominant: boolean;
	tone: 'ready' | 'partial' | 'warning' | 'neutral';
};

export type ProfileConclusionStats = {
	total: number;
	documentTypeStats: DocumentTypeStat[];
	protocolSuitabilityStats: ProtocolSuitabilityStat[];
};

export type ProfileConclusionTone = 'warning' | 'ready' | 'limited' | 'neutral';

export type DocumentProfileAction =
	| 'upload_more'
	| 'view_evidence'
	| 'view_document'
	| 'open_comparison'
	| 'view_progress'
	| 'refresh'
	| 'view_error'
	| 'retry_processing'
	| 'manual_mark';

export type ProfileConclusion = {
	tone: ProfileConclusionTone;
	messageKey: string;
	actionKeys: DocumentProfileAction[];
};

export type ProfileBadge = {
	key: string;
	labelKey: string;
	tone: string;
};

function normalizeDocumentTypeValue(value: unknown): DocumentType {
	const type = String(value ?? '')
		.trim()
		.toLowerCase();
	if (DOCUMENT_TYPE_VALUES.has(type as DocumentType)) return type as DocumentType;
	if (['methodology', 'methods', 'method_paper', 'methods_paper'].includes(type)) {
		return 'method';
	}
	if (['computation', 'computational_modeling', 'simulation', 'modeling'].includes(type)) {
		return 'computational';
	}
	return 'uncertain';
}

function normalizeProtocolExtractableValue(value: unknown): ProtocolExtractable {
	const suitability = String(value ?? '')
		.trim()
		.toLowerCase();
	if (PROTOCOL_SUITABILITY_VALUES.has(suitability as ProtocolExtractable)) {
		return suitability as ProtocolExtractable;
	}
	if (['true', 'good', 'suitable', 'extractable'].includes(suitability)) return 'yes';
	if (['limited', 'partially', 'partially_suitable'].includes(suitability)) return 'partial';
	if (['false', 'not_suitable', 'not_extractable'].includes(suitability)) return 'no';
	return 'uncertain';
}

function normalizeProcessingStatusValue(value: unknown): DocumentProcessingStatus {
	const status = String(value ?? '')
		.trim()
		.toLowerCase();
	if (['pending', 'queued', 'uploaded', 'ready_to_process'].includes(status)) return 'pending';
	if (['processing', 'running', 'started', 'in_progress'].includes(status)) return 'processing';
	if (
		['completed', 'complete', 'ready', 'success', 'parsed', 'document_profiled'].includes(status)
	) {
		return 'completed';
	}
	if (['failed', 'failure', 'error'].includes(status)) return 'failed';
	return 'unknown';
}

function percentage(count: number, total: number) {
	if (total < 1) return 0;
	return Math.round((count / total) * 100);
}

function findStatCount<K extends string>(stats: Array<{ key: K; count: number }>, key: K) {
	return stats.find((item) => item.key === key)?.count ?? 0;
}

function protocolSuitabilityTone(key: ProtocolExtractable): ProtocolSuitabilityStat['tone'] {
	if (key === 'yes') return 'ready';
	if (key === 'partial') return 'partial';
	if (key === 'no') return 'warning';
	return 'neutral';
}

export function buildDocumentTypeStats(profiles: DocumentProfile[]): DocumentTypeStat[] {
	const counts = { ...DEFAULT_DOC_TYPE_COUNTS };
	for (const profile of profiles) {
		const key = normalizeDocumentTypeValue(profile.doc_type);
		counts[key] += 1;
	}

	const total = profiles.length;
	const maxCount = Math.max(0, ...DOCUMENT_TYPE_KEYS.map((key) => counts[key]));
	return DOCUMENT_TYPE_KEYS.map((key) => ({
		key,
		labelKey: `profiles.docTypes.${key}`,
		count: counts[key],
		percent: percentage(counts[key], total),
		dominant: counts[key] > 0 && counts[key] === maxCount,
		tone: key
	}));
}

export function buildProtocolSuitabilityStats(
	profiles: DocumentProfile[]
): ProtocolSuitabilityStat[] {
	const counts = { ...DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS };
	for (const profile of profiles) {
		const key = normalizeProtocolExtractableValue(profile.protocol_extractable);
		counts[key] += 1;
	}

	const total = profiles.length;
	const maxCount = Math.max(0, ...PROTOCOL_SUITABILITY_KEYS.map((key) => counts[key]));
	return PROTOCOL_SUITABILITY_KEYS.map((key) => ({
		key,
		labelKey: `profiles.suitability.${key}`,
		count: counts[key],
		percent: percentage(counts[key], total),
		dominant: counts[key] > 0 && counts[key] === maxCount,
		tone: protocolSuitabilityTone(key)
	}));
}

export function buildProfileConclusion(stats: ProfileConclusionStats): ProfileConclusion {
	const reviewCount = findStatCount(stats.documentTypeStats, 'review');
	const experimentalCount = findStatCount(stats.documentTypeStats, 'experimental');
	const methodCount = findStatCount(stats.documentTypeStats, 'method');
	const suitableCount = findStatCount(stats.protocolSuitabilityStats, 'yes');
	const partialCount = findStatCount(stats.protocolSuitabilityStats, 'partial');
	const notSuitableCount = findStatCount(stats.protocolSuitabilityStats, 'no');
	const reviewDominant = stats.total > 0 && reviewCount >= Math.ceil(stats.total / 2);
	const notSuitableDominant = stats.total > 0 && notSuitableCount >= Math.ceil(stats.total / 2);

	if (stats.total < 1) {
		return {
			tone: 'limited',
			messageKey: 'profiles.conclusion.pending',
			actionKeys: ['upload_more', 'refresh']
		};
	}

	if (reviewDominant && notSuitableDominant) {
		return {
			tone: 'warning',
			messageKey: 'profiles.conclusion.reviewRisk',
			actionKeys: ['upload_more', 'view_evidence']
		};
	}

	if (suitableCount > 0 && experimentalCount + methodCount > 0) {
		return {
			tone: 'ready',
			messageKey: 'profiles.conclusion.ready',
			actionKeys: ['view_evidence', 'open_comparison']
		};
	}

	if (stats.total < 2) {
		return {
			tone: 'warning',
			messageKey: 'profiles.conclusion.fewDocuments',
			actionKeys: ['upload_more']
		};
	}

	if (suitableCount + partialCount > 0) {
		return {
			tone: 'ready',
			messageKey: 'profiles.conclusion.limitedReady',
			actionKeys: ['view_evidence', 'open_comparison']
		};
	}

	return {
		tone: 'limited',
		messageKey: 'profiles.conclusion.limited',
		actionKeys: ['upload_more', 'view_evidence']
	};
}

export function getDocumentNextActions(profile: DocumentProfile): DocumentProfileAction[] {
	const status = normalizeProcessingStatusValue(profile.processing_status);
	if (status === 'pending' || status === 'processing') return ['view_progress', 'refresh'];
	if (status === 'failed') return ['view_error', 'retry_processing'];

	const docType = normalizeDocumentTypeValue(profile.doc_type);
	const suitability = normalizeProtocolExtractableValue(profile.protocol_extractable);

	if (docType === 'review' && suitability === 'no') return ['view_document', 'view_evidence'];
	if ((docType === 'experimental' || docType === 'method') && suitability === 'yes') {
		return ['view_evidence', 'open_comparison'];
	}
	if (docType === 'uncertain' || suitability === 'uncertain') {
		return ['view_document', 'manual_mark'];
	}
	return ['view_document', 'view_evidence'];
}

export function formatConfidence(confidence?: number | null) {
	if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return '--';
	const percent = confidence <= 1 ? confidence * 100 : confidence;
	return `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
}

export function getDocumentTypeBadge(type: DocumentProfile['doc_type']): ProfileBadge {
	const key = normalizeDocumentTypeValue(type);
	return {
		key,
		labelKey: `profiles.docTypes.${key}`,
		tone: key
	};
}

export function getSuitabilityBadge(
	suitability: DocumentProfile['protocol_extractable']
): ProfileBadge {
	const key = normalizeProtocolExtractableValue(suitability);
	return {
		key,
		labelKey: `profiles.suitability.${key}`,
		tone: protocolSuitabilityTone(key)
	};
}

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

function toOptionalNumber(value: unknown) {
	const number = toNumber(value);
	return Number.isFinite(number) ? number : null;
}

function toPositiveInteger(value: unknown) {
	const number = toOptionalNumber(value);
	if (number === null) return null;
	const integer = Math.trunc(number);
	return integer > 0 && integer === number ? integer : null;
}

function toNonNegativeInteger(value: unknown) {
	const number = toOptionalNumber(value);
	if (number === null) return null;
	const integer = Math.trunc(number);
	return integer >= 0 && integer === number ? integer : null;
}

function normalizeTextCharRange(value: unknown): TextCharRange | null {
	const record = asRecord(value);
	if (!record) return null;

	const start = toNonNegativeInteger(record.start);
	const end = toNonNegativeInteger(record.end);
	if (start === null || end === null || end < start) return null;
	return { start, end };
}

function normalizePdfBoundingBox(value: unknown): PdfBoundingBox | null {
	const record = asRecord(value);
	if (!record) return null;

	const x0 = toOptionalNumber(record.x0);
	const y0 = toOptionalNumber(record.y0);
	const x1 = toOptionalNumber(record.x1);
	const y1 = toOptionalNumber(record.y1);
	if (x0 === null || y0 === null || x1 === null || y1 === null) return null;

	return {
		x0,
		y0,
		x1,
		y1,
		coord_origin: toOptionalText(record.coord_origin)
	};
}

function toBoolean(value: unknown) {
	if (typeof value === 'boolean') return value;
	if (typeof value === 'number') return value !== 0;
	if (typeof value === 'string') {
		const normalized = value.trim().toLowerCase();
		if (normalized === 'true') return true;
		if (normalized === 'false') return false;
	}
	return false;
}

function toScalarOrText(value: unknown): string | number | null {
	const number = toOptionalNumber(value);
	if (number !== null) return number;
	return toOptionalText(value);
}

function normalizeComparabilityStatus(value: unknown): DocumentChainComparabilityStatus {
	const status = String(value ?? '').trim();
	return ['comparable', 'limited', 'not_comparable', 'insufficient'].includes(status)
		? (status as DocumentChainComparabilityStatus)
		: 'insufficient';
}

function normalizeContentBlock(value: unknown, index: number): DocumentContentBlock | null {
	const record = asRecord(value);
	if (!record) return null;

	const block_id = String(record.block_id ?? '').trim();
	const text = String(record.text ?? '').trim();
	if (!block_id || !text) return null;

	const startOffset = toNumber(record.start_offset);
	const endOffset = toNumber(record.end_offset);

	return {
		block_id,
		block_type: toOptionalText(record.block_type),
		heading_path: toOptionalText(record.heading_path),
		heading_level: Number.isFinite(toNumber(record.heading_level))
			? toNumber(record.heading_level)
			: 0,
		order: Number.isFinite(toNumber(record.order)) ? toNumber(record.order) : index + 1,
		text,
		text_unit_ids: toStringList(record.text_unit_ids),
		start_offset: Number.isFinite(startOffset) ? startOffset : null,
		end_offset: Number.isFinite(endOffset) ? endOffset : null,
		page: toPositiveInteger(record.page),
		bbox: normalizePdfBoundingBox(record.bbox),
		charRange: normalizeTextCharRange(record.char_range ?? record.charRange)
	};
}

function normalizeProfile(value: unknown, collectionId: string): DocumentProfile | null {
	const record = asRecord(value);
	if (!record) return null;

	const document_id = String(record.document_id ?? record.id ?? '').trim();
	if (!document_id) return null;

	const confidence = toNumber(record.confidence);

	return {
		document_id,
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		title: toOptionalText(record.title) ?? toOptionalText(record.document_title),
		source_filename:
			toOptionalText(record.source_filename) ??
			toOptionalText(record.original_filename) ??
			toOptionalText(record.source_file_name),
		doc_type: normalizeDocumentTypeValue(record.doc_type),
		protocol_extractable: normalizeProtocolExtractableValue(record.protocol_extractable),
		protocol_extractability_signals: toStringList(record.protocol_extractability_signals),
		parsing_warnings: toStringList(record.parsing_warnings),
		confidence: Number.isFinite(confidence) ? confidence : null,
		page_count: toPositiveInteger(record.page_count ?? record.pages),
		updated_at: toOptionalText(record.updated_at ?? record.modified_at ?? record.created_at),
		processing_status: normalizeProcessingStatusValue(
			record.processing_status ?? record.status ?? record.profile_status
		)
	};
}

function normalizeDocumentChainMaterial(value: unknown): DocumentChainMaterial {
	const record = asRecord(value);
	return {
		label: String(record?.label ?? '--').trim() || '--',
		composition: toOptionalText(record?.composition),
		host_material_system: asRecord(record?.host_material_system)
	};
}

function normalizeDocumentChainMeasurement(value: unknown): DocumentChainMeasurement {
	const record = asRecord(value);
	return {
		property: String(record?.property ?? '--').trim() || '--',
		value: toOptionalNumber(record?.value),
		unit: toOptionalText(record?.unit),
		result_type: String(record?.result_type ?? 'scalar').trim() || 'scalar',
		summary: String(record?.summary ?? '--').trim() || '--',
		statistic_type: toOptionalText(record?.statistic_type),
		uncertainty: toOptionalText(record?.uncertainty)
	};
}

function normalizeDocumentChainTestCondition(value: unknown): DocumentChainTestCondition {
	const record = asRecord(value);
	return {
		test_method: toOptionalText(record?.test_method),
		test_temperature_c: toOptionalNumber(record?.test_temperature_c),
		strain_rate_s_1: toScalarOrText(record?.['strain_rate_s-1'] ?? record?.strain_rate_s_1),
		loading_direction: toOptionalText(record?.loading_direction),
		sample_orientation: toOptionalText(record?.sample_orientation),
		environment: toOptionalText(record?.environment),
		frequency_hz: toOptionalNumber(record?.frequency_hz),
		specimen_geometry: toOptionalText(record?.specimen_geometry),
		surface_state: toOptionalText(record?.surface_state)
	};
}

function normalizeDocumentChainBaseline(value: unknown): DocumentChainBaseline {
	const record = asRecord(value);
	return {
		label: toOptionalText(record?.label),
		reference: toOptionalText(record?.reference),
		baseline_type: toOptionalText(record?.baseline_type),
		resolved: toBoolean(record?.resolved)
	};
}

function normalizeDocumentChainAssessment(value: unknown): DocumentChainAssessment {
	const record = asRecord(value);
	return {
		comparability_status: normalizeComparabilityStatus(record?.comparability_status),
		warnings: toStringList(record?.warnings),
		basis: toStringList(record?.basis),
		missing_context: toStringList(record?.missing_context),
		requires_expert_review: toBoolean(record?.requires_expert_review),
		assessment_epistemic_status:
			String(record?.assessment_epistemic_status ?? 'unresolved').trim() || 'unresolved'
	};
}

function normalizeDocumentChainValueProvenance(value: unknown): DocumentChainValueProvenance {
	const record = asRecord(value);
	return {
		value_origin: String(record?.value_origin ?? 'unknown').trim() || 'unknown',
		source_value_text: toOptionalText(record?.source_value_text),
		source_unit_text: toOptionalText(record?.source_unit_text),
		derivation_formula: toOptionalText(record?.derivation_formula),
		derivation_inputs: asRecord(record?.derivation_inputs)
	};
}

function normalizeDocumentChainEvidence(value: unknown): DocumentChainEvidence {
	const record = asRecord(value);
	return {
		evidence_ids: toStringList(record?.evidence_ids),
		direct_anchor_ids: toStringList(record?.direct_anchor_ids),
		contextual_anchor_ids: toStringList(record?.contextual_anchor_ids),
		structure_feature_ids: toStringList(record?.structure_feature_ids),
		characterization_observation_ids: toStringList(record?.characterization_observation_ids),
		traceability_status: String(record?.traceability_status ?? 'missing').trim() || 'missing'
	};
}

function normalizeDocumentResultChain(value: unknown): DocumentResultChain | null {
	const record = asRecord(value);
	if (!record) return null;

	const result_id = String(record.result_id ?? '').trim();
	if (!result_id) return null;

	return {
		result_id,
		source_result_id: String(record.source_result_id ?? result_id).trim() || result_id,
		measurement: normalizeDocumentChainMeasurement(record.measurement),
		test_condition: normalizeDocumentChainTestCondition(record.test_condition),
		baseline: normalizeDocumentChainBaseline(record.baseline),
		assessment: normalizeDocumentChainAssessment(record.assessment),
		value_provenance: normalizeDocumentChainValueProvenance(record.value_provenance),
		evidence: normalizeDocumentChainEvidence(record.evidence)
	};
}

function normalizeDocumentResultSeries(value: unknown): DocumentResultSeries | null {
	const record = asRecord(value);
	if (!record) return null;

	const series_key = String(record.series_key ?? '').trim();
	if (!series_key) return null;

	const axisRecord = asRecord(record.varying_axis);

	return {
		series_key,
		property_family: String(record.property_family ?? '--').trim() || '--',
		test_family: String(record.test_family ?? '--').trim() || '--',
		varying_axis: {
			axis_name: toOptionalText(axisRecord?.axis_name),
			axis_unit: toOptionalText(axisRecord?.axis_unit)
		},
		chains: Array.isArray(record.chains)
			? record.chains
					.map((item) => normalizeDocumentResultChain(item))
					.filter((item): item is DocumentResultChain => item !== null)
			: []
	};
}

function normalizeDocumentVariantDossier(value: unknown): DocumentVariantDossier | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		variant_id: toOptionalText(record.variant_id),
		variant_label: toOptionalText(record.variant_label),
		material: normalizeDocumentChainMaterial(record.material),
		shared_process_state: asRecord(record.shared_process_state) ?? {},
		shared_missingness: toStringList(record.shared_missingness),
		series: Array.isArray(record.series)
			? record.series
					.map((item) => normalizeDocumentResultSeries(item))
					.filter((item): item is DocumentResultSeries => item !== null)
			: []
	};
}

function normalizeDocumentComparisonSemantics(
	value: unknown,
	collectionId: string,
	documentId: string
): DocumentComparisonSemanticsResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Document comparison semantics response is invalid.');
	}

	const items = Array.isArray(record.items) ? record.items : [];
	const variant_dossiers = Array.isArray(record.variant_dossiers)
		? record.variant_dossiers
				.map((item) => normalizeDocumentVariantDossier(item))
				.filter((item): item is DocumentVariantDossier => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		document_id: String(record.document_id ?? documentId).trim() || documentId,
		total: typeof record.total === 'number' ? record.total : items.length,
		count: typeof record.count === 'number' ? record.count : items.length,
		items,
		variant_dossiers
	};
}

type WorkbenchChainContext = {
	dossier: DocumentVariantDossier;
	series: DocumentResultSeries;
	chain: DocumentResultChain;
};

function workbenchFixtureBlocks(): DocumentContentBlock[] {
	return [
		{
			block_id: 'abstract',
			block_type: 'abstract',
			heading_path: 'Abstract',
			heading_level: 1,
			order: 1,
			text: 'We propose Graph Prompting, a simple yet effective framework that reformulates knowledge graph completion as prompt-based generation with structural context.',
			text_unit_ids: ['fixture-tu-abstract'],
			start_offset: null,
			end_offset: null,
			page: 1,
			bbox: { x0: 72, y0: 120, x1: 520, y1: 186, coord_origin: 'top_left' },
			charRange: { start: 0, end: 152 }
		},
		{
			block_id: 'intro-kcg',
			block_type: 'introduction',
			heading_path: 'Introduction',
			heading_level: 1,
			order: 2,
			text: 'In low-resource settings, each query is paired with a small relevant subgraph context. The context and query are verbalized into a prompt, which is fed into a frozen language model to predict the missing entity.',
			text_unit_ids: ['fixture-tu-intro'],
			start_offset: null,
			end_offset: null,
			page: 2,
			bbox: null,
			charRange: null
		},
		{
			block_id: 'method-model',
			block_type: 'methods',
			heading_path: 'Methodology',
			heading_level: 1,
			order: 3,
			text: 'The method samples neighborhood triples, builds a subgraph prompt, and evaluates entity prediction under few-shot knowledge graph completion benchmarks.',
			text_unit_ids: ['fixture-tu-method'],
			start_offset: null,
			end_offset: null,
			page: null,
			bbox: null,
			charRange: null
		},
		{
			block_id: 'results-main',
			block_type: 'results',
			heading_path: 'Results',
			heading_level: 1,
			order: 4,
			text: 'Across five benchmark datasets, Graph Prompting improves ranking metrics in the low-resource regime while keeping the model frozen.',
			text_unit_ids: ['fixture-tu-results'],
			start_offset: null,
			end_offset: null,
			page: 4,
			bbox: null,
			charRange: null
		},
		{
			block_id: 'discussion-limits',
			block_type: 'discussion',
			heading_path: 'Discussion',
			heading_level: 1,
			order: 5,
			text: 'The result is most reliable when the source paragraph reports the benchmark split, baseline, metric, and evaluation setting together.',
			text_unit_ids: ['fixture-tu-discussion'],
			start_offset: null,
			end_offset: null,
			page: null,
			bbox: null,
			charRange: null
		}
	];
}

function sortedWorkbenchBlocks(content: DocumentContentResponse | null | undefined) {
	const blocks = [...(content?.blocks ?? [])].sort((left, right) => left.order - right.order);
	if (blocks.length) return blocks;
	return workbenchFixtureBlocks();
}

function sectionForWorkbenchBlock(block: DocumentContentBlock, index: number) {
	return block.heading_path?.trim() || block.block_type?.trim() || `Section ${index + 1}`;
}

function sourceSpanIdForBlock(block: DocumentContentBlock) {
	return `source-${block.block_id}`;
}

function sourceTargetPrecision(block: DocumentContentBlock): SourceTargetPrecision {
	if (block.page !== null && block.bbox) return 'pdf-region';
	if (block.charRange) return 'text-range';
	if (block.page !== null) return 'pdf-page';
	if (block.heading_path) return 'section';
	if (block.text) return 'quote-search';
	return 'unavailable';
}

function sourceTargetMessage(precision: SourceTargetPrecision) {
	if (precision === 'pdf-region') {
		return 'PDF region metadata is available; this reader opens the source page until region overlays are enabled.';
	}
	if (precision === 'text-range') return 'Parsed text range is available for highlighting.';
	if (precision === 'pdf-page') return 'Precise PDF region is unavailable; page fallback is used.';
	if (precision === 'section') {
		return 'Location precision is limited; review the nearby source section.';
	}
	if (precision === 'quote-search') return 'Location is matched from the source quote.';
	return 'Source location is unavailable for this item.';
}

function buildWorkbenchSourceTarget(
	documentId: string,
	block: DocumentContentBlock,
	index: number
): WorkbenchSourceTarget {
	const label = sectionForWorkbenchBlock(block, index);
	const precision = sourceTargetPrecision(block);
	return {
		documentId,
		label,
		page: block.page,
		bbox: block.bbox,
		charRange: block.charRange,
		sectionId: block.heading_path
			? `section-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
			: null,
		headingPath: block.heading_path,
		quote: block.text || null,
		precision,
		userMessage: sourceTargetMessage(precision)
	};
}

function buildDocumentSourceFileUrl(collectionId: string, documentId: string) {
	return buildApiUrl(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/source`
	);
}

function buildWorkbenchSourceSpans(
	documentId: string,
	blocks: DocumentContentBlock[]
): WorkbenchSourceSpan[] {
	return blocks.map((block, index) => ({
		id: sourceSpanIdForBlock(block),
		block_id: block.block_id,
		page: block.page ?? Math.floor(index / 3) + 1,
		section: sectionForWorkbenchBlock(block, index),
		quote: block.text,
		evidence_id: null,
		target: buildWorkbenchSourceTarget(documentId, block, index)
	}));
}

function spanAt(spans: WorkbenchSourceSpan[], index: number) {
	return spans[index % Math.max(spans.length, 1)]?.id ?? 'source-abstract';
}

function buildWorkbenchPages(
	blocks: DocumentContentBlock[],
	spans: WorkbenchSourceSpan[],
	padFixturePages: boolean
) {
	const pagesByNumber = new Map<number, WorkbenchPdfPage>();

	for (const [index, block] of blocks.entries()) {
		const span = spans[index];
		const pageNumber = span?.page ?? Math.floor(index / 3) + 1;
		const page = pagesByNumber.get(pageNumber) ?? {
			page_number: pageNumber,
			label: `Page ${pageNumber}`,
			paragraphs: [],
			source_span_ids: []
		};
		page.paragraphs.push({
			id: block.block_id,
			section: sectionForWorkbenchBlock(block, index),
			text: block.text,
			source_span_id: span?.id ?? sourceSpanIdForBlock(block)
		});
		page.source_span_ids.push(span?.id ?? sourceSpanIdForBlock(block));
		pagesByNumber.set(pageNumber, page);
	}

	const pages = Array.from(pagesByNumber.values()).sort(
		(left, right) => left.page_number - right.page_number
	);

	while (padFixturePages && pages.length < 4) {
		const pageNumber = pages.length + 1;
		pages.push({
			page_number: pageNumber,
			label: `Page ${pageNumber}`,
			paragraphs: [
				{
					id: `fixture-page-${pageNumber}`,
					section:
						pageNumber === 2 ? 'Related Work' : pageNumber === 3 ? 'Experiments' : 'Appendix',
					text:
						pageNumber === 2
							? 'Prior methods rely on dense triples or task-specific fine tuning. This page is a fixture continuation used when the backend has not supplied a full PDF text layer.'
							: pageNumber === 3
								? 'Evaluation reports benchmark-level rows, baseline methods, and metric deltas so extracted results can be read beside the source context.'
								: 'Additional source pages are represented as placeholders until real PDF page geometry is available.',
					source_span_id: spanAt(spans, pageNumber - 1)
				}
			],
			source_span_ids: [spanAt(spans, pageNumber - 1)]
		});
	}

	return pages;
}

function flattenWorkbenchChains(
	dossiers: DocumentVariantDossier[] | undefined
): WorkbenchChainContext[] {
	const contexts: WorkbenchChainContext[] = [];
	for (const dossier of dossiers ?? []) {
		for (const series of dossier.series) {
			for (const chain of series.chains) {
				contexts.push({ dossier, series, chain });
			}
		}
	}
	return contexts;
}

function workbenchOptional(value: unknown) {
	if (value === null || value === undefined) return '';
	if (typeof value === 'string') return value.trim();
	if (typeof value === 'number' || typeof value === 'boolean') return String(value);
	return '';
}

function workbenchRecordSummary(record: Record<string, unknown> | null | undefined) {
	const entries = Object.entries(record ?? {})
		.map(([key, value]) => {
			const text = workbenchOptional(value);
			return text ? `${key}: ${text}` : '';
		})
		.filter(Boolean);
	return entries.join(' - ');
}

function workbenchMeasurementValue(value: number | null, unit: string | null) {
	if (value === null || value === undefined) return '--';
	return unit ? `${value} ${unit}` : String(value);
}

function workbenchTestConditionSummary(condition: DocumentChainTestCondition) {
	const rows = [
		condition.test_method,
		condition.test_temperature_c !== null ? `${condition.test_temperature_c} C` : null,
		condition.strain_rate_s_1 !== null ? `strain rate ${condition.strain_rate_s_1}` : null,
		condition.loading_direction,
		condition.sample_orientation,
		condition.environment,
		condition.frequency_hz !== null ? `${condition.frequency_hz} Hz` : null,
		condition.specimen_geometry,
		condition.surface_state
	]
		.map((item) => workbenchOptional(item))
		.filter(Boolean);
	return rows.join(' - ');
}

function readableComparabilityStatus(status: DocumentChainComparabilityStatus | string) {
	if (status === 'comparable') return 'Comparable';
	if (status === 'limited') return 'Limited comparability, review the source';
	if (status === 'not_comparable') return 'Not comparable across the stated baseline';
	return 'Evidence is insufficient for comparison';
}

function readableTraceabilityStatus(status: string) {
	if (status === 'direct') return 'Direct source support';
	if (status === 'partial') return 'Partial source support';
	return 'Source support is not yet available';
}

function readableWarning(raw: string) {
	const value = raw.trim().toLowerCase();
	if (!value) return '';
	if (value.includes('test') || value.includes('condition')) {
		return 'Evidence gap: the source does not report the test condition clearly.';
	}
	if (value.includes('baseline')) {
		return 'The result lacks a clearly comparable baseline.';
	}
	if (value.includes('variant') || value.includes('material')) {
		return 'Material system is not clearly specified.';
	}
	if (value.includes('process')) {
		return 'Evidence gap: the process context is not reported in the source.';
	}
	if (value.includes('insufficient')) {
		return 'Evidence is insufficient; review the source paragraph before using this result.';
	}
	return 'Comparability is limited; review the source paragraph before using this result.';
}

function readableWarnings(assessment: DocumentChainAssessment, baseline: DocumentChainBaseline) {
	const warnings: string[] = [...assessment.warnings, ...assessment.missing_context]
		.map(readableWarning)
		.filter(Boolean);
	if (!baseline.resolved && !warnings.some((item) => item.includes('baseline'))) {
		warnings.push('The result lacks a clearly comparable baseline.');
	}
	if (assessment.comparability_status === 'limited' && warnings.length === 0) {
		warnings.push(
			'Comparability is limited; review the source paragraph before using this result.'
		);
	}
	if (assessment.comparability_status === 'insufficient' && warnings.length === 0) {
		warnings.push('Evidence is insufficient for comparison.');
	}
	return Array.from(new Set(warnings));
}

function workbenchMaterialLabel(
	contexts: WorkbenchChainContext[],
	relatedResults: ResultListItem[]
) {
	return (
		contexts.find((context) => context.dossier.material.label !== '--')?.dossier.material.label ??
		relatedResults.find((item) => item.material_label)?.material_label ??
		'Material system not clearly specified'
	);
}

function buildWorkbenchResultRows(
	collectionId: string,
	contexts: WorkbenchChainContext[],
	relatedResults: ResultListItem[],
	sourceSpans: WorkbenchSourceSpan[]
): WorkbenchResultRow[] {
	if (contexts.length) {
		return contexts.map((context, index) => {
			const { dossier, series, chain } = context;
			const sourceSpanId = spanAt(sourceSpans, index + 1);
			const warnings = readableWarnings(chain.assessment, chain.baseline);
			return {
				id: chain.result_id,
				material_system: dossier.material.label,
				process:
					workbenchRecordSummary(dossier.shared_process_state) || 'Process not clearly reported',
				property: chain.measurement.property,
				baseline: chain.baseline.label || 'No comparable baseline reported',
				test_condition:
					workbenchTestConditionSummary(chain.test_condition) ||
					`${series.test_family}; test condition not fully reported`,
				comparability_status: readableComparabilityStatus(chain.assessment.comparability_status),
				warnings_count: warnings.length,
				warnings,
				source_span_id: sourceSpanId,
				evidence_id: chain.evidence.evidence_ids[0] ?? null,
				detail_href: `/collections/${encodeURIComponent(collectionId)}/results/${encodeURIComponent(chain.result_id)}`
			};
		});
	}

	return relatedResults.map((result, index) => {
		const sourceSpanId = spanAt(sourceSpans, index + 1);
		const status = normalizeComparabilityStatus(result.comparability_status);
		const warnings =
			status === 'comparable'
				? []
				: [
						status === 'limited'
							? 'Comparability is limited; review the source paragraph before using this result.'
							: readableComparabilityStatus(status)
					];
		return {
			id: result.result_id,
			material_system: result.material_label || 'Material system not clearly specified',
			process: result.process || 'Process not clearly reported',
			property: result.property,
			baseline: result.baseline || 'No comparable baseline reported',
			test_condition: result.test_condition || 'Test condition not reported',
			comparability_status: readableComparabilityStatus(status),
			warnings_count: warnings.length,
			warnings,
			source_span_id: sourceSpanId,
			evidence_id: null,
			detail_href: `/collections/${encodeURIComponent(collectionId)}/results/${encodeURIComponent(result.result_id)}`
		};
	});
}

function buildWorkbenchSummaryCards(
	contexts: WorkbenchChainContext[],
	resultRows: WorkbenchResultRow[],
	sourceSpans: WorkbenchSourceSpan[]
): WorkbenchSummaryCard[] {
	const material = workbenchMaterialLabel(contexts, []);
	const firstContext = contexts[0];
	const firstResult = resultRows[0];
	return [
		{
			id: 'summary-question',
			title: 'Research question',
			body:
				firstContext?.series.test_family && firstContext.series.property_family
					? `How does the reported ${firstContext.series.test_family} setup affect ${firstContext.series.property_family}?`
					: 'How does the paper connect its method or material design to measurable outcomes?',
			source_label: 'Abstract',
			source_span_id: spanAt(sourceSpans, 0)
		},
		{
			id: 'summary-contribution',
			title: 'Main contribution',
			body:
				firstResult?.property && firstResult.material_system
					? `The paper organizes evidence around ${firstResult.material_system} and reports ${firstResult.property} with source-backed context.`
					: 'The paper provides a structured method-result chain that can be reviewed next to the original source.',
			source_label: 'Abstract',
			source_span_id: spanAt(sourceSpans, 0)
		},
		{
			id: 'summary-materials',
			title: 'Dataset / materials',
			body: material,
			source_label: 'Methodology',
			source_span_id: spanAt(sourceSpans, 2)
		},
		{
			id: 'summary-method',
			title: 'Method',
			body:
				firstResult?.process && firstResult.process !== 'Process not clearly reported'
					? firstResult.process
					: 'Method details are represented as a source-linked extraction until the backend provides richer section roles.',
			source_label: 'Methodology',
			source_span_id: spanAt(sourceSpans, 2)
		},
		{
			id: 'summary-key-result',
			title: 'Key result',
			body:
				firstResult?.property && firstResult.comparability_status
					? `${firstResult.property}: ${firstResult.comparability_status}.`
					: 'Key results are available as reviewable cards with source jumps.',
			source_label: 'Results',
			source_span_id: firstResult?.source_span_id ?? spanAt(sourceSpans, 3)
		}
	];
}

function buildWorkbenchMethodRows(
	contexts: WorkbenchChainContext[],
	resultRows: WorkbenchResultRow[],
	sourceSpans: WorkbenchSourceSpan[]
): WorkbenchMethodRow[] {
	const firstContext = contexts[0];
	const firstResult = resultRows[0];
	return [
		{
			label: 'Experiment setup',
			value: firstContext?.series.test_family || 'Experimental setup not fully reported',
			source_span_id: spanAt(sourceSpans, 2)
		},
		{
			label: 'Material system',
			value: firstResult?.material_system || 'Material system not clearly specified',
			source_span_id: spanAt(sourceSpans, 2)
		},
		{
			label: 'Process parameters',
			value: firstResult?.process || 'Process context not reported',
			source_span_id: spanAt(sourceSpans, 2)
		},
		{
			label: 'Test conditions',
			value: firstResult?.test_condition || 'Test condition not reported',
			source_span_id: firstResult?.source_span_id ?? spanAt(sourceSpans, 3)
		},
		{
			label: 'Baseline / control',
			value: firstResult?.baseline || 'No comparable baseline reported',
			source_span_id: firstResult?.source_span_id ?? spanAt(sourceSpans, 3)
		}
	];
}

function buildWorkbenchKeyResults(
	contexts: WorkbenchChainContext[],
	relatedResults: ResultListItem[],
	resultRows: WorkbenchResultRow[],
	sourceSpans: WorkbenchSourceSpan[]
): WorkbenchKeyResultCard[] {
	const cards = contexts.slice(0, 3).map((context, index) => ({
		id: `key-${context.chain.result_id}`,
		label: context.chain.measurement.property,
		value: workbenchMeasurementValue(
			context.chain.measurement.value,
			context.chain.measurement.unit
		),
		trend:
			context.chain.assessment.comparability_status === 'comparable'
				? 'Key Finding'
				: 'Review Needed',
		source_label: 'Results',
		source_span_id: resultRows[index]?.source_span_id ?? spanAt(sourceSpans, index + 3)
	}));

	if (cards.length) return cards;

	return relatedResults.slice(0, 3).map((result, index) => ({
		id: `key-${result.result_id}`,
		label: result.property,
		value: workbenchMeasurementValue(result.value, result.unit),
		trend: result.comparability_status === 'comparable' ? 'Key Finding' : 'Review Needed',
		source_label: 'Results',
		source_span_id: resultRows[index]?.source_span_id ?? spanAt(sourceSpans, index + 3)
	}));
}

function buildWorkbenchEvidenceCards(resultRows: WorkbenchResultRow[]): WorkbenchEvidenceCard[] {
	return resultRows.map((row, index) => {
		const missing = row.comparability_status.toLowerCase().includes('insufficient');
		const limited =
			row.warnings_count > 0 || row.comparability_status.toLowerCase().includes('limited');
		return {
			id: row.evidence_id || `evidence-${row.id || index + 1}`,
			claim: `${row.property} is reported for ${row.material_system}.`,
			supporting_evidence: row.warnings[0] || row.comparability_status,
			source_section: 'Results',
			confidence: missing ? 'Low' : limited ? 'Medium' : 'High',
			sufficiency: missing
				? 'Insufficient context'
				: limited
					? 'Limited, verify source'
					: 'Sufficient',
			status: missing ? 'missing' : limited ? 'limited' : 'strong',
			source_span_id: row.source_span_id,
			result_id: row.id || null
		};
	});
}

function buildWorkbenchQaSuggestions(resultRows: WorkbenchResultRow[]): WorkbenchQaSuggestion[] {
	const firstProperty = resultRows[0]?.property || 'the main result';
	return [
		{ id: 'qa-source', text: `Where does the paper support ${firstProperty}?` },
		{ id: 'qa-baseline', text: 'Which baseline should I compare against?' },
		{ id: 'qa-limits', text: 'What context is missing or uncertain?' }
	];
}

function graphNode(
	id: string,
	label: string,
	type: WorkbenchGraphNodeType,
	position: WorkbenchGraphNodePosition,
	detail: string,
	sourceItemId: string | null,
	sourceSpanId: string | null
): WorkbenchGraphNode {
	return {
		id,
		label,
		type,
		position,
		detail,
		source_item_id: sourceItemId,
		source_span_id: sourceSpanId
	};
}

function buildWorkbenchGraphForItem(
	item: WorkbenchSelectableItem,
	resultRows: WorkbenchResultRow[],
	methodRows: WorkbenchMethodRow[]
): WorkbenchLocalGraph {
	const result =
		resultRows.find((row) => row.id === item.id || row.evidence_id === item.id) ?? resultRows[0];
	const method = methodRows[0];
	const material = result?.material_system || 'Material system';
	const property = result?.property || item.title;
	const sourceSpanId = item.source_span_id;
	const graphId = `graph-${item.id}`;
	const nodes = [
		graphNode(
			`${graphId}-center`,
			item.title,
			item.kind === 'result' ? 'result' : item.kind === 'method' ? 'method' : 'concept',
			'center',
			item.title,
			item.id,
			sourceSpanId
		),
		graphNode(
			`${graphId}-task`,
			'Understand claim',
			'task',
			'top',
			'Current local context focuses on one selected claim, result, or paragraph.',
			null,
			sourceSpanId
		),
		graphNode(
			`${graphId}-material`,
			material,
			'material',
			'left',
			`Material or dataset context: ${material}.`,
			result?.id ?? null,
			result?.source_span_id ?? sourceSpanId
		),
		graphNode(
			`${graphId}-method`,
			method?.value || 'Method context',
			'method',
			'right',
			method?.value || 'Method context extracted from the source section.',
			null,
			method?.source_span_id ?? sourceSpanId
		),
		graphNode(
			`${graphId}-result`,
			property,
			'result',
			'bottom-left',
			result?.comparability_status || 'Structured result context.',
			result?.id ?? null,
			result?.source_span_id ?? sourceSpanId
		),
		graphNode(
			`${graphId}-source`,
			'Source paragraph',
			'concept',
			'bottom-right',
			'Jump back to the highlighted paragraph in the reader.',
			null,
			sourceSpanId
		)
	];

	return {
		id: graphId,
		title: item.title,
		focus_item_id: item.id,
		nodes,
		edges: [
			{ id: `${graphId}-edge-task`, source: nodes[0].id, target: nodes[1].id, label: 'goal' },
			{ id: `${graphId}-edge-material`, source: nodes[0].id, target: nodes[2].id, label: 'uses' },
			{ id: `${graphId}-edge-method`, source: nodes[0].id, target: nodes[3].id, label: 'uses' },
			{ id: `${graphId}-edge-result`, source: nodes[0].id, target: nodes[4].id, label: 'produces' },
			{ id: `${graphId}-edge-source`, source: nodes[0].id, target: nodes[5].id, label: 'source' }
		]
	};
}

function buildWorkbenchSelectableItems(
	summaryCards: WorkbenchSummaryCard[],
	methodRows: WorkbenchMethodRow[],
	resultRows: WorkbenchResultRow[],
	evidenceCards: WorkbenchEvidenceCard[]
): WorkbenchSelectableItem[] {
	return [
		...summaryCards.map((card) => ({
			id: card.id,
			kind: 'summary' as const,
			tab: 'summary' as const,
			title: card.title,
			source_span_id: card.source_span_id,
			graph_id: `graph-${card.id}`
		})),
		...methodRows.map((row, index) => ({
			id: `method-${index}`,
			kind: 'method' as const,
			tab: 'methods' as const,
			title: row.label,
			source_span_id: row.source_span_id,
			graph_id: `graph-method-${index}`
		})),
		...resultRows.map((row) => ({
			id: row.id,
			kind: 'result' as const,
			tab: 'results' as const,
			title: row.property,
			source_span_id: row.source_span_id,
			graph_id: `graph-${row.id}`
		})),
		...evidenceCards.map((card) => ({
			id: card.id,
			kind: 'evidence' as const,
			tab: 'evidence' as const,
			title: card.claim,
			source_span_id: card.source_span_id,
			graph_id: `graph-${card.id}`
		}))
	];
}

export function buildDocumentWorkbenchModel({
	collectionId,
	documentId,
	content,
	comparisonSemantics,
	relatedResults = []
}: {
	collectionId: string;
	documentId: string;
	content: DocumentContentResponse | null;
	comparisonSemantics: DocumentComparisonSemanticsResponse | null;
	relatedResults?: ResultListItem[];
}): DocumentWorkbenchModel {
	const hasBackendBlocks = Boolean(content?.blocks.length);
	const blocks = sortedWorkbenchBlocks(content);
	const sourceSpans = buildWorkbenchSourceSpans(documentId, blocks);
	const sourceTargetsBySpanId = Object.fromEntries(
		sourceSpans.map((span) => [span.id, span.target])
	);
	const pages = buildWorkbenchPages(blocks, sourceSpans, !hasBackendBlocks);
	const contexts = flattenWorkbenchChains(comparisonSemantics?.variant_dossiers);
	const resultRows = buildWorkbenchResultRows(collectionId, contexts, relatedResults, sourceSpans);
	const summaryCards = buildWorkbenchSummaryCards(contexts, resultRows, sourceSpans);
	const methodRows = buildWorkbenchMethodRows(contexts, resultRows, sourceSpans);
	const keyResults = buildWorkbenchKeyResults(contexts, relatedResults, resultRows, sourceSpans);
	const evidenceCards = buildWorkbenchEvidenceCards(resultRows);
	const qaSuggestions = buildWorkbenchQaSuggestions(resultRows);
	const selectableItems = buildWorkbenchSelectableItems(
		summaryCards,
		methodRows,
		resultRows,
		evidenceCards
	);
	const defaultItem = selectableItems[0];
	const graphsByItemId: Record<string, WorkbenchLocalGraph> = {};

	for (const item of selectableItems) {
		graphsByItemId[item.id] = buildWorkbenchGraphForItem(item, resultRows, methodRows);
	}

	return {
		collection_id: collectionId,
		document_id: content?.document_id || documentId,
		title:
			toOptionalText(content?.title) ||
			toOptionalText(content?.source_filename) ||
			'Graph Prompting for Low-Resource Knowledge Graph Completion',
		source_filename:
			toOptionalText(content?.source_filename) || (content ? null : 'fixture-paper.txt'),
		sourceFileUrl: buildDocumentSourceFileUrl(collectionId, content?.document_id || documentId),
		metadata: [
			'Wang et al.',
			'Tsinghua University',
			'2023',
			'International Journal of Machine Tools and Manufacture'
		],
		pages,
		source_spans: sourceSpans,
		source_targets_by_span_id: sourceTargetsBySpanId,
		summary_cards: summaryCards,
		method_rows: methodRows,
		key_results: keyResults,
		result_rows: resultRows,
		evidence_cards: evidenceCards,
		qa_suggestions: qaSuggestions,
		selectable_items: selectableItems,
		graphs_by_item_id: graphsByItemId,
		default_item_id: defaultItem?.id ?? ''
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
			confidence: 0.88,
			page_count: 12,
			updated_at: '2026-04-25T12:41:00Z',
			processing_status: 'completed'
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
			confidence: 0.93,
			page_count: 18,
			updated_at: '2026-04-25T12:41:00Z',
			processing_status: 'completed'
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
			confidence: 0.64,
			page_count: null,
			updated_at: '2026-04-25T12:41:00Z',
			processing_status: 'completed'
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
				method: 0,
				computational: 0,
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

function buildComparisonSemanticsFixture(
	collectionId: string,
	documentId: string
): DocumentComparisonSemanticsResponse {
	return {
		collection_id: collectionId,
		document_id: documentId,
		total: 1,
		count: 1,
		items: [],
		variant_dossiers: [
			{
				variant_id: 'fixture_variant',
				variant_label: 'Reduced sample',
				material: {
					label: 'High-entropy oxide',
					composition: null,
					host_material_system: null
				},
				shared_process_state: {
					process: 'reduced oxygen anneal'
				},
				shared_missingness: [],
				series: [
					{
						series_key: 'cycle retention:test_condition',
						property_family: 'cycle retention',
						test_family: 'electrochemical cycling',
						varying_axis: {
							axis_name: 'cycle count',
							axis_unit: null
						},
						chains: [
							{
								result_id: 'cres_1',
								source_result_id: 'mr_fixture_1',
								measurement: {
									property: 'cycle retention',
									value: 92,
									unit: '%',
									result_type: 'scalar',
									summary: 'Retained 92% capacity after 200 cycles.',
									statistic_type: null,
									uncertainty: null
								},
								test_condition: {
									test_method: 'cycling',
									test_temperature_c: null,
									strain_rate_s_1: null,
									loading_direction: null,
									sample_orientation: null,
									environment: null,
									frequency_hz: null,
									specimen_geometry: null,
									surface_state: null
								},
								baseline: {
									label: 'air annealed control',
									reference: 'air annealed control',
									baseline_type: 'same-document',
									resolved: true
								},
								assessment: {
									comparability_status: 'comparable',
									warnings: [],
									basis: ['fixture'],
									missing_context: [],
									requires_expert_review: false,
									assessment_epistemic_status: 'grounded'
								},
								value_provenance: {
									value_origin: 'reported',
									source_value_text: '92',
									source_unit_text: '%',
									derivation_formula: null,
									derivation_inputs: null
								},
								evidence: {
									evidence_ids: ['ev_cres_1'],
									direct_anchor_ids: ['anc_cres_1'],
									contextual_anchor_ids: [],
									structure_feature_ids: [],
									characterization_observation_ids: [],
									traceability_status: 'direct'
								}
							}
						]
					}
				]
			}
		]
	};
}

function normalizeResponse(value: unknown, collectionId: string): DocumentProfilesResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Document profiles response is invalid.');
	}

	const items = Array.isArray(record.items)
		? record.items
				.map((item) => normalizeProfile(item, collectionId))
				.filter((item): item is DocumentProfile => item !== null)
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
				...((summaryRecord?.protocol_extractable_counts ??
					summaryRecord?.by_protocol_extractable) as
					| Record<ProtocolExtractable, number>
					| undefined)
			},
			warnings: toStringList(summaryRecord?.warnings)
		},
		items
	};
}

export async function fetchDocumentProfiles(
	collectionId: string
): Promise<DocumentProfilesResponse> {
	if (USE_API_FIXTURES) {
		return buildFixture(collectionId);
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/profiles`,
		{
			method: 'GET'
		}
	);
	return normalizeResponse(data, collectionId);
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

	const contentText = String(record.content_text ?? '').trim();
	const blocks = Array.isArray(record.blocks)
		? record.blocks
				.map((item, index) => normalizeContentBlock(item, index))
				.filter((item): item is DocumentContentBlock => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		document_id: String(record.document_id ?? documentId).trim() || documentId,
		title: toOptionalText(record.title),
		source_filename: toOptionalText(record.source_filename),
		content_text: contentText,
		blocks,
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
			blocks: [
				{
					block_id: 'methods',
					block_type: 'methods',
					heading_path: 'Experimental Section',
					heading_level: 1,
					order: 1,
					text: 'The precursor powders were mixed in ethanol and stirred for 2 h.',
					text_unit_ids: ['tu-1'],
					start_offset: 21,
					end_offset: 84,
					page: 3,
					bbox: null,
					charRange: { start: 21, end: 84 }
				},
				{
					block_id: 'characterization',
					block_type: 'characterization',
					heading_path: 'Characterization',
					heading_level: 1,
					order: 2,
					text: 'XRD and SEM were used to characterize the powders.',
					text_unit_ids: ['tu-2'],
					start_offset: 102,
					end_offset: 153,
					page: null,
					bbox: null,
					charRange: null
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

export async function fetchDocumentProfile(
	collectionId: string,
	documentId: string
): Promise<DocumentProfile> {
	if (USE_API_FIXTURES) {
		const fixture = buildFixture(collectionId).items.find(
			(item) => item.document_id === documentId
		);
		if (fixture) {
			return fixture;
		}
		throw new Error('Document profile fixture is missing.');
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/profile`,
		{
			method: 'GET'
		}
	);
	const profile = normalizeProfile(data, collectionId);
	if (!profile) {
		throw new Error('Document profile response is invalid.');
	}
	return profile;
}

export async function fetchDocumentComparisonSemantics(
	collectionId: string,
	documentId: string,
	options: DocumentComparisonSemanticsOptions = {}
): Promise<DocumentComparisonSemanticsResponse> {
	if (USE_API_FIXTURES) {
		return buildComparisonSemanticsFixture(collectionId, documentId);
	}

	const params = new URLSearchParams();
	if (options.includeGroupedProjections) {
		params.set('include_grouped_projections', 'true');
	}
	const query = params.toString();
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/comparison-semantics${
			query ? `?${query}` : ''
		}`,
		{
			method: 'GET'
		}
	);
	return normalizeDocumentComparisonSemantics(data, collectionId, documentId);
}
