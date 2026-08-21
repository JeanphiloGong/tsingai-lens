import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ComparisonsPageState = {
	params: { id: string };
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ComparisonsPageState) => void>();
	let current: ComparisonsPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/comparisons')
	};

	return {
		pageStore: {
			subscribe(run: (value: ComparisonsPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: ComparisonsPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown, status = 200, statusText = 'OK') {
	return new Response(JSON.stringify(body), {
		status,
		statusText,
		headers: { 'Content-Type': 'application/json' }
	});
}

function objectivesPayload() {
	return {
		collection_id: 'col_123',
		objectives: [
			{
				collection_id: 'col_123',
				objective_id: 'obj_published',
				question: 'How does annealing temperature affect electrical conductivity?',
				material_scope: ['oxide cathode'],
				variables: ['annealing temperature'],
				outcomes: ['electrical conductivity'],
				mechanisms: [],
				constraints: [],
				requested_comparator: null,
				seed_document_ids: ['doc_1', 'doc_2'],
				excluded_document_ids: [],
				confidence: 0.86,
				reason: null,
				confirmation_status: 'confirmed',
				active_analysis_version: 2,
				published_analysis_version: 2,
				created_at: null,
				updated_at: null
			},
			{
				collection_id: 'col_123',
				objective_id: 'obj_candidate',
				question: 'Does pressure affect density?',
				material_scope: ['oxide cathode'],
				variables: ['pressure'],
				outcomes: ['density'],
				mechanisms: [],
				constraints: [],
				requested_comparator: null,
				seed_document_ids: ['doc_1'],
				excluded_document_ids: [],
				confidence: 0.64,
				reason: null,
				confirmation_status: 'candidate',
				active_analysis_version: null,
				published_analysis_version: null,
				created_at: null,
				updated_at: null
			}
		]
	};
}

function findingPayload() {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_published',
		analysis_version: 2,
		items: [
			{
				collection_id: 'col_123',
				objective_id: 'obj_published',
				analysis_version: 2,
				finding_id: 'finding_1',
				statement: 'Higher annealing temperature was associated with lower conductivity.',
				factors: ['annealing temperature'],
				outcome: 'electrical conductivity',
				direction: 'decrease',
				assertion_strength: 'associative',
				attribution_scope: 'direct',
				synthesis_status: 'agreement',
				certainty: 0.82,
				display_rank: 1,
				mechanisms: [],
				scientific_context: { material: [], sample: [], process: [], test: [] },
				limitations: ['The papers used different conductivity test frequencies.'],
				paper_contributions: [
					{
						document_id: 'doc_1',
						analysis_status: 'analyzed',
						supporting_evidence_ids: ['ev_1'],
						contradicting_evidence_ids: [],
						context_evidence_ids: [],
						condition_boundary_evidence_ids: []
					},
					{
						document_id: 'doc_2',
						analysis_status: 'analyzed',
						supporting_evidence_ids: ['ev_2'],
						contradicting_evidence_ids: [],
						context_evidence_ids: [],
						condition_boundary_evidence_ids: []
					}
				]
			}
		],
		offset: 0,
		limit: 50,
		total: 1
	};
}

describe('collections/[id]/comparisons/+page.svelte', () => {
	let findings = findingPayload();

	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/comparisons')
		});
		findings = findingPayload();
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');
			if (url.pathname === '/api/v1/collections/col_123/objectives') {
				return jsonResponse(objectivesPayload());
			}
			if (
				url.pathname === '/api/v1/collections/col_123/objectives/obj_published/findings' &&
				url.searchParams.get('analysis_version') === '2'
			) {
				return jsonResponse(findings);
			}
			return jsonResponse({ detail: `unexpected request: ${url.pathname}` }, 404, 'Not Found');
		});
	});

	it('lists published cross-paper findings and links to their evidence review', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Cross-paper findings' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Higher annealing temperature was associated with lower conductivity.'
				)
			)
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('2 supporting papers')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Review finding evidence' }))
			.toHaveAttribute(
				'href',
				'/collections/col_123/objectives/obj_published?finding_id=finding_1'
			);
		expect(
			fetchMock.mock.calls.some(([input]) => String(input).includes('obj_candidate/findings'))
		).toBe(false);
	});

	it('explains when the collection has no published findings', async () => {
		findings = { ...findingPayload(), items: [], total: 0 };
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'No published findings yet' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open research objectives' }))
			.toHaveAttribute('href', '/collections/col_123/objectives');
	});
});
