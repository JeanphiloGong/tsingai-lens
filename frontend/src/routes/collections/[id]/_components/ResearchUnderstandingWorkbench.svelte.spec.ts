import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import ResearchUnderstandingWorkbench from './ResearchUnderstandingWorkbench.svelte';
import { authState } from '../../../_shared/auth';
import type {
	ResearchUnderstanding,
	ResearchUnderstandingPresentationFinding
} from '../../../_shared/researchView';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

type DatasetSampleFixture = {
	sample_id: string;
	finding_id: string;
	label_status: string;
	dataset_use_status: string;
	review_action: {
		code: string;
		label: string;
	};
	protocol_readiness?: {
		status: string;
		ready_after_review: boolean;
		missing: string[];
		blocking_missing: string[];
		checks: Record<string, boolean>;
		guidance: string;
	};
	acceptance_gate?: {
		status: string;
		accept_allowed: boolean;
		requires_correction: boolean;
		blocking_missing: string[];
		review_checks: string[];
		recommended_action_code: string;
		guidance: string;
	};
};

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
	return new Response(JSON.stringify(body), {
		status,
		statusText,
		headers: {
			'Content-Type': 'application/json'
		}
	});
}

function requestPath(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost').pathname;
}

function requestUrl(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost');
}

function datasetResponse(overrides: {
	trainingReady?: number;
	reviewCandidate?: number;
	rejected?: number;
	trainingMessages?: number;
	protocolReady?: number;
	itemCount?: number;
	labelCounts?: Record<string, number>;
	errorCategories?: Record<string, number>;
	presentationBuckets?: Record<string, number>;
	reviewReasons?: Record<string, number>;
	systemWarnings?: Record<string, number>;
	reviewCandidateReasons?: Record<string, number>;
	reviewCandidateWarnings?: Record<string, number>;
	scopeType?: string;
	scopeId?: string;
	datasetId?: string;
	items?: DatasetSampleFixture[];
} = {}) {
	const trainingReady = overrides.trainingReady ?? 2;
	const trainingMessages = overrides.trainingMessages ?? trainingReady;
	const protocolReady = overrides.protocolReady ?? trainingMessages;
	const reviewCandidate = overrides.reviewCandidate ?? 1;
	const rejected = overrides.rejected ?? 1;
	const errorCategories = overrides.errorCategories ?? {
		variable_error: 2,
		direction_error: 1,
		none: trainingReady
	};
	const reviewReasons = overrides.reviewReasons ?? {
		single_paper_evidence: 2,
		partial_support: 1
	};
	const systemWarnings = overrides.systemWarnings ?? {
		table_row_alignment_uncertain: 1
	};
	return {
		schema_version: 'research_understanding_dataset.v1',
		dataset_id: overrides.datasetId ?? 'rud_col_123_objective_obj_1',
		collection_id: 'col_123',
		scope_type: overrides.scopeType ?? 'objective',
		scope_id: overrides.scopeId ?? 'obj_1',
		task_type: 'research_understanding_finding',
		metric_profile: 'research_understanding_finding.v1',
		label_status_filter: null,
		dataset_use_status_filter: null,
		item_count: overrides.itemCount ?? trainingReady + reviewCandidate + rejected,
		label_counts: overrides.labelCounts ?? {
			candidate: 1,
			silver: 1,
			gold: 1,
			rejected
		},
		quality_summary: {
			training_ready_sample_count: trainingReady,
			training_message_sample_count: trainingMessages,
			protocol_ready_sample_count: protocolReady,
			review_candidate_sample_count: reviewCandidate,
			by_dataset_use_status: {
				training_ready: trainingReady,
				review_candidate: reviewCandidate,
				rejected
			},
			by_presentation_bucket: overrides.presentationBuckets ?? {
				primary: trainingReady,
				review_queue: reviewCandidate
			},
			by_error_category: errorCategories,
			by_review_reason: reviewReasons,
			by_system_warning: systemWarnings,
			by_review_candidate_reason: overrides.reviewCandidateReasons ?? reviewReasons,
			by_review_candidate_warning: overrides.reviewCandidateWarnings ?? systemWarnings
		},
		items: overrides.items ?? [],
		warnings: []
	};
}

function presentationFinding(
	finding: Omit<
		ResearchUnderstandingPresentationFinding,
		| 'expert_use_status'
		| 'dataset_use_status'
		| 'generalization_status'
		| 'generalization_note'
		| 'evidence_gap_summary'
		| 'upgrade_actions'
		| 'related_review_finding_ids'
		| 'comparison_summary'
	> & {
		expert_use_status?: string;
		dataset_use_status?: string;
		generalization_status?: string;
		generalization_note?: string;
		evidence_gap_summary?: string;
		upgrade_actions?: string[];
		related_review_finding_ids?: string[];
		comparison_summary?: ResearchUnderstandingPresentationFinding['comparison_summary'];
	}
): ResearchUnderstandingPresentationFinding {
	return {
		expert_use_status: 'review_candidate',
		dataset_use_status: 'review_candidate',
		generalization_status: 'cross_paper_candidate',
		generalization_note: '',
		evidence_gap_summary: '',
		upgrade_actions: [],
		related_review_finding_ids: [],
		comparison_summary: null,
		...finding
	};
}

function understandingFixture(): ResearchUnderstanding {
	return {
		schema_version: 'research_understanding.v1',
		state: 'ready',
		scope: {
			scope_type: 'objective',
			collection_id: 'col_123',
			material_id: null,
			objective_id: 'obj_1',
			document_id: null,
			title: 'LPBF 316L heat treatment'
		},
		claims: [
			{
				claim_id: 'claim_strength_supported',
				claim_type: 'finding',
				statement: 'Heat treatment changes LPBF 316L tensile response.',
				status: 'supported',
				confidence: 0.9,
				strength: 'moderate',
				evidence_ref_ids: ['ev_table_2'],
				context_ids: ['ctx_heat_treatment'],
				source_object_ids: ['unit_measure'],
				warnings: []
			},
			{
				claim_id: 'claim_mechanism_limited',
				claim_type: 'mechanism',
				statement: 'Annealing may reduce cellular substructure.',
				status: 'limited',
				confidence: 0.64,
				strength: null,
				evidence_ref_ids: ['ev_section_3'],
				context_ids: ['ctx_heat_treatment'],
				source_object_ids: ['unit_interpretation'],
				warnings: ['needs_expert_review']
			},
			{
				claim_id: 'claim_comparison_conflict',
				claim_type: 'comparison',
				statement: 'Strength trends conflict across reported heat treatments.',
				status: 'conflicted',
				confidence: 0.51,
				strength: 'weak',
				evidence_ref_ids: ['ev_conflict'],
				context_ids: ['ctx_heat_treatment'],
				source_object_ids: ['unit_compare'],
				warnings: ['conflicting_direction']
			}
		],
		relations: [
			{
				relation_id: 'rel_annealing_microstructure',
				relation_type: 'explains',
				subject: 'annealing',
				predicate: 'explains',
				object: 'cellular substructure change',
				statement: 'Annealing explains cellular substructure changes in LPBF 316L.',
				conditions: ['316L stainless steel', 'LPBF'],
				status: 'limited',
				confidence: 0.64,
				evidence_ref_ids: ['ev_section_3'],
				context_ids: ['ctx_heat_treatment'],
				source_object_ids: ['unit_interpretation'],
				warnings: []
			},
			{
				relation_id: 'rel_internal_sample',
				relation_type: 'increases',
				subject: 'sample_number: 2',
				predicate: 'increases',
				object: 'sample_context: {"sample": 2}',
				statement: null,
				conditions: [],
				status: 'supported',
				confidence: 0.95,
				evidence_ref_ids: ['ev_section_3'],
				context_ids: ['ctx_heat_treatment'],
				source_object_ids: ['unit_interpretation'],
				warnings: []
			}
		],
		evidence_refs: [
			{
				evidence_ref_id: 'ev_table_2',
				source_kind: 'table',
				document_id: 'doc_1',
				label: 'P001 Table 2',
				locator: { source_ref: 'Table 2', page: 5 },
				fact_ids: ['unit_measure'],
				anchor_ids: ['anc_1'],
				confidence: 0.9,
				traceability_status: 'traceable',
				evidence_role: 'direct_support',
				quote: null,
				href: null
			},
			{
				evidence_ref_id: 'ev_section_3',
				source_kind: 'text_window',
				document_id: 'doc_1',
				label: 'P001 Section 3.2',
				locator: { source_ref: 'Section 3.2', page: 7 },
				fact_ids: ['unit_interpretation'],
				anchor_ids: [],
				confidence: 0.64,
				traceability_status: 'traceable',
				evidence_role: 'mediator_context',
				quote: 'Annealing reduced cellular substructure.',
				href: null
			},
			{
				evidence_ref_id: 'ev_conflict',
				source_kind: 'table',
				document_id: 'doc_2',
				label: 'P002 Table 4',
				locator: { source_ref: 'Table 4', page: 9 },
				fact_ids: ['unit_compare'],
				anchor_ids: [],
				confidence: 0.51,
				traceability_status: 'traceable',
				evidence_role: 'conflict',
				quote: null,
				href: null
			}
		],
		contexts: [
			{
				context_id: 'ctx_heat_treatment',
				label: 'Heat treatment scope',
				material_scope: ['316L stainless steel'],
				process_context: { process: 'LPBF', treatment: 'annealing' },
				test_condition: { method: 'tensile test' },
				property_scope: ['yield strength'],
				limitations: ['single paper mechanism claim']
			}
		],
		warnings: [],
		summary: {
			claim_count: 3,
			relation_count: 1,
			evidence_ref_count: 3,
			context_count: 1
		},
		presentation: {
			summary: {
				title: 'LPBF 316L heat treatment',
				material_scope: ['316L stainless steel'],
				variable_axes: ['LPBF', 'annealing'],
				property_scope: ['yield strength'],
				claim_count: 3,
				relation_count: 1,
				evidence_count: 3,
				context_count: 1,
				review_queue_count: 2,
				primary_finding_count: 1,
				review_queue_finding_count: 2,
				collection_document_count: 6,
				axis_coverage: {
					variables: [
						{
							axis: 'heat treatment',
							status: 'primary',
							finding_id: 'finding_strength_supported'
						},
						{
							axis: 'annealing',
							status: 'review_queue',
							finding_id: 'finding_mechanism_limited'
						},
						{
							axis: 'laser power',
							status: 'missing',
							finding_id: ''
						}
					],
					properties: [
						{
							axis: 'yield strength',
							status: 'primary',
							finding_id: 'finding_strength_supported'
						},
						{
							axis: 'elongation',
							status: 'missing',
							finding_id: ''
						}
					]
				}
			},
			effects: [
				{
					effect_id: 'effect_strength_supported',
					claim_id: 'claim_strength_supported',
					title: 'Heat treatment -> yield strength',
					statement: 'Heat treatment changes LPBF 316L tensile response.',
					claim_type: 'finding',
					support_status: 'supported',
					confidence: 0.9,
					effect_direction: '',
					variable_axis: 'heat treatment',
					target_property: 'yield strength',
					paper_count: 1,
					evidence_count: 1,
					context_summary: '316L stainless steel, LPBF, annealing, tensile test',
					evidence_ref_ids: ['ev_table_2'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					needs_review: false,
					warnings: []
				},
				{
					effect_id: 'effect_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					title: 'Annealing -> yield strength',
					statement: 'Annealing may reduce cellular substructure.',
					claim_type: 'mechanism',
					support_status: 'limited',
					confidence: 0.64,
					effect_direction: 'explains',
					variable_axis: 'annealing',
					target_property: 'yield strength',
					paper_count: 1,
					evidence_count: 1,
					context_summary: '316L stainless steel, LPBF, annealing, tensile test',
					evidence_ref_ids: ['ev_section_3'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: ['rel_annealing_microstructure', 'rel_internal_sample'],
					needs_review: true,
					warnings: ['needs_expert_review']
				},
				{
					effect_id: 'effect_comparison_conflict',
					claim_id: 'claim_comparison_conflict',
					title: 'Heat treatment -> yield strength conflict',
					statement: 'Strength trends conflict across reported heat treatments.',
					claim_type: 'comparison',
					support_status: 'conflicted',
					confidence: 0.51,
					effect_direction: 'compares',
					variable_axis: 'heat treatment',
					target_property: 'yield strength',
					paper_count: 1,
					evidence_count: 1,
					context_summary: '316L stainless steel, LPBF, annealing, tensile test',
					evidence_ref_ids: ['ev_conflict'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					needs_review: true,
					warnings: ['conflicting_direction']
				}
			],
			findings: [
				presentationFinding({
					finding_id: 'finding_strength_supported',
					claim_id: 'claim_strength_supported',
					title: 'Heat treatment -> yield strength',
					statement: 'Heat treatment changes LPBF 316L tensile response.',
					variables: ['heat treatment'],
					mediators: ['densification'],
					outcomes: ['yield strength'],
					direction: '',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'partial',
					review_status: 'pending_review',
					confidence: 0.9,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_table_2'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					evidence_bundle: {
						direct_result: ['ev_table_2'],
						mechanism: [],
						condition_context: [],
						background: [],
						conflict: [],
						noise: [],
						uncategorized: []
					},
					comparison_summary: {
						variable: 'heat treatment type',
						direction: 'increases',
						outcome: 'density',
						baseline: {
							label: 'heat treatment type -',
							value: '90.04 %'
						},
						observed: {
							label: 'heat treatment type Furnace HT',
							value: '93.58 %'
						},
						controlled_conditions: [
							{ axis: 'laser power', value: '120' },
							{ axis: 'scan speed', value: '280' }
						]
					},
					expert_use_status: 'paper_level_finding',
					dataset_use_status: 'review_candidate',
					generalization_status: 'paper_level_only',
					generalization_note:
						'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
					evidence_gap_summary:
						'Needs independent cross-paper confirmation, support-grade curation, expert review.',
					upgrade_actions: [
						'verify_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'partial_support',
						'needs_expert_review',
						'has_unreviewed_comparable_candidates'
					],
					related_review_finding_ids: ['finding_comparison_conflict'],
					warnings: []
				}),
				presentationFinding({
					finding_id: 'finding_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					title: 'Annealing -> cellular substructure change',
					statement: 'Annealing may reduce cellular substructure.',
					variables: ['annealing'],
					mediators: ['cellular substructure'],
					outcomes: ['yield strength'],
					direction: 'explains',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'weak',
					review_status: 'needs_review',
					confidence: 0.64,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_section_3'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: ['rel_annealing_microstructure', 'rel_internal_sample'],
					evidence_bundle: {
						direct_result: [],
						mechanism: ['ev_section_3'],
						condition_context: [],
						background: [],
						conflict: [],
						noise: [],
						uncategorized: []
					},
					expert_use_status: 'evidence_repair_needed',
					dataset_use_status: 'review_candidate',
					upgrade_actions: [
						'repair_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'missing_direct_result_evidence',
						'weak_support',
						'needs_expert_review'
					],
					warnings: ['needs_expert_review']
				}),
				presentationFinding({
					finding_id: 'finding_comparison_conflict',
					claim_id: 'claim_comparison_conflict',
					title: 'Heat treatment -> yield strength conflict',
					statement: 'Strength trends conflict across reported heat treatments.',
					variables: ['heat treatment'],
					mediators: ['densification'],
					outcomes: ['yield strength'],
					direction: 'compares',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'conflict',
					review_status: 'needs_review',
					confidence: 0.51,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_conflict'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					evidence_bundle: {
						direct_result: [],
						mechanism: [],
						condition_context: [],
						background: [],
						conflict: ['ev_conflict'],
						noise: [],
						uncategorized: []
					},
					expert_use_status: 'evidence_repair_needed',
					dataset_use_status: 'review_candidate',
					upgrade_actions: [
						'repair_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'resolve_conflict',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'needs_expert_review'
					],
					warnings: ['conflicting_direction']
				})
			],
			primary_findings: [
				presentationFinding({
					finding_id: 'finding_strength_supported',
					claim_id: 'claim_strength_supported',
					title: 'Heat treatment -> yield strength',
					statement: 'Heat treatment changes LPBF 316L tensile response.',
					variables: ['heat treatment'],
					mediators: [],
					outcomes: ['yield strength'],
					direction: '',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'partial',
					review_status: 'pending_review',
					confidence: 0.9,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_table_2'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					evidence_bundle: {
						direct_result: ['ev_table_2'],
						mechanism: [],
						condition_context: [],
						background: [],
						conflict: [],
						noise: [],
						uncategorized: []
					},
					comparison_summary: {
						variable: 'heat treatment type',
						direction: 'increases',
						outcome: 'density',
						baseline: {
							label: 'heat treatment type -',
							value: '90.04 %'
						},
						observed: {
							label: 'heat treatment type Furnace HT',
							value: '93.58 %'
						},
						controlled_conditions: [
							{ axis: 'laser power', value: '120' },
							{ axis: 'scan speed', value: '280' }
						]
					},
					expert_use_status: 'paper_level_finding',
					dataset_use_status: 'review_candidate',
					generalization_status: 'paper_level_only',
					generalization_note:
						'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
					evidence_gap_summary:
						'Needs independent cross-paper confirmation, support-grade curation, expert review.',
					upgrade_actions: [
						'verify_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'partial_support',
						'needs_expert_review',
						'has_unreviewed_comparable_candidates'
					],
					related_review_finding_ids: ['finding_comparison_conflict'],
					warnings: []
				})
			],
			review_queue_findings: [
				presentationFinding({
					finding_id: 'finding_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					title: 'Annealing -> cellular substructure change',
					statement: 'Annealing may reduce cellular substructure.',
					variables: ['annealing'],
					mediators: ['cellular substructure'],
					outcomes: ['yield strength'],
					direction: 'explains',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'weak',
					review_status: 'needs_review',
					confidence: 0.64,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_section_3'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: ['rel_annealing_microstructure', 'rel_internal_sample'],
					evidence_bundle: {
						direct_result: [],
						mechanism: ['ev_section_3'],
						condition_context: [],
						background: [],
						conflict: [],
						noise: [],
						uncategorized: []
					},
					expert_use_status: 'evidence_repair_needed',
					dataset_use_status: 'review_candidate',
					upgrade_actions: [
						'repair_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'missing_direct_result_evidence',
						'weak_support',
						'needs_expert_review'
					],
					warnings: ['needs_expert_review']
				}),
				presentationFinding({
					finding_id: 'finding_comparison_conflict',
					claim_id: 'claim_comparison_conflict',
					title: 'Heat treatment -> yield strength conflict',
					statement: 'Strength trends conflict across reported heat treatments.',
					variables: ['heat treatment'],
					mediators: [],
					outcomes: ['yield strength'],
					direction: 'compares',
					scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					support_grade: 'conflict',
					review_status: 'needs_review',
					confidence: 0.51,
					paper_count: 1,
					evidence_count: 1,
					evidence_ref_ids: ['ev_conflict'],
					context_ids: ['ctx_heat_treatment'],
					relation_ids: [],
					evidence_bundle: {
						direct_result: [],
						mechanism: [],
						condition_context: [],
						background: [],
						conflict: ['ev_conflict'],
						noise: [],
						uncategorized: []
					},
					expert_use_status: 'evidence_repair_needed',
					dataset_use_status: 'review_candidate',
					upgrade_actions: [
						'repair_direct_evidence',
						'add_cross_paper_evidence',
						'curate_support_grade',
						'resolve_conflict',
						'record_expert_review'
					],
					review_reasons: [
						'single_paper_evidence',
						'needs_cross_paper_confirmation',
						'needs_expert_review'
					],
					warnings: ['conflicting_direction']
				})
			],
			evidence_items: [
				{
					evidence_ref_id: 'ev_table_2',
					document_id: 'doc_1',
					title: 'P001 Table 2 / p. 5',
					source_label: 'P001 Table 2',
					source_kind: 'table',
					source_ref: 'tbl_2',
					block_type: 'table',
					heading_path: 'Results / Mechanical testing',
					page: '5',
					quote:
						'Table 2. Columns: Build platform conditions | Yield strength | Elongation Rows: Non-preheated | 448 | 72 / Preheated | 465 | 82',
					source_text:
						'Table 2. Columns: Build platform conditions | Yield strength | Elongation Rows: Non-preheated | 448 | 72 / Preheated | 465 | 82',
					value_summary: 'P001 Table 2',
					table_audit: {
						columns: ['Build platform conditions', 'Yield strength', 'Elongation'],
						relevant_rows: [
							{ row_index: 1, cells: ['Non-preheated', '448', '72'], aligned: true },
							{ row_index: 2, cells: ['Preheated', '465', '82'], aligned: true },
							{ row_index: 3, cells: ['Parsed short row', '470'], aligned: false }
						]
					},
					traceability_status: 'traceable',
					evidence_role: 'direct_support',
					confidence: 0.9,
					href: null
				},
				{
					evidence_ref_id: 'ev_section_3',
					document_id: 'doc_1',
					title: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_P001 Section 3.2 / p. 7',
					source_label: 'P001 Section 3.2',
					source_kind: 'text_window',
					source_ref: 'blk_section_3_2',
					block_type: 'paragraph',
					heading_path: 'Results / Microstructure',
					page: '7',
					quote: 'Annealing reduced cellular substructure.',
					source_text:
						'Annealing reduced cellular substructure after LPBF processing. This paragraph is the original parsed source block used as evidence.',
					value_summary: 'P001 Section 3.2',
					table_audit: null,
					traceability_status: 'traceable',
					evidence_role: 'mediator_context',
					confidence: 0.64,
					href: null
				},
				{
					evidence_ref_id: 'ev_conflict',
					document_id: 'doc_2',
					title: 'P002 Table 4 / p. 9',
					source_label: 'P002 Table 4',
					source_kind: 'table',
					source_ref: 'tbl_4',
					block_type: 'table',
					heading_path: 'Results / Heat treatment comparison',
					page: '9',
					quote: null,
					source_text: null,
					value_summary: 'P002 Table 4',
					table_audit: null,
					traceability_status: 'traceable',
					evidence_role: 'conflict',
					confidence: 0.51,
					href: null
				}
			],
			context_summaries: [
				{
					context_id: 'ctx_heat_treatment',
					label: 'Heat treatment scope',
					material_scope: ['316L stainless steel'],
					property_scope: ['yield strength'],
					process_summary: 'LPBF, annealing',
					test_summary: 'tensile test',
					limitations: ['single paper mechanism claim']
				}
			]
		}
	};
}

