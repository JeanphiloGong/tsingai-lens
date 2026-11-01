import { requestJson } from './api';

export type FindingFeedbackStatus = 'correct' | 'incorrect' | 'partial' | 'unclear';
export type FindingFeedbackIssueType =
	| 'none'
	| 'evidence_not_grounded'
	| 'missing_evidence'
	| 'insufficient_evidence'
	| 'wrong_factor'
	| 'wrong_outcome'
	| 'wrong_direction'
	| 'wrong_context'
	| 'wrong_mechanism'
	| 'wrong_attribution'
	| 'wrong_synthesis'
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
	curated_finding: ObjectiveFinding;
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
export type FindingOrigin = 'system_generated' | 'human_authored' | 'agent_authored' | 'hybrid';
export type FindingAbstentionReason =
	| 'no_comparable_evidence'
	| 'no_grounded_evidence'
	| 'insufficient_evidence';
export type FindingAuthoringCreate = {
	source_analysis_version: number;
	selection_ids: string[];
	comparison_group_ids: string[];
	parent_finding_id?: string | null;
};
export type FindingDatasetLabelStatus = 'candidate' | 'silver' | 'gold' | 'rejected';
export type FindingDatasetUseStatus = 'training_ready' | 'review_candidate' | 'rejected';
export type FindingDatasetSample = {
	sample_id: string;
	objective_id: string;
	analysis_version: number;
	finding_id: string;
	research_objective: string;
	document_ids: string[];
	label_status: FindingDatasetLabelStatus;
	dataset_use_status: FindingDatasetUseStatus;
	finding_fingerprint: string;
	evidence_fingerprint: string;
	system_prediction: ObjectiveFinding;
	expert_target: ObjectiveFinding | null;
	training_target: ObjectiveFinding;
	evidence: ObjectiveEvidence[];
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

export type ObjectiveConfirmationStatus = 'candidate' | 'confirmed';
export type ObjectiveAnalysisStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type ObjectiveScopeClassification =
	| 'likely_relevant'
	| 'needs_inspection'
	| 'confidently_out_of_scope';
export type ObjectiveScopeDecision = {
	document_id: string;
	classification: ObjectiveScopeClassification;
	reason: string;
	doc_role: string;
	map_status: string;
	map_limitations: string[];
	support_basis: string[];
	is_seed: boolean;
};
export type ObjectiveScope = {
	collection_id: string;
	objective_id: string;
	counts: Record<ObjectiveScopeClassification, number>;
	recommended_document_ids: string[];
	review_document_ids: string[];
	excluded_document_ids: string[];
	decisions: ObjectiveScopeDecision[];
	support_is_evidence: boolean;
};
export type ObjectiveEvidenceAttributionScope =
	| 'isolated_effect'
	| 'joint_effect'
	| 'association_only'
	| 'descriptive_only'
	| 'not_attributable';
export type ObjectiveEvidenceResultDirection =
	| 'increase'
	| 'decrease'
	| 'improve'
	| 'worsen'
	| 'changed'
	| 'no_change'
	| 'mixed'
	| 'unknown';
export type ObjectiveEvidenceResultKind =
	| 'measured'
	| 'observed'
	| 'predicted'
	| 'simulated'
	| 'modeled'
	| 'unknown';
export type ObjectiveEvidenceStatus =
	| 'comparable'
	| 'association_only'
	| 'descriptive'
	| 'needs_context'
	| 'non_comparable'
	| 'extraction_failed';
export type ObjectiveAnalysisState = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	document_inputs: PreparedDocumentInput[];
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
	origin: FindingOrigin;
	source_analysis_version: number | null;
	created_by_user_id: string | null;
	created_by_tool_call_id: string | null;
	abstention_reason: FindingAbstentionReason | null;
	abstention_note: string | null;
};
export type ObjectiveAnalysisProgress = Pick<
	ObjectiveAnalysisState,
	| 'collection_id'
	| 'objective_id'
	| 'analysis_version'
	| 'status'
	| 'phase'
	| 'processed_document_count'
	| 'total_document_count'
	| 'current_document_id'
	| 'progress_message'
	| 'error_code'
	| 'error_message'
	| 'created_at'
	| 'started_at'
	| 'completed_at'
