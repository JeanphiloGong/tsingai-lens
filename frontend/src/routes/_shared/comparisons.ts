import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type ComparabilityStatus = 'comparable' | 'limited' | 'not_comparable' | 'insufficient';
export type ComparisonReviewStatus = ComparabilityStatus;
export type ComparisonTone = 'brand' | 'success' | 'warning' | 'danger' | 'neutral' | 'info';
export type ComparisonResultTypeFilter =
	| ''
	| 'property'
	| 'process'
	| 'result'
	| 'structure'
	| 'performance'
	| 'other';
export type ComparisonSpecifiedFilter = '' | 'specified' | 'unspecified';
export type ComparisonMissingContextFilter =
	| ''
	| 'baseline'
	| 'variant_link'
	| 'test_condition'
	| 'unit_context'
	| 'expert_interpretation';
export type ComparisonSortMode =
	| 'completeness'
	| 'confidence_desc'
	| 'status'
	| 'material'
	| 'recent';
export type ComparisonFieldType =
	| 'material'
	| 'process'
	| 'baseline'
	| 'test_condition'
	| 'result'
	| 'result_type'
	| 'missing_context'
	| 'generic';

export type ComparisonValueLabels = Partial<Record<ComparisonFieldType, string>>;

export type ComparisonFilters = {
	search: string;
	status: '' | ComparisonReviewStatus;
	material: string;
	resultType: ComparisonResultTypeFilter;
	testCondition: ComparisonSpecifiedFilter;
	baseline: ComparisonSpecifiedFilter;
	missingContext: ComparisonMissingContextFilter;
};

export type ComparisonBadge = {
	labelKey: string;
	fallbackLabel: string;
	tone: ComparisonTone;
	icon: string;
};

export type ComparisonQualitySummaryItem = {
	key: ComparisonReviewStatus;
	labelKey: string;
	value: number;
	percent: number | null;
	tone: ComparisonTone;
	icon: string;
};

export type ComparisonConclusionActionKey =
	| 'view_direct'
	| 'view_limited'
	| 'view_insufficient'
	| 'view_evidence'
	| 'add_to_final';

export type ComparisonConclusion = {
	tone: 'warning' | 'success' | 'info';
	titleKey: string;
	bodyKey: string;
	actionKeys: ComparisonConclusionActionKey[];
};

export type ComparisonMissingContextChip = {
	key: Exclude<ComparisonMissingContextFilter, ''> | 'material_system' | 'process';
	labelKey: string;
	fallbackLabel: string;
	tone: 'warning' | 'neutral';
};

export type ComparisonActionKey =
	| 'add_to_final'
	| 'view_evidence'
	| 'mark_issue'
	| 'view_comparison'
	| 'view_conditions'
	| 'view_missing'
	| 'view_reason'
	| 'exclude';

export type ComparisonAction = {
	key: ComparisonActionKey;
	labelKey: string;
	tone: 'primary' | 'ghost' | 'danger';
};

export type ComparisonContext = {
	materialSystem: string;
	process: string;
	baseline: string;
	testCondition: string;
	variant: string | null;
	variable: string | null;
};

export type ComparisonDisplay = {
	material_system_normalized: string;
	process_normalized: string;
	variant_id: string | null;
	variant_label: string | null;
	variable_axis: string | null;
	variable_value: string | number | null;
	property_normalized: string;
	result_type: string;
	result_summary: string;
	value: number | null;
	unit: string | null;
	test_condition_normalized: string;
	baseline_reference: string | null;
	baseline_normalized: string;
};

export type ComparisonEvidenceBundle = {
	result_source_type: string | null;
	supporting_evidence_ids: string[];
	supporting_anchor_ids: string[];
	characterization_observation_ids: string[];
	structure_feature_ids: string[];
};

export type ComparisonAssessment = {
	comparability_status: ComparabilityStatus;
	comparability_warnings: string[];
	comparability_basis: string[];
	requires_expert_review: boolean;
	assessment_epistemic_status: string;
};

export type ComparisonUncertainty = {
	missing_critical_context: string[];
	unresolved_fields: string[];
	unresolved_baseline_link: boolean;
	unresolved_condition_link: boolean;
};

export type ComparisonRow = {
	row_id: string;
	result_id: string;
	collection_id: string;
	source_document_id: string;
	confidence: number | null;
	display: ComparisonDisplay;
	evidence_bundle: ComparisonEvidenceBundle;
	assessment: ComparisonAssessment;
	uncertainty: ComparisonUncertainty;
};

