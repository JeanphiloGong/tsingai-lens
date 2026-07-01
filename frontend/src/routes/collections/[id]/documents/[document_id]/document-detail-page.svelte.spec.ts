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

vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
	GlobalWorkerOptions: { workerSrc: '' },
	getDocument: getDocumentMock
}));

vi.mock('pdfjs-dist/legacy/build/pdf.worker.mjs?url', () => ({
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

function requestPath(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost').pathname;
}

function tracebackCallPaths() {
	return fetchMock.mock.calls
		.map(([input]) => requestPath(input as string | URL | Request))
		.filter((path) => path.endsWith('/traceback'));
}

function callPaths() {
	return fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request));
}

function buildResearchPayload() {
	return {
		collection_id: 'col_123',
		document_id: 'doc_1',
		state: 'ready',
		paper_title: 'Paper A',
		overview: {
			material_systems: ['oxide cathode'],
			sample_variant_count: 1,
			main_process_variables: ['anneal temperature'],
			measured_properties: ['conductivity']
		},
		materials: [
			{
				material_id: 'oxide_cathode',
				canonical_name: 'oxide cathode',
				aliases: ['LiNiO2'],
				sample_count: 1,
				process_families: ['annealing'],
				measured_properties: ['conductivity'],
				comparison_count: 1
			}
		],
		sample_matrix: {
			matrix_id: 'sample_matrix',
			columns: [{ value_key: 'conductivity', label: 'Conductivity' }],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: 'oxide cathode',
					process_context: { anneal: '700 C' },
					values: {
						conductivity: {
							display_value: '12 mS/cm',
							status: 'observed',
							evidence_refs: [{ evidence_ref_id: 'ev_1', locator: 'Results' }]
						}
					}
				}
			]
		},
		condition_series: [
			{
				series_id: 'series_1',
				property: 'conductivity',
				condition_axis: { axis_name: 'temperature' },
				points: [
					{
						point_id: 'point_1',
						condition_value: 700,
						condition_unit: 'C',
						result: {
							display_value: '12 mS/cm',
							status: 'observed'
						}
					}
				]
			}
		]
	};
}

let researchPayload: unknown = null;

