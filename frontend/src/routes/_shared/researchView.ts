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

export type ResearchUnderstandingState = 'empty' | 'partial' | 'ready' | 'limited';
export type ResearchUnderstandingScope = {
	scope_type: string;
	collection_id: string;
	goal_id?: string | null;
	material_id: string | null;
	objective_id: string | null;
	document_id: string | null;
	title: string | null;
};
export type ResearchUnderstandingEvidenceRef = {
	evidence_ref_id: string;
	source_kind: string;
	document_id: string | null;
	label: string;
	locator: Record<string, unknown>;
	fact_ids: string[];
	anchor_ids: string[];
	confidence: number | null;
	traceability_status: string;
	evidence_role: string | null;
	quote: string | null;
	href: string | null;
};
export type ResearchUnderstandingContext = {
	context_id: string;
	label: string;
	material_scope: string[];
	process_context: Record<string, unknown>;
	test_condition: Record<string, unknown>;
	property_scope: string[];
	limitations: string[];
};
export type ResearchUnderstandingClaim = {
	claim_id: string;
	claim_type: string;
	statement: string;
	status: string;
	confidence: number | null;
	strength: string | null;
	evidence_ref_ids: string[];
	context_ids: string[];
	source_object_ids: string[];
	warnings: string[];
};
export type ResearchUnderstandingRelation = {
	relation_id: string;
	relation_type: string;
	subject: string;
	predicate: string;
	object: string;
	statement: string | null;
	conditions: string[];
	status: string;
	confidence: number | null;
	evidence_ref_ids: string[];
	context_ids: string[];
	source_object_ids: string[];
	warnings: string[];
};
export type ResearchUnderstandingPresentationSummary = {
	title: string;
	material_scope: string[];
	variable_axes: string[];
	property_scope: string[];
	claim_count: number;
	relation_count: number;
	evidence_count: number;
	context_count: number;
	review_queue_count: number;
	primary_finding_count: number;
	review_queue_finding_count: number;
	collection_document_count: number;
	axis_coverage: ResearchUnderstandingAxisCoverage;
};
export type ResearchUnderstandingAxisCoverageItem = {
	axis: string;
	status: 'primary' | 'review_queue' | 'mechanism' | 'context' | 'missing';
	finding_id: string;
};
export type ResearchUnderstandingAxisCoverage = {
	variables: ResearchUnderstandingAxisCoverageItem[];
	properties: ResearchUnderstandingAxisCoverageItem[];
};
export type ResearchUnderstandingPresentationEffect = {
	effect_id: string;
	claim_id: string;
	title: string;
	statement: string;
	claim_type: string;
	support_status: string;
	confidence: number | null;
	effect_direction: string;
	variable_axis: string;
	target_property: string;
	paper_count: number;
	evidence_count: number;
	context_summary: string;
	evidence_ref_ids: string[];
	context_ids: string[];
	relation_ids: string[];
	needs_review: boolean;
	warnings: string[];
};
export type ResearchUnderstandingPresentationEvidenceBundle = {
	direct_result: string[];
	mechanism: string[];
	condition_context: string[];
	background: string[];
	conflict: string[];
	noise: string[];
	uncategorized: string[];
};
export type ResearchUnderstandingPresentationFinding = {
	finding_id: string;
	claim_id: string;
	title: string;
	statement: string;
	variables: string[];
	mediators: string[];
	outcomes: string[];
	direction: string;
	scope_summary: string;
	support_grade: string;
	review_status: string;
	confidence: number | null;
	paper_count: number;
	evidence_count: number;
	evidence_ref_ids: string[];
	context_ids: string[];
	relation_ids: string[];
	evidence_bundle: ResearchUnderstandingPresentationEvidenceBundle;
	comparison_summary: ResearchUnderstandingPresentationComparisonSummary | null;
	expert_use_status: string;
	dataset_use_status: string;
	generalization_status: string;
	generalization_note: string;
	evidence_gap_summary: string;
	upgrade_actions: string[];
	related_review_finding_ids: string[];
	review_reasons: string[];
	warnings: string[];
};
export type ResearchUnderstandingPresentationComparisonValue = {
	label: string;
	value: string;
};
export type ResearchUnderstandingPresentationControlledCondition = {
	axis: string;
	value: string;
};
export type ResearchUnderstandingPresentationComparisonSummary = {
	variable: string;
	direction: string;
	outcome: string;
	baseline: ResearchUnderstandingPresentationComparisonValue;
	observed: ResearchUnderstandingPresentationComparisonValue;
	controlled_conditions: ResearchUnderstandingPresentationControlledCondition[];
};
export type ResearchUnderstandingPresentationEvidence = {
	evidence_ref_id: string;
	document_id: string | null;
	title: string;
	source_label: string;
	source_kind: string;
	source_ref: string | null;
	block_type: string | null;
	heading_path: string | null;
	page: string | null;
	quote: string | null;
	source_text: string | null;
	value_summary: string;
	table_audit: ResearchUnderstandingPresentationTableAudit | null;
	traceability_status: string;
	evidence_role: string | null;
	confidence: number | null;
	href: string | null;
};
export type ResearchUnderstandingPresentationTableAudit = {
	columns: string[];
	relevant_rows: ResearchUnderstandingPresentationTableRow[];
};
export type ResearchUnderstandingPresentationTableRow = {
	row_index: number;
	cells: string[];
	aligned: boolean;
};
export type ResearchUnderstandingPresentationContext = {
	context_id: string;
	label: string;
	material_scope: string[];
	property_scope: string[];
	process_summary: string;
	test_summary: string;
	limitations: string[];
};
export type ResearchUnderstandingPresentation = {
	summary: ResearchUnderstandingPresentationSummary;
	effects: ResearchUnderstandingPresentationEffect[];
	findings: ResearchUnderstandingPresentationFinding[];
	primary_findings: ResearchUnderstandingPresentationFinding[];
	review_queue_findings: ResearchUnderstandingPresentationFinding[];
	evidence_items: ResearchUnderstandingPresentationEvidence[];
	context_summaries: ResearchUnderstandingPresentationContext[];
};
export type ResearchUnderstanding = {
	schema_version: string;
	state: ResearchUnderstandingState;
	scope: ResearchUnderstandingScope;
	claims: ResearchUnderstandingClaim[];
	relations: ResearchUnderstandingRelation[];
	evidence_refs: ResearchUnderstandingEvidenceRef[];
	contexts: ResearchUnderstandingContext[];
	warnings: string[];
	summary: {
		claim_count: number;
		relation_count: number;
		evidence_ref_count: number;
		context_count: number;
	};
	presentation: ResearchUnderstandingPresentation;
};
export type ResearchUnderstandingFeedbackStatus = 'correct' | 'incorrect' | 'partial' | 'unclear';
export type ResearchUnderstandingFeedbackIssueType =
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
export type ResearchUnderstandingFeedbackCreate = {
	scope_type: string;
	scope_id: string;
	finding_id: string;
	claim_id?: string | null;
	review_status: ResearchUnderstandingFeedbackStatus;
	issue_type: ResearchUnderstandingFeedbackIssueType;
	note?: string | null;
	reviewer?: string | null;
};
export type ResearchUnderstandingFeedback = ResearchUnderstandingFeedbackCreate & {
	feedback_id: string;
	collection_id: string;
	created_at: string;
};
export type ResearchUnderstandingFeedbackFilters = {
	scope_type?: string;
	scope_id?: string;
	finding_id?: string;
	claim_id?: string;
};
export type ResearchUnderstandingCurationCreate = {
	scope_type: string;
	scope_id: string;
	finding_id: string;
	claim_id?: string | null;
	curated_claim_type: string;
	curated_status: string;
	curated_statement: string;
	curated_support_grade?: string | null;
	curated_review_status?: string | null;
	curated_variables?: string[];
	curated_mediators?: string[];
	curated_outcomes?: string[];
	curated_direction?: string | null;
	curated_scope_summary?: string | null;
	curated_evidence_ref_ids: string[];
	curated_context_ids: string[];
	note?: string | null;
	reviewer?: string | null;
};
export type ResearchUnderstandingCuration = ResearchUnderstandingCurationCreate & {
	curation_id: string;
	collection_id: string;
	updated_at: string;
};
export type ResearchUnderstandingCurationFilters = {
	scope_type?: string;
	scope_id?: string;
	finding_id?: string;
	claim_id?: string;
};
export type ResearchUnderstandingGoldDraftItem = {
	gold_item_id: string;
	document_id: string;
	family: string;
	item_key: string;
	payload: Record<string, unknown>;
	evidence_refs: Record<string, unknown>[];
	metadata: Record<string, unknown>;
};
export type ResearchUnderstandingGoldDraft = {
	collection_id: string;
	scope_type: string;
	scope_id: string;
	gold_id: string;
	target_layer: string;
	metric_profile: string;
	item_count: number;
	items: ResearchUnderstandingGoldDraftItem[];
};
export type ResearchUnderstandingGoldDraftFilters = {
	scope_type: string;
	scope_id: string;
};
export type ResearchUnderstandingDatasetLabelStatus = 'candidate' | 'silver' | 'gold' | 'rejected';
export type ResearchUnderstandingDatasetUseStatus =
	| 'training_ready'
	| 'review_candidate'
	| 'rejected';
