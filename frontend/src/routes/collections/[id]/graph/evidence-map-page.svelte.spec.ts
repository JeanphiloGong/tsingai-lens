import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type EvidenceMapPageState = {
	params: { id: string };
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: EvidenceMapPageState) => void>();
	let current: EvidenceMapPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/graph')
	};

	return {
		pageStore: {
			subscribe(run: (value: EvidenceMapPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: EvidenceMapPageState) {
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

function objectivesPayload(published = true) {
	return {
		collection_id: 'col_123',
		objectives: [
			{
				collection_id: 'col_123',
				objective_id: 'obj_1',
				question: 'How does heat treatment affect tensile strength?',
				material_scope: ['Alloy A'],
				variables: ['heat treatment temperature'],
				outcomes: ['ultimate tensile strength'],
				mechanisms: [],
				constraints: [],
				requested_comparator: null,
				seed_document_ids: ['paper-1', 'paper-2', 'paper-3'],
				excluded_document_ids: [],
				confidence: 0.9,
				reason: null,
				confirmation_status: 'confirmed',
				active_analysis_version: published ? 1 : null,
				published_analysis_version: published ? 1 : null,
				created_at: null,
				updated_at: null
			}
		]
	};
}

function evidenceMapPayload() {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_1',
		analysis_version: 1,
		projection_version: 'objective-evidence-map.v1',
		complete: true,
		coverage: {
			total_document_count: 3,
			analyzed_document_count: 2,
			excluded_document_count: 0,
			failed_document_count: 1,
			direct_evidence_document_count: 2,
			finding_count: 1,
			evidence_count: 2,
			source_count: 2,
			unlinked_evidence_count: 0
		},
		nodes: [
			{
				id: 'objective:obj_1',
				type: 'objective',
				label: 'How does heat treatment affect tensile strength?',
				objective_id: 'obj_1',
				question: 'How does heat treatment affect tensile strength?',
				material_scope: ['Alloy A'],
				variables: ['heat treatment temperature'],
				outcomes: ['ultimate tensile strength']
			},
			{
				id: 'finding:finding-1',
				type: 'finding',
				label: 'Heat treatment generally decreased tensile strength.',
				finding_id: 'finding-1',
				statement: 'Heat treatment generally decreased tensile strength.',
				factors: ['heat treatment temperature'],
				outcome: 'ultimate tensile strength',
				direction: 'decrease',
				assertion_strength: 'associative',
				synthesis_status: 'conflict',
				certainty: 0.6,
				limitations: ['One paper reported an increase.']
			},
			{
				id: 'evidence:ev-support',
				type: 'evidence',
				label: 'UTS decreased after heat treatment.',
				evidence_id: 'ev-support',
				document_id: 'paper-1',
				evidence_role: 'direct_result',
				attribution_scope: 'isolated_effect',
				confidence: 0.91,
				direction: 'decrease',
				outcome: 'ultimate tensile strength',
				source_excerpt: 'The UTS decreased after treatment.'
			},
			{
				id: 'evidence:ev-conflict',
				type: 'evidence',
				label: 'UTS increased after heat treatment.',
				evidence_id: 'ev-conflict',
				document_id: 'paper-2',
				evidence_role: 'contradictory_result',
				attribution_scope: 'isolated_effect',
				confidence: 0.82,
				direction: 'increase',
				outcome: 'ultimate tensile strength',
				source_excerpt: 'The UTS increased after treatment.'
			},
			{
				id: 'source:source-1',
				type: 'source',
				label: 'Table · table-7',
				document_id: 'paper-1',
				source_kind: 'table',
				source_ref: 'table-7',
				source_excerpt: 'The UTS decreased after treatment.',
				page_numbers: [20],
				evidence_ids: ['ev-support']
			},
			{
				id: 'source:source-2',
				type: 'source',
				label: 'Table · table-2',
				document_id: 'paper-2',
				source_kind: 'table',
				source_ref: 'table-2',
				source_excerpt: 'The UTS increased after treatment.',
				page_numbers: [8],
				evidence_ids: ['ev-conflict']
			},
			{
				id: 'document:paper-1',
				type: 'document',
				label: 'Heat treatment paper A',
				document_id: 'paper-1',
				analysis_status: 'analyzed',
				evidence_disposition: 'comparable_evidence',
				evidence_disposition_reason: null
			},
			{
				id: 'document:paper-2',
				type: 'document',
				label: 'Heat treatment paper B',
				document_id: 'paper-2',
				analysis_status: 'analyzed',
				evidence_disposition: 'comparable_evidence',
				evidence_disposition_reason: null
			},
			{
				id: 'document:paper-3',
				type: 'document',
				label: 'Heat treatment paper C',
				document_id: 'paper-3',
				analysis_status: 'failed',
				evidence_disposition: 'extraction_failed',
				evidence_disposition_reason: 'provider timeout'
			}
		],
		edges: [
			{
				id: 'edge-1',
				source: 'objective:obj_1',
				target: 'finding:finding-1',
				relation: 'has_finding',
				condition_boundary: false
			},
			{
				id: 'edge-2',
				source: 'finding:finding-1',
				target: 'evidence:ev-support',
				relation: 'supports',
				condition_boundary: false
			},
			{
				id: 'edge-3',
				source: 'finding:finding-1',
				target: 'evidence:ev-conflict',
				relation: 'contradicts',
				condition_boundary: false
			},
			{
				id: 'edge-4',
				source: 'evidence:ev-support',
				target: 'source:source-1',
				relation: 'extracted_from',
				condition_boundary: false
			},
			{
				id: 'edge-5',
				source: 'source:source-1',
				target: 'document:paper-1',
				relation: 'reported_in',
				condition_boundary: false
			}
		]
	};
}

describe('collections/[id]/graph/+page.svelte', () => {
	let published = true;

	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/graph')
		});
		published = true;
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');
			if (url.pathname === '/api/v1/collections/col_123/objectives') {
				return jsonResponse(objectivesPayload(published));
			}
			if (url.pathname === '/api/v1/collections/col_123/objectives/obj_1/evidence-map') {
				return jsonResponse(evidenceMapPayload());
			}
			return jsonResponse({ detail: `unexpected request: ${url.pathname}` }, 404, 'Not Found');
		});
	});

	it('shows support, contradiction, source lineage, and failed paper coverage', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Objective evidence map' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Heat treatment generally decreased tensile strength.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Supports')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Contradicts')).toBeInTheDocument();
		await expect.element(browserPage.getByText('1 failed paper')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Heat treatment paper C')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Table · table-7' }))
			.toHaveAttribute(
				'href',
				expect.stringContaining(
					'/collections/col_123/documents/paper-1?view=parsed-paper&source_ref=table-7'
				)
			);
	});

	it('shows an Objective action when no published analysis exists', async () => {
		published = false;
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'No published evidence maps yet' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open research objectives' }))
			.toHaveAttribute('href', '/collections/col_123/objectives');
	});
});
