import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { authState } from '../../../../_shared/auth';

type GoalPageState = {
	params: { id: string; goal_id: string };
	url: URL;
};

const { pageStore, setPage, fetchMock } = vi.hoisted(() => {
	const subscribers = new Set<(value: GoalPageState) => void>();
	let current: GoalPageState = {
		params: { id: 'col_123', goal_id: 'goal_1' },
		url: new URL('http://localhost/collections/col_123/goals/goal_1')
	};
	return {
		pageStore: {
			subscribe(run: (value: GoalPageState) => void) {
				run(current);
				subscribers.add(run);
				return () => subscribers.delete(run);
			}
		},
		setPage(next: GoalPageState) {
			current = next;
			for (const run of subscribers) run(next);
		},
		fetchMock: vi.fn()
	};
});

vi.mock('$app/stores', () => ({ page: pageStore }));
vi.stubGlobal('fetch', fetchMock);

const Page = (await import('./+page.svelte')).default;

let analysisResponse: Record<string, unknown>;
let feedbackResponse: Record<string, unknown>[];
let curationResponse: Record<string, unknown>[];

function jsonResponse(body: unknown, status = 200) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function requestPath(input: string | URL | Request) {
	const rawUrl =
		typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
	return new URL(rawUrl, 'http://localhost').pathname;
}

function requestMethod(input: string | URL | Request, init?: RequestInit) {
	return input instanceof Request ? input.method : (init?.method ?? 'GET');
}

function requestBody(init?: RequestInit) {
	return JSON.parse((init?.body as string | undefined) ?? '{}') as Record<string, unknown>;
}

