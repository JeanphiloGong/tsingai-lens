import { page } from 'vitest/browser';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { language } from '../../../_shared/i18n';
import Summary from './FindingEvidenceSummary.svelte';

const fetchMock = vi.fn();
const props = { collectionId: 'col-1', objectiveId: 'obj-1', findingId: 'f-1', analysisVersion: 2 };
const payload = {
	collection_id: 'col-1',
	objective_id: 'obj-1',
	finding_id: 'f-1',
	analysis_version: 2,
	language: 'en',
	model: 'test-model',
	text: 'Annealing was associated with higher strength.',
	citation_ids: ['evidence:ev-1'],
	references: [
		{
			id: 'evidence:ev-1',
			kind: 'evidence',
			label: 'Table 7',
			document_id: 'paper-1',
			source_ref: 'table-7',
			page_numbers: [7],
			source_excerpt: 'Strength was 620 MPa.'
		}
	]
};

beforeEach(() => {
	language.set('en');
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => language.set('en'));

it('generates one paragraph on opening and links to its exact Source', async () => {
	fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
	render(Summary, props);
	expect(fetchMock).not.toHaveBeenCalled();
	await page.getByText('AI summary', { exact: true }).click();
	await expect.element(page.getByText(payload.text)).toBeInTheDocument();
	await expect
		.element(page.getByRole('heading', { name: 'Main evidence' }))
		.not.toBeInTheDocument();
	await expect
		.element(page.getByRole('heading', { name: 'Differences and conditions' }))
		.not.toBeInTheDocument();
	await expect
		.element(page.getByRole('heading', { name: 'Current limitations' }))
		.not.toBeInTheDocument();
	await expect.element(page.getByText('test-model', { exact: false })).toBeInTheDocument();
	await expect
		.element(page.getByRole('link', { name: '[1]' }))
		.toHaveAttribute('href', expect.stringContaining('source_ref=table-7'));
	expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
		analysis_version: 2,
		language: 'en'
	});
	await page.getByText('AI summary', { exact: true }).click();
	await page.getByText('AI summary', { exact: true }).click();
	await expect.element(page.getByText(payload.text)).toBeVisible();
	expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('keeps an explicit retry when summary generation fails', async () => {
	fetchMock.mockResolvedValue(
		new Response(JSON.stringify({ detail: { code: 'summary_input_too_large' } }), { status: 503 })
	);
	render(Summary, props);
	await page.getByText('AI summary', { exact: true }).click();
	await expect.element(page.getByRole('alert')).toHaveTextContent('Too much content');
	await expect.element(page.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
	fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect.element(page.getByText(payload.text)).toBeInTheDocument();
	await expect.element(page.getByRole('alert')).not.toBeInTheDocument();
});

it('discards a response if language changes during generation', async () => {
	let finish!: (response: Response) => void;
	fetchMock.mockReturnValue(
		new Promise<Response>((resolve) => {
			finish = resolve;
		})
	);
	render(Summary, props);
	await page.getByText('AI summary', { exact: true }).click();
	await expect.element(page.getByRole('status')).toHaveTextContent('Summarizing...');
	language.set('zh');
	finish(new Response(JSON.stringify(payload), { status: 200 }));
	await expect.element(page.getByText('AI 总结', { exact: true })).toBeInTheDocument();
	await expect.element(page.getByText(payload.text)).not.toBeInTheDocument();
});

it('clears a completed summary when the Finding or analysis version changes', async () => {
	fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
	const view = render(Summary, props);
	await page.getByText('AI summary', { exact: true }).click();
	await expect.element(page.getByText(payload.text)).toBeInTheDocument();
	await view.rerender({ findingId: 'f-2', analysisVersion: 3 });
	await expect.element(page.getByText(payload.text)).not.toBeInTheDocument();
	expect(fetchMock).toHaveBeenCalledTimes(1);
});
