import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type ComparabilityStatus = 'comparable' | 'limited' | 'not_comparable' | 'insufficient';
export type ResultAvailabilityStatus = 'comparable' | 'limited' | 'insufficient' | 'unavailable';
export type ResultTraceabilityStatus = 'direct' | 'indirect' | 'none';
export type ResultTone = 'brand' | 'success' | 'warning' | 'danger' | 'neutral' | 'info';
export type ResultSpecifiedFilter = '' | 'specified' | 'unspecified';
export type ResultSortMode = 'confidence_desc' | 'context_completeness' | 'traceability' | 'recent';
export type ResultFieldType =
	| 'material'
	| 'process'
	| 'baseline'
	| 'test_condition'
	| 'property'
	| 'result'
	| 'traceability'
	| 'availability'
	| 'missing_context'
	| 'generic';

export type ResultValueLabels = Partial<Record<ResultFieldType, string>>;

export type ResultFilters = {
	search: string;
	availability: '' | ResultAvailabilityStatus;
	material: string;
	property: string;
	testCondition: ResultSpecifiedFilter;
	traceability: '' | ResultTraceabilityStatus;
};

export type ResultBadge = {
	key: string;
	labelKey: string;
	fallbackLabel: string;
	tone: ResultTone;
	icon: string;
};

export type ResultMissingContextChip = {
	key:
		| 'material_system'
		| 'process'
		| 'baseline'
		| 'test_condition'
		| 'unit_context'
		| 'experimental_explanation';
	labelKey: string;
	fallbackLabel: string;
	tone: 'warning' | 'neutral';
};

export type ResultActionKey =
	| 'view_source'
	| 'open_comparison'
	| 'open_comparison_review'
	| 'view_missing_context'
	| 'view_reason'
	| 'mark_issue';

export type ResultAction = {
	key: ResultActionKey;
	labelKey: string;
	tone: 'primary' | 'ghost' | 'danger';
};

export type ResultsQualitySummaryItem = {
	key: 'total' | 'traceable' | 'insufficientContext' | 'comparable' | 'needsReview';
	labelKey: string;
	value: number;
	tone: ResultTone;
	icon: string;
};

export type ResultsQualitySummary = {
	total: number;
	traceable: number;
	insufficientContext: number;
	comparable: number;
	needsReview: number;
	items: ResultsQualitySummaryItem[];
};

export type ResultsConclusionActionKey = 'view_insufficient' | 'open_comparison' | 'view_all';

export type ResultsConclusion = {
	tone: 'warning' | 'success' | 'info';
	titleKey: string;
	bodyKey: string;
	actionKeys: ResultsConclusionActionKey[];
};

export type ResultSourceQuote = {
	text: string;
	citation: string | null;
};

export type ResultContextDisplay = {
	materialSystem: string;
	property: string;
	process: string;
	baseline: string;
	testCondition: string;
};

export type ResultListItem = {
	result_id: string;
	document_id: string;
	document_title: string;
	material_label: string;
	variant_label: string | null;
	property: string;
	value: number | null;
	unit: string | null;
	summary: string;
	baseline: string | null;
	test_condition: string | null;
	process: string | null;
	traceability_status: string;
	comparability_status: ComparabilityStatus;
	requires_expert_review: boolean;
	confidence: number | null;
	result_type: string | null;
	source_evidence_quote: string | null;
	source_type: string | null;
	source_section: string | null;
	source_location: string | null;
	evidence_ids: string[];
	anchor_ids: string[];
	missing_context: string[];
	warnings: string[];
	created_at: string | null;
	updated_at: string | null;
};

export type ResultListResponse = {
	collection_id: string;
	total: number;
	count: number;
	items: ResultListItem[];
};

export type ResultDocument = {
	document_id: string;
	title: string;
	source_filename: string | null;
};

export type ResultMaterial = {
	label: string;
	variant_id: string | null;
	variant_label: string | null;
};

export type ResultMeasurement = {
	property: string;
	value: number | null;
	unit: string | null;
	result_type: string;
	summary: string;
	statistic_type: string | null;
	uncertainty: string | null;
};

export type ResultContext = {
	process: string | null;
	baseline: string | null;
	baseline_reference: string | null;
	test_condition: string | null;
	axis_name: string | null;
	axis_value: string | number | null;
	axis_unit: string | null;
};

export type ResultAssessment = {
	comparability_status: ComparabilityStatus;
	warnings: string[];
	basis: string[];
	missing_context: string[];
	requires_expert_review: boolean;
	assessment_epistemic_status: string;
};

export type ResultEvidenceItem = {
	evidence_id: string;
	traceability_status: string;
	source_type: string | null;
	anchor_ids: string[];
};

export type EvidenceChainMaterial = {
	label: string;
	composition: string | null;
	host_material_system: Record<string, unknown> | null;
};

export type VariantDossierSummary = {
	variant_id: string | null;
	variant_label: string | null;
	material: EvidenceChainMaterial;
	shared_process_state: Record<string, unknown>;
	shared_missingness: string[];
};