> & { analysis_version: number | null; status: ObjectiveAnalysisStatus | null };
export type ObjectiveEvidenceGap = {
	evidence_id: string;
	document_id: string;
	source_kind: string;
	source_ref: string;
	page_numbers: number[];
	evidence_status: ObjectiveEvidenceStatus;
	reason: string;
	outcome: string | null;
	source_excerpt: string;
};
export type ObjectiveEvidenceReview = {
	total_evidence_count: number;
	result_count: number;
	comparable_evidence_count: number;
	gap_count: number;
	omitted_gap_count: number;
	status_counts: Partial<Record<ObjectiveEvidenceStatus, number>>;
	gaps: ObjectiveEvidenceGap[];
};
export type PreparedDocumentInput = {
	document_id: string;
	preparation_fingerprint: string;
};
export type ObjectiveSummary = {
	collection_id: string;
	objective_id: string;
	question: string;
	material_scope: string[];
	variables: string[];
	outcomes: string[];
	mechanisms: string[];
	constraints: string[];
	requested_comparator: string | null;
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

export type ObjectiveFindingMechanism = {
	source_term: string;
	relation_type: string;
	target_term: string;
	direction: ObjectiveEvidenceResultDirection | null;
	assertion_strength: 'causal' | 'associative' | 'descriptive';
	supporting_evidence_ids: string[];
};
export type ObjectiveScientificAttribute = {
	name: string;
	value: string | number | boolean;
	unit: string | null;
};
export type ObjectiveScientificContext = {
	material: ObjectiveScientificAttribute[];
	sample: ObjectiveScientificAttribute[];
	process: ObjectiveScientificAttribute[];
	test: ObjectiveScientificAttribute[];
};
export type ObjectiveFindingPaperContribution = {
	document_id: string;
	analysis_status: 'analyzed' | 'excluded' | 'failed';
	supporting_evidence_ids: string[];
	contradicting_evidence_ids: string[];
	context_evidence_ids: string[];
	condition_boundary_evidence_ids: string[];
};
export type ObjectiveFinding = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	finding_id: string;
	statement: string;
	factors: string[];
	outcome: string;
	direction: ObjectiveEvidenceResultDirection;
	assertion_strength: 'causal' | 'associative' | 'descriptive';
	attribution_scope: Exclude<ObjectiveEvidenceAttributionScope, 'not_attributable'>;
	synthesis_status: 'agreement' | 'conflict' | 'condition_dependent' | 'insufficient_confirmation';
	certainty: number;
	display_rank: number;
	mechanisms: ObjectiveFindingMechanism[];
	scientific_context: ObjectiveScientificContext;
	limitations: string[];
	selection_ids?: string[];
	comparison_group_ids?: string[];
	paper_contributions: ObjectiveFindingPaperContribution[];
	origin: FindingOrigin;
	source_analysis_version: number | null;
	parent_finding_id: string | null;
	created_by_user_id: string | null;
	created_by_tool_call_id: string | null;
	created_at: string | null;
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
	changed_variables: {
		name: string;
		baseline_value: string | number | boolean | null;
		target_value: string | number | boolean | null;
		unit: string | null;
	}[];
	evidence_status?: ObjectiveEvidenceStatus;
	evidence_status_reason?: string;
	comparison: {
		baseline_label: string;
		target_label: string;
		axis_names: string[];
		comparable: boolean;
		incomparability_reasons: string[];
	} | null;
	reported_result: {
		outcome: string;
		result_kind?: ObjectiveEvidenceResultKind;
		value: string | number | boolean | null;
		baseline_value: string | number | boolean | null;
		target_value: string | number | boolean | null;
		unit: string | null;
		direction: ObjectiveEvidenceResultDirection;
		result_text: string;
	} | null;
	attribution_scope: ObjectiveEvidenceAttributionScope;
	scientific_context: ObjectiveScientificContext;
	resolution_status: string;
	failure_reason: string | null;
	confidence: number;
	supports_finding: boolean;
	eligible_for_finding_authoring: boolean;
	origin?: 'system_generated' | 'human_authored' | 'human_revised' | 'agent_authored';
	source_analysis_version?: number | null;
	supersedes_evidence_id?: string | null;
	superseded_by_evidence_id?: string | null;
	created_by_user_id?: string | null;
	created_by_tool_call_id?: string | null;
	created_at?: string | null;
	authoring_note?: string | null;
};
export type FindingAuthoringResult = {
	analysis: ObjectiveAnalysisState;
	finding: ObjectiveFinding | null;
	abstention_reason: FindingAbstentionReason | null;
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
	evidence_review: ObjectiveEvidenceReview;
	warnings: string[];
};
export type FindingEvidenceReview = {
	needs_review: boolean;
	evidence_replacements: Record<string, string | null>;
};
export type ObjectiveFindingPage = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	items: ObjectiveFinding[];
	evidence_reviews: Record<string, FindingEvidenceReview>;
	offset: number;
	limit: number;
	total: number;
};
export type ObjectiveFindingDetail = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	finding: ObjectiveFinding;
	evidence_review: FindingEvidenceReview;
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
export type ObjectiveEvidenceMapNodeType =
	| 'objective'
	| 'finding'
	| 'evidence'
	| 'source'
	| 'document';
