import { requestJson } from './api';
import { USE_API_FIXTURES } from './base';

export type DocumentType = 'experimental' | 'review' | 'mixed' | 'uncertain';
export type ProtocolExtractable = 'yes' | 'partial' | 'no' | 'uncertain';

export type DocumentProfile = {
	document_id: string;
	collection_id: string;
	title: string | null;
	source_filename: string | null;
	doc_type: DocumentType;
	protocol_extractable: ProtocolExtractable;
	protocol_extractability_signals: string[];
	parsing_warnings: string[];
	confidence: number | null;
};

export type DocumentProfilesResponse = {
	collection_id: string;
	total: number;
	count: number;
	summary: {
		total_documents: number;
		doc_type_counts: Record<DocumentType, number>;
		protocol_extractable_counts: Record<ProtocolExtractable, number>;
		warnings: string[];
	};
	items: DocumentProfile[];
};

export type DocumentContentBlock = {
	block_id: string;
	block_type: string | null;
	heading_path: string | null;
	heading_level: number;
	order: number;
	text: string;
	text_unit_ids: string[];
	start_offset: number | null;
	end_offset: number | null;
};

export type DocumentContentResponse = {
	collection_id: string;
	document_id: string;
	title: string | null;
	source_filename: string | null;
	content_text: string;
	blocks: DocumentContentBlock[];
	warnings: string[];
};

export type DocumentChainComparabilityStatus =
	| 'comparable'
	| 'limited'
	| 'not_comparable'
	| 'insufficient';

export type DocumentChainMaterial = {
	label: string;
	composition: string | null;
	host_material_system: Record<string, unknown> | null;
};

export type DocumentChainMeasurement = {
	property: string;
	value: number | null;
	unit: string | null;
	result_type: string;
	summary: string;
	statistic_type: string | null;
	uncertainty: string | null;
};