export type ResearchUnderstandingDatasetExportFormat = 'json' | 'jsonl' | 'messages_jsonl';
export type ResearchUnderstandingDatasetFilters = {
	scope_type: string;
	scope_id: string;
	label_status?: ResearchUnderstandingDatasetLabelStatus;
	dataset_use_status?: ResearchUnderstandingDatasetUseStatus;
};
export type ResearchUnderstandingCollectionDatasetFilters = {
	scope_type: string;
	label_status?: ResearchUnderstandingDatasetLabelStatus;
	dataset_use_status?: ResearchUnderstandingDatasetUseStatus;
};
export type ResearchUnderstandingDataset = {
	schema_version: string;
	dataset_id: string;
	collection_id: string;
	scope_type: string;
	scope_id: string;
	task_type: string;
	metric_profile: string;
	label_status_filter: ResearchUnderstandingDatasetLabelStatus | null;
	dataset_use_status_filter: ResearchUnderstandingDatasetUseStatus | null;
	item_count: number;
	label_counts: Record<ResearchUnderstandingDatasetLabelStatus, number>;
	quality_summary: {
		training_ready_sample_count: number;
		training_message_sample_count: number;
		review_candidate_sample_count: number;
		next_review_finding_id: string;
		by_dataset_use_status: Record<ResearchUnderstandingDatasetUseStatus, number>;
		by_presentation_bucket: Record<string, number>;
		by_error_category: Record<string, number>;
	};
	warnings: string[];
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
	understanding: ResearchUnderstanding | null;
	existing_comparison_rows: Record<string, unknown>[];
	warnings: ResearchViewWarning[];
};

