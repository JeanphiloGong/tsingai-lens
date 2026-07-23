import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivePageState = {
	params: { id: string; objective_id: string };
	url: URL;
};

const { pageStore, setPage, goto, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivePageState) => void>();
	let current: ObjectivePageState = {
		params: { id: 'col_123', objective_id: 'obj_1' },
		url: new URL('http://localhost/collections/col_123/objectives/obj_1')
	};
	return {
		pageStore: {
			subscribe(run: (value: ObjectivePageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ObjectivePageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		goto: vi.fn(),
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string>) =>
		route.includes('/documents/')
			? `/collections/${params.id}/documents/${params.document_id}`
			: `/collections/${params.id}/objectives/${params.objective_id}`
}));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function request(input: string | URL | Request, init?: RequestInit) {
	const raw = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	const url = new URL(raw, 'http://localhost');
	return {
		path: url.pathname,
		search: url.search,
		method: input instanceof Request ? input.method : (init?.method ?? 'GET')
	};
}

function objective(overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_1',
		question: 'How does heat treatment affect LPBF 316L tensile strength?',
		material_scope: ['316L stainless steel'],
		process_axes: ['heat treatment'],
		property_axes: ['yield strength'],
		comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
		seed_document_ids: ['paper-1'],
		excluded_document_ids: [],
		confidence: 0.91,
		reason: null,
		confirmation_status: 'confirmed',
		active_analysis_version: 1,
		published_analysis_version: 1,
		created_at: null,
		updated_at: null,
		...overrides
	};
}

function analysisState(status: string, version = 1, overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_1',
		analysis_version: version,
		source_build_id: 'build-1',
		pipeline_version: 'objective-analysis.v2',
		model_name: 'model-1',
		prompt_versions: {},
		status,
		phase: status,
		processed_document_count: status === 'succeeded' ? 1 : 0,
		total_document_count: 1,
		current_document_id: null,
		progress_message: null,
		error_code: null,
		error_message: null,
		created_at: null,
		started_at: null,
		completed_at: null,
		...overrides
	};
}

function objectiveResponse(overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		objective: objective(),
		active_analysis: analysisState('succeeded'),
		published_analysis: analysisState('succeeded'),
		warnings: [],
		...overrides
	};
}

const finding = {
	collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1,
	finding_id: 'finding-1', finding_level: 'paper',
	statement: 'Annealing was associated with higher tensile strength.',
	variables: ['heat treatment'], mediators: [], outcomes: ['tensile strength'], direction: 'increase',
	scope_summary: 'LPBF 316L in the reported tensile-test condition.', evidence_strength: 'moderate',
	generalization_status: 'paper_level_only', paper_count: 1, confidence: 0.88, display_rank: 0,
	relations: [{ relation_order: 0, source_term: 'annealing', relation_type: 'associated_with', target_term: 'tensile strength', direction: 'increase', assertion_strength: 'associative', supporting_evidence_ids: ['evidence-1'] }],
	context: { material_system: { name: '316L' }, process_conditions: [{ state: 'annealed' }], sample_state: {}, test_conditions: [{ method: 'tensile test' }], comparison_baseline: { state: 'as-built' }, limitations: ['Single paper only.'], supporting_evidence_ids: ['evidence-1'] },
	derivation: { synthesis_mode: 'paper', comparison_status: 'insufficient_confirmation', contributing_document_ids: ['paper-1'], supporting_evidence_ids: ['evidence-1'], contradicting_evidence_ids: [], rationale: 'One direct result.' }
};

const evidence = {
	collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1,
	evidence_id: 'evidence-1', document_id: 'paper-1', source_kind: 'text_window', source_ref: 'block-7',
	source_excerpt: 'After annealing, tensile strength increased to 620 MPa.', page_numbers: [7], related_source_refs: [],
	evidence_role: 'direct_result', selection_reason: 'Direct result.', selection_status: 'extracted', evidence_kind: 'measurement',
	property_normalized: 'tensile strength', material_system: { name: '316L' }, sample_context: {}, process_context: {}, test_condition: {}, resolved_condition: {},
	value_payload: { value: 620 }, unit: 'MPa', baseline_context: {}, interpretation: null, anchor_ids: [], join_keys: {},
	resolution_status: 'resolved', failure_reason: null, confidence: 0.92
};