describe('collections/[id]/documents/[document_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL('http://localhost/collections/col_123/documents/doc_1')
		});
		fetchMock.mockReset();
		researchPayload = buildResearchPayload();
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
			if (url.pathname === '/api/v1/collections/col_123/documents/doc_1/markdown') {
				return jsonResponse({
					collection_id: 'col_123',
					document_id: 'doc_1',
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					parser: 'docling',
					markdown:
						'# Paper A\n\n## Abstract\n\nConductivity improved to 12 mS/cm.\n\n## Methodology\n\nThe sample was annealed at 700 C.\n\n## Results\n\nConductivity improved to 12 mS/cm under EIS.\n\n![Fig. 1](/api/v1/collections/col_123/documents/doc_1/figures/fig_1/image)\n\n**Figure.** Fig. 1. Microstructure after annealing.\n\n| Sample | Conductivity |\n| --- | --- |\n| A | 12 mS/cm |',
					source_map: [
						{
							markdown_anchor: 'block-abstract',
							artifact_type: 'block',
							artifact_id: 'abstract',
							block_id: 'abstract',
							block_type: 'paragraph',
							page: 1,
							heading_path: 'Abstract',
							text_unit_ids: []
						},
						{
							markdown_anchor: 'block-results',
							artifact_type: 'block',
							artifact_id: 'results',
							block_id: 'results',
							block_type: 'paragraph',
							page: 3,
							heading_path: 'Results',
							text_unit_ids: []
						},
						{
							markdown_anchor: 'figure-fig-1',
							artifact_type: 'figure',
							artifact_id: 'fig_1',
							block_id: null,
							table_id: null,
							figure_id: 'fig_1',
							block_type: null,
							page: 3,
							heading_path: 'Results',
							text_unit_ids: []
						}
					],
					warnings: []
				});
			}
			if (
				url.pathname === '/api/v1/collections/col_123/documents/doc_1/research-view' &&
				researchPayload
			) {
				return jsonResponse(researchPayload);
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
										},
										{
											result_id: 'cres_2',
											source_result_id: 'mr_2',
											measurement: {
												property: 'capacity',
												value: 145,
												unit: 'mAh/g',
												result_type: 'scalar',
												summary: '145 mAh/g'
											},
											test_condition: {
												test_method: 'cycling',
												test_temperature_c: 25
											},
											baseline: {
												label: 'as-prepared',
												reference: 'same-paper control',
												baseline_type: 'same_document',
												resolved: true
											},
											assessment: {
												comparability_status: 'limited',
												warnings: ['Cycle count is not fully specified.'],
												basis: [],
												missing_context: ['cycle_count'],
												requires_expert_review: true,
												assessment_epistemic_status: 'partial'
											},
											value_provenance: {
												value_origin: 'reported',
												source_value_text: '145',
												source_unit_text: 'mAh/g'
											},
											evidence: {
												evidence_ids: ['ev_2'],
												direct_anchor_ids: ['anc_2'],
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
			if (url.pathname === '/api/v1/collections/col_123/evidence/ev_1/traceback') {
				return jsonResponse({
					collection_id: 'col_123',
					evidence_id: 'ev_1',
					traceback_status: 'ready',
					anchors: [
						{
							anchor_id: 'anc_1',
							document_id: 'doc_1',
							locator_type: 'bbox',
							locator_confidence: 'high',
							page: 3,
							quote: 'Conductivity improved to 12 mS/cm under EIS.',
							section_id: 'Results',
							block_id: 'results',
							char_range: { start: 98, end: 143 },
							bbox: { x0: 18, y0: 62, x1: 76, y1: 66.5 },
							deep_link: '/collections/col_123/documents/doc_1?evidence_id=ev_1&anchor_id=anc_1'
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
		expect(tracebackCallPaths()).toEqual([]);
		await browserPage.getByRole('button', { name: 'Show extraction details' }).click();
		await expect.element(browserPage.getByRole('tab', { name: 'Overview' })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('tab', { name: 'Methods' })).not.toBeInTheDocument();
		await expect.element(browserPage.getByRole('tab', { name: 'Q&A' })).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Graph').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research question' }).first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Preparation / processing / treatment' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Block results')).not.toBeInTheDocument();
		await expect.element(browserPage.getByTestId('markdown-paper-reader')).toBeInTheDocument();
		await expect.element(browserPage.getByRole('heading', { name: 'Abstract' })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('img', { name: 'Fig. 1' })).toHaveAttribute(
			'src',
			'/api/v1/collections/col_123/documents/doc_1/figures/fig_1/image'
		);
		await expect
			.element(browserPage.getByText('Figure. Fig. 1. Microstructure after annealing.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-page-shell').first()).not.toBeInTheDocument();

		await browserPage.getByRole('tab', { name: 'Results' }).click();
		await expect.element(browserPage.getByText('oxide cathode').first()).toBeInTheDocument();
		await expect.element(browserPage.getByText('Comparable').first()).toBeInTheDocument();
		await browserPage.getByRole('button', { name: /oxide cathode.*conductivity/i }).click();
		await expect.element(browserPage.getByTestId('pdf-highlight').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-current-page')).toHaveTextContent('3');
		expect(tracebackCallPaths()).toEqual(['/api/v1/collections/col_123/evidence/ev_1/traceback']);
		const resultHighlightStyle = browserPage
			.getByTestId('pdf-highlight')
			.first()
			.element()
			.getAttribute('style');
		expect(resultHighlightStyle).toContain('left: 18%');
		await expect.element(browserPage.getByTestId('pdf-current-page')).toHaveTextContent('3');

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

	it('uses parsed source text when the PDF cannot be rendered', async () => {
		getDocumentMock.mockImplementationOnce(() => ({
			promise: Promise.reject(new Error('connection reset')),
			destroy: vi.fn()
		}));

		render(Page);

		await browserPage.getByRole('tab', { name: 'PDF Preview' }).click();
		await expect.element(browserPage.getByText('Parsed source fallback')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Conductivity improved to 12 mS/cm under EIS.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Source preview unavailable')).not.toBeInTheDocument();
	});

	it('lets the user view parsed source text while the PDF is available', async () => {
		render(Page);

		await browserPage.getByRole('tab', { name: 'PDF Preview' }).click();
		await expect.element(browserPage.getByTestId('pdf-page-shell').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('parsed-source-fallback')).not.toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'View source text' }).click();

		await expect.element(browserPage.getByTestId('parsed-source-fallback')).toBeInTheDocument();
		await expect.element(browserPage.getByText('The sample was annealed at 700 C.')).toBeInTheDocument();

		await browserPage.getByRole('button', { name: 'View PDF' }).click();

		await expect.element(browserPage.getByTestId('pdf-page-shell').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('parsed-source-fallback')).not.toBeInTheDocument();
	});

	it('renders paper research sample matrix when research view is ready', async () => {
		render(Page);

		await browserPage.getByRole('button', { name: 'Show extraction details' }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Paper research view' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Materials in this paper' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Sample matrix' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '12 mS/cm' }).first())
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('conductivity / temperature')).toBeInTheDocument();
	});

	it('organizes structured understanding in scientific reading order', async () => {
		render(Page);

		await browserPage.getByRole('button', { name: 'Show extraction details' }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Paper scope' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Experimental objects' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Preparation / processing / treatment' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Test and characterization methods' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Measured results' }))
			.toBeInTheDocument();
	});

	it('renders an unavailable state when paper research view is missing', async () => {
		researchPayload = null;

		render(Page);

		await browserPage.getByRole('button', { name: 'Show extraction details' }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Paper research view is unavailable' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research question' }).first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Sample matrix' }))
			.not.toBeInTheDocument();
	});

	it('loads only the requested traceback for a document source deep link', async () => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL(
				'http://localhost/collections/col_123/documents/doc_1?evidence_id=ev_1&anchor_id=anc_1'
			)
		});

		render(Page);

		await expect.element(browserPage.getByText('Paper A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-current-page')).toHaveTextContent('3');
		expect(tracebackCallPaths()).toEqual(['/api/v1/collections/col_123/evidence/ev_1/traceback']);
	});

	it('keeps research-understanding evidence links in parsed paper mode', async () => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL(
				'http://localhost/collections/col_123/documents/doc_1?view=parsed-paper&evidence_id=ev_1&anchor_id=anc_1&page=3'
			)
		});

		render(Page);

		await expect.element(browserPage.getByText('Paper A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('markdown-paper-reader')).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-current-page')).not.toBeInTheDocument();
		expect(tracebackCallPaths()).toEqual(['/api/v1/collections/col_123/evidence/ev_1/traceback']);
	});

	it('highlights the parsed paper source when a source_ref deep link is present', async () => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL(
				'http://localhost/collections/col_123/documents/doc_1?view=parsed-paper&source_ref=results&page=3'
			)
		});

		render(Page);

		await expect.element(browserPage.getByText('Paper A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('markdown-paper-reader')).toBeInTheDocument();
		await expect
			.element(browserPage.getByTestId('markdown-active-source'))
			.toHaveTextContent('Conductivity improved to 12 mS/cm under EIS.');
		await expect.element(browserPage.getByTestId('pdf-current-page')).not.toBeInTheDocument();
		expect(callPaths()).not.toContain('/api/v1/collections/col_123/results');
		expect(callPaths()).not.toContain(
			'/api/v1/collections/col_123/documents/doc_1/comparison-semantics'
		);
		expect(tracebackCallPaths()).toEqual([]);
	});

	it('honors page and return_to query parameters for source review links', async () => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL(
				'http://localhost/collections/col_123/documents/doc_1?page=2&return_to=/collections/col_123/objectives/obj_1'
			)
		});

		render(Page);

		await expect.element(browserPage.getByText('Paper A').first()).toBeInTheDocument();
		await expect.element(browserPage.getByTestId('pdf-current-page')).toHaveTextContent('2');
		expect(
			browserPage.getByRole('link', { name: 'Documents' }).element().getAttribute('href')
		).toBe('/collections/col_123/objectives/obj_1');
	});
});