export type ConfirmedGoalStatus = 'pending' | 'running' | 'ready' | 'failed';
export type GoalAnalysisProgress = {
	phase: string;
	current: number | null;
	total: number | null;
	unit: string | null;
	message: string | null;
	active_document_id: string | null;
	active_document_title: string | null;
	active_source_filename: string | null;
	active_objective_id: string | null;
};
export type ConfirmedGoal = {
	goal_id: string;
	collection_id: string;
	question: string;
	source_type: string;
	material_hints: string[];
	process_hints: string[];
	property_hints: string[];
	source_objective_id: string | null;
	status: ConfirmedGoalStatus;
	analysis_error: string | null;
	analysis_progress: GoalAnalysisProgress | null;
	created_at: string | null;
	updated_at: string | null;
};
export type ConfirmedGoalList = {
	collection_id: string;
	goals: ConfirmedGoal[];
};
export type GoalAnalysis = {
	collection_id: string;
	goal: ConfirmedGoal;
	understanding: ResearchUnderstanding | null;
	pipeline_nodes: Record<string, Record<string, unknown>>;
	errors: string[];
	warnings: string[];
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
	understanding: ResearchUnderstanding | null;
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

function toNumberRecord(value: unknown): Record<string, number> {
	const record = asRecord(value);
	if (!record) return {};
	return Object.fromEntries(
		Object.entries(record)
			.map(([key, item]) => [key, toNumber(item)] as const)
			.filter(([, item]) => item > 0)
	);
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

function normalizeResearchUnderstandingDataset(value: unknown): ResearchUnderstandingDataset {
	const record = asRecord(value);
	const rawLabelCounts = asRecord(record?.label_counts) ?? {};
	const qualitySummary = asRecord(record?.quality_summary) ?? {};
	const rawUseCounts = asRecord(qualitySummary.by_dataset_use_status) ?? {};
	return {
		schema_version: toText(record?.schema_version, 'research_understanding_dataset.v1'),
		dataset_id: toText(record?.dataset_id),
		collection_id: toText(record?.collection_id),
		scope_type: toText(record?.scope_type),
		scope_id: toText(record?.scope_id),
		task_type: toText(record?.task_type, 'research_understanding_finding'),
		metric_profile: toText(record?.metric_profile),
		label_status_filter:
			normalizeResearchUnderstandingDatasetLabelStatus(record?.label_status_filter),
		dataset_use_status_filter: normalizeResearchUnderstandingDatasetUseStatus(
			record?.dataset_use_status_filter
		),
		item_count: toNumber(record?.item_count),
		label_counts: {
			candidate: toNumber(rawLabelCounts.candidate),
			silver: toNumber(rawLabelCounts.silver),
			gold: toNumber(rawLabelCounts.gold),
			rejected: toNumber(rawLabelCounts.rejected)
		},
		quality_summary: {
			training_ready_sample_count: toNumber(qualitySummary.training_ready_sample_count),
			training_message_sample_count: toNumber(qualitySummary.training_message_sample_count),
			review_candidate_sample_count: toNumber(qualitySummary.review_candidate_sample_count),
			next_review_finding_id: toText(qualitySummary.next_review_finding_id),
			by_dataset_use_status: {
				training_ready: toNumber(rawUseCounts.training_ready),
				review_candidate: toNumber(rawUseCounts.review_candidate),
				rejected: toNumber(rawUseCounts.rejected)
			},
			by_presentation_bucket: toNumberRecord(qualitySummary.by_presentation_bucket),
			by_error_category: toNumberRecord(qualitySummary.by_error_category)
		},
		warnings: toStringList(record?.warnings)
	};
}

function normalizeResearchUnderstandingDatasetLabelStatus(
	value: unknown
): ResearchUnderstandingDatasetLabelStatus | null {
	const status = toText(value) as ResearchUnderstandingDatasetLabelStatus;
	return ['candidate', 'silver', 'gold', 'rejected'].includes(status) ? status : null;
}

function normalizeResearchUnderstandingDatasetUseStatus(
	value: unknown
): ResearchUnderstandingDatasetUseStatus | null {
	const status = toText(value) as ResearchUnderstandingDatasetUseStatus;
	return ['training_ready', 'review_candidate', 'rejected'].includes(status) ? status : null;
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

function normalizeUnderstandingState(value: unknown): ResearchUnderstandingState {
	const state = toText(value) as ResearchUnderstandingState;
	return ['empty', 'partial', 'ready', 'limited'].includes(state) ? state : 'empty';
}

function normalizeResearchUnderstanding(value: unknown): ResearchUnderstanding | null {
	const record = asRecord(value);
	if (!record) return null;
	const scope = normalizeResearchUnderstandingScope(record.scope);
	const claims = asArray(record.claims)
		.map((item) => normalizeResearchUnderstandingClaim(item))
		.filter((item): item is ResearchUnderstandingClaim => item !== null);
	const relations = asArray(record.relations)
		.map((item) => normalizeResearchUnderstandingRelation(item))
		.filter((item): item is ResearchUnderstandingRelation => item !== null);
	const evidenceRefs = asArray(record.evidence_refs)
		.map((item) => normalizeResearchUnderstandingEvidenceRef(item))
		.filter((item): item is ResearchUnderstandingEvidenceRef => item !== null);
	const contexts = asArray(record.contexts)
		.map((item) => normalizeResearchUnderstandingContext(item))
		.filter((item): item is ResearchUnderstandingContext => item !== null);
	const summary = {
		claim_count: toNumber((asRecord(record.summary) ?? {}).claim_count, claims.length),
		relation_count: toNumber((asRecord(record.summary) ?? {}).relation_count, relations.length),
		evidence_ref_count: toNumber(
			(asRecord(record.summary) ?? {}).evidence_ref_count,
			evidenceRefs.length
		),
		context_count: toNumber((asRecord(record.summary) ?? {}).context_count, contexts.length)
	};
	return {
		schema_version: toText(record.schema_version, 'research_understanding.v1'),
		state: normalizeUnderstandingState(record.state),
		scope,
		claims,
		relations,
		evidence_refs: evidenceRefs,
		contexts,
		warnings: toStringList(record.warnings),
		summary,
		presentation: normalizeResearchUnderstandingPresentation(record.presentation, {
			scope,
			summary
		})
	};
}

function normalizeResearchUnderstandingScope(value: unknown): ResearchUnderstandingScope {
	const record = asRecord(value);
	return {
		scope_type: toText(record?.scope_type, 'collection'),
		collection_id: toText(record?.collection_id),
		goal_id: nonEmptyText(record?.goal_id),
		material_id: nonEmptyText(record?.material_id),
		objective_id: nonEmptyText(record?.objective_id),
		document_id: nonEmptyText(record?.document_id),
		title: nonEmptyText(record?.title)
	};
}

function normalizeResearchUnderstandingEvidenceRef(
	value: unknown
): ResearchUnderstandingEvidenceRef | null {
	const record = asRecord(value);
	if (!record) return null;
	const evidenceRefId = toText(record.evidence_ref_id ?? record.id);
	if (!evidenceRefId) return null;
	return {
		evidence_ref_id: evidenceRefId,
		source_kind: toText(record.source_kind, 'unknown'),
		document_id: nonEmptyText(record.document_id),
		label: toText(record.label, evidenceRefId),
		locator: normalizeUnknownRecord(record.locator),
		fact_ids: toStringList(record.fact_ids),
		anchor_ids: toStringList(record.anchor_ids),
		confidence: toOptionalNumber(record.confidence),
		traceability_status: toText(record.traceability_status, 'unknown'),
		evidence_role: nonEmptyText(record.evidence_role),
		quote: nonEmptyText(record.quote),
		href: nonEmptyText(record.href)
	};
}

function normalizeResearchUnderstandingContext(
	value: unknown
): ResearchUnderstandingContext | null {
	const record = asRecord(value);
	if (!record) return null;
	const contextId = toText(record.context_id ?? record.id);
	if (!contextId) return null;
	return {
		context_id: contextId,
		label: toText(record.label, contextId),
		material_scope: toStringList(record.material_scope),
		process_context: normalizeUnknownRecord(record.process_context),
		test_condition: normalizeUnknownRecord(record.test_condition),
		property_scope: toStringList(record.property_scope),
		limitations: toStringList(record.limitations)
	};
}

function normalizeResearchUnderstandingClaim(value: unknown): ResearchUnderstandingClaim | null {
	const record = asRecord(value);
	if (!record) return null;
	const statement = toText(record.statement ?? record.claim);
	if (!statement) return null;
	return {
		claim_id: toText(record.claim_id ?? record.id, statement),
		claim_type: toText(record.claim_type ?? record.type, 'finding'),
		statement,
		status: toText(record.status, 'limited'),
		confidence: toOptionalNumber(record.confidence),
		strength: nonEmptyText(record.strength),
		evidence_ref_ids: toStringList(record.evidence_ref_ids),
		context_ids: toStringList(record.context_ids),
		source_object_ids: toStringList(record.source_object_ids),
		warnings: toStringList(record.warnings)
	};
}

function normalizeResearchUnderstandingRelation(
	value: unknown
): ResearchUnderstandingRelation | null {
	const record = asRecord(value);
	if (!record) return null;
	const subject = toText(record.subject);
	const object = toText(record.object);
	if (!subject && !object) return null;
	return {
		relation_id: toText(record.relation_id ?? record.id, `${subject}:${object}`),
		relation_type: toText(record.relation_type, 'compares'),
		subject,
		predicate: toText(record.predicate, 'compares'),
		object,
		statement: toText(record.statement) || null,
		conditions: toStringList(record.conditions),
		status: toText(record.status, 'limited'),
		confidence: toOptionalNumber(record.confidence),
		evidence_ref_ids: toStringList(record.evidence_ref_ids),
		context_ids: toStringList(record.context_ids),
		source_object_ids: toStringList(record.source_object_ids),
		warnings: toStringList(record.warnings)
	};
}

function normalizeResearchUnderstandingPresentation(
	value: unknown,
	fallback: {
		scope: ResearchUnderstandingScope;
		summary: ResearchUnderstanding['summary'];
	}
): ResearchUnderstandingPresentation {
	const record = asRecord(value);
	if (!record) return emptyResearchUnderstandingPresentation(fallback);
	const summaryRecord = asRecord(record.summary) ?? {};
	const effects = asArray(record.effects)
		.map((item) => normalizeResearchUnderstandingPresentationEffect(item))
		.filter((item): item is ResearchUnderstandingPresentationEffect => item !== null);
	const findings = asArray(record.findings)
		.map((item) => normalizeResearchUnderstandingPresentationFinding(item))
		.filter((item): item is ResearchUnderstandingPresentationFinding => item !== null);
	const primaryFindingsSource = Array.isArray(record.primary_findings)
		? record.primary_findings
		: findings;
	const reviewQueueFindingsSource = Array.isArray(record.review_queue_findings)
		? record.review_queue_findings
		: findings;
	const primaryFindings = primaryFindingsSource
		.map((item) => normalizeResearchUnderstandingPresentationFinding(item))
		.filter((item): item is ResearchUnderstandingPresentationFinding => item !== null);
	const reviewQueueFindings = reviewQueueFindingsSource
		.map((item) => normalizeResearchUnderstandingPresentationFinding(item))
		.filter((item): item is ResearchUnderstandingPresentationFinding => item !== null);
	const evidenceItems = asArray(record.evidence_items)
		.map((item) => normalizeResearchUnderstandingPresentationEvidence(item))
		.filter((item): item is ResearchUnderstandingPresentationEvidence => item !== null);
	const contextSummaries = asArray(record.context_summaries)
		.map((item) => normalizeResearchUnderstandingPresentationContext(item))
		.filter((item): item is ResearchUnderstandingPresentationContext => item !== null);
	return {
		summary: {
			title: toText(summaryRecord.title, fallback.scope.title ?? 'Research understanding'),
			material_scope: toStringList(summaryRecord.material_scope),
			variable_axes: toStringList(summaryRecord.variable_axes),
			property_scope: toStringList(summaryRecord.property_scope),
			claim_count: toNumber(summaryRecord.claim_count, fallback.summary.claim_count),
			relation_count: toNumber(summaryRecord.relation_count, fallback.summary.relation_count),
			evidence_count: toNumber(summaryRecord.evidence_count, fallback.summary.evidence_ref_count),
			context_count: toNumber(summaryRecord.context_count, fallback.summary.context_count),
			review_queue_count: toNumber(summaryRecord.review_queue_count, 0),
			primary_finding_count: toNumber(summaryRecord.primary_finding_count, primaryFindings.length),
			review_queue_finding_count: toNumber(
				summaryRecord.review_queue_finding_count,
				reviewQueueFindings.length
			),
			collection_document_count: toNumber(summaryRecord.collection_document_count, 0),
			axis_coverage: normalizeResearchUnderstandingAxisCoverage(summaryRecord.axis_coverage)
		},
		effects,
		findings,
		primary_findings: primaryFindings,
		review_queue_findings: reviewQueueFindings,
		evidence_items: evidenceItems,
		context_summaries: contextSummaries
	};
}

function normalizeResearchUnderstandingAxisCoverage(
	value: unknown
): ResearchUnderstandingAxisCoverage {
	const record = asRecord(value);
	return {
		variables: asArray(record?.variables)
			.map((item) => normalizeResearchUnderstandingAxisCoverageItem(item))
			.filter((item): item is ResearchUnderstandingAxisCoverageItem => item !== null),
		properties: asArray(record?.properties)
			.map((item) => normalizeResearchUnderstandingAxisCoverageItem(item))
			.filter((item): item is ResearchUnderstandingAxisCoverageItem => item !== null)
	};
}

function normalizeResearchUnderstandingAxisCoverageItem(
	value: unknown
): ResearchUnderstandingAxisCoverageItem | null {
	const record = asRecord(value);
	if (!record) return null;
	const axis = toText(record.axis);
	if (!axis) return null;
	const status = toText(record.status);
	return {
		axis,
		status: ['primary', 'review_queue', 'mechanism', 'context', 'missing'].includes(status)
			? (status as ResearchUnderstandingAxisCoverageItem['status'])
			: 'missing',
		finding_id: toText(record.finding_id)
	};
}

function normalizeResearchUnderstandingPresentationEffect(
	value: unknown
): ResearchUnderstandingPresentationEffect | null {
	const record = asRecord(value);
	if (!record) return null;
	const claimId = toText(record.claim_id);
	const statement = toText(record.statement);
	if (!claimId && !statement) return null;
	return {
		effect_id: toText(record.effect_id, claimId || statement),
		claim_id: claimId || statement,
		title: toText(record.title, statement || 'Research finding'),
		statement,
		claim_type: toText(record.claim_type, 'finding'),
		support_status: toText(record.support_status, 'limited'),
		confidence: toOptionalNumber(record.confidence),
		effect_direction: toText(record.effect_direction),
		variable_axis: toText(record.variable_axis),
		target_property: toText(record.target_property),
		paper_count: toNumber(record.paper_count, 0),
		evidence_count: toNumber(record.evidence_count, 0),
		context_summary: toText(record.context_summary),
		evidence_ref_ids: toStringList(record.evidence_ref_ids),
		context_ids: toStringList(record.context_ids),
		relation_ids: toStringList(record.relation_ids),
		needs_review: Boolean(record.needs_review),
		warnings: toStringList(record.warnings)
	};
}

function emptyResearchUnderstandingPresentationEvidenceBundle(): ResearchUnderstandingPresentationEvidenceBundle {
	return {
		direct_result: [],
		mechanism: [],
		condition_context: [],
		background: [],
		conflict: [],
		noise: [],
		uncategorized: []
	};
}

function normalizeResearchUnderstandingPresentationEvidenceBundle(
	value: unknown
): ResearchUnderstandingPresentationEvidenceBundle {
	const record = asRecord(value);
	if (!record) return emptyResearchUnderstandingPresentationEvidenceBundle();
	return {
		direct_result: toStringList(record.direct_result),
		mechanism: toStringList(record.mechanism),
		condition_context: toStringList(record.condition_context),
		background: toStringList(record.background),
		conflict: toStringList(record.conflict),
		noise: toStringList(record.noise),
		uncategorized: toStringList(record.uncategorized)
	};
}

function normalizeResearchUnderstandingPresentationFinding(
	value: unknown
): ResearchUnderstandingPresentationFinding | null {
	const record = asRecord(value);
	if (!record) return null;
	const claimId = toText(record.claim_id);
	const statement = toText(record.statement);
	if (!claimId && !statement) return null;
	return {
		finding_id: toText(record.finding_id, claimId || statement),
		claim_id: claimId || statement,
		title: toText(record.title, statement || 'Research finding'),
		statement,
		variables: toStringList(record.variables),
		mediators: toStringList(record.mediators),
		outcomes: toStringList(record.outcomes),
		direction: toText(record.direction),
		scope_summary: toText(record.scope_summary),
		support_grade: toText(record.support_grade, 'weak'),
		review_status: toText(record.review_status, 'pending_review'),
		confidence: toOptionalNumber(record.confidence),
		paper_count: toNumber(record.paper_count, 0),
		evidence_count: toNumber(record.evidence_count, 0),
		evidence_ref_ids: toStringList(record.evidence_ref_ids),
		context_ids: toStringList(record.context_ids),
		relation_ids: toStringList(record.relation_ids),
		evidence_bundle: normalizeResearchUnderstandingPresentationEvidenceBundle(
			record.evidence_bundle
		),
		comparison_summary: normalizeResearchUnderstandingPresentationComparisonSummary(
			record.comparison_summary
		),
		expert_use_status: toText(record.expert_use_status, 'review_candidate'),
		dataset_use_status: toText(record.dataset_use_status, 'review_candidate'),
		generalization_status: toText(record.generalization_status, 'cross_paper_candidate'),
		generalization_note: toText(record.generalization_note),
		evidence_gap_summary: toText(record.evidence_gap_summary),
		upgrade_actions: toStringList(record.upgrade_actions),
		related_review_finding_ids: toStringList(record.related_review_finding_ids),
		review_reasons: toStringList(record.review_reasons),
		warnings: toStringList(record.warnings)
	};
}

function normalizeResearchUnderstandingPresentationComparisonSummary(
	value: unknown
): ResearchUnderstandingPresentationComparisonSummary | null {
	const record = asRecord(value);
	if (!record) return null;
	const baseline = normalizeResearchUnderstandingPresentationComparisonValue(record.baseline);
	const observed = normalizeResearchUnderstandingPresentationComparisonValue(record.observed);
	const variable = toText(record.variable);
	const outcome = toText(record.outcome);
	if (!baseline.value && !observed.value && !variable && !outcome) return null;
	return {
		variable,
		direction: toText(record.direction),
		outcome,
		baseline,
		observed,
		controlled_conditions: asArray(record.controlled_conditions)
			.map((item) => normalizeResearchUnderstandingPresentationControlledCondition(item))
			.filter(
				(
					item
				): item is ResearchUnderstandingPresentationControlledCondition => item !== null
			)
	};
}

function normalizeResearchUnderstandingPresentationComparisonValue(
	value: unknown
): ResearchUnderstandingPresentationComparisonValue {
	const record = asRecord(value);
	return {
		label: toText(record?.label),
		value: toText(record?.value)
	};
}

function normalizeResearchUnderstandingPresentationControlledCondition(
	value: unknown
): ResearchUnderstandingPresentationControlledCondition | null {
	const record = asRecord(value);
	if (!record) return null;
	const axis = toText(record.axis);
	const conditionValue = toText(record.value);
	if (!axis && !conditionValue) return null;
	return { axis, value: conditionValue };
}

function normalizeResearchUnderstandingPresentationEvidence(
	value: unknown
): ResearchUnderstandingPresentationEvidence | null {
	const record = asRecord(value);
	if (!record) return null;
	const evidenceRefId = toText(record.evidence_ref_id ?? record.id);
	if (!evidenceRefId) return null;
	return {
		evidence_ref_id: evidenceRefId,
		document_id: nonEmptyText(record.document_id),
		title: toText(record.title, 'Evidence'),
		source_label: toText(record.source_label, 'Evidence'),
		source_kind: toText(record.source_kind, 'unknown'),
		source_ref: nonEmptyText(record.source_ref),
		block_type: nonEmptyText(record.block_type),
		heading_path: nonEmptyText(record.heading_path),
		page: nonEmptyText(record.page),
		quote: nonEmptyText(record.quote),
		source_text: nonEmptyText(record.source_text ?? record.quote),
		value_summary: toText(record.value_summary),
		table_audit: normalizeResearchUnderstandingPresentationTableAudit(record.table_audit),
		traceability_status: toText(record.traceability_status, 'unknown'),
		evidence_role: nonEmptyText(record.evidence_role),
		confidence: toOptionalNumber(record.confidence),
		href: nonEmptyText(record.href)
	};
}

function normalizeResearchUnderstandingPresentationTableAudit(
	value: unknown
): ResearchUnderstandingPresentationTableAudit | null {
	const record = asRecord(value);
	if (!record) return null;
	const columns = asArray(record.columns)
		.map((column) => toText(column))
		.filter(Boolean);
	const relevantRows = asArray(record.relevant_rows)
		.map((row) => {
			const rowRecord = asRecord(row);
			if (!rowRecord) return null;
			const cells = asArray(rowRecord.cells)
				.map((cell) => toText(cell))
				.map((cell) => cell || '-');
			if (!cells.some((cell) => cell && cell !== '-')) return null;
			return {
				row_index: toOptionalNumber(rowRecord.row_index) ?? 0,
				cells,
				aligned:
					typeof rowRecord.aligned === 'boolean'
						? rowRecord.aligned
						: !columns.length || cells.length === columns.length
			};
		})
		.filter((row): row is ResearchUnderstandingPresentationTableRow => Boolean(row));
	if (!columns.length && !relevantRows.length) return null;
	return {
		columns,
		relevant_rows: relevantRows
	};
}

function normalizeResearchUnderstandingPresentationContext(
	value: unknown
): ResearchUnderstandingPresentationContext | null {
	const record = asRecord(value);
	if (!record) return null;
	const contextId = toText(record.context_id ?? record.id);
	if (!contextId) return null;
	return {
		context_id: contextId,
		label: toText(record.label, 'Context'),
		material_scope: toStringList(record.material_scope),
		property_scope: toStringList(record.property_scope),
		process_summary: toText(record.process_summary),
		test_summary: toText(record.test_summary),
		limitations: toStringList(record.limitations)
	};
}

function emptyResearchUnderstandingPresentation(fallback: {
	scope: ResearchUnderstandingScope;
	summary: ResearchUnderstanding['summary'];
}): ResearchUnderstandingPresentation {
	return {
		summary: {
			title: fallback.scope.title ?? 'Research understanding',
			material_scope: [],
			variable_axes: [],
			property_scope: [],
			claim_count: fallback.summary.claim_count,
			relation_count: fallback.summary.relation_count,
			evidence_count: fallback.summary.evidence_ref_count,
			context_count: fallback.summary.context_count,
			review_queue_count: 0,
			primary_finding_count: 0,
			review_queue_finding_count: 0,
			collection_document_count: 0,
			axis_coverage: { variables: [], properties: [] }
		},
		effects: [],
		findings: [],
		primary_findings: [],
		review_queue_findings: [],
		evidence_items: [],
		context_summaries: []
	};
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
		understanding: normalizeResearchUnderstanding(record?.understanding),
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
		understanding: normalizeResearchUnderstanding(record?.understanding),
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

function normalizeConfirmedGoal(value: unknown): ConfirmedGoal {
	const record = asRecord(value) ?? {};
	return {
		goal_id: toText(record.goal_id),
		collection_id: toText(record.collection_id),
		question: toText(record.question),
		source_type: toText(record.source_type, 'user_input'),
		material_hints: toStringList(record.material_hints),
		process_hints: toStringList(record.process_hints),
		property_hints: toStringList(record.property_hints),
		source_objective_id: nonEmptyText(record.source_objective_id),
		status: normalizeConfirmedGoalStatus(record.status),
		analysis_error: nonEmptyText(record.analysis_error),
		analysis_progress: normalizeGoalAnalysisProgress(record.analysis_progress),
		created_at: nonEmptyText(record.created_at),
		updated_at: nonEmptyText(record.updated_at)
	};
}

function normalizeGoalAnalysisProgress(value: unknown): GoalAnalysisProgress | null {
	const record = asRecord(value);
	if (!record) return null;
	const phase = toText(record.phase);
	if (!phase) return null;
	return {
		phase,
		current: toOptionalNumber(record.current),
		total: toOptionalNumber(record.total),
		unit: nonEmptyText(record.unit),
		message: nonEmptyText(record.message),
		active_document_id: nonEmptyText(record.active_document_id),
		active_document_title: nonEmptyText(record.active_document_title),
		active_source_filename: nonEmptyText(record.active_source_filename),
		active_objective_id: nonEmptyText(record.active_objective_id)
	};
}

function normalizeConfirmedGoalStatus(value: unknown): ConfirmedGoalStatus {
	const status = toText(value) as ConfirmedGoalStatus;
	return ['pending', 'running', 'ready', 'failed'].includes(status) ? status : 'pending';
}

function normalizeConfirmedGoalList(value: unknown, collectionId: string): ConfirmedGoalList {
	const record = asRecord(value) ?? {};
	return {
		collection_id: toText(record.collection_id, collectionId),
		goals: normalizeObjectList(value, 'goals').map((item) => normalizeConfirmedGoal(item))
	};
}

function normalizeGoalAnalysis(value: unknown, collectionId: string): GoalAnalysis {
	const record = asRecord(value) ?? {};
	return {
		collection_id: toText(record.collection_id, collectionId),
		goal: normalizeConfirmedGoal(record.goal),
		understanding: normalizeResearchUnderstanding(record.understanding),
		pipeline_nodes: normalizePipelineNodes(record.pipeline_nodes),
		errors: toStringList(record.errors),
		warnings: toStringList(record.warnings)
	};
}

function normalizePipelineNodes(value: unknown): Record<string, Record<string, unknown>> {
	const record = normalizeUnknownRecord(value);
	return Object.fromEntries(
		Object.entries(record)
			.map(([key, node]) => [key, normalizeUnknownRecord(node)])
			.filter(([key]) => Boolean(key))
	);
}

export async function createConfirmedGoalFromObjective(
	collectionId: string,
	objective: ObjectiveListItem
): Promise<ConfirmedGoal> {
	const encodedCollection = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encodedCollection}/goals`, {
		method: 'POST',
		body: JSON.stringify({
			question: objective.question,
			source_type: 'objective_candidate',
			source_objective_id: objective.objective_id,
			material_hints: objective.material_scope,
			process_hints: objective.process_axes,
			property_hints: objective.property_axes
		})
	});
	return normalizeConfirmedGoal(data);
}

export async function fetchConfirmedGoals(collectionId: string): Promise<ConfirmedGoalList> {
	const encodedCollection = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encodedCollection}/goals`);
	return normalizeConfirmedGoalList(data, collectionId);
}

export async function runGoalAnalysis(
	collectionId: string,
	goalId: string
): Promise<GoalAnalysis> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedGoal = encodeURIComponent(goalId);
	const data = await requestJson(
		`/collections/${encodedCollection}/goals/${encodedGoal}/analysis`,
		{ method: 'POST' }
	);
	return normalizeGoalAnalysis(data, collectionId);
}

export async function fetchGoalAnalysis(
	collectionId: string,
	goalId: string
): Promise<GoalAnalysis> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedGoal = encodeURIComponent(goalId);
	const data = await requestJson(`/collections/${encodedCollection}/goals/${encodedGoal}/analysis`);
	return normalizeGoalAnalysis(data, collectionId);
}

