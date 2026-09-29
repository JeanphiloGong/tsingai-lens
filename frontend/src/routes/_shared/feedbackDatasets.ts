import { requestJson } from './api';

export type FeedbackDatasetTaskType = 'sft' | 'preference' | 'evaluation';

export type FeedbackDataset = {
	dataset_id: string;
	collection_id: string;
	name: string;
	task_type: FeedbackDatasetTaskType;
	construction_spec: Record<string, unknown>;
	spec_version: number;
	created_by: string;
	created_at: string;
	updated_at: string;
};

function datasetPath(datasetId = '') {
	return `/feedback-datasets${datasetId ? `/${encodeURIComponent(datasetId)}` : ''}`;
}

export async function createFeedbackDataset(
	collectionId: string,
	name: string,
	constructionSpec: Record<string, unknown> = {}
) {
	return (await requestJson(datasetPath(), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			collection_id: collectionId,
			name,
			task_type: 'sft',
			construction_spec: constructionSpec
		})
	})) as FeedbackDataset;
}

export async function fetchFeedbackDatasets(
	collectionId: string,
	options: { limit?: number; offset?: number } = {}
) {
	const params = new URLSearchParams({
		collection_id: collectionId,
		limit: String(options.limit ?? 50),
		offset: String(options.offset ?? 0)
	});
	return (await requestJson(`${datasetPath()}?${params.toString()}`, { method: 'GET' })) as {
		items: FeedbackDataset[];
		limit: number;
		offset: number;
	};
}

export async function fetchFeedbackDataset(datasetId: string) {
	return (await requestJson(datasetPath(datasetId), { method: 'GET' })) as FeedbackDataset;
}
