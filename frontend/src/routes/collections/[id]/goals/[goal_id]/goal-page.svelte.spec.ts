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

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	return input instanceof Request ? input.method : (init?.method ?? 'GET');
}

describe('collections/[id]/goals/[goal_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', goal_id: 'goal_1' },
			url: new URL('http://localhost/collections/col_123/goals/goal_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (
				path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans' &&
				method === 'GET'
			) {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal_id: 'goal_1',
						items: [
							{
								plan_id: 'exp_1',
								collection_id: 'col_123',
								goal_id: 'goal_1',
								title: 'Preheating validation matrix',
								content: 'Compare 25 C and 150 C preheated builds.',
								status: 'draft',
								source_message_id: 'msg_1',
								source_links: [
									{
										kind: 'evidence',
										label: 'Source 1',
										href: '/collections/col_123/documents/paper-a?evidence_id=ev_1'
									}
								],
								metadata: {},
								created_by: 'expert-a',
								created_at: '2026-07-13T00:00:00+00:00',
								updated_at: '2026-07-13T00:00:00+00:00'
							}
						]
					})
				);
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
								findings: [
									{
										finding_id: 'finding_claim_1',
										claim_id: 'claim_1',
										title: 'heat treatment -> tensile strength',
										statement: 'Heat treatment changes tensile strength.',
										variables: ['heat treatment'],
										mediators: [],
										outcomes: ['tensile strength'],
										direction: '',
										scope_summary: '316L stainless steel, heat treatment',
										support_grade: 'weak',
										review_status: 'pending_review',
										confidence: 0.84,
										paper_count: 0,
										evidence_count: 0,
										evidence_ref_ids: [],
										context_ids: [],
										relation_ids: [],
										evidence_bundle: {
											direct_result: [],
											mechanism: [],
											condition_context: [],
											background: [],
											conflict: [],
											noise: [],
											uncategorized: []
										},
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
			.element(browserPage.getByRole('link', { name: 'Ask Copilot' }))
			.toHaveAttribute('href', '/collections/col_123/assistant?goal_id=goal_1');
		await expect
			.element(browserPage.getByRole('heading', { name: 'How does heat treatment affect strength?' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('heading', { name: 'Findings' })).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment changes tensile strength.').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Experiment plans' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Preheating validation matrix').first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('obj_1')).not.toBeInTheDocument();
	});

	it('edits saved experiment plan drafts on the goal page', async () => {
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (
				path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans' &&
				method === 'GET'
			) {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal_id: 'goal_1',
						items: [
							{
								plan_id: 'exp_1',
								collection_id: 'col_123',
								goal_id: 'goal_1',
								title: 'Preheating validation matrix',
								content: 'Compare 25 C and 150 C preheated builds.',
								status: 'draft',
								source_message_id: 'msg_1',
								source_links: [],
								metadata: {},
								created_by: 'expert-a',
								created_at: '2026-07-13T00:00:00+00:00',
								updated_at: '2026-07-13T00:00:00+00:00'
							}
						]
					})
				);
			}
			if (
				path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans/exp_1' &&
				method === 'PATCH'
			) {
				return Promise.resolve(
					jsonResponse({
						plan_id: 'exp_1',
						collection_id: 'col_123',
						goal_id: 'goal_1',
						title: 'Edited validation matrix',
						content: 'Add a no-preheat control.',
						status: 'ready_for_review',
						source_message_id: 'msg_1',
						source_links: [],
						metadata: {},
						created_by: 'expert-a',
						created_at: '2026-07-13T00:00:00+00:00',
						updated_at: '2026-07-13T01:00:00+00:00'
					})
				);
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
							material_hints: [],
							process_hints: [],
							property_hints: [],
							source_objective_id: null,
							status: 'ready',
							analysis_error: null,
							analysis_progress: null,
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

		const titleInput = browserPage.getByLabelText('Title');
		await expect.element(titleInput).toHaveValue('Preheating validation matrix');
		await expect.element(titleInput).toHaveAttribute('name', 'experiment_plan_title');
		await expect
			.element(browserPage.getByLabelText('Plan content'))
			.toHaveAttribute('name', 'experiment_plan_content');
		await expect
			.element(browserPage.getByLabelText('Status'))
			.toHaveAttribute('name', 'experiment_plan_status');
		await titleInput.fill('Edited validation matrix');
		await browserPage.getByLabelText('Plan content').fill('Add a no-preheat control.');
		await browserPage.getByLabelText('Status').selectOptions('ready_for_review');
		await browserPage.getByRole('button', { name: 'Save edits' }).click();

		const patchCall = fetchMock.mock.calls.find(
			([input, init]) =>
				requestPath(input) ===
					'/api/v1/collections/col_123/goals/goal_1/experiment-plans/exp_1' &&
				requestMethod(input, init) === 'PATCH'
		);
		expect(JSON.parse(patchCall?.[1]?.body as string)).toMatchObject({
			title: 'Edited validation matrix',
			content: 'Add a no-preheat control.',
			status: 'ready_for_review'
		});
		await expect.element(browserPage.getByText('Edited validation matrix').first()).toBeInTheDocument();
	});

	it('opens the experiment plan requested by the copilot deep link', async () => {
		setPage({
			params: { id: 'col_123', goal_id: 'goal_1' },
			url: new URL('http://localhost/collections/col_123/goals/goal_1?plan_id=exp_2#experiment-plans-title')
		});
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path.endsWith('/research-understanding/curations')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (path.endsWith('/research-understanding/feedback')) {
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: [] }));
			}
			if (
				path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans' &&
				method === 'GET'
			) {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal_id: 'goal_1',
						items: [
							{
								plan_id: 'exp_1',
								collection_id: 'col_123',
								goal_id: 'goal_1',
								title: 'Older validation matrix',
								content: 'Earlier draft.',
								status: 'draft',
								source_message_id: 'msg_1',
								source_links: [],
								metadata: {},
								created_by: 'expert-a',
								created_at: '2026-07-13T00:00:00+00:00',
								updated_at: '2026-07-13T00:00:00+00:00'
							},
							{
								plan_id: 'exp_2',
								collection_id: 'col_123',
								goal_id: 'goal_1',
								title: 'Copied copilot validation plan',
								content: 'Use accepted VED evidence to validate fatigue response.',
								status: 'draft',
								source_message_id: 'msg_2',
								source_links: [
									{
										kind: 'evidence',
										label: 'Source 1',
										href: '/collections/col_123/documents/paper-a?evidence_id=ev_1'
									}
								],
								metadata: {
									source: 'goal_copilot',
									source_session_id: 'session_2',
									source_mode: 'collection_grounded',
									used_evidence_ids: ['ev_1'],
									review_gate: 'training_ready_findings'
								},
								created_by: 'expert-a',
								created_at: '2026-07-13T00:01:00+00:00',
								updated_at: '2026-07-13T00:01:00+00:00'
							}
						]
					})
				);
			}
			if (path === '/api/v1/collections/col_123/goals/goal_1/analysis') {
				return Promise.resolve(
					jsonResponse({
						collection_id: 'col_123',
						goal: {
							goal_id: 'goal_1',
							collection_id: 'col_123',
							question: 'How does VED affect fatigue?',
							source_type: 'objective_candidate',
							material_hints: [],
							process_hints: [],
							property_hints: [],
							source_objective_id: null,
							status: 'ready',
							analysis_error: null,
							analysis_progress: null,
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

		await expect.element(browserPage.getByLabelText('Title')).toHaveValue('Copied copilot validation plan');
		await expect
			.element(browserPage.getByLabelText('Plan content'))
			.toHaveValue('Use accepted VED evidence to validate fatigue response.');
		await expect
			.element(browserPage.getByRole('link', { name: 'Source 1' }))
			.toHaveAttribute('href', '/collections/col_123/documents/paper-a?evidence_id=ev_1');
		await expect
			.element(browserPage.getByText('Generated from reviewed Goal Copilot evidence'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('training_ready_findings')).toBeInTheDocument();
		await expect.element(browserPage.getByText('1 evidence link(s)')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Session session_2')).toBeInTheDocument();
	});

	it('shows analysis errors instead of an empty research understanding workspace', async () => {
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
							material_hints: [],
							process_hints: [],
							property_hints: [],
							source_objective_id: null,
							status: 'failed',
							analysis_error: 'finalize_goal: goal analysis produced no research findings',
							analysis_progress: {
								phase: 'failed',
								unit: 'steps',
								message: 'Goal analysis failed.'
							},
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
							claims: [],
							relations: [],
							evidence_refs: [],
							contexts: [],
							warnings: [],
							summary: {
								claim_count: 0,
								relation_count: 0,
								evidence_ref_count: 0,
								context_count: 0
							},
							presentation: {
								summary: {
									title: 'How does heat treatment affect strength?',
									material_scope: [],
									variable_axes: [],
									property_scope: [],
									claim_count: 0,
									relation_count: 0,
									evidence_count: 0,
									context_count: 0,
									review_queue_count: 0,
									primary_finding_count: 0,
									review_queue_finding_count: 0,
									collection_document_count: 0
								},
								effects: [],
								findings: [],
								primary_findings: [],
								review_queue_findings: [],
								evidence_items: [],
								context_summaries: []
							}
						},
						pipeline_nodes: {
							finalize_goal: {
								status: 'failed',
								errors: ['goal analysis produced no research findings']
							}
						},
						errors: ['finalize_goal: goal analysis produced no research findings'],
						warnings: []
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500));
		});

		render(Page);

		await expect
			.element(browserPage.getByText('finalize_goal: goal analysis produced no research findings'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('heading', { name: 'Findings' })).not.toBeInTheDocument();
	});

	it('shows review-only understanding when goal analysis has no primary findings', async () => {
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
							question: 'How does scan strategy affect yield strength?',
							source_type: 'objective_candidate',
							material_hints: ['316L stainless steel'],
							process_hints: ['scan strategy'],
							property_hints: ['yield strength'],
							source_objective_id: null,
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
								title: 'How does scan strategy affect yield strength?'
							},
							claims: [],
							relations: [],
							evidence_refs: [],
							contexts: [],
							warnings: [],
							summary: {
								claim_count: 0,
								relation_count: 0,
								evidence_ref_count: 0,
								context_count: 0
							},
							presentation: {
								summary: {
									title: 'How does scan strategy affect yield strength?',
									material_scope: ['316L stainless steel'],
									variable_axes: ['scan strategy'],
									property_scope: ['yield strength'],
									claim_count: 0,
									relation_count: 0,
									evidence_count: 1,
									context_count: 0,
									review_queue_count: 1,
									primary_finding_count: 0,
									review_queue_finding_count: 1,
									collection_document_count: 6
								},
								effects: [],
								findings: [
									{
										finding_id: 'finding_review_only',
										claim_id: 'claim_review_only',
										title: 'scan strategy rotation angle and build orientation -> yield strength',
										statement:
											'Scan strategy rotation angles and build orientations can be used to predict crystallographic texture changes and Bishop-Hill yield strength in LPBF 316L.',
										variables: ['scan strategy rotation angle', 'build orientation'],
										mediators: ['crystallographic texture'],
										outcomes: ['yield strength'],
										direction: 'explains',
										scope_summary: '316L stainless steel, LPBF',
										support_grade: 'weak',
										review_status: 'needs_review',
										confidence: 0.72,
										paper_count: 1,
										evidence_count: 1,
										evidence_ref_ids: ['ev_review'],
										context_ids: [],
										relation_ids: [],
										evidence_bundle: {
											direct_result: ['ev_review'],
											mechanism: [],
											condition_context: [],
											background: [],
											conflict: [],
											noise: [],
											uncategorized: []
										},
										expert_use_status: 'review_candidate',
										dataset_use_status: 'review_candidate',
										generalization_status: 'paper_level_only',
										generalization_note:
											'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
										evidence_gap_summary: 'Needs expert review.',
										upgrade_actions: ['record_expert_review'],
										review_reasons: ['model_validation_finding'],
										warnings: ['model_validation_finding']
									}
								],
								primary_findings: [],
								review_queue_findings: [
									{
										finding_id: 'finding_review_only',
										claim_id: 'claim_review_only',
										title: 'scan strategy rotation angle and build orientation -> yield strength',
										statement:
											'Scan strategy rotation angles and build orientations can be used to predict crystallographic texture changes and Bishop-Hill yield strength in LPBF 316L.',
										variables: ['scan strategy rotation angle', 'build orientation'],
										mediators: ['crystallographic texture'],
										outcomes: ['yield strength'],
										direction: 'explains',
										scope_summary: '316L stainless steel, LPBF',
										support_grade: 'weak',
										review_status: 'needs_review',
										confidence: 0.72,
										paper_count: 1,
										evidence_count: 1,
										evidence_ref_ids: ['ev_review'],
										context_ids: [],
										relation_ids: [],
										evidence_bundle: {
											direct_result: ['ev_review'],
											mechanism: [],
											condition_context: [],
											background: [],
											conflict: [],
											noise: [],
											uncategorized: []
										},
										expert_use_status: 'review_candidate',
										dataset_use_status: 'review_candidate',
										generalization_status: 'paper_level_only',
										generalization_note:
											'Evidence comes from one paper; use this as a traceable paper-level finding, not a cross-paper conclusion.',
										evidence_gap_summary: 'Needs expert review.',
										upgrade_actions: ['record_expert_review'],
										review_reasons: ['model_validation_finding'],
										warnings: ['model_validation_finding']
									}
								],
								evidence_items: [],
								context_summaries: []
							}
						},
						pipeline_nodes: {
							finalize_goal: {
								status: 'succeeded',
								warnings: [
									'goal analysis produced review candidates but no primary research findings'
								]
							}
						},
						errors: [],
						warnings: [
							'goal analysis produced review candidates but no primary research findings'
						]
					})
				);
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500));
		});

		render(Page);

		await expect
			.element(browserPage.getByText('Goal analysis needs review'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'goal analysis produced review candidates but no primary research findings'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Goal analysis failed'))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research understanding' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Review before use').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Review candidates 1' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('No expert findings yet')).not.toBeInTheDocument();
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
			.element(
				browserPage.getByText('Model prediction or validation evidence needs expert review.')
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Review candidates 1' }))
			.toHaveAttribute('aria-pressed', 'true');
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