function researchUnderstanding() {
	const firstFinding = {
		finding_id: 'finding_internal_1',
		claim_id: 'claim_internal_1',
		title: 'preheating temperature -> ductility',
		statement:
			'Increasing build-platform preheating from 25 C to 150 C increases ductility by 14% in LPBF 316L.',
		variables: ['build-platform preheating temperature'],
		mediators: ['reduced thermal gradient'],
		outcomes: ['ductility'],
		direction: 'increases',
		scope_summary: 'LPBF 316L, identical build parameters, tensile testing at room temperature',
		support_grade: 'strong',
		review_status: 'needs_review',
		confidence: 0.91,
		paper_count: 2,
		evidence_count: 2,
		evidence_ref_ids: ['ev_internal_1', 'ev_internal_2'],
		context_ids: ['ctx_internal_1'],
		relation_ids: ['rel_internal_1'],
		relation_chain: [
			{
				relation_id: 'rel_internal_1',
				variable: 'build-platform preheating temperature',
				mediators: ['reduced thermal gradient'],
				outcome: 'ductility',
				direction: 'increases',
				statement: 'Higher preheating increases ductility through a reduced thermal gradient.'
			}
		],
		evidence_bundle: {
			direct_result: ['ev_internal_1', 'ev_internal_2'],
			mechanism: [],
			condition_context: [],
			background: [],
			conflict: [],
			noise: [],
			uncategorized: []
		},
		comparison_summary: null,
		expert_use_status: 'review_candidate',
		dataset_use_status: 'review_candidate',
		generalization_status: 'cross_paper_candidate',
		generalization_note:
			'Two papers report the same direction under comparable LPBF 316L conditions.',
		evidence_gap_summary: 'Expert review is required.',
		upgrade_actions: ['record_expert_review'],
		related_review_finding_ids: [],
		review_reasons: ['cross_paper_evidence', 'needs_expert_review'],
		warnings: [],
		synthesis_status: 'agreement',
		common_conditions: ['LPBF 316L', 'room-temperature tensile testing'],
		incomparable_conditions: [],
		paper_contributions: [
			{
				document_id: 'doc_internal_1',
				title: '56a67dccf6e344a0a7ed418921be62bc_P001-Preheating response.pdf',
				source_filename: 'P001-Preheating response.pdf',
				role: 'supporting',
				statement: 'The 150 C build showed 14% higher elongation than the 25 C build.',
				evidence_ref_ids: ['ev_internal_1']
			},
			{
				document_id: 'doc_internal_2',
				title: 'f66adc89b96248309706ed8a0ddc793f_P002-Thermal management.pdf',
				source_filename: 'P002-Thermal management.pdf',
				role: 'supporting',
				statement: 'The independently produced 150 C cohort showed the same ductility trend.',
				evidence_ref_ids: ['ev_internal_2']
			}
		]
	};
	const secondFinding = {
		...firstFinding,
		finding_id: 'finding_internal_2',
		claim_id: 'claim_internal_2',
		title: 'energy density -> porosity',
		statement: 'Within the tested window, higher volumetric energy density reduces porosity.',
		variables: ['volumetric energy density'],
		mediators: [],
		outcomes: ['porosity'],
		direction: 'decreases',
		scope_summary: 'LPBF 316L, 70-150 J/mm3',
		support_grade: 'partial',
		paper_count: 1,
		evidence_count: 1,
		evidence_ref_ids: ['ev_internal_3'],
		context_ids: [],
		relation_ids: [],
		relation_chain: [],
		evidence_bundle: {
			direct_result: ['ev_internal_3'],
			mechanism: [],
			condition_context: [],
			background: [],
			conflict: [],
			noise: [],
			uncategorized: []
		},
		generalization_status: 'paper_level_only',
		generalization_note: 'Only one paper provides a directly comparable result.',
		review_reasons: ['single_paper_evidence'],
		synthesis_status: 'paper_level_only',
		common_conditions: [],
		paper_contributions: [
			{
				document_id: 'doc_internal_1',
				title: null,
				source_filename: 'P001-Preheating response.pdf',
				role: 'supporting',
				statement: 'Density increased across the reported energy-density window.',
				evidence_ref_ids: ['ev_internal_3']
			}
		]
	};
	return {
		schema_version: 'research_understanding.v1',
		state: 'ready',
		scope: {
			scope_type: 'goal',
			collection_id: 'col_123',
			goal_id: 'goal_1',
			material_id: null,
			objective_id: null,
			document_id: null,
			title: 'How does preheating affect LPBF 316L?'
		},
		claims: [],
		relations: [],
		evidence_refs: [],
		contexts: [],
		warnings: [],
		summary: {
			claim_count: 2,
			relation_count: 1,
			evidence_ref_count: 3,
			context_count: 1
		},
		presentation: {
			summary: {
				title: 'How does preheating affect LPBF 316L?',
				material_scope: ['316L stainless steel'],
				variable_axes: ['build-platform preheating temperature', 'volumetric energy density'],
				property_scope: ['ductility'],
				claim_count: 2,
				relation_count: 1,
				evidence_count: 3,
				context_count: 1,
				review_queue_count: 2,
				primary_finding_count: 1,
				review_queue_finding_count: 1,
				collection_document_count: 6,
				axis_coverage: {
					variables: [
						{
							axis: 'build-platform preheating temperature',
							status: 'review_queue',
							finding_id: 'finding_internal_1'
						},
						{
							axis: 'scan strategy',
							status: 'missing',
							finding_id: ''
						}
					],
					properties: [
						{ axis: 'ductility', status: 'review_queue', finding_id: 'finding_internal_1' }
					]
				}
			},
			effects: [],
			findings: [firstFinding, secondFinding],
			primary_findings: [firstFinding],
			review_queue_findings: [secondFinding],
			evidence_items: [
				{
					evidence_ref_id: 'ev_internal_1',
					document_id: 'doc_internal_1',
					title: '56a67dccf6e344a0a7ed418921be62bc_P001-Preheating response / p. 5',
					source_label: '56a67dccf6e344a0a7ed418921be62bc_P001-Preheating response',
					source_kind: 'text_window',
					source_ref: 'block_internal_1',
					block_type: 'paragraph',
					heading_path: '3.2 Tensile properties',
					page: '5',
					quote: 'Preheating the build platform to 150 C increased elongation by 14%.',
					source_text: 'A much longer parsed source block that is not shown by default.',
					value_summary: '',
					table_audit: null,
					traceability_status: 'resolved',
					evidence_role: 'direct_support',
					confidence: 0.96,
					href: '/collections/col_123/documents/doc_internal_1?view=parsed-paper&page=5&quote=Preheating'
				},
				{
					evidence_ref_id: 'ev_internal_2',
					document_id: 'doc_internal_2',
					title: 'f66adc89b96248309706ed8a0ddc793f_P002-Thermal management / p. 7',
					source_label: 'f66adc89b96248309706ed8a0ddc793f_P002-Thermal management',
					source_kind: 'table',
					source_ref: 'table_internal_1',
					block_type: null,
					heading_path: null,
					page: '7',
					quote: 'The 150 C cohort reproduced the increase in elongation.',
					source_text: null,
					value_summary: '',
					table_audit: null,
					traceability_status: 'resolved',
					evidence_role: 'direct_support',
					confidence: 0.92,
					href: '/collections/col_123/documents/doc_internal_2?view=parsed-paper&page=7'
				},
				{
					evidence_ref_id: 'ev_internal_3',
					document_id: 'doc_internal_1',
					title: 'P001-Preheating response / p. 3',
					source_label: 'P001-Preheating response',
					source_kind: 'table',
					source_ref: 'table_internal_2',
					block_type: null,
					heading_path: null,
					page: '3',
					quote: 'Relative density rose from 93.8% to 98.0% across the tested range.',
					source_text: null,
					value_summary: '',
					table_audit: null,
					traceability_status: 'resolved',
					evidence_role: 'direct_support',
					confidence: 0.9,
					href: '/collections/col_123/documents/doc_internal_1?view=parsed-paper&page=3'
				}
			],
			context_summaries: []
		}
	};
}

