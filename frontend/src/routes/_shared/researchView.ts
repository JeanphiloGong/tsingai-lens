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
export type FindingOrigin =
	| 'system_generated'
	| 'human_authored'
	| 'agent_authored'
	| 'hybrid';
export type FindingAbstentionReason =
	| 'no_comparable_evidence'
	| 'no_grounded_evidence'
	| 'insufficient_evidence';
export type FindingAuthoringCreate = {
	source_analysis_version: number;
	statement: string | null;
	assertion_strength: 'causal' | 'associative' | 'descriptive' | null;
	supporting_evidence_ids: string[];
	contradicting_evidence_ids: string[];
	context_evidence_ids: string[];
	condition_boundary_evidence_ids: string[];
	limitations: string[];
	parent_finding_id: string | null;
	abstention_reason: FindingAbstentionReason | null;
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
	comparison: {
		baseline_label: string;
		target_label: string;
		axis_names: string[];
		comparable: boolean;
		incomparability_reasons: string[];
	} | null;
	reported_result: {
		outcome: string;
		value: string | number | boolean | null;
		baseline_value: string | number | boolean | null;
		target_value: string | number | boolean | null;
		unit: string | null;
		direction: ObjectiveEvidenceResultDirection;
		result_text: string;
	} | null;
	attribution_scope: ObjectiveEvidenceAttributionScope;
	scientific_context: ObjectiveScientificContext;
	anchor_ids: string[];
	resolution_status: string;
	failure_reason: string | null;
	confidence: number;
	supports_finding: boolean;
	origin?: 'system_generated' | 'human_authored' | 'human_revised' | 'agent_authored';
	source_analysis_version?: number | null;
	supersedes_evidence_id?: string | null;
	superseded_by_evidence_id?: string | null;
	created_by_user_id?: string | null;
	created_by_tool_call_id?: string | null;
	created_at?: string | null;
	authoring_note?: string | null;
};
export type EvidenceAuthoringCreate = {
	source_analysis_version: number;
	document_id: string;
	source_kind: 'text_window' | 'table' | 'figure';
	source_ref: string;
	source_excerpt: string;
	evidence_role:
		| 'direct_result'
		| 'condition_context'
		| 'mechanism_context'
		| 'baseline_context'
		| 'comparison_context'
		| 'background_context'
		| 'contradictory_result'
		| 'irrelevant';
	changed_variables: Array<{
		name: string;
		baseline_value: string | number | boolean | null;
		target_value: string | number | boolean | null;
		unit: string | null;
	}>;
	comparison: {
		baseline_label: string;
		target_label: string;
		axis_names: string[];
		comparable: boolean;
		incomparability_reasons: string[];
	} | null;
	reported_result: {
		outcome: string;
		value: string | number | boolean | null;
		baseline_value: string | number | boolean | null;
		target_value: string | number | boolean | null;
		unit: string | null;
		direction: ObjectiveEvidenceResultDirection;
		result_text: string;
	} | null;
	attribution_scope: ObjectiveEvidence['attribution_scope'];
	scientific_context: ObjectiveScientificContext;
	supersedes_evidence_id: string | null;
	authoring_note: string | null;
};
export type EvidenceAuthoringResult = {
	analysis: ObjectiveAnalysisState;
	evidence: ObjectiveEvidence;
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
export type ObjectiveFindingDetail = {
	collection_id: string;
	objective_id: string;
	analysis_version: number;
	finding: ObjectiveFinding;
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
	confidence?: number;
	source_excerpt?: string;
	source_kind?: string;
	source_ref?: string;
	page_numbers?: number[];
	evidence_ids?: string[];
	analysis_status?: 'pending' | 'analyzed' | 'excluded' | 'failed';
	evidence_disposition?: string | null;
	evidence_disposition_reason?: string | null;
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

function normalizeUnknownRecord(value: unknown): Record<string, unknown> {
	const record = asRecord(value);
	return record ? { ...record } : {};
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
		variables: toStringList(record.variables),
		outcomes: toStringList(record.outcomes),
		mechanisms: toStringList(record.mechanisms),
		constraints: toStringList(record.constraints),
		requested_comparator: nonEmptyText(record.requested_comparator),
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
	const origin = toText(record.origin) as FindingOrigin;
	const abstentionReason = nonEmptyText(record.abstention_reason) as FindingAbstentionReason | null;
	return {
		collection_id: toText(record.collection_id),
		objective_id: toText(record.objective_id),
		analysis_version: toNumber(record.analysis_version),
		document_inputs: asArray(record.document_inputs)
			.map((item) => {
				const input = asRecord(item);
				const documentId = toText(input?.document_id);
				const fingerprint = toText(input?.preparation_fingerprint);
				return documentId && fingerprint
					? { document_id: documentId, preparation_fingerprint: fingerprint }
					: null;
			})
			.filter((item): item is PreparedDocumentInput => item !== null),
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
		completed_at: nonEmptyText(record.completed_at),
		origin: ['human_authored', 'agent_authored', 'hybrid'].includes(origin)
			? origin
			: 'system_generated',
		source_analysis_version: toOptionalNumber(record.source_analysis_version),
		created_by_user_id: nonEmptyText(record.created_by_user_id),
		created_by_tool_call_id: nonEmptyText(record.created_by_tool_call_id),
		abstention_reason: abstentionReason,
		abstention_note: nonEmptyText(record.abstention_note)
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

export function normalizeObjectiveScope(
	value: unknown,
	collectionId: string,
	objectiveId: string
): ObjectiveScope {
	const record = asRecord(value);
	const counts = asRecord(record?.counts);
	const classifications: ObjectiveScopeClassification[] = [
		'likely_relevant',
		'needs_inspection',
		'confidently_out_of_scope'
	];
	const decisions = asArray(record?.decisions)
		.map((item) => {
			const decision = asRecord(item);
			const documentId = toText(decision?.document_id);
			const classification = toText(decision?.classification) as ObjectiveScopeClassification;
			if (!documentId || !classifications.includes(classification)) return null;
			return {
				document_id: documentId,
				classification,
				reason: toText(decision?.reason),
				doc_role: toText(decision?.doc_role, 'uncertain'),
				map_status: toText(decision?.map_status, 'unknown'),
				map_limitations: toStringList(decision?.map_limitations),
				support_basis: toStringList(decision?.support_basis),
				is_seed: decision?.is_seed === true
			} satisfies ObjectiveScopeDecision;
		})
		.filter((item): item is ObjectiveScopeDecision => item !== null);
	return {
		collection_id: toText(record?.collection_id, collectionId),
		objective_id: toText(record?.objective_id, objectiveId),
		counts: {
			likely_relevant: Math.max(0, toNumber(counts?.likely_relevant)),
			needs_inspection: Math.max(0, toNumber(counts?.needs_inspection)),
			confidently_out_of_scope: Math.max(0, toNumber(counts?.confidently_out_of_scope))
		},
		recommended_document_ids: toStringList(record?.recommended_document_ids),
		review_document_ids: toStringList(record?.review_document_ids),
		excluded_document_ids: toStringList(record?.excluded_document_ids),
		decisions,
		support_is_evidence: record?.support_is_evidence === true
	};
}

export async function fetchCollectionObjectives(collectionId: string): Promise<ObjectiveList> {
	const encoded = encodeURIComponent(collectionId);
	const data = await requestJson(`/collections/${encoded}/objectives`);
	return normalizeObjectiveList(data, collectionId);
}

export async function fetchObjectiveScope(
	collectionId: string,
	objectiveId: string
): Promise<ObjectiveScope> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/scope`;
	const data = await requestJson(path);
	return normalizeObjectiveScope(data, collectionId, objectiveId);
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
				variables: [],
				outcomes: [],
				mechanisms: [],
				constraints: [],
				requested_comparator: null,
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

export async function fetchObjectiveFinding(
	collectionId: string,
	objectiveId: string,
	analysisVersion: number,
	findingId: string
): Promise<ObjectiveFindingDetail> {
	const path = `/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/findings/${encodeURIComponent(findingId)}`;
	const params = new URLSearchParams({ analysis_version: String(analysisVersion) });
	return requestJson(`${path}?${params.toString()}`) as Promise<ObjectiveFindingDetail>;
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
	return requestJson(`${path}?${params.toString()}`) as Promise<ObjectiveEvidencePage>;
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

export async function createEvidenceVersion(
	collectionId: string,
	objectiveId: string,
	payload: EvidenceAuthoringCreate
): Promise<EvidenceAuthoringResult> {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	return requestJson(`/collections/${encodedCollection}/objectives/${encodedObjective}/evidence`, {
		method: 'POST',
		body: JSON.stringify(payload)
	}) as Promise<EvidenceAuthoringResult>;
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
) {
	const encodedCollection = encodeURIComponent(collectionId);
	const encodedObjective = encodeURIComponent(objectiveId);
	const data = await requestJson(
		`/collections/${encodedCollection}/objectives/${encodedObjective}/analysis`,
		{
			method: 'POST',
			body: JSON.stringify({ document_ids: documentIds })
		}
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
	format: 'json' | 'training_jsonl' | 'llamafactory_alpaca',
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
	return requestJson(
		`/collections/${encodeURIComponent(collectionId)}/objectives/${encodeURIComponent(objectiveId)}/finding-dataset${suffix}`
	) as Promise<FindingDataset>;
}