function goalUnderstandingFixture(): ResearchUnderstanding {
	const fixture = understandingFixture();
	return {
		...fixture,
		scope: {
			...fixture.scope,
			scope_type: 'goal',
			goal_id: 'goal_1',
			objective_id: null,
			title: 'Confirmed heat-treatment goal'
		}
	};
}

function findingOnlyUnderstandingFixture(): ResearchUnderstanding {
	const fixture = understandingFixture();
	const noisySemContext =
		'SLM processed 316L stainless steel samples were characterized in FEI-INSPECT 50 SEM. Same samples used for microhardness testing were used for SEM characterizations as well. The samples were polished using different grades of polishing cloths from 400 to 1200 and then polished for 30 min on a micro cloth using colloidal silica. SEM characterization was done on horizontal as well as on vertical sections of each sample.';
	const finding: ResearchUnderstandingPresentationFinding = presentationFinding({
		finding_id: 'finding_relation_density',
		claim_id: 'claim_relation_density',
		title: 'VED -> density',
		statement:
			"The achieved density measured using the Archimedes ' method was 91.9, 98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively.",
		variables: ['VED'],
		mediators: ['porosity'],
		outcomes: ['density'],
		direction: 'increases',
		scope_summary: 'stainless steel 316L, VED, density, selective laser melting',
		support_grade: 'partial',
		review_status: 'pending_review',
		confidence: 0.88,
		paper_count: 1,
		evidence_count: 1,
		evidence_ref_ids: ['ev_density_quote'],
		context_ids: [
			'ctx_density_objective',
			'ctx_density_noisy_sem',
			'ctx_density_internal',
			'ctx_density_numeric',
			'ctx_density_off_axis_fatigue'
		],
		relation_ids: ['rel_density_quote'],
		evidence_bundle: {
			direct_result: ['ev_density_quote'],
			mechanism: [],
			condition_context: [],
			background: [],
			conflict: [],
			noise: [],
			uncategorized: []
		},
		review_reasons: ['single_paper_evidence', 'needs_cross_paper_confirmation', 'partial_support'],
		warnings: []
	});
	const returnValue = {
		...fixture,
		presentation: {
			...fixture.presentation,
			summary: {
				...fixture.presentation.summary,
				primary_finding_count: 1,
				review_queue_finding_count: 0,
				collection_document_count: 6
			},
			findings: [finding],
			primary_findings: [finding],
			review_queue_findings: [],
			effects: [],
			evidence_items: [
				{
					evidence_ref_id: 'ev_density_quote',
					document_id: 'doc_1',
					title: 'P003 Results / p. 3',
					source_label: 'P003 Results',
					source_kind: 'text_window',
					source_ref: 'blk_density_results',
					block_type: 'paragraph',
					heading_path: 'Results / Density',
					page: '3',
					quote:
						"The achieved density measured using the Archimedes ' method was 91.9, 98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively.",
					source_text:
						'L-VED, M-VED and H-VED samples reached 91.9, 98.9 and 99.6 % density, respectively.',
					value_summary: 'P003 Results',
					table_audit: null,
					traceability_status: 'traceable',
					evidence_role: 'direct_support',
					confidence: 0.88,
					href: null
				},
				{
					evidence_ref_id: 'ev_density_aim',
					document_id: 'doc_1',
					title: 'P003 Abstract / p. 1',
					source_label: 'P003 Abstract',
					source_kind: 'text_window',
					source_ref: 'blk_density_abstract',
					block_type: 'paragraph',
					heading_path: 'Abstract',
					page: '1',
					quote: 'This study aims to understand how VED changes LPBF 316L density.',
					source_text:
						'This study aims to understand how VED changes LPBF 316L density and microstructure, but it does not report the measured result.',
					value_summary: 'P003 Abstract',
					table_audit: null,
					traceability_status: 'traceable',
					evidence_role: null,
					confidence: 0.45,
					href: null
				}
			],
			context_summaries: [
				{
					context_id: 'ctx_density_objective',
					label: 'Objective scope',
					material_scope: ['stainless steel 316L'],
					property_scope: ['density'],
					process_summary: 'VED, variable, selective laser melting, test specimen',
					test_summary: 'Archimedes method, test specimen',
					limitations: []
				},
				{
					context_id: 'ctx_density_noisy_sem',
					label: 'Claim applicability',
					material_scope: ['stainless steel 316L'],
					property_scope: ['density'],
					process_summary: '0.114, A, 0.25, density_porosity_microstructure, oeu_6b9838393120',
					test_summary: noisySemContext,
					limitations: []
				},
				{
					context_id: 'ctx_density_internal',
					label: 'Claim applicability',
					material_scope: ['stainless steel 316L'],
					property_scope: ['density'],
					process_summary: 'oeu_48def1c60d60, 100, 280, HIP, 8, 91.54',
					test_summary: 'density_porosity_microstructure, SEM / ImageJ',
					limitations: []
				},
				{
					context_id: 'ctx_density_numeric',
					label: 'Claim applicability',
					material_scope: ['stainless steel 316L'],
					property_scope: ['density'],
					process_summary: '0.12, B, 0.111, 6, 14',
					test_summary: 'SEM / ImageJ',
					limitations: []
				},
				{
					context_id: 'ctx_microhardness_off_target',
					label: 'Claim applicability',
					material_scope: ['stainless steel 316L'],
					property_scope: ['microhardness'],
					process_summary:
						'samples processed via scanning strategy B and C, selective laser melting, 150 J/mm³, 0.111 mm/s, A, 316L',
					test_summary: 'ASTM B842',
					limitations: []
				},
				{
					context_id: 'ctx_density_off_axis_fatigue',
					label: 'Claim applicability',
					material_scope: ['stainless steel 316L'],
					property_scope: ['density'],
					process_summary:
						'condition without preheating the build platform, porosity level, fatigue tests, HIP-SLM',
					test_summary: 'fatigue testing, machined specimens',
					limitations: []
				}
			]
		}
	};
	const relationFinding = returnValue.presentation.findings[0];
	relationFinding.evidence_count = 2;
	relationFinding.evidence_ref_ids = ['ev_density_quote', 'ev_density_aim'];
	relationFinding.evidence_bundle.uncategorized = ['ev_density_aim'];
	relationFinding.context_ids = [...relationFinding.context_ids, 'ctx_microhardness_off_target'];
	return returnValue;
}

function findingWithPrimaryReviewFixture(): ResearchUnderstanding {
	const fixture = findingOnlyUnderstandingFixture();
	const primaryFinding = fixture.presentation.primary_findings[0];
	primaryFinding.review_status = 'needs_review';
	fixture.presentation.findings = [primaryFinding];
	fixture.presentation.primary_findings = [primaryFinding];
	fixture.presentation.review_queue_findings = [];
	fixture.presentation.summary = {
		...fixture.presentation.summary,
		primary_finding_count: 1,
		review_queue_finding_count: 0,
		review_queue_count: 0,
		collection_document_count: 6
	};
	return fixture;
}

function fullyCoveredDraftAnswerFixture(): ResearchUnderstanding {
	const fixture = findingOnlyUnderstandingFixture();
	const primaryFinding = fixture.presentation.primary_findings[0];
	fixture.presentation.summary = {
		...fixture.presentation.summary,
		axis_coverage: {
			variables: [
				{
					axis: 'VED',
					status: 'primary',
					finding_id: primaryFinding.finding_id
				}
			],
			properties: [
				{
					axis: 'density',
					status: 'primary',
					finding_id: primaryFinding.finding_id
				}
			]
		}
	};
	return fixture;
}

function reviewOnlyFindingProjectionFixture(): ResearchUnderstanding {
	const fixture = findingOnlyUnderstandingFixture();
	const reviewFinding = fixture.presentation.primary_findings[0];
	reviewFinding.finding_id = 'finding_review_only';
	reviewFinding.claim_id = 'claim_review_only';
	reviewFinding.title = 'scan strategy rotation angle and build orientation -> yield strength';
	reviewFinding.statement =
		'Scan strategy rotation angles and build orientations can be used to predict crystallographic texture changes and Bishop-Hill yield strength in LPBF 316L.';
	reviewFinding.review_status = 'needs_review';
	reviewFinding.support_grade = 'weak';
	reviewFinding.expert_use_status = 'review_candidate';
	reviewFinding.warnings = ['model_validation_finding'];
	fixture.presentation.findings = [reviewFinding];
	fixture.presentation.primary_findings = [];
	fixture.presentation.review_queue_findings = [reviewFinding];
	fixture.presentation.summary = {
		...fixture.presentation.summary,
		primary_finding_count: 0,
		review_queue_finding_count: 1,
		review_queue_count: 1,
		collection_document_count: 6
	};
	return fixture;
}

