import { downloadBlob, requestJson } from './api';

export type DatasetType = 'evaluation' | 'sft' | 'preference';
export type DatasetSelection = { case_id: string };

export type DatasetSnapshot = {
	dataset_id: string;
	owner_id: string;
	collection_id: string;
	dataset_type: DatasetType;
	rows: Array<Record<string, unknown>>;
	exclusions: Array<Record<string, unknown>>;
	provenance: Record<string, unknown>;
	manifest: Record<string, unknown>;
	manifest_digest: string;
	provenance_digest: string;
	content_digest: string;
	row_count: number;
	excluded_count: number;
	is_empty: boolean;
	created_at: string;
};

export type DatasetSnapshotSummary = Pick<
	DatasetSnapshot,
	| 'dataset_id'
	| 'collection_id'
	| 'dataset_type'
	| 'manifest_digest'
	| 'provenance_digest'
	| 'content_digest'
	| 'row_count'
	| 'excluded_count'
	| 'is_empty'
	| 'created_at'
>;

function datasetPath(datasetId = '') {
	return `/dataset-snapshots${datasetId ? `/${encodeURIComponent(datasetId)}` : ''}`;
}

export async function createDatasetSnapshot(
	collectionId: string,
	datasetType: DatasetType,
	items: DatasetSelection[]
) {
	return (await requestJson(datasetPath(), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			collection_id: collectionId,
			dataset_type: datasetType,
			items
		})
	})) as DatasetSnapshot;
}

export async function fetchDatasetSnapshots(
	collectionId: string,
	options: { datasetType?: DatasetType; limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams({ collection_id: collectionId });
	if (options.datasetType) params.set('dataset_type', options.datasetType);
	params.set('limit', String(options.limit ?? 50));
	params.set('offset', String(options.offset ?? 0));
	return (await requestJson(`${datasetPath()}?${params.toString()}`, { method: 'GET' })) as {
		items: DatasetSnapshotSummary[];
		limit: number;
		offset: number;
	};
}

export async function fetchDatasetSnapshot(datasetId: string) {
	return (await requestJson(datasetPath(datasetId), { method: 'GET' })) as DatasetSnapshot;
}

export async function downloadDatasetSnapshot(datasetId: string) {
	await downloadBlob(`${datasetPath(datasetId)}/jsonl`, `${datasetId}.jsonl`);
}
