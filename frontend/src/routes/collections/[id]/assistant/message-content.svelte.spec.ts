import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import MessageContent from './MessageContent.svelte';

describe('research reply Markdown', () => {
	it('renders comparison cells, headings, ordered steps, links, and code without changing values', async () => {
		const screen = render(MessageContent, {
			content: [
				'## LPBF 316L comparison',
				'',
				'| Paper | UTS (MPa) |',
				'| :--- | ---: |',
				'| A | **610** |',
				'| B | 580 |',
				'',
				'1. Check the test direction.',
				'2. Compare the same material state.',
				'',
				'> Different heat treatments prevent an isolated causal claim.',
				'',
				'[Source](/collections/col_123/documents/doc_1)',
				'',
				'```python',
				'energy = power / (speed * hatch * layer)',
				'```'
			].join('\n')
		});
		await expect
			.element(screen.getByRole('heading', { name: 'LPBF 316L comparison' }))
			.toBeVisible();
		await expect.element(screen.getByRole('cell', { name: '610' })).toBeVisible();
		expect(screen.container.querySelectorAll('tbody tr')).toHaveLength(2);
		expect(screen.container.querySelector('td strong')?.textContent).toBe('610');
		expect(screen.container.querySelector('th:last-child')?.getAttribute('style')).toContain(
			'right'
		);
		expect(screen.container.querySelectorAll('ol > li')).toHaveLength(2);
		expect(screen.container.querySelector('blockquote')?.textContent).toContain('causal claim');
		await expect
			.element(screen.getByRole('link', { name: 'Source' }))
			.toHaveAttribute('href', '/collections/col_123/documents/doc_1');
		expect(screen.container.querySelector('pre code.language-python')?.textContent).toBe(
			'energy = power / (speed * hatch * layer)\n'
		);
	});

	it.each([
		[String.raw`Energy $E_v = \frac{P}{vht}$ depends on four parameters.`, false],
		[String.raw`Energy \(E_v = \frac{P}{vht}\) depends on four parameters.`, false],
		[String.raw`$$E_v = \frac{P}{vht}$$`, true],
		[String.raw`\[E_v = \frac{P}{vht}\]`, true]
	])('renders accessible math for %s', async (content, display) => {
		const screen = render(MessageContent, { content });
		await expect.element(screen.getByTestId('message-content')).toBeVisible();
		expect(screen.container.querySelectorAll('.katex')).toHaveLength(1);
		expect(screen.container.querySelector('math')).not.toBeNull();
		expect(screen.container.querySelector('annotation')?.textContent).toContain('\\frac{P}{vht}');
		expect(Boolean(screen.container.querySelector('.katex-display'))).toBe(display);
		expect(screen.container.querySelector('.katex-error')).toBeNull();
	});

	it('keeps incomplete streamed math readable before rendering the closed formula', async () => {
		const screen = render(MessageContent, { content: '$$\nE_v = \\frac{P}{', streaming: true });
		await expect.element(screen.getByTestId('message-content')).toBeVisible();
		expect(screen.container.querySelector('.math-pending')?.textContent).toBe('E_v = \\frac{P}{');
		expect(screen.container.querySelector('.katex-error')).toBeNull();
		await screen.rerender({ content: '$$\nE_v = \\frac{P}{vht}\n$$', streaming: true });
		expect(screen.container.querySelector('math')).not.toBeNull();
		expect(screen.container.querySelector('.math-pending')).toBeNull();
		await screen.rerender({ streaming: false });
		expect(screen.container.querySelector('.stream-cursor')).toBeNull();
	});

	it('updates a streamed table and code fence without losing rows or parsing literal code as math', async () => {
		const screen = render(MessageContent, { content: '| Paper | UTS |\n| ---', streaming: true });
		await screen.rerender({ content: '| Paper | UTS |\n| --- | --- |\n| A | 610 |\n| B | 580 |' });
		await expect.element(screen.getByRole('cell', { name: '580' })).toBeVisible();
		await screen.rerender({ content: '```text\n$x^2$ <script>alert(1)</script>' });
		expect(screen.container.querySelector('pre code')?.textContent).toContain('$x^2$ <script>');
		expect(screen.container.querySelector('math, script')).toBeNull();
	});

	it('keeps currency and escaped math delimiters literal', async () => {
		const screen = render(MessageContent, {
			content: 'The samples cost $20 and $30.\n\nLiteral \\$x\\$ and `$y$`.'
		});
		await expect.element(screen.getByTestId('message-content')).toBeVisible();
		expect(screen.container.querySelector('math')).toBeNull();
		expect(screen.container.textContent).toContain('$20 and $30');
		expect(screen.container.textContent).toContain('$x$');
	});

	it('escapes HTML and blocks executable links and remote image requests', async () => {
		const screen = render(MessageContent, {
			content: [
				'<img src=x onerror="alert(1)"><script>alert(1)</script>',
				'[bad](javascript:alert%281%29)',
				'[encoded](jav&#x61;script:alert%281%29)',
				'![remote plot](https://example.test/private-tracker.png)',
				'[paper](https://example.test/paper)',
				String.raw`$$\href{javascript:alert(1)}{unsafe} + \includegraphics{https://example.test/a.png}$$`
			].join('\n\n')
		});
		await expect
			.element(screen.getByRole('link', { name: 'paper' }))
			.toHaveAttribute('rel', 'noopener noreferrer');
		expect(screen.container.querySelector('script, img, iframe, [onerror], [onclick]')).toBeNull();
		expect(
			[...screen.container.querySelectorAll('a')].map((link) => link.getAttribute('href'))
		).toEqual(['https://example.test/paper']);
		expect(screen.container.textContent).toContain('<script>alert(1)</script>');
	});

	it('preserves invalid math as text and confines macro definitions to one render', async () => {
		const screen = render(MessageContent, { content: String.raw`$\gdef\lensmacro{42}\lensmacro$` });
		await expect.element(screen.getByTestId('message-content')).toBeVisible();
		expect(screen.container.querySelector('.katex-error')).toBeNull();
		await screen.rerender({ content: String.raw`$\lensmacro$` });
		expect(screen.container.textContent).toContain('\\lensmacro');
		expect(screen.container.textContent).not.toContain('42');
		await screen.rerender({ content: String.raw`Before $\frac{1}{$ after.` });
		expect(screen.container.querySelector('.katex-error')?.textContent).toBe('\\frac{1}{');
		expect(screen.container.textContent).toContain('after.');
	});
});
