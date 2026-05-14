import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivePageState = {
	params: {
		id: string;
		objective_id: string;
	};
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
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

function objectivePayload() {
	return {
		collection_id: 'col_123',
		state: 'ready',
		objective: {
			objective_id: 'obj_1',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			material_scope: ['316L stainless steel'],
			process_axes: ['heat treatment'],
			property_axes: ['yield strength'],
			comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
			confidence: 0.91
		},
		objective_context: {
			objective_id: 'obj_1',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			material_scope: ['316L stainless steel'],
			variable_process_axes: ['heat treatment'],
			target_property_axes: ['yield strength'],
			confidence: 0.88
		},
		readiness: {
			objectives_ready: true,
			frames_ready: true,
			routes_ready: true,
			evidence_units_ready: true,
			logic_chain_ready: true
		},
		paper_frames: [
			{
				frame_id: 'opf_1',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				title: 'LPBF 316L heat treatment study',
				source_filename: 'paper-a.pdf',
				relevance: 'high',
				paper_role: 'primary_experiment',
				background: 'Reports tensile testing of as-built and heat-treated LPBF 316L.',
				material_match: ['316L stainless steel'],
				changed_variables: ['heat treatment'],
				measured_property_scope: ['yield strength'],
				relevant_sections: ['Results'],
				relevant_tables: ['table-2'],
				excluded_tables: ['table-1']
			}
		],
		evidence_routes: [
			{
				route_id: 'route_1',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				source_kind: 'table',
				source_ref: 'table-2',
				role: 'result_table',
				extractable: true,
				table_schema: {
					column_headers: ['Sample', 'Yield strength']
				}
			}
		],
		evidence_units: [
			{
				evidence_unit_id: 'unit_measure',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'measurement',
				property_normalized: 'yield strength',
				sample_context: {
					sample: 'HT-SLM'
				},
				process_context: {
					process: 'LPBF',
					heat_treatment: 'annealed'
				},
				test_condition: {
					method: 'tensile test'
				},
				value_payload: {
					statement: 'Yield strength reached 560 MPa.'
				},
				unit: 'MPa',
				source_refs: [
					{
						document_id: 'doc_1',
						source_kind: 'table',
						source_ref: 'table-2',
						page: 5
					}
				],
				resolution_status: 'resolved',
				confidence: 0.92
			},
			{
				evidence_unit_id: 'unit_condition',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'test_condition',
				property_normalized: 'yield strength',
				test_condition: {
					method: 'tensile test',
					standard: 'ASTM E8'
				},
				value_payload: {
					statement: 'Tensile testing followed ASTM E8.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.86
			},
			{
				evidence_unit_id: 'unit_obs',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'characterization',
				property_normalized: 'microstructure',
				value_payload: {
					observation_text: 'Annealing reduced cellular substructure.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.82
			},
			{
				evidence_unit_id: 'unit_compare',
				objective_id: 'obj_1',
				document_id: 'doc_1',
				unit_kind: 'comparison',
				property_normalized: 'yield strength',
				value_payload: {
					statement: 'Heat-treated samples exceeded the as-built baseline.'
				},
				source_refs: [],
				resolution_status: 'resolved',
				confidence: 0.79
			}
		],
		logic_chain: {
			logic_chain_id: 'chain_1',
			objective_id: 'obj_1',
			chain_scope: 'objective',
			question: 'How does heat treatment affect LPBF 316L tensile strength?',
			evidence_unit_ids: ['unit_measure', 'unit_condition', 'unit_obs'],
			summary: 'Heat-treated LPBF 316L is supported by tensile and microstructure evidence.',
			chain_payload: {
				cross_paper: {
					gaps: ['No cross-paper comparison unit yet.']
				}
			},
			confidence: 0.83
		}
	};
}

describe('collections/[id]/objectives/[objective_id]/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation(async (input: string | URL | Request) => {
			const path = requestPath(input);

			if (path === '/api/v1/collections/col_123/objectives/obj_1/research-view') {
				return jsonResponse(objectivePayload());
			}

			return jsonResponse({ detail: `unexpected request: ${path}` }, 500, 'Unexpected');
		});
	});

	it('renders the objective as a logic-chain workspace with evidence groups and source links', async () => {
		render(Page);

		await expect
			.element(
				browserPage.getByRole('heading', {
					name: 'How does heat treatment affect LPBF 316L tensile strength?'
				})
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Logic chain' }))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Papers are ranked by objective relevance and show the variables, measurements, tables, and evidence units that support this target.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Measurement results' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Test conditions' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Characterization observations' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparison evidence' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('No cross-paper comparison unit yet.'))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Extraction diagnostics' }))
			.toBeInTheDocument();
		expect(document.body.textContent?.indexOf('Logic chain')).toBeLessThan(
			document.body.textContent?.indexOf('Relevant papers')
		);

		const sourceLink = browserPage.getByRole('link', { name: 'table · table-2 · p. 5' });
		await expect
			.element(sourceLink)
			.toHaveAttribute(
				'href',
				'/collections/col_123/documents/doc_1?page=5&source=table-2&evidence_unit_id=unit_measure&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1'
			);
		expect(
			fetchMock.mock.calls.map(([input]) => requestPath(input as string | URL | Request))
		).toEqual(['/api/v1/collections/col_123/objectives/obj_1/research-view']);
	});

	it('filters evidence units by kind and updates the inspector', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence units' }))
			.toBeInTheDocument();
		await browserPage.getByLabelText('Evidence kind').selectOptions('comparison');

		await expect
			.element(browserPage.getByRole('heading', { name: 'Comparison evidence' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Measurement results' }))
			.not.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Heat-treated samples exceeded the as-built baseline.')
			)
			.toBeInTheDocument();
	});

	it('uses logic-chain steps to focus related evidence', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Logic chain' }))
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /Measured results/ }).click();
		await expect.element(browserPage.getByLabelText('Evidence kind')).toHaveValue('measurement');
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Yield strength reached 560 MPa.')
			)
			.toBeInTheDocument();

		await browserPage.getByRole('button', { name: /Experimental conditions/ }).click();
		await expect.element(browserPage.getByLabelText('Evidence kind')).toHaveValue('test_condition');
		await expect
			.element(
				browserPage
					.getByRole('complementary', { name: 'Evidence detail' })
					.getByText('Tensile testing followed ASTM E8.')
			)
			.toBeInTheDocument();
	});
});