export async function createResearchUnderstandingFeedback(
	collectionId: string,
	payload: ResearchUnderstandingFeedbackCreate
): Promise<ResearchUnderstandingFeedback> {
	const encodedCollection = encodeURIComponent(collectionId);
	return requestJson(`/collections/${encodedCollection}/research-understanding/feedback`, {
		method: 'POST',
		body: JSON.stringify(payload)
	}) as Promise<ResearchUnderstandingFeedback>;
}

export async function fetchResearchUnderstandingFeedback(
	collectionId: string,
	filters: ResearchUnderstandingFeedbackFilters = {}
): Promise<ResearchUnderstandingFeedback[]> {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = new URLSearchParams();
	if (filters.scope_type) params.set('scope_type', filters.scope_type);
	if (filters.scope_id) params.set('scope_id', filters.scope_id);
	if (filters.finding_id) params.set('finding_id', filters.finding_id);
	if (filters.claim_id) params.set('claim_id', filters.claim_id);
	const suffix = params.toString() ? `?${params.toString()}` : '';
	const data = (await requestJson(
		`/collections/${encodedCollection}/research-understanding/feedback${suffix}`
	)) as { items?: ResearchUnderstandingFeedback[] };
	return Array.isArray(data.items) ? data.items : [];
}

export async function createResearchUnderstandingCuration(
	collectionId: string,
	payload: ResearchUnderstandingCurationCreate
): Promise<ResearchUnderstandingCuration> {
	const encodedCollection = encodeURIComponent(collectionId);
	return requestJson(`/collections/${encodedCollection}/research-understanding/curations`, {
		method: 'POST',
		body: JSON.stringify(payload)
	}) as Promise<ResearchUnderstandingCuration>;
}