export type TestConditionDetail = {
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

export type BaselineDetail = {
	label: string | null;
	reference: string | null;
	baseline_type: string | null;
	resolved: boolean;
	baseline_scope: string | null;
};

export type StructureSupport = {
	support_id: string;
	support_type: string;
	summary: string;
	condition: Record<string, unknown>;
};

export type ValueProvenance = {
	value_origin: string;
	source_value_text: string | null;
	source_unit_text: string | null;
	derivation_formula: string | null;
	derivation_inputs: Record<string, unknown> | null;
};

export type SeriesSibling = {
	result_id: string;
	axis_value: string | number | null;
	axis_unit: string | null;
	measurement: {
		property: string;
		value: number | null;
		unit: string | null;
	};
};

export type SeriesNavigation = {
	series_key: string;
	varying_axis: {
		axis_name: string | null;
		axis_unit: string | null;
	};
	siblings: SeriesSibling[];
};

export type ResultActions = {
	open_document: string | null;
	open_comparisons: string | null;
	open_evidence: string | null;
};

export type ResultDetail = {
	result_id: string;
	document: ResultDocument;
	material: ResultMaterial;
	measurement: ResultMeasurement;
	context: ResultContext;
	assessment: ResultAssessment;
	evidence: ResultEvidenceItem[];
	actions: ResultActions;
	variant_dossier: VariantDossierSummary | null;
	test_condition_detail: TestConditionDetail | null;
	baseline_detail: BaselineDetail | null;
	structure_support: StructureSupport[];
	value_provenance: ValueProvenance | null;
	series_navigation: SeriesNavigation | null;
};

export type ResultsQuery = {
	limit?: number;
	offset?: number;
	material_system_normalized?: string;
	property_normalized?: string;
	test_condition_normalized?: string;
	baseline_normalized?: string;
	comparability_status?: string;
	source_document_id?: string;
};

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function toOptionalText(value: unknown): string | null {
	if (typeof value !== 'string') return null;
	const text = value.trim();
	return text || null;
}

function toNumber(value: unknown): number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim() !== '') {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}
	return null;
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

function toBoolean(value: unknown): boolean {
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
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	return toOptionalText(value);
}

function normalizeComparabilityStatus(value: unknown): ComparabilityStatus {
	const status = String(value ?? '').trim();
	return ['comparable', 'limited', 'not_comparable', 'insufficient'].includes(status)
		? (status as ComparabilityStatus)
		: 'insufficient';
}

function normalizeListItem(value: unknown): ResultListItem | null {
	const record = asRecord(value);
	if (!record) return null;

	const result_id = String(record.result_id ?? record.comparable_result_id ?? '').trim();
	if (!result_id) return null;
	const documentRecord = asRecord(record.document);
	const displayRecord = asRecord(record.display);
	const valueRecord = asRecord(record.value);
	const contextRecord = asRecord(record.normalized_context) ?? asRecord(record.context);
	const assessmentRecord = asRecord(record.assessment);
	const evidenceRecord = asRecord(record.evidence) ?? asRecord(record.evidence_bundle);
	const provenanceRecord = asRecord(record.value_provenance);
	const evidenceIds = toStringList(
		record.evidence_ids ?? evidenceRecord?.evidence_ids ?? evidenceRecord?.supporting_evidence_ids
	);
	const directAnchorIds = toStringList(
		record.anchor_ids ?? evidenceRecord?.direct_anchor_ids ?? evidenceRecord?.supporting_anchor_ids
	);
	const contextualAnchorIds = toStringList(evidenceRecord?.contextual_anchor_ids);
	const anchorIds = [...directAnchorIds, ...contextualAnchorIds];

	return {
		result_id,
		document_id: String(
			record.document_id ?? record.source_document_id ?? documentRecord?.document_id ?? ''
		).trim(),
		document_title: String(
			record.document_title ??
				record.document_name ??
				documentRecord?.title ??
				documentRecord?.document_title ??
				record.document_id ??
				result_id
		).trim(),
		material_label:
			String(
				record.material_label ??
					contextRecord?.material_system_normalized ??
					displayRecord?.material_system_normalized ??
					'--'
			).trim() || '--',
		variant_label: toOptionalText(
			record.variant_label ?? record.variant_name ?? displayRecord?.variant_label
		),
		property:
			String(
				record.property ??
					valueRecord?.property_normalized ??
					displayRecord?.property_normalized ??
					'--'
			).trim() || '--',
		value: toNumber(record.value ?? valueRecord?.numeric_value ?? displayRecord?.value),
		unit: toOptionalText(record.unit ?? valueRecord?.unit ?? displayRecord?.unit),
		summary:
			String(
				record.summary ??
					valueRecord?.summary ??
					record.result_summary ??
					displayRecord?.result_summary ??
					'--'
			).trim() || '--',
		baseline: toOptionalText(
			record.baseline ??
				record.baseline_reference ??
				contextRecord?.baseline_normalized ??
				displayRecord?.baseline_normalized ??
				displayRecord?.baseline_reference
		),
		test_condition: toOptionalText(
			record.test_condition ??
				contextRecord?.test_condition_normalized ??
				displayRecord?.test_condition_normalized
		),
		process: toOptionalText(
			record.process ?? contextRecord?.process_normalized ?? displayRecord?.process_normalized
		),
		traceability_status:
			String(
				record.traceability_status ?? evidenceRecord?.traceability_status ?? 'missing'
			).trim() || 'missing',
		comparability_status: normalizeComparabilityStatus(
			record.comparability_status ?? assessmentRecord?.comparability_status
		),
		requires_expert_review: toBoolean(
			record.requires_expert_review ?? assessmentRecord?.requires_expert_review
		),
		confidence: toNumber(
			record.confidence ??
				record.confidence_score ??
				assessmentRecord?.confidence ??
				assessmentRecord?.confidence_score
		),
		result_type: toOptionalText(
			record.result_type ?? valueRecord?.result_type ?? displayRecord?.result_type
		),
		source_evidence_quote: toOptionalText(
			record.source_evidence_quote ??
				record.evidence_quote ??
				record.source_quote ??
				record.quote ??
				record.quote_span ??
				provenanceRecord?.source_value_text
		),
		source_type: toOptionalText(
			record.source_type ?? record.result_source_type ?? evidenceRecord?.result_source_type
		),
		source_section: toOptionalText(
			record.source_section ?? record.section ?? record.section_title ?? record.heading_path
		),
		source_location: toOptionalText(
			record.source_location ?? record.location ?? record.source_anchor_label ?? record.anchor_label
		),
		evidence_ids: evidenceIds,
		anchor_ids: anchorIds,
		missing_context: toStringList(
			record.missing_context ??
				record.missing_critical_context ??
				assessmentRecord?.missing_context ??
				assessmentRecord?.missing_critical_context
		),
		warnings: toStringList(record.warnings ?? assessmentRecord?.warnings),
		created_at: toOptionalText(record.created_at ?? record.generated_at),
		updated_at: toOptionalText(record.updated_at ?? record.modified_at)
	};
}

