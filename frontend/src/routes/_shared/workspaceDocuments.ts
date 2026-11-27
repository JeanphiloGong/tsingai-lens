import { errorMessage, getApiErrorReason, requestJson } from './api';

export type WorkspaceDocument = {
	document_id: string;
	filename: string;
	storage_key: string;
	sha256: string;
	media_type?: string | null;
	status: string;
	size_bytes: number;
	created_at: string;
	updated_at: string;
	parser_version: string | null;
	document_analysis_version: string | null;
	source_fingerprint: string | null;
	profile_fingerprint: string | null;
	preparation_fingerprint: string | null;
};

export type WorkspaceDocumentsResponse = {
	count: number;
	items: WorkspaceDocument[];
};

export type WorkspaceDocumentUploadFailure = {
	file: File;
	message: string;
};

export type WorkspaceDocumentUploadResponse = WorkspaceDocumentsResponse & {
	failures: WorkspaceDocumentUploadFailure[];
};

export async function listWorkspaceDocuments(
	workspaceId: string
): Promise<WorkspaceDocumentsResponse> {
	return requestJson(`/workspaces/${encodeURIComponent(workspaceId)}/documents`, {
		method: 'GET'
	}) as Promise<WorkspaceDocumentsResponse>;
}

export async function uploadWorkspaceDocument(
	workspaceId: string,
	file: File,
	reuseExisting = false
) {
	const formData = new FormData();
	formData.append('file', file);
	const query = reuseExisting ? '?reuse_existing=true' : '';
	const data = await requestJson(
		`/workspaces/${encodeURIComponent(workspaceId)}/documents${query}`,
		{
			method: 'POST',
			body: formData
		}
	);

	return data as WorkspaceDocument;
}

export function isDuplicateWorkspaceDocumentError(error: unknown) {
	return getApiErrorReason(error) === 'document_content_already_exists';
}

export async function uploadWorkspaceDocuments(
	workspaceId: string,
	files: File[]
): Promise<WorkspaceDocumentUploadResponse> {
	const items: WorkspaceDocument[] = [];
	const failures: WorkspaceDocumentUploadFailure[] = [];
	for (const file of files) {
		try {
			items.push(await uploadWorkspaceDocument(workspaceId, file));
		} catch (error) {
			failures.push({ file, message: errorMessage(error) });
		}
	}

	return { count: items.length, items, failures };
}
