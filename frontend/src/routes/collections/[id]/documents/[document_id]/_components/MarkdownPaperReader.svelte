<script lang="ts">
	import { browser } from '$app/environment';
	import { tick } from 'svelte';
	import { t } from '../../../../../_shared/i18n';
	import type {
		DocumentMarkdownResponse,
		DocumentMarkdownSourceMapItem,
		WorkbenchSourceSpan
	} from '../../../../../_shared/documents';

	type MarkdownNodeBase = {
		sourceMap: DocumentMarkdownSourceMapItem | null;
	};
	type MarkdownHeading = MarkdownNodeBase & {
		type: 'heading';
		level: number;
		text: string;
	};
	type MarkdownParagraph = MarkdownNodeBase & {
		type: 'paragraph';
		text: string;
	};
	type MarkdownList = MarkdownNodeBase & {
		type: 'list';
		items: string[];
	};
	type MarkdownTable = MarkdownNodeBase & {
		type: 'table';
		headers: string[];
		rows: string[][];
	};
	type MarkdownImage = MarkdownNodeBase & {
		type: 'image';
		alt: string;
		src: string;
	};
	type MarkdownNode = MarkdownHeading | MarkdownParagraph | MarkdownList | MarkdownTable | MarkdownImage;

	export let markdown: DocumentMarkdownResponse | null = null;
	export let sourceFileUrl = '';
	export let activeSourceRef = '';
	export let activeSourceSpan: WorkbenchSourceSpan | null = null;
	export let onShowPdf: () => void = () => {};

	$: nodes = parseMarkdown(markdown?.markdown ?? '');
	$: title = markdown?.title || markdown?.source_filename || markdown?.document_id || '';
	$: metadata = [
		markdown?.source_filename ? `${$t('workbench.sourceFileLabel')}: ${markdown.source_filename}` : '',
		markdown?.parser ? `${$t('workbench.parserLabel')}: ${markdown.parser}` : '',
		markdown?.source_map.length ? `${$t('workbench.sourceMapLabel')}: ${markdown.source_map.length}` : ''
	].filter(Boolean);
	$: activeNodeKey = activeMarkdownNodeKey(nodes, activeSourceRef, activeSourceSpan);
	$: if (activeNodeKey) {
		void scrollActiveNodeIntoView(activeNodeKey);
	}

	function parseMarkdown(value: string): MarkdownNode[] {
		const lines = value.replace(/\r\n/g, '\n').split('\n');
		const parsed: MarkdownNode[] = [];
		const usedSourceMapIndexes = new Set<number>();
		let paragraph: string[] = [];
		let listItems: string[] = [];

		function flushParagraph() {
			const text = paragraph.join(' ').trim();
			if (text) parsed.push({ type: 'paragraph', text, sourceMap: null });
			paragraph = [];
		}

		function flushList() {
			if (listItems.length) parsed.push({ type: 'list', items: listItems, sourceMap: null });
			listItems = [];
		}

		for (let index = 0; index < lines.length; index += 1) {
			const rawLine = lines[index] ?? '';
			const line = rawLine.trim();
			if (!line) {
				flushParagraph();
				flushList();
				continue;
			}

			const table = tryReadTable(lines, index, usedSourceMapIndexes);
			if (table) {
				flushParagraph();
				flushList();
				parsed.push(table.node);
				index = table.nextIndex;
				continue;
			}

			const image = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(line);
			if (image) {
				flushParagraph();
				flushList();
				parsed.push({
					type: 'image',
					alt: stripInlineMarkdown(image[1]),
					src: image[2].trim(),
					sourceMap: nextSourceMapForArtifacts(['figure'], usedSourceMapIndexes)
				});
				continue;
			}

			const heading = /^(#{1,6})\s+(.+)$/.exec(line);
			if (heading) {
				flushParagraph();
				flushList();
				parsed.push({
					type: 'heading',
					level: heading[1].length,
					text: stripInlineMarkdown(heading[2]),
					sourceMap: null
				});
				continue;
			}

			const listItem = /^[-*]\s+(.+)$/.exec(line);
			if (listItem) {
				flushParagraph();
				listItems.push(stripInlineMarkdown(listItem[1]));
				continue;
			}

			flushList();
			paragraph.push(stripInlineMarkdown(line));
		}

		flushParagraph();
		flushList();
		return parsed;
	}

	function tryReadTable(lines: string[], startIndex: number, usedSourceMapIndexes: Set<number>) {
		const headerLine = lines[startIndex]?.trim() ?? '';
		const separatorLine = lines[startIndex + 1]?.trim() ?? '';
		if (!isTableLine(headerLine) || !/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(separatorLine)) {
			return null;
		}

		const headers = parseTableCells(headerLine);
		const rows: string[][] = [];
		let cursor = startIndex + 2;
		while (cursor < lines.length && isTableLine(lines[cursor] ?? '')) {
			rows.push(parseTableCells(lines[cursor] ?? ''));
			cursor += 1;
		}
		return {
			node: {
				type: 'table' as const,
				headers,
				rows,
				sourceMap: nextSourceMapForArtifacts(['table'], usedSourceMapIndexes)
			},
			nextIndex: cursor - 1
		};
	}

	function isTableLine(value: string) {
		const line = value.trim();
		return line.startsWith('|') && line.endsWith('|') && line.includes('|');
	}

	function parseTableCells(line: string) {
		return line
			.trim()
			.replace(/^\|/, '')
			.replace(/\|$/, '')
			.split('|')
			.map((cell) => stripInlineMarkdown(cell.replace(/\\\|/g, '|').trim()));
	}

	function stripInlineMarkdown(value: string) {
		return value
			.replace(/\*\*([^*]+)\*\*/g, '$1')
			.replace(/__([^_]+)__/g, '$1')
			.replace(/\*([^*]+)\*/g, '$1')
			.replace(/_([^_]+)_/g, '$1')
			.trim();
	}

	function nextSourceMapForArtifacts(
		artifactTypes: string[],
		usedIndexes: Set<number>
	): DocumentMarkdownSourceMapItem | null {
		const sourceMap = markdown?.source_map ?? [];
		for (const [index, item] of sourceMap.entries()) {
			if (usedIndexes.has(index)) continue;
			if (!artifactTypes.includes(item.artifact_type)) continue;
			usedIndexes.add(index);
			return item;
		}
		return null;
	}

	function activeMarkdownNodeKey(
		currentNodes: MarkdownNode[],
		sourceRef: string,
		sourceSpan: WorkbenchSourceSpan | null
	) {
		const targetKeys = [
			sourceRef,
			sourceSpan?.block_id,
			sourceSpan?.anchor_id,
			sourceSpan?.target.sectionId,
			sourceSpan?.target.headingPath,
			sourceSpan?.target.label
		]
			.map(normalizeMatchKey)
			.filter(Boolean);
		const sourceQuote = normalizeMatchKey(sourceSpan?.quote || sourceSpan?.target.quote || '');
		for (const [index, node] of currentNodes.entries()) {
			const nodeMapValues = [
				node.sourceMap?.markdown_anchor,
				node.sourceMap?.artifact_id,
				node.sourceMap?.block_id,
				node.sourceMap?.table_id,
				node.sourceMap?.figure_id,
				node.sourceMap?.heading_path
			].map(normalizeMatchKey);
			if (targetKeys.some((target) => nodeMapValues.includes(target))) {
				return markdownNodeKey(node, index);
			}
			const text = normalizeMatchKey(nodeText(node));
			if (sourceQuote && text.includes(sourceQuote.slice(0, 80))) {
				return markdownNodeKey(node, index);
			}
		}
		return '';
	}

	function markdownNodeKey(node: MarkdownNode, index: number) {
		return [
			node.type,
			node.sourceMap?.markdown_anchor,
			node.sourceMap?.artifact_id,
			nodeText(node).slice(0, 64),
			index
		]
			.filter(Boolean)
			.join(':');
	}

	function nodeText(node: MarkdownNode) {
		if (node.type === 'heading' || node.type === 'paragraph') return node.text;
		if (node.type === 'image') return node.alt;
		if (node.type === 'list') return node.items.join(' ');
		return [...node.headers, ...node.rows.flat()].join(' ');
	}

	function normalizeMatchKey(value: string | null | undefined) {
		return (value ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
	}

	async function scrollActiveNodeIntoView(nodeKey: string) {
		if (!browser) return;
		await tick();
		document
			.querySelector<HTMLElement>(`[data-markdown-node-key="${CSS.escape(nodeKey)}"]`)
			?.scrollIntoView({ block: 'center' });
	}
</script>

<section class="markdown-reader" aria-label={$t('workbench.markdownReaderLabel')}>
	<header class="markdown-reader__header">
		<div>
			<h1>{title}</h1>
			{#if metadata.length}
				<div class="markdown-reader__meta">
					{#each metadata as item, index}
						<span>{item}</span>
						{#if index < metadata.length - 1}
							<span aria-hidden="true">|</span>
						{/if}
					{/each}
				</div>
			{/if}
		</div>
		<div class="markdown-reader__actions">
			<button type="button" on:click={onShowPdf}>{$t('workbench.pdfPreview')}</button>
			{#if sourceFileUrl}
				<a href={sourceFileUrl}>{$t('workbench.downloadSource')}</a>
			{/if}
		</div>
	</header>

	<div class="markdown-reader__body" data-testid="markdown-paper-reader">
		{#if nodes.length}
			{#each nodes as node, index (markdownNodeKey(node, index))}
				{@const nodeKey = markdownNodeKey(node, index)}
				{#if node.type === 'heading'}
					{#if node.level <= 1}
						<h1
							class:markdown-node--active={activeNodeKey === nodeKey}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h1>
					{:else if node.level === 2}
						<h2
							class:markdown-node--active={activeNodeKey === nodeKey}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h2>
					{:else if node.level === 3}
						<h3
							class:markdown-node--active={activeNodeKey === nodeKey}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h3>
					{:else}
						<h4
							class:markdown-node--active={activeNodeKey === nodeKey}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h4>
					{/if}
				{:else if node.type === 'paragraph'}
					<p
						class:markdown-node--active={activeNodeKey === nodeKey}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						{node.text}
					</p>
				{:else if node.type === 'image'}
					<figure
						class="markdown-figure"
						class:markdown-node--active={activeNodeKey === nodeKey}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						<img src={node.src} alt={node.alt} loading="lazy" />
					</figure>
				{:else if node.type === 'list'}
					<ul
						class:markdown-node--active={activeNodeKey === nodeKey}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						{#each node.items as item}
							<li>{item}</li>
						{/each}
					</ul>
				{:else if node.type === 'table'}
					<div
						class="markdown-table-wrapper"
						class:markdown-node--active={activeNodeKey === nodeKey}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						<table>
							<thead>
								<tr>
									{#each node.headers as header}
										<th>{header}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each node.rows as row}
									<tr>
										{#each node.headers as _header, index}
											<td>{row[index] ?? ''}</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			{/each}
		{:else}
			<div class="markdown-reader__empty" role="status">
				<h2>{$t('workbench.markdownUnavailableTitle')}</h2>
				<p>{$t('workbench.markdownUnavailableBody')}</p>
			</div>
		{/if}
	</div>
</section>

<style>
	.markdown-reader {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		height: 100%;
		min-width: 0;
		overflow: hidden;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
	}

	.markdown-reader__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		padding: 18px 22px;
		border-bottom: 1px solid #e2e8f0;
		background: #ffffff;
	}

	.markdown-reader__header h1 {
		margin: 0;
		color: #0f172a;
		font-size: 20px;
		line-height: 28px;
	}

	.markdown-reader__meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 6px;
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.markdown-reader__actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
	}

	.markdown-reader__actions button,
	.markdown-reader__actions a {
		display: inline-flex;
		min-height: 34px;
		align-items: center;
		padding: 0 12px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #eff6ff;
		color: #1d4ed8;
		font-size: 13px;
		font-weight: 700;
		text-decoration: none;
		cursor: pointer;
	}

	.markdown-reader__body {
		min-width: 0;
		overflow: auto;
		padding: 28px clamp(22px, 5vw, 72px) 56px;
		color: #1e293b;
	}

	.markdown-reader__body :global(h1),
	.markdown-reader__body h1,
	.markdown-reader__body h2,
	.markdown-reader__body h3,
	.markdown-reader__body h4 {
		max-width: 820px;
		margin: 26px auto 12px;
		color: #0f172a;
		letter-spacing: 0;
	}

	.markdown-reader__body h1:first-child {
		margin-top: 0;
	}

	.markdown-reader__body h1 {
		font-size: 28px;
		line-height: 36px;
	}

	.markdown-reader__body h2 {
		font-size: 22px;
		line-height: 30px;
	}

	.markdown-reader__body h3 {
		font-size: 18px;
		line-height: 26px;
	}

	.markdown-reader__body h4 {
		font-size: 16px;
		line-height: 24px;
	}

	.markdown-reader__body p,
	.markdown-reader__body ul {
		max-width: 820px;
		margin: 0 auto 14px;
		font-size: 15px;
		line-height: 1.72;
	}

	.markdown-reader__body ul {
		padding-left: 24px;
	}

	.markdown-reader__body li + li {
		margin-top: 6px;
	}

	.markdown-reader__body .markdown-node--active {
		border-radius: 8px;
		outline: 2px solid #2563eb;
		outline-offset: 4px;
		background: #eff6ff;
	}

	.markdown-figure {
		max-width: 920px;
		margin: 20px auto;
	}

	.markdown-figure img {
		display: block;
		width: auto;
		max-width: 100%;
		max-height: 720px;
		margin: 0 auto;
		border: 1px solid #e2e8f0;
		background: #ffffff;
		object-fit: contain;
	}

	.markdown-table-wrapper {
		max-width: 920px;
		margin: 18px auto;
		overflow-x: auto;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
	}

	.markdown-table-wrapper table {
		width: 100%;
		min-width: 520px;
		border-collapse: collapse;
		font-size: 13px;
	}

	.markdown-table-wrapper th,
	.markdown-table-wrapper td {
		padding: 10px 12px;
		border-bottom: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: top;
	}

	.markdown-table-wrapper th {
		background: #f8fafc;
		color: #475569;
		font-weight: 700;
	}

	.markdown-table-wrapper tr:last-child td {
		border-bottom: 0;
	}

	.markdown-reader__empty {
		display: grid;
		max-width: 620px;
		margin: 0 auto;
		gap: 8px;
		padding: 32px;
		border: 1px dashed #cbd5e1;
		border-radius: 12px;
		background: #f8fafc;
		text-align: center;
	}

	.markdown-reader__empty h2,
	.markdown-reader__empty p {
		margin: 0;
	}

	@media (max-width: 720px) {
		.markdown-reader__header {
			display: grid;
		}

		.markdown-reader__actions {
			justify-content: flex-start;
		}
	}
</style>