function normalizeDocument(value: unknown, fallbackResultId: string): ResultDocument {
	const record = asRecord(value);
	return {
		document_id: String(record?.document_id ?? '').trim(),
		title:
			String(
				record?.title ?? record?.document_title ?? record?.document_id ?? fallbackResultId
			).trim() || fallbackResultId,
		source_filename: toOptionalText(record?.source_filename)
	};
}

function normalizeMaterial(value: unknown): ResultMaterial {
	const record = asRecord(value);
	return {
		label: String(record?.label ?? '--').trim() || '--',
		variant_id: toOptionalText(record?.variant_id),
		variant_label: toOptionalText(record?.variant_label)
	};
}

function normalizeMeasurement(value: unknown): ResultMeasurement {
	const record = asRecord(value);
	return {
		property: String(record?.property ?? '--').trim() || '--',
		value: toNumber(record?.value),
		unit: toOptionalText(record?.unit),
		result_type: String(record?.result_type ?? 'scalar').trim() || 'scalar',
		summary: String(record?.summary ?? '--').trim() || '--',
		statistic_type: toOptionalText(record?.statistic_type),
		uncertainty: toOptionalText(record?.uncertainty)
	};
}

function normalizeContext(value: unknown): ResultContext {
	const record = asRecord(value);
	return {
		process: toOptionalText(record?.process),
		baseline: toOptionalText(record?.baseline),
		baseline_reference: toOptionalText(record?.baseline_reference),
		test_condition: toOptionalText(record?.test_condition),
		axis_name: toOptionalText(record?.axis_name),
		axis_value: toScalarOrText(record?.axis_value),
		axis_unit: toOptionalText(record?.axis_unit)
	};
}

function normalizeAssessment(value: unknown): ResultAssessment {
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

function normalizeEvidenceItem(value: unknown): ResultEvidenceItem | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidence_id = String(record.evidence_id ?? '').trim();
	if (!evidence_id) return null;

	return {
		evidence_id,
		traceability_status: String(record.traceability_status ?? 'missing').trim() || 'missing',
		source_type: toOptionalText(record.source_type),
		anchor_ids: toStringList(record.anchor_ids)
	};
}

function normalizeEvidenceChainMaterial(value: unknown): EvidenceChainMaterial {
	const record = asRecord(value);
	return {
		label: String(record?.label ?? '--').trim() || '--',
		composition: toOptionalText(record?.composition),
		host_material_system: asRecord(record?.host_material_system)
	};
}

function normalizeVariantDossierSummary(value: unknown): VariantDossierSummary | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		variant_id: toOptionalText(record.variant_id),
		variant_label: toOptionalText(record.variant_label),
		material: normalizeEvidenceChainMaterial(record.material),
		shared_process_state: asRecord(record.shared_process_state) ?? {},
		shared_missingness: toStringList(record.shared_missingness)
	};
}

function normalizeTestConditionDetail(value: unknown): TestConditionDetail | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		test_method: toOptionalText(record.test_method),
		test_temperature_c: toNumber(record.test_temperature_c),
		strain_rate_s_1: toScalarOrText(record['strain_rate_s-1'] ?? record.strain_rate_s_1),
		loading_direction: toOptionalText(record.loading_direction),
		sample_orientation: toOptionalText(record.sample_orientation),
		environment: toOptionalText(record.environment),
		frequency_hz: toNumber(record.frequency_hz),
		specimen_geometry: toOptionalText(record.specimen_geometry),
		surface_state: toOptionalText(record.surface_state)
	};
}

function normalizeBaselineDetail(value: unknown): BaselineDetail | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		label: toOptionalText(record.label),
		reference: toOptionalText(record.reference),
		baseline_type: toOptionalText(record.baseline_type),
		resolved: toBoolean(record.resolved),
		baseline_scope: toOptionalText(record.baseline_scope)
	};
}

function normalizeStructureSupport(value: unknown): StructureSupport | null {
	const record = asRecord(value);
	if (!record) return null;

	const support_id = String(record.support_id ?? '').trim();
	if (!support_id) return null;

	return {
		support_id,
		support_type: String(record.support_type ?? 'unknown').trim() || 'unknown',
		summary: String(record.summary ?? '--').trim() || '--',
		condition: asRecord(record.condition) ?? {}
	};
}

function normalizeValueProvenance(value: unknown): ValueProvenance | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		value_origin: String(record.value_origin ?? 'unknown').trim() || 'unknown',
		source_value_text: toOptionalText(record.source_value_text),
		source_unit_text: toOptionalText(record.source_unit_text),
		derivation_formula: toOptionalText(record.derivation_formula),
		derivation_inputs: asRecord(record.derivation_inputs)
	};
}

function normalizeSeriesSibling(value: unknown): SeriesSibling | null {
	const record = asRecord(value);
	if (!record) return null;

	const result_id = String(record.result_id ?? '').trim();
	if (!result_id) return null;

	const measurementRecord = asRecord(record.measurement);

	return {
		result_id,
		axis_value: toScalarOrText(record.axis_value),
		axis_unit: toOptionalText(record.axis_unit),
		measurement: {
			property: String(measurementRecord?.property ?? '--').trim() || '--',
			value: toNumber(measurementRecord?.value),
			unit: toOptionalText(measurementRecord?.unit)
		}
	};
}

