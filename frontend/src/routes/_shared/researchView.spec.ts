import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import {
	createFindingCuration,
	createFindingFeedback,
	discoverCollectionObjectives,
	fetchCollectionObjectives,
	fetchFindingCurations,
	fetchFindingFeedback,
	fetchObjectiveAnalysis,
	fetchObjectiveEvidence,
	fetchObjectiveEvidenceMap,
	fetchObjectiveFinding,
	fetchObjectiveFindings,
	runObjectiveAnalysis
} from './researchView';

vi.mock('./api', () => ({ requestJson: vi.fn() }));
const request = vi.mocked(requestJson);

const objective = {
	collection_id: 'col_123',
	objective_id: 'obj_1',
	question: 'How does temperature affect strength?',
	material_scope: ['Alloy A'],
	variables: ['temperature'],
	outcomes: ['strength'],
	mechanisms: ['precipitate evolution'],
	constraints: ['LPBF'],
	requested_comparator: 'Compare temperatures.',
	seed_document_ids: ['paper-1'],
	excluded_document_ids: [],
	confidence: 0.9,
	reason: null,
	confirmation_status: 'confirmed',
	active_analysis_version: 1,
	published_analysis_version: 1,
	created_at: null,
	updated_at: null
};

const analysis = {
	collection_id: 'col_123',
	objective_id: 'obj_1',
	analysis_version: 1,
	document_inputs: [{ document_id: 'paper-1', preparation_fingerprint: 'fingerprint-paper-1' }],
	pipeline_version: 'objective-analysis.v2',
	model_name: 'model-1',
	prompt_versions: {},
	status: 'succeeded',
	phase: 'completed',
	processed_document_count: 1,
	total_document_count: 1,
	current_document_id: null,
	progress_message: 'Completed.',
	error_code: null,
	error_message: null,
	created_at: null,
	started_at: null,
	completed_at: null
};

const finding = {
	collection_id: 'col_123',
	objective_id: 'obj_1',
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
			context_evidence_ids: [],
			condition_boundary_evidence_ids: []
		}
	]
};

