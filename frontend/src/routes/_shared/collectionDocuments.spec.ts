import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import { listCollectionDocuments } from './collectionDocuments';

vi.mock('./api', () => ({ requestJson: vi.fn() }));
const request = vi.mocked(requestJson);

describe('collection document API', () => {
	beforeEach(() => request.mockReset());

	it('preserves the current preparation versions and fingerprint', async () => {
		request.mockResolvedValue({
			items: [
				{
					document_id: 'doc_1',
					original_filename: 'paper.pdf',
					stored_filename: 'stored.pdf',
					storage_key: 'col_1/input/stored.pdf',
					sha256: 'a'.repeat(64),
					media_type: 'application/pdf',
					status: 'ready',
					size_bytes: 2048,
					created_at: '2026-08-27T00:00:00Z',
					updated_at: '2026-08-27T00:01:00Z',
					parser_version: 'source-runtime.v2',
					document_analysis_version: 'paper-map.v3',
					source_fingerprint: 'source-fingerprint-doc-1',
					profile_fingerprint: 'profile-fingerprint-doc-1',
					preparation_fingerprint: 'fingerprint-doc-1'
				}
			]
		});

		const result = await listCollectionDocuments('col_1');

		expect(request).toHaveBeenCalledWith('/collections/col_1/documents', { method: 'GET' });
		expect(result.items[0]).toMatchObject({
			document_id: 'doc_1',
			status: 'ready',
			parser_version: 'source-runtime.v2',
			document_analysis_version: 'paper-map.v3',
			source_fingerprint: 'source-fingerprint-doc-1',
			profile_fingerprint: 'profile-fingerprint-doc-1',
			preparation_fingerprint: 'fingerprint-doc-1'
		});
	});
});
