import { beforeEach, describe, expect, it, vi } from 'vitest';

import { requestJson } from './api';
import { listCollectionDocuments, uploadCollectionDocuments } from './collectionDocuments';

vi.mock('./api', async (importActual) => ({
	...(await importActual<typeof import('./api')>()),
	requestJson: vi.fn()
}));
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

	it('continues after a failed file and returns only failed files for retry', async () => {
		const first = new File(['pdf'], 'first.pdf');
		const damaged = new File(['pdf'], 'damaged.pdf');
		const last = new File(['pdf'], 'last.pdf');
		request
			.mockResolvedValueOnce({
				document_id: 'doc_1',
				original_filename: 'first.pdf',
				stored_filename: 'first.pdf',
				storage_key: 'col_1/input/first.pdf',
				sha256: 'a'.repeat(64),
				status: 'stored',
				size_bytes: 3,
				created_at: '2026-08-27T00:00:00Z',
				updated_at: '2026-08-27T00:00:00Z'
			})
			.mockRejectedValueOnce(new Error('Upload failed.'))
			.mockResolvedValueOnce({
				document_id: 'doc_2',
				original_filename: 'last.pdf',
				stored_filename: 'last.pdf',
				storage_key: 'col_1/input/last.pdf',
				sha256: 'b'.repeat(64),
				status: 'stored',
				size_bytes: 3,
				created_at: '2026-08-27T00:00:00Z',
				updated_at: '2026-08-27T00:00:00Z'
			});

		const result = await uploadCollectionDocuments('col_1', [first, damaged, last]);

		expect(request).toHaveBeenCalledTimes(3);
		expect(result.count).toBe(2);
		expect(result.items.map((item) => item.original_filename)).toEqual(['first.pdf', 'last.pdf']);
		expect(result.failures).toEqual([{ file: damaged, message: 'Upload failed.' }]);
	});

	it('rejects a malformed list response instead of treating it as an empty collection', async () => {
		request.mockResolvedValue({ status: 'temporarily_unavailable' });

		await expect(listCollectionDocuments('col_1')).rejects.toThrow(
			'Collection documents response is missing items.'
		);
	});
});
