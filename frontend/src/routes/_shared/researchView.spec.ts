import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import {
	confirmObjective,
	createFindingCuration,
	createFindingFeedback,
	fetchCollectionObjectives,
	fetchFindingCurations,
	fetchFindingFeedback,
	fetchObjective,
	fetchObjectiveAnalysis,
	fetchObjectiveEvidence,
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
	process_axes: ['temperature'],
	property_axes: ['strength'],
	comparison_intent: 'Compare temperatures.',
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
	source_build_id: 'build-1',
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

describe('objective Finding API', () => {
	beforeEach(() => request.mockReset());

	it('loads Objective definitions without workspace counters', async () => {
		request.mockResolvedValue({ collection_id: 'col_123', objectives: [objective] });

		const result = await fetchCollectionObjectives('col_123');

		expect(request).toHaveBeenCalledWith('/collections/col_123/objectives');
		expect(result.objectives[0].confirmation_status).toBe('confirmed');
		expect(result.objectives[0].published_analysis_version).toBe(1);
		expect(result.objectives[0]).not.toHaveProperty('evidence_unit_count');
	});

	it('loads Objective and analysis lifecycle separately', async () => {
		request.mockResolvedValue({
			collection_id: 'col_123',
			objective,
			active_analysis: analysis,
			published_analysis: analysis,
			warnings: []
		});

		const result = await fetchObjective('col_123', 'obj_1');

		expect(request).toHaveBeenCalledWith('/collections/col_123/objectives/obj_1');
		expect(result.objective.confirmation_status).toBe('confirmed');
		expect(result.active_analysis?.status).toBe('succeeded');
	});

	it('uses the same lifecycle response for confirm, queue, and poll', async () => {
		request.mockResolvedValue({
			collection_id: 'col_123',
			objective,
			active_analysis: analysis,
			published_analysis: analysis,
			warnings: []
		});

		await confirmObjective('col_123', 'obj_1');
		await runObjectiveAnalysis('col_123', 'obj_1');
		await fetchObjectiveAnalysis('col_123', 'obj_1');

		expect(request).toHaveBeenNthCalledWith(
			1,
			'/collections/col_123/objectives/obj_1/confirm',
			{ method: 'POST' }
		);
		expect(request).toHaveBeenNthCalledWith(
			2,
			'/collections/col_123/objectives/obj_1/analysis',
			{ method: 'POST' }
		);
		expect(request).toHaveBeenNthCalledWith(
			3,
			'/collections/col_123/objectives/obj_1/analysis'
		);
	});

	it('requests versioned Finding and exact Evidence pages', async () => {
		request
			.mockResolvedValueOnce({
				collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1,
				items: [], offset: 0, limit: 20, total: 0
			})
			.mockResolvedValueOnce({
				collection_id: 'col_123', objective_id: 'obj_1', analysis_version: 1,
				finding_id: 'finding-1', items: [], offset: 0, limit: 100, total: 0
			});

		await fetchObjectiveFindings('col_123', 'obj_1', 1, 0, 20);
		await fetchObjectiveEvidence('col_123', 'obj_1', 1, 'finding-1');

		expect(request.mock.calls[0][0]).toBe(
			'/collections/col_123/objectives/obj_1/findings?analysis_version=1&offset=0&limit=20'
		);
		expect(request.mock.calls[1][0]).toBe(
			'/collections/col_123/objectives/obj_1/evidence?analysis_version=1&finding_id=finding-1&offset=0&limit=100'
		);
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
			curated_statement: 'Narrower statement.',
			curated_evidence_ids: ['evidence-1']
		});

		expect(request).toHaveBeenCalledWith(
			'/collections/col_123/objectives/obj_1/findings/finding-1/curation',
			expect.objectContaining({ method: 'PUT' })
		);
	});
});
