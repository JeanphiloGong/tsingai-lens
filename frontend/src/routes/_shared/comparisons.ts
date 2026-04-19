import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type ComparabilityStatus = 'comparable' | 'limited' | 'not_comparable' | 'insufficient';

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
	collection_id: string;
	source_document_id: string;
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
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		source_document_id: String(record.source_document_id ?? record.document_id ?? '').trim(),
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
			collection_id: collectionId,
			source_document_id: 'doc_a',
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
			collection_id: collectionId,
			source_document_id: 'doc_c',
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
			collection_id: collectionId,
			source_document_id: 'doc_b',
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
			collection_id: collectionId,
			source_document_id: 'doc_d',
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

export async function fetchComparison(
	collectionId: string,
	rowId: string
): Promise<ComparisonRow> {
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
