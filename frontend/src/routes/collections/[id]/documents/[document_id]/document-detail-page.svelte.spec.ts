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

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
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

describe('collections/[id]/documents/[document_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', document_id: 'doc_1' },
			url: new URL('http://localhost/collections/col_123/documents/doc_1')
		});
		fetchMock.mockReset();
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
					content_text: 'content',
					blocks: [
						{
							block_id: 'results',
							block_type: 'results',
							heading_path: 'Results',
							heading_level: 1,
							order: 1,
							text: 'Conductivity improved to 12 mS/cm.',
							start_offset: 0,
							end_offset: 33,
							text_unit_ids: []
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
			if (url.pathname === '/api/v1/collections/col_123/evidence/ev_1/traceback') {
				return jsonResponse({
					collection_id: 'col_123',
					evidence_id: 'ev_1',
					traceback_status: 'ready',
					anchors: [
						{
							anchor_id: 'anc_1',
							document_id: 'doc_1',
							locator_type: 'char_range',
							locator_confidence: 'high',
							page: 4,
							quote: 'Conductivity improved to 12 mS/cm.',
							section_id: 'results',
							block_id: 'results',
							char_range: {
								start: 0,
								end: 33
							},
							bbox: null,
							deep_link: null
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

	it('renders a split source and evidence review workspace', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Source reader' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence review' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Conductivity improved to 12 mS/cm.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Block results')).toBeInTheDocument();

		const sectionHeading = browserPage.getByRole('heading', { name: 'Results from this document' });
		await expect.element(sectionHeading).toBeInTheDocument();

		const resultLink = browserPage.getByRole('link', { name: 'oxide cathode · conductivity' });
		await expect.element(resultLink).toHaveAttribute('href', '/collections/col_123/results/cres_1');

		await expect
			.element(browserPage.getByRole('heading', { name: 'Document evidence chains' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('optimized VED + HIP')).toBeInTheDocument();

		const chainLink = browserPage.getByRole('link', { name: 'conductivity · 12 mS/cm' });
		await expect.element(chainLink).toHaveAttribute('href', '/collections/col_123/results/cres_1');

		const locateButton = browserPage.getByRole('button', { name: 'Locate source' });
		await locateButton.click();

		expect(fetchMock).toHaveBeenCalledWith(
			'/api/v1/collections/col_123/evidence/ev_1/traceback',
			expect.objectContaining({ method: 'GET' })
		);
		await expect.element(browserPage.getByText('Source located')).toBeInTheDocument();
	});
});
