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

function normalizeCollectionDocument(item: unknown): CollectionDocument | null {
	if (!item || typeof item !== 'object') return null;
	const record = item as Record<string, unknown>;
	const documentId = String(record.document_id ?? '').trim();
	if (!documentId) return null;

	return {
		document_id: documentId,
		original_filename: String(record.original_filename ?? ''),
		stored_filename: String(record.stored_filename ?? ''),
		storage_key: String(record.storage_key ?? ''),
		sha256: String(record.sha256 ?? ''),
		media_type: typeof record.media_type === 'string' ? record.media_type : null,
		status: String(record.status ?? 'unknown'),
		size_bytes:
			typeof record.size_bytes === 'number' ? record.size_bytes : Number(record.size_bytes ?? 0),
		created_at: String(record.created_at ?? ''),
		updated_at: String(record.updated_at ?? record.created_at ?? ''),
		parser_version: typeof record.parser_version === 'string' ? record.parser_version : null,
		document_analysis_version:
			typeof record.document_analysis_version === 'string'
				? record.document_analysis_version
				: null,
		source_fingerprint:
			typeof record.source_fingerprint === 'string' ? record.source_fingerprint : null,
		profile_fingerprint:
			typeof record.profile_fingerprint === 'string' ? record.profile_fingerprint : null,
		preparation_fingerprint:
			typeof record.preparation_fingerprint === 'string' ? record.preparation_fingerprint : null
	};
}

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

	const items = ((data as Record<string, unknown>).items as unknown[])
		.map((item) => normalizeCollectionDocument(item))
		.filter((item): item is CollectionDocument => item !== null);

	return { count: items.length, items };
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

	const uploaded = normalizeCollectionDocument(data);
	if (!uploaded) {
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
