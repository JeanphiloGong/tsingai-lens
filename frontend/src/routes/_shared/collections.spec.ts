import { describe, expect, it } from 'vitest';
import { getCollectionStatusGroup, type Collection } from './collections';

function collection(
	status: string,
	documentStatuses: string[]
): Pick<Collection, 'status' | 'documents'> {
	return {
		status,
		documents: documentStatuses.map((documentStatus, index) => ({
			document_id: `doc_${index}`,
			original_filename: `paper-${index}.pdf`,
			stored_filename: `paper-${index}.pdf`,
			storage_key: `collection/paper-${index}.pdf`,
			sha256: 'a'.repeat(64),
			media_type: 'application/pdf',
			status: documentStatus,
			size_bytes: 1,
			created_at: '2026-08-27T00:00:00Z',
			updated_at: '2026-08-27T00:00:00Z',
			parser_version: null,
			document_analysis_version: null,
			source_fingerprint: null,
			profile_fingerprint: null,
			preparation_fingerprint: null
		}))
	};
}

describe('getCollectionStatusGroup', () => {
	it('recognizes uploaded collections with all ready documents', () => {
		expect(getCollectionStatusGroup(collection('uploaded', ['ready', 'ready']))).toBe('ready');
	});

	it('keeps mixed document preparation in the pending state', () => {
		expect(getCollectionStatusGroup(collection('uploaded', ['ready', 'uploaded']))).toBe('neutral');
	});

	it('prioritizes active preparation over the legacy collection status', () => {
		expect(getCollectionStatusGroup(collection('uploaded', ['ready', 'processing']))).toBe(
			'processing'
		);
	});

	it('does not hide an active collection run behind ready documents', () => {
		expect(getCollectionStatusGroup(collection('processing', ['ready', 'ready']))).toBe(
			'processing'
		);
	});

	it('prioritizes failed documents as attention required', () => {
		expect(getCollectionStatusGroup(collection('uploaded', ['ready', 'failed']))).toBe('attention');
	});

	it('preserves an explicit completed collection status', () => {
		expect(getCollectionStatusGroup(collection('completed', ['ready']))).toBe('complete');
	});
});
