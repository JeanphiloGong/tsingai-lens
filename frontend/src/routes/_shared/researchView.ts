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

export type FindingFeedbackStatus = 'correct' | 'incorrect' | 'partial' | 'unclear';
export type FindingFeedbackIssueType =
	| 'none'
	| 'evidence_not_grounded'
	| 'missing_evidence'
	| 'insufficient_evidence'
	| 'wrong_variable'
	| 'wrong_outcome'
	| 'wrong_direction'
	| 'wrong_context'
	| 'wrong_relation'
	| 'overclaim'
	| 'unclear_statement'
	| 'other';
export type FindingFeedbackCreate = {
	analysis_version: number;
	review_status: FindingFeedbackStatus;
	issue_type: FindingFeedbackIssueType;
	note?: string | null;
	reviewer?: string | null;
};
export type FindingFeedback = FindingFeedbackCreate & {
	feedback_id: string;
	collection_id: string;
	objective_id: string;
	finding_id: string;
	created_at: string;
};
export type FindingCurationCreate = {
	analysis_version: number;
	curated_status: string;
	curated_statement: string;
	curated_support_grade?: string | null;
	curated_review_status?: string | null;
	curated_variables?: string[];
	curated_mediators?: string[];
	curated_outcomes?: string[];
	curated_direction?: string | null;
	curated_scope_summary?: string | null;
	curated_evidence_ids: string[];
	note?: string | null;
	reviewer?: string | null;
};
export type FindingCuration = FindingCurationCreate & {
	curation_id: string;
	collection_id: string;
	objective_id: string;
	finding_id: string;
	updated_at: string;
};
export type FindingDatasetLabelStatus = 'candidate' | 'silver' | 'gold' | 'rejected';
export type FindingDatasetUseStatus = 'training_ready' | 'review_candidate' | 'rejected';
export type FindingDatasetSample = {
	sample_id: string;
	objective_id: string;
	analysis_version: number;
	finding_id: string;
	research_objective: string;
	finding_level: string;
	document_ids: string[];
	label_status: FindingDatasetLabelStatus;
	dataset_use_status: FindingDatasetUseStatus;
	system_prediction: Record<string, unknown>;
	expert_target: Record<string, unknown> | null;
	evidence: Record<string, unknown>[];
	training_schema_version: string;
	training_prompt_version: string;
	training_messages: Array<{ role: string; content: string }>;
	metadata: Record<string, unknown>;
};
export type FindingDataset = {
	schema_version: string;
	collection_id: string;
	objective_id: string | null;
	items: FindingDatasetSample[];
	warnings: string[];
};
export type FindingDatasetFilters = {
	label_status?: FindingDatasetLabelStatus;
	dataset_use_status?: FindingDatasetUseStatus;
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

export type MaterialSummary = {
	material_id: string;
	canonical_name: string;
	aliases: string[];
	paper_count: number;
	sample_count: number;
	process_families: string[];
	measured_properties: string[];
	comparison_count: number;
	evidence_coverage: string | number | null;
	state: ResearchViewState;
	links: Record<string, string>;
	warnings: ResearchViewWarning[];
};

export type PaperMaterialSummary = {
	material_id: string;
	canonical_name: string;
	aliases: string[];
	sample_count: number;
	process_families: string[];
	measured_properties: string[];
	comparison_count: number;
	evidence_coverage: string | number | null;
	links: Record<string, string>;
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
	document_id: string | null;
	sample_id: string;
	sample_label: string;
	material: string;
	process_context: Record<string, string>;
	test_condition?: Record<string, string>;
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

export type ObjectiveConfirmationStatus = 'candidate' | 'confirmed';
export type ObjectiveAnalysisStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type ObjectiveAnalysisState = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	source_build_id: string;
	pipeline_version: string;
	model_name: string | null;
	prompt_versions: Record<string, string>;
	status: ObjectiveAnalysisStatus;
	phase: string;
	processed_document_count: number;
	total_document_count: number;
	current_document_id: string | null;
	progress_message: string | null;
	error_code: string | null;
	error_message: string | null;
	created_at: string | null;
	started_at: string | null;
	completed_at: string | null;
};

export type ObjectiveSummary = {
	collection_id: string;
	objective_id: string;
	question: string;
	material_scope: string[];
	process_axes: string[];
	property_axes: string[];
	comparison_intent: string | null;
	seed_document_ids: string[];
	excluded_document_ids: string[];
	confidence: number;
	reason: string | null;
	confirmation_status: ObjectiveConfirmationStatus;
	active_analysis_version: number | null;
	published_analysis_version: number | null;
	created_at: string | null;
	updated_at: string | null;
};

export type ObjectiveFindingRelation = {
	relation_order: number;
	source_term: string;
	relation_type: string;
	target_term: string;
	direction: string | null;
	assertion_strength: string;
	supporting_evidence_ids: string[];
};
export type ObjectiveFindingContext = {
	material_system: Record<string, unknown>;
	process_conditions: Record<string, unknown>[];
	sample_state: Record<string, unknown>;
	test_conditions: Record<string, unknown>[];
	comparison_baseline: Record<string, unknown>;
	limitations: string[];
	supporting_evidence_ids: string[];
};
export type ObjectiveFindingDerivation = {
	synthesis_mode: string;
	comparison_status: string;
	contributing_document_ids: string[];
	supporting_evidence_ids: string[];
	contradicting_evidence_ids: string[];
	rationale: string;
};
export type ObjectiveFinding = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	finding_id: string;
	finding_level: string;
	statement: string;
	variables: string[];
	mediators: string[];
	outcomes: string[];
	direction: string | null;
	scope_summary: string;
	evidence_strength: string;
	generalization_status: string;
	paper_count: number;
	confidence: number;
	display_rank: number;
	relations: ObjectiveFindingRelation[];
	context: ObjectiveFindingContext;
	derivation: ObjectiveFindingDerivation;
};
export type ObjectiveEvidence = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	evidence_id: string;
	document_id: string;
	source_kind: string;
	source_ref: string;
	source_excerpt: string;
	page_numbers: number[];
	related_source_refs: Record<string, unknown>[];
	evidence_role: string;
	selection_reason: string | null;
	selection_status: string;
	evidence_kind: string;
	property_normalized: string | null;
	material_system: Record<string, unknown>;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	resolved_condition: Record<string, unknown>;
	test_condition: Record<string, unknown>;
	value_payload: Record<string, unknown>;
	unit: string | null;
	baseline_context: Record<string, unknown>;
	interpretation: string | null;
	anchor_ids: string[];
	join_keys: Record<string, unknown>;
	resolution_status: string;
	failure_reason: string | null;
	confidence: number;
};

