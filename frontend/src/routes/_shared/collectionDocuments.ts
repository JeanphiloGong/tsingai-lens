import { errorMessage, getApiErrorDetail, requestJson } from './api';

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
	const data = await requestJson(`/collections/${encodeURIComponent(collectionId)}/documents`, {
		method: 'GET'
	});

	if (
		!data ||
		typeof data !== 'object' ||
		!Array.isArray((data as Record<string, unknown>).items)
	) {
		throw new Error('Collection documents response is missing items.');
	}

	const items = (data as CollectionDocumentsResponse).items;
	if (items.some((item) => !item || typeof item.document_id !== 'string' || !item.document_id)) {
		throw new Error('Collection documents response is missing document_id.');
	}
	return data as CollectionDocumentsResponse;
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

	const uploaded = data as CollectionDocument;
	if (!uploaded || typeof uploaded.document_id !== 'string' || !uploaded.document_id) {
		throw new Error('Document upload response is missing document_id.');
	}
	return uploaded;
}

export function isDuplicateCollectionDocumentError(error: unknown) {
	return getApiErrorDetail(error) === 'document content already exists in collection';
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
