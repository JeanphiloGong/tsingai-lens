import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import Workbench from './FindingWorkbench.svelte';

const fetchMock = vi.fn();

function jsonResponse(body: unknown) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
	vi.stubGlobal('fetch', fetchMock);
});

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string>) =>
		route.includes('/documents/')
			? `/collections/${params.id}/documents/${params.document_id}`
			: `/collections/${params.id}/objectives/${params.objective_id}`
}));

const finding = {
	collection_id: 'col-1',
	objective_id: 'obj-1',
	analysis_version: 1,
	finding_id: 'finding-1',
	statement: 'Higher temperature was associated with greater strength.',
	factors: ['temperature'],
	outcome: 'strength',
	direction: 'increase' as const,
	assertion_strength: 'associative' as const,
	attribution_scope: 'isolated_effect' as const,
	synthesis_status: 'insufficient_confirmation' as const,
	certainty: 0.8,
	display_rank: 0,
	mechanisms: [
		{
			source_term: 'temperature',
			relation_type: 'associated_with',
			target_term: 'strength',
			direction: 'increase' as const,
			assertion_strength: 'associative' as const,
			supporting_evidence_ids: ['evidence-1']
		}
	],
	scientific_context: {
		material: [{ name: 'alloy', value: 'Alloy A', unit: null }],
		sample: [],
		process: [],
		test: []
	},
	limitations: ['Single paper only.'],
	paper_contributions: [
		{
			document_id: 'paper-1',
			analysis_status: 'analyzed' as const,
			supporting_evidence_ids: ['evidence-1'],
			contradicting_evidence_ids: [],
			context_evidence_ids: ['evidence-1'],
			condition_boundary_evidence_ids: ['evidence-1']
		}
	]
};

const evidence = [
	{
		collection_id: 'col-1',
		objective_id: 'obj-1',
		analysis_version: 1,
		evidence_id: 'evidence-1',
		document_id: 'paper-1',
		source_kind: 'text_window',
		source_ref: 'block-7',
		source_excerpt: 'At 500 C, tensile strength increased to 620 MPa.',
		page_numbers: [7],
		related_source_refs: [],
		evidence_role: 'direct_result',
		selection_reason: null,
		selection_status: 'extracted',
		changed_variables: [{ name: 'temperature', baseline_value: 400, target_value: 500, unit: 'C' }],
		comparison: {
			baseline_label: '400 C',
			target_label: '500 C',
			axis_names: ['temperature'],
			comparable: true,
			incomparability_reasons: []
		},
		reported_result: {
			outcome: 'strength',
			value: 620,
			unit: 'MPa',
			direction: 'increase' as const,
			result_text: 'At 500 C, tensile strength increased to 620 MPa.'
		},
		attribution_scope: 'isolated_effect' as const,
		scientific_context: {
			material: [{ name: 'alloy', value: 'Alloy A', unit: null }],
			sample: [],
			process: [],
			test: []
		},
		anchor_ids: [],
		resolution_status: 'resolved',
		failure_reason: null,
		confidence: 0.9
	}
];

describe('single Finding workbench', () => {
	it('shows relation, scope, and exact source evidence', async () => {
		render(Workbench, { finding, evidence, collectionId: 'col-1' });

		await expect.element(browserPage.getByText(finding.statement)).toBeInTheDocument();
		await expect.element(browserPage.getByText('associated_with')).toBeInTheDocument();
		await expect.element(browserPage.getByText('支持结果')).toBeInTheDocument();
		await expect.element(browserPage.getByText('上下文')).toBeInTheDocument();
		await expect.element(browserPage.getByText('条件边界')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: '文献 1 · p.7' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(evidence[0].source_excerpt);
		await expect
			.element(browserPage.getByRole('link', { name: '打开原文' }))
			.toHaveAttribute(
				'href',
				'/collections/col-1/documents/paper-1?view=parsed-paper&evidence_id=evidence-1&source_ref=block-7&quote=At+500+C%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2Fcol-1%2Fobjectives%2Fobj-1%3Ffinding_id%3Dfinding-1&page=7'
			);
	});

	it('shows explicit empty mechanism and limitation states', async () => {
		render(Workbench, {
			finding: { ...finding, mechanisms: [], limitations: [] },
			evidence,
			collectionId: 'col-1'
		});

		await expect
			.element(browserPage.getByRole('heading', { name: '作用机制' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('未报告可由原文证据支持的作用机制。'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('未报告额外限制。')).toBeInTheDocument();
	});

	it('keeps feedback behind an explicit action', async () => {
		render(Workbench, { finding, evidence, collectionId: 'col-1' });
		const reviewStatus = browserPage.getByRole('combobox', { name: '判断', exact: true });
		await expect.element(reviewStatus).not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: '反馈' }).click();
		await expect.element(reviewStatus).toBeInTheDocument();
	});

	it('restores the latest feedback and keeps the submitted decision visible', async () => {
		fetchMock
			.mockResolvedValueOnce(
				jsonResponse({
					items: [
						{
							feedback_id: 'feedback-old',
							collection_id: 'col-1',
							objective_id: 'obj-1',
							analysis_version: 1,
							finding_id: 'finding-1',
							review_status: 'correct',
							issue_type: 'none',
							note: 'Earlier review',
							created_at: '2026-08-01T00:00:00+00:00'
						},
						{
							feedback_id: 'feedback-latest',
							collection_id: 'col-1',
							objective_id: 'obj-1',
							analysis_version: 1,
							finding_id: 'finding-1',
							review_status: 'partial',
							issue_type: 'wrong_context',
							note: 'Check the test condition.',
							created_at: '2026-08-02T00:00:00+00:00'
						}
					]
				})
			)
			.mockResolvedValueOnce(
				jsonResponse({
					feedback_id: 'feedback-new',
					collection_id: 'col-1',
					objective_id: 'obj-1',
					analysis_version: 1,
					finding_id: 'finding-1',
					review_status: 'incorrect',
					issue_type: 'wrong_attribution',
					note: 'Variables changed together.',
					created_at: '2026-08-02T01:00:00+00:00'
				})
			);
		render(Workbench, { finding, evidence, collectionId: 'col-1' });

		await browserPage.getByRole('button', { name: '反馈' }).click();
		const status = browserPage.getByRole('combobox', { name: '判断', exact: true });
		const issue = browserPage.getByRole('combobox', { name: '问题类型' });
		const note = browserPage.getByRole('textbox', { name: '说明' });
		await expect.element(status).toHaveValue('partial');
		await expect.element(issue).toHaveValue('wrong_context');
		await expect.element(note).toHaveValue('Check the test condition.');

		await status.selectOptions('incorrect');
		await issue.selectOptions('wrong_attribution');
		await note.fill('Variables changed together.');
		await browserPage.getByRole('button', { name: '提交反馈' }).click();

		await expect.element(browserPage.getByText('反馈已记录。')).toBeInTheDocument();
		await expect.element(status).toHaveValue('incorrect');
		await expect.element(issue).toHaveValue('wrong_attribution');
		await expect.element(note).toHaveValue('Variables changed together.');
	});
});