export type DocumentChainTestCondition = {
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

export type DocumentChainBaseline = {
	label: string | null;
	reference: string | null;
	baseline_type: string | null;
	resolved: boolean;
};

export type DocumentChainAssessment = {
	comparability_status: DocumentChainComparabilityStatus;
	warnings: string[];
	basis: string[];
	missing_context: string[];
	requires_expert_review: boolean;
	assessment_epistemic_status: string;
};

export type DocumentChainValueProvenance = {
	value_origin: string;
	source_value_text: string | null;
	source_unit_text: string | null;
	derivation_formula: string | null;
	derivation_inputs: Record<string, unknown> | null;
};

export type DocumentChainEvidence = {
	evidence_ids: string[];
	direct_anchor_ids: string[];
	contextual_anchor_ids: string[];
	structure_feature_ids: string[];
	characterization_observation_ids: string[];
	traceability_status: string;
};

export type DocumentResultChain = {
	result_id: string;
	source_result_id: string;
	measurement: DocumentChainMeasurement;
	test_condition: DocumentChainTestCondition;
	baseline: DocumentChainBaseline;
	assessment: DocumentChainAssessment;
	value_provenance: DocumentChainValueProvenance;
	evidence: DocumentChainEvidence;
};

export type DocumentResultSeries = {
	series_key: string;
	property_family: string;
	test_family: string;
	varying_axis: {
		axis_name: string | null;
		axis_unit: string | null;
	};
	chains: DocumentResultChain[];
};

export type DocumentVariantDossier = {
	variant_id: string | null;
	variant_label: string | null;
	material: DocumentChainMaterial;
	shared_process_state: Record<string, unknown>;
	shared_missingness: string[];
	series: DocumentResultSeries[];
};

export type DocumentComparisonSemanticsResponse = {
	collection_id: string;
	document_id: string;
	total: number;
	count: number;
	items: unknown[];
	variant_dossiers: DocumentVariantDossier[];
};

export type DocumentComparisonSemanticsOptions = {
	includeGroupedProjections?: boolean;
};

const DEFAULT_DOC_TYPE_COUNTS: Record<DocumentType, number> = {
	experimental: 0,
	review: 0,
	mixed: 0,
	uncertain: 0
};

const DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS: Record<ProtocolExtractable, number> = {
	yes: 0,
	partial: 0,
	no: 0,
	uncertain: 0
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

function toNumber(value: unknown) {
	return typeof value === 'number' && Number.isFinite(value) ? value : Number(value ?? NaN);
}

function toOptionalText(value: unknown) {
	if (typeof value !== 'string') return null;
	const text = value.trim();
	return text ? text : null;
}

function toOptionalNumber(value: unknown) {
	const number = toNumber(value);
	return Number.isFinite(number) ? number : null;
}

function toBoolean(value: unknown) {
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
	const number = toOptionalNumber(value);
	if (number !== null) return number;
	return toOptionalText(value);
}

function normalizeComparabilityStatus(value: unknown): DocumentChainComparabilityStatus {
	const status = String(value ?? '').trim();
	return ['comparable', 'limited', 'not_comparable', 'insufficient'].includes(status)
		? (status as DocumentChainComparabilityStatus)
		: 'insufficient';
}

function normalizeContentBlock(value: unknown, index: number): DocumentContentBlock | null {
	const record = asRecord(value);
	if (!record) return null;

	const block_id = String(record.block_id ?? '').trim();
	const text = String(record.text ?? '').trim();
	if (!block_id || !text) return null;

	const startOffset = toNumber(record.start_offset);
	const endOffset = toNumber(record.end_offset);

	return {
		block_id,
		block_type: toOptionalText(record.block_type),
		heading_path: toOptionalText(record.heading_path),
		heading_level: Number.isFinite(toNumber(record.heading_level))
			? toNumber(record.heading_level)
			: 0,
		order: Number.isFinite(toNumber(record.order)) ? toNumber(record.order) : index + 1,
		text,
		text_unit_ids: toStringList(record.text_unit_ids),
		start_offset: Number.isFinite(startOffset) ? startOffset : null,
		end_offset: Number.isFinite(endOffset) ? endOffset : null
	};
}

function normalizeProfile(value: unknown, collectionId: string): DocumentProfile | null {
	const record = asRecord(value);
	if (!record) return null;

	const document_id = String(record.document_id ?? record.id ?? '').trim();
	if (!document_id) return null;

	const doc_type = String(record.doc_type ?? 'uncertain').trim() as DocumentType;
	const protocol_extractable = String(
		record.protocol_extractable ?? 'uncertain'
	).trim() as ProtocolExtractable;
	const confidence = toNumber(record.confidence);

	return {
		document_id,
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		title: toOptionalText(record.title) ?? toOptionalText(record.document_title),
		source_filename:
			toOptionalText(record.source_filename) ??
			toOptionalText(record.original_filename) ??
			toOptionalText(record.source_file_name),
		doc_type: ['experimental', 'review', 'mixed', 'uncertain'].includes(doc_type)
			? doc_type
			: 'uncertain',
		protocol_extractable: ['yes', 'partial', 'no', 'uncertain'].includes(protocol_extractable)
			? protocol_extractable
			: 'uncertain',
		protocol_extractability_signals: toStringList(record.protocol_extractability_signals),
		parsing_warnings: toStringList(record.parsing_warnings),
		confidence: Number.isFinite(confidence) ? confidence : null
	};
}

function normalizeDocumentChainMaterial(value: unknown): DocumentChainMaterial {
	const record = asRecord(value);
	return {
		label: String(record?.label ?? '--').trim() || '--',
		composition: toOptionalText(record?.composition),
		host_material_system: asRecord(record?.host_material_system)
	};
}

function normalizeDocumentChainMeasurement(value: unknown): DocumentChainMeasurement {
	const record = asRecord(value);
	return {
		property: String(record?.property ?? '--').trim() || '--',
		value: toOptionalNumber(record?.value),
		unit: toOptionalText(record?.unit),
		result_type: String(record?.result_type ?? 'scalar').trim() || 'scalar',
		summary: String(record?.summary ?? '--').trim() || '--',
		statistic_type: toOptionalText(record?.statistic_type),
		uncertainty: toOptionalText(record?.uncertainty)
	};
}

function normalizeDocumentChainTestCondition(value: unknown): DocumentChainTestCondition {
	const record = asRecord(value);
	return {
		test_method: toOptionalText(record?.test_method),
		test_temperature_c: toOptionalNumber(record?.test_temperature_c),
		strain_rate_s_1: toScalarOrText(record?.['strain_rate_s-1'] ?? record?.strain_rate_s_1),
		loading_direction: toOptionalText(record?.loading_direction),
		sample_orientation: toOptionalText(record?.sample_orientation),
		environment: toOptionalText(record?.environment),
		frequency_hz: toOptionalNumber(record?.frequency_hz),
		specimen_geometry: toOptionalText(record?.specimen_geometry),
		surface_state: toOptionalText(record?.surface_state)
	};
}

function normalizeDocumentChainBaseline(value: unknown): DocumentChainBaseline {
	const record = asRecord(value);
	return {
		label: toOptionalText(record?.label),
		reference: toOptionalText(record?.reference),
		baseline_type: toOptionalText(record?.baseline_type),
		resolved: toBoolean(record?.resolved)
	};
}

function normalizeDocumentChainAssessment(value: unknown): DocumentChainAssessment {
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

function normalizeDocumentChainValueProvenance(value: unknown): DocumentChainValueProvenance {
	const record = asRecord(value);
	return {
		value_origin: String(record?.value_origin ?? 'unknown').trim() || 'unknown',
		source_value_text: toOptionalText(record?.source_value_text),
		source_unit_text: toOptionalText(record?.source_unit_text),
		derivation_formula: toOptionalText(record?.derivation_formula),
		derivation_inputs: asRecord(record?.derivation_inputs)
	};
}

function normalizeDocumentChainEvidence(value: unknown): DocumentChainEvidence {
	const record = asRecord(value);
	return {
		evidence_ids: toStringList(record?.evidence_ids),
		direct_anchor_ids: toStringList(record?.direct_anchor_ids),
		contextual_anchor_ids: toStringList(record?.contextual_anchor_ids),
		structure_feature_ids: toStringList(record?.structure_feature_ids),
		characterization_observation_ids: toStringList(record?.characterization_observation_ids),
		traceability_status: String(record?.traceability_status ?? 'missing').trim() || 'missing'
	};
}

function normalizeDocumentResultChain(value: unknown): DocumentResultChain | null {
	const record = asRecord(value);
	if (!record) return null;

	const result_id = String(record.result_id ?? '').trim();
	if (!result_id) return null;

	return {
		result_id,
		source_result_id: String(record.source_result_id ?? result_id).trim() || result_id,
		measurement: normalizeDocumentChainMeasurement(record.measurement),
		test_condition: normalizeDocumentChainTestCondition(record.test_condition),
		baseline: normalizeDocumentChainBaseline(record.baseline),
		assessment: normalizeDocumentChainAssessment(record.assessment),
		value_provenance: normalizeDocumentChainValueProvenance(record.value_provenance),
		evidence: normalizeDocumentChainEvidence(record.evidence)
	};
}

function normalizeDocumentResultSeries(value: unknown): DocumentResultSeries | null {
	const record = asRecord(value);
	if (!record) return null;

	const series_key = String(record.series_key ?? '').trim();
	if (!series_key) return null;

	const axisRecord = asRecord(record.varying_axis);

	return {
		series_key,
		property_family: String(record.property_family ?? '--').trim() || '--',
		test_family: String(record.test_family ?? '--').trim() || '--',
		varying_axis: {
			axis_name: toOptionalText(axisRecord?.axis_name),
			axis_unit: toOptionalText(axisRecord?.axis_unit)
		},
		chains: Array.isArray(record.chains)
			? record.chains
					.map((item) => normalizeDocumentResultChain(item))
					.filter((item): item is DocumentResultChain => item !== null)
			: []
	};
}

function normalizeDocumentVariantDossier(value: unknown): DocumentVariantDossier | null {
	const record = asRecord(value);
	if (!record) return null;

	return {
		variant_id: toOptionalText(record.variant_id),
		variant_label: toOptionalText(record.variant_label),
		material: normalizeDocumentChainMaterial(record.material),
		shared_process_state: asRecord(record.shared_process_state) ?? {},
		shared_missingness: toStringList(record.shared_missingness),
		series: Array.isArray(record.series)
			? record.series
					.map((item) => normalizeDocumentResultSeries(item))
					.filter((item): item is DocumentResultSeries => item !== null)
			: []
	};
}

function normalizeDocumentComparisonSemantics(
	value: unknown,
	collectionId: string,
	documentId: string
): DocumentComparisonSemanticsResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Document comparison semantics response is invalid.');
	}

	const items = Array.isArray(record.items) ? record.items : [];
	const variant_dossiers = Array.isArray(record.variant_dossiers)
		? record.variant_dossiers
				.map((item) => normalizeDocumentVariantDossier(item))
				.filter((item): item is DocumentVariantDossier => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		document_id: String(record.document_id ?? documentId).trim() || documentId,
		total: typeof record.total === 'number' ? record.total : items.length,
		count: typeof record.count === 'number' ? record.count : items.length,
		items,
		variant_dossiers
	};
}

function buildFixture(collectionId: string): DocumentProfilesResponse {
	const items: DocumentProfile[] = [
		{
			document_id: 'doc_a',
			collection_id: collectionId,
			title: 'High-entropy oxide cycling study',
			source_filename: 'high-entropy-oxide-cycling-study.pdf',
			doc_type: 'experimental',
			protocol_extractable: 'partial',
			protocol_extractability_signals: ['methods density', 'condition completeness'],
			parsing_warnings: [],
			confidence: 0.88
		},
		{
			document_id: 'doc_b',
			collection_id: collectionId,
			title: 'Review of interface engineering strategies',
			source_filename: 'interface-engineering-review.pdf',
			doc_type: 'review',
			protocol_extractable: 'no',
			protocol_extractability_signals: ['review contamination'],
			parsing_warnings: ['Weak procedural continuity'],
			confidence: 0.93
		},
		{
			document_id: 'doc_c',
			collection_id: collectionId,
			title: null,
			source_filename: 'mixed-experimental-survey-benchmark.txt',
			doc_type: 'mixed',
			protocol_extractable: 'uncertain',
			protocol_extractability_signals: ['critical parameter missingness'],
			parsing_warnings: ['Baseline definition varies across sections'],
			confidence: 0.64
		}
	];

	return {
		collection_id: collectionId,
		total: items.length,
		count: items.length,
		summary: {
			total_documents: items.length,
			doc_type_counts: {
				experimental: 1,
				review: 1,
				mixed: 1,
				uncertain: 0
			},
			protocol_extractable_counts: {
				yes: 0,
				partial: 1,
				no: 1,
				uncertain: 1
			},
			warnings: ['Fixture mode is enabled for document profiles.']
		},
		items
	};
}

function buildComparisonSemanticsFixture(
	collectionId: string,
	documentId: string
): DocumentComparisonSemanticsResponse {
	return {
		collection_id: collectionId,
		document_id: documentId,
		total: 1,
		count: 1,
		items: [],
		variant_dossiers: [
			{
				variant_id: 'fixture_variant',
				variant_label: 'Reduced sample',
				material: {
					label: 'High-entropy oxide',
					composition: null,
					host_material_system: null
				},
				shared_process_state: {
					process: 'reduced oxygen anneal'
				},
				shared_missingness: [],
				series: [
					{
						series_key: 'cycle retention:test_condition',
						property_family: 'cycle retention',
						test_family: 'electrochemical cycling',
						varying_axis: {
							axis_name: 'cycle count',
							axis_unit: null
						},
						chains: [
							{
								result_id: 'cres_1',
								source_result_id: 'mr_fixture_1',
								measurement: {
									property: 'cycle retention',
									value: 92,
									unit: '%',
									result_type: 'scalar',
									summary: 'Retained 92% capacity after 200 cycles.',
									statistic_type: null,
									uncertainty: null
								},
								test_condition: {
									test_method: 'cycling',
									test_temperature_c: null,
									strain_rate_s_1: null,
									loading_direction: null,
									sample_orientation: null,
									environment: null,
									frequency_hz: null,
									specimen_geometry: null,
									surface_state: null
								},
								baseline: {
									label: 'air annealed control',
									reference: 'air annealed control',
									baseline_type: 'same-document',
									resolved: true
								},
								assessment: {
									comparability_status: 'comparable',
									warnings: [],
									basis: ['fixture'],
									missing_context: [],
									requires_expert_review: false,
									assessment_epistemic_status: 'grounded'
								},
								value_provenance: {
									value_origin: 'reported',
									source_value_text: '92',
									source_unit_text: '%',
									derivation_formula: null,
									derivation_inputs: null
								},
								evidence: {
									evidence_ids: ['ev_cres_1'],
									direct_anchor_ids: ['anc_cres_1'],
									contextual_anchor_ids: [],
									structure_feature_ids: [],
									characterization_observation_ids: [],
									traceability_status: 'direct'
								}
							}
						]
					}
				]
			}
		]
	};
}

function normalizeResponse(value: unknown, collectionId: string): DocumentProfilesResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Document profiles response is invalid.');
	}

	const items = Array.isArray(record.items)
		? record.items
				.map((item) => normalizeProfile(item, collectionId))
				.filter((item): item is DocumentProfile => item !== null)
		: [];

	const summaryRecord = asRecord(record.summary);

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		total: typeof record.total === 'number' ? record.total : items.length,
		count: typeof record.count === 'number' ? record.count : items.length,
		summary: {
			total_documents:
				typeof summaryRecord?.total_documents === 'number'
					? summaryRecord.total_documents
					: typeof record.total === 'number'
						? record.total
						: items.length,
			doc_type_counts: {
				...DEFAULT_DOC_TYPE_COUNTS,
				...((summaryRecord?.doc_type_counts ?? summaryRecord?.by_doc_type) as
					| Record<DocumentType, number>
					| undefined)
			},
			protocol_extractable_counts: {
				...DEFAULT_PROTOCOL_EXTRACTABLE_COUNTS,
				...((summaryRecord?.protocol_extractable_counts ??
					summaryRecord?.by_protocol_extractable) as
					| Record<ProtocolExtractable, number>
					| undefined)
			},
			warnings: toStringList(summaryRecord?.warnings)
		},
		items
	};
}

