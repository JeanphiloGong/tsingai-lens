export type ModelConnection = {
	connection_id: string;
	display_name: string;
	base_url: string;
	model: string;
	kind: 'chat' | 'embedding';
	api_key_configured: boolean;
	enabled: boolean;
	priority: number;
	context_window_tokens: number | null;
	max_output_tokens: number | null;
	request_timeout_seconds: number | null;
	version: number;
	created_at: string;
	updated_at: string;
};
export type ConnectionPage = {
	items: ModelConnection[];
	total: number;
	limit: number;
	offset: number;
};
export type ProbeResult = {
	connection_id: string;
	tested_version: number;
	success: boolean;
	latency_ms: number;
	reason: string | null;
};
export type ModelDraft = {
	display_name: string;
	base_url: string;
	model: string;
	kind: ModelConnection['kind'];
	enabled: boolean;
	priority: number;
	context_window_tokens: number | null;
	max_output_tokens: number | null;
	request_timeout_seconds: number | null;
	api_key: string;
};

/** Only explicit key intent enters the PATCH; a blank input preserves the saved key. */
export function configurationChanges(saved: ModelConnection, draft: ModelDraft, clearKey: boolean) {
	const changes: Record<string, unknown> = { expected_version: saved.version };
	for (const field of [
		'display_name',
		'enabled',
		'priority',
		'context_window_tokens',
		'max_output_tokens',
		'request_timeout_seconds'
	] as const) {
		const value = draft[field] ?? null;
		if (value !== saved[field]) changes[field] = value;
	}
	if (draft.api_key !== '') changes.api_key = draft.api_key;
	else if (clearKey) changes.api_key = null;
	return changes;
}