export async function fetchResearchUnderstandingCurations(
	collectionId: string,
	filters: ResearchUnderstandingCurationFilters = {}
): Promise<ResearchUnderstandingCuration[]> {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = new URLSearchParams();
	if (filters.scope_type) params.set('scope_type', filters.scope_type);
	if (filters.scope_id) params.set('scope_id', filters.scope_id);
	if (filters.finding_id) params.set('finding_id', filters.finding_id);
	if (filters.claim_id) params.set('claim_id', filters.claim_id);
	const suffix = params.toString() ? `?${params.toString()}` : '';
	const data = (await requestJson(
		`/collections/${encodedCollection}/research-understanding/curations${suffix}`
	)) as { items?: ResearchUnderstandingCuration[] };
	return Array.isArray(data.items) ? data.items : [];
}

export async function exportResearchUnderstandingGoldDraft(
	collectionId: string,
	filters: ResearchUnderstandingGoldDraftFilters
): Promise<ResearchUnderstandingGoldDraft> {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = new URLSearchParams();
	params.set('scope_type', filters.scope_type);
	params.set('scope_id', filters.scope_id);
	return requestJson(
		`/collections/${encodedCollection}/research-understanding/gold-draft?${params.toString()}`
	) as Promise<ResearchUnderstandingGoldDraft>;
}

