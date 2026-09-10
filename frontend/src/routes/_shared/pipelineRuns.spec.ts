import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import {
	formCollectionResearchQuestions,
	listCollectionPipelineRuns,
	prepareCollectionDocument
} from './pipelineRuns';

vi.mock('./api', () => ({ requestJson: vi.fn() }));
const request = vi.mocked(requestJson);

describe('document preparation API', () => {
	beforeEach(() => request.mockReset());

	it('starts preparation for one exact document and preserves run identity', async () => {
		request.mockResolvedValue({
			run_id: 'run_1',
			collection_id: 'col_1',
			scope_type: 'document',
			scope_id: 'doc_1',
			pipeline_name: 'document_preparation',
			mode: 'standard',
			input_fingerprint: 'input-doc-1',
			status: 'queued',
			current_node: 'queued',
			progress_percent: 0,
			errors: [],
			warnings: [],
			created_at: '2026-08-27T00:00:00Z',
			updated_at: '2026-08-27T00:00:00Z'
		});

		const result = await prepareCollectionDocument('col_1', 'doc_1');

		expect(request).toHaveBeenCalledWith('/collections/col_1/documents/doc_1/preparation', {
			method: 'POST'
		});
		expect(result).toMatchObject({
			run_id: 'run_1',
			scope_id: 'doc_1',
			mode: 'standard',
			input_fingerprint: 'input-doc-1'
		});
	});

	it('queues research-question formation as a collection run', async () => {
		request.mockResolvedValue({
			run_id: 'run_discovery',
			collection_id: 'col_1',
			scope_type: 'collection',
			scope_id: 'col_1',
			pipeline_name: 'objective_discovery',
			mode: 'standard',
			input_fingerprint: 'scope-1',
			status: 'queued',
			current_node: 'queued',
			progress_percent: 0,
			errors: [],
			warnings: [],
			created_at: '2026-08-31T00:00:00Z',
			updated_at: '2026-08-31T00:00:00Z'
		});

		const result = await formCollectionResearchQuestions('col_1', ['doc_1', 'doc_2']);

		expect(request).toHaveBeenCalledWith('/collections/col_1/objective-discovery', {
			method: 'POST',
			body: JSON.stringify({ document_ids: ['doc_1', 'doc_2'] })
		});
		expect(result).toMatchObject({
			run_id: 'run_discovery',
			pipeline_name: 'objective_discovery',
			status: 'queued'
		});
	});

	it('normalizes collection history as compact run summaries', async () => {
		request.mockResolvedValue({
			collection_id: 'col_1',
			count: 1,
			items: [
				{
					run_id: 'run_1',
					pipeline_name: 'document_preparation',
					scope_type: 'document',
					scope_id: 'doc_1',
					status: 'running',
					current_node: 'document_profile',
					progress_percent: 45,
					progress_detail: {
						phase: 'document_profile',
						message: 'Classifying the paper.'
					},
					errors: [],
					warnings: [],
					updated_at: '2026-09-08T00:00:00Z'
				}
			]
		});

		const result = await listCollectionPipelineRuns('col_1', { limit: 100 });

		expect(request).toHaveBeenCalledWith('/collections/col_1/pipeline-runs?limit=100&offset=0', {
			method: 'GET'
		});
		expect(result.items[0]).toEqual({
			run_id: 'run_1',
			pipeline_name: 'document_preparation',
			scope_type: 'document',
			scope_id: 'doc_1',
			status: 'running',
			current_node: 'document_profile',
			progress_percent: 45,
			progress_detail: {
				phase: 'document_profile',
				current: null,
				total: null,
				unit: null,
				message: 'Classifying the paper.',
				active_document_id: null,
				active_objective_id: null
			},
			errors: [],
			warnings: [],
			updated_at: '2026-09-08T00:00:00Z'
		});
	});
});