function installPublishedResponses(response = objectiveResponse()) {
	fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
		const current = request(input, init);
		if (current.path.endsWith('/objectives/obj_1') && current.method === 'GET') {
			return jsonResponse(response);
		}
		if (current.path.endsWith('/objectives/obj_1/findings')) {
			return jsonResponse({ collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1, items: [finding], offset: 0, limit: 50, total: 1 });
		}
		if (current.path.endsWith('/objectives/obj_1/evidence')) {
			return jsonResponse({ collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1, finding_id: 'finding-1', items: [evidence], offset: 0, limit: 100, total: 1 });
		}
		throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
	});
}

describe('collections/[id]/objectives/[objective_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('confirms a candidate and queues analysis on the same Objective', async () => {
		const requests: Array<{ path: string; method: string }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			requests.push({ path: current.path, method: current.method });
			if (current.path.endsWith('/objectives/obj_1') && current.method === 'GET') {
				return jsonResponse(objectiveResponse({
					objective: objective({ confirmation_status: 'candidate', active_analysis_version: null, published_analysis_version: null }),
					active_analysis: null,
					published_analysis: null
				}));
			}
			if (current.path.endsWith('/confirm') && current.method === 'POST') {
				return jsonResponse(objectiveResponse({ objective: objective({ published_analysis_version: null }), active_analysis: null, published_analysis: null }));
			}
			if (current.path.endsWith('/analysis') && current.method === 'POST') {
				return jsonResponse(objectiveResponse({
					objective: objective({ published_analysis_version: null }),
					active_analysis: analysisState('queued', 1, { progress_message: 'Objective analysis is queued.' }),
					published_analysis: null
				}));
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await browserPage.getByRole('button', { name: '确认并分析' }).click();

		await expect.element(browserPage.getByText('Objective analysis is queued.')).toBeInTheDocument();
		expect(requests).toContainEqual({ path: '/api/v1/collections/col_123/objectives/obj_1/confirm', method: 'POST' });
		expect(requests).toContainEqual({ path: '/api/v1/collections/col_123/objectives/obj_1/analysis', method: 'POST' });
	});

	it('keeps the published Finding readable while a failed retry is shown', async () => {
		const failed = objectiveResponse({
			objective: objective({ active_analysis_version: 2, published_analysis_version: 1 }),
			active_analysis: analysisState('failed', 2, { error_code: 'provider_error', error_message: 'Evidence extraction failed.' }),
			published_analysis: analysisState('succeeded', 1)
		});
		installPublishedResponses(failed);

		render(Page);

		await expect.element(browserPage.getByText('本次分析失败')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Evidence extraction failed.')).toBeInTheDocument();
		await expect.element(browserPage.getByText(finding.statement).first()).toBeInTheDocument();
		await expect.element(browserPage.getByText(evidence.source_excerpt)).toBeInTheDocument();
		await expect.element(browserPage.getByRole('button', { name: '重试分析' })).toBeInTheDocument();
	});

	it('renders one Finding with relation, Context, and an exact source jump', async () => {
		installPublishedResponses();

		render(Page);

		await expect.element(browserPage.getByRole('heading', { name: 'Findings' })).toBeInTheDocument();
		await expect.element(browserPage.getByText('associated_with')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Single paper only.')).toBeInTheDocument();
		await expect.element(browserPage.getByText(evidence.source_excerpt)).toBeInTheDocument();
		await expect.element(browserPage.getByRole('link', { name: '打开原文' })).toHaveAttribute(
			'href',
			'/collections/col_123/documents/paper-1?view=parsed-paper&source_ref=block-7&page=7&quote=After+annealing%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1'
		);
	});
});