function goalAnalysis(overrides: Record<string, unknown> = {}) {
	return {
		collection_id: 'col_123',
		goal: {
			goal_id: 'goal_1',
			collection_id: 'col_123',
			question: 'How does preheating affect LPBF 316L?',
			source_type: 'objective_candidate',
			material_hints: ['316L stainless steel'],
			process_hints: ['preheating'],
			property_hints: ['ductility'],
			source_objective_id: 'objective_internal_1',
			status: 'ready',
			analysis_error: null,
			analysis_progress: null,
			created_at: null,
			updated_at: null
		},
		understanding: researchUnderstanding(),
		pipeline_nodes: {},
		errors: [],
		warnings: [],
		...overrides
	};
}

function datasetResponse() {
	return {
		schema_version: 'research_understanding_dataset.v1',
		dataset_id: 'dataset_internal_1',
		collection_id: 'col_123',
		scope_type: 'goal',
		scope_id: 'goal_1',
		task_type: 'research_understanding_finding',
		metric_profile: 'research_understanding_v1',
		label_status_filter: null,
		dataset_use_status_filter: null,
		item_count: 2,
		label_counts: { candidate: 2, silver: 0, gold: 0, rejected: 0 },
		quality_summary: {
			training_ready_sample_count: 0,
			training_message_sample_count: 0,
			protocol_ready_sample_count: 0,
			review_candidate_sample_count: 2,
			next_review_finding_id: 'finding_internal_1',
			by_dataset_use_status: { training_ready: 0, review_candidate: 2, rejected: 0 }
		},
		items: [
			{
				sample_id: 'sample_internal_1',
				finding_id: 'finding_internal_1',
				claim_id: 'claim_internal_1',
				finding_fingerprint: 'fingerprint_internal_1',
				label_status: 'candidate',
				dataset_use_status: 'review_candidate',
				review_action: { code: 'review_evidence', label: 'Review source evidence' },
				protocol_readiness: null,
				acceptance_gate: {
					status: 'review_required',
					accept_allowed: true,
					requires_correction: false,
					blocking_missing: [],
					accept_blockers: [],
					review_checks: [
						'Confirm both papers used comparable LPBF 316L conditions.',
						'Confirm the 14% value in the source passage.'
					],
					recommended_action_code: 'review_evidence',
					guidance: 'Accept after checking both sources.'
				},
				review_decision_hint: null,
				feedback_refs: [],
				metadata: {
					curation_id: null,
					ignored_feedback_refs: [],
					ignored_curation_refs: [],
					training_message_diagnostic: []
				}
			}
		],
		warnings: []
	};
}