function primaryOnlyFindingProjectionFixture(): ResearchUnderstanding {
	const fixture = findingOnlyUnderstandingFixture();
	const primaryFinding = fixture.presentation.primary_findings[0];
	fixture.presentation.findings = [];
	fixture.presentation.primary_findings = [primaryFinding];
	fixture.presentation.review_queue_findings = [];
	return fixture;
}

function findingWithDuplicateEvidenceTargetsFixture(): ResearchUnderstanding {
	const fixture = findingOnlyUnderstandingFixture();
	const finding = fixture.presentation.primary_findings[0];
	finding.evidence_count = 2;
	finding.evidence_ref_ids = ['ev_density_quote', 'ev_density_quote_duplicate'];
	finding.evidence_bundle.direct_result = ['ev_density_quote'];
	finding.evidence_bundle.uncategorized = ['ev_density_quote_duplicate'];
	fixture.presentation.findings = [finding];
	fixture.presentation.primary_findings = [finding];
	fixture.presentation.review_queue_findings = [];
	fixture.presentation.evidence_items = [
		...fixture.presentation.evidence_items,
		{
			...fixture.presentation.evidence_items[0],
			evidence_ref_id: 'ev_density_quote_duplicate',
			evidence_role: null
		}
	];
	return fixture;
}

async function openMechanismClaimDetail(
	findingName: RegExp = /Annealing may reduce cellular substructure\./
) {
	await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();
	await browserPage.getByRole('button', { name: 'Weak 1' }).click();
	await browserPage.getByRole('button', { name: findingName }).click();
	return browserPage.getByLabelText('Finding detail');
}

async function openConflictedClaimDetail() {
	await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();
	await browserPage.getByRole('button', { name: 'Conflict 1' }).click();
	await browserPage
		.getByRole('button', { name: /Strength trends conflict across reported heat treatments\./ })
		.click();
	return browserPage.getByLabelText('Finding detail');
}

function currentDatasetRegionText() {
	return (
		Array.from(document.querySelectorAll('details'))
			.map((element) => element.textContent ?? '')
			.find((text) => text.includes('Training ready') && text.includes('Needs review')) ?? ''
	);
}

function datasetSummaryLocator() {
	return browserPage.getByText('Dataset', { exact: true });
}

function collectionDatasetGetRequestCount() {
	return fetchMock.mock.calls.filter(([input, init]) => {
		const method =
			input instanceof Request
				? input.method
				: typeof (init as RequestInit | undefined)?.method === 'string'
					? (init as RequestInit).method
					: 'GET';
		return (
			requestPath(input as string | URL | Request).endsWith(
				'/research-understanding/dataset/collection'
			) && method === 'GET'
		);
	}).length;
}

function clickDatasetSummary(datasetRegion: HTMLDetailsElement | null) {
	const summary = datasetRegion?.querySelector('summary');
	expect(summary).toBeTruthy();
	(summary as HTMLElement).click();
}

