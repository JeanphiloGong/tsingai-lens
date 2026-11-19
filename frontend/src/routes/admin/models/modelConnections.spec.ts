import { describe, expect, it } from 'vitest';
import { configurationChanges, type ModelConnection, type ModelDraft } from './modelConnections';
const saved: ModelConnection = {
	connection_id: 'lab-a',
	display_name: 'Lab',
	base_url: 'http://localhost/v1',
	model: 'chat',
	kind: 'chat',
	api_key_configured: true,
	enabled: false,
	priority: 0,
	context_window_tokens: null,
	max_output_tokens: null,
	request_timeout_seconds: null,
	version: 3,
	created_at: '2026-11-14T00:00:00Z',
	updated_at: '2026-11-14T00:00:00Z'
};
const draft: ModelDraft = {
	display_name: 'Lab',
	base_url: saved.base_url,
	model: saved.model,
	kind: saved.kind,
	enabled: false,
	priority: 0,
	context_window_tokens: null,
	max_output_tokens: null,
	request_timeout_seconds: null,
	api_key: ''
};
describe('configuration save intent', () => {
	it('omits a blank key and combines new keys with ordinary changes', () => {
		expect(configurationChanges(saved, { ...draft, enabled: true }, false)).toEqual({
			expected_version: 3,
			enabled: true
		});
		expect(
			configurationChanges(
				saved,
				{ ...draft, display_name: 'New', api_key: 'synthetic-new' },
				false
			)
		).toEqual({ expected_version: 3, display_name: 'New', api_key: 'synthetic-new' });
	});
	it('clears only on explicit intent and lets new input replace a clearing draft', () => {
		expect(configurationChanges(saved, draft, true)).toEqual({
			expected_version: 3,
			api_key: null
		});
		expect(configurationChanges(saved, { ...draft, api_key: 'new' }, true)).toEqual({
			expected_version: 3,
			api_key: 'new'
		});
	});
});