export type ObjectiveEvidenceMapNode = {
	id: string;
	type: ObjectiveEvidenceMapNodeType;
	label: string;
	objective_id?: string;
	question?: string;
	material_scope?: string[];
	variables?: string[];
	outcomes?: string[];
	finding_id?: string;
	statement?: string;
	factors?: string[];
	outcome?: string | null;
	direction?: ObjectiveEvidenceResultDirection | null;
	assertion_strength?: 'causal' | 'associative' | 'descriptive';
	synthesis_status?: 'agreement' | 'conflict' | 'condition_dependent' | 'insufficient_confirmation';
	certainty?: number;
	limitations?: string[];
	evidence_id?: string;
	document_id?: string;
	evidence_role?: string;
	attribution_scope?: ObjectiveEvidenceAttributionScope;
	evidence_status?: ObjectiveEvidenceStatus;
	evidence_status_reason?: string;
	confidence?: number;
	source_excerpt?: string;
	source_kind?: string;
	source_ref?: string;
	page_numbers?: number[];
	evidence_ids?: string[];
	analysis_status?: 'pending' | 'analyzed' | 'excluded' | 'failed';
	evidence_disposition?: string | null;
	evidence_disposition_reason?: string | null;
	uninspected_source_count?: number | null;
};
export type ObjectiveEvidenceMapEdge = {
	id: string;
	source: string;
	target: string;
	relation:
		| 'has_finding'
		| 'supports'
		| 'contradicts'
		| 'contextualizes'
		| 'extracted_from'
		| 'reported_in'
		| 'includes_document';
	condition_boundary: boolean;
};
export type ObjectiveEvidenceMapCoverage = {
	total_document_count: number;
	analyzed_document_count: number;
	excluded_document_count: number;
	failed_document_count: number;
	direct_evidence_document_count: number;
	finding_count: number;
	evidence_count: number;
	source_count: number;
	unlinked_evidence_count: number;
	evidence_status_counts?: Partial<Record<ObjectiveEvidenceStatus, number>>;
};
export type ObjectiveEvidenceMap = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	projection_version: 'objective-evidence-map.v1';
	complete: boolean;
	nodes: ObjectiveEvidenceMapNode[];
	edges: ObjectiveEvidenceMapEdge[];
	coverage: ObjectiveEvidenceMapCoverage;
};

export function formatShortIdentifier(value: string | null | undefined): string {
	const text = value?.trim() ?? '';
	if (!text) return '--';
	if (text.length <= 24) return text;
	return `${text.slice(0, 10)}...${text.slice(-6)}`;
}

export async function fetchCollectionObjectives(collectionId: string): Promise<ObjectiveList> {
	const data = (await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/objectives`
	)) as ObjectiveList;
	if (data.collection_id !== collectionId) {
		throw new Error('Objective list response does not match collection_id.');
	}
	return data;
}

export async function fetchObjectiveScope(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveScope> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/scope`;
	const data = (await requestJson(path)) as ObjectiveScope;
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId) {
		throw new Error('Objective scope response does not match the requested objective.');
	}
	return data;
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
	const data = (await requestJson(`${path}?${params.toString()}`)) as ObjectiveFindingPage;
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion) {
		throw new Error('Objective Findings response does not match the requested analysis.');
	}
	return data;
}

