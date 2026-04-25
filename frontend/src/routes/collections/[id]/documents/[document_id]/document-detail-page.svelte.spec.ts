import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type DocumentDetailPageState = {
	params: {
		id: string;
		document_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock, getDocumentMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: DocumentDetailPageState) => void>();
	let current: DocumentDetailPageState = {
		params: { id: 'col_123', document_id: 'doc_1' },
		url: new URL('http://localhost/collections/col_123/documents/doc_1')
	};

	return {
		pageStore: {
			subscribe(run: (value: DocumentDetailPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: DocumentDetailPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn(),
		getDocumentMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({
	page: pageStore
}));

vi.mock('pdfjs-dist', () => ({
	GlobalWorkerOptions: { workerSrc: '' },
	getDocument: getDocumentMock
}));

vi.mock('pdfjs-dist/build/pdf.worker.mjs?url', () => ({
	default: '/mock-pdf-worker.mjs'
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

describe('collections/[id]/documents/[document_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL('http://localhost/collections/col_123/documents/doc_1')
		});
		fetchMock.mockReset();
		getDocumentMock.mockReset();
		getDocumentMock.mockImplementation(() => ({
			promise: Promise.resolve({
				numPages: 4,
				destroy: vi.fn(),
				getPage: vi.fn(async () => ({
					getViewport: ({ scale }: { scale: number }) => ({
						width: 600 * scale,
						height: 820 * scale
					}),
					render: vi.fn(() => ({
						promise: Promise.resolve(),
						cancel: vi.fn()
					}))
				}))
			}),
			destroy: vi.fn()
		}));
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const rawUrl =
				typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			const url = new URL(rawUrl, 'http://localhost');

			if (url.pathname === '/api/v1/collections/col_123/documents/doc_1/content') {
				return jsonResponse({
					collection_id: 'col_123',
					document_id: 'doc_1',
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					content_text:
						'Abstract\nConductivity improved to 12 mS/cm.\nMethodology\nThe sample was annealed at 700 C.\nResults\nConductivity improved to 12 mS/cm under EIS.',
					blocks: [
						{
							block_id: 'abstract',
							block_type: 'abstract',
							heading_path: 'Abstract',
							heading_level: 1,
							order: 1,
							text: 'Conductivity improved to 12 mS/cm.',
							start_offset: 9,
							end_offset: 43,
							text_unit_ids: [],
							page: 1,
							bbox: { x0: 18, y0: 20, x1: 82, y1: 24.5, coord_origin: 'percent' }
						},
						{
							block_id: 'methods',
							block_type: 'methods',
							heading_path: 'Methodology',
							heading_level: 1,
							order: 2,
							text: 'The sample was annealed at 700 C.',
							start_offset: 56,
							end_offset: 89,
							text_unit_ids: [],
							page: 2,
							bbox: { x0: 22, y0: 44, x1: 72, y1: 48.5, coord_origin: 'percent' }
						},
						{
							block_id: 'results',
							block_type: 'results',
							heading_path: 'Results',
							heading_level: 1,
							order: 3,
							text: 'Conductivity improved to 12 mS/cm under EIS.',
							start_offset: 98,
							end_offset: 143,
							text_unit_ids: [],
							page: 3,
							bbox: { x0: 18, y0: 62, x1: 76, y1: 66.5, coord_origin: 'percent' }
						}
					],
					warnings: []
				});
			}
			if (url.pathname === '/api/v1/collections/col_123/results') {
				return jsonResponse({
					collection_id: 'col_123',
					total: 1,
					count: 1,
					items: [
						{
							result_id: 'cres_1',
							document_id: 'doc_1',
							document_title: 'Paper A',
							material_label: 'oxide cathode',
							variant_label: 'Sample A',
							property: 'conductivity',
							value: 12,
							unit: 'mS/cm',
							summary: '12 mS/cm',
							baseline: 'as-prepared',
							test_condition: 'EIS',
							process: '700 C',
							traceability_status: 'direct',
							comparability_status: 'comparable',
							requires_expert_review: false
						}
					]
				});
			}
			if (
				url.pathname === '/api/v1/collections/col_123/documents/doc_1/comparison-semantics' &&
				url.searchParams.get('include_grouped_projections') === 'true'
			) {
				return jsonResponse({
					collection_id: 'col_123',
					document_id: 'doc_1',
					total: 1,
					count: 1,
					items: [],
					variant_dossiers: [
						{
							variant_id: 'var_1',
							variant_label: 'optimized VED + HIP',
							material: {
								label: 'oxide cathode',
								composition: 'LiNiO2'
							},
							shared_process_state: {
								anneal_temperature_c: 700
							},
							shared_missingness: [],
							series: [
								{
									series_key: 'conductivity:test_temperature_c',
									property_family: 'conductivity',
									test_family: 'EIS',
									varying_axis: {
										axis_name: 'test_temperature_c',
										axis_unit: 'C'
									},
									chains: [
										{
											result_id: 'cres_1',
											source_result_id: 'mr_1',
											measurement: {
												property: 'conductivity',
												value: 12,
												unit: 'mS/cm',
												result_type: 'scalar',
												summary: '12 mS/cm'
											},
											test_condition: {
												test_method: 'EIS',
												test_temperature_c: 25
											},
											baseline: {
												label: 'as-prepared',
												reference: 'same-paper control',
												baseline_type: 'same_document',
												resolved: true
											},
											assessment: {
												comparability_status: 'comparable',
												warnings: [],
												basis: [],
												missing_context: [],
												requires_expert_review: false,
												assessment_epistemic_status: 'grounded'
											},
											value_provenance: {
												value_origin: 'reported',
												source_value_text: '12',
												source_unit_text: 'mS/cm'
											},
											evidence: {
												evidence_ids: ['ev_1'],
												direct_anchor_ids: ['anc_1'],
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
				});
			}

			return jsonResponse({ detail: 'collection not found: col_123' }, 404, 'Not Found');
		});
	});

	it('renders the paper reading workbench with tabs and local graph', async () => {
		render(Page);

		await expect.element(browserPage.getByText('Lens')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Paper A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByRole('tab', { name: 'Summary' })).toBeInTheDocument();
		await expect.element(browserPage.getByText('Graph').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research question' }).first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Block results')).not.toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-page-shell').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Parsed source fallback')).not.toBeInTheDocument();

		await browserPage.getByRole('tab', { name: 'Results' }).click();
		await expect.element(browserPage.getByText('oxide cathode').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Comparable').first()).toBeInTheDocument();
		await browserPage.getByText('oxide cathode').first().click();
		await expect.element(browserPage.getByTestId('pdf-highlight').first()).toBeInTheDocument();
		const resultHighlightStyle = browserPage
			.getByTestId('pdf-highlight')
			.first()
			.element()
			.getAttribute('style');
		expect(resultHighlightStyle).toContain('left: 22%');

		await browserPage.getByRole('tab', { name: 'Evidence' }).click();
		await expect
			.element(browserPage.getByText('conductivity is reported for oxide cathode.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Jump to source' }).first())
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Jump to source' }).first().click();
		await expect.element(browserPage.getByTestId('pdf-highlight').first()).toBeInTheDocument();
	});
});
