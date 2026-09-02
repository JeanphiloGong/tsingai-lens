import { page as browserPage } from 'vitest/browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

import Editor from './EvidenceAuthoringEditor.svelte';

const fetchMock = vi.fn();

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockResolvedValue(
		new Response(
			JSON.stringify({
				analysis: { analysis_version: 2, status: 'succeeded' },
				evidence: {
					evidence_id: 'evidence-manual-1',
					analysis_version: 2,
					origin: 'human_authored',
					supports_finding: true
				}
			}),
			{ status: 201, headers: { 'Content-Type': 'application/json' } }
		)
	);
	vi.stubGlobal('fetch', fetchMock);
});

const sourceEvidence = {
	collection_id: 'col-1',
	objective_id: 'obj-1',
	analysis_version: 1,
	evidence_id: 'evidence-1',
	document_id: 'paper-1',
	source_kind: 'text_window',
	source_ref: 'block-result',
	source_excerpt: 'Elongation decreased as the combined energy input increased.',
	page_numbers: [5],
	related_source_refs: [],
	evidence_role: 'direct_result',
	selection_reason: null,
	selection_status: 'extracted',
	changed_variables: [
		{ name: 'energy input', baseline_value: 40, target_value: 60, unit: 'J/mm3' }
	],
	comparison: {
		baseline_label: '40 J/mm3',
		target_label: '60 J/mm3',
		axis_names: ['energy input'],
		comparable: true,
		incomparability_reasons: []
	},
	reported_result: {
		outcome: 'elongation',
		value: 7.8,
		baseline_value: 10.1,
		target_value: 7.8,
		unit: '%',
		direction: 'decrease' as const,
		result_text: 'Elongation decreased as the combined energy input increased.'
	},
	attribution_scope: 'association_only' as const,
	scientific_context: { material: [], sample: [], process: [], test: [] },
	anchor_ids: [],
	resolution_status: 'resolved',
	failure_reason: null,
	confidence: 0.9,
	supports_finding: true
};

describe('Evidence authoring editor', () => {
	it('prefills exact Source facts and publishes a new version', async () => {
		const onSaved = vi.fn();
		render(Editor, {
			collectionId: 'col-1',
			objectiveId: 'obj-1',
			analysisVersion: 1,
			sourceEvidence,
			documentTitle: 'LPBF energy input study',
			onSaved
		});

		await expect
			.element(browserPage.getByRole('heading', { name: '创建 Evidence' }))
			.toBeInTheDocument();
		await expect.element(browserPage.getByText('LPBF energy input study')).toBeInTheDocument();
		await expect
			.element(browserPage.getByRole('textbox').nth(0))
			.toHaveValue(sourceEvidence.source_excerpt);
		await expect.element(browserPage.getByRole('textbox').nth(1)).toHaveValue('energy input');
		await expect.element(browserPage.getByRole('textbox').nth(2)).toHaveValue('40');
		await expect.element(browserPage.getByRole('textbox').nth(3)).toHaveValue('60');

		await browserPage.getByRole('button', { name: '确认创建并发布' }).click();
		await vi.waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [path, request] = fetchMock.mock.calls[0] as [string, RequestInit];
		expect(path).toBe('/api/v1/collections/col-1/objectives/obj-1/evidence');
		expect(request.method).toBe('POST');
		const payload = JSON.parse(String(request.body));
		expect(payload.source_ref).toBe('block-result');
		expect(payload.source_analysis_version).toBe(1);
		expect(payload.changed_variables[0].name).toBe('energy input');
	});

	it('keeps the draft and reports a server validation failure', async () => {
		fetchMock.mockResolvedValueOnce(
			new Response(
				JSON.stringify({ detail: 'Source excerpt is not contained in the canonical Source' }),
				{
					status: 409,
					headers: { 'Content-Type': 'application/json' }
				}
			)
		);
		render(Editor, {
			collectionId: 'col-1',
			objectiveId: 'obj-1',
			analysisVersion: 1,
			sourceEvidence,
			documentTitle: 'LPBF energy input study'
		});

		await browserPage.getByRole('button', { name: '确认创建并发布' }).click();
		await expect
			.element(browserPage.getByRole('alert'))
			.toHaveTextContent('Source excerpt is not contained');
		await expect
			.element(browserPage.getByRole('textbox').nth(0))
			.toHaveValue(sourceEvidence.source_excerpt);
	});
});
