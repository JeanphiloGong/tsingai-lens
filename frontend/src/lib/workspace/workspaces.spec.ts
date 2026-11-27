import { describe, expect, it } from 'vitest';
import { getWorkspaceStatusGroup, type Workspace } from './workspaces';

function workspace(
	status: string,
	documentStatuses: string[]
): Pick<Workspace, 'status' | 'documents'> {
	return {
		status,
		documents: documentStatuses.map((documentStatus, index) => ({
			document_id: `doc_${index}`,
			filename: `paper-${index}.pdf`,
			storage_key: `workspace/paper-${index}.pdf`,
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

describe('getWorkspaceStatusGroup', () => {
	it('recognizes uploaded workspaces with all ready documents', () => {
		expect(getWorkspaceStatusGroup(workspace('uploaded', ['ready', 'ready']))).toBe('ready');
	});

	it('keeps mixed document preparation in the pending state', () => {
		expect(getWorkspaceStatusGroup(workspace('uploaded', ['ready', 'uploaded']))).toBe('neutral');
	});

	it('prioritizes active preparation over the legacy workspace status', () => {
		expect(getWorkspaceStatusGroup(workspace('uploaded', ['ready', 'processing']))).toBe(
			'processing'
		);
	});

	it('does not hide an active workspace run behind ready documents', () => {
		expect(getWorkspaceStatusGroup(workspace('processing', ['ready', 'ready']))).toBe(
			'processing'
		);
	});

	it('prioritizes failed documents as attention required', () => {
		expect(getWorkspaceStatusGroup(workspace('uploaded', ['ready', 'failed']))).toBe('attention');
	});

	it('preserves an explicit completed workspace status', () => {
		expect(getWorkspaceStatusGroup(workspace('completed', ['ready']))).toBe('complete');
	});
});
