import { expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ResearchProgress from './ResearchProgress.svelte';

it('keeps retry counts in expanded progress while the main line stays brief', async () => {
	const screen = render(ResearchProgress, {
		progress: { phase: 'model_retry', retry_attempt: 2, retry_delay_ms: 2500 }
	});
	await expect.element(screen.getByRole('status')).toHaveTextContent(/Waiting for the research model|正在等待研究模型/);
	await expect.element(screen.getByText(/Retry 2 in 3s|3 秒后第 2 次重试/)).not.toBeInTheDocument();
	await screen.getByRole('button', { name: /Toggle research progress history|展开或收起研究进度历史/ }).click();
	await expect.element(screen.getByText(/Retry 2 in 3s|3 秒后第 2 次重试/)).toBeVisible();
	await screen.rerender({ progress: { phase: 'context_compaction' } });
	await expect.element(screen.getByRole('status')).toHaveTextContent(/Preserving research progress|正在整理并保留研究进展/);
});

it('shows model cycle numbers only in the progress details', async () => {
	const screen = render(ResearchProgress, { progress: { phase: 'model', cycle_index: 19 } });
	await expect.element(screen.getByRole('status')).toHaveTextContent(/Planning research|正在规划研究/);
	expect(screen.getByRole('status').element().textContent).not.toContain('19');
	await screen.getByRole('button', { name: /Toggle research progress history|展开或收起研究进度历史/ }).click();
	await expect.element(screen.getByRole('list', { name: /Research stage history|研究阶段历史/ })).toHaveTextContent('19');
});

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
	await screen.rerender({
		progress: {
			phase: 'tools',
			execution_plan: {
				plan_id: 'plan-1',
				plan_version: 1,
				status: 'in_progress',
				model_status: 'in_progress',
				steps: [{ step_id: 'read', action: 'Read the Source', status: 'in_progress' }]
			}
		},
		readings: [reading]
	});
	await expect.element(screen.getByTestId('progress-plan')).toBeVisible();
	await expect.element(screen.getByText('Read the Source')).toBeVisible();
	await screen.rerender({ readings: [{ ...reading, status: 'failed' }] });
	expect(screen.container.querySelector('.reading-current.failed')).not.toBeNull();
});
