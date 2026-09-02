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
	resolve: (route: string, params?: Record<string, string>) =>
		!route.includes('[')
			? route
			: route.includes('/documents/')
				? `/collections/${params!.id}/documents/${params!.document_id}`
				: `/collections/${params!.id}/objectives/${params!.objective_id}`
}));

const mechanism = {
	source_term: 'temperature',
	relation_type: 'associated_with',
	target_term: 'strength',
	direction: 'increase' as const,
	assertion_strength: 'associative' as const,
	supporting_evidence_ids: ['evidence-mechanism']
};

const finding = {
	collection_id: 'col-1',
	objective_id: 'obj-1',
	analysis_version: 1,
	finding_id: 'finding-1',
	origin: 'system_generated' as const,
	source_analysis_version: null,
	parent_finding_id: null,
	created_by_user_id: null,
	created_by_tool_call_id: null,
	created_at: null,
	statement: 'Higher temperature was associated with greater strength.',
	factors: ['temperature'],
	outcome: 'strength',
	direction: 'increase' as const,
	assertion_strength: 'associative' as const,
	attribution_scope: 'isolated_effect' as const,
	synthesis_status: 'insufficient_confirmation' as const,
	certainty: 0.8,
	display_rank: 0,
	mechanisms: [],
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
			baseline_value: null,
			target_value: null,
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
		confidence: 0.9,
		supports_finding: true
	}
];

