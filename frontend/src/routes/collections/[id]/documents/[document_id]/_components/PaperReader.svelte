<script lang="ts">
	import { browser } from '$app/environment';
	import { tick } from 'svelte';
	import { t } from '../../../../../_shared/i18n';
	import type {
		WorkbenchPdfPage,
		WorkbenchSourceTarget
	} from '../../../../../_shared/documents';

	export let title = '';
	export let metadata: string[] = [];
	export let pages: WorkbenchPdfPage[] = [];
	export let sourceFileUrl = '';
	export let sourceFilename: string | null = null;
	export let activeSourceSpanId = '';
	export let sourceTarget: WorkbenchSourceTarget | null = null;
	export let onSelectSourceSpan: (sourceSpanId: string) => void = () => {};

	let thumbnailTab: 'source' | 'outline' = 'source';
	let currentPage = 1;
	let zoom = '100%';
	const zoomLevels = ['Fit', '90%', '100%', '125%'];

	$: readerMode = resolveReaderMode(sourceFilename, sourceFileUrl, pages);
	$: sourceTargetMessageKey = messageKeyForTarget(sourceTarget);
	$: pdfSourceUrl = sourceFileUrl ? `${sourceFileUrl}#page=${currentPage}` : '';
	$: currentPage = pageForSourceSpan(activeSourceSpanId, sourceTarget);
	$: if (activeSourceSpanId) {
		void scrollToSourceSpan(activeSourceSpanId);
	}

	function resolveReaderMode(
		filename: string | null,
		fileUrl: string,
		sourcePages: WorkbenchPdfPage[]
	): 'pdf' | 'text' | 'unavailable' {
		if (fileUrl && filename?.toLowerCase().endsWith('.pdf')) return 'pdf';
		return sourcePages.length ? 'text' : 'unavailable';
	}

	function messageKeyForTarget(target: WorkbenchSourceTarget | null) {
		if (!target) return '';
		if (target.precision === 'pdf-region') return 'workbench.sourcePdfRegionFallback';
		if (target.precision === 'text-range') return 'workbench.sourceTextRange';
		if (target.precision === 'pdf-page') return 'workbench.sourcePdfPageFallback';
		if (target.precision === 'section') return 'workbench.sourceSectionFallback';
		if (target.precision === 'quote-search') return 'workbench.sourceQuoteFallback';
		return 'workbench.sourceUnavailable';
	}

	function pageForSourceSpan(sourceSpanId: string, target: WorkbenchSourceTarget | null) {
		if (target?.page) return target.page;
		const page = pages.find((item) => item.source_span_ids.includes(sourceSpanId));
		return page?.page_number ?? currentPage;
	}

	async function scrollToSourceSpan(sourceSpanId: string) {
		if (!browser || !sourceSpanId) return;
		await tick();
		const target = document.getElementById(`pdf-source-${sourceSpanId}`);
		if (target && typeof target.scrollIntoView === 'function') {
			target.scrollIntoView({ behavior: 'smooth', block: 'center' });
		}
	}

	async function scrollToPage(pageNumber: number) {
		currentPage = pageNumber;
		if (!browser) return;
		await tick();
		const target = document.getElementById(`pdf-page-${pageNumber}`);
		if (target && typeof target.scrollIntoView === 'function') {
			target.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}

	function selectParagraph(sourceSpanId: string | null) {
		if (sourceSpanId) onSelectSourceSpan(sourceSpanId);
	}

	function outlineSections() {
		const seen = new Set<string>();
		const sections: { label: string; sourceSpanId: string | null }[] = [];
		for (const page of pages) {
			for (const paragraph of page.paragraphs) {
				const label = paragraph.section || $t('workbench.sectionFallback');
				if (seen.has(label)) continue;
				seen.add(label);
				sections.push({ label, sourceSpanId: paragraph.source_span_id });
			}
		}
		return sections;
	}

	function shouldShowSectionHeading(
		pageIndex: number,
		paragraphIndex: number,
		section: string | null
	) {
		if (!section) return false;
		const previousParagraph =
			paragraphIndex > 0
				? pages[pageIndex]?.paragraphs[paragraphIndex - 1]
				: pages[pageIndex - 1]?.paragraphs.at(-1);
		return previousParagraph?.section !== section;
	}

	function handleParagraphKeydown(event: KeyboardEvent, sourceSpanId: string | null) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			selectParagraph(sourceSpanId);
		}
	}
