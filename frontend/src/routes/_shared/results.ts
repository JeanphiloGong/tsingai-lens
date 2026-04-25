import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type ComparabilityStatus = 'comparable' | 'limited' | 'not_comparable' | 'insufficient';

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

	return {
		result_id,
		document_id: String(record.document_id ?? record.source_document_id ?? '').trim(),
		document_title: String(
			record.document_title ?? record.document_name ?? record.document_id ?? result_id
		).trim(),
		material_label: String(record.material_label ?? '--').trim() || '--',
		variant_label: toOptionalText(record.variant_label),
		property: String(record.property ?? '--').trim() || '--',
		value: toNumber(record.value),
		unit: toOptionalText(record.unit),
		summary: String(record.summary ?? record.result_summary ?? '--').trim() || '--',
		baseline: toOptionalText(record.baseline),
		test_condition: toOptionalText(record.test_condition),
		process: toOptionalText(record.process),
		traceability_status: String(record.traceability_status ?? 'missing').trim() || 'missing',
		comparability_status: normalizeComparabilityStatus(record.comparability_status),
		requires_expert_review: toBoolean(record.requires_expert_review)
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
			requires_expert_review: false
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
			requires_expert_review: true
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
