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
				status: 'limited',
				confidence: 0.64,
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

	it('filters claims by type and opens the selected claim detail', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('3 of 3')).toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();

		await expect.element(browserPage.getByText('1 of 3')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Annealing may reduce cellular substructure.').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes LPBF 316L tensile response.').first())
			.not.toBeInTheDocument();
		const claimDetail = browserPage.getByLabelText('Claim detail');
		await expect.element(claimDetail.getByText('P001 Section 3.2').first()).toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('Annealing reduced cellular substructure.'))
			.toBeInTheDocument();
		await expect
			.element(claimDetail.getByText('process: LPBF; treatment: annealing'))
			.toBeInTheDocument();
		await expect.element(claimDetail.getByText('needs expert review')).toBeInTheDocument();
		await expect.element(browserPage.getByText('cellular substructure change')).toBeInTheDocument();
	});

	it('filters claims by support status for conflict review', async () => {
		render(ResearchUnderstandingWorkbench, {
			understanding: understandingFixture(),
			collectionId: 'col_123'
		});

		await browserPage.getByRole('button', { name: 'Conflicted 1' }).click();

		await expect.element(browserPage.getByText('1 of 3')).toBeInTheDocument();
		const claimDetail = browserPage.getByLabelText('Claim detail');
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

		await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();
		const claimDetail = browserPage.getByLabelText('Claim detail');
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

		await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();
		const claimDetail = browserPage.getByLabelText('Claim detail');
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

		await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();
		const claimDetail = browserPage.getByLabelText('Claim detail');
		await claimDetail.getByLabelText('Curated type').selectOptions('mechanism');
		await claimDetail.getByLabelText('Curated support status').selectOptions('limited');
		await claimDetail
			.getByLabelText('Curated claim')
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

		await browserPage.getByRole('button', { name: 'Mechanism 1' }).click();
		const claimDetail = browserPage.getByLabelText('Claim detail');

		await expect
			.element(claimDetail.getByLabelText('Curated claim'))
			.toHaveValue('Existing expert curation: mechanism evidence remains limited.');
		await expect.element(claimDetail.getByLabelText('Curated type')).toHaveValue('limitation');
		await expect
			.element(claimDetail.getByLabelText('Curation note'))
			.toHaveValue('Existing expert note.');
	});
});
