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
	resolve: (route: string, params?: Record<string, string>) =>
		!route.includes('[')
			? route
			: route.includes('/documents/')
				? `/collections/${params!.id}/documents/${params!.document_id}`
				: route.endsWith('/objectives')
					? `/collections/${params!.id}/objectives`
					: `/collections/${params!.id}/objectives/${params!.objective_id}`
}));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function setFindingPage(findingId = 'finding-1') {
	setPage({
		params: { id: 'col_123', objective_id: 'obj_1' },
		url: new URL(`http://localhost/collections/col_123/objectives/obj_1?finding_id=${findingId}`)
	});
}

async function openAuditTrail() {
	await browserPage.getByText(/Source evidence and paper contributions|原文证据与文献贡献/).click();
}

function request(input: string | URL | Request, init?: RequestInit) {
	const raw =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
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
		variables: ['heat treatment'],
		outcomes: ['yield strength'],
		mechanisms: ['precipitate evolution'],
		constraints: ['LPBF 316L'],
		requested_comparator: 'Compare as-built and heat-treated LPBF 316L.',
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
		document_inputs: [{ document_id: 'paper-1', preparation_fingerprint: 'fingerprint-paper-1' }],
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
		origin: 'system_generated',
		source_analysis_version: null,
		created_by_user_id: null,
		abstention_reason: null,
		abstention_note: null,
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
	collection_id: 'col_123',
	objective_id: 'obj_1',
	analysis_version: 1,
	finding_id: 'finding-1',
	origin: 'system_generated' as const,
	source_analysis_version: null,
	parent_finding_id: null,
	created_by_user_id: null,
	created_at: null,
	statement: 'Annealing was associated with higher tensile strength.',
	factors: ['heat treatment'],
	outcome: 'tensile strength',
	direction: 'increase',
	assertion_strength: 'associative',
	attribution_scope: 'isolated_effect',
	synthesis_status: 'insufficient_confirmation',
	certainty: 0.88,
	display_rank: 0,
	selection_ids: ['selection-1'],
	comparison_group_ids: [],
	mechanisms: [
		{
			source_term: 'annealing',
			relation_type: 'associated_with',
			target_term: 'tensile strength',
			direction: 'increase',
			assertion_strength: 'associative',
			supporting_evidence_ids: ['evidence-mechanism']
		}
	],
	scientific_context: {
		material: [{ name: 'alloy', value: '316L', unit: null }],
		sample: [{ name: 'state', value: 'annealed', unit: null }],
		process: [{ name: 'process', value: 'LPBF', unit: null }],
		test: [{ name: 'method', value: 'tensile test', unit: null }]
	},
	limitations: ['Single paper only.'],
	paper_contributions: [
		{
			document_id: 'paper-1',
			analysis_status: 'analyzed',
			supporting_evidence_ids: ['evidence-1'],
			contradicting_evidence_ids: [],
			context_evidence_ids: ['evidence-mechanism'],
			condition_boundary_evidence_ids: []
		}
	]
};

const evidence = {
	collection_id: 'col_123',
	objective_id: 'obj_1',
	analysis_version: 1,
	evidence_id: 'evidence-1',
	document_id: 'paper-1',
	source_kind: 'text_window',
	source_ref: 'block-7',
	source_excerpt: 'After annealing, tensile strength increased to 620 MPa.',
	page_numbers: [7],
	related_source_refs: [],
	evidence_role: 'direct_result',
	selection_reason: 'Direct result.',
	selection_status: 'extracted',
	changed_variables: [
		{
			name: 'heat treatment',
			baseline_value: 'as-built',
			target_value: 'annealed',
			unit: null
		}
	],
	comparison: {
		baseline_label: 'as-built',
		target_label: 'annealed',
		axis_names: ['heat treatment'],
		comparable: true,
		incomparability_reasons: []
	},
	reported_result: {
		outcome: 'tensile strength',
		value: 620,
		baseline_value: null,
		target_value: null,
		unit: 'MPa',
		direction: 'increase',
		result_text: 'After annealing, tensile strength increased to 620 MPa.'
	},
	attribution_scope: 'isolated_effect',
	scientific_context: {
		material: [{ name: 'alloy', value: '316L', unit: null }],
		sample: [{ name: 'state', value: 'annealed', unit: null }],
		process: [{ name: 'process', value: 'LPBF', unit: null }],
		test: [{ name: 'method', value: 'tensile test', unit: null }]
	},
	resolution_status: 'resolved',
	failure_reason: null,
	confidence: 0.92,
	supports_finding: true,
	eligible_for_finding_authoring: true
};