function normalizeSeriesNavigation(value: unknown): SeriesNavigation | null {
	const record = asRecord(value);
	if (!record) return null;

	const axisRecord = asRecord(record.varying_axis);

	return {
		series_key: String(record.series_key ?? '').trim(),
		varying_axis: {
			axis_name: toOptionalText(axisRecord?.axis_name),
			axis_unit: toOptionalText(axisRecord?.axis_unit)
		},
		siblings: Array.isArray(record.siblings)
			? record.siblings
					.map((item) => normalizeSeriesSibling(item))
					.filter((item): item is SeriesSibling => item !== null)
			: []
	};
}

function normalizeActions(
	value: unknown,
	collectionId: string,
	fallbackDocumentId: string
): ResultActions {
	const record = asRecord(value);
	return {
		open_document:
			toOptionalText(record?.open_document) ||
			`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(fallbackDocumentId)}`,
		open_comparisons: toOptionalText(record?.open_comparisons),
		open_evidence: toOptionalText(record?.open_evidence)
	};
}

function normalizeListResponse(value: unknown, collectionId: string): ResultListResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Results response is invalid.');
	}

	const items = Array.isArray(record.items)
		? record.items
				.map((item) => normalizeListItem(item))
				.filter((item): item is ResultListItem => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		total: typeof record.total === 'number' ? record.total : items.length,
		count: typeof record.count === 'number' ? record.count : items.length,
		items
	};
}

function normalizeDetail(value: unknown, collectionId: string, resultId: string): ResultDetail {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Result detail response is invalid.');
	}

	const document = normalizeDocument(record.document, resultId);

	return {
		result_id: String(record.result_id ?? resultId).trim() || resultId,
		document,
		material: normalizeMaterial(record.material),
		measurement: normalizeMeasurement(record.measurement),
		context: normalizeContext(record.context),
		assessment: normalizeAssessment(record.assessment),
		evidence: Array.isArray(record.evidence)
			? record.evidence
					.map((item) => normalizeEvidenceItem(item))
					.filter((item): item is ResultEvidenceItem => item !== null)
			: [],
		actions: normalizeActions(record.actions, collectionId, document.document_id),
		variant_dossier: normalizeVariantDossierSummary(record.variant_dossier),
		test_condition_detail: normalizeTestConditionDetail(record.test_condition_detail),
		baseline_detail: normalizeBaselineDetail(record.baseline_detail),
		structure_support: Array.isArray(record.structure_support)
			? record.structure_support
					.map((item) => normalizeStructureSupport(item))
					.filter((item): item is StructureSupport => item !== null)
			: [],
		value_provenance: normalizeValueProvenance(record.value_provenance),
		series_navigation: normalizeSeriesNavigation(record.series_navigation)
	};
}

function buildFixtureList(collectionId: string): ResultListResponse {
	const items: ResultListItem[] = [
		{
			result_id: 'cres_1',
			document_id: 'doc_a',
			document_title: 'High-entropy oxide cycling study',
			material_label: 'High-entropy oxide',
			variant_label: 'Reduced sample',
			property: 'cycle retention',
			value: 92,
			unit: '%',
			summary: 'Retained 92% capacity after 200 cycles.',
			baseline: 'air annealed control',
			test_condition: '200 cycles at 1C',
			process: 'reduced oxygen anneal',
			traceability_status: 'direct',
			comparability_status: 'comparable',
			requires_expert_review: false,
			confidence: 0.9,
			result_type: 'result',
			source_evidence_quote: 'Retained 92% capacity after 200 cycles.',
			source_type: 'table',
			source_section: 'Results',
			source_location: 'Table 2',
			evidence_ids: ['ev_cres_1'],
			anchor_ids: ['anc_cres_1'],
			missing_context: [],
			warnings: [],
			created_at: '2026-04-25T04:30:00Z',
			updated_at: '2026-04-25T04:41:00Z'
		},
		{
			result_id: 'cres_2',
			document_id: 'doc_c',
			document_title: 'Carbon coating benchmark',
			material_label: 'Layered oxide',
			variant_label: '2 wt% coating',
			property: 'impedance',
			value: null,
			unit: null,
			summary: 'Impedance improved, but baseline alignment is incomplete.',
			baseline: 'untreated reference',
			test_condition: 'EIS after 50 cycles',
			process: 'carbon coating',
			traceability_status: 'partial',
			comparability_status: 'limited',
			requires_expert_review: true,
			confidence: 0.86,
			result_type: 'result',
			source_evidence_quote: 'Impedance improved, but baseline alignment is incomplete.',
			source_type: 'text',
			source_section: 'Results',
			source_location: 'Results paragraph 4',
			evidence_ids: ['ev_cres_2'],
			anchor_ids: ['anc_cres_2'],
			missing_context: ['baseline_reference'],
			warnings: ['Baseline alignment is incomplete.'],
			created_at: '2026-04-25T04:31:00Z',
			updated_at: '2026-04-25T04:42:00Z'
		}
	];

	return {
		collection_id: collectionId,
		total: items.length,
		count: items.length,
		items
	};
}

function filterFixtureItems(items: ResultListItem[], query: ResultsQuery) {
	return items.filter((item) => {
		if (
			query.material_system_normalized &&
			item.material_label !== query.material_system_normalized
		) {
			return false;
		}
		if (query.property_normalized && item.property !== query.property_normalized) {
			return false;
		}
		if (
			query.test_condition_normalized &&
			item.test_condition !== query.test_condition_normalized
		) {
			return false;
		}
		if (query.baseline_normalized && item.baseline !== query.baseline_normalized) {
			return false;
		}
		if (query.comparability_status && item.comparability_status !== query.comparability_status) {
			return false;
		}
		if (query.source_document_id && item.document_id !== query.source_document_id) {
			return false;
		}
		return true;
	});
}

