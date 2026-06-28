import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type GoalPageState = {
	params: {
		id: string;
		goal_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: GoalPageState) => void>();
	let current: GoalPageState = {
		params: { id: 'col_123', goal_id: 'goal_1' },
		url: new URL('http://localhost/collections/col_123/goals/goal_1')
	};

	return {
		pageStore: {
			subscribe(run: (value: GoalPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: GoalPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

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

describe('collections/[id]/goals/[goal_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', goal_id: 'goal_1' },
			url: new URL('http://localhost/collections/col_123/goals/goal_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation((input: string | URL | Request) => {
			const path = requestPath(input);
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path === '/api/v1/collections/col_123/goals/goal_1/analysis') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal: {
							goal_id: 'goal_1',
							collection_id: 'col_123',
							question: 'How does heat treatment affect strength?',
							source_type: 'objective_candidate',
							material_hints: ['316L stainless steel'],
							process_hints: ['heat treatment'],
							property_hints: ['yield strength'],
							source_objective_id: 'obj_1',
							status: 'ready',
							analysis_error: null,
							analysis_progress: null,
							created_at: null,
							updated_at: null
						},
						understanding: {
							schema_version: 'research_understanding.v1',
							state: 'ready',
							scope: {
								scope_type: 'goal',
								collection_id: 'col_123',
								goal_id: 'goal_1',
								material_id: null,
								objective_id: null,
								document_id: null,
								title: 'How does heat treatment affect strength?'
							},
							claims: [
								{
									claim_id: 'claim_1',
									claim_type: 'finding',
									statement: 'Heat treatment changes tensile strength.',
									status: 'supported',
									confidence: 0.84,
									strength: 'moderate',
									evidence_ref_ids: [],
									context_ids: [],
									source_object_ids: [],
									warnings: []
								}
							],
							relations: [],
							evidence_refs: [],
							contexts: [],
							warnings: [],
							summary: {
								claim_count: 1,
								relation_count: 0,
								evidence_ref_count: 0,
								context_count: 0
							},
							presentation: {
								summary: {
									title: 'How does heat treatment affect strength?',
									material_scope: ['316L stainless steel'],
									variable_axes: ['heat treatment'],
									property_scope: ['tensile strength'],
									claim_count: 1,
									relation_count: 0,
									evidence_count: 0,
									context_count: 0,
									review_queue_count: 0
								},
								effects: [
									{
										effect_id: 'effect_claim_1',
										claim_id: 'claim_1',
										title: 'heat treatment -> tensile strength',
										statement: 'Heat treatment changes tensile strength.',
										claim_type: 'finding',
										support_status: 'supported',
										confidence: 0.84,
										effect_direction: '',
										variable_axis: 'heat treatment',
										target_property: 'tensile strength',
										paper_count: 0,
										evidence_count: 0,
										context_summary: '316L stainless steel, heat treatment',
										evidence_ref_ids: [],
										context_ids: [],
										relation_ids: [],
										needs_review: false,
										warnings: []
									}
								],
								evidence_items: [],
								context_summaries: []
							}
						},
						pipeline_nodes: {},
						errors: [],
						warnings: []
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500));
		});
	});

	it('loads confirmed goal analysis into the research understanding workspace', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'How does heat treatment affect strength?' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes tensile strength.').first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('obj_1')).not.toBeInTheDocument();
	});

	it('shows running goal analysis progress with the active paper', async () => {
		fetchMock.mockImplementation((input: string | URL | Request) => {
			const path = requestPath(input);
			if (path === '/api/v1/collections/col_123/goals/goal_1/analysis') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal: {
							goal_id: 'goal_1',
							collection_id: 'col_123',
							question: 'How does heat treatment affect strength?',
							source_type: 'objective_candidate',
							material_hints: ['316L stainless steel'],
							process_hints: ['heat treatment'],
							property_hints: ['yield strength'],
							source_objective_id: 'obj_1',
							status: 'running',
							analysis_error: null,
							analysis_progress: {
								phase: 'objective_evidence_routing_started',
								current: 3,
								total: 6,
								unit: 'frames',
								message: 'Routing source blocks and tables.',
								active_document_id: 'doc_1',
								active_document_title: 'Heat treatment study',
								active_source_filename: 'heat-treatment.pdf',
								active_objective_id: 'obj_1'
							},
							created_at: null,
							updated_at: null
						},
						understanding: null,
						pipeline_nodes: {},
						errors: [],
						warnings: []
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500));
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Analyzing this research goal' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Heat treatment study')).toBeInTheDocument();
		await expect.element(browserPage.getByText('3/6 frames')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Analyzing...' }))
			.toBeDisabled();
	});
});