function researchUnderstandingDatasetParams(
	filters: ResearchUnderstandingDatasetFilters,
	format?: ResearchUnderstandingDatasetExportFormat
): URLSearchParams {
	const params = new URLSearchParams();
	params.set('scope_type', filters.scope_type);
	params.set('scope_id', filters.scope_id);
	if (filters.label_status) params.set('label_status', filters.label_status);
	if (filters.dataset_use_status) params.set('dataset_use_status', filters.dataset_use_status);
	if (format) params.set('format', format);
	return params;
}

export function researchUnderstandingDatasetUrl(
	collectionId: string,
	filters: ResearchUnderstandingDatasetFilters,
	format: ResearchUnderstandingDatasetExportFormat
): string {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = researchUnderstandingDatasetParams(filters, format);
	return `/api/v1/collections/${encodedCollection}/research-understanding/dataset?${params.toString()}`;
}

export function researchUnderstandingCollectionDatasetUrl(
	collectionId: string,
	filters: ResearchUnderstandingCollectionDatasetFilters,
	format: ResearchUnderstandingDatasetExportFormat
): string {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = new URLSearchParams();
	params.set('scope_type', filters.scope_type);
	if (filters.label_status) params.set('label_status', filters.label_status);
	if (filters.dataset_use_status) params.set('dataset_use_status', filters.dataset_use_status);
	params.set('format', format);
	return `/api/v1/collections/${encodedCollection}/research-understanding/dataset/collection?${params.toString()}`;
}

export async function fetchResearchUnderstandingDataset(
	collectionId: string,
	filters: ResearchUnderstandingDatasetFilters
): Promise<ResearchUnderstandingDataset> {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = researchUnderstandingDatasetParams(filters);
	const data = await requestJson(
		`/collections/${encodedCollection}/research-understanding/dataset?${params.toString()}`
	);
	return normalizeResearchUnderstandingDataset(data);
}

export async function fetchResearchUnderstandingCollectionDataset(
	collectionId: string,
	filters: ResearchUnderstandingCollectionDatasetFilters
): Promise<ResearchUnderstandingDataset> {
	const encodedCollection = encodeURIComponent(collectionId);
	const params = new URLSearchParams();
	params.set('scope_type', filters.scope_type);
	if (filters.label_status) params.set('label_status', filters.label_status);
	if (filters.dataset_use_status) params.set('dataset_use_status', filters.dataset_use_status);
	const data = await requestJson(
		`/collections/${encodedCollection}/research-understanding/dataset/collection?${params.toString()}`
	);
	return normalizeResearchUnderstandingDataset(data);
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
