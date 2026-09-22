import { expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ResearchProgress from './ResearchProgress.svelte';

it('keeps actual document and passage visible without a generated research plan', async () => {
	const reading = { toolCallId: 'read-1', kind: 'passage' as const, status: 'reading' as const,
		title: 'LPBF Ti-6Al-4V', page: '7', heading: 'Methods', excerpt: 'Annealing conditions', query: '' };
	const screen = render(ResearchProgress, { progress: { phase: 'tools', cycle_index: 2 }, readings: [reading] });
	await expect.element(screen.getByTestId('current-reading')).toBeVisible();
	await expect.element(screen.getByText('LPBF Ti-6Al-4V')).toBeVisible();
	await expect.element(screen.getByText('Methods', { exact: true })).toBeVisible();
	expect(screen.container.querySelector('.research-plan')).toBeNull();
	await screen.rerender({ readings: [{ ...reading, status: 'failed' }] });
	expect(screen.container.querySelector('.reading-current.failed')).not.toBeNull();
});