describe('ResearchUnderstandingWorkbench', () => {
	beforeEach(() => {
		authState.set({
			status: 'authenticated',
			user: {
				user_id: 'user_materials_expert',
				email: 'materials-expert@example.com',
				display_name: 'Materials Expert'
			}
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset/collection') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 15,
							rejected: 0,
							scopeType: 'collection',
							scopeId: 'goal',
							datasetId: 'rud_col_123_collection_goal'
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(
					jsonResponse({
						curation_id: 'ruc_saved_1234567890',
						collection_id: 'col_123',
						scope_type: 'objective',
						scope_id: 'obj_1',
						finding_id: 'finding_mechanism_limited',
						claim_id: 'claim_mechanism_limited',
						curated_claim_type: 'mechanism',
						curated_status: 'limited',
						curated_statement:
							'Annealing may reduce cellular substructure, but the mechanism evidence is limited.',
						curated_support_grade: 'weak',
						curated_review_status: 'needs_review',
						curated_variables: ['annealing'],
						curated_mediators: ['cellular substructure'],
						curated_outcomes: ['yield strength'],
						curated_direction: 'explains',
						curated_scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
						curated_evidence_ref_ids: ['ev_section_3'],
						curated_context_ids: ['ctx_heat_treatment'],
						note: 'Keep limited until EBSD evidence is added.',
						reviewer: 'materials-expert@example.com',
						updated_at: '2026-06-18T09:00:00+00:00'
					})
				);
			}
			return Promise.resolve(
				jsonResponse({
					feedback_id: 'ruf_saved_1234567890',
					collection_id: 'col_123',
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					review_status: 'incorrect',
					issue_type: 'evidence_not_grounded',
					note: 'Mechanism claim needs direct microstructure evidence.',
					reviewer: 'materials-expert@example.com',
					created_at: '2026-06-18T09:00:00+00:00'
				})
			);
		});
	});

	it('marks AI-reviewed findings as silver review candidates, not training-ready gold', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								feedback_id: 'ruf_ai_reviewed',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_strength_supported',
								claim_id: 'claim_strength_supported',
								review_status: 'correct',
								issue_type: 'none',
								note: 'AI evidence audit accepted the source quote.',
								reviewer: 'ai-reviewer-codex-evidence-audit',
								created_at: '2026-07-11T09:00:00+00:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse({ trainingReady: 0, reviewCandidate: 1 })));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect.element(findingsTable.getByText('Silver', { exact: true })).toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Review candidate · AI reviewed', { exact: true }))
			.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Gold', { exact: true })).not.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Training-ready', { exact: true }))
			.not.toBeInTheDocument();

		await findingsTable.getByRole('button', {
			name: /Heat treatment changes LPBF 316L tensile response/
		}).click();
		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(findingDetail.getByText('Silver', { exact: true }).first()).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Review candidate', { exact: true }).first())
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('AI reviewed', { exact: true }).first())
			.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText(
					'AI review keeps this as a silver review candidate; human confirmation is still required before training-ready use.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText(
					'Accepted expert review or curation can make this usable as a labeled training/evaluation sample.'
				)
			)
			.not.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Gold', { exact: true })).not.toBeInTheDocument();
	});

	it('prioritizes table row verification in finding review actions', async () => {
		const fixture = understandingFixture();
		for (const findingRows of [fixture.presentation.findings, fixture.presentation.primary_findings]) {
			const finding = findingRows.find((item) => item.finding_id === 'finding_strength_supported');
			if (!finding) continue;
			finding.review_reasons = [
				...finding.review_reasons,
				'table_row_alignment_uncertain'
			];
			finding.warnings = ['table_row_alignment_uncertain'];
		}

		render(ResearchUnderstandingWorkbench, {
			understanding: fixture,
			collectionId: 'col_123'
		});

		await browserPage
			.getByRole('button', { name: /Heat treatment changes LPBF 316L tensile response/ })
			.click();

		const reviewPriorities = browserPage.getByLabelText('Review priorities');
		await expect
			.element(
				reviewPriorities.getByText(
					'Verify the parsed table rows against the original source table before accepting or correcting.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				reviewPriorities.getByText(
					'Selected table rows do not align cleanly with the parsed columns; verify the source table before accepting.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				reviewPriorities.getByText(
					'Accept only as paper-level evidence unless another paper confirms, contradicts, or extends it.'
				)
			)
			.not.toBeInTheDocument();
	});

	it('prioritizes mechanism evidence decisions when direct evidence exists', async () => {
		const fixture = understandingFixture();
		for (const findingRows of [fixture.presentation.findings, fixture.presentation.primary_findings]) {
			const finding = findingRows.find((item) => item.finding_id === 'finding_strength_supported');
			if (!finding) continue;
			finding.review_reasons = ['missing_mechanism_evidence', 'needs_expert_review'];
			finding.warnings = [];
		}

		render(ResearchUnderstandingWorkbench, {
			understanding: fixture,
			collectionId: 'col_123'
		});

		await browserPage
			.getByRole('button', { name: /Heat treatment changes LPBF 316L tensile response/ })
			.click();

		const reviewPriorities = browserPage.getByLabelText('Review priorities');
		await expect
			.element(
				reviewPriorities.getByText(
					'Decide whether mechanism evidence is required for the final label; otherwise scope the finding to the direct result.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(reviewPriorities.getByText('Mechanism evidence is not yet linked.'))
			.toBeInTheDocument();
	});

	it('shows human accepted training-ready findings without stale needs-review badges', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								feedback_id: 'ruf_human_reviewed',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_strength_supported',
								claim_id: 'claim_strength_supported',
								review_status: 'correct',
								issue_type: 'none',
								note: 'Human expert accepted the source-backed paper-level finding.',
								reviewer: 'materials-expert@example.com',
								created_at: '2026-07-13T09:00:00+00:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 0,
							itemCount: 1,
							labelCounts: { candidate: 0, silver: 0, gold: 1, rejected: 0 }
						})
					)
				);
			}
			return Promise.resolve(jsonResponse({}));
		});
		const fixture = understandingFixture();
		fixture.presentation.findings[0].review_status = 'needs_review';
		fixture.presentation.findings[0].review_reasons = [
			'single_paper_evidence',
			'needs_cross_paper_confirmation',
			'partial_support',
			'needs_expert_review'
		];
		fixture.presentation.findings[0].warnings = ['needs_expert_review'];
		fixture.presentation.primary_findings[0].review_status = 'needs_review';
		fixture.presentation.primary_findings[0].review_reasons = [
			'single_paper_evidence',
			'needs_cross_paper_confirmation',
			'partial_support',
			'needs_expert_review'
		];
		fixture.presentation.primary_findings[0].warnings = ['needs_expert_review'];

		render(ResearchUnderstandingWorkbench, {
			understanding: fixture,
			collectionId: 'col_123'
		});

		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect.element(findingsTable.getByText('Feedback 1', { exact: true })).toBeInTheDocument();
		await expect.element(findingsTable.getByText('Gold', { exact: true })).toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Training-ready · Human confirmed', { exact: true }))
			.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Accepted', { exact: true })).toBeInTheDocument();
		await expect.element(findingsTable.getByText('Needs review', { exact: true })).not.toBeInTheDocument();

		await findingsTable
			.getByRole('button', { name: /Heat treatment changes LPBF 316L tensile response/ })
			.click();
		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(findingDetail.getByText('Gold', { exact: true }).first()).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Training-ready', { exact: true }).first())
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Human confirmed', { exact: true }).first()).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Accepted', { exact: true }).first()).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Needs review', { exact: true }))
			.not.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('needs expert review', { exact: true }))
			.not.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText(
					'Expert review is still required before using this as a settled conclusion.'
				)
			)
			.not.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Record expert feedback or curation for the final label.'))
			.not.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText(
					'Needs independent cross-paper confirmation, support-grade curation, expert review.'
				)
			)
			.not.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText('Find a second paper that confirms, contradicts, or extends it.')
			)
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Curate the support grade before treating it as strong.'))
			.toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText(
					'Review this finding before using it for model evaluation, training data, or downstream answers.'
				)
			)
			.not.toBeInTheDocument();
	});

	it('filters findings by dataset use status from current expert review state', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								feedback_id: 'ruf_human_reviewed',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_strength_supported',
								claim_id: 'claim_strength_supported',
								review_status: 'correct',
								issue_type: 'none',
								note: 'Human expert accepted the source-backed paper-level finding.',
								reviewer: 'materials-expert@example.com',
								created_at: '2026-07-13T09:00:00+00:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 2,
							itemCount: 3,
							labelCounts: { candidate: 2, silver: 0, gold: 1, rejected: 0 }
						})
					)
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('button', { name: 'All uses 1' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Training-ready 1' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Training-ready 1' }).click();

		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect
			.element(findingsTable.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Training-ready · Human confirmed', { exact: true }))
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();
		await expect
			.element(browserPage.getByRole('button', { name: 'Review candidate 2' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Review candidate 2' }).click();
		await expect
			.element(findingsTable.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(
				findingsTable.getByText('Strength trends conflict across reported heat treatments.').first()
			)
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.not.toBeInTheDocument();
	});

	it('opens directly on dataset review candidates from a review queue deep link', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123',
			initialFocus: 'review_queue'
		});

		await expect
			.element(browserPage.getByRole('button', { name: 'Review candidate 3' }))
			.toHaveAttribute('aria-pressed', 'true');
		await expect.element(browserPage.getByText('3 of 3')).toBeInTheDocument();
		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect
			.element(findingsTable.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(
				findingsTable.getByText('Strength trends conflict across reported heat treatments.').first()
			)
			.toBeInTheDocument();
	});

	it('uses dataset review-candidate count for expert review progress', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse({ reviewCandidate: 3 })));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const summary = browserPage.getByLabelText('Research understanding summary');
		await expect.element(summary.getByText('Candidate queue')).toBeInTheDocument();
		await expect.element(summary.getByText('3')).toBeInTheDocument();

		const expertSummary = browserPage.getByLabelText('Expert readiness summary');
		await expect
			.element(
				expertSummary.getByText(
					'3 candidate finding(s) remain in the review queue; do not treat them as usable conclusions until curated.'
				)
			)
			.toBeInTheDocument();
	});

	it('opens a specific review candidate finding from a deep link', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123',
			initialFocus: 'review_queue',
			initialFindingId: 'finding_mechanism_limited'
		});

		await expect
			.element(browserPage.getByRole('button', { name: 'Review candidate 3' }))
			.toHaveAttribute('aria-pressed', 'true');
		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(findingDetail.getByText('Review candidate 2 of 3')).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept paper-level', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Reject', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Correct', exact: true }))
			.toBeInTheDocument();
	});

	it('shows the backend dataset review action in selected finding details', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_mechanism_limited',
									finding_id: 'finding_mechanism_limited',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'review_table_rows',
										label: 'Review selected table rows'
									},
									acceptance_gate: {
										status: 'review_required',
										accept_allowed: true,
										requires_correction: false,
										blocking_missing: [],
										review_checks: [
											'Verify the selected table rows, variable columns, and outcome values.'
										],
										recommended_action_code: 'review_table_rows',
										guidance: 'Accept only after checking the source table rows.'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingDetail = await openMechanismClaimDetail();
		await expect.element(findingDetail.getByText('Review selected table rows')).toBeInTheDocument();
		const gatePanel = findingDetail.getByLabelText('Acceptance gate');
		await expect.element(gatePanel.getByText('Accept after review')).toBeInTheDocument();
		await expect
			.element(gatePanel.getByText('Accept only after checking the source table rows.'))
			.toBeInTheDocument();
		await expect
			.element(
				gatePanel.getByText('Verify the selected table rows, variable columns, and outcome values.')
			)
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Repair evidence binding')).not.toBeInTheDocument();
	});

	it('shows protocol readiness for a selected review candidate', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_mechanism_limited',
									finding_id: 'finding_mechanism_limited',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'accept_as_paper_level',
										label: 'Accept as paper-level evidence'
									},
									protocol_readiness: {
										status: 'ready_after_review',
										ready_after_review: true,
										missing: ['expert_review_decision'],
										blocking_missing: [],
										checks: {
											expert_review_decision: false,
											statement: true,
											variables: true,
											outcomes: true,
											direction_or_scope: true,
											traceable_training_evidence: true
										},
										guidance: 'accept or correct before protocol use'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingDetail = await openMechanismClaimDetail();
		const protocolPanel = findingDetail.getByLabelText('Protocol readiness');
		await expect.element(protocolPanel.getByText('Ready after expert review')).toBeInTheDocument();
		await expect
			.element(
				protocolPanel.getByText(
					'The protocol fields are complete; accepting or correcting this finding will make it usable for traceable experiment drafts.'
				)
			)
			.toBeInTheDocument();
		await expect.element(protocolPanel.getByText('Blocking gaps')).toBeInTheDocument();
		await expect.element(protocolPanel.getByText('expert review decision')).toBeInTheDocument();
	});

	it('explains when the running backend omits protocol readiness detail', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_mechanism_limited',
									finding_id: 'finding_mechanism_limited',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'accept_as_paper_level',
										label: 'Accept as paper-level evidence'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingDetail = await openMechanismClaimDetail();
		const protocolPanel = findingDetail.getByLabelText('Protocol readiness');
		await expect
			.element(protocolPanel.getByText('Readiness detail unavailable'))
			.toBeInTheDocument();
		await expect
			.element(
				protocolPanel.getByText(
					'The running backend returned a dataset sample without protocol readiness details. Treat this finding as review-only until the backend is updated or restarted.'
				)
			)
			.toBeInTheDocument();
	});

	it('shows blocking protocol gaps before a finding can be accepted for protocol drafting', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_strength_supported',
									finding_id: 'finding_strength_supported',
									label_status: 'candidate',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'correct_protocol_fields',
										label: 'Correct protocol fields'
									},
									protocol_readiness: {
										status: 'needs_correction',
										ready_after_review: false,
										missing: ['variables', 'direction_or_scope', 'traceable_training_evidence'],
										blocking_missing: [
											'variables',
											'direction_or_scope',
											'traceable_training_evidence'
										],
										checks: {
											expert_review_decision: false,
											statement: true,
											variables: false,
											direction_or_scope: false,
											traceable_training_evidence: false
										},
										guidance: 'Correct variables, direction, and evidence before accepting.'
									},
									acceptance_gate: {
										status: 'correction_required',
										accept_allowed: false,
										requires_correction: true,
										blocking_missing: [
											'variables',
											'direction_or_scope',
											'traceable_training_evidence'
										],
										review_checks: [],
										recommended_action_code: 'correct_protocol_fields',
										guidance: 'Do not accept directly; correct or reject the blocking gaps first.'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage
			.getByRole('button', { name: /Heat treatment changes LPBF 316L tensile response/ })
			.click();

		const protocolPanel = browserPage
			.getByLabelText('Finding detail')
			.getByLabelText('Protocol readiness');
		const gatePanel = browserPage.getByLabelText('Finding detail').getByLabelText('Acceptance gate');
		await expect.element(gatePanel.getByText('Correct before accept')).toBeInTheDocument();
		await expect
			.element(
				gatePanel.getByText('Do not accept directly; correct or reject the blocking gaps first.')
			)
			.toBeInTheDocument();
		await expect.element(gatePanel.getByText('variables', { exact: true })).toBeInTheDocument();
		await expect.element(protocolPanel.getByText('Needs correction before use')).toBeInTheDocument();
		await expect
			.element(protocolPanel.getByText('Correct variables, direction, and evidence before accepting.'))
			.toBeInTheDocument();
		await expect.element(protocolPanel.getByText('variables', { exact: true })).toBeInTheDocument();
		await expect
			.element(protocolPanel.getByText('direction or scope', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(protocolPanel.getByText('traceable source evidence', { exact: true }))
			.toBeInTheDocument();
	});

	it('shows the backend dataset review action in the findings table', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_strength_supported',
									finding_id: 'finding_strength_supported',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'accept_as_paper_level',
										label: 'Accept as paper-level evidence'
									},
									protocol_readiness: {
										status: 'ready_after_review',
										ready_after_review: true,
										missing: ['expert_review_decision'],
										blocking_missing: ['expert_review_decision'],
										checks: {
											expert_review_decision: false
										},
										guidance: 'accept or correct before protocol use'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect
			.element(findingsTable.getByText('Accept as paper-level evidence'))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('button', { name: 'Accept paper-level' }))
			.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Verify 1 direct evidence link(s) against the parsed source text.')).not.toBeInTheDocument();
	});

	it('surfaces the next review candidate in the review loop', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_strength_supported',
									finding_id: 'finding_strength_supported',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'accept_as_paper_level',
										label: 'Accept as paper-level evidence'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const reviewLoop = browserPage.getByLabelText('Review loop');
		await expect.element(reviewLoop.getByText('Next review candidate')).toBeInTheDocument();
		await expect
			.element(reviewLoop.getByText('Heat treatment changes LPBF 316L tensile response.'))
			.toBeInTheDocument();
		await expect.element(reviewLoop.getByText('Accept as paper-level evidence')).toBeInTheDocument();
		await expect.element(reviewLoop.getByText('5 review reason(s)')).toBeInTheDocument();
		await expect.element(reviewLoop.getByText('Evidence comes from one paper.')).toBeInTheDocument();
		await expect.element(reviewLoop.getByText('Support is partial.')).toBeInTheDocument();
		await expect.element(reviewLoop.getByText('heat treatment', { exact: true })).toBeInTheDocument();
		await expect.element(reviewLoop.getByText('yield strength', { exact: true })).toBeInTheDocument();
		await expect.element(reviewLoop.getByRole('button', { name: 'Review evidence' })).toBeInTheDocument();
		await expect
			.element(reviewLoop.getByRole('button', { name: 'Accept paper-level' }))
			.not.toBeInTheDocument();
		await expect.element(reviewLoop.getByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
		await expect.element(reviewLoop.getByRole('button', { name: 'Correct' })).not.toBeInTheDocument();
	});

	it('labels selected paper-level accept actions without implying cross-paper acceptance', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							reviewCandidate: 1,
							items: [
								{
									sample_id: 'rud_sample_mechanism_limited',
									finding_id: 'finding_mechanism_limited',
									label_status: 'silver',
									dataset_use_status: 'review_candidate',
									review_action: {
										code: 'accept_as_paper_level',
										label: 'Accept as paper-level evidence'
									}
								}
							]
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingDetail = await openMechanismClaimDetail();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept paper-level', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept paper-level and next' }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept', exact: true }))
			.not.toBeInTheDocument();
	});

	it('falls back to paper-level accept labels for single-paper findings without dataset actions', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const findingDetail = await openMechanismClaimDetail();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept paper-level', exact: true }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept', exact: true }))
			.not.toBeInTheDocument();
	});

	it('opens directly on training-ready findings and dataset exports from a messages deep link', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								feedback_id: 'ruf_human_reviewed',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_strength_supported',
								claim_id: 'claim_strength_supported',
								review_status: 'correct',
								issue_type: 'none',
								note: 'Human expert accepted the source-backed paper-level finding.',
								reviewer: 'materials-expert@example.com',
								created_at: '2026-07-13T09:00:00+00:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							trainingMessages: 0,
							protocolReady: 0,
							reviewCandidate: 2,
							itemCount: 3,
							labelCounts: { candidate: 2, silver: 0, gold: 1, rejected: 0 }
						})
					)
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123',
			initialFocus: 'training_ready'
		});

		await expect
			.element(browserPage.getByRole('button', { name: 'Training-ready 1' }))
			.toHaveAttribute('aria-pressed', 'true');
		await expect.element(browserPage.getByText('1 of 3')).toBeInTheDocument();
		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect
			.element(findingsTable.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Training-ready · Human confirmed', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Annealing may reduce cellular substructure.').first())
			.not.toBeInTheDocument();
		const datasetRegion = document.querySelector(
			'.research-understanding-workbench__dataset'
		) as HTMLDetailsElement | null;
		expect(datasetRegion?.open).toBe(true);
		const datasetText = datasetRegion?.textContent ?? '';
		expect(datasetText).toContain('Training messages 0');
		expect(datasetText).toContain('Protocol ready 0');
		const messagesLink = browserPage.getByRole('link', { name: 'Training messages JSONL' });
		await expect.element(messagesLink).toBeInTheDocument();
		const messagesUrl = new URL(messagesLink.element().getAttribute('href') ?? '', 'http://localhost');
		expect(messagesUrl.searchParams.get('format')).toBe('messages_jsonl');
		expect(messagesUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
	});

	it('opens the next review candidate detail from the review loop', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Review next finding' }).click();

		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(findingDetail.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Accept paper-level', exact: true }))
			.toBeInTheDocument();
		await expect.element(findingDetail.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
		await expect.element(findingDetail.getByRole('button', { name: 'Correct' })).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('Table 2. Columns: Build platform conditions').first())
			.toBeInTheDocument();
	});

	it('shows an expert acceptance checklist for the goal review loop', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const checklist = browserPage.getByLabelText('Expert acceptance checklist');
		await expect.element(checklist.getByText('Findings are readable')).toBeInTheDocument();
		await expect
			.element(
				checklist.getByText(
					'3 finding(s) are visible with variable, outcome, condition, and support status.'
				)
			)
			.toBeInTheDocument();
		await expect.element(checklist.getByText('Evidence is auditable')).toBeInTheDocument();
		await expect
			.element(
				checklist.getByText(
					'2 finding(s) still lack direct result evidence and should be repaired or rejected.'
				)
			)
			.toBeInTheDocument();
		await expect.element(checklist.getByText('Human review is closed')).toBeInTheDocument();
		await expect
			.element(
				checklist.getByText('1 candidate finding(s) still need accept, reject, or correction.')
			)
			.toBeInTheDocument();
		await expect.element(checklist.getByText('Training export is ready')).toBeInTheDocument();
		await expect
			.element(
				checklist.getByText(
					'2 training message sample(s) can be exported for evaluation or fine-tuning preparation.'
				)
			)
			.toBeInTheDocument();
		await expect.element(checklist.getByText('Protocol drafting is safe')).toBeInTheDocument();
	});

	it('accepts the selected finding and advances to the next review candidate', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'POST') {
				const body = JSON.parse(String(init?.body ?? '{}'));
				return Promise.resolve(
					jsonResponse({
						feedback_id: `ruf_${body.finding_id}`,
						collection_id: 'col_123',
						scope_type: body.scope_type,
						scope_id: body.scope_id,
						finding_id: body.finding_id,
						claim_id: body.claim_id,
						review_status: body.review_status,
						issue_type: body.issue_type,
						note: body.note,
						reviewer: 'materials-expert@example.com',
						created_at: '2026-07-13T09:00:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Review next finding' }).click();
		await browserPage.getByRole('button', { name: 'Accept paper-level and next' }).click();

		const feedbackPayloads = fetchMock.mock.calls
			.filter(([input, init]) => {
				return (
					requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
					(init as RequestInit | undefined)?.method === 'POST'
				);
			})
			.map(([, init]) => JSON.parse(String((init as RequestInit).body)));
		expect(feedbackPayloads).toHaveLength(1);
		expect(feedbackPayloads[0]).toMatchObject({
			finding_id: 'finding_strength_supported',
			review_status: 'correct',
			issue_type: 'none',
			note: 'Human expert accepted the source-backed paper-level finding.'
		});
		await expect
			.element(
				browserPage.getByText(
					'Dataset now has 2 training-ready, 2 message-exportable, 2 protocol-ready, and 1 review-candidate sample(s).',
					{ exact: false }
				)
			)
			.toBeInTheDocument();
		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(findingDetail.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
	});

	it('filters claim rows by type and opens the selected claim detail', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Findings' }))
			.toBeInTheDocument();
		const summary = browserPage.getByLabelText('Research understanding summary');
		await expect.element(summary.getByText('Primary findings', { exact: true })).toBeInTheDocument();
		await expect
			.element(summary.getByText('1 / 6 papers covered by primary findings'))
			.toBeInTheDocument();
		await expect.element(summary.getByText('Direct evidence', { exact: true })).toBeInTheDocument();
		await expect.element(summary.getByText('Relations')).not.toBeInTheDocument();
		const expertSummary = browserPage.getByLabelText('Expert readiness summary');
		await expect.element(expertSummary.getByText('Paper-level evidence')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Paper-level evidence', { exact: true }).first())
			.toBeInTheDocument();
		await expect
			.element(expertSummary.getByText('Review before use', { exact: true }))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Ready', { exact: true })).not.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText(
					'1 paper-level finding(s) can be used for source-grounded review, but need another paper or expert review before becoming cross-paper conclusions.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(expertSummary.getByText(/review candidate finding\(s\) need expert review or curation/))
			.not.toBeInTheDocument();
		await expect
			.element(expertSummary.getByText(/1 finding\(s\) are backed by one paper only/))
			.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText(
					'1 finding(s) have partial support; curate the support grade before using them as strong findings.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText(
					'2 finding(s) are weak, conflicted, or insufficient and should not be used directly.'
				)
			)
			.not.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText('2 finding(s) lack direct result evidence and need source repair.')
			)
			.not.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText(
					'2 candidate finding(s) remain in the review queue; do not treat them as usable conclusions until curated.'
				)
			)
			.toBeInTheDocument();
		const goalCoverage = browserPage.getByLabelText('Goal coverage');
		await expect.element(goalCoverage.getByRole('heading', { name: 'Goal coverage' })).toBeInTheDocument();
		const answerBoundary = browserPage.getByLabelText('Answer boundary');
		await expect.element(answerBoundary.getByText('The goal is only partially answered')).toBeInTheDocument();
		await expect
			.element(
				answerBoundary.getByText(
					'Primary findings cover 1/3 requested variable axis(es) and 1/2 requested outcome axis(es).'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				answerBoundary.getByText(
					'Not yet conclusion-ready: annealing, laser power, elongation'
				)
			)
			.toBeInTheDocument();
		await expect.element(answerBoundary.getByText(/Scope or mechanism only/)).not.toBeInTheDocument();
		const coverageGaps = browserPage.getByLabelText('Coverage gaps');
		await expect
			.element(
				coverageGaps.getByText(
					'Requested axes not backed by primary findings yet. Treat these as missing evidence or review work before using the goal result.'
				)
			)
			.toBeInTheDocument();
		await expect.element(coverageGaps.getByText('Missing', { exact: true })).toBeInTheDocument();
		await expect.element(coverageGaps.getByText('laser power, elongation')).toBeInTheDocument();
		await expect.element(coverageGaps.getByText('Review candidates')).toBeInTheDocument();
		await expect.element(coverageGaps.getByText('annealing')).toBeInTheDocument();
		await expect.element(coverageGaps.getByText('finding_strength_supported')).not.toBeInTheDocument();
		await expect.element(goalCoverage.getByText('Variables', { exact: true })).toBeInTheDocument();
		await expect.element(goalCoverage.getByText('Outcomes', { exact: true })).toBeInTheDocument();
		await expect
			.element(goalCoverage.getByRole('button', { name: 'heat treatment Primary finding' }))
			.toBeInTheDocument();
		await expect
			.element(goalCoverage.getByRole('button', { name: 'annealing Candidate' }))
			.toBeInTheDocument();
		await expect.element(goalCoverage.getByText('laser power', { exact: true })).toBeInTheDocument();
		await expect.element(goalCoverage.getByText('elongation', { exact: true })).toBeInTheDocument();
		await expect.element(goalCoverage.getByText('finding_strength_supported')).not.toBeInTheDocument();
		await goalCoverage.getByRole('button', { name: 'heat treatment Primary finding' }).click();
		await expect.element(browserPage.getByLabelText('Finding detail')).toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Back to findings' }).click();
		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Evidence grade' }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Current use' }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Use boundary' }))
			.not.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Actions' }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Variables' }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('columnheader', { name: 'Mechanism' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('1 of 1')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Paper-level finding', { exact: true }))
			.toBeInTheDocument();
		await expect.element(findingsTable.getByText('1 / 6 papers covered')).toBeInTheDocument();
		await expect
			.element(
				findingsTable.getByText(
					'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.'
				)
			)
			.not.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('1 direct evidence', { exact: true }))
			.toBeInTheDocument();
		await expect.element(findingsTable.getByText('90.04 % -> 93.58 %')).toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('Fixed: laser power 120; scan speed 280'))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('316L stainless steel, LPBF, annealing +1 more'))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByText('316L stainless steel, LPBF, annealing, tensile test'))
			.not.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Direct 1')).not.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Mechanism 0')).not.toBeInTheDocument();
		await expect.element(findingsTable.getByText('Conflict 0')).not.toBeInTheDocument();
		await expect.element(findingsTable.getByRole('link', { name: /P001 Table 2/ })).not.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('button', { name: 'Review evidence' }))
			.toBeInTheDocument();
		await expect
			.element(findingsTable.getByRole('button', { name: 'Reject' }))
			.toBeInTheDocument();
		await findingsTable.getByRole('button', { name: 'Reject' }).click();
		await expect
			.element(
				browserPage
					.getByLabelText('Finding detail')
					.getByRole('heading', { name: 'Expert feedback' })
			)
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Back to findings' }).click();
		await expect
			.element(
				browserPage.getByText(
					'Needs another paper to confirm, contradict, or extend it.',
					{ exact: true }
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Annealing may reduce cellular substructure.').first())
			.not.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('Strength trends conflict across reported heat treatments.').first()
			)
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Finding detail')).not.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /Heat treatment -> yield strength/ }).click();
		const primaryDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(primaryDetail.getByText('Use as paper-level finding')).toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Single-paper finding')).toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Paper-level only')).toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText(
					'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.'
				)
			)
			.toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Comparison')).toBeInTheDocument();
		await expect
			.element(primaryDetail.getByText('heat treatment type -> density'))
			.toBeInTheDocument();
		await expect.element(primaryDetail.getByText('90.04 % -> 93.58 %')).toBeInTheDocument();
		await expect
			.element(primaryDetail.getByText('Fixed: laser power 120; scan speed 280'))
			.toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText('This finding has direct source support, but only from one paper.')
			)
			.toBeInTheDocument();
		const evidenceBasis = primaryDetail.getByLabelText('Evidence basis');
		await expect.element(evidenceBasis.getByText('Evidence basis')).toBeInTheDocument();
		await expect.element(evidenceBasis.getByText('1 / 6 papers covered')).toBeInTheDocument();
		const roleCoverage = primaryDetail.getByLabelText('Evidence role coverage');
		await expect.element(roleCoverage.getByText('Direct 1')).toBeInTheDocument();
		await expect.element(roleCoverage.getByText('Mechanism 1')).toBeInTheDocument();
		await expect.element(roleCoverage.getByText('Conflict 0')).toBeInTheDocument();
		await expect
			.element(
				roleCoverage.getByText(
					'Mechanism is stated, but mechanism evidence is not linked.'
				)
			)
			.not.toBeInTheDocument();
		await expect
			.element(
				roleCoverage.getByText(
					'Needs another paper before it can be treated as a cross-paper finding.'
				)
			)
			.toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Selected quote').first()).toBeInTheDocument();
		const tableEvidenceCard = primaryDetail
			.getByText('P001 Table 2')
			.first()
			.element()
			.closest('.research-understanding-workbench__evidence');
		expect(tableEvidenceCard).toBeTruthy();
		expect(tableEvidenceCard?.textContent).toContain('Relevant table rows');
		expect(tableEvidenceCard?.textContent).toContain(
			'Build platform conditions | Yield strength | Elongation'
		);
		expect(tableEvidenceCard?.textContent).toContain('Non-preheated | 448 | 72');
		expect(tableEvidenceCard?.textContent).toContain('Preheated | 465 | 82');
		const tableEvidenceHref = tableEvidenceCard?.querySelector('a[href]')?.getAttribute('href') ?? '';
		expect(tableEvidenceHref).toContain('view=parsed-paper');
		expect(new URL(tableEvidenceHref, 'http://localhost').searchParams.get('quote')).toBe(
			'Table 2. Columns: Build platform conditions | Yield strength | Elongation Rows: Non-preheated | 448 | 72 / Preheated | 465 | 82'
		);
		const usagePath = primaryDetail.getByLabelText('Expert use path');
		await expect.element(usagePath.getByText('Current use')).toBeInTheDocument();
		await expect.element(usagePath.getByText('Paper-level finding')).toBeInTheDocument();
		await expect
			.element(
				usagePath.getByText(
					'Use this as a traceable finding from one paper. Do not generalize it across the collection yet.'
				)
			)
			.toBeInTheDocument();
		await expect.element(usagePath.getByText('Dataset status')).toBeInTheDocument();
		await expect
			.element(
				usagePath.getByText(
					'Keep this as a review candidate until expert feedback or curation records the final label.'
				)
			)
			.toBeInTheDocument();
		await expect.element(usagePath.getByText('Upgrade checklist')).toBeInTheDocument();
		await expect
			.element(
				usagePath.getByText('Verify 1 direct evidence link(s) against the parsed source text.')
			)
			.toBeInTheDocument();
		await expect
			.element(
				usagePath.getByText('Find a second paper that confirms, contradicts, or extends it.')
			)
			.toBeInTheDocument();
		await expect
			.element(usagePath.getByText('Curate the support grade before treating it as strong.'))
			.toBeInTheDocument();
		await expect
			.element(usagePath.getByText('Record expert feedback or curation for the final label.'))
			.toBeInTheDocument();
		const reviewPriorities = primaryDetail.getByLabelText('Review priorities');
		await expect.element(reviewPriorities.getByText('Review priorities')).toBeInTheDocument();
		await expect
			.element(
				reviewPriorities.getByText(
					'Accept only as paper-level evidence unless another paper confirms, contradicts, or extends it.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(reviewPriorities.getByText('Evidence comes from one paper.'))
			.toBeInTheDocument();
		await expect
			.element(
				reviewPriorities.getByText('Comparable candidate findings are waiting in the review queue.')
			)
			.toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Conclusion use boundary')).toBeInTheDocument();
		await expect.element(primaryDetail.getByText('Paper-level only')).toBeInTheDocument();
		await expect
			.element(evidenceBasis.getByText('Evidence comes from one paper.'))
			.toBeInTheDocument();
		await expect
			.element(evidenceBasis.getByText('Needs another paper to confirm, contradict, or extend it.'))
			.toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText(
					'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText(
					'Needs independent cross-paper confirmation, support-grade curation, expert review.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				reviewPriorities.getByText('Needs expert review before use as a settled conclusion.')
			)
			.toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText(
					'Use this as a paper-level finding, not a settled cross-paper conclusion.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(
				primaryDetail.getByText(
					'Review this finding before using it for model evaluation, training data, or downstream answers.'
				)
			)
			.toBeInTheDocument();
		const relatedReview = primaryDetail.getByLabelText('Review candidates to check');
		await expect.element(relatedReview.getByText('Review candidates to check')).toBeInTheDocument();
		await expect
			.element(
				relatedReview.getByText(
					'Use these candidates to confirm, contradict, or extend this paper-level finding before upgrading it.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(relatedReview.getByText('Strength trends conflict across reported heat treatments.'))
			.toBeInTheDocument();
		await relatedReview
			.getByRole('button', { name: /Strength trends conflict across reported heat treatments/ })
			.click();
		const relatedDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(relatedDetail.getByText('Strength trends conflict across reported heat treatments.'))
			.toBeInTheDocument();
		await expect.element(relatedDetail.getByText('Do not use yet')).toBeInTheDocument();
		const conflictReviewPriorities = relatedDetail.getByLabelText('Review priorities');
		await expect
			.element(
				conflictReviewPriorities.getByText(
					'Resolve the conflicting evidence before using this finding downstream.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(conflictReviewPriorities.getByText('Evidence contains conflicting directions.'))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Back to findings' }).click();
		await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();
		await browserPage.getByRole('button', { name: /Heat treatment -> yield strength/ }).click();
		await expect.element(primaryDetail.getByText('Direct result evidence')).toBeInTheDocument();
		const tableAudit = primaryDetail
			.getByText('Relevant table rows')
			.first()
			.element()
			.closest('.research-understanding-workbench__table-audit');
		expect(tableAudit?.textContent).toContain(
			'Build platform conditions: Non-preheated; Yield strength: 448; Elongation: 72'
		);
		expect(tableAudit?.textContent).toContain(
			'Build platform conditions: Preheated; Yield strength: 465; Elongation: 82'
		);
		expect(tableAudit?.textContent).toContain('Unaligned cells: Parsed short row | 470');
		expect(tableAudit?.textContent).toContain(
			'Some selected rows are not aligned with the parsed columns.'
		);
		await browserPage.getByRole('button', { name: 'Back to findings' }).click();

		const claimDetail = await openMechanismClaimDetail();
		await expect.element(claimDetail).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Back to findings' }))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Mechanism evidence')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('Variables')).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('316L stainless steel, LPBF, annealing, tensile test'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('annealing', { exact: true })).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('cellular substructure', { exact: true }))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Outcomes yield strength')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('P001 Section 3.2').first()).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'))
			.not.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Annealing reduced cellular substructure.'))
			.toBeInTheDocument();
		const sourceBlock = claimDetail
			.getByText('Parsed source block', { exact: true })
			.element()
			.closest('details');
		expect(sourceBlock).toBeTruthy();
		expect(sourceBlock?.textContent).toContain(
			'Annealing reduced cellular substructure after LPBF processing. This paragraph is the original parsed source block used as evidence.'
		);
		await expect
			.element(claimDetail.getByText('paragraph · p. 7 · Results / Microstructure · traceable'))
			.toBeInTheDocument();
		const evidenceCard = claimDetail
			.getByText('P001 Section 3.2')
			.first()
			.element()
			.closest('.research-understanding-workbench__evidence');
		expect(evidenceCard).toBeTruthy();
		const evidenceHref = evidenceCard?.querySelector('a[href]')?.getAttribute('href') ?? '';
		expect(evidenceHref).toContain('view=parsed-paper');
		expect(new URL(evidenceHref, 'http://localhost').searchParams.get('quote')).toBe(
			'Annealing reduced cellular substructure.'
		);
		await expect
			.element(claimDetail.getByText('LPBF, annealing', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('needs expert review', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Annealing -> cellular substructure change'))
			.toBeInTheDocument();
		await expect
			.element(
				claimDetail.getByText('Annealing explains cellular substructure changes in LPBF 316L.')
			)
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Context: 316L stainless steel, LPBF'))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('1 low-level relation(s) are hidden until normalized.'))
			.toBeInTheDocument();
		const mechanismReviewPriorities = claimDetail.getByLabelText('Review priorities');
		await expect
			.element(
				mechanismReviewPriorities.getByText(
					'Repair or reject the evidence binding before accepting this finding.'
				)
			)
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('sample_number: 2')).not.toBeInTheDocument();
		await expect
			.element(claimDetail.getByRole('button', { name: 'Expert feedback' }))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByRole('button', { name: 'Expert curation' }))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByLabelText('Review result')).not.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Back to findings' }).click();
		await expect.element(browserPage.getByText('1 of 2')).toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Finding detail')).not.toBeInTheDocument();
	});

	it('labels fully covered paper-level findings as a draft answer before expert use', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: fullyCoveredDraftAnswerFixture(),
			collectionId: 'col_123'
		});

		const answerBoundary = browserPage.getByLabelText('Answer boundary');
		await expect
			.element(answerBoundary.getByText('The goal has a source-grounded draft answer'))
			.toBeInTheDocument();
		await expect
			.element(answerBoundary.getByText('The goal has expert-ready findings'))
			.not.toBeInTheDocument();
		await expect
			.element(
				answerBoundary.getByText(
					'Needs expert review or curation before conclusion: VED -> density'
				)
			)
			.toBeInTheDocument();
	});

	it('does not ask for curation after a covered finding is training-ready', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								curation_id: 'ruc_density_accepted',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_relation_density',
								claim_id: 'claim_relation_density',
								curated_claim_type: 'finding',
								curated_status: 'limited',
								curated_statement:
									"VED increased LPBF 316L density from 91.9% to 99.6% in the cited Archimedes measurements.",
								curated_support_grade: 'partial',
								curated_review_status: 'accepted',
								curated_variables: ['VED'],
								curated_mediators: ['porosity'],
								curated_outcomes: ['density'],
								curated_direction: 'increases',
								curated_scope_summary: 'stainless steel 316L, VED, density',
								curated_evidence_ref_ids: ['ev_density_quote'],
								curated_context_ids: ['ctx_density_objective'],
								note: 'Human expert accepted the source-grounded finding.',
								reviewer: 'materials-expert@example.com',
								updated_at: '2026-07-13T09:00:00+08:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse({ trainingReady: 1, reviewCandidate: 0 })));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: fullyCoveredDraftAnswerFixture(),
			collectionId: 'col_123'
		});

		const answerBoundary = browserPage.getByLabelText('Answer boundary');
		await expect
			.element(answerBoundary.getByText('The goal has expert-ready findings'))
			.toBeInTheDocument();
		await expect
			.element(answerBoundary.getByText(/Needs expert review or curation before conclusion/))
			.not.toBeInTheDocument();
	});

	it('does not present low-level effects as expert-ready findings when finding projection is missing', async () => {
		const fixture = understandingFixture();
		fixture.presentation.findings = [];
		fixture.presentation.primary_findings = [];
		fixture.presentation.review_queue_findings = [];
		fixture.presentation.summary.primary_finding_count = 0;
		fixture.presentation.summary.review_queue_finding_count = 0;

		render(ResearchUnderstandingWorkbench, {
			understanding: fixture,
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Findings' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByLabelText('Research understanding summary'))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Dataset export')).not.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Only low-level candidate effects are available. Review or curate them before treating them as expert findings.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('columnheader', { name: 'Claim' }))
			.not.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByRole('button', {
					name: /Annealing may reduce cellular substructure\./
				})
			)
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Claim detail')).not.toBeInTheDocument();
	});

	it('shows dataset readiness counts and same-origin export links', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain(
			'4 finding sample(s) can be exported. Gold is expert-confirmed; candidate still needs review.'
		);
		const datasetText = datasetRegion?.textContent ?? '';
		expect(datasetText).toContain('Candidate 1');
		expect(datasetText).toContain('Training ready 2');
		expect(datasetText).toContain('Training messages 2');
		expect(datasetText).toContain('Needs review 1');
		expect(datasetText).toContain(
			'Training exports include evidence-grounded user/assistant messages for evaluation or fine-tuning preparation.'
		);
		expect(datasetText).toContain('Silver 1');
		expect(datasetText).toContain('Gold 1');
		expect(datasetText).toContain('Rejected 1');
		expect(datasetText).toContain(
			'Gold is human-confirmed and can become training-ready; Silver is AI or non-human review and still needs expert confirmation.'
		);
		expect(datasetText).toContain('Common error categories');
		expect(datasetText).toContain('Variable error 2');
		expect(datasetText).toContain('Direction error 1');
		expect(datasetText).toContain('Review priorities');
		expect(datasetText).toContain('Single-paper evidence 2');
		expect(datasetText).toContain('Partial support 1');
		expect(datasetText).toContain('System warnings');
		expect(datasetText).toContain('Table row alignment uncertain 1');
		expect(datasetText).not.toContain('No issue');

		const jsonUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Training JSON', exact: true })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(jsonUrl.pathname).toBe('/api/v1/collections/col_123/research-understanding/dataset');
		expect(jsonUrl.searchParams.get('scope_type')).toBe('objective');
		expect(jsonUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(jsonUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
		expect(jsonUrl.searchParams.get('format')).toBe('json');

		const jsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Training JSONL', exact: true })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(jsonlUrl.pathname).toBe('/api/v1/collections/col_123/research-understanding/dataset');
		expect(jsonlUrl.searchParams.get('scope_type')).toBe('objective');
		expect(jsonlUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(jsonlUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
		expect(jsonlUrl.searchParams.get('format')).toBe('jsonl');

		const messagesJsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Training messages JSONL' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(messagesJsonlUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(messagesJsonlUrl.searchParams.get('scope_type')).toBe('objective');
		expect(messagesJsonlUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(messagesJsonlUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
		expect(messagesJsonlUrl.searchParams.get('format')).toBe('messages_jsonl');

		const reviewJsonUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Review candidates JSON' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(reviewJsonUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(reviewJsonUrl.searchParams.get('scope_type')).toBe('objective');
		expect(reviewJsonUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(reviewJsonUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
		expect(reviewJsonUrl.searchParams.get('format')).toBe('json');

		const reviewJsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Review JSONL template' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(reviewJsonlUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(reviewJsonlUrl.searchParams.get('scope_type')).toBe('objective');
		expect(reviewJsonlUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(reviewJsonlUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
		expect(reviewJsonlUrl.searchParams.get('format')).toBe('review_jsonl');

		const reviewPacketUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Review packet' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(reviewPacketUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(reviewPacketUrl.searchParams.get('scope_type')).toBe('objective');
		expect(reviewPacketUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(reviewPacketUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
		expect(reviewPacketUrl.searchParams.get('format')).toBe('review_packet');

		const decisionTemplateUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Decision template' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(decisionTemplateUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(decisionTemplateUrl.searchParams.get('scope_type')).toBe('objective');
		expect(decisionTemplateUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(decisionTemplateUrl.searchParams.get('dataset_use_status')).toBe(
			'review_candidate'
		);
		expect(decisionTemplateUrl.searchParams.get('format')).toBe('decision_template');

		const datasetGetCall = fetchMock.mock.calls.find(([input, init]) => {
			const url = requestUrl(input as string | URL | Request);
			return (
				url.pathname.endsWith('/research-understanding/dataset') &&
				((init as RequestInit | undefined)?.method ?? 'GET') === 'GET'
			);
		}) as [string | URL | Request, RequestInit | undefined] | undefined;
		expect(datasetGetCall).toBeTruthy();
		const [input] = datasetGetCall!;
		const requestedUrl = requestUrl(input);
		expect(requestedUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset'
		);
		expect(requestedUrl.searchParams.get('scope_type')).toBe('objective');
		expect(requestedUrl.searchParams.get('scope_id')).toBe('obj_1');
		expect(requestedUrl.searchParams.get('dataset_use_status')).toBeNull();
		expect(requestedUrl.searchParams.get('format')).toBeNull();
	});

	it('exposes collection-level training export links on goal scopes', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = init?.method ?? 'GET';
			if (path.endsWith('/research-understanding/dataset/collection') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 15,
							rejected: 0,
							errorCategories: {
								variable_error: 3,
								evidence_error: 2,
								none: 1
							},
							labelCounts: {
								candidate: 4,
								silver: 10,
								gold: 1,
								rejected: 0
							},
							presentationBuckets: {
								primary: 5,
								review_queue: 10
							},
							reviewReasons: {
								single_paper_evidence: 9,
								needs_cross_paper_confirmation: 7
							},
							systemWarnings: {
								table_row_alignment_uncertain: 4
							},
							scopeType: 'collection',
							scopeId: 'goal',
							datasetId: 'rud_col_123_collection_goal'
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		expect(collectionDatasetGetRequestCount()).toBe(0);
		clickDatasetSummary(datasetRegion);
		await expect.poll(() => collectionDatasetGetRequestCount()).toBe(1);
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain(
			'1 training-ready, 1 message-exportable, 1 protocol-ready, and 15 review-candidate goal sample(s) in this collection.'
		);
		const datasetText = datasetRegion?.textContent ?? '';
		expect(datasetText).toContain('Collection dataset');
		expect(datasetText).toContain(
			'1 training-ready, 1 message-exportable, 1 protocol-ready, and 15 review-candidate goal sample(s) in this collection.'
		);
		expect(datasetText).toContain('Training ready 1');
		expect(datasetText).toContain('Training messages 1');
		expect(datasetText).toContain('Protocol ready 1');
		expect(datasetText).toContain('Needs review 15');
		expect(datasetText).toContain('Candidate 4');
		expect(datasetText).toContain('Silver 10');
		expect(datasetText).toContain('Gold 1');
		expect(datasetText).toContain('Rejected 0');
		expect(datasetText).toContain('Variable error 3');
		expect(datasetText).toContain('Evidence error 2');
		expect(datasetText).toContain('Primary findings 5');
		expect(datasetText).toContain('Review queue 10');
		expect(datasetText).toContain('Single-paper evidence 9');
		expect(datasetText).toContain('Needs cross-paper confirmation 7');
		expect(datasetText).toContain('Table row alignment uncertain 4');

		const collectionJsonUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection training JSON', exact: true })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionJsonUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionJsonUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionJsonUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
		expect(collectionJsonUrl.searchParams.get('format')).toBe('json');

		const collectionJsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection training JSONL' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionJsonlUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionJsonlUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionJsonlUrl.searchParams.get('dataset_use_status')).toBe('training_ready');
		expect(collectionJsonlUrl.searchParams.get('format')).toBe('jsonl');

		const collectionMessagesJsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection training messages JSONL' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionMessagesJsonlUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionMessagesJsonlUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionMessagesJsonlUrl.searchParams.get('dataset_use_status')).toBe(
			'training_ready'
		);
		expect(collectionMessagesJsonlUrl.searchParams.get('format')).toBe('messages_jsonl');

		const collectionReviewUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection review JSON', exact: true })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionReviewUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionReviewUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionReviewUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
		expect(collectionReviewUrl.searchParams.get('format')).toBe('json');

		const collectionReviewJsonlUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection review JSONL template' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionReviewJsonlUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionReviewJsonlUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionReviewJsonlUrl.searchParams.get('dataset_use_status')).toBe(
			'review_candidate'
		);
		expect(collectionReviewJsonlUrl.searchParams.get('format')).toBe('review_jsonl');

		const collectionReviewPacketUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection review packet' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionReviewPacketUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionReviewPacketUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionReviewPacketUrl.searchParams.get('dataset_use_status')).toBe(
			'review_candidate'
		);
		expect(collectionReviewPacketUrl.searchParams.get('format')).toBe('review_packet');

		const collectionDecisionTemplateUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection decision template' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionDecisionTemplateUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionDecisionTemplateUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionDecisionTemplateUrl.searchParams.get('dataset_use_status')).toBe(
			'review_candidate'
		);
		expect(collectionDecisionTemplateUrl.searchParams.get('format')).toBe(
			'decision_template'
		);
	});

	it('dry-runs pasted review decisions before import', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/review-decisions/import') && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						status: 'ok',
						dry_run: true,
						total_rows: 1,
						written_count: 0,
						skipped_count: 0,
						counts: { accept: 1 },
						errors: [],
						warnings: [
							{
								line: 1,
								action: 'accept',
								message: 'Rerun dry-run with fail-on-warnings before import.'
							}
						],
						review_progress: {
							actionable_count: 1,
							skipped_count: 0,
							needs_review_count: 0,
							ready_to_write: true,
							next_steps: []
						},
						affected_goals: []
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.element(browserPage.getByText('Import reviewed decisions')).toBeInTheDocument();

		const row = {
			sample_id: 'sample_1',
			finding_id: 'finding_strength_supported',
			action: 'accept',
			review_status: 'correct',
			issue_type: 'none'
		};
		await browserPage.getByLabelText('Reviewed JSONL rows').fill(JSON.stringify(row));
		await browserPage.getByRole('button', { name: 'Dry run' }).click();

		await expect
			.element(browserPage.getByText('1 actionable row(s), 0 skipped row(s), 0 written.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Import warnings')).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('line 1 · accept · Rerun dry-run with fail-on-warnings before import.')
			)
			.toBeInTheDocument();

		const importCall = fetchMock.mock.calls.find(([input, init]) => {
			const method =
				input instanceof Request
					? input.method
					: typeof (init as RequestInit | undefined)?.method === 'string'
						? (init as RequestInit).method
						: 'GET';
			return (
				requestPath(input as string | URL | Request).endsWith(
					'/research-understanding/review-decisions/import'
				) && method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(importCall).toBeTruthy();
		const [input, init] = importCall!;
		expect(requestPath(input)).toBe(
			'/api/v1/collections/col_123/research-understanding/review-decisions/import'
		);
		expect(JSON.parse(String(init.body))).toEqual({
			rows: [row],
			reviewer: 'materials-expert@example.com',
			dry_run: true,
			fail_on_warnings: true
		});
	});

	it('imports reviewed decisions and refreshes dataset readiness', async () => {
		let datasetRequestCount = 0;
		let feedbackGetCount = 0;
		let curationGetCount = 0;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				datasetRequestCount += 1;
				return Promise.resolve(
					jsonResponse(
						datasetResponse(
							datasetRequestCount === 1
								? {
										trainingReady: 0,
										reviewCandidate: 1,
										rejected: 0,
										itemCount: 1,
										labelCounts: {
											candidate: 0,
											silver: 1,
											gold: 0,
											rejected: 0
										}
									}
								: {
										trainingReady: 1,
										reviewCandidate: 0,
										rejected: 0,
										itemCount: 1,
										labelCounts: {
											candidate: 0,
											silver: 0,
											gold: 1,
											rejected: 0
										}
									}
						)
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				feedbackGetCount += 1;
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				curationGetCount += 1;
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/review-decisions/import') && method === 'POST') {
				return Promise.resolve(
					jsonResponse({
						status: 'ok',
						dry_run: false,
						total_rows: 1,
						written_count: 1,
						skipped_count: 0,
						counts: { accept: 1 },
						errors: [],
						warnings: [],
						review_progress: {
							actionable_count: 1,
							skipped_count: 0,
							needs_review_count: 0,
							ready_to_write: true,
							next_steps: []
						},
						affected_goals: [{ goal_id: 'obj_1', written_count: 1 }]
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain('No training-ready samples');

		const row = {
			sample_id: 'sample_1',
			finding_id: 'finding_strength_supported',
			action: 'accept',
			review_status: 'correct',
			issue_type: 'none'
		};
		await browserPage.getByLabelText('Reviewed JSONL rows').fill(JSON.stringify(row));
		await browserPage.getByRole('button', { name: 'Import decisions' }).click();

		await expect
			.element(browserPage.getByText('1 actionable row(s), 0 skipped row(s), 1 written.'))
			.toBeInTheDocument();
		await expect.poll(() => datasetRequestCount).toBeGreaterThanOrEqual(2);
		await expect.poll(() => feedbackGetCount).toBeGreaterThanOrEqual(2);
		await expect.poll(() => curationGetCount).toBeGreaterThanOrEqual(2);
		await expect.poll(() => currentDatasetRegionText()).toContain('Training ready 1');

		const importCall = fetchMock.mock.calls.find(([input, init]) => {
			const method =
				input instanceof Request
					? input.method
					: typeof (init as RequestInit | undefined)?.method === 'string'
						? (init as RequestInit).method
						: 'GET';
			const body = JSON.parse(String((init as RequestInit | undefined)?.body ?? '{}'));
			return (
				requestPath(input as string | URL | Request).endsWith(
					'/research-understanding/review-decisions/import'
				) &&
				method === 'POST' &&
				body.dry_run === false
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(importCall).toBeTruthy();
		expect(JSON.parse(String(importCall![1].body))).toEqual({
			rows: [row],
			reviewer: 'materials-expert@example.com',
			dry_run: false,
			fail_on_warnings: false
		});
	});

	it('keeps collection review export visible when the current goal has no review candidates', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = init?.method ?? 'GET';
			if (path.endsWith('/research-understanding/dataset/collection') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 15,
							rejected: 0,
							scopeType: 'collection',
							scopeId: 'goal',
							datasetId: 'rud_col_123_collection_goal'
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(datasetResponse({ trainingReady: 1, reviewCandidate: 0, rejected: 0 }))
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		expect(collectionDatasetGetRequestCount()).toBe(0);
		clickDatasetSummary(datasetRegion);
		await expect.poll(() => collectionDatasetGetRequestCount()).toBe(1);
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain('Training ready 1');

		await expect
			.element(browserPage.getByRole('link', { name: 'Review candidates JSON' }))
			.not.toBeInTheDocument();
		const collectionReviewUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Collection review JSON', exact: true })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(collectionReviewUrl.pathname).toBe(
			'/api/v1/collections/col_123/research-understanding/dataset/collection'
		);
		expect(collectionReviewUrl.searchParams.get('scope_type')).toBe('goal');
		expect(collectionReviewUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
		expect(collectionReviewUrl.searchParams.get('format')).toBe('json');
	});

	it('links protocol drafting to Copilot when a goal has training-ready messages', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = init?.method ?? 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							trainingMessages: 1,
							reviewCandidate: 0,
							rejected: 0
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		const draftLink = browserPage.getByRole('link', { name: 'Draft protocol with Copilot' });
		await expect.element(draftLink).toBeInTheDocument();
		const draftUrl = new URL(draftLink.element().getAttribute('href') ?? '', 'http://localhost');
		expect(draftUrl.pathname).toBe('/collections/col_123/assistant');
		expect(draftUrl.searchParams.get('goal_id')).toBe('goal_1');
	});

	it('blocks protocol drafting from the review loop until goal findings are training-ready', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = init?.method ?? 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							trainingMessages: 0,
							reviewCandidate: 3,
							rejected: 0
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('link', { name: 'Draft protocol with Copilot' }))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Protocol needs reviewed findings')).toBeInTheDocument();
	});

	it('flags training-ready goals whose training messages are not exportable yet', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = init?.method ?? 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							trainingMessages: 0,
							reviewCandidate: 0,
							rejected: 0
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		await expect.element(browserPage.getByText('Training messages pending')).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'1 training-ready sample(s) exist, but only 0 training message sample(s) are exportable. Inspect dataset export quality before using this goal downstream.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Draft protocol with Copilot' }))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Protocol needs training messages')).toBeInTheDocument();
	});

	it('describes mixed readiness review items as candidates, not primary findings', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse({ reviewCandidate: 2 })));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain('Training ready 2');
		await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();

		const expertSummary = browserPage.getByLabelText('Expert readiness summary');
		await expect
			.element(expertSummary.getByText('Mixed review and training set'))
			.toBeInTheDocument();
		await expect
			.element(expertSummary.getByText(/review candidate finding\(s\) still need expert curation/))
			.toBeInTheDocument();
		await expect
			.element(
				expertSummary.getByText(
					'2 candidate finding(s) remain in the review queue; do not treat them as usable conclusions until curated.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(expertSummary.getByText(/primary finding\(s\) still need review/))
			.not.toBeInTheDocument();
	});

	it('does not expose training download links when only review candidates exist', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							reviewCandidate: 4,
							rejected: 0,
							itemCount: 4,
							labelCounts: {
								candidate: 0,
								silver: 4,
								gold: 0,
								rejected: 0
							}
						})
					)
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.poll(() => currentDatasetRegionText()).toContain('No training-ready samples');
		await expect
			.element(browserPage.getByRole('link', { name: 'Training JSON', exact: true }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Training JSONL' }))
			.not.toBeInTheDocument();

		const reviewJsonUrl = new URL(
			browserPage
				.getByRole('link', { name: 'Review candidates JSON' })
				.element()
				.getAttribute('href') ?? '',
			'http://localhost'
		);
		expect(reviewJsonUrl.searchParams.get('dataset_use_status')).toBe('review_candidate');
	});

	it('shows a dataset export error when readiness cannot load', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse({ detail: 'dataset unavailable' }, 500, 'Failed'));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect
			.element(browserPage.getByText(/Dataset export is unavailable:/))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Download JSON' }))
			.not.toBeInTheDocument();
	});

	it('opens finding-only detail with evidence and review actions', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: findingOnlyUnderstandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Findings' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: /VED -> density/ }).click();

		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(findingDetail).toBeInTheDocument();
		const densityEvidenceCard = findingDetail
			.getByText('P003 Results')
			.first()
			.element()
			.closest('.research-understanding-workbench__evidence');
		expect(densityEvidenceCard).toBeTruthy();
		expect(densityEvidenceCard?.textContent).toContain(
			"The achieved density measured using the Archimedes ' method was 91.9, 98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively."
		);
		expect(densityEvidenceCard?.textContent).toContain('Selected quote');
		const findingOnlyReviewPriorities = findingDetail.getByLabelText('Review priorities');
		await expect.element(findingOnlyReviewPriorities.getByText('Review priorities')).toBeInTheDocument();
		await expect
			.element(findingOnlyReviewPriorities.getByText('Evidence comes from one paper.'))
			.toBeInTheDocument();
		const findingOnlyEvidenceBasis = findingDetail.getByLabelText('Evidence basis');
		await expect.element(findingOnlyEvidenceBasis.getByText('Evidence basis')).toBeInTheDocument();
		await expect
			.element(findingOnlyEvidenceBasis.getByText('Evidence comes from one paper.'))
			.toBeInTheDocument();
		await expect
			.element(
				findingOnlyEvidenceBasis.getByText(
					'Needs another paper to confirm, contradict, or extend it.'
				)
			)
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Variables')).toBeInTheDocument();
		await expect.element(findingDetail.getByText('VED', { exact: true })).toBeInTheDocument();
		await expect.element(findingDetail.getByText('porosity', { exact: true })).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Outcomes density')).toBeInTheDocument();
		await expect
			.element(
				findingDetail.getByText('stainless steel 316L, VED, density, selective laser melting')
			)
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Direct result evidence')).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Uncategorized evidence')).not.toBeInTheDocument();
		const densitySourceBlock = findingDetail
			.getByText('Parsed source block', { exact: true })
			.element()
			.closest('details');
		expect(densitySourceBlock).toBeTruthy();
		expect(densitySourceBlock?.textContent).toContain(
			'L-VED, M-VED and H-VED samples reached 91.9'
		);
		await expect
			.element(
				findingDetail.getByText('1 secondary evidence record(s) available for audit and curation.')
			)
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText(/This study aims to understand how VED changes/))
			.not.toBeInTheDocument();
		const findingEvidenceHref =
			densityEvidenceCard?.querySelector('a[href]')?.getAttribute('href') ?? '';
		expect(new URL(findingEvidenceHref, 'http://localhost').searchParams.get('quote')).toBe(
			"The achieved density measured using the Archimedes ' method was 91.9, 98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively."
		);
		await expect.element(findingDetail.getByText('Objective scope')).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('VED, selective laser melting'))
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Archimedes method')).toBeInTheDocument();
		await expect.element(findingDetail.getByText(/test specimen/)).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText(/variable/)).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText(/oeu_6b9838393120/)).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText(/FEI-INSPECT 50 SEM/)).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText('microhardness')).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText('ASTM B842')).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText(/fatigue testing/)).not.toBeInTheDocument();
		await expect.element(findingDetail.getByText(/HIP-SLM/)).not.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('5 additional context record(s) available for curation.'))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Expert feedback' }))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Expert curation' }))
			.toBeInTheDocument();
	});

	it('opens primary-finding detail even when the backend omits the combined findings list', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: primaryOnlyFindingProjectionFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Findings' }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: /VED -> density/ }).click();

		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect.element(findingDetail).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Direct result evidence')).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('L-VED, M-VED and H-VED samples reached 91.9'))
			.toBeInTheDocument();
		await expect
			.element(findingDetail.getByRole('button', { name: 'Expert feedback' }))
			.toBeInTheDocument();
	});

	it('deduplicates evidence links that point to the same parsed source target', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: findingWithDuplicateEvidenceTargetsFixture(),
			collectionId: 'col_123'
		});

		const findingsTable = browserPage.getByLabelText('Research findings table');
		const tableSourceLinkCount = findingsTable
			.element()
			.querySelectorAll('a[href*="source_ref=blk_density_results"]').length;
		expect(tableSourceLinkCount).toBe(0);
		await expect
			.element(findingsTable.getByText('1 direct evidence', { exact: true }))
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /VED -> density/ }).click();

		const findingDetail = browserPage.getByLabelText('Finding detail');
		const detailSourceLinkCount = findingDetail
			.element()
			.querySelectorAll('a[href*="source_ref=blk_density_results"]').length;
		expect(detailSourceLinkCount).toBe(1);
		await expect.element(findingDetail.getByText('Direct result evidence')).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Uncategorized evidence')).not.toBeInTheDocument();
		await expect
			.element(findingDetail.getByText(/secondary evidence record/))
			.not.toBeInTheDocument();
	});

	it('filters claims by support status for conflict review', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openConflictedClaimDetail();
		await expect
			.element(claimDetail.getByText('Strength trends conflict across reported heat treatments.'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Conflict evidence')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('P002 Table 4').first()).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Evidence contains conflicting directions.').first())
			.toBeInTheDocument();
	});

	it('submits expert feedback for the selected claim', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByLabelText('Issue type').selectOptions('evidence_not_grounded');
		await claimDetail
			.getByLabelText('Feedback note')
			.fill('Mechanism claim needs direct microstructure evidence.');
		await claimDetail.getByRole('button', { name: 'Save feedback', exact: true }).click();

		await expect.element(claimDetail.getByText(/Feedback saved:/)).toBeInTheDocument();
		const feedbackPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
				(init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(feedbackPostCall).toBeTruthy();
		const [input, init] = feedbackPostCall!;
		expect(requestPath(input)).toBe('/api/v1/collections/col_123/research-understanding/feedback');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_mechanism_limited',
			claim_id: 'claim_mechanism_limited',
			review_status: 'incorrect',
			issue_type: 'evidence_not_grounded',
			note: 'Mechanism claim needs direct microstructure evidence.'
		});
	});

	it('saves feedback and advances to the next review candidate', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'POST') {
				const body = JSON.parse(String(init?.body ?? '{}'));
				return Promise.resolve(
					jsonResponse({
						feedback_id: `ruf_${body.finding_id}`,
						collection_id: 'col_123',
						scope_type: body.scope_type,
						scope_id: body.scope_id,
						finding_id: body.finding_id,
						claim_id: body.claim_id,
						review_status: body.review_status,
						issue_type: body.issue_type,
						note: body.note,
						reviewer: 'materials-expert@example.com',
						created_at: '2026-07-13T09:00:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Review next finding' }).click();
		let claimDetail = browserPage.getByLabelText('Finding detail');
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByLabelText('Issue type').selectOptions('wrong_direction');
		await claimDetail.getByLabelText('Feedback note').fill('Direction is not supported.');
		await claimDetail.getByRole('button', { name: 'Save feedback and next' }).click();

		const feedbackPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
				(init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(feedbackPostCall).toBeTruthy();
		expect(JSON.parse(String(feedbackPostCall![1].body))).toMatchObject({
			finding_id: 'finding_strength_supported',
			review_status: 'incorrect',
			issue_type: 'wrong_direction',
			note: 'Direction is not supported.'
		});
		claimDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(claimDetail.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
	});

	it('submits material-specific feedback issue types', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByLabelText('Issue type').selectOptions('wrong_variable');
		await expect
			.element(
				claimDetail.getByText(
					'Counts as Variable error. Use when the process, input, or material variable is wrong.'
				)
			)
			.toBeInTheDocument();
		await claimDetail
			.getByLabelText('Feedback note')
			.fill('The finding uses the wrong experimental variable.');
		await claimDetail.getByRole('button', { name: 'Save feedback', exact: true }).click();

		await expect.element(claimDetail.getByText(/Feedback saved:/)).toBeInTheDocument();
		const feedbackPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
				(init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(feedbackPostCall).toBeTruthy();
		expect(JSON.parse(String(feedbackPostCall![1].body))).toMatchObject({
			review_status: 'incorrect',
			issue_type: 'wrong_variable',
			note: 'The finding uses the wrong experimental variable.'
		});
	});

	it('accepts a selected finding without opening the full feedback form first', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Accept paper-level', exact: true }).click();

		await expect.element(claimDetail.getByText(/Feedback saved:/)).toBeInTheDocument();
		const feedbackPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
				(init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(feedbackPostCall).toBeTruthy();
		expect(JSON.parse(String(feedbackPostCall![1].body))).toMatchObject({
			finding_id: 'finding_mechanism_limited',
			claim_id: 'claim_mechanism_limited',
			review_status: 'correct',
			issue_type: 'none',
			note: 'Human expert accepted the source-backed paper-level finding.'
		});
	});

	it('opens reject and correct review paths for a selected finding', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Reject' }).click();

		await expect.element(claimDetail.getByLabelText('Review result')).toHaveValue('incorrect');
		await expect.element(claimDetail.getByLabelText('Issue type')).toHaveValue('wrong_variable');

		await claimDetail.getByRole('button', { name: 'Correct' }).click();

		await expect.element(claimDetail.getByLabelText('Curated statement')).toHaveValue(
			'Annealing may reduce cellular substructure.'
		);
	});

	it('requires an authenticated reviewer before expert feedback can be saved', async () => {
		authState.set({ status: 'anonymous', user: null });
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();

		await expect.element(claimDetail.getByText('Sign in required')).toBeInTheDocument();
		await expect
			.element(claimDetail.getByRole('button', { name: 'Save feedback', exact: true }))
			.toBeDisabled();
	});

	it('refreshes dataset readiness after expert feedback is saved', async () => {
		let datasetRequestCount = 0;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				datasetRequestCount += 1;
				return Promise.resolve(
					jsonResponse(
						datasetResponse(
							datasetRequestCount === 1
								? {
										trainingReady: 0,
										reviewCandidate: 4,
										rejected: 0,
										itemCount: 4,
										labelCounts: {
											candidate: 0,
											silver: 4,
											gold: 0,
											rejected: 0
										}
									}
								: {
										trainingReady: 1,
										reviewCandidate: 3,
										rejected: 0,
										itemCount: 4,
										labelCounts: {
											candidate: 0,
											silver: 3,
											gold: 1,
											rejected: 0
										}
									}
						)
					)
				);
			}
			return Promise.resolve(
				jsonResponse({
					feedback_id: 'ruf_saved_1234567890',
					collection_id: 'col_123',
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					review_status: 'correct',
					issue_type: 'none',
					note: null,
					reviewer: 'materials-expert@example.com',
					created_at: '2026-06-18T09:00:00+00:00'
				})
			);
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.poll(() => datasetRegion?.textContent ?? '').toContain(
			'No training-ready samples'
		);

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();
		await claimDetail.getByLabelText('Review result').selectOptions('correct');
		await claimDetail.getByLabelText('Issue type').selectOptions('none');
		await claimDetail.getByRole('button', { name: 'Save feedback', exact: true }).click();

		await expect.element(claimDetail.getByText(/Feedback saved:/)).toBeInTheDocument();
		await expect.poll(() => datasetRequestCount).toBeGreaterThanOrEqual(2);
		await expect.poll(() => currentDatasetRegionText()).toContain('Training ready 1');
		await expect
			.element(browserPage.getByRole('link', { name: 'Training JSON', exact: true }))
			.toBeInTheDocument();
	});

	it('submits feedback against the confirmed goal scope id', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert feedback' }).click();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByRole('button', { name: 'Save feedback', exact: true }).click();

		await expect.element(claimDetail.getByText(/Feedback saved:/)).toBeInTheDocument();
		const feedbackPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
				(init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(feedbackPostCall).toBeTruthy();
		const [, init] = feedbackPostCall!;
		expect(JSON.parse(String(init.body))).toMatchObject({
			scope_type: 'goal',
			scope_id: 'goal_1',
			finding_id: 'finding_mechanism_limited',
			claim_id: 'claim_mechanism_limited',
			review_status: 'incorrect'
		});
	});

	it('requires experts to review candidate findings one at a time', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 0,
							reviewCandidate: 3,
							rejected: 0,
							itemCount: 3,
							labelCounts: {
								candidate: 3,
								silver: 0,
								gold: 0,
								rejected: 0
							}
						})
					)
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Open review queue' }).click();
		await expect
			.element(browserPage.getByRole('button', { name: /Accept visible/ }))
			.not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Review next finding' }).click();
		await expect
			.element(
				browserPage.getByRole('button', {
					name: 'Accept paper-level',
					exact: true
				})
			)
			.toBeInTheDocument();
		const feedbackPayloads = fetchMock.mock.calls
			.filter(([input, init]) => {
				return (
					requestPath(input as string | URL | Request).endsWith('/research-understanding/feedback') &&
					(init as RequestInit | undefined)?.method === 'POST'
				);
			})
			.map(([, init]) => JSON.parse(String((init as RequestInit).body)));
		expect(feedbackPayloads).toHaveLength(0);
	});

	it('submits expert curation for the selected claim classification', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await claimDetail.getByLabelText('Curated type').selectOptions('mechanism');
		await claimDetail.getByLabelText('Curated support status').selectOptions('limited');
		await claimDetail.getByLabelText('Curated evidence grade').selectOptions('partial');
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Annealing may reduce cellular substructure, but the mechanism evidence is limited.');
		await claimDetail.getByLabelText('Curated variables').fill('preheating, annealing');
		await claimDetail.getByLabelText('Curated mechanism').fill('cellular substructure, GND density');
		await claimDetail.getByLabelText('Curated outcomes').fill('ductility');
		await claimDetail.getByLabelText('Curated direction').fill('increase');
		await claimDetail
			.getByLabelText('Curated conditions')
			.fill('LPBF 316L, 150 C build platform preheating, tensile test');
		await claimDetail
			.getByLabelText('Curation note')
			.fill('Keep limited until EBSD evidence is added.');
		await claimDetail.getByRole('button', { name: 'Save curation', exact: true }).click();

		await expect.element(claimDetail.getByText(/Curation saved:/)).toBeInTheDocument();
		const curationPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith(
					'/research-understanding/curations'
				) && (init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(curationPostCall).toBeTruthy();
		const [input, init] = curationPostCall!;
		expect(requestPath(input)).toBe('/api/v1/collections/col_123/research-understanding/curations');
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({
			scope_type: 'objective',
			scope_id: 'obj_1',
			finding_id: 'finding_mechanism_limited',
			claim_id: 'claim_mechanism_limited',
			curated_claim_type: 'mechanism',
			curated_status: 'limited',
			curated_statement:
				'Annealing may reduce cellular substructure, but the mechanism evidence is limited.',
			curated_support_grade: 'partial',
			curated_review_status: 'accepted',
			curated_variables: ['preheating', 'annealing'],
			curated_mediators: ['cellular substructure', 'GND density'],
			curated_outcomes: ['ductility'],
			curated_direction: 'increase',
			curated_scope_summary: 'LPBF 316L, 150 C build platform preheating, tensile test',
			curated_evidence_ref_ids: ['ev_section_3'],
			curated_context_ids: ['ctx_heat_treatment'],
			note: 'Keep limited until EBSD evidence is added.'
		});
	});

	it('saves curation and advances to the next review candidate', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/curations') && method === 'POST') {
				const body = JSON.parse(String(init?.body ?? '{}'));
				return Promise.resolve(
					jsonResponse({
						curation_id: `ruc_${body.finding_id}`,
						collection_id: 'col_123',
						scope_type: body.scope_type,
						scope_id: body.scope_id,
						finding_id: body.finding_id,
						claim_id: body.claim_id,
						curated_claim_type: body.curated_claim_type,
						curated_status: body.curated_status,
						curated_statement: body.curated_statement,
						curated_support_grade: body.curated_support_grade,
						curated_review_status: body.curated_review_status,
						curated_variables: body.curated_variables,
						curated_mediators: body.curated_mediators,
						curated_outcomes: body.curated_outcomes,
						curated_direction: body.curated_direction,
						curated_scope_summary: body.curated_scope_summary,
						curated_evidence_ref_ids: body.curated_evidence_ref_ids,
						curated_context_ids: body.curated_context_ids,
						note: body.note,
						reviewer: 'materials-expert@example.com',
						updated_at: '2026-07-13T09:00:00+00:00'
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Review next finding' }).click();
		let claimDetail = browserPage.getByLabelText('Finding detail');
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Heat treatment changes LPBF 316L tensile response with limited scope.');
		await claimDetail.getByRole('button', { name: 'Save curation and next' }).click();

		const curationPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith(
					'/research-understanding/curations'
				) && (init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(curationPostCall).toBeTruthy();
		expect(JSON.parse(String(curationPostCall![1].body))).toMatchObject({
			finding_id: 'finding_strength_supported',
			claim_id: 'claim_strength_supported',
			curated_statement: 'Heat treatment changes LPBF 316L tensile response with limited scope.'
		});
		claimDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(claimDetail.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
	});

	it('requires an authenticated curator before expert curation can be saved', async () => {
		authState.set({ status: 'anonymous', user: null });
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Annealing may reduce cellular substructure, but current evidence is limited.');

		await expect.element(claimDetail.getByText('Sign in required')).toBeInTheDocument();
		await expect
			.element(claimDetail.getByRole('button', { name: 'Save curation', exact: true }))
			.toBeDisabled();
	});

	it('refreshes dataset readiness after expert curation is saved', async () => {
		let datasetRequestCount = 0;
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				datasetRequestCount += 1;
				return Promise.resolve(
					jsonResponse(
						datasetResponse(
							datasetRequestCount === 1
								? {
										trainingReady: 0,
										reviewCandidate: 4,
										rejected: 0,
										itemCount: 4,
										labelCounts: {
											candidate: 0,
											silver: 4,
											gold: 0,
											rejected: 0
										}
									}
								: {
										trainingReady: 1,
										reviewCandidate: 3,
										rejected: 0,
										itemCount: 4,
										labelCounts: {
											candidate: 0,
											silver: 3,
											gold: 1,
											rejected: 0
										}
									}
						)
					)
				);
			}
			return Promise.resolve(
				jsonResponse({
					curation_id: 'ruc_saved_1234567890',
					collection_id: 'col_123',
					scope_type: 'objective',
					scope_id: 'obj_1',
					finding_id: 'finding_mechanism_limited',
					claim_id: 'claim_mechanism_limited',
					curated_claim_type: 'mechanism',
					curated_status: 'limited',
					curated_statement:
						'Annealing may reduce cellular substructure, but the mechanism evidence is limited.',
					curated_support_grade: 'weak',
					curated_review_status: 'needs_review',
					curated_variables: ['annealing'],
					curated_mediators: ['cellular substructure'],
					curated_outcomes: ['yield strength'],
					curated_direction: 'explains',
					curated_scope_summary: '316L stainless steel, LPBF, annealing, tensile test',
					curated_evidence_ref_ids: ['ev_section_3'],
					curated_context_ids: ['ctx_heat_treatment'],
					note: 'Keep limited until EBSD evidence is added.',
					reviewer: 'materials-expert@example.com',
					updated_at: '2026-06-18T09:00:00+00:00'
				})
			);
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const datasetSummary = datasetSummaryLocator();
		await expect.element(datasetSummary).toBeInTheDocument();
		const datasetRegion = datasetSummary.element().closest('details');
		expect(datasetRegion).toBeTruthy();
		datasetRegion?.setAttribute('open', '');
		await expect.poll(() => currentDatasetRegionText()).toContain('No training-ready samples');

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Annealing may reduce cellular substructure, but the mechanism evidence is limited.');
		await claimDetail.getByRole('button', { name: 'Save curation', exact: true }).click();

		await expect.element(claimDetail.getByText(/Curation saved:/)).toBeInTheDocument();
		await expect.poll(() => datasetRequestCount).toBeGreaterThanOrEqual(2);
		await expect.poll(() => currentDatasetRegionText()).toContain('Training ready 1');
		await expect
			.element(browserPage.getByRole('link', { name: 'Training JSON', exact: true }))
			.toBeInTheDocument();
	});

	it('submits expert curation with corrected evidence and context bindings', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await expect.element(claimDetail.getByText('Curated evidence', { exact: true })).toBeInTheDocument();
		await expect.element(claimDetail.getByText('Curated context', { exact: true })).toBeInTheDocument();
		await claimDetail.getByLabelText(/P001 Section 3\.2/).click();
		await claimDetail.getByLabelText(/Heat treatment scope/).click();
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Annealing may reduce cellular substructure, but current evidence should be removed.');
		await claimDetail.getByRole('button', { name: 'Save curation', exact: true }).click();

		await expect.element(claimDetail.getByText(/Curation saved:/)).toBeInTheDocument();
		const curationPostCall = fetchMock.mock.calls.find(([input, init]) => {
			return (
				requestPath(input as string | URL | Request).endsWith(
					'/research-understanding/curations'
				) && (init as RequestInit | undefined)?.method === 'POST'
			);
		}) as [string | URL | Request, RequestInit] | undefined;
		expect(curationPostCall).toBeTruthy();
		const [, init] = curationPostCall!;
		expect(JSON.parse(String(init.body))).toMatchObject({
			curated_evidence_ref_ids: [],
			curated_context_ids: []
		});
	});

	it('loads existing expert curation into the selected claim form', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			if (path.endsWith('/research-understanding/curations') && init?.method !== 'POST') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								curation_id: 'ruc_existing',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								claim_id: 'claim_mechanism_limited',
								curated_claim_type: 'limitation',
								curated_status: 'limited',
								curated_statement: 'Existing expert curation: mechanism evidence remains limited.',
								curated_evidence_ref_ids: ['ev_section_3'],
								curated_context_ids: ['ctx_heat_treatment'],
								note: 'Existing expert note.',
								reviewer: 'materials-expert@example.com',
								updated_at: '2026-06-18T09:00:00+00:00'
							}
						]
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail(/Existing expert curation/);

		await expect.element(claimDetail.getByLabelText('Curated statement')).not.toBeInTheDocument();
		await claimDetail.getByRole('button', { name: 'Expert curation' }).click();
		await expect
			.element(claimDetail.getByLabelText('Curated statement'))
			.toHaveValue('Existing expert curation: mechanism evidence remains limited.');
		await expect.element(claimDetail.getByLabelText('Curated type')).toHaveValue('limitation');
		await expect
			.element(claimDetail.getByLabelText('Curation note'))
			.toHaveValue('Existing expert note.');
		await expect.element(claimDetail.getByText('Applied expert curation')).toBeInTheDocument();
		await expect
			.element(
				claimDetail.getByText('Existing expert curation: mechanism evidence remains limited.')
					.first()
			)
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Original classification')).toBeInTheDocument();
	});

	it('uses existing expert curation as the main finding display', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								curation_id: 'ruc_existing',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								finding_id: 'finding_mechanism_limited',
								claim_id: 'claim_mechanism_limited',
								curated_claim_type: 'mechanism',
								curated_status: 'limited',
								curated_statement:
									'Preheating at 150 C improves LPBF 316L ductility through GND density changes.',
								curated_support_grade: 'partial',
								curated_review_status: 'accepted',
								curated_variables: ['preheating'],
								curated_mediators: ['GND density'],
								curated_outcomes: ['ductility'],
								curated_direction: 'increase',
								curated_scope_summary: 'LPBF 316L, 150 C build platform preheating',
								curated_evidence_ref_ids: ['ev_section_3'],
								curated_context_ids: ['ctx_heat_treatment'],
								note: 'Corrected by domain expert.',
								reviewer: 'materials-expert@example.com',
								updated_at: '2026-06-18T09:00:00+00:00'
							}
						]
					})
				);
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/dataset/collection') && method === 'GET') {
				return Promise.resolve(
					jsonResponse(
						datasetResponse({
							trainingReady: 1,
							reviewCandidate: 15,
							rejected: 0,
							scopeType: 'collection',
							scopeId: 'goal',
							datasetId: 'rud_col_123_collection_goal'
						})
					)
				);
			}
			if (path.endsWith('/research-understanding/dataset') && method === 'GET') {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();
		await expect
			.element(
				browserPage.getByRole('button', {
					name: /Preheating at 150 C improves LPBF 316L ductility/
				})
			)
			.toBeInTheDocument();
		const findingsTable = browserPage.getByLabelText('Research findings table');
		await expect.element(findingsTable.getByText('preheating', { exact: true })).toBeInTheDocument();
		await expect.element(findingsTable.getByText('GND density', { exact: true })).toBeInTheDocument();
		await expect.element(findingsTable.getByText('ductility', { exact: true })).toBeInTheDocument();
		await expect.element(findingsTable.getByText('LPBF 316L, 150 C build platform preheating')).toBeInTheDocument();
		await expect.element(findingsTable.getByText('Partial', { exact: true })).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Partial 1' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Weak 1' })).not.toBeInTheDocument();

		await browserPage
			.getByRole('button', { name: /Preheating at 150 C improves LPBF 316L ductility/ })
			.click();
		const findingDetail = browserPage.getByLabelText('Finding detail');
		await expect
			.element(
				findingDetail.getByText(
					'Preheating at 150 C improves LPBF 316L ductility through GND density changes.'
				).first()
			)
			.toBeInTheDocument();
		await expect.element(findingDetail.getByText('Variables')).toBeInTheDocument();
		await expect.element(findingDetail.getByText('preheating', { exact: true })).toBeInTheDocument();
		await expect.element(findingDetail.getByText('GND density', { exact: true })).toBeInTheDocument();
		await expect.element(findingDetail.getByText('Outcomes ductility')).toBeInTheDocument();
		await expect
			.element(findingDetail.getByText('LPBF 316L, 150 C build platform preheating'))
			.toBeInTheDocument();
	});

	it('loads existing expert feedback into the selected claim review history', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			if (path.endsWith('/research-understanding/curations') && method === 'GET') {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback') && method === 'GET') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						items: [
							{
								feedback_id: 'ruf_existing',
								collection_id: 'col_123',
								scope_type: 'objective',
								scope_id: 'obj_1',
								claim_id: 'claim_mechanism_limited',
								review_status: 'incorrect',
								issue_type: 'evidence_not_grounded',
								note: 'Existing feedback: mechanism claim needs direct evidence.',
								reviewer: 'materials-expert@example.com',
								created_at: '2026-06-18T09:00:00+00:00'
							}
						]
					})
				);
			}
			return Promise.resolve(jsonResponse({}));
		});

		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();

		await expect.element(claimDetail.getByText('Feedback history')).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Existing feedback: mechanism claim needs direct evidence.'))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Incorrect · Evidence does not support it'))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('materials-expert@example.com · 2026-06-18T09:00:00+00:00'))
			.toBeInTheDocument();
	});

	it('filters the claim list to the review queue', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Repair candidates 2' }).click();

		await expect.element(browserPage.getByText('2 of 2')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('Strength trends conflict across reported heat treatments.').first()
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.not.toBeInTheDocument();
	});

	it('keeps primary findings that need review out of the candidate queue filter', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: findingWithPrimaryReviewFixture(),
			collectionId: 'col_123'
		});

		const summary = browserPage.getByLabelText('Research understanding summary');
		await expect.element(summary.getByText('Candidate queue')).toBeInTheDocument();
		await expect.element(summary.getByText('0')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Repair candidates 0' }))
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Repair candidates 0' }).click();

		await expect
			.element(browserPage.getByText('No findings match the current filters.'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByText(
						"The achieved density measured using the Archimedes ' method was 91.9, 98.9 and 99.6 % for L-VED, M-VED and H-VED, respectively."
					)
					.first()
			)
			.not.toBeInTheDocument();
	});

	it('defaults to the review queue when a projection has no primary findings', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: reviewOnlyFindingProjectionFixture(),
			collectionId: 'col_123'
		});

		const summary = browserPage.getByLabelText('Research understanding summary');
		await expect.element(summary.getByText('Primary findings', { exact: true })).toBeInTheDocument();
		await expect
			.element(summary.getByText('0 / 6 papers covered by primary findings'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Repair candidates 1' }))
			.toHaveAttribute('aria-pressed', 'true');
		await expect.element(browserPage.getByText('1 of 1')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Model prediction or validation evidence needs expert review.'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByText(
						'Scan strategy rotation angles and build orientations can be used to predict crystallographic texture changes and Bishop-Hill yield strength in LPBF 316L.'
					)
					.first()
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Reject' }))
			.toBeInTheDocument();
	});
});
