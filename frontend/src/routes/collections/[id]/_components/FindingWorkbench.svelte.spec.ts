import { page as browserPage } from 'vitest/browser';
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import Workbench from './FindingWorkbench.svelte';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string>) =>
		route.includes('/documents/')
			? `/collections/${params.id}/documents/${params.document_id}`
			: `/collections/${params.id}/objectives/${params.objective_id}`
}));

const finding = {
	collection_id: 'col-1', objective_id: 'obj-1', analysis_version: 1,
	finding_id: 'finding-1', finding_level: 'paper',
	statement: 'Higher temperature was associated with greater strength.',
	variables: ['temperature'], mediators: [], outcomes: ['strength'], direction: 'increase',
	scope_summary: 'Alloy A', evidence_strength: 'weak',
	generalization_status: 'paper_level_only', paper_count: 1, confidence: 0.8, display_rank: 0,
	relations: [{ relation_order: 0, source_term: 'temperature', relation_type: 'associated_with', target_term: 'strength', direction: 'increase', assertion_strength: 'associative', supporting_evidence_ids: ['evidence-1'] }],
	context: { material_system: { name: 'Alloy A' }, process_conditions: [], sample_state: {}, test_conditions: [], comparison_baseline: {}, limitations: ['Single paper only.'], supporting_evidence_ids: ['evidence-1'] },
	derivation: { synthesis_mode: 'paper', comparison_status: 'insufficient_confirmation', contributing_document_ids: ['paper-1'], supporting_evidence_ids: ['evidence-1'], contradicting_evidence_ids: [], rationale: 'One direct result.' }
};

const evidence = [{
	collection_id: 'col-1', objective_id: 'obj-1', analysis_version: 1,
	evidence_id: 'evidence-1', document_id: 'paper-1', source_kind: 'text_window', source_ref: 'block-7',
	source_excerpt: 'At 500 C, tensile strength increased to 620 MPa.', page_numbers: [7], related_source_refs: [],
	evidence_role: 'direct_result', selection_reason: null, selection_status: 'extracted', evidence_kind: 'measurement',
	property_normalized: 'strength', material_system: {}, sample_context: {}, process_context: {}, resolved_condition: {},
	test_condition: {}, value_payload: { value: 620 }, unit: 'MPa', baseline_context: {}, interpretation: null,
	anchor_ids: [], join_keys: {}, resolution_status: 'resolved', failure_reason: null, confidence: 0.9
}];

describe('single Finding workbench', () => {
	it('shows relation, scope, and exact source evidence', async () => {
		render(Workbench, { finding, evidence, collectionId: 'col-1' });

		await expect.element(browserPage.getByText(finding.statement)).toBeInTheDocument();
		await expect.element(browserPage.getByText('associated_with')).toBeInTheDocument();
		await expect.element(browserPage.getByText(evidence[0].source_excerpt)).toBeInTheDocument();
			await expect.element(browserPage.getByRole('link', { name: '打开原文' })).toHaveAttribute(
				'href',
				'/collections/col-1/documents/paper-1?view=parsed-paper&source_ref=block-7&page=7&quote=At+500+C%2C+tensile+strength+increased+to+620+MPa.&return_to=%2Fcollections%2Fcol-1%2Fobjectives%2Fobj-1'
			);
	});

	it('keeps feedback behind an explicit action', async () => {
		render(Workbench, { finding, evidence, collectionId: 'col-1' });
		await expect.element(browserPage.getByLabelText('判断')).not.toBeInTheDocument();
		await browserPage.getByRole('button', { name: '反馈' }).click();
		await expect.element(browserPage.getByLabelText('判断')).toBeInTheDocument();
	});
});