export type ComparisonsResponse = {
	collection_id: string;
	total: number;
	count: number;
	items: ComparisonRow[];
};

export type ComparisonsQuery = {
	limit?: number;
	offset?: number;
	material_system_normalized?: string;
	property_normalized?: string;
	test_condition_normalized?: string;
	baseline_normalized?: string;
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

function toOptionalText(value: unknown): string | null {
	if (typeof value !== 'string') return null;
	const text = value.trim();
	return text || null;
}

function toOptionalNumber(value: unknown): number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim() !== '') {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}
	return null;
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

function normalizeDisplay(value: unknown): ComparisonDisplay {
	const record = asRecord(value);

	return {
		material_system_normalized: String(record?.material_system_normalized ?? '--').trim() || '--',
		process_normalized: String(record?.process_normalized ?? '--').trim() || '--',
		variant_id: toOptionalText(record?.variant_id),
		variant_label: toOptionalText(record?.variant_label),
		variable_axis: toOptionalText(record?.variable_axis),
		variable_value: toScalarOrText(record?.variable_value),
		property_normalized: String(record?.property_normalized ?? '--').trim() || '--',
		result_type: String(record?.result_type ?? 'unspecified').trim() || 'unspecified',
		result_summary: String(record?.result_summary ?? '--').trim() || '--',
		value: toOptionalNumber(record?.value),
		unit: toOptionalText(record?.unit),
		test_condition_normalized: String(record?.test_condition_normalized ?? '--').trim() || '--',
		baseline_reference: toOptionalText(record?.baseline_reference),
		baseline_normalized: String(record?.baseline_normalized ?? '--').trim() || '--'
	};
}

function normalizeEvidenceBundle(value: unknown): ComparisonEvidenceBundle {
	const record = asRecord(value);

	return {
		result_source_type: toOptionalText(record?.result_source_type),
		supporting_evidence_ids: toStringList(record?.supporting_evidence_ids),
		supporting_anchor_ids: toStringList(record?.supporting_anchor_ids),
		characterization_observation_ids: toStringList(record?.characterization_observation_ids),
		structure_feature_ids: toStringList(record?.structure_feature_ids)
	};
}

function normalizeAssessment(value: unknown): ComparisonAssessment {
	const record = asRecord(value);

	return {
		comparability_status: normalizeComparabilityStatus(record?.comparability_status),
		comparability_warnings: toStringList(record?.comparability_warnings),
		comparability_basis: toStringList(record?.comparability_basis),
		requires_expert_review: toBoolean(record?.requires_expert_review),
		assessment_epistemic_status:
			String(record?.assessment_epistemic_status ?? 'unresolved').trim() || 'unresolved'
	};
}

function normalizeUncertainty(value: unknown): ComparisonUncertainty {
	const record = asRecord(value);

	return {
		missing_critical_context: toStringList(record?.missing_critical_context),
		unresolved_fields: toStringList(record?.unresolved_fields),
		unresolved_baseline_link: toBoolean(record?.unresolved_baseline_link),
		unresolved_condition_link: toBoolean(record?.unresolved_condition_link)
	};
}

function normalizeRow(value: unknown, collectionId: string): ComparisonRow | null {
	const record = asRecord(value);
	if (!record) return null;

	const row_id = String(record.row_id ?? record.id ?? '').trim();
	if (!row_id) return null;

	return {
		row_id,
		result_id: String(record.result_id ?? record.comparable_result_id ?? row_id).trim() || row_id,
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		source_document_id: String(record.source_document_id ?? record.document_id ?? '').trim(),
		confidence: toOptionalNumber(
			record.confidence ??
				record.confidence_score ??
				asRecord(record.assessment)?.confidence ??
				asRecord(record.assessment)?.confidence_score
		),
		display: normalizeDisplay(record.display),
		evidence_bundle: normalizeEvidenceBundle(record.evidence_bundle),
		assessment: normalizeAssessment(record.assessment),
		uncertainty: normalizeUncertainty(record.uncertainty)
	};
}

