import { requestJson } from '../../routes/_shared/api';

export type ModelConnectionChoice = {
	connection_id: string;
	display_name: string;
	model: string;
};

export async function fetchModelConnections(signal?: AbortSignal) {
	return (await requestJson('/model-connections', { signal, method: 'GET' })) as {
		items: ModelConnectionChoice[];
	};
}