</script>

<section class="paper-reader-grid" aria-label={$t('workbench.readerLabel')}>
	<aside class="thumbnail-rail" aria-label={$t('workbench.thumbnailLabel')}>
		<div class="thumbnail-tabs" role="tablist" aria-label={$t('workbench.sourceNavigationLabel')}>
			<button
				type="button"
				class:active={thumbnailTab === 'source'}
				on:click={() => (thumbnailTab = 'source')}
			>
				{$t('workbench.sourceTab')}
			</button>
			<button
				type="button"
				class:active={thumbnailTab === 'outline'}
				on:click={() => (thumbnailTab = 'outline')}
			>
				{$t('workbench.outlineTab')}
			</button>
		</div>

		{#if thumbnailTab === 'source'}
			<div class="page-thumbnails">
				{#each pages as page}
					<button
						type="button"
						class:active={currentPage === page.page_number}
						class="page-thumbnail"
						aria-label={$t('workbench.pageLabel', { page: page.page_number })}
						on:click={() => void scrollToPage(page.page_number)}
					>
						<span class="thumbnail-paper" aria-hidden="true">
							<span></span>
							<span></span>
							<span></span>
							<span></span>
						</span>
						<span class="thumbnail-page">{page.page_number}</span>
					</button>
				{/each}
			</div>
		{:else}
			<div class="outline-list">
				{#each outlineSections() as section}
					<button
						type="button"
						on:click={() => selectParagraph(section.sourceSpanId)}
						class:active={section.sourceSpanId === activeSourceSpanId}
					>
						{section.label}
					</button>
				{/each}
			</div>
		{/if}

		<button class="rail-bottom" type="button" aria-label={$t('workbench.morePages')}>v</button>
	</aside>

	<article class="pdf-shell" aria-labelledby="paper-reader-title">
		<header class="pdf-header">
			<div>
				<h1 id="paper-reader-title">{title}</h1>
				<div class="paper-meta">
					{#each metadata as item, index}
						<span>{item}</span>
						{#if index < metadata.length - 1}
							<span aria-hidden="true">|</span>
						{/if}
					{/each}
				</div>
			</div>
			<div class="header-icon-actions">
				<button type="button" aria-label={$t('workbench.starPaper')}>*</button>
				<button type="button" aria-label={$t('workbench.bookmarkPaper')}>B</button>
			</div>
		</header>

		<div class="pdf-toolbar" aria-label={$t('workbench.readerToolbarLabel')}>
			<div class="page-control">{currentPage}</div>
			<span class="toolbar-muted">/ {pages.length}</span>
			<button type="button" class="icon-button" aria-label={$t('workbench.zoomOut')}>-</button>
			<button type="button" class="icon-button" aria-label={$t('workbench.zoomIn')}>+</button>
			<select bind:value={zoom} aria-label={$t('workbench.zoomLabel')}>
				{#each zoomLevels as level}
					<option value={level}>{level}</option>
				{/each}
			</select>
			<button type="button" class="icon-button" aria-label={$t('workbench.fitWidth')}>F</button>
			<button type="button" class="icon-button" aria-label={$t('workbench.searchSource')}>S</button>
			{#if sourceFileUrl}
				<a class="icon-button" href={sourceFileUrl} aria-label={$t('workbench.downloadSource')}
					>DL</a
				>
			{:else}
				<button type="button" class="icon-button" aria-label={$t('workbench.downloadSource')}>
					DL
				</button>
			{/if}
		</div>

		<div class="pdf-canvas">
			{#if readerMode === 'pdf'}
				<div class="pdf-object-stage" id={`pdf-page-${currentPage}`}>
					<object data={pdfSourceUrl} type="application/pdf" title={title}>
						<div class="empty-state">
							<h3>{$t('workbench.sourceUnavailableTitle')}</h3>
							<p>{$t('workbench.sourceUnavailableBody')}</p>
						</div>
					</object>
				</div>

				{#if sourceTargetMessageKey}
					<div class="source-target-note">
						<strong>{sourceTarget?.label}</strong>
						<span>{$t(sourceTargetMessageKey)}</span>
					</div>
				{/if}

				<div class="parsed-source-strip" aria-label={$t('workbench.parsedSourceFallback')}>
					{#each pages as page, pageIndex}
						<section class="parsed-page" id={`parsed-page-${page.page_number}`}>
							{#each page.paragraphs as paragraph, paragraphIndex}
								{#if shouldShowSectionHeading(pageIndex, paragraphIndex, paragraph.section)}
									<h3>{paragraph.section}</h3>
								{/if}
								<button
									type="button"
									id={paragraph.source_span_id ? `pdf-source-${paragraph.source_span_id}` : undefined}
									class:source-span--active={paragraph.source_span_id === activeSourceSpanId}
									class="pdf-paragraph"
									on:click={() => selectParagraph(paragraph.source_span_id)}
									on:keydown={(event) => handleParagraphKeydown(event, paragraph.source_span_id)}
								>
									{paragraph.text}
								</button>
							{/each}
						</section>
					{/each}
				</div>
			{:else if readerMode === 'text'}
				<div class="selection-popover" aria-label={$t('workbench.selectionActions')}>
					<button type="button">{$t('workbench.explain')}</button>
					<button type="button">{$t('workbench.summarize')}</button>
					<button type="button">{$t('workbench.addNote')}</button>
					<button type="button">{$t('workbench.more')}</button>
				</div>

				<div class="reader-tool-rail" aria-label={$t('workbench.readerToolsLabel')}>
					<button type="button" aria-label={$t('workbench.selectTool')}>T</button>
					<button type="button" aria-label={$t('workbench.panTool')}>P</button>
					<button type="button" aria-label={$t('workbench.commentTool')}>C</button>
					<button type="button" aria-label={$t('workbench.penTool')}>/</button>
					<button type="button" aria-label={$t('workbench.searchTool')}>S</button>
				</div>

				{#each pages as page, pageIndex}
					<section class="pdf-page" id={`pdf-page-${page.page_number}`} aria-label={page.label}>
						{#if page.page_number === 1}
							<h2>{title}</h2>
							<p class="authors">{metadata.slice(0, 2).join(' | ')}</p>
						{/if}
						{#each page.paragraphs as paragraph, paragraphIndex}
							{#if shouldShowSectionHeading(pageIndex, paragraphIndex, paragraph.section)}
								<h3>{paragraph.section}</h3>
							{/if}
							<button
								type="button"
								id={paragraph.source_span_id ? `pdf-source-${paragraph.source_span_id}` : undefined}
								class:source-span--active={paragraph.source_span_id === activeSourceSpanId}
								class="pdf-paragraph"
								on:click={() => selectParagraph(paragraph.source_span_id)}
								on:keydown={(event) => handleParagraphKeydown(event, paragraph.source_span_id)}
							>
								{paragraph.text}
							</button>
						{/each}
					</section>
				{/each}
			{:else}
				<div class="empty-state empty-state--reader">
					<h3>{$t('workbench.sourceUnavailableTitle')}</h3>
					<p>{$t('workbench.sourceUnavailableBody')}</p>
				</div>
			{/if}
		</div>
	</article>
</section>

<style>
	.paper-reader-grid {
		display: grid;
		grid-template-columns: 96px minmax(0, 1fr);
		gap: 16px;
		height: 100%;
		min-width: 0;
	}

	.thumbnail-rail {
		position: relative;
		width: 96px;
		height: 100%;
		padding: 12px 8px 56px;
		overflow-y: auto;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		background: #ffffff;
	}

	.thumbnail-tabs {
		display: grid;
		grid-template-columns: 1fr;
		gap: 6px;
		margin-bottom: 14px;
	}

	.thumbnail-tabs button,
	.outline-list button {
		height: 36px;
		border: 1px solid transparent;
		border-radius: 8px;
		background: transparent;
		color: #475569;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.thumbnail-tabs button.active,
	.outline-list button.active {
		border-color: #60a5fa;
		background: #eff6ff;
		color: #2563eb;
	}

	.page-thumbnails,
	.outline-list {
		display: grid;
		gap: 14px;
	}

	.page-thumbnail {
		position: relative;
		display: grid;
		place-items: center;
		width: 78px;
		padding: 0;
		border: 0;
		background: transparent;
		cursor: pointer;
	}

	.thumbnail-paper {
		display: grid;
		gap: 8px;
		width: 72px;
		height: 96px;
		padding: 12px 10px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
	}

	.page-thumbnail.active .thumbnail-paper {
		border: 2px solid #2563eb;
	}

	.thumbnail-paper span {
		height: 5px;
		border-radius: 999px;
		background: #e2e8f0;
	}

	.thumbnail-paper span:nth-child(2) {
		width: 72%;
	}

	.thumbnail-paper span:nth-child(4) {
		width: 58%;
	}

	.thumbnail-page {
		display: grid;
		width: 24px;
		height: 24px;
		margin-top: 6px;
		place-items: center;
		border-radius: 999px;
		background: #f1f5f9;
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
	}

	.page-thumbnail.active .thumbnail-page {
		background: #2563eb;
		color: #ffffff;
	}

	.outline-list button {
		width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.rail-bottom {
		position: absolute;
		right: 24px;
		bottom: 20px;
		width: 40px;
		height: 32px;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #ffffff;
		color: #64748b;
		cursor: pointer;
	}

	.pdf-shell {
		display: flex;
		min-width: 0;
		height: 100%;
		overflow: hidden;
		flex-direction: column;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		background: #ffffff;
	}

	.pdf-header {
		display: flex;
		height: 92px;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		padding: 20px 24px 12px;
		overflow: hidden;
		border-bottom: 1px solid #e2e8f0;
	}

	.pdf-header h1 {
		max-width: 520px;
		margin: 0;
		color: #0f172a;
		font-size: 22px;
		font-weight: 700;
		line-height: 1.22;
	}

	.paper-meta {
		display: flex;
		max-width: 520px;
		margin-top: 8px;
		align-items: center;
		gap: 8px;
		overflow: hidden;
		color: #64748b;
		font-size: 12px;
		font-weight: 500;
		line-height: 18px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.header-icon-actions {
		display: flex;
		gap: 8px;
	}

	.header-icon-actions button,
	.icon-button {
		display: grid;
		width: 32px;
		height: 32px;
		place-items: center;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
		color: #475569;
		font-size: 13px;
		font-weight: 700;
		text-decoration: none;
		cursor: pointer;
	}

	.pdf-toolbar {
		display: flex;
		height: 52px;
		align-items: center;
		gap: 12px;
		padding: 0 16px;
		border-bottom: 1px solid #e2e8f0;
	}

	.page-control,
	.pdf-toolbar select {
		display: grid;
		width: 48px;
		height: 32px;
		place-items: center;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		font-size: 13px;
	}

	.pdf-toolbar select {
		width: 72px;
		padding: 0 8px;
	}

	.toolbar-muted {
		color: #64748b;
		font-size: 13px;
	}

	.pdf-canvas {
		position: relative;
		flex: 1;
		padding: 24px 18px;
		overflow: auto;
		background: #f8fafc;
	}

	.pdf-object-stage {
		width: min(100%, 680px);
		height: calc(100% - 106px);
		min-height: 620px;
		margin: 0 auto 16px;
		overflow: hidden;
		border: 1px solid #e5e7eb;
		background: #ffffff;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
	}

	.pdf-object-stage object {
		display: block;
		width: 100%;
		height: 100%;
		border: 0;
	}

	.source-target-note {
		display: flex;
		width: min(100%, 680px);
		margin: 0 auto 12px;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 12px;
		border: 1px solid #bfdbfe;
		border-radius: 12px;
		background: #eff6ff;
		color: #1e40af;
		font-size: 12px;
		line-height: 18px;
	}

	.source-target-note strong {
		color: #0f172a;
		font-weight: 700;
	}

	.parsed-source-strip {
		width: min(100%, 680px);
		max-height: 190px;
		margin: 0 auto;
		overflow-y: auto;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
	}

	.parsed-page + .parsed-page {
		margin-top: 12px;
	}

	.pdf-page {
		width: 600px;
		min-height: 820px;
		margin: 0 auto 24px;
		padding: 32px 42px;
		border: 1px solid #e5e7eb;
		background: #ffffff;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
	}

	.pdf-page h2 {
		margin: 0 auto 18px;
		max-width: 430px;
		text-align: center;
		color: #111827;
		font-family: Georgia, 'Times New Roman', serif;
		font-size: 20px;
		font-weight: 700;
		line-height: 1.25;
	}

	.authors {
		margin: 0 0 24px;
		text-align: center;
		color: #334155;
		font-family: Georgia, 'Times New Roman', serif;
		font-size: 12px;
		line-height: 1.55;
	}

	.pdf-page h3 {
		margin: 18px 0 8px;
		font-family: Georgia, 'Times New Roman', serif;
		font-size: 15px;
		font-weight: 700;
		line-height: 1.35;
	}

	.parsed-page h3 {
		margin: 0 0 8px;
		color: #0f172a;
		font-size: 13px;
		font-weight: 700;
		line-height: 18px;
	}

	.pdf-paragraph {
		display: block;
		width: 100%;
		margin: 0 0 12px;
		padding: 3px 4px;
		scroll-margin-top: 80px;
		border: 1px solid transparent;
		border-radius: 4px;
		background: transparent;
		color: #111827;
		font-family: Georgia, 'Times New Roman', serif;
		font-size: 12px;
		line-height: 1.55;
		text-align: left;
		cursor: pointer;
	}

	.parsed-source-strip .pdf-paragraph {
		font-family:
			system-ui,
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			sans-serif;
		font-size: 12px;
		line-height: 18px;
	}

	.source-span--active {
		border-color: #60a5fa;
		background: #dbeafe;
		box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
	}

	.empty-state {
		display: grid;
		height: 100%;
		place-content: center;
		gap: 8px;
		padding: 24px;
		border: 1px dashed #cbd5e1;
		border-radius: 14px;
		background: #f8fafc;
		text-align: center;
	}

	.empty-state h3 {
		margin: 0;
		color: #0f172a;
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
	}

	.empty-state p {
		max-width: 320px;
		margin: 0;
		color: #64748b;
		font-size: 14px;
		line-height: 22px;
	}

	.empty-state--reader {
		min-height: 320px;
	}

	.selection-popover {
		position: sticky;
		top: 374px;
		z-index: 2;
		display: flex;
		width: fit-content;
		height: 44px;
		margin: 0 auto -44px;
		align-items: center;
		gap: 10px;
		padding: 0 12px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		background: #ffffff;
		box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
	}

	.selection-popover button {
		border: 0;
		background: transparent;
		color: #334155;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.reader-tool-rail {
		position: sticky;
		top: 390px;
		z-index: 3;
		display: grid;
		width: 44px;
		margin: 24px 0 -236px auto;
		gap: 8px;
	}

	.reader-tool-rail button {
		display: grid;
		width: 36px;
		height: 36px;
		place-items: center;
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #ffffff;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
		color: #2563eb;
		font-size: 14px;
		font-weight: 700;
		cursor: pointer;
	}

	@media (max-width: 1024px) {
		.paper-reader-grid {
			grid-template-columns: 1fr;
		}

		.thumbnail-rail {
			display: none;
		}

		.pdf-page {
			width: min(600px, 100%);
		}
	}
</style>