function buildFixture(collectionId: string): ComparisonsResponse {
	const items: ComparisonRow[] = [
		{
			row_id: 'cmp_1',
			result_id: 'cres_1',
			collection_id: collectionId,
			source_document_id: 'doc_a',
			confidence: 0.9,
			display: {
				material_system_normalized: 'High-entropy oxide',
				process_normalized: 'Reduced oxygen anneal',
				variant_id: 'var_1',
				variant_label: 'Reduced sample',
				variable_axis: 'Anneal atmosphere',
				variable_value: 'low oxygen',
				property_normalized: 'Cycle retention',
				result_type: 'retention',
				result_summary: 'Retained 92% capacity after 200 cycles.',
				value: 92,
				unit: '%',
				test_condition_normalized: '200 cycles at 1C',
				baseline_reference: 'Air annealed control',
				baseline_normalized: 'Air annealed sample'
			},
			evidence_bundle: {
				result_source_type: 'table',
				supporting_evidence_ids: ['ev_1'],
				supporting_anchor_ids: ['anc_1'],
				characterization_observation_ids: ['char_1'],
				structure_feature_ids: ['struct_1']
			},
			assessment: {
				comparability_status: 'comparable',
				comparability_warnings: [],
				comparability_basis: ['Shared cycling window', 'Aligned baseline'],
				requires_expert_review: false,
				assessment_epistemic_status: 'grounded'
			},
			uncertainty: {
				missing_critical_context: [],
				unresolved_fields: [],
				unresolved_baseline_link: false,
				unresolved_condition_link: false
			}
		},
		{
			row_id: 'cmp_2',
			result_id: 'cres_2',
			collection_id: collectionId,
			source_document_id: 'doc_c',
			confidence: 0.86,
			display: {
				material_system_normalized: 'Layered oxide',
				process_normalized: 'Carbon coating',
				variant_id: 'var_2',
				variant_label: '2 wt% coating',
				variable_axis: 'Carbon fraction',
				variable_value: '2 wt%',
				property_normalized: 'Impedance',
				result_type: 'scalar',
				result_summary: 'Impedance improved, but baseline alignment is incomplete.',
				value: null,
				unit: null,
				test_condition_normalized: 'EIS after 50 cycles',
				baseline_reference: null,
				baseline_normalized: 'Reference not fully specified'
			},
			evidence_bundle: {
				result_source_type: 'text',
				supporting_evidence_ids: ['ev_2'],
				supporting_anchor_ids: ['anc_2'],
				characterization_observation_ids: [],
				structure_feature_ids: []
			},
			assessment: {
				comparability_status: 'limited',
				comparability_warnings: ['Baseline is only partially aligned across documents.'],
				comparability_basis: ['Test setup partially aligned'],
				requires_expert_review: true,
				assessment_epistemic_status: 'provisional'
			},
			uncertainty: {
				missing_critical_context: ['baseline_reference'],
				unresolved_fields: ['baseline_reference'],
				unresolved_baseline_link: true,
				unresolved_condition_link: false
			}
		},
		{
			row_id: 'cmp_3',
			result_id: 'cres_3',
			collection_id: collectionId,
			source_document_id: 'doc_b',
			confidence: 0.64,
			display: {
				material_system_normalized: 'Interface strategy review',
				process_normalized: 'Narrative survey',
				variant_id: null,
				variant_label: null,
				variable_axis: null,
				variable_value: null,
				property_normalized: 'Cycle stability',
				result_type: 'trend',
				result_summary: 'Review-only source; no single experimental baseline.',
				value: null,
				unit: null,
				test_condition_normalized: '--',
				baseline_reference: null,
				baseline_normalized: '--'
			},
			evidence_bundle: {
				result_source_type: 'text',
				supporting_evidence_ids: [],
				supporting_anchor_ids: [],
				characterization_observation_ids: [],
				structure_feature_ids: []
			},
			assessment: {
				comparability_status: 'not_comparable',
				comparability_warnings: ['Review-only source; not a directly comparable experiment row.'],
				comparability_basis: ['No matched experimental baseline'],
				requires_expert_review: false,
				assessment_epistemic_status: 'grounded'
			},
			uncertainty: {
				missing_critical_context: [],
				unresolved_fields: [],
				unresolved_baseline_link: false,
				unresolved_condition_link: false
			}
		},
		{
			row_id: 'cmp_4',
			result_id: 'cres_4',
			collection_id: collectionId,
			source_document_id: 'doc_d',
			confidence: 0.82,
			display: {
				material_system_normalized: 'Nickel superalloy',
				process_normalized: 'Laser powder bed fusion',
				variant_id: 'var_4',
				variant_label: 'High-power run',
				variable_axis: 'Laser power',
				variable_value: 350,
				property_normalized: 'Fatigue life',
				result_type: 'scalar',
				result_summary: 'Result reported, but condition details remain unresolved.',
				value: null,
				unit: null,
				test_condition_normalized: 'unspecified test condition',
				baseline_reference: null,
				baseline_normalized: 'unspecified baseline'
			},
			evidence_bundle: {
				result_source_type: 'table',
				supporting_evidence_ids: ['ev_4'],
				supporting_anchor_ids: ['anc_4'],
				characterization_observation_ids: ['char_4'],
				structure_feature_ids: ['struct_4']
			},
			assessment: {
				comparability_status: 'insufficient',
				comparability_warnings: ['Critical condition context is unresolved.'],
				comparability_basis: ['Condition link missing'],
				requires_expert_review: true,
				assessment_epistemic_status: 'unresolved'
			},
			uncertainty: {
				missing_critical_context: ['test_condition', 'baseline_reference'],
				unresolved_fields: ['test_condition', 'baseline_reference'],
				unresolved_baseline_link: true,
				unresolved_condition_link: true
			}
		}
	];

	return {
		collection_id: collectionId,
		total: items.length,
		count: items.length,
		items
	};
}