const mechanismEvidence = {
	...evidence,
	evidence_id: 'evidence-mechanism',
	source_ref: 'block-8',
	source_excerpt: 'Precipitate evolution was associated with increased tensile strength.',
	page_numbers: [8],
	evidence_role: 'mechanism_context',
	selection_reason: 'Mechanism context.',
	changed_variables: [],
	comparison: null,
	reported_result: null,
	attribution_scope: 'not_attributable'
};

function deferredResponse() {
	let resolve!: (response: Response) => void;
	const promise = new Promise<Response>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

function installPublishedResponses(
	response = objectiveResponse(),
	findingItem: Record<string, unknown> | null = finding,
	evidenceItems: Array<Record<string, unknown>> = [evidence, mechanismEvidence]
) {
	fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
		const current = request(input, init);
		if (current.path.endsWith('/documents/profiles')) {
			return jsonResponse({
				collection_id: 'col_123',
				items: [
					{
						document_id: 'paper-1',
						collection_id: 'col_123',
						title: 'Annealing response of LPBF 316L',
						source_filename: 'annealing-316l.pdf',
						doc_type: 'experimental',
						profile_warnings: [],
						confidence: 0.95
					}
				],
				total: 1,
				count: 1,
				summary: { total_documents: 1, doc_type_counts: {}, warnings: [] }
			});
		}
		if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'GET') {
			return jsonResponse(response);
		}
		if (current.path.endsWith('/objectives/obj_1/experiment-analysis')) {
			return jsonResponse({
				selections: [
					{
						selection_id: 'selection-1',
						experiment_id: 'experiment-1',
						experiment_version: 1,
						outcome: 'tensile strength',
						measurement_keys: ['measurement-1'],
						comparison_keys: [],
						missing_context: []
					}
				],
				comparison_groups: [],
				experiments: [],
				findings: []
			});
		}
		if (current.path.endsWith('/objectives/obj_1/findings')) {
			return jsonResponse({
				collection_id: 'col_123',
				objective_id: 'obj_1',
				analysis_version: 1,
				items: findingItem ? [findingItem] : [],
				offset: 0,
				limit: 50,
				total: findingItem ? 1 : 0
			});
		}
		if (current.path.endsWith('/objectives/obj_1/evidence')) {
			return jsonResponse({
				collection_id: 'col_123',
				objective_id: 'obj_1',
				analysis_version: 1,
				finding_id: 'finding-1',
				items: evidenceItems,
				offset: 0,
				limit: 100,
				total: evidenceItems.length
			});
		}
		throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
	});
}

