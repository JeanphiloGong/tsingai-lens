import { requestJson } from './api';

export type ResearchViewState = 'empty' | 'processing' | 'partial' | 'ready' | 'failed';
export type EvidenceBackedValueStatus =
	| 'observed'
	| 'normalized'
	| 'inferred'
	| 'missing'
	| 'conflicted';

export type ResearchViewWarning = {
	warning_id: string;
	severity: string;
	scope: string;
	code: string;
	message: string;
	related_object_ids: string[];
};

export type EvidenceReference = {
	evidence_ref_id: string;
	fact_ids: string[];
	anchor_ids: string[];
	source_kind: string | null;
	document_id: string | null;
	locator: string | null;
	confidence: number | null;
	traceability_status: string | null;
};

export type EvidenceBackedValue = {
	display_value: string;
	value: string | number | null;
	unit: string | null;
	normalized_value: string | number | null;
	normalized_unit: string | null;
	status: EvidenceBackedValueStatus;
	confidence: number | null;
	evidence_refs: EvidenceReference[];
	duplicate_count: number;
	conflict_status: string | null;
	warnings: ResearchViewWarning[];
};

export type SampleMatrixColumn = {
	column_id: string;
	key: string;
	label: string;
	kind: string;
	unit: string | null;
};

export type SampleMatrixRow = {
	row_id: string;
	sample_id: string;
	sample_label: string;
	material: string;
	process_context: Record<string, string>;
	variable_axis: string | null;
	variable_value: string | number | null;
	values: Record<string, EvidenceBackedValue>;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type SampleMatrix = {
	matrix_id: string;
	document_id: string;
	state: ResearchViewState;
	columns: SampleMatrixColumn[];
	rows: SampleMatrixRow[];
	warnings: ResearchViewWarning[];
};

export type ConditionSeriesPoint = {
	point_id: string;
	condition_value: string | number | null;
	condition_unit: string | null;
	result: EvidenceBackedValue;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type ConditionSeries = {
	series_id: string;
	document_id: string;
	sample_id: string | null;
	property: string;
	condition_axis: string;
	points: ConditionSeriesPoint[];
	warnings: ResearchViewWarning[];
};

export type PaperCoverageRow = {
	document_id: string;
	title: string;
	state: ResearchViewState;
	sample_count: number;
	process_param_count: number;
	measurement_count: number;
	condition_count: number;
	evidence_count: number;
	issue_count: number;
	primary_warnings: ResearchViewWarning[];
	links: Record<string, string>;
};

export type CrossPaperMatrixRow = {
	row_id: string;
	document_id: string;
	sample_id: string | null;
	sample_label: string | null;
	material: string;
	process_context: Record<string, string>;
	variable_value: string | number | null;
	test_condition: string | null;
	property: string;
	result: EvidenceBackedValue;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type CrossPaperMatrix = {
	matrix_id: string;
	group_id: string;
	columns: SampleMatrixColumn[];
	rows: CrossPaperMatrixRow[];
	warnings: ResearchViewWarning[];
};

export type ComparableGroup = {
	group_id: string;
	title: string;
	material_system: string;
	process_family: string;
	variable_axis: string | null;
	fixed_conditions: Record<string, string>;
	properties: string[];
	documents: string[];
	samples: string[];
	comparability_status: 'comparable' | 'limited' | 'blocked';
	matrix: CrossPaperMatrix;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type PaperAggregationOverview = {
	material_systems: string[];
	sample_variant_count: number;
	main_process_variables: string[];
	measured_properties: string[];
	condition_families: string[];
	evidence_count: number;
	warning_count: number;
};

export type PaperAggregation = {
	collection_id: string;
	document_id: string;
	paper_title: string;
	state: ResearchViewState;
	overview: PaperAggregationOverview;
	sample_matrix: SampleMatrix;
	condition_series: ConditionSeries[];
	evidence_links: Record<string, string>;
	debug_links: Record<string, string>;
	warnings: ResearchViewWarning[];
};

export type CollectionAggregationOverview = {
	document_count: number;
	sample_count: number;
	measurement_count: number;
	evidence_count: number;
	material_systems: string[];
	process_families: string[];
	variable_axes: string[];
	measured_properties: string[];
	coverage_quality: string | null;
};

export type CollectionAggregation = {
	collection_id: string;
	state: ResearchViewState;
	overview: CollectionAggregationOverview;
	paper_coverage: PaperCoverageRow[];
	comparable_groups: ComparableGroup[];
	cross_paper_matrices: CrossPaperMatrix[];
	trend_series: ConditionSeries[];
	evidence_links: Record<string, string>;
	debug_links: Record<string, string>;
	warnings: ResearchViewWarning[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function asArray(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [];
}

function nonEmptyText(value: unknown): string | null {
	if (typeof value !== 'string') return null;
	const text = value.trim();
	return text ? text : null;
}

function toText(value: unknown, fallback = ''): string {
	if (typeof value === 'string') return value.trim() || fallback;
	if (typeof value === 'number' && Number.isFinite(value)) return String(value);
	return fallback;
}

function toNumber(value: unknown, fallback = 0): number {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim() !== '') {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : fallback;
	}
	return fallback;
}

function toOptionalNumber(value: unknown): number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim() !== '') {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : null;
	}
	return null;
}

function toScalar(value: unknown): string | number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	return nonEmptyText(value);
}

function toStringList(value: unknown): string[] {
	if (Array.isArray(value)) {
		return value
			.map((item) => {
				if (typeof item === 'string' || typeof item === 'number') return String(item).trim();
				const record = asRecord(item);
				return toText(record?.label ?? record?.name ?? record?.id ?? record?.message);
			})
			.filter((item) => item !== '');
	}
	if (typeof value === 'string' && value.trim()) return [value.trim()];
	return [];
}

function normalizeResearchState(value: unknown, fallback: ResearchViewState): ResearchViewState {
	const state = toText(value) as ResearchViewState;
	return ['empty', 'processing', 'partial', 'ready', 'failed'].includes(state) ? state : fallback;
}

function normalizeEvidenceStatus(value: unknown): EvidenceBackedValueStatus {
	const status = toText(value) as EvidenceBackedValueStatus;
	return ['observed', 'normalized', 'inferred', 'missing', 'conflicted'].includes(status)
		? status
		: 'missing';
}

function normalizeStringRecord(value: unknown): Record<string, string> {
	const record = asRecord(value);
	if (!record) return {};

	return Object.fromEntries(
		Object.entries(record)
			.map(([key, item]) => [key, toText(item)] as const)
			.filter(([, item]) => item !== '')
	);
}

function normalizeContextRecord(value: unknown, fallbackKey: string): Record<string, string> {
	if (typeof value === 'string' || typeof value === 'number') {
		const text = toText(value);
		return text ? { [fallbackKey]: text } : {};
	}
	return normalizeStringRecord(value);
}

function normalizeLinkRecord(value: unknown): Record<string, string> {
	return normalizeStringRecord(value);
}

function locatorText(value: unknown): string | null {
	if (typeof value === 'string') return nonEmptyText(value);
	const record = asRecord(value);
	if (!record) return null;

	const parts = [
		record.page ? `p.${toText(record.page)}` : '',
		toText(record.table ?? record.figure ?? record.section ?? record.paragraph ?? record.row),
		toText(record.label ?? record.source_label)
	].filter((item) => item !== '');
	return parts.length ? parts.join(' / ') : JSON.stringify(record);
}

function conditionAxisText(value: unknown): string {
	const record = asRecord(value);
	if (!record) return toText(value, '--');
	return toText(record.label ?? record.name ?? record.axis_name ?? record.key, '--');
}

function warningFromText(message: string, index: number): ResearchViewWarning {
	return {
		warning_id: `warning_${index + 1}`,
		severity: 'warning',
		scope: 'unknown',
		code: 'warning',
		message,
		related_object_ids: []
	};
}

export function normalizeResearchWarning(value: unknown): ResearchViewWarning | null {
	if (typeof value === 'string') {
		const message = value.trim();
		return message ? warningFromText(message, 0) : null;
	}

	const record = asRecord(value);
	if (!record) return null;

	const message = toText(record.message ?? record.detail ?? record.code);
	if (!message) return null;

	return {
		warning_id: toText(record.warning_id ?? record.id, `warning_${message}`),
		severity: toText(record.severity, 'warning'),
		scope: toText(record.scope, 'unknown'),
		code: toText(record.code, 'warning'),
		message,
		related_object_ids: toStringList(record.related_object_ids ?? record.object_ids)
	};
}

function normalizeWarnings(value: unknown): ResearchViewWarning[] {
	if (typeof value === 'string') return [warningFromText(value, 0)].filter((item) => item.message);
	return asArray(value)
		.map((item, index) => normalizeResearchWarning(item) ?? warningFromText(String(item), index))
		.filter((item) => item.message);
}

function normalizeEvidenceReference(value: unknown): EvidenceReference | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceRefId = toText(
		record.evidence_ref_id ?? record.evidence_id ?? record.id ?? record.anchor_id
	);
	const factIds = toStringList(record.fact_ids ?? record.result_ids ?? record.source_fact_ids);
	const anchorIds = toStringList(record.anchor_ids ?? record.direct_anchor_ids);
	if (!evidenceRefId && !factIds.length && !anchorIds.length) return null;

	return {
		evidence_ref_id: evidenceRefId || factIds[0] || anchorIds[0] || 'evidence_ref',
		fact_ids: factIds,
		anchor_ids: anchorIds,
		source_kind: nonEmptyText(record.source_kind ?? record.source_type),
		document_id: nonEmptyText(record.document_id ?? record.source_document_id),
		locator: locatorText(record.locator ?? record.location ?? record.source_label),
		confidence: toOptionalNumber(record.confidence ?? record.confidence_score),
		traceability_status: nonEmptyText(record.traceability_status)
	};
}

function normalizeEvidenceReferences(value: unknown): EvidenceReference[] {
	return asArray(value)
		.map((item) => normalizeEvidenceReference(item))
		.filter((item): item is EvidenceReference => item !== null);
}

export function normalizeEvidenceBackedValue(value: unknown): EvidenceBackedValue {
	const record = asRecord(value);
	const scalar = !record ? toScalar(value) : null;
	const displayValue = toText(record?.display_value ?? record?.display ?? record?.label ?? scalar);
	const rawValue = toScalar(record?.value ?? scalar);
	const normalizedValue = toScalar(record?.normalized_value);
	const status = normalizeEvidenceStatus(
		record?.status ??
			(displayValue || rawValue !== null || normalizedValue !== null ? 'observed' : 'missing')
	);

	return {
		display_value: displayValue,
		value: rawValue,
		unit: nonEmptyText(record?.unit),
		normalized_value: normalizedValue,
		normalized_unit: nonEmptyText(record?.normalized_unit),
		status,
		confidence: toOptionalNumber(record?.confidence ?? record?.confidence_score),
		evidence_refs: normalizeEvidenceReferences(record?.evidence_refs ?? record?.evidence),
		duplicate_count: Math.max(0, toNumber(record?.duplicate_count, 0)),
		conflict_status: nonEmptyText(record?.conflict_status),
		warnings: normalizeWarnings(record?.warnings)
	};
}

function normalizeColumn(value: unknown, index: number): SampleMatrixColumn | null {
	if (typeof value === 'string') {
		const key = value.trim();
		return key
			? {
					column_id: key,
					key,
					label: key,
					kind: 'value',
					unit: null
				}
			: null;
	}

	const record = asRecord(value);
	if (!record) return null;
	const key = toText(
		record.value_key ?? record.key ?? record.column_id ?? record.id ?? record.label,
		`column_${index + 1}`
	);

	return {
		column_id: toText(record.column_id ?? record.id, key),
		key,
		label: toText(record.label ?? record.name, key),
		kind: toText(record.role ?? record.kind ?? record.type, 'value'),
		unit: nonEmptyText(record.unit)
	};
}

function normalizeValueMap(value: unknown): Record<string, EvidenceBackedValue> {
	const record = asRecord(value);
	if (!record) return {};

	return Object.fromEntries(
		Object.entries(record).map(([key, item]) => [key, normalizeEvidenceBackedValue(item)])
	);
}

export function normalizeSampleMatrixRow(value: unknown): SampleMatrixRow | null {
	const record = asRecord(value);
	if (!record) return null;

	const rowId = toText(record.row_id ?? record.id ?? record.sample_id);
	const sampleId = toText(record.sample_id ?? record.variant_id ?? rowId);
	if (!rowId && !sampleId) return null;

	return {
		row_id: rowId || sampleId,
		sample_id: sampleId || rowId,
		sample_label: toText(
			record.sample_label ?? record.variant_label ?? record.label,
			sampleId || rowId
		),
		material: toText(record.material ?? record.material_system, '--'),
		process_context: normalizeContextRecord(
			record.process_context ?? record.process_family ?? record.process,
			'process'
		),
		variable_axis: nonEmptyText(record.variable_axis),
		variable_value: toScalar(record.variable_value),
		values: normalizeValueMap(record.values ?? record.cells),
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

export function normalizeSampleMatrix(value: unknown): SampleMatrix {
	const record = asRecord(value);

	return {
		matrix_id: toText(record?.matrix_id ?? record?.id, 'sample_matrix'),
		document_id: toText(record?.document_id),
		state: normalizeResearchState(record?.state, 'empty'),
		columns: asArray(record?.columns)
			.map((item, index) => normalizeColumn(item, index))
			.filter((item): item is SampleMatrixColumn => item !== null),
		rows: asArray(record?.rows)
			.map((item) => normalizeSampleMatrixRow(item))
			.filter((item): item is SampleMatrixRow => item !== null),
		warnings: normalizeWarnings(record?.warnings)
	};
}

function normalizeConditionSeriesPoint(value: unknown, index: number): ConditionSeriesPoint | null {
	const record = asRecord(value);
	if (!record) return null;

	const result = normalizeEvidenceBackedValue(record.result ?? record.value);
	return {
		point_id: toText(record.point_id ?? record.id, `point_${index + 1}`),
		condition_value: toScalar(record.condition_value ?? record.x),
		condition_unit: nonEmptyText(record.condition_unit ?? record.x_unit),
		result,
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

export function normalizeConditionSeries(value: unknown): ConditionSeries | null {
	const record = asRecord(value);
	if (!record) return null;

	const seriesId = toText(record.series_id ?? record.id);
	const property = toText(record.property ?? record.property_name);
	const conditionAxis = conditionAxisText(record.condition_axis ?? record.axis);
	if (!seriesId && !property && !conditionAxis) return null;

	return {
		series_id: seriesId || `${property || 'series'}_${conditionAxis || 'axis'}`,
		document_id: toText(record.document_id),
		sample_id: nonEmptyText(record.sample_id),
		property: property || '--',
		condition_axis: conditionAxis || '--',
		points: asArray(record.points)
			.map((item, index) => normalizeConditionSeriesPoint(item, index))
			.filter((item): item is ConditionSeriesPoint => item !== null),
		warnings: normalizeWarnings(record.warnings)
	};
}

function normalizePaperCoverageRow(value: unknown): PaperCoverageRow | null {
	const record = asRecord(value);
	if (!record) return null;

	const documentId = toText(record.document_id ?? record.id);
	if (!documentId) return null;

	return {
		document_id: documentId,
		title: toText(record.title ?? record.paper_title ?? record.source_filename, documentId),
		state: normalizeResearchState(record.state, 'partial'),
		sample_count: toNumber(record.sample_count),
		process_param_count: toNumber(record.process_param_count ?? record.process_parameter_count),
		measurement_count: toNumber(record.measurement_count),
		condition_count: toNumber(record.condition_count),
		evidence_count: toNumber(record.evidence_count),
		issue_count: toNumber(record.issue_count),
		primary_warnings: normalizeWarnings(record.primary_warnings ?? record.warnings),
		links: normalizeLinkRecord(record.links)
	};
}

function normalizeCrossPaperMatrixRow(value: unknown, index: number): CrossPaperMatrixRow | null {
	const record = asRecord(value);
	if (!record) return null;

	const rowId = toText(record.row_id ?? record.id, `matrix_row_${index + 1}`);
	const result = normalizeEvidenceBackedValue(record.result ?? record.value);

	return {
		row_id: rowId,
		document_id: toText(record.document_id ?? record.source_document_id),
		sample_id: nonEmptyText(record.sample_id ?? record.variant_id),
		sample_label: nonEmptyText(record.sample_label ?? record.variant_label),
		material: toText(record.material ?? record.material_system, '--'),
		process_context: normalizeContextRecord(
			record.process_context ?? record.process_family ?? record.process,
			'process'
		),
		variable_value: toScalar(record.variable_value),
		test_condition: nonEmptyText(record.test_condition ?? record.test_condition_normalized),
		property: toText(record.property ?? record.property_normalized, '--'),
		result,
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

export function normalizeCrossPaperMatrix(value: unknown): CrossPaperMatrix {
	const record = asRecord(value);

	return {
		matrix_id: toText(record?.matrix_id ?? record?.id, 'cross_paper_matrix'),
		group_id: toText(record?.group_id),
		columns: asArray(record?.columns)
			.map((item, index) => normalizeColumn(item, index))
			.filter((item): item is SampleMatrixColumn => item !== null),
		rows: asArray(record?.rows)
			.map((item, index) => normalizeCrossPaperMatrixRow(item, index))
			.filter((item): item is CrossPaperMatrixRow => item !== null),
		warnings: normalizeWarnings(record?.warnings)
	};
}

function normalizeComparableStatus(value: unknown): ComparableGroup['comparability_status'] {
	const status = toText(value);
	if (status === 'comparable' || status === 'limited' || status === 'blocked') return status;
	if (status === 'not_comparable' || status === 'insufficient') return 'blocked';
	return 'limited';
}

export function normalizeComparableGroup(value: unknown): ComparableGroup | null {
	const record = asRecord(value);
	if (!record) return null;

	const groupId = toText(record.group_id ?? record.id);
	if (!groupId) return null;

	return {
		group_id: groupId,
		title: toText(record.title ?? record.name, groupId),
		material_system: toText(record.material_system, '--'),
		process_family: toText(record.process_family, '--'),
		variable_axis: nonEmptyText(record.variable_axis),
		fixed_conditions: normalizeStringRecord(record.fixed_conditions),
		properties: toStringList(record.properties),
		documents: toStringList(record.documents ?? record.document_ids),
		samples: toStringList(record.samples ?? record.sample_ids),
		comparability_status: normalizeComparableStatus(record.comparability_status ?? record.status),
		matrix: normalizeCrossPaperMatrix(record.matrix),
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

function normalizeCollectionOverview(value: unknown): CollectionAggregationOverview {
	const record = asRecord(value);

	return {
		document_count: toNumber(record?.document_count ?? record?.paper_count),
		sample_count: toNumber(record?.sample_count ?? record?.sample_variant_count),
		measurement_count: toNumber(record?.measurement_count),
		evidence_count: toNumber(record?.evidence_count),
		material_systems: toStringList(record?.material_systems ?? record?.materials),
		process_families: toStringList(record?.process_families ?? record?.processes),
		variable_axes: toStringList(record?.variable_axes ?? record?.main_process_variables),
		measured_properties: toStringList(record?.measured_properties ?? record?.properties),
		coverage_quality: nonEmptyText(record?.coverage_quality)
	};
}

function normalizePaperOverview(value: unknown): PaperAggregationOverview {
	const record = asRecord(value);

	return {
		material_systems: toStringList(record?.material_systems ?? record?.materials),
		sample_variant_count: toNumber(record?.sample_variant_count ?? record?.sample_count),
		main_process_variables: toStringList(record?.main_process_variables ?? record?.variable_axes),
		measured_properties: toStringList(record?.measured_properties ?? record?.properties),
		condition_families: toStringList(record?.condition_families ?? record?.conditions),
		evidence_count: toNumber(record?.evidence_count),
		warning_count: toNumber(record?.warning_count)
	};
}

export function normalizeCollectionAggregation(
	value: unknown,
	collectionId: string
): CollectionAggregation {
	const record = asRecord(value);
	const matrices = asArray(record?.cross_paper_matrices)
		.map((item) => normalizeCrossPaperMatrix(item))
		.filter((item) => item.matrix_id);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		state: normalizeResearchState(record?.state, 'empty'),
		overview: normalizeCollectionOverview(record?.overview),
		paper_coverage: asArray(record?.paper_coverage)
			.map((item) => normalizePaperCoverageRow(item))
			.filter((item): item is PaperCoverageRow => item !== null),
		comparable_groups: asArray(record?.comparable_groups)
			.map((item) => normalizeComparableGroup(item))
			.filter((item): item is ComparableGroup => item !== null),
		cross_paper_matrices: matrices,
		trend_series: asArray(record?.trend_series)
			.map((item) => normalizeConditionSeries(item))
			.filter((item): item is ConditionSeries => item !== null),
		evidence_links: normalizeLinkRecord(record?.evidence_links),
		debug_links: normalizeLinkRecord(record?.debug_links),
		warnings: normalizeWarnings(record?.warnings)
	};
}

export function normalizePaperAggregation(
	value: unknown,
	collectionId: string,
	documentId: string
): PaperAggregation {
	const record = asRecord(value);
	const sampleMatrix = normalizeSampleMatrix(record?.sample_matrix);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		document_id: toText(record?.document_id, documentId),
		paper_title: toText(record?.paper_title ?? record?.title, documentId),
		state: normalizeResearchState(record?.state, sampleMatrix.rows.length ? 'partial' : 'empty'),
		overview: normalizePaperOverview(record?.overview),
		sample_matrix: {
			...sampleMatrix,
			document_id: sampleMatrix.document_id || documentId
		},
		condition_series: asArray(record?.condition_series)
			.map((item) => normalizeConditionSeries(item))
			.filter((item): item is ConditionSeries => item !== null),
		evidence_links: normalizeLinkRecord(record?.evidence_links),
		debug_links: normalizeLinkRecord(record?.debug_links),
		warnings: normalizeWarnings(record?.warnings)
	};
}

export async function fetchCollectionResearchView(
	collectionId: string
): Promise<CollectionAggregation> {
	const encoded = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encoded}/research-view`);
	return normalizeCollectionAggregation(data, collectionId);
}

export async function fetchDocumentResearchView(
	collectionId: string,
	documentId: string
): Promise<PaperAggregation> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedDocument = encodeURIComponent(documentId);
	const data = await requestJson(
		`/collections/${encodedCollection}/documents/${encodedDocument}/research-view`
	);
	return normalizePaperAggregation(data, collectionId, documentId);
}

export function getResearchViewStateTone(state: ResearchViewState): string {
	if (state === 'ready') return 'ready';
	if (state === 'partial' || state === 'processing') return 'processing';
	if (state === 'failed') return 'failed';
	return 'empty';
}

export function hasObservedValue(value: EvidenceBackedValue): boolean {
	if (value.status === 'missing') return false;
	return (
		value.display_value !== '' ||
		value.value !== null ||
		value.normalized_value !== null ||
		value.evidence_refs.length > 0
	);
}

export function formatEvidenceBackedValue(value: EvidenceBackedValue): string {
	if (value.display_value) return value.display_value;

	const renderedValue = value.normalized_value ?? value.value;
	const renderedUnit = value.normalized_unit ?? value.unit;
	if (renderedValue !== null) {
		return renderedUnit ? `${renderedValue} ${renderedUnit}` : String(renderedValue);
	}

	return '--';
}
