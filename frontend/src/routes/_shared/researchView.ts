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

export type ObjectiveWorkspaceReadiness = {
	objectives_ready: boolean;
	frames_ready: boolean;
	routes_ready: boolean;
	evidence_units_ready: boolean;
	logic_chain_ready: boolean;
};

export type ObjectiveSummary = {
	objective_id: string;
	question: string;
	material_scope: string[];
	process_axes: string[];
	property_axes: string[];
	comparison_intent: string | null;
	confidence: number;
};

export type ObjectiveListItem = ObjectiveSummary & {
	state: ResearchViewState;
	paper_frame_count: number;
	evidence_route_count: number;
	evidence_unit_count: number;
	logic_chain_count: number;
};

export type ObjectiveContext = {
	objective_id: string;
	question: string;
	material_scope: string[];
	variable_process_axes: string[];
	process_context_axes: string[];
	target_property_axes: string[];
	excluded_property_axes: string[];
	routing_hints: Record<string, unknown>[];
	extraction_guidance: Record<string, unknown>;
	confidence: number;
};

export type ObjectivePaperFrame = {
	frame_id: string;
	objective_id: string;
	document_id: string;
	title: string | null;
	source_filename: string | null;
	relevance: string;
	paper_role: string;
	background: string | null;
	material_match: string[];
	changed_variables: string[];
	measured_property_scope: string[];
	test_environment_scope: string[];
	relevant_sections: string[];
	relevant_tables: string[];
	excluded_tables: string[];
};

export type ObjectiveEvidenceRoute = {
	route_id: string;
	objective_id: string;
	document_id: string;
	source_kind: string;
	source_ref: string;
	role: string;
	extractable: boolean;
	reason: string | null;
	table_schema: Record<string, unknown>;
	column_roles: Record<string, unknown>;
	join_keys: Record<string, unknown>;
	join_plan: Record<string, unknown>;
	confidence: number;
};

export type ObjectiveEvidenceUnit = {
	evidence_unit_id: string;
	objective_id: string;
	document_id: string;
	unit_kind: string;
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
	source_refs: Record<string, unknown>[];
	evidence_anchor_ids: string[];
	join_keys: Record<string, unknown>;
	resolution_status: string;
	confidence: number;
};

export type ObjectiveLogicChain = {
	logic_chain_id: string;
	objective_id: string;
	chain_scope: string;
	document_id: string | null;
	question: string | null;
	evidence_unit_ids: string[];
	chain_payload: Record<string, unknown>;
	summary: string | null;
	confidence: number;
};

export type ObjectiveConclusionNarrativeClaim = {
	claim: string;
	evidence_unit_ids: string[];
	source_refs: Record<string, unknown>[];
	strength: string;
};

export type ObjectiveConclusionNarrativeSection = {
	section_id: string;
	title: string;
	body: string;
	claims: ObjectiveConclusionNarrativeClaim[];
	evidence_unit_ids: string[];
	source_refs: Record<string, unknown>[];
};

export type ObjectiveConclusionNarrative = {
	status: string;
	sections: ObjectiveConclusionNarrativeSection[];
};

export type ObjectiveConclusionContribution = {
	document_id: string;
	title: string | null;
	source_filename: string | null;
	paper_role: string;
	relevance: string;
	background: string | null;
	changed_variables: string[];
	measured_property_scope: string[];
	evidence_unit_count: number;
	evidence_unit_ids: string[];
};

export type ObjectiveConclusionMeasurementRow = {
	evidence_unit_id: string;
	document_id: string | null;
	property: string | null;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	test_condition: Record<string, unknown>;
	value: string | number | null;
	source_value_text: string | null;
	unit: string | null;
	resolution_status: string;
	source_refs: Record<string, unknown>[];
};

export type ObjectiveConclusionValueRangeEndpoint = {
	evidence_unit_id: string;
	value: string | number | null;
	unit: string | null;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	document_id: string | null;
	source_refs: Record<string, unknown>[];
};

export type ObjectiveConclusionMeasurementRange = {
	property_normalized: string;
	min: ObjectiveConclusionValueRangeEndpoint | null;
	max: ObjectiveConclusionValueRangeEndpoint | null;
	unit: string | null;
	count: number;
};

export type ObjectiveConclusionEvidenceTable = {
	table_id: string;
	title: string;
	rows: ObjectiveConclusionMeasurementRow[];
	measurement_value_ranges: ObjectiveConclusionMeasurementRange[];
};

export type ObjectiveConclusionComparison = {
	evidence_unit_id: string;
	document_id: string | null;
	property: string | null;
	comparison_axis: string | null;
	direction: string | null;
	summary: string | null;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	baseline_context: Record<string, unknown>;
	source_refs: Record<string, unknown>[];
	validity: string;
};

export type ObjectiveConclusionMechanismEvidence = {
	evidence_unit_id: string;
	document_id: string | null;
	unit_kind: string;
	property: string | null;
	summary: string | null;
	source_refs: Record<string, unknown>[];
};

export type ObjectiveConclusionMechanismStep = {
	step_role: string;
	label: string;
};

export type ObjectiveConclusionMechanismChain = {
	steps: ObjectiveConclusionMechanismStep[];
	evidence: ObjectiveConclusionMechanismEvidence[];
	evidence_unit_ids: string[];
};