export async function fetchObjectiveFinding(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string
): Promise<ObjectiveFindingDetail> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/findings/${encodeURIComponent(findingId)}`;
	const params = new URLSearchParams({ analysis_version: String(analysisVersion) });
	const data = (await requestJson(`${path}?${params.toString()}`)) as ObjectiveFindingDetail;
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion || data.finding?.finding_id !== findingId) {
		throw new Error('Objective Finding response does not match the requested finding.');
	}
	return data;
}

export async function fetchObjectiveEvidence(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string | null,
	offset = 0,
	limit = 100
): Promise<ObjectiveEvidencePage> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/evidence`;
	const params = new URLSearchParams({ analysis_version: String(analysisVersion) });
	if (findingId) params.set('finding_id', findingId);
	params.set('offset', String(offset));
	params.set('limit', String(limit));
	const data = (await requestJson(`${path}?${params.toString()}`)) as ObjectiveEvidencePage;
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion || data.finding_id !== findingId) {
		throw new Error('Objective Evidence response does not match the requested analysis.');
	}
	return data;
}

export async function createFindingVersion(
	collectionId: string,
	objectiveId: string,
	payload: FindingAuthoringCreate
): Promise<FindingAuthoringResult> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	return requestJson(`/collections/${encodedCollection}/objectives/${encodedObjective}/findings`, {
		method: 'POST',
		body: JSON.stringify(payload)
	}) as Promise<FindingAuthoringResult>;
}

export type ExperimentAnalysisProjection = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	selections: Array<{
		selection_id: string;
		experiment_id: string;
		experiment_version: number;
		outcome: string;
		measurement_keys: string[];
		comparison_keys: string[];
		missing_context: string[];
	}>;
	comparison_groups: Array<{
		group_id: string;
		outcome: string;
		comparison_basis: string[];
		status: 'comparable' | 'conditional' | 'insufficient';
		limitations: string[];
		members: Array<{ selection_id: string; role: string; comparability: string; reason: string }>;
	}>;
	experiments: PaperExperimentRevision[];
	findings: ObjectiveFinding[];
};

export type ExperimentSource = {
	document_id: string;
	source_fingerprint: string;
	source_kind: string;
	source_ref: string;
	quote: string;
};
export type ExperimentMeasurement = {
	measurement_key: string;
	outcome: string;
	variant_key: string | null;
	test_key: string | null;
	value: unknown;
	unit: string | null;
	result_text: string | null;
	statistics: Record<string, unknown>;
	result_kind: string;
	binding_status: string;
	source_refs: ExperimentSource[];
};
export type ExperimentComparison = {
	comparison_key: string;
	baseline_variant_key: string;
	target_variant_key: string;
	outcome: string;
	baseline_measurement_keys: string[];
	target_measurement_keys: string[];
	changed_variables: Array<{ name: string; baseline_value: unknown; target_value: unknown; unit: string | null }>;
	matched_conditions: ObjectiveScientificAttribute[];
	basis: string;
	direction: string;
	reported_statement: string | null;
	status: string;
	relation_status: string;
	reasons: string[];
	source_refs: ExperimentSource[];
};
export type PaperExperimentRevision = {
	experiment_id: string;
	experiment_version: number;
	document_id: string;
	label: string;
	scope_description: string;
	variants: Array<{
		variant_key: string;
		variant_label: string;
		subject_attributes: ObjectiveScientificAttribute[];
		intervention_attributes: ObjectiveScientificAttribute[];
		state: ObjectiveScientificAttribute[];
	}>;
	test_conditions: Array<{
		test_key: string;
		test_type: string;
		parameters: ObjectiveScientificAttribute[];
		missing_parameters: string[];
	}>;
	measurements: ExperimentMeasurement[];
	comparisons: ExperimentComparison[];
};

export function experimentAnalysisExportUrl(
	collectionId: string, objectiveId: string, analysisVersion: number, format: 'json' | 'csv'
) {
	return `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/experiment-analysis/export?${new URLSearchParams({ analysis_version: String(analysisVersion), format })}`;
}