describe('collections/[id]/objectives/[objective_id]/+page.svelte', () => {
	beforeEach(async () => {
		await browserPage.viewport(1280, 900);
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('opens the result overview without selecting the first Finding', async () => {
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		installPublishedResponses();

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Research findings' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(finding.statement)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('region', { name: 'Finding details' }))
			.not.toBeInTheDocument();
	});

	it('creates a new Finding from a fixed experiment selection and reloads its version', async () => {
		let publishedVersion = 1;
		let submitted: Record<string, unknown> | null = null;
		const manualFinding = {
			...finding,
			analysis_version: 2,
			finding_id: 'finding-manual-1',
			statement: 'Annealing is associated with higher tensile strength in the reported test.',
			display_rank: 1,
			origin: 'human_authored',
			source_analysis_version: 1,
			parent_finding_id: null,
			created_by_user_id: 'user-researcher',
			created_at: '2026-09-01T00:00:00+00:00'
		};

		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			const params = new URLSearchParams(current.search);
			if (current.path.endsWith('/documents'))
				return jsonResponse({
					items: [{ document_id: 'paper-1', original_filename: 'annealing.pdf', status: 'ready' }],
					count: 1
				});
			if (current.path.endsWith('/scope'))
				return jsonResponse({
					recommended_document_ids: ['paper-1'],
					review_document_ids: [],
					excluded_document_ids: [],
					decisions: [],
					counts: { likely_relevant: 1, needs_inspection: 0, confidently_out_of_scope: 0 }
				});
			if (current.path.endsWith('/documents/profiles')) {
				return jsonResponse({
					items: [
						{
							document_id: 'paper-1',
							title: 'Annealing response of LPBF 316L',
							source_filename: 'annealing.pdf'
						}
					],
					total: 1
				});
			}
			if (current.path.endsWith('/objectives/obj_1/analysis')) {
				return jsonResponse(
					objectiveResponse({
						objective: objective({
							active_analysis_version: publishedVersion,
							published_analysis_version: publishedVersion
						}),
						active_analysis: analysisState('succeeded', publishedVersion),
						published_analysis: analysisState('succeeded', publishedVersion)
					})
				);
			}
			if (current.path.endsWith('/objectives/obj_1/experiment-analysis')) {
				return jsonResponse({
					selections: [
						{
							selection_id: 'selection-1',
							experiment_id: 'experiment-1',
							experiment_version: 1,
							outcome: 'tensile strength',
							measurement_keys: ['measurement-1'],
							comparison_keys: [],
							missing_context: []
						}
					],
					comparison_groups: [],
					experiments: [],
					findings: []
				});
			}
			if (current.path.endsWith('/objectives/obj_1/findings') && current.method === 'POST') {
				submitted = JSON.parse(String(init?.body ?? '{}'));
				publishedVersion = 2;
				return jsonResponse({
					analysis: analysisState('succeeded', 2, {
						origin: 'hybrid',
						source_analysis_version: 1,
						created_by_user_id: 'user-researcher'
					}),
					finding: manualFinding,
					abstention_reason: null
				});
			}
			if (current.path.endsWith('/objectives/obj_1/findings')) {
				return jsonResponse({
					items:
						publishedVersion === 2
							? [{ ...finding, analysis_version: 2 }, manualFinding]
							: [finding],
					total: publishedVersion === 2 ? 2 : 1
				});
			}
			if (current.path.endsWith('/objectives/obj_1/evidence')) {
				const findingId = params.get('finding_id');
				return jsonResponse({
					items: [{ ...evidence, analysis_version: publishedVersion }],
					total: 1,
					finding_id: findingId
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
		});

		render(Page);
		await browserPage.getByRole('button', { name: /Create finding|新建研究发现/ }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: '从实验选择创建 Finding' }))
			.toBeInTheDocument();
		await browserPage.getByLabelText(/selection-1/).click();
		await browserPage.getByRole('button', { name: '创建 Finding' }).click();
		expect(submitted).toMatchObject({
			source_analysis_version: 1,
			selection_ids: ['selection-1'],
			comparison_group_ids: []
		});
	});

	it('keeps experiment-backed Finding detail free of evidence review actions', async () => {
		setFindingPage();
		installPublishedResponses();
		const baseFetch = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/objectives/obj_1/findings')) {
				return jsonResponse({
					items: [{ ...finding, analysis_version: 1 }],
					total: 1,
					evidence_reviews: {
						'finding-1': {
							needs_review: true,
							evidence_replacements: { 'evidence-1': 'evidence-new' }
						}
					}
				});
			}
			return baseFetch(input, init);
		});
		render(Page);
		await expect
			.element(browserPage.getByRole('region', { name: 'Evidence updated, review required' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Review with Agent' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: 'Revise conclusion', exact: true }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '基于此 Finding 创建新版本' }))
			.not.toBeInTheDocument();
	});

	it('confirms a candidate and queues analysis on the same Objective', async () => {
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		const requests: Array<{ path: string; method: string }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			requests.push({ path: current.path, method: current.method });
			if (current.path.endsWith('/documents'))
				return jsonResponse({
					items: [{ document_id: 'paper-1', original_filename: 'annealing.pdf', status: 'ready' }],
					count: 1
				});
			if (current.path.endsWith('/scope'))
				return jsonResponse({
					recommended_document_ids: ['paper-1'],
					review_document_ids: [],
					excluded_document_ids: [],
					decisions: [],
					counts: { likely_relevant: 1, needs_inspection: 0, confidently_out_of_scope: 0 }
				});
			if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'GET') {
				return jsonResponse(
					objectiveResponse({
						objective: objective({
							confirmation_status: 'candidate',
							active_analysis_version: null,
							published_analysis_version: null
						}),
						active_analysis: null,
						published_analysis: null
					})
				);
			}
			if (current.path.endsWith('/analysis') && current.method === 'POST') {
				return jsonResponse(
					objectiveResponse({
						objective: objective({ published_analysis_version: null }),
						active_analysis: analysisState('queued', 1, {
							progress_message: 'Objective analysis is queued.'
						}),
						published_analysis: null
					})
				);
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await expect
			.element(
				browserPage.getByRole('button', { name: /Analyze selected papers|使用所选文献分析/ })
			)
			.toBeVisible();
		await browserPage
			.getByRole('button', { name: /Analyze selected papers|使用所选文献分析/ })
			.click();

		await expect
			.element(browserPage.getByText('Objective analysis is queued.'))
			.toBeInTheDocument();
		expect(requests).toContainEqual({
			path: '/api/v1/collections/col_123/objectives/obj_1/analysis',
			method: 'POST'
		});
		expect(requests.filter((item) => item.method === 'POST')).toHaveLength(1);
	});

	it('keeps the published Finding readable while a failed retry is shown', async () => {
		setFindingPage();
		const failed = objectiveResponse({
			objective: objective({ active_analysis_version: 2, published_analysis_version: 1 }),
			active_analysis: analysisState('failed', 2, {
				model_name: 'model-2',
				error_code: 'provider_error',
				error_message: 'Evidence extraction failed.'
			}),
			published_analysis: analysisState('succeeded', 1)
		});
		installPublishedResponses(failed);

		render(Page);

		await expect.element(browserPage.getByText(/Analysis failed|本次分析失败/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Evidence analysis did not complete.'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(finding.statement).first()).toBeInTheDocument();
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('blockquote').filter({ hasText: evidence.source_excerpt }))
			.toHaveTextContent(evidence.source_excerpt);
		await expect
			.element(browserPage.getByRole('button', { name: /Retry analysis|重试分析/ }))
			.toBeInTheDocument();
	});

	it('labels historical published analyses whose model was not recorded', async () => {
		installPublishedResponses(
			objectiveResponse({
				published_analysis: analysisState('succeeded', 1, { model_name: null })
			})
		);

		render(Page);

		await expect.element(browserPage.getByText(finding.statement).first()).toBeInTheDocument();
	});

	it('renders one Finding with relation, Context, and an exact source jump', async () => {
		setFindingPage();
		installPublishedResponses();

		render(Page);

		await expect
			.element(browserPage.getByRole('region', { name: 'Finding details' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('相关联', { exact: true })).toBeInTheDocument();
		await expect.element(browserPage.getByText('associated_with')).not.toBeInTheDocument();
		await browserPage.getByText(/Analysis and experiment versions|分析与实验版本/).click();
		await expect.element(browserPage.getByText(/Experiment version\s*v1|实验版本\s*v1/)).toHaveTextContent('v1');
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('link', { name: 'Annealing response of LPBF 316L · p.7' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Annealing response of LPBF 316L · p.8' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('blockquote').filter({ hasText: evidence.source_excerpt }))
			.toHaveTextContent(evidence.source_excerpt);
		await expect
			.element(browserPage.getByRole('link', { name: /Open source|打开原文/ }).first())
			.toHaveAttribute(
				'href',
				'/collections/col_123/documents/paper-1?view=parsed-paper&evidence_id=evidence-1&source_ref=block-7&quote=After+annealing%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1%3Ffinding_id%3Dfinding-1&page=7'
			);
		expect(
			fetchMock.mock.calls.some(([input]) => /\/findings\/finding-1(?:\?|$)/.test(String(input)))
		).toBe(false);
		for (const kind of ['feedback', 'curation']) {
			expect(
				fetchMock.mock.calls.some(([input]) =>
					String(input).includes(`/findings/finding-1/${kind}`)
				)
			).toBe(false);
		}
	});

	it('downloads the published Finding dataset with the selected filters', async () => {
		setFindingPage();
		installPublishedResponses();
		const installed = fetchMock.getMockImplementation()!;
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/finding-dataset')) {
				return new Response('{"messages":[]}', {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				});
			}
			return installed(input, init);
		});

		render(Page);
		await browserPage.getByRole('button', { name: /Export data|导出数据/ }).click();
		await browserPage.getByText(/Finding dataset export|研究发现数据集导出/).click();
		await browserPage.getByLabelText(/Label status|标注状态/).selectOptions('gold');
		await browserPage.getByLabelText(/Dataset use|数据用途/).selectOptions('training_ready');
		await browserPage.getByRole('button', { name: 'JSON', exact: true }).click();

		const datasetCall = fetchMock.mock.calls.find(([input]) =>
			String(input).includes('/finding-dataset')
		);
		expect(datasetCall).toBeDefined();
		expect(String(datasetCall?.[0])).toContain('label_status=gold');
		expect(String(datasetCall?.[0])).toContain('dataset_use_status=training_ready');
		expect(String(datasetCall?.[0])).toContain('format=json');
	});

	it('renders a categorical result transition and qualitative direction', async () => {
		setFindingPage();
		const phaseFinding = {
			...finding,
			statement: 'Heat treatment was associated with a phase-composition change.',
			factors: ['heat treatment'],
			outcome: 'phase composition',
			direction: 'changed',
			mechanisms: []
		};
		const phaseEvidence = {
			...evidence,
			source_excerpt: 'The phase changed from alpha-prime to alpha+beta after annealing.',
			reported_result: {
				outcome: 'phase composition',
				value: 'alpha+beta',
				baseline_value: 'alpha-prime',
				target_value: 'alpha+beta',
				unit: null,
				direction: 'changed',
				result_text: 'Phase composition changed from alpha-prime to alpha+beta.'
			}
		};
		installPublishedResponses(objectiveResponse(), phaseFinding, [phaseEvidence]);

		render(Page);

		await expect.element(browserPage.getByText(phaseFinding.statement).first()).toBeInTheDocument();
	});

	it('shows completed scientific abstention when no comparable Finding was formed', async () => {
		installPublishedResponses(objectiveResponse(), null, []);

		render(Page);

		await expect
			.element(
				browserPage.getByText(
					/The current evidence has not produced a finding|当前证据尚未形成研究发现/
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText(/Analysis failed|本次分析失败/))
			.not.toBeInTheDocument();
	});

	it('shows retained Evidence gaps when no Finding is formed', async () => {
		installPublishedResponses(
			objectiveResponse({
				evidence_review: {
					total_evidence_count: 3,
					result_count: 2,
					comparable_evidence_count: 0,
					gap_count: 3,
					omitted_gap_count: 0,
					status_counts: {
						descriptive: 1,
						needs_context: 1,
						extraction_failed: 1
					},
					gaps: [
						{
							evidence_id: 'gap-1',
							document_id: 'paper-1',
							source_kind: 'text_window',
							source_ref: 'results-7',
							page_numbers: [7],
							evidence_status: 'needs_context',
							reason: '缺少样品状态，不能判断是否可以比较。',
							outcome: 'yield strength',
							source_excerpt: 'Yield strength increased after treatment.'
						}
					]
				}
			}),
			null,
			[]
		);

		render(Page);

		const coverage = browserPage.getByRole('group', { name: /Evidence coverage|证据覆盖/ });
		await expect.element(coverage).not.toHaveAttribute('open');
		await expect
			.element(browserPage.getByText(/^Evidence coverage|^证据覆盖/))
			.toHaveTextContent(/3 records.*3 to review|3 条.*3 条待核查/);
		await expect
			.element(browserPage.getByText('缺少样品状态，不能判断是否可以比较。'))
			.not.toBeVisible();
		await expect
			.element(
				browserPage.getByText(
					/The current evidence has not produced a finding|当前证据尚未形成研究发现/
				)
			)
			.toBeVisible();
		await browserPage.getByText(/^Evidence coverage|^证据覆盖/).click();
		await expect.element(coverage).toHaveAttribute('open');
		await expect.element(browserPage.getByText('3 source records · 2 results')).toBeVisible();
		await expect
			.element(browserPage.getByText('Missing context', { exact: true }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('缺少样品状态，不能判断是否可以比较。'))
			.toBeInTheDocument();
		await expect
			.element(
				browserPage
					.getByRole('blockquote')
					.filter({ hasText: 'Yield strength increased after treatment.' })
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Open source' }))
			.toHaveAttribute(
				'href',
				'/collections/col_123/documents/paper-1?view=parsed-paper&evidence_id=gap-1&source_ref=results-7&quote=Yield+strength+increased+after+treatment.&return_to=%2Fcollections%2Fcol_123%2Fobjectives%2Fobj_1&page=7'
			);
		await expect
			.element(
				browserPage.getByText(
					/The current evidence has not produced a finding|当前证据尚未形成研究发现/
				)
			)
			.toBeInTheDocument();
	});

	it('loads every Finding and selected Evidence page', async () => {
		const secondFinding = {
			...finding,
			finding_id: 'finding-2',
			statement: 'A Finding returned on the second page.'
		};
		const contextEvidence = {
			...evidence,
			evidence_id: 'evidence-2',
			evidence_role: 'condition_context',
			source_excerpt: 'The specimen was tested at room temperature.'
		};
		const pagedFinding = {
			...finding,
			paper_contributions: [
				{
					...finding.paper_contributions[0],
					context_evidence_ids: ['evidence-2']
				}
			]
		};

		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			const params = new URLSearchParams(current.search);
			if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'GET') {
				return jsonResponse(objectiveResponse());
			}
			if (current.path.endsWith('/objectives/obj_1/findings')) {
				const offset = Number(params.get('offset'));
				return jsonResponse({
					items: offset === 0 ? [pagedFinding] : [secondFinding],
					total: 2
				});
			}
			if (current.path.endsWith('/objectives/obj_1/evidence')) {
				const offset = Number(params.get('offset'));
				return jsonResponse({
					items: offset === 0 ? [evidence] : [contextEvidence],
					total: 2
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('button', { name: /A Finding returned on the second page/ }))
			.toBeInTheDocument();
		await browserPage
			.getByRole('button', { name: /Annealing was associated with higher tensile strength/ })
			.click();
		await expect.element(browserPage.getByText(contextEvidence.source_excerpt)).toBeInTheDocument();
		expect(
			fetchMock.mock.calls.some(([input]) =>
				String(input).includes('/findings?analysis_version=1&offset=1&limit=200')
			)
		).toBe(true);
		expect(
			fetchMock.mock.calls.some(([input]) =>
				String(input).includes(
					'/evidence?analysis_version=1&finding_id=finding-1&offset=1&limit=500'
				)
			)
		).toBe(true);
	});

	it('discards stale Evidence responses after rapid selection', async () => {
		const slowFinding = {
			...finding,
			finding_id: 'finding-2',
			statement: 'A slow Finding response.',
			factors: ['slow factor'],
			paper_contributions: [
				{
					...finding.paper_contributions[0],
					supporting_evidence_ids: ['evidence-2']
				}
			]
		};
		const latestFinding = {
			...finding,
			finding_id: 'finding-3',
			statement: 'The latest selected Finding.',
			factors: ['latest factor'],
			paper_contributions: [
				{
					...finding.paper_contributions[0],
					supporting_evidence_ids: ['evidence-3']
				}
			]
		};
		const slowEvidence = {
			...evidence,
			evidence_id: 'evidence-2',
			source_excerpt: 'This stale Evidence must not replace the current selection.'
		};
		const latestEvidence = {
			...evidence,
			evidence_id: 'evidence-3',
			source_excerpt: 'This Evidence belongs to the latest selected Finding.'
		};
		const slowEvidenceResponse = deferredResponse();

		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'GET') {
				return jsonResponse(objectiveResponse());
			}
			if (current.path.endsWith('/objectives/obj_1/findings')) {
				return jsonResponse({
					collection_id: 'col_123',
					objective_id: 'obj_1',
					analysis_version: 1,
					items: [finding, slowFinding, latestFinding],
					offset: 0,
					limit: 50,
					total: 3
				});
			}
			if (current.path.endsWith('/objectives/obj_1/evidence')) {
				const findingId = new URLSearchParams(current.search).get('finding_id');
				if (findingId === 'finding-2') return slowEvidenceResponse.promise;
				const item = findingId === 'finding-3' ? latestEvidence : evidence;
				return jsonResponse({ items: [item], total: 1 });
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
		});

		render(Page);
		await browserPage
			.getByRole('button', { name: /Annealing was associated with higher tensile strength/ })
			.click();
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(evidence.source_excerpt);
		setFindingPage('finding-2');
		setFindingPage('finding-3');
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(latestEvidence.source_excerpt);

		slowEvidenceResponse.resolve(jsonResponse({ items: [slowEvidence], total: 1 }));
		await expect
			.element(browserPage.getByRole('blockquote'))
			.not.toHaveTextContent(slowEvidence.source_excerpt);
	});

	it('discards stale Evidence responses after a new analysis version is published', async () => {
		const slowFinding = {
			...finding,
			finding_id: 'finding-v1-slow',
			statement: 'A stale version 1 Finding.',
			paper_contributions: [
				{
					...finding.paper_contributions[0],
					supporting_evidence_ids: ['evidence-v1-slow']
				}
			]
		};
		const publishedFinding = {
			...finding,
			analysis_version: 2,
			finding_id: 'finding-v2',
			statement: 'The published version 2 Finding.',
			paper_contributions: [
				{
					...finding.paper_contributions[0],
					supporting_evidence_ids: ['evidence-v2']
				}
			]
		};
		const slowEvidence = {
			...evidence,
			evidence_id: 'evidence-v1-slow',
			source_excerpt: 'Stale version 1 source excerpt.'
		};
		const publishedEvidence = {
			...evidence,
			analysis_version: 2,
			evidence_id: 'evidence-v2',
			source_excerpt: 'Current version 2 source excerpt.'
		};
		const slowEvidenceResponse = deferredResponse();
		let analysisStarted = false;

		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			const params = new URLSearchParams(current.search);
			if (current.path.endsWith('/documents'))
				return jsonResponse({
					items: [{ document_id: 'paper-1', original_filename: 'annealing.pdf', status: 'ready' }],
					count: 1
				});
			if (current.path.endsWith('/scope'))
				return jsonResponse({
					recommended_document_ids: ['paper-1'],
					review_document_ids: [],
					excluded_document_ids: [],
					decisions: [],
					counts: { likely_relevant: 1, needs_inspection: 0, confidently_out_of_scope: 0 }
				});
			if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'POST') {
				analysisStarted = true;
				return jsonResponse(
					objectiveResponse({
						objective: objective({ active_analysis_version: 2 }),
						active_analysis: analysisState('queued', 2),
						published_analysis: analysisState('succeeded', 1)
					})
				);
			}
			if (current.path.endsWith('/objectives/obj_1/analysis') && current.method === 'GET') {
				if (!analysisStarted) return jsonResponse(objectiveResponse());
				return jsonResponse(
					objectiveResponse({
						objective: objective({
							active_analysis_version: 2,
							published_analysis_version: 2
						}),
						active_analysis: analysisState('succeeded', 2),
						published_analysis: analysisState('succeeded', 2)
					})
				);
			}
			if (current.path.endsWith('/objectives/obj_1/analysis/status')) {
				return jsonResponse(analysisState('succeeded', 2));
			}
			if (current.path.endsWith('/objectives/obj_1/findings')) {
				const version = Number(params.get('analysis_version'));
				return jsonResponse({
					items: version === 2 ? [publishedFinding] : [finding, slowFinding],
					total: version === 2 ? 1 : 2
				});
			}
			if (current.path.endsWith('/objectives/obj_1/evidence')) {
				const findingId = params.get('finding_id');
				if (findingId === 'finding-v1-slow') return slowEvidenceResponse.promise;
				return jsonResponse({
					items: findingId === 'finding-v2' ? [publishedEvidence] : [evidence],
					total: 1
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}${current.search}`);
		});

		render(Page);
		await browserPage
			.getByRole('button', { name: /Annealing was associated with higher tensile strength/ })
			.click();
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(evidence.source_excerpt);
		setFindingPage('finding-v1-slow');
		await browserPage.getByRole('button', { name: /Re-analyze|重新分析/ }).click();
		setPage({
			params: { id: 'col_123', objective_id: 'obj_1' },
			url: new URL('http://localhost/collections/col_123/objectives/obj_1')
		});
		await browserPage
			.getByRole('button', { name: /Analyze selected papers|使用所选文献分析/ })
			.click();
		await new Promise((resolve) => setTimeout(resolve, 2700));
		await expect
			.element(browserPage.getByRole('button', { name: /The published version 2 Finding/ }))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: /The published version 2 Finding/ }).click();
		await openAuditTrail();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(publishedEvidence.source_excerpt);

		slowEvidenceResponse.resolve(jsonResponse({ items: [slowEvidence], total: 1 }));
		await expect
			.element(browserPage.getByRole('blockquote'))
			.not.toHaveTextContent(slowEvidence.source_excerpt);
	});
});