describe('objective Finding API', () => {
	beforeEach(() => request.mockReset());

	it('loads Objective definitions without workspace counters', async () => {
		request.mockResolvedValue({ collection_id: 'col_123', objectives: [objective] });

		const result = await fetchCollectionObjectives('col_123');

		expect(request).toHaveBeenCalledWith('/collections/col_123/objectives');
		expect(result.objectives[0].confirmation_status).toBe('confirmed');
		expect(result.objectives[0].published_analysis_version).toBe(1);
		expect(result.objectives[0].mechanisms).toEqual(['precipitate evolution']);
		expect(result.objectives[0].constraints).toEqual(['LPBF']);
		expect(result.objectives[0]).not.toHaveProperty('evidence_unit_count');
	});

	it('uses the same lifecycle response for queue and poll', async () => {
		request.mockResolvedValue({
			collection_id: 'col_123',
			objective,
			active_analysis: analysis,
			published_analysis: analysis,
			warnings: []
		});

		await runObjectiveAnalysis('col_123', 'obj_1', ['paper-1']);
		const result = await fetchObjectiveAnalysis('col_123', 'obj_1');

		expect(request).toHaveBeenNthCalledWith(1, '/collections/col_123/objectives/obj_1/analysis', {
			method: 'POST',
			body: JSON.stringify({ document_ids: ['paper-1'] })
		});
		expect(request).toHaveBeenNthCalledWith(2, '/collections/col_123/objectives/obj_1/analysis');
		expect(result.objective.confirmation_status).toBe('confirmed');
		expect(result.active_analysis?.status).toBe('succeeded');
		expect(result.active_analysis?.document_inputs).toEqual([
			{ document_id: 'paper-1', preparation_fingerprint: 'fingerprint-paper-1' }
		]);
	});

	it('discovers objectives from the exact ready document selection', async () => {
		request.mockResolvedValue({ collection_id: 'col_123', document_inputs: [], objectives: [] });

		await discoverCollectionObjectives('col_123', ['paper-1', 'paper-3']);

		expect(request).toHaveBeenCalledWith('/collections/col_123/objective-discovery', {
			method: 'POST',
			body: JSON.stringify({ document_ids: ['paper-1', 'paper-3'] })
		});
	});

	it('requests versioned Finding and exact Evidence pages', async () => {
		request
			.mockResolvedValueOnce({
				collection_id: 'col_123',
				objective_id: 'obj_1',
				analysis_version: 1,
				items: [],
				offset: 0,
				limit: 20,
				total: 0
			})
			.mockResolvedValueOnce({
				collection_id: 'col_123',
				objective_id: 'obj_1',
				analysis_version: 1,
				finding
			})
			.mockResolvedValueOnce({
				collection_id: 'col_123',
				objective_id: 'obj_1',
				analysis_version: 1,
				finding_id: 'finding-1',
				items: [],
				offset: 0,
				limit: 100,
				total: 0
			});

		await fetchObjectiveFindings('col_123', 'obj_1', 1, 0, 20);
		await fetchObjectiveFinding('col_123', 'obj_1', 1, 'finding-1');
		await fetchObjectiveEvidence('col_123', 'obj_1', 1, 'finding-1');

		expect(request.mock.calls[0][0]).toBe(
			'/collections/col_123/objectives/obj_1/findings?analysis_version=1&offset=0&limit=20'
		);
		expect(request.mock.calls[1][0]).toBe(
			'/collections/col_123/objectives/obj_1/findings/finding-1?analysis_version=1'
		);
		expect(request.mock.calls[2][0]).toBe(
			'/collections/col_123/objectives/obj_1/evidence?analysis_version=1&finding_id=finding-1&offset=0&limit=100'
		);
	});

	it('loads the published Objective evidence map from the Objective subresource', async () => {
		request.mockResolvedValue({
			collection_id: 'col_123',
			objective_id: 'obj_1',
			analysis_version: 1,
			projection_version: 'objective-evidence-map.v1',
			complete: true,
			nodes: [],
			edges: [],
			coverage: {
				total_document_count: 0,
				analyzed_document_count: 0,
				excluded_document_count: 0,
				failed_document_count: 0,
				direct_evidence_document_count: 0,
				finding_count: 0,
				evidence_count: 0,
				source_count: 0,
				unlinked_evidence_count: 0
			}
		});

		const result = await fetchObjectiveEvidenceMap('col_123', 'obj_1');

		expect(request).toHaveBeenCalledWith('/collections/col_123/objectives/obj_1/evidence-map');
		expect(result.projection_version).toBe('objective-evidence-map.v1');
	});

	it('records feedback using analysis_version and finding_id only', async () => {
		request.mockResolvedValue({ feedback_id: 'feedback-1' });

		await createFindingFeedback('col_123', 'obj_1', 'finding-1', {
			analysis_version: 1,
			review_status: 'correct',
			issue_type: 'none'
		});

		expect(request).toHaveBeenCalledWith(
			'/collections/col_123/objectives/obj_1/findings/finding-1/feedback',
			{
				method: 'POST',
				body: JSON.stringify({
					analysis_version: 1,
					review_status: 'correct',
					issue_type: 'none'
				})
			}
		);
	});

	it('lists feedback and curations for one exact Finding version', async () => {
		request.mockResolvedValue({ items: [] });

		await fetchFindingFeedback('col_123', 'obj_1', 1, 'finding-1');
		await fetchFindingCurations('col_123', 'obj_1', 1, 'finding-1');

		expect(request.mock.calls[0][0]).toContain(
			'/objectives/obj_1/findings/finding-1/feedback?analysis_version=1'
		);
		expect(request.mock.calls[1][0]).toContain(
			'/objectives/obj_1/findings/finding-1/curation?analysis_version=1'
		);
	});

	it('writes curation with canonical evidence IDs', async () => {
		request.mockResolvedValue({ curation_id: 'curation-1' });

		await createFindingCuration('col_123', 'obj_1', 'finding-1', {
			analysis_version: 1,
			curated_status: 'limited',
			curated_finding: finding
		});

		expect(request).toHaveBeenCalledWith(
			'/collections/col_123/objectives/obj_1/findings/finding-1/curation',
			expect.objectContaining({ method: 'PUT' })
		);
	});
});