function experimentPlansResponse() {
	return {
		collection_id: 'col_123',
		goal_id: 'goal_1',
		items: [
			{
				plan_id: 'plan_internal_1',
				collection_id: 'col_123',
				goal_id: 'goal_1',
				title: 'Preheating validation matrix',
				content:
					'Hypothesis: preheating increases ductility.\nVariable matrix: 25 C and 150 C.\nMeasurements: elongation.\nControls: same LPBF parameters.\nRisks: single alloy.',
				status: 'draft',
				source_message_id: null,
				source_links: [],
				metadata: {},
				created_by: 'Materials Expert',
				created_at: '2026-07-19T00:00:00Z',
				updated_at: '2026-07-19T00:00:00Z'
			}
		]
	};
}

describe('collections/[id]/goals/[goal_id]/+page.svelte', () => {
	beforeEach(() => {
		analysisResponse = goalAnalysis();
		feedbackResponse = [];
		curationResponse = [];
		authState.set({
			status: 'authenticated',
			user: {
				user_id: 'expert_internal_1',
				email: 'materials-expert@example.com',
				display_name: 'Materials Expert'
			}
		});
		setPage({
			params: { id: 'col_123', goal_id: 'goal_1' },
			url: new URL('http://localhost/collections/col_123/goals/goal_1')
		});
		fetchMock.mockReset();
		fetchMock.mockImplementation((input: string | URL | Request, init?: RequestInit) => {
			const path = requestPath(input);
			const method = requestMethod(input, init);
			if (path === '/api/v1/collections/col_123/goals/goal_1/analysis') {
				return Promise.resolve(jsonResponse(analysisResponse));
			}
			if (path === '/api/v1/collections/col_123/goals/goal_1/experiment-plans') {
				return Promise.resolve(jsonResponse(experimentPlansResponse()));
			}
			if (path.endsWith('/research-understanding/dataset')) {
				return Promise.resolve(jsonResponse(datasetResponse()));
			}
			if (path.endsWith('/research-understanding/feedback')) {
				if (method === 'POST') {
					const body = requestBody(init);
					return Promise.resolve(
						jsonResponse({
							...body,
							feedback_id: 'feedback_internal_saved',
							collection_id: 'col_123',
							finding_fingerprint: null,
							created_at: '2026-07-19T00:00:00Z'
						})
					);
				}
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: feedbackResponse }));
			}
			if (path.endsWith('/research-understanding/curations')) {
				if (method === 'POST') {
					const body = requestBody(init);
					return Promise.resolve(
						jsonResponse({
							...body,
							curation_id: 'curation_internal_saved',
							collection_id: 'col_123',
							finding_fingerprint: null,
							updated_at: '2026-07-19T00:00:00Z'
						})
					);
				}
				return Promise.resolve(jsonResponse({ collection_id: 'col_123', items: curationResponse }));
			}
			return Promise.resolve(jsonResponse({ detail: `unexpected request: ${path}` }, 500));
		});
	});

	it('renders a focused Finding list and keeps secondary tools out of the primary flow', async () => {
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'How does preheating affect LPBF 316L?' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research findings' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('2', { exact: true }).first()).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText(
					'Increasing build-platform preheating from 25 C to 150 C increases ductility by 14% in LPBF 316L.'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Experiment plans' }))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Audit binding')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Parsed source block')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Raw JSON')).not.toBeInTheDocument();
		expect(document.body.textContent).not.toContain('finding_internal_1');
		expect(document.body.textContent).not.toContain('claim_internal_1');
		expect(document.body.textContent).not.toContain('rel_internal_1');
		expect(document.body.textContent).not.toContain('ev_internal_1');
		expect(document.body.textContent).not.toContain('doc_internal_1');
		expect(document.body.textContent).not.toContain('56a67dccf6e344a0a7ed418921be62bc');
	});

	it('opens one Finding and shows paper-by-paper original evidence with source navigation', async () => {
		render(Page);

		await browserPage.getByRole('button', { name: /Increasing build-platform preheating/ }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: /Increasing build-platform preheating/ }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Relationship' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('reduced thermal gradient')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Evidence by paper' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('P001-Preheating response')).toBeInTheDocument();
		await expect
			.element(
				browserPage.getByText('Preheating the build platform to 150 C increased elongation by 14%.')
			)
			.toBeInTheDocument();
		const sourceLink = browserPage.getByRole('link', { name: /Open in paper/ }).first();
		await expect
			.element(sourceLink)
			.toHaveAttribute(
				'href',
				expect.stringContaining('/collections/col_123/documents/doc_internal_1?')
			);
		await expect.element(sourceLink).toHaveAttribute('href', expect.stringContaining('page=5'));
		await expect.element(sourceLink).toHaveAttribute('href', expect.stringContaining('return_to='));
		await expect.element(browserPage.getByText('Cross-paper synthesis')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Finding evidence')).not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Back to findings' }).click();
		await expect
			.element(browserPage.getByRole('table', { name: 'Research findings' }))
			.toBeInTheDocument();
	});

	it('submits an accepted Finding as correct feedback', async () => {
		render(Page);
		await browserPage.getByRole('button', { name: /Increasing build-platform preheating/ }).click();
		await browserPage.getByRole('button', { name: 'Review', exact: true }).click();
		await expect.element(browserPage.getByRole('dialog')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Confirm the 14% value in the source passage.'))
			.toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Save decision' }).click();

		await vi.waitFor(() => {
			const call = fetchMock.mock.calls.find(
				([input, init]) =>
					requestPath(input) === '/api/v1/collections/col_123/research-understanding/feedback' &&
					requestMethod(input, init) === 'POST'
			);
			expect(requestBody(call?.[1])).toMatchObject({
				scope_type: 'goal',
				scope_id: 'goal_1',
				finding_id: 'finding_internal_1',
				claim_id: 'claim_internal_1',
				review_status: 'correct',
				issue_type: 'none',
				reviewer: 'materials-expert@example.com'
			});
		});
		await expect.element(browserPage.getByText('Accepted').first()).toBeInTheDocument();
	});

	it('submits rejection feedback with an expert issue and note', async () => {
		render(Page);
		await browserPage.getByRole('button', { name: /Increasing build-platform preheating/ }).click();
		await browserPage.getByRole('button', { name: 'Review', exact: true }).click();
		await browserPage.getByRole('button', { name: 'Reject', exact: true }).click();
		await browserPage.getByLabelText('Issue type').selectOptions('overclaim');
		await browserPage
			.getByLabelText('Reason for rejection')
			.fill('The second paper does not report an independently controlled comparison.');
		await browserPage.getByRole('button', { name: 'Save decision' }).click();

		await vi.waitFor(() => {
			const call = fetchMock.mock.calls.find(
				([input, init]) =>
					requestPath(input) === '/api/v1/collections/col_123/research-understanding/feedback' &&
					requestMethod(input, init) === 'POST'
			);
			expect(requestBody(call?.[1])).toMatchObject({
				review_status: 'incorrect',
				issue_type: 'overclaim',
				note: 'The second paper does not report an independently controlled comparison.'
			});
		});
		await expect.element(browserPage.getByText('Rejected').first()).toBeInTheDocument();
	});

	it('submits a corrected Finding with structured fields and retained evidence', async () => {
		render(Page);
		await browserPage.getByRole('button', { name: /Increasing build-platform preheating/ }).click();
		await browserPage.getByRole('button', { name: 'Review', exact: true }).click();
		await browserPage.getByRole('button', { name: 'Correct', exact: true }).click();
		await browserPage
			.getByLabelText('Corrected finding')
			.fill(
				'At 150 C, build-platform preheating increased elongation by 14% in the reported LPBF 316L cohort.'
			);
		await browserPage.getByLabelText('Variables').fill('build-platform preheating temperature');
		await browserPage.getByLabelText('Mechanism').fill('reduced thermal gradient');
		await browserPage.getByLabelText('Outcomes').fill('elongation');
		await browserPage.getByLabelText('Direction').fill('increases');
		await browserPage.getByLabelText('Evidence grade').selectOptions('partial');
		await browserPage
			.getByRole('textbox', { name: 'Applicability' })
			.fill('Reported LPBF 316L cohort under room-temperature tensile testing');
		await browserPage.getByRole('button', { name: 'Save decision' }).click();

		await vi.waitFor(() => {
			const call = fetchMock.mock.calls.find(
				([input, init]) =>
					requestPath(input) === '/api/v1/collections/col_123/research-understanding/curations' &&
					requestMethod(input, init) === 'POST'
			);
			expect(requestBody(call?.[1])).toMatchObject({
				finding_id: 'finding_internal_1',
				claim_id: 'claim_internal_1',
				curated_statement:
					'At 150 C, build-platform preheating increased elongation by 14% in the reported LPBF 316L cohort.',
				curated_variables: ['build-platform preheating temperature'],
				curated_mediators: ['reduced thermal gradient'],
				curated_outcomes: ['elongation'],
				curated_direction: 'increases',
				curated_support_grade: 'partial',
				curated_evidence_ref_ids: ['ev_internal_1', 'ev_internal_2']
			});
		});
		await expect.element(browserPage.getByText('Corrected').first()).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: /At 150 C, build-platform preheating/ }))
			.toBeInTheDocument();
	});

	it('shows requested variable and outcome coverage separately and opens linked Findings', async () => {
		render(Page);
		await browserPage.getByRole('button', { name: /Coverage/ }).click();

		await expect
			.element(browserPage.getByRole('heading', { name: 'Question coverage' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Variable coverage' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Outcome coverage' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('scan strategy')).toBeInTheDocument();
		await expect.element(browserPage.getByText('No finding').first()).toBeInTheDocument();
		await browserPage
			.getByRole('button', { name: /Increasing build-platform preheating/ })
			.first()
			.click();
		await expect
			.element(browserPage.getByRole('heading', { name: /Increasing build-platform preheating/ }))
			.toBeInTheDocument();
	});

	it('keeps exports and experiment plans under More actions', async () => {
		render(Page);
		await browserPage.getByText('More', { exact: true }).click();
		await expect
			.element(browserPage.getByRole('link', { name: 'Download review packet' }))
			.toHaveAttribute(
				'href',
				'/api/v1/collections/col_123/research-understanding/dataset?scope_type=goal&scope_id=goal_1&dataset_use_status=review_candidate&format=review_packet'
			);
		await browserPage.getByRole('button', { name: 'Experiment plans' }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Experiment plans' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Preheating validation matrix')).toBeInTheDocument();
		await browserPage.getByRole('button', { name: 'Close plans' }).click();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Experiment plans' }))
			.not.toBeInTheDocument();
	});

	it('opens a requested Copilot experiment plan as a secondary section', async () => {
		setPage({
			params: { id: 'col_123', goal_id: 'goal_1' },
			url: new URL(
				'http://localhost/collections/col_123/goals/goal_1?plan_id=plan_internal_1#experiment-plans-title'
			)
		});
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Experiment plans' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByLabelText('Title'))
			.toHaveValue('Preheating validation matrix');
	});

	it('shows running analysis progress with the active paper', async () => {
		analysisResponse = goalAnalysis({
			goal: {
				goal_id: 'goal_1',
				collection_id: 'col_123',
				question: 'How does preheating affect LPBF 316L?',
				source_type: 'objective_candidate',
				material_hints: ['316L stainless steel'],
				process_hints: ['preheating'],
				property_hints: ['ductility'],
				source_objective_id: null,
				status: 'running',
				analysis_error: null,
				analysis_progress: {
					phase: 'objective_evidence_routing_started',
					current: 3,
					total: 6,
					unit: 'papers',
					message: 'Routing source blocks and tables.',
					active_document_id: 'doc_internal_1',
					active_document_title: 'Preheating response',
					active_source_filename: 'P001-Preheating response.pdf',
					active_objective_id: null
				},
				created_at: null,
				updated_at: null
			},
			understanding: null
		});
		render(Page);

		await expect
			.element(browserPage.getByRole('heading', { name: 'Analyzing this research goal' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Preheating response')).toBeInTheDocument();
		await expect.element(browserPage.getByText('3/6 papers')).toBeInTheDocument();
	});

	it('keeps analysis failures explicit and does not render an empty Finding workspace', async () => {
		analysisResponse = goalAnalysis({
			goal: {
				...(goalAnalysis().goal as Record<string, unknown>),
				status: 'failed',
				analysis_error: 'Goal analysis produced no research findings.'
			},
			understanding: null,
			errors: ['Goal analysis produced no research findings.']
		});
		render(Page);

		await expect
			.element(browserPage.getByText('Goal analysis produced no research findings.').first())
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: 'Research findings' }))
			.not.toBeInTheDocument();
	});
});
