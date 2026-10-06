import { expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ResearchProgress from './ResearchProgress.svelte';

it('keeps actual document and passage visible without a generated research plan', async () => {
	const reading = {
		toolCallId: 'read-1',
		kind: 'passage' as const,
		status: 'reading' as const,
		title: 'LPBF Ti-6Al-4V',
		href: '/collections/c1/documents/p1?source_ref=methods',
		page: '7',
		heading: 'Methods',
		excerpt: 'Annealing conditions',
		query: ''
	};
	const screen = render(ResearchProgress, {
		progress: {
			phase: 'tools',
			cycle_index: 2,
			selected_capability_names: ['read_source'],
			requested_tool_count: 2,
			executed_tool_count: 1
		},
		readings: [reading]
	});
	await expect.element(screen.getByTestId('current-reading')).toBeVisible();
	await expect.element(screen.getByText('LPBF Ti-6Al-4V')).toBeVisible();
	await expect.element(screen.getByText('Methods', { exact: true })).toBeVisible();
	await expect.element(screen.getByText(/Current action:|当前动作：/)).toBeVisible();
	await expect
		.element(screen.getByText(/1 \/ 2 research actions|已完成 1 \/ 2 个研究动作/))
		.toBeVisible();
	expect(screen.container.querySelector('.progress-plan')).toBeNull();
	await expect
		.element(screen.getByRole('link', { name: /Open source location|打开原文位置/ }))
		.toHaveAttribute('href', reading.href);
	await screen.rerender({ readings: [{ ...reading, status: 'failed' }] });
	expect(screen.container.querySelector('.reading-current.failed')).not.toBeNull();
});
