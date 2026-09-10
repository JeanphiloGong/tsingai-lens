<script context="module" lang="ts">
	import MarkdownIt from 'markdown-it';
	import { katex } from '@mdit/plugin-katex';
	import 'katex/dist/katex.min.css';

	const macros: Record<string, string> = {};
	const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true }).use(katex, {
		delimiters: 'all',
		throwOnError: false,
		trust: false,
		maxExpand: 1000,
		maxSize: 20,
		macros,
		logger: () => 'ignore',
		transformer: (html: string, display: boolean) =>
			display ? `<div class="math-scroll" tabindex="0">${html}</div>` : html
	});
	const escape = markdown.utils.escapeHtml;
	markdown.renderer.rules.table_open = (tokens, index, options, env, self) =>
		`<div class="table-scroll" role="region" aria-label="${escape(env.tableLabel)}" tabindex="0">${self.renderToken(tokens, index, options)}`;
	markdown.renderer.rules.table_close = () => '</table></div>\n';
	markdown.renderer.rules.link_open = (tokens, index, options, _env, self) => {
		const token = tokens[index];
		token.attrSet('rel', 'noopener noreferrer');
		if (/^(https?:)?\/\//i.test(token.attrGet('href') ?? '')) token.attrSet('target', '_blank');
		return self.renderToken(tokens, index, options);
	};
	// Inspectable images belong to Source artifacts, not automatic requests from model text.
	markdown.renderer.rules.image = (tokens, index) => escape(tokens[index].content);
	markdown.renderer.rules.fence = (tokens, index) => {
		const token = tokens[index];
		const language = token.info.trim().split(/\s+/)[0];
		const attribute = language ? ` class="language-${escape(language)}"` : '';
		return `<pre tabindex="0"><code${attribute}>${escape(token.content)}</code></pre>\n`;
	};
	const renderMathBlock = markdown.renderer.rules.math_block!;
	markdown.renderer.rules.math_block = (tokens, index, options, env, self) => {
		const token = tokens[index];
		const source = env.lines.slice(token.map?.[0], token.map?.[1]).join('\n').trim();
		const delimiter = token.markup === '\\[' ? '\\]' : '$$';
		if (env.streaming && (source.length <= delimiter.length || !source.endsWith(delimiter))) {
			return `<pre class="math-pending">${escape(token.content)}</pre>\n`;
		}
		return renderMathBlock(tokens, index, options, env, self);
	};

	function renderMessage(text: string, streaming: boolean, tableLabel: string) {
		// KaTeX permits local macro definitions; reset them for every complete render.
		for (const name of Object.keys(macros)) delete macros[name];
		return markdown.render(text, { streaming, tableLabel, lines: text.split(/\r\n?|\n/) });
	}
</script>

<script lang="ts">
	import { t } from '../../../_shared/i18n';
	export let content = '';
	export let streaming = false;
	$: html = renderMessage(content, streaming, $t('researchAgent.responseTable'));
</script>

{#if content}
	<div class="assistant-copy" class:streaming data-testid="message-content">
		<!-- HTML input is disabled; only Markdown and untrusted-mode KaTeX emit markup. -->
		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		{@html html}
		{#if streaming}
			<span class="stream-cursor" aria-hidden="true"></span>
		{/if}
	</div>
{:else if streaming}
	<div class="assistant-copy streaming-copy" role="status" aria-label={$t('researchAgent.sending')}>
		<span class="stream-cursor" aria-hidden="true"></span>
	</div>
{/if}

<style>
	.assistant-copy {
		min-width: 0;
		max-width: 100%;
		padding: 2px 0 0;
		font-size: 14px;
		line-height: 1.65;
		overflow-wrap: anywhere;
	}

	.assistant-copy :global(p),
	.assistant-copy :global(ul),
	.assistant-copy :global(ol),
	.assistant-copy :global(blockquote),
	.assistant-copy :global(pre),
	.assistant-copy :global(.table-scroll),
	.assistant-copy :global(.math-scroll) {
		margin: 0 0 14px;
	}
	.assistant-copy :global(> :last-child) {
		margin-bottom: 0;
	}
	.assistant-copy :global(h1),
	.assistant-copy :global(h2),
	.assistant-copy :global(h3),
	.assistant-copy :global(h4),
	.assistant-copy :global(h5),
	.assistant-copy :global(h6) {
		margin: 22px 0 10px;
		font-size: 16px;
		font-weight: 650;
		line-height: 1.4;
	}
	.assistant-copy :global(h1),
	.assistant-copy :global(h2) {
		font-size: 18px;
	}
	.assistant-copy :global(> :first-child) {
		margin-top: 0;
	}
	.assistant-copy :global(ul),
	.assistant-copy :global(ol) {
		padding-left: 24px;
	}
	.assistant-copy :global(ul) {
		list-style: disc;
	}
	.assistant-copy :global(ol) {
		list-style: decimal;
	}
	.assistant-copy :global(li + li) {
		margin-top: 4px;
	}
	.assistant-copy :global(li > ul),
	.assistant-copy :global(li > ol),
	.assistant-copy :global(li > p) {
		margin-bottom: 4px;
	}
	.assistant-copy :global(a) {
		color: var(--brand-primary);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.assistant-copy :global(blockquote) {
		padding: 4px 0 4px 14px;
		border-left: 3px solid var(--border-default);
		color: var(--text-secondary);
	}
	.assistant-copy :global(blockquote > :last-child) {
		margin-bottom: 0;
	}
	.assistant-copy :global(hr) {
		margin: 20px 0;
		border: 0;
		border-top: 1px solid var(--border-default);
	}
	.assistant-copy :global(code) {
		padding: 2px 5px;
		border-radius: 4px;
		background: var(--bg-subtle);
		font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
		font-size: 0.9em;
	}
	.assistant-copy :global(pre) {
		max-width: 100%;
		overflow-x: auto;
		padding: 14px 16px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--bg-subtle);
		white-space: pre;
		overflow-wrap: normal;
	}
	.assistant-copy :global(pre code) {
		padding: 0;
		background: transparent;
	}
	.assistant-copy :global(.table-scroll),
	.assistant-copy :global(.math-scroll) {
		max-width: 100%;
		overflow-x: auto;
		overscroll-behavior-x: contain;
	}
	.assistant-copy :global(table) {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
		line-height: 1.5;
	}
	.assistant-copy :global(th),
	.assistant-copy :global(td) {
		min-width: 104px;
		padding: 10px 12px;
		border: 1px solid var(--border-default);
		text-align: left;
		vertical-align: top;
	}
	.assistant-copy :global(th) {
		background: var(--bg-subtle);
		font-weight: 650;
	}
	.assistant-copy :global(tbody tr:nth-child(even)) {
		background: color-mix(in srgb, var(--bg-subtle) 50%, transparent);
	}
	.assistant-copy :global(.katex) {
		font-size: 1.08em;
		overflow-wrap: normal;
	}
	.assistant-copy :global(p > .katex),
	.assistant-copy :global(li > .katex),
	.assistant-copy :global(td > .katex) {
		display: inline-block;
		max-width: 100%;
		overflow-x: auto;
		overflow-y: hidden;
		vertical-align: middle;
		padding: 2px 0;
	}
	.assistant-copy :global(.katex-block) {
		margin: 0;
	}
	.assistant-copy :global(.katex-display) {
		margin: 12px 0;
	}
	.assistant-copy :global(.katex-display > .katex) {
		width: max-content;
		min-width: 100%;
	}
	.assistant-copy :global(.katex-error) {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.assistant-copy :global(.math-pending),
	.assistant-copy.streaming :global(.katex-error) {
		color: var(--text-secondary) !important;
	}
	.assistant-copy :global(:focus-visible) {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}

	.streaming-copy {
		min-width: 48px;
		min-height: 51px;
	}

	.stream-cursor {
		display: inline-block;
		width: 2px;
		height: 1em;
		margin-left: 2px;
		background: currentColor;
		vertical-align: text-bottom;
		animation: stream-cursor 0.9s steps(1) infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.stream-cursor {
			animation: none;
		}
	}

	@keyframes stream-cursor {
		50% {
			opacity: 0;
		}
	}
</style>
