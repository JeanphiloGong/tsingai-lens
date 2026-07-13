import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivesPageState = {
	params: {
		id: string;
	};
	url: URL;
};

const { pageStore, setPage, goto, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivesPageState) => void>();
	let current: ObjectivesPageState = {
		params: { id: 'col_4c54ffe568ec' },
		url: new URL('http://localhost/collections/col_4c54ffe568ec/objectives')
	};

	return {
		pageStore: {
			subscribe(run: (value: ObjectivesPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ObjectivesPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		goto: vi.fn(),
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.mock('$app/navigation', () => ({
	goto
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

function requestUrl(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost');
}

function researchUnderstandingDatasetResponse({
	trainingReady = 0,
	trainingMessages = 0,
	reviewCandidate = 0,
	scopeId = 'goal_1',
	errorCategories = {},
	nextReviewFindingId = '',
	reviewActionCode = ''
} = {}) {
	return {
		schema_version: 'research_understanding_dataset.v1',
		dataset_id: `rud_${scopeId}`,
		collection_id: 'col_4c54ffe568ec',
		scope_type: 'goal',
		scope_id: scopeId,
		task_type: 'research_understanding_finding',
		metric_profile: 'finding_review',
		item_count: trainingReady + reviewCandidate,
		label_counts: {
			candidate: reviewCandidate,
			silver: 0,
			gold: trainingReady,
			rejected: 0
		},
		quality_summary: {
			training_ready_sample_count: trainingReady,
			training_message_sample_count: trainingMessages,
			review_candidate_sample_count: reviewCandidate,
			next_review_finding_id: nextReviewFindingId,
			by_dataset_use_status: {
				training_ready: trainingReady,
				review_candidate: reviewCandidate,
				rejected: 0
			},
			by_presentation_bucket: {},
			by_error_category: errorCategories
		},
		items: reviewCandidate
			? [
					{
						sample_id: `sample_${scopeId}`,
						finding_id: nextReviewFindingId || `finding_${scopeId}`,
						label_status: 'silver',
						dataset_use_status: 'review_candidate',
						review_action: reviewActionCode
							? {
									code: reviewActionCode,
									label: 'review selected table rows before accepting or correcting'
								}
							: {}
					}
				]
			: [],
		warnings: []
	};
}

function confirmedGoalsResponse() {
	return {
		collection_id: 'col_4c54ffe568ec',
		goals: [
			{
				goal_id: 'goal_messages_pending',
				collection_id: 'col_4c54ffe568ec',
				question: 'Which reviewed finding is missing training messages?',
				source_type: 'objective_candidate',
				material_hints: ['316L stainless steel'],
				process_hints: ['VED'],
				property_hints: ['fatigue strength'],
				source_objective_id: 'obj_messages_pending',
				status: 'ready',
				analysis_error: null,
				analysis_progress: null,
				created_at: null,
				updated_at: null
			},
			{
				goal_id: 'goal_protocol_ready',
				collection_id: 'col_4c54ffe568ec',
				question: 'Which reviewed finding can support a protocol?',
				source_type: 'objective_candidate',
				material_hints: ['316L stainless steel'],
				process_hints: ['preheating'],
				property_hints: ['ductility'],
				source_objective_id: 'obj_protocol_ready',
				status: 'ready',
				analysis_error: null,
				analysis_progress: null,
				created_at: null,
				updated_at: null
			},
			{
				goal_id: 'goal_heat_strength',
				collection_id: 'col_4c54ffe568ec',
				question: 'How does heat treatment affect strength?',
				source_type: 'objective_candidate',
				material_hints: ['316L stainless steel'],
				process_hints: ['heat treatment'],
				property_hints: ['yield strength'],
				source_objective_id: 'obj_heat_strength',
				status: 'ready',
				analysis_error: null,
				analysis_progress: null,
				created_at: null,
				updated_at: null
			}
		]
	};
}

function goalReviewResponse(input: string | URL | Request) {
	const url = requestUrl(input);
	const path = url.pathname;
	if (path === '/api/v1/collections/col_4c54ffe568ec/goals') {
		return jsonResponse(confirmedGoalsResponse());
	}
	if (
		path === '/api/v1/collections/col_4c54ffe568ec/research-understanding/dataset'
	) {
		const scopeId = url.searchParams.get('scope_id') ?? '';
		return jsonResponse(
			researchUnderstandingDatasetResponse({
				trainingReady:
					scopeId === 'goal_protocol_ready' || scopeId === 'goal_messages_pending' ? 1 : 0,
				trainingMessages: scopeId === 'goal_protocol_ready' ? 1 : 0,
				reviewCandidate:
					scopeId === 'goal_protocol_ready' || scopeId === 'goal_messages_pending' ? 0 : 2,
				scopeId,
				errorCategories:
					scopeId === 'goal_heat_strength'
						? { variable_error: 2, direction_error: 1, none: 1 }
						: {},
				nextReviewFindingId: scopeId === 'goal_heat_strength' ? 'finding_heat_strength' : '',
				reviewActionCode: scopeId === 'goal_heat_strength' ? 'review_table_rows' : ''
			})
		);
	}
	return null;
}

describe('collections/[id]/objectives/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_4c54ffe568ec' },
			url: new URL('http://localhost/collections/col_4c54ffe568ec/objectives')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('treats not-ready objectives as a pending workflow state', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_4c54ffe568ec/objectives') {
				return jsonResponse(
					{
						code: 'research_objectives_not_ready',
						message:
							'The collection does not have research objectives yet. Finish processing first.',
						collection_id: 'col_4c54ffe568ec'
					},
					409,
					'Conflict'
				);
			}

			return (
				goalReviewResponse(input) ??
				jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected')
			);
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research objectives are pending' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Finish collection processing before reviewing objectives.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open collection overview' }))
			.toHaveAttribute('href', '/collections/col_4c54ffe568ec');
		await expect.element(browserPage.getByText(/409 Conflict/)).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/research_objectives_not_ready/))
			.not.toBeInTheDocument();
	});

	it('confirms an objective, runs goal analysis, and navigates to the goal workspace', async () => {
		const requests: Array<{ path: string; method: string; body: unknown }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			requests.push({
				path,
				method,
				body: init?.body ? JSON.parse(String(init.body)) : null
			});

			if (path === '/api/v1/collections/col_4c54ffe568ec/objectives') {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					count: 1,
					objectives: [
						{
							objective_id: 'obj_heat_strength',
							question: 'How does heat treatment affect strength?',
							material_scope: ['316L stainless steel'],
							process_axes: ['heat treatment'],
							property_axes: ['yield strength'],
							comparison_intent: 'Compare treated and untreated samples.',
							confidence: 0.82,
							state: 'ready',
							paper_frame_count: 2,
							evidence_route_count: 2,
							evidence_unit_count: 1,
							logic_chain_count: 0,
							links: {},
							warnings: []
						}
					]
				});
			}

			if (path === '/api/v1/collections/col_4c54ffe568ec/goals' && method === 'POST') {
				return jsonResponse({
					goal_id: 'goal_heat_strength',
					collection_id: 'col_4c54ffe568ec',
					question: 'How does heat treatment affect strength?',
					source_type: 'objective_candidate',
					material_hints: ['316L stainless steel'],
					process_hints: ['heat treatment'],
					property_hints: ['yield strength'],
					source_objective_id: 'obj_heat_strength',
					status: 'pending',
					analysis_error: null,
					analysis_progress: null,
					created_at: null,
					updated_at: null
				});
			}

			if (
				path === '/api/v1/collections/col_4c54ffe568ec/goals/goal_heat_strength/analysis' &&
				method === 'POST'
			) {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					goal: {
						goal_id: 'goal_heat_strength',
						collection_id: 'col_4c54ffe568ec',
						question: 'How does heat treatment affect strength?',
						source_type: 'objective_candidate',
						material_hints: ['316L stainless steel'],
						process_hints: ['heat treatment'],
						property_hints: ['yield strength'],
						source_objective_id: 'obj_heat_strength',
						status: 'running',
						analysis_error: null,
						analysis_progress: {
							phase: 'queued',
							unit: 'steps',
							message: 'Goal analysis is queued.'
						},
						created_at: null,
						updated_at: null
					},
					understanding: null,
					pipeline_nodes: {
						prepare_goal: { status: 'succeeded' },
						analyze_goal: { status: 'succeeded' },
						finalize_goal: { status: 'succeeded' }
					},
					errors: [],
					warnings: []
				});
			}

			return (
				goalReviewResponse(input) ??
				jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected')
			);
		});

		render(Page);

		await browserPage.getByRole('button', { name: 'Confirm and analyze' }).click();

		expect(
			requests.some(
				(request) =>
					request.path === '/api/v1/collections/col_4c54ffe568ec/goals' &&
					request.method === 'POST' &&
					(request.body as Record<string, unknown>).source_objective_id === 'obj_heat_strength'
			)
		).toBe(true);
		expect(
			requests.some(
				(request) =>
					request.path ===
						'/api/v1/collections/col_4c54ffe568ec/goals/goal_heat_strength/analysis' &&
					request.method === 'POST'
			)
		).toBe(true);
		await vi.waitFor(() => {
			expect(goto).toHaveBeenCalledWith(
				'/collections/col_4c54ffe568ec/goals/goal_heat_strength'
			);
		});
	});

	it('shows confirmed goal review progress for expert labeling', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_4c54ffe568ec/objectives') {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					count: 1,
					objectives: [
						{
							objective_id: 'obj_heat_strength',
							question: 'How does heat treatment affect strength?',
							material_scope: ['316L stainless steel'],
							process_axes: ['heat treatment'],
							property_axes: ['yield strength'],
							comparison_intent: 'Compare treated and untreated samples.',
							confidence: 0.82,
							state: 'ready',
							paper_frame_count: 2,
							evidence_route_count: 2,
							evidence_unit_count: 1,
							logic_chain_count: 0,
							links: {},
							warnings: []
						}
					]
				});
			}

			return (
				goalReviewResponse(input) ??
				jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected')
			);
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Confirmed goal review' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'3 confirmed goal(s): 2 training-ready sample(s), 1 training message(s), 2 review candidate(s).'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Expert loop incomplete'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'2 goal(s) still need expert action: 2 finding(s) need accept/reject/correct, and 1 goal(s) are missing exportable training messages.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Review next goal' }))
			.toHaveAttribute(
				'href',
				'/collections/col_4c54ffe568ec/goals/goal_heat_strength?review=queue&finding_id=finding_heat_strength'
			);
		const correctionTypes = browserPage.getByLabelText('Common expert correction types');
		await expect.element(correctionTypes.getByText('Variable error')).toBeInTheDocument();
		await expect.element(correctionTypes.getByText('2')).toBeInTheDocument();
		await expect.element(correctionTypes.getByText('Direction error')).toBeInTheDocument();
		await expect.element(correctionTypes.getByText('1')).toBeInTheDocument();
		const goalLinks = browserPage.getByRole('link').all();
		const goalReviewLinks = await Promise.all(
			goalLinks.map(async (link) => ({
				text: link.element().textContent ?? '',
				href: link.element().getAttribute('href')
			}))
		);
		const reviewRows = goalReviewLinks.filter(
			(link) => link.href?.includes('/goals/') && link.text.includes('?')
		);
		expect(reviewRows[0]).toMatchObject({
			href: '/collections/col_4c54ffe568ec/goals/goal_heat_strength?review=queue&finding_id=finding_heat_strength'
		});
		expect(reviewRows[0].text).toContain('How does heat treatment affect strength?');
		expect(reviewRows[0].text).toContain('Review selected table rows');
		expect(reviewRows[1]).toMatchObject({
			href: '/collections/col_4c54ffe568ec/goals/goal_messages_pending?review=training_ready'
		});
		expect(reviewRows[1].text).toContain('Which reviewed finding is missing training messages?');
		expect(reviewRows[1].text).toContain('Messages pending');
		expect(reviewRows[1].text).toContain('Check 1 training sample(s)');
		expect(reviewRows[2]).toMatchObject({
			href: '/collections/col_4c54ffe568ec/goals/goal_protocol_ready'
		});
		expect(reviewRows[2].text).toContain('Which reviewed finding can support a protocol?');
		expect(reviewRows[2].text).toContain('Draft from 1 reviewed finding(s)');
	});

	it('confirms an objective without existing routed evidence and lets analysis build coverage', async () => {
		const requests: Array<{ path: string; method: string; body: unknown }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method =
				input instanceof Request
					? input.method
					: typeof init?.method === 'string'
						? init.method
						: 'GET';
			requests.push({
				path,
				method,
				body: init?.body ? JSON.parse(String(init.body)) : null
			});

			if (path === '/api/v1/collections/col_4c54ffe568ec/objectives') {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					count: 1,
					objectives: [
						{
							objective_id: 'obj_empty',
							question: 'How does scan strategy affect fatigue strength?',
							material_scope: ['316L stainless steel'],
							process_axes: ['scan strategy'],
							property_axes: ['fatigue strength'],
							comparison_intent: 'Compare scan strategies.',
							confidence: 0.9,
							state: 'empty',
							paper_frame_count: 0,
							evidence_route_count: 0,
							evidence_unit_count: 0,
							logic_chain_count: 0,
							links: {},
							warnings: []
						}
					]
				});
			}

			if (path === '/api/v1/collections/col_4c54ffe568ec/goals' && method === 'POST') {
				return jsonResponse({
					goal_id: 'goal_empty',
					collection_id: 'col_4c54ffe568ec',
					question: 'How does scan strategy affect fatigue strength?',
					source_type: 'objective_candidate',
					material_hints: ['316L stainless steel'],
					process_hints: ['scan strategy'],
					property_hints: ['fatigue strength'],
					source_objective_id: 'obj_empty',
					status: 'pending',
					analysis_error: null,
					analysis_progress: null,
					created_at: null,
					updated_at: null
				});
			}

			if (
				path === '/api/v1/collections/col_4c54ffe568ec/goals/goal_empty/analysis' &&
				method === 'POST'
			) {
				return jsonResponse({
					collection_id: 'col_4c54ffe568ec',
					goal: {
						goal_id: 'goal_empty',
						collection_id: 'col_4c54ffe568ec',
						question: 'How does scan strategy affect fatigue strength?',
						source_type: 'objective_candidate',
						material_hints: ['316L stainless steel'],
						process_hints: ['scan strategy'],
						property_hints: ['fatigue strength'],
						source_objective_id: 'obj_empty',
						status: 'running',
						analysis_error: null,
						analysis_progress: {
							phase: 'queued',
							unit: 'steps',
							message: 'Goal analysis is queued.'
						},
						created_at: null,
						updated_at: null
					},
					understanding: null,
					pipeline_nodes: {
						prepare_goal: { status: 'succeeded' },
						analyze_goal: { status: 'succeeded' },
						finalize_goal: { status: 'succeeded' }
					},
					errors: [],
					warnings: []
				});
			}

			return (
				goalReviewResponse(input) ??
				jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected')
			);
		});

		render(Page);

		await browserPage.getByRole('button', { name: 'Confirm and analyze' }).click();
		await expect
			.element(
				browserPage.getByText(
					'No routed evidence has been built yet. Confirming this objective will run goal analysis and build coverage.'
				)
			)
			.toBeInTheDocument();
		expect(
			requests.some(
				(request) =>
					request.path === '/api/v1/collections/col_4c54ffe568ec/goals' &&
					request.method === 'POST' &&
					(request.body as Record<string, unknown>).source_objective_id === 'obj_empty'
			)
		).toBe(true);
		expect(
			requests.some(
				(request) =>
					request.path === '/api/v1/collections/col_4c54ffe568ec/goals/goal_empty/analysis' &&
					request.method === 'POST'
			)
		).toBe(true);
		await vi.waitFor(() => {
			expect(goto).toHaveBeenCalledWith('/collections/col_4c54ffe568ec/goals/goal_empty');
		});
	});
});