function buildFixtureDetail(collectionId: string, resultId: string): ResultDetail {
	const listItem =
		buildFixtureList(collectionId).items.find((item) => item.result_id === resultId) ??
		buildFixtureList(collectionId).items[0];
	return {
		result_id: listItem.result_id,
		document: {
			document_id: listItem.document_id,
			title: listItem.document_title,
			source_filename: `${listItem.document_id}.pdf`
		},
		material: {
			label: listItem.material_label,
			variant_id: `var_${listItem.result_id}`,
			variant_label: listItem.variant_label
		},
		measurement: {
			property: listItem.property,
			value: listItem.value,
			unit: listItem.unit,
			result_type: 'scalar',
			summary: listItem.summary,
			statistic_type: null,
			uncertainty: null
		},
		context: {
			process: listItem.process,
			baseline: listItem.baseline,
			baseline_reference: listItem.baseline,
			test_condition: listItem.test_condition,
			axis_name: null,
			axis_value: null,
			axis_unit: null
		},
		assessment: {
			comparability_status: listItem.comparability_status,
			warnings:
				listItem.comparability_status === 'limited' ? ['Baseline alignment is incomplete.'] : [],
			basis: ['collection overlay'],
			missing_context: listItem.comparability_status === 'limited' ? ['baseline_reference'] : [],
			requires_expert_review: listItem.requires_expert_review,
			assessment_epistemic_status: 'grounded'
		},
		evidence: [
			{
				evidence_id: `ev_${listItem.result_id}`,
				traceability_status: listItem.traceability_status,
				source_type: 'text',
				anchor_ids: [`anc_${listItem.result_id}`]
			}
		],
		actions: {
			open_document: `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(listItem.document_id)}`,
			open_comparisons: `/collections/${encodeURIComponent(collectionId)}/comparisons?property_normalized=${encodeURIComponent(listItem.property)}`,
			open_evidence: null
		},
		variant_dossier: {
			variant_id: `var_${listItem.result_id}`,
			variant_label: listItem.variant_label,
			material: {
				label: listItem.material_label,
				composition: null,
				host_material_system: null
			},
			shared_process_state: listItem.process ? { process: listItem.process } : {},
			shared_missingness: []
		},
		test_condition_detail: {
			test_method: listItem.test_condition,
			test_temperature_c: null,
			strain_rate_s_1: null,
			loading_direction: null,
			sample_orientation: null,
			environment: null,
			frequency_hz: null,
			specimen_geometry: null,
			surface_state: null
		},
		baseline_detail: {
			label: listItem.baseline,
			reference: listItem.baseline,
			baseline_type: 'fixture',
			resolved: Boolean(listItem.baseline),
			baseline_scope: 'same fixture'
		},
		structure_support: [],
		value_provenance: {
			value_origin: 'reported',
			source_value_text: listItem.value === null ? null : String(listItem.value),
			source_unit_text: listItem.unit,
			derivation_formula: null,
			derivation_inputs: null
		},
		series_navigation: null
	};
}

function buildQueryString(query: ResultsQuery = {}) {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(query)) {
		if (value !== undefined && value !== null && String(value).trim() !== '') {
			params.set(key, String(value));
		}
	}
	const text = params.toString();
	return text ? `?${text}` : '';
}

function clampPercent(value: number) {
	return Math.max(0, Math.min(100, Math.round(value)));
}

function usefulText(value?: string | number | null) {
	const text = String(value ?? '').trim();
	if (!text || text === '--') return '';
	return text;
}

