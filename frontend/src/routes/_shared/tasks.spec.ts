import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import { prepareCollectionDocument } from './tasks';

vi.mock('./api', () => ({ requestJson: vi.fn() }));
const request = vi.mocked(requestJson);

describe('document preparation API', () => {
	beforeEach(() => request.mockReset());

	it('starts preparation for one exact document and preserves task identity', async () => {
		request.mockResolvedValue({
			task_id: 'task_1',
			collection_id: 'col_1',
			document_id: 'doc_1',
			task_type: 'document_preparation',
			mode: 'fast',
			input_fingerprint: 'input-doc-1',
			status: 'queued',
			current_stage: 'queued',
			progress_percent: 0,
			errors: [],
			warnings: [],
			created_at: '2026-08-27T00:00:00Z',
			updated_at: '2026-08-27T00:00:00Z'
		});

		const result = await prepareCollectionDocument('col_1', 'doc_1', 'fast');

		expect(request).toHaveBeenCalledWith('/collections/col_1/documents/doc_1/preparation', {
			method: 'POST',
			body: JSON.stringify({ mode: 'fast' })
		});
		expect(result).toMatchObject({
			task_id: 'task_1',
			document_id: 'doc_1',
			mode: 'fast',
			input_fingerprint: 'input-doc-1'
		});
	});
});