export type ObjectiveConclusionStatement = {
	claim: string;
	evidence_unit_ids: string[];
	strength: string;
};

export type ObjectiveConclusionLimitation = {
	code: string;
	message: string;
	evidence_unit_ids: string[];
};

export type ObjectiveExpertFinding = {
	finding_id: string;
	statement: string;
	strength: string;
	evidence_unit_ids: string[];
	source_refs: Record<string, unknown>[];
};

export type ObjectiveExpertEvidenceMatrix = {
	relevant_paper_count: number;
	measurement_result_count: number;
	measurement_property_count: number;
	controlled_comparison_count: number;
	mechanism_evidence_count: number;
	limitation_count: number;
	source_ref_count: number;
	measurement_value_ranges: ObjectiveConclusionMeasurementRange[];
};

export type ObjectiveExpertPaperContribution = {
	document_id: string;
	paper_label: string | null;
	display_title: string | null;
	paper_role: string;
	relevance: string;
	contribution_summary: string | null;
	changed_variables: string[];
	measured_property_scope: string[];
	evidence_unit_count: number;
	evidence_unit_ids: string[];
	source_refs: Record<string, unknown>[];
};

export type ObjectiveExpertComparison = {
	comparison_id: string;
	evidence_unit_id: string;
	document_id: string | null;
	property: string | null;
	comparison_axis: string | null;
	direction: string | null;
	validity: string;
	summary: string | null;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	baseline_context: Record<string, unknown>;
	source_refs: Record<string, unknown>[];
};

export type ObjectiveExpertMechanismEvidence = {
	evidence_unit_id: string;
	document_id: string | null;
	unit_kind: string;
	property: string | null;
	summary: string | null;
	sample_context: Record<string, unknown>;
	process_context: Record<string, unknown>;
	source_refs: Record<string, unknown>[];
};

export type ObjectiveExpertMechanismChain = {
	steps: ObjectiveConclusionMechanismStep[];
	evidence: ObjectiveExpertMechanismEvidence[];
	evidence_unit_ids: string[];
};

export type ObjectiveExpertLimitation = {
	code: string;
	message: string;
	evidence_unit_ids: string[];
	source_refs: Record<string, unknown>[];
};

export type ObjectiveExpertReport = {
	schema_version: string;
	status: string;
	headline_conclusion: string;
	scientific_context: string;
	key_findings: ObjectiveExpertFinding[];
	evidence_matrix: ObjectiveExpertEvidenceMatrix;
	paper_contribution_map: ObjectiveExpertPaperContribution[];
	controlled_comparisons: ObjectiveExpertComparison[];
	mechanism_chain: ObjectiveExpertMechanismChain;
	limitations: ObjectiveExpertLimitation[];
	source_traceback: Record<string, unknown>[];
	traceability: Record<string, unknown>;
};

export type ObjectiveReportStatus = 'generating' | 'ready' | 'ready_with_warnings' | 'failed';

export type ObjectiveReportArtifact = {
	collection_id: string;
	report_id: string;
	objective_id: string;
	status: ObjectiveReportStatus;
	stage: string;
	message: string | null;
	title: string;
	language: string;
	model: string | null;
	data_version: string;
	markdown: string | null;
	warnings: string[];
	source_refs: Record<string, unknown>[];
	created_at: string;
	updated_at: string;
	generated_at: string | null;
};

export type ObjectiveConclusionPackage = {
	schema_version: string;
	title: string;
	objective: {
		objective_id: string;
		question: string;
		material_scope: string[];
		process_axes: string[];
		property_axes: string[];
	};
	status: string;
	narrative: ObjectiveConclusionNarrative;
	paper_contributions: ObjectiveConclusionContribution[];
	primary_evidence_tables: ObjectiveConclusionEvidenceTable[];
	controlled_comparisons: ObjectiveConclusionComparison[];
	mechanism_chain: ObjectiveConclusionMechanismChain;
	conclusions: ObjectiveConclusionStatement[];
	limitations: ObjectiveConclusionLimitation[];
	source_refs: Record<string, unknown>[];
	expert_report: ObjectiveExpertReport | null;
};

export type ObjectiveList = {
	collection_id: string;
	state: ResearchViewState;
	readiness: ObjectiveWorkspaceReadiness;
	objectives: ObjectiveListItem[];
	warnings: ResearchViewWarning[];
};

