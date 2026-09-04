import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import {
	createFindingCuration,
	createFindingFeedback,
	fetchCollectionObjectives,
	fetchFindingCurations,
	fetchFindingFeedback,
	fetchObjectiveAnalysis,
	fetchObjectiveEvidence,
	fetchObjectiveEvidenceMap,
	fetchObjectiveFinding,
	fetchObjectiveFindings,
	fetchObjectiveScope,
	collectionFindingDatasetUrl,
	findingGoldDraftUrl,
	objectiveFindingDatasetUrl,
	normalizeObjectiveScope,
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

	it('builds a filtered Objective dataset export URL', () => {
		expect(
			objectiveFindingDatasetUrl('col/1', 'obj 1', 'training_jsonl', {
				label_status: 'gold',
				dataset_use_status: 'training_ready'
			})
		).toBe(
			'/api/v1/collections/col%2F1/objectives/obj%201/finding-dataset?label_status=gold&dataset_use_status=training_ready&format=training_jsonl'
		);
	});

	it('builds collection-level dataset and gold-draft export URLs', () => {
		expect(collectionFindingDatasetUrl('col/1', 'json')).toBe(
			'/api/v1/collections/col%2F1/finding-dataset?format=json'
		);
		expect(findingGoldDraftUrl('col/1')).toBe('/api/v1/collections/col%2F1/finding-gold-draft');
	});

	it('normalizes and fetches the complete Objective scope preview', async () => {
		const payload = {
			collection_id: 'col_123',
			objective_id: 'obj_1',
			counts: {
				likely_relevant: 2,
				needs_inspection: 1,
				confidently_out_of_scope: 1
			},
			recommended_document_ids: ['paper-1', 'paper-3'],
			review_document_ids: ['paper-2'],
			excluded_document_ids: ['paper-4'],
			decisions: [
				{
					document_id: 'paper-1',
					classification: 'likely_relevant',
					reason: 'mapped_research_scope',
					doc_role: 'experimental',
					map_status: 'sufficient',
					map_limitations: [],
					support_basis: ['relationship-1'],
					is_seed: true
				},
				{ document_id: '', classification: 'likely_relevant' },
				{ document_id: 'paper-invalid', classification: 'maybe' }
			],
			support_is_evidence: false
		};
		request.mockResolvedValue(payload);

		const result = await fetchObjectiveScope('col_123', 'obj_1');

		expect(request).toHaveBeenCalledWith('/collections/col_123/objectives/obj_1/scope');
		expect(result.recommended_document_ids).toEqual(['paper-1', 'paper-3']);
		expect(result.review_document_ids).toEqual(['paper-2']);
		expect(result.decisions).toHaveLength(1);
		expect(result.decisions[0]).toMatchObject({
			document_id: 'paper-1',
			classification: 'likely_relevant',
			is_seed: true
		});
		expect(result.support_is_evidence).toBe(false);
		expect(normalizeObjectiveScope(null, 'col_fallback', 'obj_fallback')).toMatchObject({
			collection_id: 'col_fallback',
			objective_id: 'obj_fallback',
			recommended_document_ids: [],
			decisions: [],
			support_is_evidence: false
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

	it('builds the LlamaFactory Alpaca dataset export URL', () => {
		expect(objectiveFindingDatasetUrl('col/1', 'obj 1', 'llamafactory_alpaca')).toBe(
			'/api/v1/collections/col%2F1/objectives/obj%201/finding-dataset?format=llamafactory_alpaca'
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
			curated_finding: finding
		});

		expect(request).toHaveBeenCalledWith(
			'/collections/col_123/objectives/obj_1/findings/finding-1/curation',
			expect.objectContaining({ method: 'PUT' })
		);
	});
});