export async function fetchExperimentAnalysis(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number
): Promise<ExperimentAnalysisProjection> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/experiment-analysis`;
	const data = (await requestJson(
		`${path}?analysis_version=${encodeURIComponent(String(analysisVersion))}`
	)) as ExperimentAnalysisProjection;
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion) {
		throw new Error('Experiment analysis response does not match the requested analysis.');
	}
	return data;
}

export type FindingEvidenceSummary = {
	collection_id: string;
	objective_id: string;
	finding_id: string;
	analysis_version: number;
	language: 'en' | 'zh';
	text: string;
	citation_ids: string[];
	references: Array<{
		id: string;
		kind: 'finding' | 'evidence';
		label: string;
		document_id?: string | null;
		source_ref?: string | null;
		page_numbers?: number[];
		source_excerpt?: string | null;
	}>;
	model: string;
	prompt_version: string;
	generated_at: string;
};

export async function generateFindingSummary(
	collectionId: string,
	objectiveId: string,
	findingId: string,
	analysisVersion: number,
	language: 'en' | 'zh',
	signal?: AbortSignal
): Promise<FindingEvidenceSummary> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/findings/${encodeURIComponent(findingId)}/summary`;
	return requestJson(path, {
		method: 'POST',
		body: JSON.stringify({ analysis_version: analysisVersion, language }),
		signal
	}) as Promise<FindingEvidenceSummary>;
}

export async function fetchObjectiveEvidenceMap(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveEvidenceMap> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/evidence-map`;
	return requestJson(path) as Promise<ObjectiveEvidenceMap>;
}

export async function runObjectiveAnalysis(
	collectionId: string,
	objectiveId: string,
	documentIds: string[]
): Promise<ObjectiveAnalysis> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = (await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis`,
		{
			method: 'POST',
			body: JSON.stringify({ document_ids: documentIds })
		}
	)) as ObjectiveAnalysis;
	if (data.collection_id !== collectionId || data.objective?.objective_id !== objectiveId) {
		throw new Error('Objective analysis response does not match the requested objective.');
	}
	return data;
}

export async function fetchObjectiveAnalysis(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveAnalysis> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = (await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis`
	)) as ObjectiveAnalysis;
	if (data.collection_id !== collectionId || data.objective?.objective_id !== objectiveId) {
		throw new Error('Objective analysis response does not match the requested objective.');
	}
	return data;
}

export async function fetchObjectiveAnalysisStatus(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveAnalysisProgress> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	return (await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis/status`
	)) as ObjectiveAnalysisProgress;
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
	)) as {
		collection_id: string;
		objective_id: string;
		analysis_version: number;
		finding_id: string;
		items: FindingFeedback[];
	};
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion || data.finding_id !== findingId) {
		throw new Error('Finding feedback response does not match the requested finding.');
	}
	return data.items;
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
	)) as {
		collection_id: string;
		objective_id: string;
		analysis_version: number;
		finding_id: string;
		items: FindingCuration[];
	};
	if (data.collection_id !== collectionId || data.objective_id !== objectiveId ||
		data.analysis_version !== analysisVersion || data.finding_id !== findingId) {
		throw new Error('Finding curation response does not match the requested finding.');
	}
	return data.items;
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
	format: 'json' | 'training_jsonl' | 'llamafactory_alpaca',
	filters: FindingDatasetFilters = {}
): string {
	const params = findingDatasetParams(filters);
	params.set('format', format);
	return `/api/v1/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset?${params.toString()}`;
}

export function collectionFindingDatasetUrl(
	collectionId: string,
	format: 'json' | 'training_jsonl',
	filters: FindingDatasetFilters = {}
): string {
	const params = findingDatasetParams(filters);
	params.set('format', format);
	return `/api/v1/collections/${encodeURIComponent(collectionId)}/finding-dataset?${params.toString()}`;
}

export function findingGoldDraftUrl(collectionId: string): string {
	return `/api/v1/collections/${encodeURIComponent(collectionId)}/finding-gold-draft`;
}

export async function fetchObjectiveFindingDataset(
	collectionId: string,
	objectiveId: string,
	filters: FindingDatasetFilters = {}
): Promise<FindingDataset> {
	const params = findingDatasetParams(filters);
	const suffix = params.size ? `?${params.toString()}` : '';
	return requestJson(
		`/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset${suffix}`
	) as Promise<FindingDataset>;
}