export type ObjectiveResearchView = {
	collection_id: string;
	state: ResearchViewState;
	objective: ObjectiveSummary;
	objective_context: ObjectiveContext | null;
	readiness: ObjectiveWorkspaceReadiness;
	paper_frames: ObjectivePaperFrame[];
	evidence_routes: ObjectiveEvidenceRoute[];
	evidence_units: ObjectiveEvidenceUnit[];
	logic_chain: ObjectiveLogicChain | null;
	conclusion_package: ObjectiveConclusionPackage | null;
	objective_report: ObjectiveReportArtifact | null;
	existing_comparison_rows: Record<string, unknown>[];
	warnings: ResearchViewWarning[];
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

export type MaterialReportPerformanceResult = {
	property: string;
	display_value: string;
	value: string | number | null;
	unit: string | null;
	condition: string | null;
	status: EvidenceBackedValueStatus;
	evidence_refs: EvidenceReference[];
	warnings: ResearchViewWarning[];
};

export type MaterialReportStateChain = {
	chain_id: string;
	document_id: string | null;
	sample_id: string;
	sample_label: string;
	material: string;
	material_state: string;
	preparation_context: Record<string, string>;
	test_conditions: Record<string, string>;
	performance_results: MaterialReportPerformanceResult[];
	source_evidence: EvidenceReference[];
	comparability_boundary: string[];
	confidence: number | null;
	unresolved_fields: string[];
};

export type MaterialReportPaperContribution = {
	document_id: string;
	title: string | null;
	source_filename: string | null;
	sample_count: number;
	measured_properties: string[];
	contribution_summary: string;
};

export type MaterialReportPackage = {
	schema_version: string;
	status: ResearchViewState;
	title: string;
	material_id: string;
	canonical_name: string;
	summary: string;
	paper_contributions: MaterialReportPaperContribution[];
	material_state_chains: MaterialReportStateChain[];
	limitations: string[];
	source_refs: EvidenceReference[];
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
	report_package: MaterialReportPackage | null;
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

function normalizeMaterialReportResult(value: unknown): MaterialReportPerformanceResult | null {
	const record = asRecord(value);
	if (!record) return null;
	const property = toText(record.property ?? record.property_normalized ?? record.name);
	if (!property) return null;

	return {
		property,
		display_value: toText(record.display_value ?? record.display ?? record.value),
		value: toScalar(record.value),
		unit: nonEmptyText(record.unit),
		condition: nonEmptyText(record.condition ?? record.test_condition),
		status: normalizeEvidenceStatus(record.status),
		evidence_refs: normalizeEvidenceReferences(record.evidence_refs ?? record.evidence),
		warnings: normalizeWarnings(record.warnings)
	};
}

function normalizeMaterialReportChain(value: unknown): MaterialReportStateChain | null {
	const record = asRecord(value);
	if (!record) return null;
	const chainId = toText(record.chain_id ?? record.id);
	const sampleId = toText(record.sample_id ?? record.variant_id ?? chainId);
	if (!chainId && !sampleId) return null;

	return {
		chain_id: chainId || sampleId,
		document_id: nonEmptyText(record.document_id),
		sample_id: sampleId || chainId,
		sample_label: toText(record.sample_label ?? record.label ?? record.material_state, sampleId),
		material: toText(record.material ?? record.material_system, '--'),
		material_state: toText(record.material_state ?? record.sample_label ?? record.label, sampleId),
		preparation_context: normalizeContextRecord(
			record.preparation_context ?? record.process_context,
			'process'
		),
		test_conditions: normalizeContextRecord(
			record.test_conditions ?? record.test_condition,
			'condition'
		),
		performance_results: normalizeObjectList(
			record.performance_results ?? record.results,
			'items'
		)
			.map((item) => normalizeMaterialReportResult(item))
			.filter((item): item is MaterialReportPerformanceResult => item !== null),
		source_evidence: normalizeEvidenceReferences(record.source_evidence ?? record.evidence_refs),
		comparability_boundary: toStringList(record.comparability_boundary ?? record.boundaries),
		confidence: toOptionalNumber(record.confidence),
		unresolved_fields: toStringList(record.unresolved_fields)
	};
}

function normalizeMaterialReportContribution(value: unknown): MaterialReportPaperContribution | null {
	const record = asRecord(value);
	if (!record) return null;
	const documentId = toText(record.document_id ?? record.id);
	if (!documentId) return null;

	return {
		document_id: documentId,
		title: nonEmptyText(record.title),
		source_filename: nonEmptyText(record.source_filename),
		sample_count: toNumber(record.sample_count),
		measured_properties: toStringList(record.measured_properties ?? record.properties),
		contribution_summary: toText(record.contribution_summary ?? record.summary, documentId)
	};
}

function normalizeMaterialReportPackage(value: unknown): MaterialReportPackage | null {
	const record = asRecord(value);
	if (!record) return null;
	const chains = normalizeObjectList(record.material_state_chains ?? record.chains, 'items')
		.map((item) => normalizeMaterialReportChain(item))
		.filter((item): item is MaterialReportStateChain => item !== null);

	return {
		schema_version: toText(record.schema_version, 'material_report_package.v1'),
		status: normalizeResearchState(record.status, chains.length ? 'partial' : 'empty'),
		title: toText(record.title, 'Material report package'),
		material_id: toText(record.material_id),
		canonical_name: toText(record.canonical_name),
		summary: toText(record.summary),
		paper_contributions: normalizeObjectList(record.paper_contributions, 'items')
			.map((item) => normalizeMaterialReportContribution(item))
			.filter((item): item is MaterialReportPaperContribution => item !== null),
		material_state_chains: chains,
		limitations: toStringList(record.limitations),
		source_refs: normalizeEvidenceReferences(record.source_refs ?? record.evidence_refs)
	};
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

function normalizeObjectiveReadiness(value: unknown): ObjectiveWorkspaceReadiness {
	const record = asRecord(value);
	return {
		objectives_ready: Boolean(record?.objectives_ready),
		frames_ready: Boolean(record?.frames_ready),
		routes_ready: Boolean(record?.routes_ready),
		evidence_units_ready: Boolean(record?.evidence_units_ready),
		logic_chain_ready: Boolean(record?.logic_chain_ready)
	};
}

function normalizeObjectiveSummary(value: unknown): ObjectiveSummary | null {
	const record = asRecord(value);
	if (!record) return null;

	const objectiveId = toText(record.objective_id ?? record.id);
	const question = toText(record.question ?? record.title);
	if (!objectiveId && !question) return null;

	return {
		objective_id: objectiveId || question,
		question: question || objectiveId,
		material_scope: toStringList(record.material_scope ?? record.materials),
		process_axes: toStringList(record.process_axes ?? record.processes),
		property_axes: toStringList(record.property_axes ?? record.properties),
		comparison_intent: nonEmptyText(record.comparison_intent ?? record.intent),
		confidence: toNumber(record.confidence)
	};
}

function normalizeObjectiveListItem(value: unknown): ObjectiveListItem | null {
	const summary = normalizeObjectiveSummary(value);
	const record = asRecord(value);
	if (!summary || !record) return null;

	return {
		...summary,
		state: normalizeResearchState(record.state, 'partial'),
		paper_frame_count: toNumber(record.paper_frame_count ?? record.frame_count),
		evidence_route_count: toNumber(record.evidence_route_count ?? record.route_count),
		evidence_unit_count: toNumber(record.evidence_unit_count ?? record.unit_count),
		logic_chain_count: toNumber(record.logic_chain_count ?? record.chain_count)
	};
}

function normalizeObjectiveContext(value: unknown): ObjectiveContext | null {
	const record = asRecord(value);
	if (!record) return null;

	const objectiveId = toText(record.objective_id ?? record.id);
	const question = toText(record.question);
	if (!objectiveId && !question) return null;

	return {
		objective_id: objectiveId || question,
		question: question || objectiveId,
		material_scope: toStringList(record.material_scope ?? record.materials),
		variable_process_axes: toStringList(record.variable_process_axes),
		process_context_axes: toStringList(record.process_context_axes),
		target_property_axes: toStringList(record.target_property_axes),
		excluded_property_axes: toStringList(record.excluded_property_axes),
		routing_hints: normalizeUnknownRecordList(record.routing_hints),
		extraction_guidance: normalizeUnknownRecord(record.extraction_guidance),
		confidence: toNumber(record.confidence)
	};
}

function normalizeObjectivePaperFrame(value: unknown): ObjectivePaperFrame | null {
	const record = asRecord(value);
	if (!record) return null;

	const frameId = toText(record.frame_id ?? record.id);
	const documentId = toText(record.document_id ?? record.paper_id);
	if (!frameId && !documentId) return null;

	return {
		frame_id: frameId || documentId,
		objective_id: toText(record.objective_id),
		document_id: documentId,
		title: nonEmptyText(record.title ?? record.paper_title),
		source_filename: nonEmptyText(record.source_filename),
		relevance: toText(record.relevance, 'uncertain'),
		paper_role: toText(record.paper_role, 'uncertain'),
		background: nonEmptyText(record.background),
		material_match: toStringList(record.material_match),
		changed_variables: toStringList(record.changed_variables),
		measured_property_scope: toStringList(record.measured_property_scope),
		test_environment_scope: toStringList(record.test_environment_scope),
		relevant_sections: toStringList(record.relevant_sections),
		relevant_tables: toStringList(record.relevant_tables),
		excluded_tables: toStringList(record.excluded_tables)
	};
}

function normalizeObjectiveEvidenceRoute(value: unknown): ObjectiveEvidenceRoute | null {
	const record = asRecord(value);
	if (!record) return null;

	const routeId = toText(record.route_id ?? record.id);
	if (!routeId) return null;

	return {
		route_id: routeId,
		objective_id: toText(record.objective_id),
		document_id: toText(record.document_id ?? record.paper_id),
		source_kind: toText(record.source_kind, 'text_window'),
		source_ref: toText(record.source_ref),
		role: toText(record.role, 'low_value_or_irrelevant'),
		extractable: Boolean(record.extractable),
		reason: nonEmptyText(record.reason),
		table_schema: normalizeUnknownRecord(record.table_schema),
		column_roles: normalizeUnknownRecord(record.column_roles),
		join_keys: normalizeUnknownRecord(record.join_keys),
		join_plan: normalizeUnknownRecord(record.join_plan),
		confidence: toNumber(record.confidence)
	};
}

function normalizeObjectiveEvidenceUnit(value: unknown): ObjectiveEvidenceUnit | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	if (!evidenceUnitId) return null;

	return {
		evidence_unit_id: evidenceUnitId,
		objective_id: toText(record.objective_id),
		document_id: toText(record.document_id ?? record.paper_id),
		unit_kind: toText(record.unit_kind, 'unknown'),
		property_normalized: nonEmptyText(record.property_normalized),
		material_system: normalizeUnknownRecord(record.material_system),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		resolved_condition: normalizeUnknownRecord(record.resolved_condition),
		test_condition: normalizeUnknownRecord(record.test_condition),
		value_payload: normalizeUnknownRecord(record.value_payload),
		unit: nonEmptyText(record.unit),
		baseline_context: normalizeUnknownRecord(record.baseline_context),
		interpretation: nonEmptyText(record.interpretation),
		source_refs: normalizeUnknownRecordList(record.source_refs),
		evidence_anchor_ids: toStringList(record.evidence_anchor_ids),
		join_keys: normalizeUnknownRecord(record.join_keys),
		resolution_status: toText(record.resolution_status, 'unknown'),
		confidence: toNumber(record.confidence)
	};
}

function normalizeObjectiveLogicChain(value: unknown): ObjectiveLogicChain | null {
	const record = asRecord(value);
	if (!record) return null;

	const logicChainId = toText(record.logic_chain_id ?? record.id);
	if (!logicChainId) return null;

	return {
		logic_chain_id: logicChainId,
		objective_id: toText(record.objective_id),
		chain_scope: toText(record.chain_scope, 'objective'),
		document_id: nonEmptyText(record.document_id ?? record.paper_id),
		question: nonEmptyText(record.question),
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		chain_payload: normalizeUnknownRecord(record.chain_payload),
		summary: nonEmptyText(record.summary),
		confidence: toNumber(record.confidence)
	};
}

function normalizeConclusionMeasurementRow(
	value: unknown,
	index: number
): ObjectiveConclusionMeasurementRow | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id, `measurement_${index + 1}`);
	return {
		evidence_unit_id: evidenceUnitId,
		document_id: nonEmptyText(record.document_id),
		property: nonEmptyText(record.property ?? record.property_normalized),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		test_condition: normalizeUnknownRecord(record.test_condition),
		value: toScalar(record.value ?? record.observed_value),
		source_value_text: nonEmptyText(record.source_value_text ?? record.display_value),
		unit: nonEmptyText(record.unit),
		resolution_status: toText(record.resolution_status, 'unknown'),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeConclusionRangeEndpoint(
	value: unknown
): ObjectiveConclusionValueRangeEndpoint | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	if (!evidenceUnitId && toScalar(record.value) === null) return null;

	return {
		evidence_unit_id: evidenceUnitId,
		value: toScalar(record.value),
		unit: nonEmptyText(record.unit),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		document_id: nonEmptyText(record.document_id),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeConclusionMeasurementRange(
	value: unknown
): ObjectiveConclusionMeasurementRange | null {
	const record = asRecord(value);
	if (!record) return null;

	const property = toText(record.property_normalized ?? record.property);
	if (!property) return null;

	return {
		property_normalized: property,
		min: normalizeConclusionRangeEndpoint(record.min),
		max: normalizeConclusionRangeEndpoint(record.max),
		unit: nonEmptyText(record.unit),
		count: toNumber(record.count)
	};
}

function normalizeConclusionEvidenceTable(value: unknown): ObjectiveConclusionEvidenceTable | null {
	const record = asRecord(value);
	if (!record) return null;

	const tableId = toText(record.table_id ?? record.id);
	if (!tableId) return null;

	return {
		table_id: tableId,
		title: toText(record.title, tableId),
		rows: asArray(record.rows)
			.map((item, index) => normalizeConclusionMeasurementRow(item, index))
			.filter((item): item is ObjectiveConclusionMeasurementRow => item !== null),
		measurement_value_ranges: asArray(record.measurement_value_ranges)
			.map((item) => normalizeConclusionMeasurementRange(item))
			.filter((item): item is ObjectiveConclusionMeasurementRange => item !== null)
	};
}

function normalizeConclusionContribution(
	value: unknown
): ObjectiveConclusionContribution | null {
	const record = asRecord(value);
	if (!record) return null;

	const documentId = toText(record.document_id ?? record.paper_id);
	if (!documentId) return null;

	return {
		document_id: documentId,
		title: nonEmptyText(record.title ?? record.paper_title),
		source_filename: nonEmptyText(record.source_filename),
		paper_role: toText(record.paper_role, 'uncertain'),
		relevance: toText(record.relevance, 'uncertain'),
		background: nonEmptyText(record.background),
		changed_variables: toStringList(record.changed_variables),
		measured_property_scope: toStringList(record.measured_property_scope),
		evidence_unit_count: toNumber(record.evidence_unit_count),
		evidence_unit_ids: toStringList(record.evidence_unit_ids)
	};
}

function normalizeConclusionComparison(value: unknown): ObjectiveConclusionComparison | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	if (!evidenceUnitId) return null;

	return {
		evidence_unit_id: evidenceUnitId,
		document_id: nonEmptyText(record.document_id),
		property: nonEmptyText(record.property ?? record.property_normalized),
		comparison_axis: nonEmptyText(record.comparison_axis),
		direction: nonEmptyText(record.direction),
		summary: nonEmptyText(record.summary ?? record.statement),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		baseline_context: normalizeUnknownRecord(record.baseline_context),
		source_refs: normalizeUnknownRecordList(record.source_refs),
		validity: toText(record.validity, 'directional')
	};
}

function normalizeConclusionMechanismEvidence(
	value: unknown
): ObjectiveConclusionMechanismEvidence | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	if (!evidenceUnitId) return null;

	return {
		evidence_unit_id: evidenceUnitId,
		document_id: nonEmptyText(record.document_id),
		unit_kind: toText(record.unit_kind, 'interpretation'),
		property: nonEmptyText(record.property ?? record.property_normalized),
		summary: nonEmptyText(record.summary ?? record.statement ?? record.interpretation),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeConclusionMechanismStep(value: unknown): ObjectiveConclusionMechanismStep | null {
	const record = asRecord(value);
	if (!record) return null;

	const label = toText(record.label ?? record.summary);
	if (!label) return null;

	return {
		step_role: toText(record.step_role ?? record.role, 'mechanism_step'),
		label
	};
}

function normalizeConclusionMechanismChain(value: unknown): ObjectiveConclusionMechanismChain {
	const record = asRecord(value);
	return {
		steps: asArray(record?.steps)
			.map((item) => normalizeConclusionMechanismStep(item))
			.filter((item): item is ObjectiveConclusionMechanismStep => item !== null),
		evidence: asArray(record?.evidence)
			.map((item) => normalizeConclusionMechanismEvidence(item))
			.filter((item): item is ObjectiveConclusionMechanismEvidence => item !== null),
		evidence_unit_ids: toStringList(record?.evidence_unit_ids)
	};
}

function normalizeConclusionStatement(value: unknown): ObjectiveConclusionStatement | null {
	const record = asRecord(value);
	if (!record) return null;

	const claim = toText(record.claim ?? record.message ?? record.summary);
	if (!claim) return null;

	return {
		claim,
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		strength: toText(record.strength, 'statement')
	};
}

function normalizeConclusionLimitation(value: unknown): ObjectiveConclusionLimitation | null {
	const record = asRecord(value);
	if (!record) return null;

	const message = toText(record.message ?? record.detail ?? record.code);
	if (!message) return null;

	return {
		code: toText(record.code, 'limitation'),
		message,
		evidence_unit_ids: toStringList(record.evidence_unit_ids)
	};
}

function normalizeObjectiveExpertFinding(value: unknown): ObjectiveExpertFinding | null {
	const record = asRecord(value);
	if (!record) return null;

	const statement = toText(record.statement ?? record.claim ?? record.summary);
	if (!statement) return null;

	return {
		finding_id: toText(record.finding_id ?? record.id, statement),
		statement,
		strength: toText(record.strength, 'evidence'),
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveExpertEvidenceMatrix(
	value: unknown
): ObjectiveExpertEvidenceMatrix {
	const record = asRecord(value);
	return {
		relevant_paper_count: toNumber(record?.relevant_paper_count),
		measurement_result_count: toNumber(record?.measurement_result_count),
		measurement_property_count: toNumber(record?.measurement_property_count),
		controlled_comparison_count: toNumber(record?.controlled_comparison_count),
		mechanism_evidence_count: toNumber(record?.mechanism_evidence_count),
		limitation_count: toNumber(record?.limitation_count),
		source_ref_count: toNumber(record?.source_ref_count),
		measurement_value_ranges: asArray(record?.measurement_value_ranges)
			.map((item) => normalizeConclusionMeasurementRange(item))
			.filter((item): item is ObjectiveConclusionMeasurementRange => item !== null)
	};
}

function normalizeObjectiveExpertPaperContribution(
	value: unknown
): ObjectiveExpertPaperContribution | null {
	const record = asRecord(value);
	if (!record) return null;

	const documentId = toText(record.document_id ?? record.paper_id);
	if (!documentId) return null;

	return {
		document_id: documentId,
		paper_label: nonEmptyText(record.paper_label),
		display_title: nonEmptyText(record.display_title ?? record.title),
		paper_role: toText(record.paper_role, 'uncertain'),
		relevance: toText(record.relevance, 'uncertain'),
		contribution_summary: nonEmptyText(record.contribution_summary ?? record.summary),
		changed_variables: toStringList(record.changed_variables),
		measured_property_scope: toStringList(record.measured_property_scope),
		evidence_unit_count: toNumber(record.evidence_unit_count),
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveExpertComparison(value: unknown): ObjectiveExpertComparison | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	const comparisonId = toText(record.comparison_id ?? record.id, evidenceUnitId);
	if (!evidenceUnitId && !comparisonId) return null;

	return {
		comparison_id: comparisonId || evidenceUnitId,
		evidence_unit_id: evidenceUnitId,
		document_id: nonEmptyText(record.document_id),
		property: nonEmptyText(record.property ?? record.property_normalized),
		comparison_axis: nonEmptyText(record.comparison_axis),
		direction: nonEmptyText(record.direction),
		validity: toText(record.validity, 'directional'),
		summary: nonEmptyText(record.summary ?? record.statement),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		baseline_context: normalizeUnknownRecord(record.baseline_context),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveExpertMechanismEvidence(
	value: unknown
): ObjectiveExpertMechanismEvidence | null {
	const record = asRecord(value);
	if (!record) return null;

	const evidenceUnitId = toText(record.evidence_unit_id ?? record.id);
	if (!evidenceUnitId) return null;

	return {
		evidence_unit_id: evidenceUnitId,
		document_id: nonEmptyText(record.document_id),
		unit_kind: toText(record.unit_kind, 'interpretation'),
		property: nonEmptyText(record.property ?? record.property_normalized),
		summary: nonEmptyText(record.summary ?? record.statement ?? record.interpretation),
		sample_context: normalizeUnknownRecord(record.sample_context),
		process_context: normalizeUnknownRecord(record.process_context),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveExpertMechanismChain(value: unknown): ObjectiveExpertMechanismChain {
	const record = asRecord(value);
	return {
		steps: asArray(record?.steps)
			.map((item) => normalizeConclusionMechanismStep(item))
			.filter((item): item is ObjectiveConclusionMechanismStep => item !== null),
		evidence: asArray(record?.evidence)
			.map((item) => normalizeObjectiveExpertMechanismEvidence(item))
			.filter((item): item is ObjectiveExpertMechanismEvidence => item !== null),
		evidence_unit_ids: toStringList(record?.evidence_unit_ids)
	};
}

function normalizeObjectiveExpertLimitation(value: unknown): ObjectiveExpertLimitation | null {
	const record = asRecord(value);
	if (!record) return null;

	const message = toText(record.message ?? record.detail ?? record.code);
	if (!message) return null;

	return {
		code: toText(record.code, 'limitation'),
		message,
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveExpertReport(value: unknown): ObjectiveExpertReport | null {
	const record = asRecord(value);
	if (!record) return null;

	const headlineConclusion = toText(record.headline_conclusion ?? record.answer);
	const scientificContext = toText(record.scientific_context ?? record.context);
	if (!headlineConclusion && !scientificContext) return null;

	return {
		schema_version: toText(record.schema_version, 'objective_expert_report.v1'),
		status: toText(record.status, 'empty'),
		headline_conclusion: headlineConclusion,
		scientific_context: scientificContext,
		key_findings: asArray(record.key_findings)
			.map((item) => normalizeObjectiveExpertFinding(item))
			.filter((item): item is ObjectiveExpertFinding => item !== null),
		evidence_matrix: normalizeObjectiveExpertEvidenceMatrix(record.evidence_matrix),
		paper_contribution_map: asArray(record.paper_contribution_map)
			.map((item) => normalizeObjectiveExpertPaperContribution(item))
			.filter((item): item is ObjectiveExpertPaperContribution => item !== null),
		controlled_comparisons: asArray(record.controlled_comparisons)
			.map((item) => normalizeObjectiveExpertComparison(item))
			.filter((item): item is ObjectiveExpertComparison => item !== null),
		mechanism_chain: normalizeObjectiveExpertMechanismChain(record.mechanism_chain),
		limitations: asArray(record.limitations)
			.map((item) => normalizeObjectiveExpertLimitation(item))
			.filter((item): item is ObjectiveExpertLimitation => item !== null),
		source_traceback: normalizeUnknownRecordList(record.source_traceback),
		traceability: normalizeUnknownRecord(record.traceability)
	};
}

function normalizeConclusionNarrativeClaim(
	value: unknown
): ObjectiveConclusionNarrativeClaim | null {
	const record = asRecord(value);
	if (!record) return null;

	const claim = toText(record.claim ?? record.message ?? record.summary);
	if (!claim) return null;

	return {
		claim,
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		source_refs: normalizeUnknownRecordList(record.source_refs),
		strength: toText(record.strength, 'statement')
	};
}

function normalizeConclusionNarrativeSection(
	value: unknown
): ObjectiveConclusionNarrativeSection | null {
	const record = asRecord(value);
	if (!record) return null;

	const sectionId = toText(record.section_id ?? record.id);
	const title = toText(record.title ?? record.heading, sectionId);
	const body = toText(record.body ?? record.summary ?? record.text);
	if (!sectionId || (!title && !body)) return null;

	return {
		section_id: sectionId,
		title,
		body,
		claims: asArray(record.claims)
			.map((item) => normalizeConclusionNarrativeClaim(item))
			.filter((item): item is ObjectiveConclusionNarrativeClaim => item !== null),
		evidence_unit_ids: toStringList(record.evidence_unit_ids),
		source_refs: normalizeUnknownRecordList(record.source_refs)
	};
}

function normalizeObjectiveConclusionPackage(value: unknown): ObjectiveConclusionPackage | null {
	const record = asRecord(value);
	if (!record) return null;

	const objectiveRecord = asRecord(record.objective);
	const title = toText(record.title ?? objectiveRecord?.question);
	if (!title) return null;
	const narrativeRecord = asRecord(record.narrative);

	return {
		schema_version: toText(record.schema_version, 'objective_conclusion_package.v1'),
		title,
		objective: {
			objective_id: toText(objectiveRecord?.objective_id ?? objectiveRecord?.id),
			question: toText(objectiveRecord?.question, title),
			material_scope: toStringList(objectiveRecord?.material_scope),
			process_axes: toStringList(objectiveRecord?.process_axes),
			property_axes: toStringList(objectiveRecord?.property_axes)
		},
		status: toText(record.status, 'empty'),
		narrative: {
			status: toText(narrativeRecord?.status, 'not_generated'),
			sections: asArray(narrativeRecord?.sections)
				.map((item) => normalizeConclusionNarrativeSection(item))
				.filter((item): item is ObjectiveConclusionNarrativeSection => item !== null)
		},
		paper_contributions: asArray(record.paper_contributions)
			.map((item) => normalizeConclusionContribution(item))
			.filter((item): item is ObjectiveConclusionContribution => item !== null),
		primary_evidence_tables: asArray(record.primary_evidence_tables)
			.map((item) => normalizeConclusionEvidenceTable(item))
			.filter((item): item is ObjectiveConclusionEvidenceTable => item !== null),
		controlled_comparisons: asArray(record.controlled_comparisons)
			.map((item) => normalizeConclusionComparison(item))
			.filter((item): item is ObjectiveConclusionComparison => item !== null),
		mechanism_chain: normalizeConclusionMechanismChain(record.mechanism_chain),
		conclusions: asArray(record.conclusions)
			.map((item) => normalizeConclusionStatement(item))
			.filter((item): item is ObjectiveConclusionStatement => item !== null),
		limitations: asArray(record.limitations)
			.map((item) => normalizeConclusionLimitation(item))
			.filter((item): item is ObjectiveConclusionLimitation => item !== null),
		source_refs: normalizeUnknownRecordList(record.source_refs),
		expert_report: normalizeObjectiveExpertReport(record.expert_report)
	};
}

function normalizeObjectiveReportArtifact(value: unknown): ObjectiveReportArtifact | null {
	const record = asRecord(value);
	if (!record) return null;

	const reportId = toText(record.report_id);
	const objectiveId = toText(record.objective_id);
	if (!reportId || !objectiveId) return null;

	const status = toText(record.status, 'generating') as ObjectiveReportStatus;
	const normalizedStatus: ObjectiveReportStatus = [
		'generating',
		'ready',
		'ready_with_warnings',
		'failed'
	].includes(status)
		? status
		: 'generating';

	return {
		collection_id: toText(record.collection_id),
		report_id: reportId,
		objective_id: objectiveId,
		status: normalizedStatus,
		stage: toText(record.stage, normalizedStatus),
		message: nonEmptyText(record.message),
		title: toText(record.title, 'Research objective report'),
		language: toText(record.language, 'zh'),
		model: nonEmptyText(record.model),
		data_version: toText(record.data_version),
		markdown: nonEmptyText(record.markdown),
		warnings: toStringList(record.warnings),
		source_refs: normalizeUnknownRecordList(record.source_refs),
		created_at: toText(record.created_at),
		updated_at: toText(record.updated_at),
		generated_at: nonEmptyText(record.generated_at)
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
		report_package: normalizeMaterialReportPackage(record?.report_package),
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
	const objectives = normalizeObjectList(record?.objectives, 'objectives')
		.map((item) => normalizeObjectiveListItem(item))
		.filter((item): item is ObjectiveListItem => item !== null);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		state: normalizeResearchState(record?.state, objectives.length ? 'partial' : 'empty'),
		readiness: normalizeObjectiveReadiness(record?.readiness),
		objectives,
		warnings: normalizeWarnings(record?.warnings)
	};
}

export function normalizeObjectiveResearchView(
	value: unknown,
	collectionId: string,
	objectiveId: string
): ObjectiveResearchView {
	const record = asRecord(value);
	const objective = normalizeObjectiveSummary(record?.objective) ?? {
		objective_id: objectiveId,
		question: objectiveId,
		material_scope: [],
		process_axes: [],
		property_axes: [],
		comparison_intent: null,
		confidence: 0
	};
	const paperFrames = asArray(record?.paper_frames)
		.map((item) => normalizeObjectivePaperFrame(item))
		.filter((item): item is ObjectivePaperFrame => item !== null);
	const evidenceRoutes = asArray(record?.evidence_routes)
		.map((item) => normalizeObjectiveEvidenceRoute(item))
		.filter((item): item is ObjectiveEvidenceRoute => item !== null);
	const evidenceUnits = asArray(record?.evidence_units)
		.map((item) => normalizeObjectiveEvidenceUnit(item))
		.filter((item): item is ObjectiveEvidenceUnit => item !== null);

	return {
		collection_id: toText(record?.collection_id, collectionId),
		state: normalizeResearchState(record?.state, paperFrames.length ? 'partial' : 'empty'),
		objective,
		objective_context: normalizeObjectiveContext(record?.objective_context),
		readiness: normalizeObjectiveReadiness(record?.readiness),
		paper_frames: paperFrames,
		evidence_routes: evidenceRoutes,
		evidence_units: evidenceUnits,
		logic_chain: normalizeObjectiveLogicChain(record?.logic_chain),
		conclusion_package: normalizeObjectiveConclusionPackage(record?.conclusion_package),
		objective_report: normalizeObjectiveReportArtifact(record?.objective_report),
		existing_comparison_rows: normalizeUnknownRecordList(record?.existing_comparison_rows),
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

export async function fetchObjectiveResearchView(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveResearchView> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/research-view`
	);
	return normalizeObjectiveResearchView(data, collectionId, objectiveId);
}

export async function fetchObjectiveReport(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveReportArtifact> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/report`
	);
	const report = normalizeObjectiveReportArtifact(data);
	if (!report) {
		throw new Error('Invalid objective report response');
	}
	return report;
}

export async function createObjectiveReport(
	collectionId: string,
	objectiveId: string,
	options: { language?: 'zh' | 'en'; force_regenerate?: boolean } = {}
): Promise<ObjectiveReportArtifact> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/report`,
		{
			method: 'POST',
			body: JSON.stringify({
				language: options.language ?? 'zh',
				force_regenerate: options.force_regenerate ?? false
			})
		}
	);
	const report = normalizeObjectiveReportArtifact(data);
	if (!report) {
		throw new Error('Invalid objective report response');
	}
	return report;
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
