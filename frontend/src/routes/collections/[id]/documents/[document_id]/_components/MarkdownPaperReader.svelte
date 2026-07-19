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
		items: { text: string; sourceMap: DocumentMarkdownSourceMapItem | null }[];
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
	export let activeSourceQuote = '';
	export let activeSourceSpan: WorkbenchSourceSpan | null = null;
	export let onShowPdf: () => void = () => {};

	$: nodes = parseMarkdown(markdown?.markdown ?? '');
	$: title = markdown?.title || markdown?.source_filename || markdown?.document_id || '';
	$: metadata = [
		markdown?.source_filename ? `${$t('traceback.sourceFileLabel')}: ${markdown.source_filename}` : '',
		markdown?.parser ? `${$t('workbench.parserLabel')}: ${markdown.parser}` : '',
		markdown?.source_map.length ? `${$t('workbench.sourceMapLabel')}: ${markdown.source_map.length}` : ''
	].filter(Boolean);
	$: selectedEvidenceQuote = cleanSourceText(
		activeSourceQuote || activeSourceSpan?.quote || activeSourceSpan?.target.quote || ''
	);
	$: activeNodeKey = activeMarkdownNodeKey(
		nodes,
		activeSourceRef,
		activeSourceSpan,
		selectedEvidenceQuote
	);
	$: activeFallback = activeSourceFallback(
		activeNodeKey,
		activeSourceRef,
		activeSourceSpan,
		selectedEvidenceQuote
	);
	$: if (activeNodeKey) {
		void scrollActiveNodeIntoView(activeNodeKey);
	}
	$: if (activeFallback) {
		void scrollActiveElementIntoView('[data-testid="markdown-active-source-fallback"]');
	}

	function parseMarkdown(value: string): MarkdownNode[] {
		const lines = value.replace(/\r\n/g, '\n').split('\n');
		const parsed: MarkdownNode[] = [];
		const usedSourceMapIndexes = new Set<number>();
		let paragraph: string[] = [];
		let listItems: string[] = [];
		let currentHeading = '';

		function flushParagraph() {
			const text = paragraph.join(' ').trim();
			if (text) {
				parsed.push({
					type: 'paragraph',
					text,
					sourceMap: nextSourceMapForTextNode(
						['block', 'paragraph', 'text'],
						usedSourceMapIndexes,
						currentHeading
					)
				});
			}
			paragraph = [];
		}

		function flushList() {
			if (listItems.length) {
				parsed.push({
					type: 'list',
					items: listItems.map((item) => ({
						text: item,
						sourceMap: nextSourceMapForTextNode(
							['block', 'list_item', 'list'],
							usedSourceMapIndexes,
							currentHeading
						)
					})),
					sourceMap: null
				});
			}
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
				currentHeading = stripInlineMarkdown(heading[2]);
				parsed.push({
					type: 'heading',
					level: heading[1].length,
					text: currentHeading,
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

	function nextSourceMapForTextNode(
		artifactTypes: string[],
		usedIndexes: Set<number>,
		currentHeading: string
	): DocumentMarkdownSourceMapItem | null {
		const sourceMap = markdown?.source_map ?? [];
		const headingKey = normalizeMatchKey(currentHeading);
		for (const [index, item] of sourceMap.entries()) {
			if (usedIndexes.has(index)) continue;
			if (!sourceMapTypeMatches(item, artifactTypes)) continue;
			if (!headingKey || !sourceMapHeadingMatches(item, headingKey)) continue;
			usedIndexes.add(index);
			return item;
		}
		return null;
	}

	function sourceMapTypeMatches(item: DocumentMarkdownSourceMapItem, artifactTypes: string[]) {
		const artifactType = normalizeMatchKey(item.artifact_type);
		const blockType = normalizeMatchKey(item.block_type);
		if (artifactType === 'block' && blockType) return artifactTypes.includes(blockType);
		return artifactTypes.includes(artifactType) || artifactTypes.includes(blockType);
	}

	function sourceMapHeadingMatches(item: DocumentMarkdownSourceMapItem, headingKey: string) {
		const itemHeading = normalizeMatchKey(item.heading_path);
		if (!itemHeading) return false;
		if (itemHeading === headingKey) return true;
		const segments = itemHeading
			.split('/')
			.map((segment) => normalizeMatchKey(segment))
			.filter(Boolean);
		return segments.includes(headingKey);
	}

	function activeMarkdownNodeKey(
		currentNodes: MarkdownNode[],
		sourceRef: string,
		sourceSpan: WorkbenchSourceSpan | null,
		selectedQuote: string
	) {
		const directTargetKeys = [sourceRef, sourceSpan?.block_id, sourceSpan?.anchor_id]
			.map(normalizeMatchKey)
			.filter(Boolean);
		const sectionTargetKeys = [
			sourceSpan?.target.sectionId,
			sourceSpan?.target.headingPath,
			sourceSpan?.target.label
		]
			.map(normalizeMatchKey)
			.filter(Boolean);
		const sourceQuote = normalizeMatchKey(
			cleanSourceText(selectedQuote || sourceSpan?.quote || sourceSpan?.target.quote || '')
		);
		const directKey = activeMarkdownNodeKeyByDirectTarget(currentNodes, directTargetKeys);
		if (directKey) return directKey;
		if (!directTargetKeys.length) {
			const sectionKey = activeMarkdownNodeKeyBySection(currentNodes, sectionTargetKeys);
			if (sectionKey) return sectionKey;
		}
		return activeMarkdownNodeKeyByQuote(currentNodes, sourceQuote);
	}

	function activeMarkdownNodeKeyByDirectTarget(
		currentNodes: MarkdownNode[],
		directTargetKeys: string[]
	) {
		for (const [index, node] of currentNodes.entries()) {
			const childKey = activeChildNodeKeyByDirectTarget(node, index, directTargetKeys);
			if (childKey) return childKey;
			if (node.type === 'list') continue;
			if (sourceMapMatchesDirectTargets(node.sourceMap, directTargetKeys)) {
				return markdownNodeKey(node, index);
			}
		}
		return '';
	}

	function activeMarkdownNodeKeyBySection(
		currentNodes: MarkdownNode[],
		sectionTargetKeys: string[]
	) {
		for (const [index, node] of currentNodes.entries()) {
			const childKey = activeChildNodeKeyBySection(node, index, sectionTargetKeys);
			if (childKey) return childKey;
			if (node.type === 'list') continue;
			if (sourceMapMatchesSectionTargets(node.sourceMap, sectionTargetKeys)) {
				return markdownNodeKey(node, index);
			}
		}
		return '';
	}

	function activeMarkdownNodeKeyByQuote(currentNodes: MarkdownNode[], sourceQuote: string) {
		for (const [index, node] of currentNodes.entries()) {
			const childKey = activeChildNodeKeyByQuote(node, index, sourceQuote);
			if (childKey) return childKey;
			if (node.type === 'list') continue;
			const text = normalizeMatchKey(cleanSourceText(nodeText(node)));
			if (sourceQuote && text.includes(sourceQuote.slice(0, 80))) {
				return markdownNodeKey(node, index);
			}
		}
		return '';
	}

	function activeChildNodeKeyByDirectTarget(
		node: MarkdownNode,
		index: number,
		directTargetKeys: string[]
	) {
		if (node.type !== 'list') return '';
		for (const [itemIndex, item] of node.items.entries()) {
			if (sourceMapMatchesDirectTargets(item.sourceMap, directTargetKeys)) {
				return markdownListItemKey(node, index, item, itemIndex);
			}
		}
		return '';
	}

	function activeChildNodeKeyBySection(
		node: MarkdownNode,
		index: number,
		sectionTargetKeys: string[]
	) {
		if (node.type !== 'list') return '';
		for (const [itemIndex, item] of node.items.entries()) {
			if (sourceMapMatchesSectionTargets(item.sourceMap, sectionTargetKeys)) {
				return markdownListItemKey(node, index, item, itemIndex);
			}
		}
		return '';
	}

	function activeChildNodeKeyByQuote(
		node: MarkdownNode,
		index: number,
		sourceQuote: string
	) {
		if (node.type !== 'list') return '';
		for (const [itemIndex, item] of node.items.entries()) {
			const text = normalizeMatchKey(cleanSourceText(item.text));
			if (sourceQuote && text.includes(sourceQuote.slice(0, 80))) {
				return markdownListItemKey(node, index, item, itemIndex);
			}
		}
		return '';
	}

	function sourceMapMatchesDirectTargets(
		sourceMap: DocumentMarkdownSourceMapItem | null,
		directTargetKeys: string[]
	) {
		const values = [
			sourceMap?.markdown_anchor,
			sourceMap?.artifact_id,
			sourceMap?.block_id,
			sourceMap?.table_id,
			sourceMap?.figure_id
		].map(normalizeMatchKey);
		return directTargetKeys.some((target) => values.includes(target));
	}

	function sourceMapMatchesSectionTargets(
		sourceMap: DocumentMarkdownSourceMapItem | null,
		sectionTargetKeys: string[]
	) {
		const values = [sourceMap?.heading_path].map(normalizeMatchKey);
		return sectionTargetKeys.some((target) => values.includes(target));
	}

	function activeSourceFallback(
		nodeKey: string,
		sourceRef: string,
		sourceSpan: WorkbenchSourceSpan | null,
		selectedQuote: string
	) {
		if (nodeKey || !sourceRef || !sourceSpan) return null;
		const quote = cleanSourceText(selectedQuote || sourceSpan.quote || sourceSpan.target.quote || '');
		if (!quote) return null;
		return {
			label: sourceSpan.target.label || sourceSpan.section || sourceSpan.target.headingPath || sourceRef,
			page: sourceSpan.page || sourceSpan.target.page,
			section: sourceSpan.section || sourceSpan.target.headingPath || '',
			quote
		};
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

	function markdownListItemKey(
		node: MarkdownList,
		nodeIndex: number,
		item: MarkdownList['items'][number],
		itemIndex: number
	) {
		return [
			node.type,
			item.sourceMap?.markdown_anchor,
			item.sourceMap?.artifact_id,
			item.text.slice(0, 64),
			nodeIndex,
			itemIndex
		]
			.filter(Boolean)
			.join(':');
	}

	function nodeText(node: MarkdownNode) {
		if (node.type === 'heading' || node.type === 'paragraph') return node.text;
		if (node.type === 'image') return node.alt;
		if (node.type === 'list') return node.items.map((item) => item.text).join(' ');
		return [...node.headers, ...node.rows.flat()].join(' ');
	}

	function normalizeMatchKey(value: string | null | undefined) {
		return cleanSourceText(value ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
	}

	function cleanSourceText(value: string) {
		return value.replace(/\ufffd/g, ' ').replace(/\s+/g, ' ').trim();
	}

	async function scrollActiveNodeIntoView(nodeKey: string) {
		if (!browser) return;
		await scrollActiveElementIntoView(`[data-markdown-node-key="${CSS.escape(nodeKey)}"]`);
	}

	async function scrollActiveElementIntoView(selector: string) {
		if (!browser) return;
		await tick();
		for (let attempt = 0; attempt < 3; attempt += 1) {
			await nextAnimationFrame();
			const target = document.querySelector<HTMLElement>(selector);
			if (!target) continue;
			target.scrollIntoView({ block: 'center', behavior: 'auto' });
		}
	}

	function nextAnimationFrame() {
		return new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
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
		{#if activeFallback}
			<aside
				class="markdown-source-fallback"
				data-testid="markdown-active-source-fallback"
				aria-label={$t('workbench.selectedSourceBlockLabel')}
				aria-current="location"
			>
				<div class="markdown-source-fallback__header">
					<div>
						<h2>{$t('workbench.selectedSourceBlockLabel')}</h2>
						<div class="markdown-source-fallback__meta">
							<span>{activeFallback.label}</span>
							{#if activeFallback.page}
								<span>{$t('workbench.pageLabel', { page: activeFallback.page })}</span>
							{/if}
							{#if activeFallback.section && normalizeMatchKey(activeFallback.section) !== normalizeMatchKey(activeFallback.label)}
								<span>{activeFallback.section}</span>
							{/if}
						</div>
					</div>
					<button type="button" on:click={onShowPdf}>{$t('workbench.viewPdf')}</button>
				</div>
				<div class="markdown-source-fallback__body">
					<strong>{$t('workbench.parsedSourceView')}</strong>
					<p>{activeFallback.quote}</p>
				</div>
			</aside>
		{/if}
		{#if nodes.length}
			{#each nodes as node, index (markdownNodeKey(node, index))}
				{@const nodeKey = markdownNodeKey(node, index)}
				{#if node.type === 'heading'}
					{#if node.level <= 1}
						<h1
							class:markdown-node--active={activeNodeKey === nodeKey}
							aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h1>
					{:else if node.level === 2}
						<h2
							class:markdown-node--active={activeNodeKey === nodeKey}
							aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h2>
					{:else if node.level === 3}
						<h3
							class:markdown-node--active={activeNodeKey === nodeKey}
							aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h3>
					{:else}
						<h4
							class:markdown-node--active={activeNodeKey === nodeKey}
							aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
							data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
							data-markdown-node-key={nodeKey}
						>
							{node.text}
						</h4>
					{/if}
				{:else if node.type === 'paragraph'}
					<p
						class:markdown-node--active={activeNodeKey === nodeKey}
						aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						{#if activeNodeKey === nodeKey && selectedEvidenceQuote}
							<span
								class="markdown-selected-quote"
								data-testid="markdown-selected-evidence-quote"
							>
								<strong>{$t('workbench.selectedEvidenceQuoteLabel')}</strong>
								<span>{selectedEvidenceQuote}</span>
							</span>
						{/if}
						{node.text}
					</p>
				{:else if node.type === 'image'}
					<figure
						class="markdown-figure"
						class:markdown-node--active={activeNodeKey === nodeKey}
						aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						<img src={node.src} alt={node.alt} loading="lazy" />
					</figure>
				{:else if node.type === 'list'}
					<ul
						data-markdown-node-key={nodeKey}
					>
						{#each node.items as item, itemIndex (markdownListItemKey(node, index, item, itemIndex))}
							{@const itemKey = markdownListItemKey(node, index, item, itemIndex)}
							<li
								class:markdown-node--active={activeNodeKey === itemKey}
								aria-current={activeNodeKey === itemKey ? 'location' : undefined}
								data-testid={activeNodeKey === itemKey ? 'markdown-active-source' : undefined}
								data-markdown-node-key={itemKey}
							>
								{#if activeNodeKey === itemKey && selectedEvidenceQuote}
									<span
										class="markdown-selected-quote"
										data-testid="markdown-selected-evidence-quote"
									>
										<strong>{$t('workbench.selectedEvidenceQuoteLabel')}</strong>
										<span>{selectedEvidenceQuote}</span>
									</span>
								{/if}
								{item.text}
							</li>
						{/each}
					</ul>
				{:else if node.type === 'table'}
					<div
						class="markdown-table-wrapper"
						class:markdown-node--active={activeNodeKey === nodeKey}
						aria-current={activeNodeKey === nodeKey ? 'location' : undefined}
						data-testid={activeNodeKey === nodeKey ? 'markdown-active-source' : undefined}
						data-markdown-node-key={nodeKey}
					>
						{#if activeNodeKey === nodeKey && selectedEvidenceQuote}
							<div
								class="markdown-selected-quote"
								data-testid="markdown-selected-evidence-quote"
							>
								<strong>{$t('workbench.selectedEvidenceQuoteLabel')}</strong>
								<span>{selectedEvidenceQuote}</span>
							</div>
						{/if}
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

	.markdown-selected-quote {
		display: block;
		margin: 0 0 10px;
		padding: 10px 12px;
		border: 1px solid #bfdbfe;
		border-left: 4px solid #2563eb;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		font-size: 14px;
		line-height: 1.6;
	}

	.markdown-selected-quote strong {
		display: block;
		margin-bottom: 4px;
		color: #1d4ed8;
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.markdown-selected-quote span {
		display: block;
	}

	.markdown-source-fallback {
		max-width: 820px;
		margin: 0 auto 28px;
		padding: 16px 18px 18px;
		border: 1px solid #bfdbfe;
		border-left: 4px solid #2563eb;
		border-radius: 8px;
		background: #eff6ff;
		box-shadow: 0 10px 28px rgba(37, 99, 235, 0.12);
	}

	.markdown-source-fallback__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}

	.markdown-source-fallback__header h2 {
		margin: 0 0 8px;
		color: #0f172a;
		font-size: 15px;
		line-height: 22px;
	}

	.markdown-source-fallback__header button {
		display: inline-flex;
		min-height: 32px;
		flex: 0 0 auto;
		align-items: center;
		padding: 0 12px;
		border: 1px solid #2563eb;
		border-radius: 8px;
		background: #2563eb;
		color: #ffffff;
		font-size: 13px;
		font-weight: 700;
		cursor: pointer;
	}

	.markdown-source-fallback__meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		color: #1d4ed8;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.markdown-source-fallback__meta span {
		display: inline-flex;
		align-items: center;
		min-height: 22px;
		padding: 0 8px;
		border: 1px solid #bfdbfe;
		border-radius: 6px;
		background: #ffffff;
	}

	.markdown-source-fallback__body {
		margin-top: 14px;
		padding-top: 14px;
		border-top: 1px solid #bfdbfe;
	}

	.markdown-source-fallback__body strong {
		display: block;
		margin-bottom: 6px;
		color: #1d4ed8;
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.markdown-source-fallback p {
		margin: 0;
		color: #0f172a;
		font-size: 15px;
		line-height: 1.72;
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