export type ObjectiveList = {
	collection_id: string;
	objectives: ObjectiveSummary[];
};
export type ObjectiveAnalysis = {
	collection_id: string;
	objective: ObjectiveSummary;
	active_analysis: ObjectiveAnalysisState | null;
	published_analysis: ObjectiveAnalysisState | null;
	warnings: string[];
};
export type ObjectiveFindingPage = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	items: ObjectiveFinding[];
	offset: number;
	limit: number;
	total: number;
};
export type ObjectiveEvidencePage = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	finding_id: string | null;
	items: ObjectiveEvidence[];
	offset: number;
	limit: number;
	total: number;
};

export type MaterialPaperCoverage = {
	document_id: string;
	title: string;
	source_filename: string | null;
	state: ResearchViewState;
	sample_count: number;
	process_families: string[];
	measured_properties: string[];
	evidence_count: number;
	issue_count: number;
	links: Record<string, string>;
	warnings: ResearchViewWarning[];
};

export type ProcessParameterRange = {
	parameter: string;
	display_range: string;
	min_value: string | number | null;
	max_value: string | number | null;
	unit: string | null;
	sample_count: number;
	document_count: number;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type PropertySummary = {
	property: string;
	display_range: string;
	min_value: string | number | null;
	max_value: string | number | null;
	unit: string | null;
	sample_count: number;
	document_count: number;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type MaterialProfileOverview = {
	paper_count: number;
	sample_count: number;
	comparison_count: number;
	condition_series_count: number;
	evidence_count: number;
	process_families: string[];
	measured_properties: string[];
	variable_axes: string[];
};

export type MaterialProfile = {
	collection_id: string;
	material_id: string;
	canonical_name: string;
	aliases: string[];
	state: ResearchViewState;
	overview: MaterialProfileOverview;
	papers: MaterialPaperCoverage[];
	sample_matrix: SampleMatrix;
	process_parameter_ranges: ProcessParameterRange[];
	measured_properties: PropertySummary[];
	comparison_groups: ComparableGroup[];
	condition_series: ConditionSeries[];
	evidence_refs: EvidenceReference[];
	debug_links: Record<string, string>;
	warnings: ResearchViewWarning[];
};

export type DocumentMaterialProfile = {
	collection_id: string;
	document_id: string;
	material_id: string;
	canonical_name: string;
	aliases: string[];
	state: ResearchViewState;
	overview: MaterialProfileOverview;
	sample_matrix: SampleMatrix;
	process_conditions: Record<string, string>[];
	test_conditions: Record<string, string>[];
	measured_properties: PropertySummary[];
	within_paper_comparisons: ComparableGroup[];
	condition_series: ConditionSeries[];
	evidence_refs: EvidenceReference[];
	debug_links: Record<string, string>;
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
	materials: PaperMaterialSummary[];
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
	materials: MaterialSummary[];
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

export function formatShortIdentifier(value: string | null | undefined): string {
	const text = String(value ?? '').trim();
	if (!text) return '--';
	if (text.length <= 24) return text;
	return `${text.slice(0, 10)}...${text.slice(-6)}`;
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

function normalizeUnknownRecord(value: unknown): Record<string, unknown> {
	const record = asRecord(value);
	return record ? { ...record } : {};
}

function normalizeUnknownRecordList(value: unknown): Record<string, unknown>[] {
	return asArray(value)
		.map((item) => normalizeUnknownRecord(item))
		.filter((item) => Object.keys(item).length > 0);
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

function normalizeObjectList(value: unknown, key: string): unknown[] {
	if (Array.isArray(value)) return value;
	const record = asRecord(value);
	return asArray(record?.[key] ?? record?.items);
}

function normalizeEvidenceCoverage(value: unknown): string | number | null {
	const scalar = toScalar(value);
	if (scalar !== null) return scalar;

	const record = asRecord(value);
	return toScalar(record?.display_value ?? record?.display ?? record?.value ?? record?.coverage);
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

function normalizeFindingDataset(value: unknown): FindingDataset {
	const record = asRecord(value);
	return {
		schema_version: toText(record?.schema_version),
		collection_id: toText(record?.collection_id),
		objective_id: nonEmptyText(record?.objective_id),
		items: asArray(record?.items)
			.map((item) => normalizeFindingDatasetSample(item))
			.filter((item): item is FindingDatasetSample => item !== null),
		warnings: toStringList(record?.warnings)
	};
}

function normalizeFindingDatasetSample(value: unknown): FindingDatasetSample | null {
	const record = asRecord(value);
	if (!record) return null;
	const sampleId = toText(record.sample_id);
	const objectiveId = toText(record.objective_id);
	const analysisVersion = toNumber(record.analysis_version);
	const findingId = toText(record.finding_id);
	if (!sampleId || !objectiveId || analysisVersion < 1 || !findingId) return null;
	const labelStatus = toText(record.label_status) as FindingDatasetLabelStatus;
	const datasetUseStatus = toText(record.dataset_use_status) as FindingDatasetUseStatus;
	if (!['candidate', 'silver', 'gold', 'rejected'].includes(labelStatus)) return null;
	if (!['training_ready', 'review_candidate', 'rejected'].includes(datasetUseStatus)) return null;
	return {
		sample_id: sampleId,
		objective_id: objectiveId,
		analysis_version: analysisVersion,
		finding_id: findingId,
		research_objective: toText(record.research_objective),
		finding_level: toText(record.finding_level),
		document_ids: toStringList(record.document_ids),
		label_status: labelStatus,
		dataset_use_status: datasetUseStatus,
		system_prediction: normalizeUnknownRecord(record.system_prediction),
		expert_target: asRecord(record.expert_target),
		evidence: normalizeUnknownRecordList(record.evidence),
		training_schema_version: toText(record.training_schema_version),
		training_prompt_version: toText(record.training_prompt_version),
		training_messages: asArray(record.training_messages)
			.map((message) => {
				const messageRecord = asRecord(message);
				const role = toText(messageRecord?.role);
				const content = toText(messageRecord?.content);
				return role && content ? { role, content } : null;
			})
			.filter((message): message is { role: string; content: string } => message !== null),
		metadata: normalizeUnknownRecord(record.metadata)
	};
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
		document_id: nonEmptyText(record.document_id ?? record.source_document_id),
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
		test_condition: normalizeContextRecord(
			record.test_condition ?? record.test_conditions ?? record.condition_context,
			'condition'
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

function normalizeObjectiveSummary(value: unknown): ObjectiveSummary | null {
	const record = asRecord(value);
	if (!record || !toText(record.objective_id) || !toText(record.question)) return null;
	const confirmationStatus = toText(record.confirmation_status);
	return {
		collection_id: toText(record.collection_id),
		objective_id: toText(record.objective_id),
		question: toText(record.question),
		material_scope: toStringList(record.material_scope),
		process_axes: toStringList(record.process_axes),
		property_axes: toStringList(record.property_axes),
		comparison_intent: nonEmptyText(record.comparison_intent),
		seed_document_ids: toStringList(record.seed_document_ids),
		excluded_document_ids: toStringList(record.excluded_document_ids),
		confidence: toNumber(record.confidence),
		reason: nonEmptyText(record.reason),
		confirmation_status: confirmationStatus === 'confirmed' ? 'confirmed' : 'candidate',
		active_analysis_version: toOptionalNumber(record.active_analysis_version),
		published_analysis_version: toOptionalNumber(record.published_analysis_version),
		created_at: nonEmptyText(record.created_at),
		updated_at: nonEmptyText(record.updated_at)
	};
}

function normalizeObjectiveAnalysisState(value: unknown): ObjectiveAnalysisState | null {
	const record = asRecord(value);
	if (!record || !toNumber(record.analysis_version)) return null;
	const status = toText(record.status) as ObjectiveAnalysisStatus;
	return {
		collection_id: toText(record.collection_id),
		objective_id: toText(record.objective_id),
		analysis_version: toNumber(record.analysis_version),
		source_build_id: toText(record.source_build_id),
		pipeline_version: toText(record.pipeline_version),
		model_name: nonEmptyText(record.model_name),
		prompt_versions: Object.fromEntries(
			Object.entries(normalizeUnknownRecord(record.prompt_versions)).map(([key, item]) => [
				key,
				toText(item)
			])
		),
		status: ['queued', 'running', 'succeeded', 'failed'].includes(status) ? status : 'failed',
		phase: toText(record.phase),
		processed_document_count: toNumber(record.processed_document_count),
		total_document_count: toNumber(record.total_document_count),
		current_document_id: nonEmptyText(record.current_document_id),
		progress_message: nonEmptyText(record.progress_message),
		error_code: nonEmptyText(record.error_code),
		error_message: nonEmptyText(record.error_message),
		created_at: nonEmptyText(record.created_at),
		started_at: nonEmptyText(record.started_at),
		completed_at: nonEmptyText(record.completed_at)
	};
}

export function normalizeMaterialSummary(value: unknown): MaterialSummary | null {
	const record = asRecord(value);
	if (!record) return null;

	const canonicalName = toText(
		record.canonical_name ?? record.name ?? record.material_system ?? record.material
	);
	const materialId = toText(record.material_id ?? record.id ?? record.key, canonicalName);
	if (!materialId && !canonicalName) return null;

	return {
		material_id: materialId || canonicalName,
		canonical_name: canonicalName || materialId,
		aliases: toStringList(record.aliases ?? record.names),
		paper_count: toNumber(record.paper_count ?? record.document_count),
		sample_count: toNumber(record.sample_count ?? record.sample_variant_count),
		process_families: toStringList(record.process_families ?? record.processes),
		measured_properties: toStringList(record.measured_properties ?? record.properties),
		comparison_count: toNumber(record.comparison_count ?? record.comparable_group_count),
		evidence_coverage: normalizeEvidenceCoverage(record.evidence_coverage),
		state: normalizeResearchState(record.state, 'partial'),
		links: normalizeLinkRecord(record.links),
		warnings: normalizeWarnings(record.warnings)
	};
}

export function normalizePaperMaterialSummary(value: unknown): PaperMaterialSummary | null {
	const material = normalizeMaterialSummary(value);
	if (!material) return null;

	return {
		material_id: material.material_id,
		canonical_name: material.canonical_name,
		aliases: material.aliases,
		sample_count: material.sample_count,
		process_families: material.process_families,
		measured_properties: material.measured_properties,
		comparison_count: material.comparison_count,
		evidence_coverage: material.evidence_coverage,
		links: material.links,
		warnings: material.warnings
	};
}

function normalizeMaterialPaperCoverage(value: unknown): MaterialPaperCoverage | null {
	const record = asRecord(value);
	if (!record) return null;

	const documentId = toText(record.document_id ?? record.id);
	if (!documentId) return null;

	return {
		document_id: documentId,
		title: toText(
			record.title ?? record.paper_title ?? record.source_filename,
			formatShortIdentifier(documentId)
		),
		source_filename: nonEmptyText(record.source_filename),
		state: normalizeResearchState(record.state, 'partial'),
		sample_count: toNumber(record.sample_count ?? record.sample_variant_count),
		process_families: toStringList(record.process_families ?? record.processes),
		measured_properties: toStringList(record.measured_properties ?? record.properties),
		evidence_count: toNumber(record.evidence_count),
		issue_count: toNumber(record.issue_count),
		links: normalizeLinkRecord(record.links),
		warnings: normalizeWarnings(record.warnings ?? record.primary_warnings)
	};
}

export function normalizeProcessParameterRange(value: unknown): ProcessParameterRange | null {
	const record = asRecord(value);
	if (!record) return null;

	const parameter = toText(record.parameter ?? record.name ?? record.key);
	if (!parameter) return null;

	const minValue = toScalar(record.min_value ?? record.min);
	const maxValue = toScalar(record.max_value ?? record.max);
	const unit = nonEmptyText(record.unit);
	const displayRange =
		toText(record.display_range ?? record.range ?? record.display) ||
		(minValue !== null && maxValue !== null
			? `${minValue}${unit ? ` ${unit}` : ''} - ${maxValue}${unit ? ` ${unit}` : ''}`
			: '');

	return {
		parameter,
		display_range: displayRange || '--',
		min_value: minValue,
		max_value: maxValue,
		unit,
		sample_count: toNumber(record.sample_count),
		document_count: toNumber(record.document_count ?? record.paper_count),
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

export function normalizePropertySummary(value: unknown): PropertySummary | null {
	if (typeof value === 'string') {
		const property = value.trim();
		return property
			? {
					property,
					display_range: '--',
					min_value: null,
					max_value: null,
					unit: null,
					sample_count: 0,
					document_count: 0,
					evidence_refs: [],
					warnings: []
				}
			: null;
	}

	const record = asRecord(value);
	if (!record) return null;

	const property = toText(record.property ?? record.name ?? record.key);
	if (!property) return null;

	const minValue = toScalar(record.min_value ?? record.min);
	const maxValue = toScalar(record.max_value ?? record.max);
	const unit = nonEmptyText(record.unit);
	const displayRange =
		toText(record.display_range ?? record.range ?? record.display) ||
		(minValue !== null && maxValue !== null
			? `${minValue}${unit ? ` ${unit}` : ''} - ${maxValue}${unit ? ` ${unit}` : ''}`
			: '');

	return {
		property,
		display_range: displayRange || '--',
		min_value: minValue,
		max_value: maxValue,
		unit,
		sample_count: toNumber(record.sample_count),
		document_count: toNumber(record.document_count ?? record.paper_count),
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
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

function normalizeMaterialProfileOverview(value: unknown): MaterialProfileOverview {
	const record = asRecord(value);

	return {
		paper_count: toNumber(record?.paper_count ?? record?.document_count),
		sample_count: toNumber(record?.sample_count ?? record?.sample_variant_count),
		comparison_count: toNumber(record?.comparison_count ?? record?.comparable_group_count),
		condition_series_count: toNumber(record?.condition_series_count ?? record?.series_count),
		evidence_count: toNumber(record?.evidence_count),
		process_families: toStringList(record?.process_families ?? record?.processes),
		measured_properties: toStringList(record?.measured_properties ?? record?.properties),
		variable_axes: toStringList(record?.variable_axes ?? record?.main_process_variables)
	};
}

function normalizeConditionRecords(value: unknown): Record<string, string>[] {
	return asArray(value)
		.map((item) => normalizeStringRecord(item))
		.filter((item) => Object.keys(item).length > 0);
}

export function normalizeMaterialProfile(
	value: unknown,
	collectionId: string,
	materialId: string
): MaterialProfile {
	const record = asRecord(value);
	const sampleMatrix = normalizeSampleMatrix(record?.sample_matrix);
	const comparisonGroups = normalizeObjectList(
		record?.comparison_groups ?? record?.comparable_groups,
		'items'
	)
		.map((item) => normalizeComparableGroup(item))
		.filter((item): item is ComparableGroup => item !== null);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		material_id: toText(record?.material_id ?? record?.id, materialId),
		canonical_name: toText(
			record?.canonical_name ?? record?.name ?? record?.material_system,
			materialId
		),
		aliases: toStringList(record?.aliases ?? record?.names),
		state: normalizeResearchState(
			record?.state,
			sampleMatrix.rows.length || comparisonGroups.length ? 'partial' : 'empty'
		),
		overview: normalizeMaterialProfileOverview(record?.overview),
		papers: normalizeObjectList(record?.papers ?? record?.paper_coverage, 'items')
			.map((item) => normalizeMaterialPaperCoverage(item))
			.filter((item): item is MaterialPaperCoverage => item !== null),
		sample_matrix: sampleMatrix,
		process_parameter_ranges: normalizeObjectList(
			record?.process_parameter_ranges ?? record?.process_ranges,
			'items'
		)
			.map((item) => normalizeProcessParameterRange(item))
			.filter((item): item is ProcessParameterRange => item !== null),
		measured_properties: normalizeObjectList(
			record?.measured_properties ?? record?.property_summaries ?? record?.properties,
			'items'
		)
			.map((item) => normalizePropertySummary(item))
			.filter((item): item is PropertySummary => item !== null),
		comparison_groups: comparisonGroups,
		condition_series: normalizeObjectList(record?.condition_series ?? record?.trend_series, 'items')
			.map((item) => normalizeConditionSeries(item))
			.filter((item): item is ConditionSeries => item !== null),
		evidence_refs: normalizeEvidenceReferences(record?.evidence_refs ?? record?.evidence),
		debug_links: normalizeLinkRecord(record?.debug_links),
		warnings: normalizeWarnings(record?.warnings)
	};
}

export function normalizeDocumentMaterialProfile(
	value: unknown,
	collectionId: string,
	documentId: string,
	materialId: string
): DocumentMaterialProfile {
	const record = asRecord(value);
	const sampleMatrix = normalizeSampleMatrix(record?.sample_matrix);
	const comparisons = normalizeObjectList(
		record?.within_paper_comparisons ?? record?.comparison_groups ?? record?.comparable_groups,
		'items'
	)
		.map((item) => normalizeComparableGroup(item))
		.filter((item): item is ComparableGroup => item !== null);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		document_id: toText(record?.document_id, documentId),
		material_id: toText(record?.material_id ?? record?.id, materialId),
		canonical_name: toText(
			record?.canonical_name ?? record?.name ?? record?.material_system,
			materialId
		),
		aliases: toStringList(record?.aliases ?? record?.names),
		state: normalizeResearchState(
			record?.state,
			sampleMatrix.rows.length || comparisons.length ? 'partial' : 'empty'
		),
		overview: normalizeMaterialProfileOverview(record?.overview),
		sample_matrix: {
			...sampleMatrix,
			document_id: sampleMatrix.document_id || documentId
		},
		process_conditions: normalizeConditionRecords(record?.process_conditions),
		test_conditions: normalizeConditionRecords(record?.test_conditions),
		measured_properties: normalizeObjectList(
			record?.measured_properties ?? record?.property_summaries ?? record?.properties,
			'items'
		)
			.map((item) => normalizePropertySummary(item))
			.filter((item): item is PropertySummary => item !== null),
		within_paper_comparisons: comparisons,
		condition_series: normalizeObjectList(record?.condition_series, 'items')
			.map((item) => normalizeConditionSeries(item))
			.filter((item): item is ConditionSeries => item !== null),
		evidence_refs: normalizeEvidenceReferences(record?.evidence_refs ?? record?.evidence),
		debug_links: normalizeLinkRecord(record?.debug_links),
		warnings: normalizeWarnings(record?.warnings)
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
		materials: normalizeObjectList(record?.materials, 'materials')
			.map((item) => normalizeMaterialSummary(item))
			.filter((item): item is MaterialSummary => item !== null),
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
		materials: normalizeObjectList(record?.materials ?? record?.paper_materials, 'items')
			.map((item) => normalizePaperMaterialSummary(item))
			.filter((item): item is PaperMaterialSummary => item !== null),
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

export function normalizeObjectiveList(value: unknown, collectionId: string): ObjectiveList {
	const record = asRecord(value);
	return {
		collection_id: toText(record?.collection_id, collectionId),
		objectives: asArray(record?.objectives)
			.map((item) => normalizeObjectiveSummary(item))
			.filter((item): item is ObjectiveSummary => item !== null)
	};
}

export async function fetchCollectionResearchView(
	collectionId: string
): Promise<CollectionAggregation> {
	const encoded = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encoded}/research-view`);
	return normalizeCollectionAggregation(data, collectionId);
}

export async function fetchCollectionMaterials(collectionId: string): Promise<MaterialSummary[]> {
	const encoded = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encoded}/materials`);
	return normalizeObjectList(data, 'materials')
		.map((item) => normalizeMaterialSummary(item))
		.filter((item): item is MaterialSummary => item !== null);
}

export async function fetchMaterialResearchView(
	collectionId: string,
	materialId: string
): Promise<MaterialProfile> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedMaterial = encodeURIComponent(materialId);
	const data = await requestJson(
		`/collections/${encodedCollection}/materials/${encodedMaterial}/research-view`
	);
	return normalizeMaterialProfile(data, collectionId, materialId);
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

export async function fetchCollectionObjectives(collectionId: string): Promise<ObjectiveList> {
	const encoded = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encoded}/objectives`);
	return normalizeObjectiveList(data, collectionId);
}

export async function fetchObjective(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveAnalysis> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}`
	);
	return normalizeObjectiveAnalysis(data, collectionId);
}

function normalizeObjectiveAnalysis(value: unknown, collectionId: string): ObjectiveAnalysis {
	const record = asRecord(value) ?? {};
	const objective = normalizeObjectiveSummary(record.objective);
	return {
		collection_id: toText(record.collection_id, collectionId),
		objective:
			objective ??
			({
				objective_id: '',
				question: '',
				material_scope: [],
				process_axes: [],
				property_axes: [],
				comparison_intent: null,
				seed_document_ids: [],
				excluded_document_ids: [],
				confidence: 0,
				reason: null,
				confirmation_status: 'candidate',
				active_analysis_version: null,
				published_analysis_version: null,
				collection_id: collectionId,
				created_at: null,
				updated_at: null
			} satisfies ObjectiveSummary),
		active_analysis: normalizeObjectiveAnalysisState(record.active_analysis),
		published_analysis: normalizeObjectiveAnalysisState(record.published_analysis),
		warnings: toStringList(record.warnings)
	};
}

export async function fetchObjectiveFindings(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	offset = 0,
	limit = 50
): Promise<ObjectiveFindingPage> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/findings`;
	const params = new URLSearchParams({
		analysis_version: String(analysisVersion),
		offset: String(offset),
		limit: String(limit)
	});
	return requestJson(`${path}?${params.toString()}`) as Promise<ObjectiveFindingPage>;
}

export async function fetchObjectiveEvidence(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string,
	offset = 0,
	limit = 100
): Promise<ObjectiveEvidencePage> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/evidence`;
	const params = new URLSearchParams({
		analysis_version: String(analysisVersion),
		finding_id: findingId,
		offset: String(offset),
		limit: String(limit)
	});
	return requestJson(`${path}?${params.toString()}`) as Promise<ObjectiveEvidencePage>;
}

export async function confirmObjective(collectionId: string, objectiveId: string) {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/confirm`,
		{ method: 'POST' }
	);
	return normalizeObjectiveAnalysis(data, collectionId);
}

export async function runObjectiveAnalysis(collectionId: string, objectiveId: string) {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis`,
		{ method: 'POST' }
	);
	return normalizeObjectiveAnalysis(data, collectionId);
}

export async function fetchObjectiveAnalysis(collectionId: string, objectiveId: string) {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis`
	);
	return normalizeObjectiveAnalysis(data, collectionId);
}

export async function createFindingFeedback(
	collectionId: string,
	objectiveId: string,
	findingId: string,
	payload: FindingFeedbackCreate
): Promise<FindingFeedback> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const encodedFinding = encodeURIComponent(findingId);
	return requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/findings/${encodedFinding}/feedback`,
		{
			method: 'POST',
			body: JSON.stringify(payload)
		}
	) as Promise<FindingFeedback>;
}

export async function fetchFindingFeedback(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string
): Promise<FindingFeedback[]> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const encodedFinding = encodeURIComponent(findingId);
	const data = (await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/findings/${encodedFinding}/feedback?analysis_version=${analysisVersion}`
	)) as { items?: FindingFeedback[] };
	return Array.isArray(data.items) ? data.items : [];
}

export async function createFindingCuration(
	collectionId: string,
	objectiveId: string,
	findingId: string,
	payload: FindingCurationCreate
): Promise<FindingCuration> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const encodedFinding = encodeURIComponent(findingId);
	return requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/findings/${encodedFinding}/curation`,
		{
			method: 'PUT',
			body: JSON.stringify(payload)
		}
	) as Promise<FindingCuration>;
}

export async function fetchFindingCurations(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string
): Promise<FindingCuration[]> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const encodedFinding = encodeURIComponent(findingId);
	const data = (await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/findings/${encodedFinding}/curation?analysis_version=${analysisVersion}`
	)) as { items?: FindingCuration[] };
	return Array.isArray(data.items) ? data.items : [];
}

function findingDatasetParams(filters: FindingDatasetFilters): URLSearchParams {
	const params = new URLSearchParams();
	if (filters.label_status) params.set('label_status', filters.label_status);
	if (filters.dataset_use_status) params.set('dataset_use_status', filters.dataset_use_status);
	return params;
}

export function objectiveFindingDatasetUrl(
	collectionId: string,
	objectiveId: string,
	format: 'json' | 'training_jsonl',
	filters: FindingDatasetFilters = {}
): string {
	const params = findingDatasetParams(filters);
	params.set('format', format);
	return `/api/v1/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset?${params.toString()}`;
}

export async function fetchObjectiveFindingDataset(
	collectionId: string,
	objectiveId: string,
	filters: FindingDatasetFilters = {}
): Promise<FindingDataset> {
	const params = findingDatasetParams(filters);
	const suffix = params.size ? `?${params.toString()}` : '';
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset${suffix}`
	);
	return normalizeFindingDataset(data);
}

export async function fetchDocumentMaterials(
	collectionId: string,
	documentId: string
): Promise<PaperMaterialSummary[]> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedDocument = encodeURIComponent(documentId);
	const data = await requestJson(
		`/collections/${encodedCollection}/documents/${encodedDocument}/materials`
	);
	return normalizeObjectList(data, 'materials')
		.map((item) => normalizePaperMaterialSummary(item))
		.filter((item): item is PaperMaterialSummary => item !== null);
}

export async function fetchDocumentMaterialResearchView(
	collectionId: string,
	documentId: string,
	materialId: string
): Promise<DocumentMaterialProfile> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedDocument = encodeURIComponent(documentId);
	const encodedMaterial = encodeURIComponent(materialId);
	const data = await requestJson(
		`/collections/${encodedCollection}/documents/${encodedDocument}/materials/${encodedMaterial}/research-view`
	);
	return normalizeDocumentMaterialProfile(data, collectionId, documentId, materialId);
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
