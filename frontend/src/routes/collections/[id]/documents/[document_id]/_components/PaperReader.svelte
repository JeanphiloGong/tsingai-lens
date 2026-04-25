<script lang="ts">
	import { browser } from '$app/environment';
	import { onDestroy, onMount, tick } from 'svelte';
	import { t } from '../../../../../_shared/i18n';
	import type {
		SourceAnchor,
		SourceAnchorRect,
		WorkbenchPdfPage
	} from '../../../../../_shared/documents';
	import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';

	type PdfJsModule = typeof import('pdfjs-dist');
	type PdfLoadingTask = {
		promise: Promise<PDFDocumentProxy>;
		destroy?: () => Promise<void> | void;
	};
	type PdfPageState = {
		pageNumber: number;
		label: string;
		width: number;
		height: number;
		status: 'queued' | 'rendering' | 'rendered' | 'error';
		error: string | null;
	};

	export let title = '';
	export let metadata: string[] = [];
	export let pages: WorkbenchPdfPage[] = [];
	export let sourceFileUrl = '';
	export let sourceFilename: string | null = null;
	export let activeSourceSpanId = '';
	export let activeSourceAnchor: SourceAnchor | null = null;
	export let sourceJumpToken = 0;
	export let onSelectSourceSpan: (sourceSpanId: string) => void = () => {};

	let thumbnailTab: 'source' | 'outline' = 'source';
	let currentPage = 1;
	let zoom = 'Fit';
	let mounted = false;
	let loadedSourceFileUrl = '';
	let renderedZoom = '';
	let pdfLoading = false;
	let pdfError = '';
	let pdfScrollContainer: HTMLDivElement | null = null;
	let pdfDocument: PDFDocumentProxy | null = null;
	let loadingTask: PdfLoadingTask | null = null;
	let pdfPageStates: PdfPageState[] = [];
	let loadGeneration = 0;
	let renderGeneration = 0;

	const zoomLevels = ['Fit', '90%', '100%', '125%'];
	const canvasNodes = new Map<number, HTMLCanvasElement>();
	const renderTasks = new Map<number, RenderTask>();

	$: hasPdfSource = Boolean(
		sourceFileUrl && (!sourceFilename || sourceFilename.toLowerCase().endsWith('.pdf'))
	);
	$: totalPages = pdfPageStates.length || pages.length || 1;
	$: thumbnailPageNumbers = pageNumbersForReader(totalPages);
	$: activePendingAnchor = Boolean(
		activeSourceAnchor &&
		activeSourceAnchor.pageIndex >= 0 &&
		(activeSourceAnchor.rects.length === 0 || activeSourceAnchor.precision === 'pending')
	);
	$: if (mounted && hasPdfSource && sourceFileUrl && sourceFileUrl !== loadedSourceFileUrl) {
		void loadPdf();
	}
	$: if (mounted && pdfDocument && zoom !== renderedZoom) {
		renderedZoom = zoom;
		void renderAllPages();
	}
	$: if (mounted && activeSourceAnchor && sourceJumpToken >= 0) {
		void jumpToSource(activeSourceAnchor);
	}
	$: if (mounted && !hasPdfSource) {
		clearPdfState();
	}

	onMount(() => {
		mounted = true;
		if (hasPdfSource) void loadPdf();
	});

	onDestroy(() => {
		mounted = false;
		cleanupPdf();
	});

	function clearPdfState() {
		if (!pdfDocument && !pdfPageStates.length && !loadedSourceFileUrl) return;
		cleanupPdf();
		pdfPageStates = [];
		pdfError = '';
		loadedSourceFileUrl = '';
	}

	async function loadPdfJs(): Promise<PdfJsModule> {
		const [pdfjs, worker] = await Promise.all([
			import('pdfjs-dist'),
			import('pdfjs-dist/build/pdf.worker.mjs?url')
		]);
		pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
		return pdfjs;
	}

	function cleanupPdf() {
		loadGeneration += 1;
		renderGeneration += 1;
		cancelRenderTasks();
		const task = loadingTask;
		loadingTask = null;
		if (task?.destroy) void task.destroy();
		const document = pdfDocument;
		pdfDocument = null;
		if (document) void document.destroy();
		canvasNodes.clear();
	}

	async function loadPdf() {
		const sourceUrl = sourceFileUrl;
		if (!sourceUrl || !hasPdfSource) return;

		cleanupPdf();
		const generation = loadGeneration;
		loadedSourceFileUrl = sourceUrl;
		pdfLoading = true;
		pdfError = '';
		pdfPageStates = [];

		try {
			const pdfjs = await loadPdfJs();
			if (generation !== loadGeneration) return;
			const task = pdfjs.getDocument({ url: sourceUrl }) as PdfLoadingTask;
			loadingTask = task;
			const document = await task.promise;
			if (loadingTask === task) loadingTask = null;
			if (generation !== loadGeneration) {
				await document.destroy();
				return;
			}
			pdfDocument = document;
			currentPage = 1;
			renderedZoom = '';
		} catch (error) {
			if (generation !== loadGeneration) return;
			pdfDocument = null;
			pdfError = error instanceof Error ? error.message : String(error);
		} finally {
			if (generation === loadGeneration) {
				pdfLoading = false;
			}
		}
	}

	function cancelRenderTasks() {
		for (const task of renderTasks.values()) {
			task.cancel();
		}
		renderTasks.clear();
	}

	async function renderAllPages() {
		const document = pdfDocument;
		if (!document) return;

		const generation = loadGeneration;
		const renderId = ++renderGeneration;
		cancelRenderTasks();

		try {
			const nextPages: PdfPageState[] = [];
			for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
				const page = await document.getPage(pageNumber);
				if (generation !== loadGeneration || renderId !== renderGeneration) return;
				const baseViewport = page.getViewport({ scale: 1 });
				const scale = scaleForPage(baseViewport.width);
				const viewport = page.getViewport({ scale });
				nextPages.push({
					pageNumber,
					label: $t('workbench.pageLabel', { page: pageNumber }),
					width: Math.round(viewport.width),
					height: Math.round(viewport.height),
					status: 'queued',
					error: null
				});
			}

			pdfPageStates = nextPages;
			await tick();
			await Promise.all(nextPages.map((page) => renderPage(page.pageNumber, renderId)));
		} catch (error) {
			if (generation !== loadGeneration || renderId !== renderGeneration) return;
			pdfError = error instanceof Error ? error.message : String(error);
		}
	}

	async function renderPage(pageNumber: number, renderId: number) {
		const document = pdfDocument;
		const canvas = canvasNodes.get(pageNumber);
		if (!document || !canvas || renderId !== renderGeneration) return;

		updatePageState(pageNumber, { status: 'rendering', error: null });

		try {
			const page = await document.getPage(pageNumber);
			if (renderId !== renderGeneration) return;

			const baseViewport = page.getViewport({ scale: 1 });
			const scale = scaleForPage(baseViewport.width);
			const viewport = page.getViewport({ scale });
			const outputScale = browser ? window.devicePixelRatio || 1 : 1;
			const context = canvas.getContext('2d');
			if (!context) throw new Error('Canvas rendering context is unavailable.');

			canvas.width = Math.floor(viewport.width * outputScale);
			canvas.height = Math.floor(viewport.height * outputScale);
			canvas.style.width = `${viewport.width}px`;
			canvas.style.height = `${viewport.height}px`;

			const task = page.render({
				canvasContext: context,
				canvas,
				viewport,
				transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined
			});
			renderTasks.set(pageNumber, task);
			await task.promise;
			renderTasks.delete(pageNumber);

			if (renderId === renderGeneration) {
				updatePageState(pageNumber, {
					width: Math.round(viewport.width),
					height: Math.round(viewport.height),
					status: 'rendered',
					error: null
				});
			}
		} catch (error) {
			renderTasks.delete(pageNumber);
			if (renderId !== renderGeneration) return;
			if (error instanceof Error && error.name === 'RenderingCancelledException') return;
			updatePageState(pageNumber, {
				status: 'error',
				error: error instanceof Error ? error.message : String(error)
			});
		}
	}

	function updatePageState(pageNumber: number, patch: Partial<PdfPageState>) {
		pdfPageStates = pdfPageStates.map((page) =>
			page.pageNumber === pageNumber ? { ...page, ...patch } : page
		);
	}

	function scaleForPage(baseWidth: number) {
		if (zoom === 'Fit') {
			const availableWidth = Math.max(320, (pdfScrollContainer?.clientWidth ?? 680) - 36);
			return Math.max(0.5, Math.min(1.8, availableWidth / baseWidth));
		}
		const parsed = Number.parseFloat(zoom.replace('%', ''));
		return Number.isFinite(parsed) ? parsed / 100 : 1;
	}

	function pageNumbersForReader(count: number) {
		return Array.from({ length: Math.max(1, count) }, (_, index) => index + 1);
	}

	async function jumpToSource(anchor: SourceAnchor) {
		if (!browser) return;
		const pageNumber = Math.max(1, Math.min(totalPages, anchor.pageIndex + 1));
		currentPage = pageNumber;
		await tick();
		const target = document.getElementById(`pdf-page-${pageNumber}`);
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

	function changeZoom(delta: number) {
		const index = zoomLevels.indexOf(zoom);
		const nextIndex = Math.max(0, Math.min(zoomLevels.length - 1, index + delta));
		zoom = zoomLevels[nextIndex] ?? '100%';
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

	function selectOutlineSource(sourceSpanId: string | null) {
		if (sourceSpanId) onSelectSourceSpan(sourceSpanId);
	}

	function rectStyle(rect: SourceAnchorRect) {
		return `left: ${rect.left}%; top: ${rect.top}%; width: ${rect.width}%; height: ${rect.height}%;`;
	}

	function canvasPage(node: HTMLCanvasElement, pageNumber: number) {
		canvasNodes.set(pageNumber, node);
		return {
			update(nextPageNumber: number) {
				canvasNodes.delete(pageNumber);
				pageNumber = nextPageNumber;
				canvasNodes.set(pageNumber, node);
			},
			destroy() {
				canvasNodes.delete(pageNumber);
			}
		};
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
				{#each thumbnailPageNumbers as pageNumber}
					<button
						type="button"
						class:active={currentPage === pageNumber}
						class="page-thumbnail"
						aria-label={$t('workbench.pageLabel', { page: pageNumber })}
						on:click={() => void scrollToPage(pageNumber)}
					>
						<span class="thumbnail-paper" aria-hidden="true">
							<span></span>
							<span></span>
							<span></span>
							<span></span>
						</span>
						<span class="thumbnail-page">{pageNumber}</span>
					</button>
				{/each}
			</div>
		{:else}
			<div class="outline-list">
				{#each outlineSections() as section}
					<button
						type="button"
						on:click={() => selectOutlineSource(section.sourceSpanId)}
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
			<span class="toolbar-muted">/ {totalPages}</span>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.zoomOut')}
				on:click={() => changeZoom(-1)}>-</button
			>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.zoomIn')}
				on:click={() => changeZoom(1)}>+</button
			>
			<select bind:value={zoom} aria-label={$t('workbench.zoomLabel')}>
				{#each zoomLevels as level}
					<option value={level}>{level}</option>
				{/each}
			</select>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.fitWidth')}
				on:click={() => (zoom = 'Fit')}>F</button
			>
			<button type="button" class="icon-button" aria-label={$t('workbench.searchSource')}>S</button>
			{#if sourceFileUrl}
				<a class="icon-button" href={sourceFileUrl} aria-label={$t('workbench.downloadSource')}
					>DL</a
				>
			{:else}
				<button type="button" class="icon-button" aria-label={$t('workbench.downloadSource')}
					>DL</button
				>
			{/if}
			{#if activePendingAnchor}
				<span class="source-pending-badge">{$t('workbench.preciseRegionPending')}</span>
			{/if}
		</div>

		<div class="pdf-scroll-container" bind:this={pdfScrollContainer}>
			<div class="reader-tool-rail" aria-label={$t('workbench.readerToolsLabel')}>
				<button type="button" aria-label={$t('workbench.selectTool')}>T</button>
				<button type="button" aria-label={$t('workbench.panTool')}>P</button>
				<button type="button" aria-label={$t('workbench.commentTool')}>C</button>
				<button type="button" aria-label={$t('workbench.penTool')}>/</button>
				<button type="button" aria-label={$t('workbench.searchTool')}>S</button>
			</div>

			{#if hasPdfSource && pdfPageStates.length}
				{#each pdfPageStates as page}
					<section
						class="pdf-page-shell"
						data-testid="pdf-page-shell"
						id={`pdf-page-${page.pageNumber}`}
						aria-label={page.label}
						style={`width: ${page.width}px; height: ${page.height}px;`}
					>
						<canvas class="pdf-canvas-layer" use:canvasPage={page.pageNumber}></canvas>
						<div class="pdf-text-layer" aria-hidden="true"></div>
						<div class="pdf-highlight-layer" aria-hidden="true">
							{#if activeSourceAnchor && activeSourceAnchor.pageIndex === page.pageNumber - 1}
								{#key sourceJumpToken}
									{#each activeSourceAnchor.rects as rect}
										<span class="pdf-highlight" data-testid="pdf-highlight" style={rectStyle(rect)}
										></span>
									{/each}
								{/key}
							{/if}
						</div>
						{#if page.status === 'error'}
							<div class="page-error">
								<strong>{$t('workbench.pdfPageRenderError')}</strong>
								<span>{page.error}</span>
							</div>
						{/if}
					</section>
				{/each}
			{:else if hasPdfSource && pdfLoading}
				<div class="empty-state empty-state--reader">
					<div class="skeleton skeleton--wide"></div>
					<div class="skeleton"></div>
					<p>{$t('workbench.pdfLoading')}</p>
				</div>
			{:else}
				<div class="empty-state empty-state--reader">
					<h3>{$t('workbench.sourceUnavailableTitle')}</h3>
					<p>
						{#if pdfError}
							{$t('workbench.pdfLoadFailed')}
						{:else}
							{$t('workbench.sourceUnavailableBody')}
						{/if}
					</p>
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

	.source-pending-badge {
		display: inline-flex;
		height: 26px;
		align-items: center;
		padding: 0 10px;
		border: 1px solid #bfdbfe;
		border-radius: 999px;
		background: #eff6ff;
		color: #1d4ed8;
		font-size: 12px;
		font-weight: 700;
		white-space: nowrap;
	}

	.pdf-scroll-container {
		position: relative;
		flex: 1;
		min-height: 0;
		padding: 24px 18px;
		overflow: auto;
		background: #f8fafc;
	}

	.pdf-page-shell {
		position: relative;
		margin: 0 auto 24px;
		overflow: hidden;
		border: 1px solid #e5e7eb;
		background: #ffffff;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
	}

	.pdf-canvas-layer,
	.pdf-text-layer,
	.pdf-highlight-layer {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}

	.pdf-canvas-layer {
		display: block;
	}

	.pdf-text-layer {
		pointer-events: none;
	}

	.pdf-highlight-layer {
		pointer-events: none;
	}

	.pdf-highlight {
		position: absolute;
		display: block;
		border: 1px solid #60a5fa;
		border-radius: 4px;
		background: rgba(59, 130, 246, 0.22);
		box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
		animation: highlight-focus 1.1s ease-out;
	}

	.page-error {
		position: absolute;
		inset: 16px;
		display: grid;
		place-content: center;
		gap: 6px;
		padding: 16px;
		border: 1px dashed #cbd5e1;
		border-radius: 14px;
		background: rgba(248, 250, 252, 0.94);
		color: #64748b;
		text-align: center;
		font-size: 13px;
		line-height: 20px;
	}

	.page-error strong {
		color: #0f172a;
		font-size: 15px;
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

	.skeleton {
		width: 280px;
		height: 16px;
		margin: 0 auto;
		border-radius: 8px;
		background: linear-gradient(90deg, #f1f5f9, #e2e8f0, #f1f5f9);
	}

	.skeleton--wide {
		width: 420px;
	}

	.reader-tool-rail {
		position: sticky;
		top: 366px;
		z-index: 4;
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

	@keyframes highlight-focus {
		0% {
			box-shadow:
				0 0 0 2px rgba(37, 99, 235, 0.1),
				0 0 0 0 rgba(37, 99, 235, 0.35);
		}
		55% {
			box-shadow:
				0 0 0 2px rgba(37, 99, 235, 0.16),
				0 0 0 8px rgba(37, 99, 235, 0.12);
		}
		100% {
			box-shadow:
				0 0 0 2px rgba(37, 99, 235, 0.12),
				0 0 0 0 rgba(37, 99, 235, 0);
		}
	}

	@media (max-width: 1024px) {
		.paper-reader-grid {
			grid-template-columns: 1fr;
		}

		.thumbnail-rail {
			display: none;
		}
	}
</style>