export async function fetchDocumentProfiles(
	collectionId: string
): Promise<DocumentProfilesResponse> {
	if (USE_API_FIXTURES) {
		return buildFixture(collectionId);
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/profiles`,
		{
			method: 'GET'
		}
	);
	return normalizeResponse(data, collectionId);
}

function normalizeDocumentContent(
	value: unknown,
	collectionId: string,
	documentId: string
): DocumentContentResponse {
	const record = asRecord(value);
	if (!record) {
		throw new Error('Document content response is invalid.');
	}

	const contentText = String(record.content_text ?? '').trim();
	const blocks = Array.isArray(record.blocks)
		? record.blocks
				.map((item, index) => normalizeContentBlock(item, index))
				.filter((item): item is DocumentContentBlock => item !== null)
		: [];

	return {
		collection_id: String(record.collection_id ?? collectionId).trim() || collectionId,
		document_id: String(record.document_id ?? documentId).trim() || documentId,
		title: toOptionalText(record.title),
		source_filename: toOptionalText(record.source_filename),
		content_text: contentText,
		blocks,
		warnings: toStringList(record.warnings)
	};
}

export async function fetchDocumentContent(
	collectionId: string,
	documentId: string
): Promise<DocumentContentResponse> {
	if (USE_API_FIXTURES) {
		return {
			collection_id: collectionId,
			document_id: documentId,
			title: 'Fixture document viewer',
			source_filename: 'fixture-paper.txt',
			content_text:
				'Experimental Section\nThe precursor powders were mixed in ethanol and stirred for 2 h.\nCharacterization\nXRD and SEM were used to characterize the powders.',
			blocks: [
				{
					block_id: 'methods',
					block_type: 'methods',
					heading_path: 'Experimental Section',
					heading_level: 1,
					order: 1,
					text: 'The precursor powders were mixed in ethanol and stirred for 2 h.',
					text_unit_ids: ['tu-1'],
					start_offset: 21,
					end_offset: 84
				},
				{
					block_id: 'characterization',
					block_type: 'characterization',
					heading_path: 'Characterization',
					heading_level: 1,
					order: 2,
					text: 'XRD and SEM were used to characterize the powders.',
					text_unit_ids: ['tu-2'],
					start_offset: 102,
					end_offset: 153
				}
			],
			warnings: []
		};
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/content`,
		{
			method: 'GET'
		}
	);
	return normalizeDocumentContent(data, collectionId, documentId);
}

export async function fetchDocumentProfile(
	collectionId: string,
	documentId: string
): Promise<DocumentProfile> {
	if (USE_API_FIXTURES) {
		const fixture = buildFixture(collectionId).items.find(
			(item) => item.document_id === documentId
		);
		if (fixture) {
			return fixture;
		}
		throw new Error('Document profile fixture is missing.');
	}

	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/profile`,
		{
			method: 'GET'
		}
	);
	const profile = normalizeProfile(data, collectionId);
	if (!profile) {
		throw new Error('Document profile response is invalid.');
	}
	return profile;
}

export async function fetchDocumentComparisonSemantics(
	collectionId: string,
	documentId: string,
	options: DocumentComparisonSemanticsOptions = {}
): Promise<DocumentComparisonSemanticsResponse> {
	if (USE_API_FIXTURES) {
		return buildComparisonSemanticsFixture(collectionId, documentId);
	}

	const params = new URLSearchParams();
	if (options.includeGroupedProjections) {
		params.set('include_grouped_projections', 'true');
	}
	const query = params.toString();
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/comparison-semantics${
			query ? `?${query}` : ''
		}`,
		{
			method: 'GET'
		}
	);
	return normalizeDocumentComparisonSemantics(data, collectionId, documentId);
}
