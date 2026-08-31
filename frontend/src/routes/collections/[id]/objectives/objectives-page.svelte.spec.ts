import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

type ObjectivesPageState = {
	params: { id: string };
	url: URL;
};

const { pageStore, setPage, goto, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: ObjectivesPageState) => void>();
	let current: ObjectivesPageState = {
		params: { id: 'col_123' },
		url: new URL('http://localhost/collections/col_123/objectives')
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

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.mock('$app/navigation', () => ({ goto }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

function request(input: string | URL | Request, init?: RequestInit) {
	const raw =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return {
		path: new URL(raw, 'http://localhost').pathname,
		method: input instanceof Request ? input.method : (init?.method ?? 'GET')
	};
}

function objective(overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_heat_strength',
		question: 'How does heat treatment affect strength?',
		material_scope: ['316L stainless steel'],
		variables: ['heat treatment'],
		outcomes: ['yield strength'],
		mechanisms: ['precipitate evolution'],
		constraints: ['LPBF 316L'],
		requested_comparator: 'Compare treated and untreated samples.',
		seed_document_ids: ['paper-1', 'paper-2'],
		excluded_document_ids: [],
		confidence: 0.82,
		reason: null,
		confirmation_status: 'candidate',
		active_analysis_version: null,
		published_analysis_version: null,
		created_at: null,
		updated_at: null,
		...overrides
	};
}

function analysisState(status: 'queued' | 'running' | 'succeeded' | 'failed') {
	return {
		collection_id: 'col_123',
		objective_id: 'obj_heat_strength',
		analysis_version: 1,
		document_inputs: [
			{ document_id: 'paper-1', preparation_fingerprint: 'fingerprint-paper-1' },
			{ document_id: 'paper-2', preparation_fingerprint: 'fingerprint-paper-2' }
		],
		pipeline_version: 'objective-analysis-v1',
		model_name: null,
		prompt_versions: {},
		status,
		phase: status === 'running' ? 'evidence_extraction' : status,
		processed_document_count: status === 'running' ? 2 : 0,
		total_document_count: 6,
		current_document_id: status === 'running' ? 'paper-2' : null,
		progress_message: status === 'running' ? 'Extracting evidence.' : null,
		error_code: null,
		error_message: null,
		created_at: null,
		started_at: null,
		completed_at: null
	};
}

function scopePreview({
	recommended = ['paper-1', 'paper-3'],
	review = [],
	excluded = []
}: {
	recommended?: string[];
	review?: string[];
	excluded?: string[];
} = {}) {
	const decisions = [
		...recommended.map((documentId) => ({
			document_id: documentId,
			classification: 'likely_relevant',
			reason: 'mapped_research_scope',
			doc_role: 'experimental',
			map_status: 'sufficient',
			map_limitations: [],
			support_basis: [`relationship-${documentId}`],
			is_seed: ['paper-1', 'paper-2'].includes(documentId)
		})),
		...review.map((documentId) => ({
			document_id: documentId,
			classification: 'needs_inspection',
			reason: 'paper_map_incomplete',
			doc_role: 'review',
			map_status: 'insufficient_map',
			map_limitations: ['Outcome coverage is incomplete.'],
			support_basis: [],
			is_seed: ['paper-1', 'paper-2'].includes(documentId)
		})),
		...excluded.map((documentId) => ({
			document_id: documentId,
			classification: 'confidently_out_of_scope',
			reason: 'no_mapped_scope_match',
			doc_role: 'experimental',
			map_status: 'sufficient',
			map_limitations: [],
			support_basis: [],
			is_seed: ['paper-1', 'paper-2'].includes(documentId)
		}))
	];
	return {
		collection_id: 'col_123',
		objective_id: 'obj_heat_strength',
		counts: {
			likely_relevant: recommended.length,
			needs_inspection: review.length,
			confidently_out_of_scope: excluded.length
		},
		recommended_document_ids: recommended,
		review_document_ids: review,
		excluded_document_ids: excluded,
		decisions,
		support_is_evidence: false
	};
}

describe('collections/[id]/objectives/+page.svelte', () => {
	beforeEach(() => {
		setPage({
			params: { id: 'col_123' },
			url: new URL('http://localhost/collections/col_123/objectives')
		});
		goto.mockReset();
		fetchMock.mockReset();
	});

	it('shows an explicit empty state before Objective candidates exist', async () => {
		fetchMock.mockResolvedValue(jsonResponse({ collection_id: 'col_123', objectives: [] }));

		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: '研究目标' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: '没有可供确认的研究目标' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText(/不表示目标级证据分析已经完成/)).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '检查文献' }))
			.toHaveAttribute('href', '/collections/col_123/documents');
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('uses the recommended paper scope without opening the adjustment dialog', async () => {
		const requests: Array<{ path: string; method: string }> = [];
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			requests.push(current);
			if (current.path.endsWith('/documents') && current.method === 'GET') {
				return jsonResponse({
					items: [
						{
							document_id: 'paper-1',
							original_filename: 'paper-1.pdf',
							status: 'ready',
							size_bytes: 100,
							created_at: '2026-08-27T00:00:00Z'
						},
						{
							document_id: 'paper-2',
							original_filename: 'paper-2.pdf',
							status: 'ready',
							size_bytes: 100,
							created_at: '2026-08-27T00:00:00Z'
						},
						{
							document_id: 'paper-3',
							original_filename: 'unrelated-paper.pdf',
							status: 'ready',
							size_bytes: 100,
							created_at: '2026-08-27T00:00:00Z'
						}
					]
				});
			}
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({ collection_id: 'col_123', objectives: [objective()] });
			}
			if (current.path.endsWith('/obj_heat_strength/scope') && current.method === 'GET') {
				return jsonResponse(scopePreview());
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({ confirmation_status: 'confirmed', active_analysis_version: 1 }),
					active_analysis: null,
					published_analysis: null,
					warnings: []
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await expect
			.element(
				browserPage.getByRole('heading', { name: 'How does heat treatment affect strength?' })
			)
			.toBeInTheDocument();
		await expect.element(browserPage.getByRole('checkbox')).not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: '确认并分析' }).click();
		await expect
			.element(browserPage.getByRole('dialog', { name: '确认分析论文范围' }))
			.not.toBeInTheDocument();

		await vi.waitFor(() => {
			expect(requests).toContainEqual({
				path: '/api/v1/collections/col_123/objectives/obj_heat_strength/analysis',
				method: 'POST'
			});
			expect(requests.filter((item) => item.method === 'POST')).toHaveLength(1);
			expect(goto).toHaveBeenCalledWith('/collections/col_123/objectives/obj_heat_strength');
		});
		const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
		expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
			document_ids: ['paper-1', 'paper-3']
		});
	});

	it('edits only one Objective paper scope with searchable bounded results', async () => {
		const secondObjective = objective({
			objective_id: 'obj_heat_ductility',
			question: 'How does heat treatment affect ductility?',
			seed_document_ids: ['paper-2']
		});
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/documents') && current.method === 'GET') {
				return jsonResponse({
					items: [
						{ document_id: 'paper-1', original_filename: 'strength.pdf', status: 'ready' },
						{ document_id: 'paper-2', original_filename: 'ductility.pdf', status: 'ready' },
						{ document_id: 'paper-3', original_filename: 'laser-review.pdf', status: 'ready' }
					]
				});
			}
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [objective(), secondObjective]
				});
			}
			if (current.path.endsWith('/obj_heat_strength/scope') && current.method === 'GET') {
				return jsonResponse(
					scopePreview({ recommended: ['paper-1', 'paper-2'], review: ['paper-3'] })
				);
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'POST') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective(),
					active_analysis: null,
					published_analysis: null,
					warnings: []
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await browserPage.getByRole('button', { name: '调整范围' }).first().click();
		await browserPage.getByLabelText('搜索可用论文').fill('laser');
		await expect.element(browserPage.getByText('laser-review.pdf')).toBeInTheDocument();
		await expect.element(browserPage.getByText('待人工确认', { exact: true })).toBeInTheDocument();
		await expect.element(browserPage.getByText('strength.pdf')).not.toBeInTheDocument();
		await browserPage.getByRole('checkbox', { name: 'laser-review.pdf' }).click();
		await expect.element(browserPage.getByText('已选择 3 篇论文')).toBeInTheDocument();
		await browserPage.getByRole('button', { name: '使用 3 篇论文开始分析' }).click();

		await vi.waitFor(() => expect(goto).toHaveBeenCalled());
		const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
		expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
			document_ids: ['paper-1', 'paper-2', 'paper-3']
		});
	});

	it('uses failed analysis frozen inputs as the retry scope', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/documents') && current.method === 'GET') {
				return jsonResponse({
					items: [
						{ document_id: 'paper-1', original_filename: 'seed.pdf', status: 'ready' },
						{ document_id: 'paper-3', original_filename: 'frozen.pdf', status: 'ready' }
					]
				});
			}
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [objective({ confirmation_status: 'confirmed', active_analysis_version: 1 })]
				});
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({ confirmation_status: 'confirmed', active_analysis_version: 1 }),
					active_analysis: {
						...analysisState('failed'),
						document_inputs: [
							{ document_id: 'paper-3', preparation_fingerprint: 'fingerprint-paper-3' }
						]
					},
					published_analysis: null,
					warnings: []
				});
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'POST') {
				return jsonResponse({ collection_id: 'col_123', warnings: [] });
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);
		await browserPage.getByRole('button', { name: '重试分析' }).click();
		await expect
			.element(browserPage.getByRole('dialog', { name: '确认分析论文范围' }))
			.not.toBeInTheDocument();

		await vi.waitFor(() => expect(goto).toHaveBeenCalled());
		const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
		expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({ document_ids: ['paper-3'] });
	});

	it('requires explicit selection for a seedless Objective', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/documents') && current.method === 'GET') {
				return jsonResponse({
					items: [{ document_id: 'paper-1', original_filename: 'available.pdf', status: 'ready' }]
				});
			}
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [objective({ seed_document_ids: [] })]
				});
			}
			if (current.path.endsWith('/obj_heat_strength/scope') && current.method === 'GET') {
				return jsonResponse(scopePreview({ recommended: [], review: ['paper-1'] }));
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);

		await browserPage.getByRole('button', { name: '确认并分析' }).click();
		await expect.element(browserPage.getByText('已选择 0 篇论文')).toBeInTheDocument();
		await expect.element(browserPage.getByText('请选择至少一篇论文。')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '选择论文后开始分析' }))
			.toBeDisabled();
		await browserPage.getByRole('checkbox', { name: 'available.pdf' }).click();
		await expect
			.element(browserPage.getByRole('button', { name: '使用 1 篇论文开始分析' }))
			.toBeEnabled();
	});

	it('shows active analysis progress instead of offering confirmation again', async () => {
		fetchMock.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
			const current = request(input, init);
			if (current.path.endsWith('/objectives') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objectives: [
						objective({
							confirmation_status: 'confirmed',
							active_analysis_version: 1
						})
					]
				});
			}
			if (current.path.endsWith('/obj_heat_strength/analysis') && current.method === 'GET') {
				return jsonResponse({
					collection_id: 'col_123',
					objective: objective({
						confirmation_status: 'confirmed',
						active_analysis_version: 1
					}),
					active_analysis: analysisState('running'),
					published_analysis: null,
					warnings: []
				});
			}
			throw new Error(`unexpected request: ${current.method} ${current.path}`);
		});

		render(Page);

		await expect
			.element(browserPage.getByRole('progressbar', { name: '研究目标分析进度' }))
			.toHaveAttribute('aria-valuenow', '33');
		await expect.element(browserPage.getByText('论文进度 2 / 6')).toBeInTheDocument();
		await expect.element(browserPage.getByText('正在逐篇提取相关证据')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '确认并分析' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '查看状态' }))
			.not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'How does heat treatment affect strength?' }))
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_heat_strength');
	});

	it('shows the published version without a second result lookup', async () => {
		fetchMock.mockImplementation(async () => {
			return jsonResponse({
				collection_id: 'col_123',
				objectives: [
					objective({
						confirmation_status: 'confirmed',
						active_analysis_version: 2,
						published_analysis_version: 2
					})
				]
			});
		});

		render(Page);

		await expect.element(browserPage.getByText('结果 v2')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '查看 Findings' }))
			.toHaveAttribute('href', '/collections/col_123/objectives/obj_heat_strength');
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('prioritizes resumed work and paginates lower-ranked candidates', async () => {
		const candidates = Array.from({ length: 8 }, (_, index) =>
			objective({
				objective_id: `obj-${index + 1}`,
				question: `Candidate question ${index + 1}?`,
				seed_document_ids: [`paper-${index + 1}`]
			})
		);
		const published = objective({
			objective_id: 'obj-published',
			question: 'Published research question?',
			confirmation_status: 'confirmed',
			active_analysis_version: 2,
			published_analysis_version: 2
		});
		fetchMock.mockResolvedValue(
			jsonResponse({ collection_id: 'col_123', objectives: [...candidates, published] })
		);

		render(Page);

		await expect.element(browserPage.getByText('Published research question?')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Candidate question 5?')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Objectives 1–5 of 9')).toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Next' }).click();
		await expect.element(browserPage.getByText('Candidate question 5?')).toBeInTheDocument();
		await expect.element(browserPage.getByText(/Objectives 6/)).toBeInTheDocument();
		await browserPage.getByLabelText('搜索研究目标').fill('Candidate question');
		await expect.element(browserPage.getByText('Objectives 1–5 of 8')).toBeInTheDocument();
		await expect.element(browserPage.getByText('Candidate question 1?')).toBeInTheDocument();
	});

	it('filters the complete Objective list by scientific text and workflow status', async () => {
		const candidates = Array.from({ length: 7 }, (_, index) =>
			objective({
				objective_id: `obj-candidate-${index + 1}`,
				question: `Candidate question ${index + 1}?`,
				material_scope: index === 5 ? ['Ti-6Al-4V'] : ['316L'],
				outcomes: index === 5 ? ['fatigue life'] : ['yield strength']
			})
		);
		const published = objective({
			objective_id: 'obj-published-fatigue',
			question: 'How does heat treatment affect fatigue life?',
			material_scope: ['Ti-6Al-4V'],
			outcomes: ['fatigue life'],
			confirmation_status: 'confirmed',
			active_analysis_version: 2,
			published_analysis_version: 2
		});
		fetchMock.mockResolvedValue(
			jsonResponse({ collection_id: 'col_123', objectives: [...candidates, published] })
		);

		render(Page);
		await browserPage.getByLabelText('搜索研究目标').fill('fatigue');
		await browserPage.getByLabelText('分析状态').selectOptions('published');

		await expect
			.element(browserPage.getByText('How does heat treatment affect fatigue life?'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Candidate question 6?')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('找到 1 个研究目标')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('button', { name: '下一页' }))
			.not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: '清除筛选' }).click();
		await expect.element(browserPage.getByText('Candidate question 1?')).toBeInTheDocument();
	});
});