function normalizeMachineText(value: string) {
	return value.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function sentenceCase(value: string) {
	const normalized = normalizeMachineText(value);
	if (!normalized) return '';
	const lower = normalized.toLowerCase();
	const restored = lower
		.replace(/\blaves\b/g, 'Laves')
		.replace(/\bhaz\b/g, 'HAZ')
		.replace(/\blpbf\b/g, 'LPBF')
		.replace(/\beis\b/g, 'EIS')
		.replace(/\bsem\b/g, 'SEM')
		.replace(/\btem\b/g, 'TEM')
		.replace(/\bni\b/g, 'Ni');
	return `${restored.charAt(0).toUpperCase()}${restored.slice(1)}`;
}

function isMissingResultValue(
	value: string | number | null | undefined,
	fieldType: ResultFieldType
) {
	const normalized = String(value ?? '')
		.trim()
		.toLowerCase();
	if (!normalized || normalized === '--' || normalized === 'null' || normalized === 'undefined') {
		return true;
	}
	if (['n/a', 'na', 'unknown', 'none', 'missing'].includes(normalized)) return true;
	if (normalized.startsWith('unspecified')) return true;
	if (normalized.includes('not specified')) return true;
	if (fieldType === 'baseline' && normalized.includes('no single experimental baseline')) {
		return true;
	}
	return false;
}

function specifiedResultValue(
	value: string | number | null | undefined,
	fieldType: ResultFieldType
) {
	return !isMissingResultValue(value, fieldType);
}

function missingValueLabel(fieldType: ResultFieldType, labels: ResultValueLabels = {}) {
	if (labels[fieldType]) return labels[fieldType];
	if (fieldType === 'material') return 'Unspecified material system';
	if (fieldType === 'process') return 'Unspecified treatment';
	if (fieldType === 'baseline') return 'Unspecified baseline';
	if (fieldType === 'test_condition') return 'Unspecified test condition';
	return labels.generic ?? 'Unspecified';
}

function normalizedConfidenceValue(confidence?: number | null) {
	if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return null;
	if (confidence <= 1) return Math.max(0, Math.min(1, confidence));
	return Math.max(0, Math.min(1, confidence / 100));
}

function inferredConfidenceValue(result: ResultListItem) {
	const normalized = normalizedConfidenceValue(result.confidence);
	if (normalized !== null) return normalized;

	if (result.comparability_status === 'comparable' && getTraceabilityStatus(result) === 'direct') {
		return 0.9;
	}
	if (result.comparability_status === 'limited') return 0.84;
	if (result.comparability_status === 'not_comparable') return 0.58;
	if (result.requires_expert_review) return 0.76;
	return 0.8;
}

function fieldMentions(values: string[], needles: string[]) {
	const haystack = values.map((value) => normalizeMachineText(value).toLowerCase()).join(' ');
	return needles.some((needle) => haystack.includes(needle));
}

function addUnique<T>(items: T[], item: T) {
	if (!items.includes(item)) items.push(item);
}

function missingContextKeys(result: ResultListItem) {
	const keys: ResultMissingContextChip['key'][] = [];
	const missingValues = [...result.missing_context, ...result.warnings];

	if (
		fieldMentions(missingValues, ['material system', 'material']) ||
		!specifiedResultValue(result.material_label, 'material')
	) {
		addUnique(keys, 'material_system');
	}
	if (
		fieldMentions(missingValues, ['process', 'treatment']) ||
		!specifiedResultValue(result.process, 'process')
	) {
		addUnique(keys, 'process');
	}
	if (
		fieldMentions(missingValues, ['baseline', 'baseline reference', 'control']) ||
		!specifiedResultValue(result.baseline, 'baseline')
	) {
		addUnique(keys, 'baseline');
	}
	if (
		fieldMentions(missingValues, ['test condition', 'condition link', 'test setup']) ||
		!specifiedResultValue(result.test_condition, 'test_condition')
	) {
		addUnique(keys, 'test_condition');
	}
	if (
		fieldMentions(missingValues, ['unit', 'unit context']) ||
		(result.value !== null && !result.unit)
	) {
		addUnique(keys, 'unit_context');
	}
	if (
		result.requires_expert_review ||
		fieldMentions(missingValues, [
			'experimental explanation',
			'experiment explanation',
			'expert interpretation',
			'interpretation'
		])
	) {
		addUnique(keys, 'experimental_explanation');
	}

	return keys;
}

function statusRank(status: ResultAvailabilityStatus) {
	if (status === 'unavailable') return 0;
	if (status === 'insufficient') return 1;
	if (status === 'limited') return 2;
	return 3;
}

function traceabilityRank(status: ResultTraceabilityStatus) {
	if (status === 'none') return 0;
	if (status === 'indirect') return 1;
	return 2;
}

function sourceTypeLabel(value?: string | null) {
	const normalized = normalizeMachineText(String(value ?? '')).toLowerCase();
	if (normalized === 'figure') return '图';
	if (normalized === 'table') return '表';
	if (normalized === 'method' || normalized === 'methods') return '方法';
	return '正文';
}

export function formatResultValue(
	value: string | number | null | undefined,
	fieldType: ResultFieldType,
	labels: ResultValueLabels = {}
) {
	if (isMissingResultValue(value, fieldType)) return missingValueLabel(fieldType, labels);

	const text = usefulText(value);
	if (!text) return missingValueLabel(fieldType, labels);
	if (text.includes('_') || /^[a-z0-9 -]+$/.test(text)) return sentenceCase(text);
	return text;
}

export function formatDocumentTitle(documentId?: string | null, documentTitle?: string | null) {
	const title = usefulText(documentTitle);
	const id = usefulText(documentId);
	const looksLikeHash = /^[a-f0-9]{20,}$/i.test(id) || /^[a-z0-9]{28,}$/i.test(id);
	if (title && title !== id) return title;
	if (title && !looksLikeHash) return title;
	if (id && !looksLikeHash && !id.startsWith('doc_')) return id;
	return 'Untitled document';
}

export function getTraceabilityStatus(result: ResultListItem): ResultTraceabilityStatus {
	const normalized = normalizeMachineText(result.traceability_status).toLowerCase();
	if (normalized === 'direct' || normalized === 'ready' || normalized === 'traceable') {
		return 'direct';
	}
	if (normalized === 'indirect' || normalized === 'partial' || normalized === 'contextual') {
		return 'indirect';
	}
	if (normalized === 'none' || normalized === 'missing' || normalized === 'unavailable') {
		return 'none';
	}
	if (result.anchor_ids.length || result.evidence_ids.length) return 'direct';
	return 'none';
}

export function getResultAvailabilityStatus(result: ResultListItem): ResultAvailabilityStatus {
	const traceability = getTraceabilityStatus(result);
	const confidence = inferredConfidenceValue(result);
	const missingKeys = missingContextKeys(result);
	const hasCriticalMissingContext = missingKeys.some((key) =>
		['material_system', 'baseline', 'test_condition'].includes(key)
	);

	if (
		traceability === 'none' ||
		confidence < 0.55 ||
		result.comparability_status === 'not_comparable'
	) {
		return 'unavailable';
	}
	if (
		result.comparability_status === 'insufficient' ||
		hasCriticalMissingContext ||
		missingKeys.length >= 3
	) {
		return 'insufficient';
	}
	if (
		result.comparability_status === 'limited' ||
		missingKeys.length > 0 ||
		result.requires_expert_review ||
		traceability === 'indirect'
	) {
		return 'limited';
	}
	return 'comparable';
}

export function getResultStatusBadges(result: ResultListItem): ResultBadge[] {
	const availability = getResultAvailabilityStatus(result);
	const traceability = getTraceabilityStatus(result);
	const availabilityBadges: Record<ResultAvailabilityStatus, ResultBadge> = {
		comparable: {
			key: 'availability-comparable',
			labelKey: 'results.status.comparable',
			fallbackLabel: 'Can enter comparison',
			tone: 'success',
			icon: 'OK'
		},
		limited: {
			key: 'availability-limited',
			labelKey: 'results.status.limited',
			fallbackLabel: 'Limited',
			tone: 'warning',
			icon: '!'
		},
		insufficient: {
			key: 'availability-insufficient',
			labelKey: 'results.status.insufficient',
			fallbackLabel: 'Insufficient context',
			tone: 'warning',
			icon: '!'
		},
		unavailable: {
			key: 'availability-unavailable',
			labelKey: 'results.status.unavailable',
			fallbackLabel: 'Unavailable',
			tone: 'danger',
			icon: 'X'
		}
	};
	const traceabilityBadges: Record<ResultTraceabilityStatus, ResultBadge> = {
		direct: {
			key: 'traceability-direct',
			labelKey: 'results.traceability.direct',
			fallbackLabel: 'Directly traceable',
			tone: 'success',
			icon: 'T'
		},
		indirect: {
			key: 'traceability-indirect',
			labelKey: 'results.traceability.indirect',
			fallbackLabel: 'Indirectly traceable',
			tone: 'warning',
			icon: 'T'
		},
		none: {
			key: 'traceability-none',
			labelKey: 'results.traceability.none',
			fallbackLabel: 'Not traceable',
			tone: 'danger',
			icon: 'T'
		}
	};

	return [
		availabilityBadges[availability],
		traceabilityBadges[traceability],
		{
			key: 'confidence',
			labelKey: 'results.card.confidenceValue',
			fallbackLabel: `Confidence ${getResultConfidence(result)}%`,
			tone: 'neutral',
			icon: '%'
		}
	];
}

export function getMissingContextChips(result: ResultListItem): ResultMissingContextChip[] {
	const chips: Record<ResultMissingContextChip['key'], ResultMissingContextChip> = {
		material_system: {
			key: 'material_system',
			labelKey: 'results.missing.materialSystem',
			fallbackLabel: 'Missing material system',
			tone: 'warning'
		},
		process: {
			key: 'process',
			labelKey: 'results.missing.process',
			fallbackLabel: 'Missing treatment',
			tone: 'warning'
		},
		baseline: {
			key: 'baseline',
			labelKey: 'results.missing.baseline',
			fallbackLabel: 'Missing baseline',
			tone: 'warning'
		},
		test_condition: {
			key: 'test_condition',
			labelKey: 'results.missing.testCondition',
			fallbackLabel: 'Missing test condition',
			tone: 'warning'
		},
		unit_context: {
			key: 'unit_context',
			labelKey: 'results.missing.unitContext',
			fallbackLabel: 'Missing unit context',
			tone: 'neutral'
		},
		experimental_explanation: {
			key: 'experimental_explanation',
			labelKey: 'results.missing.experimentalExplanation',
			fallbackLabel: 'Missing experimental explanation',
			tone: 'neutral'
		}
	};
	return missingContextKeys(result).map((key) => chips[key]);
}

export function getResultActions(result: ResultListItem): ResultAction[] {
	const availability = getResultAvailabilityStatus(result);
	const traceability = getTraceabilityStatus(result);

	if (traceability === 'none' || availability === 'unavailable') {
		return [
			{ key: 'view_reason', labelKey: 'results.actions.viewReason', tone: 'ghost' },
			{ key: 'mark_issue', labelKey: 'results.actions.markIssue', tone: 'danger' }
		];
	}
	if (availability === 'comparable') {
		return [
			{ key: 'view_source', labelKey: 'results.actions.viewSource', tone: 'primary' },
			{ key: 'open_comparison', labelKey: 'results.actions.openComparison', tone: 'ghost' },
			{ key: 'mark_issue', labelKey: 'results.actions.markIssue', tone: 'danger' }
		];
	}
	return [
		{ key: 'view_source', labelKey: 'results.actions.viewSource', tone: 'primary' },
		{
			key: 'view_missing_context',
			labelKey: 'results.actions.viewMissingContext',
			tone: 'ghost'
		},
		{
			key: 'open_comparison_review',
			labelKey: 'results.actions.openComparisonReview',
			tone: 'ghost'
		},
		{ key: 'mark_issue', labelKey: 'results.actions.markIssue', tone: 'danger' }
	];
}

export function getSourceEvidenceQuote(result: ResultListItem): ResultSourceQuote {
	const text =
		usefulText(result.source_evidence_quote) ||
		usefulText(result.summary) ||
		formatResultValue(result.property, 'result');
	const citationParts = [
		formatDocumentTitle(result.document_id, result.document_title),
		getSourceLocation(result)
	].filter((item) => usefulText(item));
	return {
		text,
		citation: citationParts.join(' · ') || null
	};
}

export function getSourceLocation(result: ResultListItem) {
	const explicitLocation = usefulText(result.source_location);
	if (explicitLocation) return explicitLocation;
	const parts = [sourceTypeLabel(result.source_type), usefulText(result.source_section)].filter(
		Boolean
	);
	return parts.join(' · ') || '正文';
}

export function getResultConfidence(result: ResultListItem) {
	return clampPercent(inferredConfidenceValue(result) * 100);
}

export function getResultContext(
	result: ResultListItem,
	labels: ResultValueLabels = {}
): ResultContextDisplay {
	return {
		materialSystem: formatResultValue(result.material_label, 'material', labels),
		property: formatResultValue(result.property, 'property', labels),
		process: formatResultValue(result.process, 'process', labels),
		baseline: formatResultValue(result.baseline, 'baseline', labels),
		testCondition: formatResultValue(result.test_condition, 'test_condition', labels)
	};
}

export function buildResultsQualitySummary(results: ResultListItem[]): ResultsQualitySummary {
	const total = results.length;
	const traceable = results.filter((result) => getTraceabilityStatus(result) === 'direct').length;
	const insufficientContext = results.filter(
		(result) => getMissingContextChips(result).length
	).length;
	const comparable = results.filter(
		(result) => getResultAvailabilityStatus(result) === 'comparable'
	).length;
	const needsReview = results.filter((result) => {
		const availability = getResultAvailabilityStatus(result);
		return (
			result.requires_expert_review ||
			getTraceabilityStatus(result) === 'none' ||
			availability === 'limited' ||
			availability === 'insufficient' ||
			availability === 'unavailable'
		);
	}).length;

	return {
		total,
		traceable,
		insufficientContext,
		comparable,
		needsReview,
		items: [
			{
				key: 'total',
				labelKey: 'results.summary.total',
				value: total,
				tone: 'brand',
				icon: 'R'
			},
			{
				key: 'traceable',
				labelKey: 'results.summary.traceable',
				value: traceable,
				tone: 'success',
				icon: 'T'
			},
			{
				key: 'insufficientContext',
				labelKey: 'results.summary.insufficientContext',
				value: insufficientContext,
				tone: 'warning',
				icon: '!'
			},
			{
				key: 'comparable',
				labelKey: 'results.summary.comparable',
				value: comparable,
				tone: 'info',
				icon: 'C'
			},
			{
				key: 'needsReview',
				labelKey: 'results.summary.needsReview',
				value: needsReview,
				tone: 'danger',
				icon: '!'
			}
		]
	};
}

export function buildResultsConclusion(summary: ResultsQualitySummary): ResultsConclusion {
	const highRisk =
		summary.total < 1 ||
		summary.insufficientContext > summary.total / 2 ||
		summary.needsReview > summary.total / 2;

	if (highRisk) {
		return {
			tone: 'warning',
			titleKey: 'results.conclusion.title',
			bodyKey: 'results.conclusion.warningBody',
			actionKeys: ['view_insufficient', 'open_comparison']
		};
	}
	if (summary.comparable > 0) {
		return {
			tone: 'success',
			titleKey: 'results.conclusion.title',
			bodyKey: 'results.conclusion.successBody',
			actionKeys: ['open_comparison', 'view_all']
		};
	}
	return {
		tone: 'info',
		titleKey: 'results.conclusion.title',
		bodyKey: 'results.conclusion.successBody',
		actionKeys: ['view_all', 'open_comparison']
	};
}

export function filterResults(
	results: ResultListItem[],
	filters: ResultFilters,
	labels: ResultValueLabels = {}
) {
	const query = filters.search.trim().toLowerCase();

	return results.filter((result) => {
		const availability = getResultAvailabilityStatus(result);
		const traceability = getTraceabilityStatus(result);
		const context = getResultContext(result, labels);
		const missing = getMissingContextChips(result);
		const quote = getSourceEvidenceQuote(result);

		if (filters.availability && availability !== filters.availability) return false;
		if (filters.material && context.materialSystem !== filters.material) return false;
		if (filters.property && context.property !== filters.property) return false;
		if (
			filters.testCondition &&
			(specifiedResultValue(result.test_condition, 'test_condition')
				? 'specified'
				: 'unspecified') !== filters.testCondition
		) {
			return false;
		}
		if (filters.traceability && traceability !== filters.traceability) return false;
		if (!query) return true;

		const searchable = [
			result.result_id,
			formatDocumentTitle(result.document_id, result.document_title),
			context.materialSystem,
			context.property,
			context.process,
			context.baseline,
			context.testCondition,
			formatResultValue(result.summary, 'result', labels),
			quote.text,
			quote.citation ?? '',
			...missing.flatMap((chip) => [chip.key, chip.fallbackLabel])
		]
			.join(' ')
			.toLowerCase();
		return searchable.includes(query);
	});
}

export function sortResults(
	results: ResultListItem[],
	sortMode: ResultSortMode,
	labels: ResultValueLabels = {}
) {
	return [...results].sort((a, b) => {
		if (sortMode === 'confidence_desc') {
			return getResultConfidence(b) - getResultConfidence(a);
		}
		if (sortMode === 'traceability') {
			return (
				traceabilityRank(getTraceabilityStatus(b)) - traceabilityRank(getTraceabilityStatus(a))
			);
		}
		if (sortMode === 'recent') {
			const aDate = Date.parse(a.updated_at || a.created_at || '');
			const bDate = Date.parse(b.updated_at || b.created_at || '');
			const aTime = Number.isNaN(aDate) ? 0 : aDate;
			const bTime = Number.isNaN(bDate) ? 0 : bDate;
			return bTime - aTime;
		}

		const missingDelta = getMissingContextChips(a).length - getMissingContextChips(b).length;
		if (missingDelta !== 0) return missingDelta;
		const statusDelta =
			statusRank(getResultAvailabilityStatus(b)) - statusRank(getResultAvailabilityStatus(a));
		if (statusDelta !== 0) return statusDelta;
		return getResultContext(a, labels).materialSystem.localeCompare(
			getResultContext(b, labels).materialSystem
		);
	});
}

export async function fetchCollectionResults(
	collectionId: string,
	query: ResultsQuery = {}
): Promise<ResultListResponse> {
	if (USE_API_FIXTURES) {
		const fixture = buildFixtureList(collectionId);
		const items = filterFixtureItems(fixture.items, query);
		return {
			...fixture,
			total: items.length,
			count: items.length,
			items
		};
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/results${buildQueryString(query)}`,
		{
			method: 'GET'
		}
	);
	return normalizeListResponse(data, collectionId);
}

export async function fetchCollectionResult(
	collectionId: string,
	resultId: string
): Promise<ResultDetail> {
	if (USE_API_FIXTURES) {
		return buildFixtureDetail(collectionId, resultId);
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/results/${encodeURIComponent(resultId)}`,
		{
			method: 'GET'
		}
	);
	return normalizeDetail(data, collectionId, resultId);
}
