import { errorMessage, getApiErrorReason, requestJson } from './api';

export type CollectionDocument = {
	document_id: string;
	original_filename: string;
	stored_filename: string;
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

export type CollectionDocumentsResponse = {
	count: number;
	items: CollectionDocument[];
};

export type CollectionDocumentUploadFailure = {
	file: File;
	message: string;
};

export type CollectionDocumentUploadResponse = CollectionDocumentsResponse & {
	failures: CollectionDocumentUploadFailure[];
};

export async function listCollectionDocuments(
	collectionId: string
): Promise<CollectionDocumentsResponse> {
	return requestJson(`/collections/${encodeURIComponent(collectionId)}/documents`, {
		method: 'GET'
	}) as Promise<CollectionDocumentsResponse>;
}

export async function uploadCollectionDocument(
	collectionId: string,
	file: File,
	reuseExisting = false
) {
	const formData = new FormData();
	formData.append('file', file);
	const query = reuseExisting ? '?reuse_existing=true' : '';
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents${query}`,
		{
			method: 'POST',
			body: formData
		}
	);

	return data as CollectionDocument;
}

export function isDuplicateCollectionDocumentError(error: unknown) {
	return getApiErrorReason(error) === 'document_content_already_exists';
}

export async function uploadCollectionDocuments(
	collectionId: string,
	files: File[]
): Promise<CollectionDocumentUploadResponse> {
	const items: CollectionDocument[] = [];
	const failures: CollectionDocumentUploadFailure[] = [];
	for (const file of files) {
		try {
			items.push(await uploadCollectionDocument(collectionId, file));
		} catch (error) {
			failures.push({ file, message: errorMessage(error) });
		}
	}

	return { count: items.length, items, failures };
}
