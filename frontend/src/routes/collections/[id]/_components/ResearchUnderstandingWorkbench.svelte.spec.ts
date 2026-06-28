import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import ResearchUnderstandingWorkbench from './ResearchUnderstandingWorkbench.svelte';
import type { ResearchUnderstanding } from '../../../_shared/researchView';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

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
				review_queue_count: 2
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
					quote: null,
					source_text: null,
					value_summary: 'P001 Table 2',
					traceability_status: 'traceable',
					confidence: 0.9,
					href: null
				},
				{
					evidence_ref_id: 'ev_section_3',
					document_id: 'doc_1',
					title: 'P001 Section 3.2 / p. 7',
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
					traceability_status: 'traceable',
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
					traceability_status: 'traceable',
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

async function openMechanismClaimDetail() {
	await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();
	await browserPage
		.getByRole('button', { name: /Annealing may reduce cellular substructure\./ })
		.click();
	return browserPage.getByLabelText('Claim detail');
}

async function openConflictedClaimDetail() {
	await browserPage.getByRole('button', { name: 'Conflicted 1' }).click();
	await browserPage
		.getByRole('button', { name: /Strength trends conflict across reported heat treatments\./ })
		.click();
	return browserPage.getByLabelText('Claim detail');
}

describe('ResearchUnderstandingWorkbench', () => {
	beforeEach(() => {
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
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(
					jsonResponse({
						curation_id: 'ruc_saved_1234567890',
						collection_id: 'col_123',
						scope_type: 'objective',
						scope_id: 'obj_1',
						claim_id: 'claim_mechanism_limited',
						curated_claim_type: 'mechanism',
						curated_status: 'limited',
						curated_statement:
							'Annealing may reduce cellular substructure, but the mechanism evidence is limited.',
						curated_evidence_ref_ids: ['ev_section_3'],
						curated_context_ids: ['ctx_heat_treatment'],
						note: 'Keep limited until EBSD evidence is added.',
						reviewer: 'materials-expert',
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
					claim_id: 'claim_mechanism_limited',
					review_status: 'incorrect',
					issue_type: 'evidence_not_grounded',
					note: 'Mechanism claim needs direct microstructure evidence.',
					reviewer: 'materials-expert',
					created_at: '2026-06-18T09:00:00+00:00'
				})
			);
		});
	});

	it('filters claim rows by type and opens the selected claim detail', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('3 of 3')).toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Claim detail')).not.toBeInTheDocument();

		const claimDetail = await openMechanismClaimDetail();
		await expect.element(claimDetail).toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: 'Back to claims' })).toBeInTheDocument();
		await expect.element(claimDetail.getByText('P001 Section 3.2').first()).toBeInTheDocument();
		await expect
			.element(
				claimDetail.getByText(
					'Annealing reduced cellular substructure after LPBF processing. This paragraph is the original parsed source block used as evidence.'
				)
			)
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('paragraph · p. 7 · Results / Microstructure · traceable')).toBeInTheDocument();
		const evidenceLink = claimDetail.getByRole('link', { name: /P001 Section 3.2/ }).element();
		expect(evidenceLink.getAttribute('href')).toContain('view=parsed-paper');
		await expect
			.element(claimDetail.getByText('LPBF, annealing'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('needs expert review')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('Annealing -> yield strength')).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Annealing explains cellular substructure changes in LPBF 316L.'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Context: 316L stainless steel, LPBF')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('1 low-level relation(s) are hidden until normalized.')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('sample_number: 2')).not.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Back to claims' }).click();
		await expect.element(browserPage.getByText('1 of 3')).toBeInTheDocument();
		await expect.element(browserPage.getByLabelText('Claim detail')).not.toBeInTheDocument();
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
		await expect.element(claimDetail.getByText('P002 Table 4').first()).toBeInTheDocument();
		await expect.element(claimDetail.getByText('conflicting direction')).toBeInTheDocument();
	});

	it('submits expert feedback for the selected claim', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByLabelText('Issue type').selectOptions('evidence_not_grounded');
		await claimDetail
			.getByLabelText('Feedback note')
			.fill('Mechanism claim needs direct microstructure evidence.');
		await claimDetail.getByLabelText('Reviewer').fill('materials-expert');
		await claimDetail.getByRole('button', { name: 'Save feedback' }).click();

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
			claim_id: 'claim_mechanism_limited',
			review_status: 'incorrect',
			issue_type: 'evidence_not_grounded',
			note: 'Mechanism claim needs direct microstructure evidence.',
			reviewer: 'materials-expert'
		});
	});

	it('submits feedback against the confirmed goal scope id', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: goalUnderstandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByLabelText('Review result').selectOptions('incorrect');
		await claimDetail.getByRole('button', { name: 'Save feedback' }).click();

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
			claim_id: 'claim_mechanism_limited',
			review_status: 'incorrect'
		});
	});

	it('submits expert curation for the selected claim classification', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		const claimDetail = await openMechanismClaimDetail();
		await claimDetail.getByLabelText('Curated type').selectOptions('mechanism');
		await claimDetail.getByLabelText('Curated support status').selectOptions('limited');
		await claimDetail
			.getByLabelText('Curated statement')
			.fill('Annealing may reduce cellular substructure, but the mechanism evidence is limited.');
		await claimDetail
			.getByLabelText('Curation note')
			.fill('Keep limited until EBSD evidence is added.');
		await claimDetail.getByLabelText('Curator').fill('materials-expert');
		await claimDetail.getByRole('button', { name: 'Save curation' }).click();

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
			claim_id: 'claim_mechanism_limited',
			curated_claim_type: 'mechanism',
			curated_status: 'limited',
			curated_statement:
				'Annealing may reduce cellular substructure, but the mechanism evidence is limited.',
			curated_evidence_ref_ids: ['ev_section_3'],
			curated_context_ids: ['ctx_heat_treatment'],
			note: 'Keep limited until EBSD evidence is added.',
			reviewer: 'materials-expert'
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
								reviewer: 'materials-expert',
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

		const claimDetail = await openMechanismClaimDetail();

		await expect
			.element(claimDetail.getByLabelText('Curated statement'))
			.toHaveValue('Existing expert curation: mechanism evidence remains limited.');
		await expect.element(claimDetail.getByLabelText('Curated type')).toHaveValue('limitation');
		await expect
			.element(claimDetail.getByLabelText('Curation note'))
			.toHaveValue('Existing expert note.');
		await expect
			.element(claimDetail.getByText('Applied expert curation'))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Existing expert curation: mechanism evidence remains limited.'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('Original classification')).toBeInTheDocument();
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
								reviewer: 'materials-expert',
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
		await expect.element(claimDetail.getByText('Incorrect · Evidence does not support it')).toBeInTheDocument();
		await expect.element(claimDetail.getByText('materials-expert · 2026-06-18T09:00:00+00:00')).toBeInTheDocument();
	});

	it('filters the claim list to the review queue', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Needs review 2' }).click();

		await expect.element(browserPage.getByText('2 of 3')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Strength trends conflict across reported heat treatments.').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.not.toBeInTheDocument();
	});
});