function buildComparisonsQuery(query: ComparisonsQuery = {}) {
	const params = new URLSearchParams();

	if (typeof query.limit === 'number') {
		params.set('limit', String(query.limit));
	}
	if (typeof query.offset === 'number') {
		params.set('offset', String(query.offset));
	}
	for (const [key, value] of Object.entries(query)) {
		if (key === 'limit' || key === 'offset') continue;
		const normalized = typeof value === 'string' ? value.trim() : '';
		if (normalized) {
			params.set(key, normalized);
		}
	}

	const rendered = params.toString();
	return rendered ? `?${rendered}` : '';
}

function applyComparisonsQuery(
	response: ComparisonsResponse,
	query: ComparisonsQuery = {}
): ComparisonsResponse {
	const filtered = response.items.filter((item) => {
		if (
			query.material_system_normalized &&
			item.display.material_system_normalized !== query.material_system_normalized
		) {
			return false;
		}
		if (
			query.property_normalized &&
			item.display.property_normalized !== query.property_normalized
		) {
			return false;
		}
		if (
			query.test_condition_normalized &&
			item.display.test_condition_normalized !== query.test_condition_normalized
		) {
			return false;
		}
		if (
			query.baseline_normalized &&
			item.display.baseline_normalized !== query.baseline_normalized
		) {
			return false;
		}
		return true;
	});

	const offset = Math.max(query.offset ?? 0, 0);
	const limit = Math.max(query.limit ?? filtered.length, 0);
	const items = filtered.slice(offset, offset + limit);

	return {
		collection_id: response.collection_id,
		total: filtered.length,
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
		? record.items
				.map((item) => normalizeRow(item, collectionId))
				.filter((item): item is ComparisonRow => item !== null)
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
		.replace(/\blpbf\b/g, 'LPBF')
		.replace(/\bni\b/g, 'Ni');
	return `${restored.charAt(0).toUpperCase()}${restored.slice(1)}`;
}

function isMissingComparisonValue(
	value: string | number | null | undefined,
	fieldType: ComparisonFieldType
) {
	const normalized = String(value ?? '')
		.trim()
		.toLowerCase();
	if (!normalized || normalized === '--' || normalized === 'null' || normalized === 'undefined') {
		return true;
	}
	if (normalized === 'n/a' || normalized === 'na' || normalized === 'unknown') return true;
	if (normalized.startsWith('unspecified')) return true;
	if (normalized.includes('not specified')) return true;
	if (fieldType === 'baseline' && normalized.includes('no single experimental baseline'))
		return true;
	return false;
}

function specifiedComparisonValue(
	value: string | number | null | undefined,
	fieldType: ComparisonFieldType
) {
	return !isMissingComparisonValue(value, fieldType);
}

function missingValueLabel(fieldType: ComparisonFieldType, labels: ComparisonValueLabels = {}) {
	if (labels[fieldType]) return labels[fieldType];
	if (fieldType === 'material') return 'Unspecified material system';
	if (fieldType === 'process') return 'Unspecified treatment';
	if (fieldType === 'baseline') return 'Unspecified baseline';
	if (fieldType === 'test_condition') return 'Unspecified test condition';
	return labels.generic ?? 'Unspecified';
}

function normalizedConfidenceValue(confidence?: number | null) {
	if (typeof confidence !== 'number' || !Number.isFinite(confidence)) return null;
	if (confidence <= 1) return Math.max(0, confidence);
	return Math.max(0, Math.min(1, confidence / 100));
}

function inferredConfidenceValue(row: ComparisonRow) {
	const normalized = normalizedConfidenceValue(row.confidence);
	if (normalized !== null) return normalized;
	if (row.assessment.assessment_epistemic_status === 'grounded') return 0.9;
	if (row.assessment.assessment_epistemic_status === 'provisional') return 0.86;
	if (row.assessment.assessment_epistemic_status === 'unresolved') return 0.82;
	const status = row.assessment.comparability_status;
	if (status === 'comparable') return 0.9;
	if (status === 'limited') return 0.84;
	if (status === 'not_comparable') return 0.62;
	return 0.78;
}

function normalizedResultType(type?: string | null): Exclude<ComparisonResultTypeFilter, ''> {
	const normalized = normalizeMachineText(String(type ?? '')).toLowerCase();
	if (['property', 'process', 'result', 'structure', 'performance'].includes(normalized)) {
		return normalized as Exclude<ComparisonResultTypeFilter, ''>;
	}
	if (['scalar', 'trend', 'measurement', 'retention', 'observation'].includes(normalized)) {
		return 'result';
	}
	return 'other';
}

function fieldMentions(values: string[], needles: string[]) {
	const haystack = values.map((value) => normalizeMachineText(value).toLowerCase()).join(' ');
	return needles.some((needle) => haystack.includes(needle));
}

function addUnique<T>(items: T[], item: T) {
	if (!items.includes(item)) items.push(item);
}

function missingContextKeys(row: ComparisonRow) {
	const keys: ComparisonMissingContextChip['key'][] = [];
	const missingValues = [
		...row.uncertainty.missing_critical_context,
		...row.uncertainty.unresolved_fields
	];

	if (
		row.uncertainty.unresolved_baseline_link ||
		fieldMentions(missingValues, ['baseline', 'baseline reference']) ||
		(!specifiedComparisonValue(row.display.baseline_normalized, 'baseline') &&
			!specifiedComparisonValue(row.display.baseline_reference, 'baseline'))
	) {
		addUnique(keys, 'baseline');
	}
	if (
		row.uncertainty.unresolved_condition_link ||
		fieldMentions(missingValues, ['test condition', 'condition link']) ||
		!specifiedComparisonValue(row.display.test_condition_normalized, 'test_condition')
	) {
		addUnique(keys, 'test_condition');
	}
	if (
		fieldMentions(missingValues, ['material system', 'material']) ||
		!specifiedComparisonValue(row.display.material_system_normalized, 'material')
	) {
		addUnique(keys, 'material_system');
	}
	if (
		fieldMentions(missingValues, ['process', 'treatment']) ||
		!specifiedComparisonValue(row.display.process_normalized, 'process')
	) {
		addUnique(keys, 'process');
	}
	if (fieldMentions(missingValues, ['variant', 'variant link', 'variant details'])) {
		addUnique(keys, 'variant_link');
	}
	if (
		fieldMentions(missingValues, ['unit', 'unit context']) ||
		(row.display.value !== null && !row.display.unit)
	) {
		addUnique(keys, 'unit_context');
	}
	if (
		row.assessment.requires_expert_review ||
		fieldMentions(missingValues, ['expert', 'expert interpretation'])
	) {
		addUnique(keys, 'expert_interpretation');
	}

	return keys;
}

function statusRank(status: ComparisonReviewStatus) {
	if (status === 'not_comparable') return 0;
	if (status === 'insufficient') return 1;
	if (status === 'limited') return 2;
	return 3;
}

export function formatComparisonValue(
	value: string | number | null | undefined,
	fieldType: ComparisonFieldType,
	labels: ComparisonValueLabels = {}
) {
	if (isMissingComparisonValue(value, fieldType)) return missingValueLabel(fieldType, labels);

	const text = usefulText(value);
	if (!text) return missingValueLabel(fieldType, labels);
	if (text.includes('_') || /^[a-z0-9 -]+$/.test(text)) return sentenceCase(text);
	return text;
}

export function getComparisonContext(
	row: ComparisonRow,
	labels: ComparisonValueLabels = {}
): ComparisonContext {
	const variableAxis = usefulText(row.display.variable_axis);
	const variableValue =
		row.display.variable_value === null || row.display.variable_value === undefined
			? ''
			: String(row.display.variable_value).trim();

	return {
		materialSystem: formatComparisonValue(
			row.display.material_system_normalized,
			'material',
			labels
		),
		process: formatComparisonValue(row.display.process_normalized, 'process', labels),
		baseline: formatComparisonValue(
			usefulText(row.display.baseline_normalized) || row.display.baseline_reference,
			'baseline',
			labels
		),
		testCondition: formatComparisonValue(
			row.display.test_condition_normalized,
			'test_condition',
			labels
		),
		variant: usefulText(row.display.variant_label),
		variable:
			variableAxis && variableValue
				? `${formatComparisonValue(variableAxis, 'generic', labels)}: ${variableValue}`
				: variableAxis
					? formatComparisonValue(variableAxis, 'generic', labels)
					: variableValue || null
	};
}

export function getMissingContextChips(row: ComparisonRow): ComparisonMissingContextChip[] {
	const chips: Record<ComparisonMissingContextChip['key'], ComparisonMissingContextChip> = {
		baseline: {
			key: 'baseline',
			labelKey: 'comparison.missing.baseline',
			fallbackLabel: 'Missing baseline',
			tone: 'warning'
		},
		variant_link: {
			key: 'variant_link',
			labelKey: 'comparison.missing.variantLink',
			fallbackLabel: 'Missing variant link',
			tone: 'warning'
		},
		test_condition: {
			key: 'test_condition',
			labelKey: 'comparison.missing.testCondition',
			fallbackLabel: 'Missing test condition',
			tone: 'warning'
		},
		unit_context: {
			key: 'unit_context',
			labelKey: 'comparison.missing.unitContext',
			fallbackLabel: 'Missing unit context',
			tone: 'neutral'
		},
		expert_interpretation: {
			key: 'expert_interpretation',
			labelKey: 'comparison.missing.expertInterpretation',
			fallbackLabel: 'Missing expert interpretation',
			tone: 'neutral'
		},
		material_system: {
			key: 'material_system',
			labelKey: 'comparison.missing.materialSystem',
			fallbackLabel: 'Missing material system',
			tone: 'warning'
		},
		process: {
			key: 'process',
			labelKey: 'comparison.missing.process',
			fallbackLabel: 'Missing treatment',
			tone: 'neutral'
		}
	};
	return missingContextKeys(row).map((key) => chips[key]);
}

export function getComparisonStatus(row: ComparisonRow): ComparisonReviewStatus {
	const baseStatus = row.assessment.comparability_status;
	if (baseStatus === 'not_comparable') return 'not_comparable';

	const missingKeys = missingContextKeys(row);
	const hasBlockingMissingContext = missingKeys.some((key) =>
		['material_system', 'baseline', 'test_condition'].includes(key)
	);

	if (baseStatus === 'insufficient' || hasBlockingMissingContext || missingKeys.length >= 3) {
		return 'insufficient';
	}
	if (baseStatus === 'limited' || missingKeys.length > 0 || row.assessment.requires_expert_review) {
		return 'limited';
	}
	return 'comparable';
}

export function getComparisonStatusBadge(status: ComparisonReviewStatus): ComparisonBadge {
	if (status === 'comparable') {
		return {
			labelKey: 'comparison.status.comparable',
			fallbackLabel: '可直接比较',
			tone: 'success',
			icon: 'OK'
		};
	}
	if (status === 'limited') {
		return {
			labelKey: 'comparison.status.limited',
			fallbackLabel: '受限比较',
			tone: 'warning',
			icon: '!'
		};
	}
	if (status === 'not_comparable') {
		return {
			labelKey: 'comparison.status.notComparable',
			fallbackLabel: '不可比较',
			tone: 'danger',
			icon: 'X'
		};
	}
	return {
		labelKey: 'comparison.status.insufficient',
		fallbackLabel: '信息不足',
		tone: 'neutral',
		icon: '?'
	};
}

export function getResultTypeBadge(type?: string | null): ComparisonBadge {
	const normalized = normalizedResultType(type);
	const badges: Record<Exclude<ComparisonResultTypeFilter, ''>, ComparisonBadge> = {
		property: {
			labelKey: 'comparison.resultTypes.property',
			fallbackLabel: 'Property',
			tone: 'neutral',
			icon: 'P'
		},
		process: {
			labelKey: 'comparison.resultTypes.process',
			fallbackLabel: 'Process',
			tone: 'brand',
			icon: 'P'
		},
		result: {
			labelKey: 'comparison.resultTypes.result',
			fallbackLabel: 'Result',
			tone: 'success',
			icon: 'R'
		},
		structure: {
			labelKey: 'comparison.resultTypes.structure',
			fallbackLabel: 'Structure',
			tone: 'info',
			icon: 'S'
		},
		performance: {
			labelKey: 'comparison.resultTypes.performance',
			fallbackLabel: 'Performance',
			tone: 'warning',
			icon: 'F'
		},
		other: {
			labelKey: 'comparison.resultTypes.other',
			fallbackLabel: 'Other',
			tone: 'neutral',
			icon: 'O'
		}
	};
	return badges[normalized];
}

export function formatComparisonConfidence(row: ComparisonRow) {
	return `${clampPercent(inferredConfidenceValue(row) * 100)}%`;
}

export function buildComparisonQualitySummary(
	comparisonItems: ComparisonRow[]
): ComparisonQualitySummaryItem[] {
	const total = comparisonItems.length;
	const counts: Record<ComparisonReviewStatus, number> = {
		comparable: 0,
		limited: 0,
		not_comparable: 0,
		insufficient: 0
	};

	for (const item of comparisonItems) {
		counts[getComparisonStatus(item)] += 1;
	}

	return [
		{
			key: 'comparable',
			labelKey: 'comparison.summary.direct',
			value: counts.comparable,
			percent: percentOf(counts.comparable, total),
			tone: 'success',
			icon: 'OK'
		},
		{
			key: 'limited',
			labelKey: 'comparison.summary.limited',
			value: counts.limited,
			percent: percentOf(counts.limited, total),
			tone: 'warning',
			icon: '!'
		},
		{
			key: 'not_comparable',
			labelKey: 'comparison.summary.notComparable',
			value: counts.not_comparable,
			percent: percentOf(counts.not_comparable, total),
			tone: 'danger',
			icon: 'X'
		},
		{
			key: 'insufficient',
			labelKey: 'comparison.summary.insufficient',
			value: counts.insufficient,
			percent: percentOf(counts.insufficient, total),
			tone: 'neutral',
			icon: '?'
		}
	];
}

export function buildComparisonConclusion(
	summary: ComparisonQualitySummaryItem[]
): ComparisonConclusion {
	const valueFor = (key: ComparisonReviewStatus) =>
		summary.find((item) => item.key === key)?.value ?? 0;
	const direct = valueFor('comparable');
	const limited = valueFor('limited');
	const notComparable = valueFor('not_comparable');
	const insufficient = valueFor('insufficient');
	const total = direct + limited + notComparable + insufficient;

	if (direct > 0 && direct >= limited && direct >= insufficient && direct >= notComparable) {
		return {
			tone: 'success',
			titleKey: 'comparison.conclusion.title',
			bodyKey: 'comparison.conclusion.directBody',
			actionKeys: ['view_direct', 'add_to_final']
		};
	}
	if (limited > 0 && limited >= insufficient && limited >= direct) {
		return {
			tone: 'warning',
			titleKey: 'comparison.conclusion.title',
			bodyKey: 'comparison.conclusion.limitedBody',
			actionKeys: ['view_limited', 'view_evidence']
		};
	}
	if (total < 1 || insufficient >= Math.max(direct, limited, notComparable)) {
		return {
			tone: 'warning',
			titleKey: 'comparison.conclusion.title',
			bodyKey: 'comparison.conclusion.insufficientBody',
			actionKeys: ['view_insufficient', 'view_evidence']
		};
	}
	return {
		tone: 'warning',
		titleKey: 'comparison.conclusion.title',
		bodyKey: 'comparison.conclusion.insufficientBody',
		actionKeys: ['view_insufficient', 'view_evidence']
	};
}

export function getComparisonNote(row: ComparisonRow) {
	const warnings = row.assessment.comparability_warnings.map((item) => item.trim()).filter(Boolean);
	if (warnings.length) return warnings.join(' ');

	const missing = getMissingContextChips(row);
	if (missing.length) {
		return `Missing context: ${missing.map((chip) => chip.fallbackLabel).join(', ')}.`;
	}
	if (row.assessment.requires_expert_review) {
		return 'Result shape requires expert interpretation before comparison.';
	}
	return 'No major caution flags.';
}

export function getComparisonActions(row: ComparisonRow): ComparisonAction[] {
	const status = getComparisonStatus(row);
	if (status === 'comparable') {
		return [
			{ key: 'add_to_final', labelKey: 'comparison.actions.addToFinal', tone: 'primary' },
			{ key: 'view_evidence', labelKey: 'comparison.actions.viewEvidence', tone: 'ghost' },
			{ key: 'mark_issue', labelKey: 'comparison.actions.markIssue', tone: 'ghost' }
		];
	}
	if (status === 'limited') {
		return [
			{ key: 'view_comparison', labelKey: 'comparison.actions.viewComparison', tone: 'ghost' },
			{ key: 'view_conditions', labelKey: 'comparison.actions.viewConditions', tone: 'ghost' },
			{ key: 'add_to_final', labelKey: 'comparison.actions.addToFinal', tone: 'primary' }
		];
	}
	if (status === 'not_comparable') {
		return [
			{ key: 'view_reason', labelKey: 'comparison.actions.viewReason', tone: 'ghost' },
			{ key: 'exclude', labelKey: 'comparison.actions.exclude', tone: 'danger' },
			{ key: 'view_evidence', labelKey: 'comparison.actions.viewEvidence', tone: 'ghost' }
		];
	}
	return [
		{ key: 'view_evidence', labelKey: 'comparison.actions.viewEvidence', tone: 'ghost' },
		{ key: 'view_missing', labelKey: 'comparison.actions.viewMissing', tone: 'ghost' },
		{ key: 'mark_issue', labelKey: 'comparison.actions.markIssue', tone: 'danger' }
	];
}

export function filterComparisonItems(
	comparisonItems: ComparisonRow[],
	filters: ComparisonFilters,
	labels: ComparisonValueLabels = {}
): ComparisonRow[] {
	const query = filters.search.trim().toLowerCase();

	return comparisonItems.filter((item) => {
		const status = getComparisonStatus(item);
		const context = getComparisonContext(item, labels);
		const missing = getMissingContextChips(item);

		if (filters.status && status !== filters.status) return false;
		if (filters.material && context.materialSystem !== filters.material) return false;
		if (
			filters.resultType &&
			normalizedResultType(item.display.result_type) !== filters.resultType
		) {
			return false;
		}
		if (
			filters.testCondition &&
			(specifiedComparisonValue(item.display.test_condition_normalized, 'test_condition')
				? 'specified'
				: 'unspecified') !== filters.testCondition
		) {
			return false;
		}
		if (
			filters.baseline &&
			(specifiedComparisonValue(item.display.baseline_normalized, 'baseline')
				? 'specified'
				: 'unspecified') !== filters.baseline
		) {
			return false;
		}
		if (filters.missingContext && !missing.some((chip) => chip.key === filters.missingContext)) {
			return false;
		}
		if (!query) return true;

		const searchable = [
			item.row_id,
			item.result_id,
			formatComparisonValue(item.display.property_normalized, 'result', labels),
			formatComparisonValue(item.display.result_summary, 'result', labels),
			item.display.result_type,
			context.materialSystem,
			context.process,
			context.baseline,
			context.testCondition,
			context.variant ?? '',
			context.variable ?? '',
			getComparisonNote(item),
			...missing.flatMap((chip) => [chip.fallbackLabel, chip.key])
		]
			.join(' ')
			.toLowerCase();
		return searchable.includes(query);
	});
}

export function sortComparisonItems(
	comparisonItems: ComparisonRow[],
	sortMode: ComparisonSortMode,
	labels: ComparisonValueLabels = {}
): ComparisonRow[] {
	return [...comparisonItems].sort((a, b) => {
		if (sortMode === 'confidence_desc') {
			return inferredConfidenceValue(b) - inferredConfidenceValue(a);
		}
		if (sortMode === 'status') {
			return statusRank(getComparisonStatus(b)) - statusRank(getComparisonStatus(a));
		}
		if (sortMode === 'material') {
			return getComparisonContext(a, labels).materialSystem.localeCompare(
				getComparisonContext(b, labels).materialSystem
			);
		}
		if (sortMode === 'recent') return 0;

		const missingDelta = getMissingContextChips(a).length - getMissingContextChips(b).length;
		if (missingDelta !== 0) return missingDelta;
		return statusRank(getComparisonStatus(b)) - statusRank(getComparisonStatus(a));
	});
}

export async function fetchComparisons(
	collectionId: string,
	query: ComparisonsQuery = {}
): Promise<ComparisonsResponse> {
	if (USE_API_FIXTURES) {
		return applyComparisonsQuery(buildFixture(collectionId), query);
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/comparisons${buildComparisonsQuery(query)}`,
		{
			method: 'GET'
		}
	);
	return normalizeResponse(data, collectionId);
}

export async function fetchComparison(collectionId: string, rowId: string): Promise<ComparisonRow> {
	if (USE_API_FIXTURES) {
		const fixture = buildFixture(collectionId).items.find((item) => item.row_id === rowId);
		if (fixture) {
			return fixture;
		}
		throw new Error('Comparison row fixture is missing.');
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/comparisons/${encodeURIComponent(rowId)}`,
		{
			method: 'GET'
		}
	);
	const row = normalizeRow(data, collectionId);
	if (!row) {
		throw new Error('Comparison row response is invalid.');
	}
	return row;
}

export const fetchComparisonRow = fetchComparison;