describe('single Finding workbench', () => {
	it('shows scope and exact source evidence', async () => {
		render(Workbench, {
			finding,
			evidence,
			collectionId: 'col-1',
			documentTitles: { 'paper-1': 'Thermal treatment of Alloy A' }
		});

		await expect.element(browserPage.getByText(finding.statement)).toBeInTheDocument();
		await expect.element(browserPage.getByText('associated_with')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('heading', { name: '证据对比' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('columnheader', { name: '参照条件' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('columnheader', { name: '比较条件' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('400 C', { exact: true })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('cell', { name: '500 C' })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('cell', { name: '支持结果' })).toBeInTheDocument();
		await expect.element(browserPage.getByRole('cell', { name: '增加' })).toBeInTheDocument();
		await expect.element(browserPage.getByText('strength: 620 MPa')).toBeInTheDocument();
		await expect.element(browserPage.getByText('1 条结构化 Evidence')).toBeInTheDocument();
		await expect.element(browserPage.getByText('样品状态')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('工艺条件')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('测试条件')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('分析边界')).toBeInTheDocument();
		await expect.element(browserPage.getByText('上下文')).toBeInTheDocument();
		await expect.element(browserPage.getByText('条件边界')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Thermal treatment of Alloy A · p.7' }))
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('blockquote'))
			.toHaveTextContent(evidence[0].source_excerpt);
		expect(document.body.textContent?.split(evidence[0].source_excerpt).length).toBe(2);
		await expect
			.element(browserPage.getByRole('link', { name: '打开原文' }))
			.toHaveAttribute(
				'href',
				'/collections/col-1/documents/paper-1?view=parsed-paper&evidence_id=evidence-1&source_ref=block-7&quote=At+500+C%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2Fcol-1%2Fobjectives%2Fobj-1%3Ffinding_id%3Dfinding-1&page=7'
			);
	});

	it('keeps jointly changed variables in one comparison row', async () => {
		const jointEvidence = {
			...evidence[0],
			evidence_id: 'evidence-joint',
			source_ref: 'table-2',
			source_excerpt:
				'Laser power and scan speed changed together, increasing relative density to 99.1%.',
			changed_variables: [
				{ name: 'laser power', baseline_value: 180, target_value: 220, unit: 'W' },
				{ name: 'scan speed', baseline_value: 800, target_value: 1000, unit: 'mm/s' }
			],
			comparison: {
				baseline_label: '180 W / 800 mm/s',
				target_label: '220 W / 1000 mm/s',
				axis_names: ['laser power', 'scan speed'],
				comparable: true,
				incomparability_reasons: []
			},
			reported_result: {
				outcome: 'relative density',
				value: 99.1,
				baseline_value: null,
				target_value: null,
				unit: '%',
				direction: 'increase' as const,
				result_text: 'Relative density increased to 99.1%.'
			},
			attribution_scope: 'joint_effect' as const
		};
		render(Workbench, {
			finding: {
				...finding,
				factors: ['laser power', 'scan speed'],
				outcome: 'relative density',
				attribution_scope: 'joint_effect' as const,
				mechanisms: [],
				paper_contributions: [
					{
						...finding.paper_contributions[0],
						supporting_evidence_ids: ['evidence-joint'],
						context_evidence_ids: [],
						condition_boundary_evidence_ids: []
					}
				]
			},
			evidence: [jointEvidence],
			collectionId: 'col-1',
			documentTitles: { 'paper-1': 'Joint LPBF parameter study' }
		});

		expect(browserPage.getByRole('row').length).toBe(2);
		const comparisonRow = browserPage.getByRole('row').nth(1);
		await expect.element(comparisonRow).toHaveTextContent('laser power');
		await expect.element(comparisonRow).toHaveTextContent('scan speed');
		await expect.element(browserPage.getByText('relative density: 99.1 %')).toBeInTheDocument();
	});

	it('groups same-table treatment comparisons as one source with a shared reference', async () => {
		const treatmentResults = [
			['800 SC', 1082.43],
			['800 FC', 1063.02],
			['800 RQ', 1050.39],
			['920 SC', 990.83],
			['920 FC', 991.86],
			['920 RQ', 1070.03],
			['1050 SC', 906.94],
			['1050 RQ', 1035.62],
			['1050 RQ + 800 SC', 1028.26],
			['1050 RQ + 920 FC', 961.53]
		] as const;
		const tableEvidence = treatmentResults.map(([condition, targetValue], index) => ({
			...evidence[0],
			evidence_id: `evidence-table-${index + 1}`,
			source_kind: 'table',
			source_ref: 'table-8',
			source_excerpt: `Condition: AB | UTS: 1294.20 MPa\nCondition: ${condition} | UTS: ${targetValue} MPa`,
			page_numbers: [20],
			related_source_refs: [
				{ source_kind: 'table', source_ref: 'table-8', row_index: 1, col_index: 5 },
				{ source_kind: 'table', source_ref: 'table-8', row_index: index + 2, col_index: 5 }
			],
			changed_variables: [
				{
					name: 'post-processing condition',
					baseline_value: 'AB',
					target_value: condition,
					unit: null
				}
			],
			comparison: {
				baseline_label: 'AB',
				target_label: condition,
				axis_names: ['post-processing condition'],
				comparable: true,
				incomparability_reasons: []
			},
			reported_result: {
				outcome: 'ultimate tensile strength',
				value: targetValue,
				baseline_value: 1294.2,
				target_value: targetValue,
				unit: 'MPa',
				direction: 'decrease' as const,
				result_text: `UTS decreased from 1294.2 MPa to ${targetValue} MPa.`
			},
			attribution_scope: 'association_only' as const
		}));
		const evidenceIds = tableEvidence.map((item) => item.evidence_id);

		render(Workbench, {
			finding: {
				...finding,
				statement: 'Post-processing conditions were associated with lower UTS.',
				factors: ['post-processing condition'],
				outcome: 'ultimate tensile strength',
				direction: 'decrease' as const,
				attribution_scope: 'association_only' as const,
				paper_contributions: [
					{
						...finding.paper_contributions[0],
						supporting_evidence_ids: evidenceIds,
						context_evidence_ids: [],
						condition_boundary_evidence_ids: []
					}
				]
			},
			evidence: tableEvidence,
			collectionId: 'col-1',
			documentTitles: { 'paper-1': 'HIP treatment of Ti-6Al-4V' }
		});

		const evidenceScope = browserPage.getByRole('group', { name: '证据范围' });
		await expect.element(evidenceScope).toHaveTextContent('1篇直接文献');
		await expect.element(evidenceScope).toHaveTextContent('1个原文来源');
		await expect.element(evidenceScope).toHaveTextContent('10个结果比较');
		await expect.element(browserPage.getByText('表格来源 · p.20')).toBeInTheDocument();
		await expect
			.element(browserPage.getByText('共享参照 AB · 10 个组间比较', { exact: true }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('10 条证据')).not.toBeInTheDocument();
		const tableSource = browserPage.getByRole('group', { name: '表格来源 · p.20' });
		await expect.element(tableSource).not.toHaveAttribute('open');
		await browserPage.getByText('表格来源 · p.20', { exact: true }).click();
		await expect.element(tableSource).toHaveAttribute('open');
		const sharedReference = tableSource.getByRole('group', { name: '共享参照' });
		await expect.element(sharedReference).toHaveTextContent('AB');
		await expect.element(sharedReference).toHaveTextContent('ultimate tensile strength');
		await expect.element(sharedReference).toHaveTextContent('1294.2 MPa');
		const matrix = tableSource.getByRole('table', { name: '共享参照比较' });
		expect(matrix.getByRole('row').length).toBe(11);
		const firstTreatment = matrix.getByRole('row', { name: /^比较条件 800 SC 报告结果/ });
		await expect.element(firstTreatment).toHaveTextContent('1082.43 MPa');
		await expect.element(firstTreatment).toHaveTextContent('-211.77 MPa');
		await expect.element(firstTreatment).toHaveTextContent('降低');
		await expect.element(firstTreatment.getByRole('link', { name: '打开原文' })).toBeVisible();
		const excerpt = firstTreatment.getByText(tableEvidence[0].source_excerpt, { exact: true });
		await expect.element(excerpt).not.toBeVisible();
		await firstTreatment.getByText('查看摘录', { exact: true }).click();
		await expect.element(excerpt).toBeVisible();
	});

	it('does not merge same-source comparisons whose reported baselines conflict', async () => {
		const conflictingEvidence = [1294.2, 1200].map((baselineValue, index) => ({
			...evidence[0],
			evidence_id: `evidence-conflict-${index + 1}`,
			source_kind: 'table',
			source_ref: 'table-conflict',
			source_excerpt: `AB baseline ${baselineValue} MPa; treatment ${index + 1}.`,
			page_numbers: [20],
			changed_variables: [
				{
					name: 'post-processing condition',
					baseline_value: 'AB',
					target_value: index === 0 ? '800 SC' : '920 SC',
					unit: null
				}
			],
			comparison: {
				baseline_label: 'AB',
				target_label: index === 0 ? '800 SC' : '920 SC',
				axis_names: ['post-processing condition'],
				comparable: true,
				incomparability_reasons: []
			},
			reported_result: {
				outcome: 'ultimate tensile strength',
				value: index === 0 ? 1082.43 : 990.83,
				baseline_value: baselineValue,
				target_value: index === 0 ? 1082.43 : 990.83,
				unit: 'MPa',
				direction: 'decrease' as const,
				result_text: 'Reported UTS comparison.'
			},
			attribution_scope: 'association_only' as const
		}));

		render(Workbench, {
			finding: {
				...finding,
				paper_contributions: [
					{
						...finding.paper_contributions[0],
						supporting_evidence_ids: conflictingEvidence.map((item) => item.evidence_id),
						context_evidence_ids: [],
						condition_boundary_evidence_ids: []
					}
				]
			},
			evidence: conflictingEvidence,
			collectionId: 'col-1'
		});

		const tableSource = browserPage.getByRole('group', { name: '表格来源 · p.20' });
		await expect.element(tableSource).not.toHaveTextContent('共享参照');
		await browserPage.getByText('表格来源 · p.20', { exact: true }).click();
		await expect
			.element(tableSource.getByRole('table', { name: '共享参照比较' }))
			.not.toBeInTheDocument();
		await expect.element(tableSource.getByText('AB → 800 SC', { exact: true })).toBeVisible();
		await expect.element(tableSource.getByText('AB → 920 SC', { exact: true })).toBeVisible();
	});

	it('links each mechanism to its exact supporting Evidence', async () => {
		const mechanismEvidence = {
			...evidence[0],
			evidence_id: 'evidence-mechanism',
			source_ref: 'block-8',
			source_excerpt: 'Precipitate evolution was associated with increased strength.',
			page_numbers: [8],
			evidence_role: 'mechanism_context',
			changed_variables: [],
			comparison: null,
			reported_result: null,
			attribution_scope: 'not_attributable' as const
		};
		render(Workbench, {
			finding: {
				...finding,
				mechanisms: [mechanism],
				paper_contributions: [
					{
						...finding.paper_contributions[0],
						context_evidence_ids: ['evidence-mechanism'],
						condition_boundary_evidence_ids: []
					}
				]
			},
			evidence: [evidence[0], mechanismEvidence],
			collectionId: 'col-1',
			documentTitles: { 'paper-1': 'Thermal treatment of Alloy A' }
		});

		await expect.element(browserPage.getByText('相关联', { exact: true })).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('link', { name: 'Thermal treatment of Alloy A · p.8' }))
			.toHaveAttribute(
				'href',
				'/collections/col-1/documents/paper-1?view=parsed-paper&evidence_id=evidence-mechanism&source_ref=block-8&quote=Precipitate+evolution+was+associated+with+increased+strength.&return_to=%2Fcollections%2Fcol-1%2Fobjectives%2Fobj-1%3Ffinding_id%3Dfinding-1&page=8'
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
		await expect.element(browserPage.getByText('未识别额外分析边界。')).toBeInTheDocument();
	});

	it('hides paper groups without Evidence and summarizes their analysis states', async () => {
		const emptyContributions = [
			{
				document_id: 'paper-empty-analyzed',
				analysis_status: 'analyzed' as const,
				supporting_evidence_ids: [],
				contradicting_evidence_ids: [],
				context_evidence_ids: [],
				condition_boundary_evidence_ids: []
			},
			{
				document_id: 'paper-excluded',
				analysis_status: 'excluded' as const,
				supporting_evidence_ids: [],
				contradicting_evidence_ids: [],
				context_evidence_ids: [],
				condition_boundary_evidence_ids: []
			},
			{
				document_id: 'paper-failed',
				analysis_status: 'failed' as const,
				supporting_evidence_ids: [],
				contradicting_evidence_ids: [],
				context_evidence_ids: [],
				condition_boundary_evidence_ids: []
			}
		];
		render(Workbench, {
			finding: {
				...finding,
				paper_contributions: [...finding.paper_contributions, ...emptyContributions]
			},
			evidence,
			collectionId: 'col-1',
			documentTitles: {
				'paper-1': 'Thermal treatment of Alloy A',
				'paper-empty-analyzed': 'Paper without extracted Evidence',
				'paper-excluded': 'Excluded paper',
				'paper-failed': 'Failed paper'
			}
		});

		const evidenceScope = browserPage.getByRole('group', { name: '证据范围' });
		await expect.element(evidenceScope).toHaveTextContent('1篇直接文献');
		await expect.element(evidenceScope).toHaveTextContent('1个原文来源');
		await expect.element(evidenceScope).toHaveTextContent('1个结果比较');
		await expect
			.element(
				browserPage.getByText(
					'另有 3 篇文献未形成可审计 Evidence：已分析但无 Evidence 1 篇，已排除 1 篇，分析失败 1 篇。'
				)
			)
			.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('Paper without extracted Evidence'))
			.not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Excluded paper')).not.toBeInTheDocument();
		await expect.element(browserPage.getByText('Failed paper')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('该文献未绑定到此 Finding 的可审计证据。'))
			.not.toBeInTheDocument();
	});

	it('shows one collection-level empty state when no paper has Evidence', async () => {
		const emptyContribution = {
			document_id: 'paper-failed',
			analysis_status: 'failed' as const,
			supporting_evidence_ids: [],
			contradicting_evidence_ids: [],
			context_evidence_ids: [],
			condition_boundary_evidence_ids: []
		};
		render(Workbench, {
			finding: { ...finding, paper_contributions: [emptyContribution] },
			evidence: [],
			collectionId: 'col-1',
			documentTitles: { 'paper-failed': 'Failed paper' }
		});

		await expect
			.element(browserPage.getByText('当前 Finding 没有可审计的原文 Evidence。'))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('Failed paper')).not.toBeInTheDocument();
		await expect
			.element(browserPage.getByText('另有 1 篇文献未形成可审计 Evidence：分析失败 1 篇。'))
			.toBeInTheDocument();
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
