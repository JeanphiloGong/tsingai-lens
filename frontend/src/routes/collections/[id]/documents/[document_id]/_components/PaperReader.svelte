<script lang="ts">
	import { browser } from '$app/environment';
	import { onDestroy, onMount, tick } from 'svelte';
	import { t } from '../../../../../_shared/i18n';
	import type {
		SourceAnchor,
		SourceAnchorRect,
		WorkbenchPdfPage
	} from '../../../../../_shared/documents';
	import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist/legacy/build/pdf.mjs';

	type PdfJsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');
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
	type SourceSearchMatch = {
		pageNumber: number;
		sourceSpanId: string | null;
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
	let searchInput: HTMLInputElement | null = null;
	let pdfDocument: PDFDocumentProxy | null = null;
	let loadingTask: PdfLoadingTask | null = null;
	let pdfPageStates: PdfPageState[] = [];
	let readerView: 'pdf' | 'source' = 'pdf';
	let pendingSourceJump: SourceAnchor | null = null;
	let appliedSourceJumpKey = '';
	let sourceSearchOpen = false;
	let sourceSearchQuery = '';
	let searchMatchIndex = -1;
	let loadGeneration = 0;
	let renderGeneration = 0;
	let pageObserver: IntersectionObserver | null = null;

	const zoomLevels = ['Fit', '90%', '100%', '125%'];
	const canvasNodes = new Map<number, HTMLCanvasElement>();
	const pageShellNodes = new Map<number, HTMLElement>();
	const renderTasks = new Map<number, RenderTask>();
	const renderedPageNumbers = new Set<number>();
	const queuedPageNumbers = new Set<number>();

	$: hasPdfSource = Boolean(
		sourceFileUrl && (!sourceFilename || sourceFilename.toLowerCase().endsWith('.pdf'))
	);
	$: hasParsedSource = pages.some((page) => page.paragraphs.length > 0);
	$: showParsedSourceFallback = hasParsedSource && (!hasPdfSource || Boolean(pdfError));
	$: showParsedSourceView = hasParsedSource && (readerView === 'source' || showParsedSourceFallback);
	$: showPdfView = hasPdfSource && readerView === 'pdf' && !pdfError;
	$: totalPages = pdfPageStates.length || pages.length || 1;
	$: thumbnailPageNumbers = pageNumbersForReader(totalPages);
	$: sourceSearchMatches = sourceSearchResults(pages, sourceSearchQuery);
	$: sourceJumpKey = activeSourceAnchor
		? `${sourceJumpToken}:${activeSourceAnchor.pageIndex}:${activeSourceAnchor.precision ?? ''}`
		: '';
	$: pendingSourceJumpPage = pendingSourceJump ? pendingSourceJump.pageIndex + 1 : null;
	$: pendingSourceJumpReady = Boolean(
		pendingSourceJumpPage !== null &&
		pdfPageStates.some((page) => page.pageNumber === pendingSourceJumpPage)
	);
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
	$: if (mounted && activeSourceAnchor && sourceJumpKey && sourceJumpKey !== appliedSourceJumpKey) {
		appliedSourceJumpKey = sourceJumpKey;
		void jumpToSource(activeSourceAnchor);
	}
	$: if (mounted && pendingSourceJump && pendingSourceJumpReady) {
		void flushPendingSourceJump();
	}
	$: if (mounted && !hasPdfSource) {
		clearPdfState();
	}
	$: if (!sourceSearchMatches.length && searchMatchIndex !== -1) {
		searchMatchIndex = -1;
	}
	$: if (sourceSearchMatches.length && searchMatchIndex >= sourceSearchMatches.length) {
		searchMatchIndex = 0;
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
			import('pdfjs-dist/legacy/build/pdf.mjs'),
			import('pdfjs-dist/legacy/build/pdf.worker.mjs?url')
		]);
		pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
		return pdfjs;
	}

	function cleanupPdf() {
		loadGeneration += 1;
		renderGeneration += 1;
		disconnectPageObserver();
		cancelRenderTasks();
		const task = loadingTask;
		loadingTask = null;
		if (task?.destroy) void task.destroy();
		const document = pdfDocument;
		pdfDocument = null;
		if (document) void document.destroy();
		canvasNodes.clear();
		pageShellNodes.clear();
		renderedPageNumbers.clear();
		queuedPageNumbers.clear();
		pendingSourceJump = null;
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

	function disconnectPageObserver() {
		pageObserver?.disconnect();
		pageObserver = null;
	}

	async function renderAllPages() {
		const document = pdfDocument;
		if (!document) return;

		const generation = loadGeneration;
		const renderId = ++renderGeneration;
		cancelRenderTasks();
		renderedPageNumbers.clear();
		queuedPageNumbers.clear();
		disconnectPageObserver();

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
			observePageShells();
			await renderInitialPages(renderId);
		} catch (error) {
			if (generation !== loadGeneration || renderId !== renderGeneration) return;
			pdfError = error instanceof Error ? error.message : String(error);
		}
	}

	function initialPageNumbers() {
		const pageNumbers = new Set<number>();
		pageNumbers.add(currentPage);
		pageNumbers.add(currentPage + 1);
		if (activeSourceAnchor) pageNumbers.add(activeSourceAnchor.pageIndex + 1);
		if (pendingSourceJumpPage) pageNumbers.add(pendingSourceJumpPage);
		return Array.from(pageNumbers).filter(
			(pageNumber) => pageNumber >= 1 && pageNumber <= totalPages
		);
	}

	async function renderInitialPages(renderId: number) {
		await Promise.all(
			initialPageNumbers().map((pageNumber) => ensurePageRendered(pageNumber, renderId))
		);
	}

	function observePageShells() {
		disconnectPageObserver();
		if (!browser || !pdfScrollContainer || !('IntersectionObserver' in window)) {
			void renderInitialPages(renderGeneration);
			return;
		}

		pageObserver = new IntersectionObserver(
			(entries) => {
				for (const entry of entries) {
					if (!entry.isIntersecting) continue;
					const pageNumber = Number((entry.target as HTMLElement).dataset.pageNumber);
					if (Number.isFinite(pageNumber)) void ensurePageRendered(pageNumber, renderGeneration);
				}
			},
			{ root: pdfScrollContainer, rootMargin: '900px 0px', threshold: 0.01 }
		);

		for (const node of pageShellNodes.values()) {
			pageObserver.observe(node);
		}
	}

	async function ensurePageRendered(pageNumber: number, renderId = renderGeneration) {
		if (renderedPageNumbers.has(pageNumber) || queuedPageNumbers.has(pageNumber)) return;
		if (pageNumber < 1 || pageNumber > totalPages) return;

		queuedPageNumbers.add(pageNumber);
		const rendered = await renderPage(pageNumber, renderId);
		queuedPageNumbers.delete(pageNumber);
		if (rendered) renderedPageNumbers.add(pageNumber);
	}

	async function renderPage(pageNumber: number, renderId: number): Promise<boolean> {
		const document = pdfDocument;
		let canvas = canvasNodes.get(pageNumber);
		if (!document || renderId !== renderGeneration) return false;
		if (!canvas) {
			await tick();
			canvas = canvasNodes.get(pageNumber);
		}
		if (!canvas) return false;

		updatePageState(pageNumber, { status: 'rendering', error: null });

		try {
			const page = await document.getPage(pageNumber);
			if (renderId !== renderGeneration) return false;

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
			return renderId === renderGeneration;
		} catch (error) {
			renderTasks.delete(pageNumber);
			if (renderId !== renderGeneration) return false;
			if (error instanceof Error && error.name === 'RenderingCancelledException') return false;
			updatePageState(pageNumber, {
				status: 'error',
				error: error instanceof Error ? error.message : String(error)
			});
			return false;
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
		await ensurePageRendered(pageNumber);
		const target = document.getElementById(`pdf-page-${pageNumber}`);
		if (target) {
			pendingSourceJump = null;
			scrollPageIntoView(target, 'center');
		} else {
			pendingSourceJump = anchor;
		}
	}

	async function scrollToPage(pageNumber: number) {
		currentPage = pageNumber;
		if (!browser) return;
		await tick();
		await ensurePageRendered(pageNumber);
		const target = document.getElementById(`pdf-page-${pageNumber}`);
		if (target) {
			scrollPageIntoView(target, 'start');
		}
	}

	async function flushPendingSourceJump() {
		const anchor = pendingSourceJump;
		if (!anchor) return;
		await jumpToSource(anchor);
	}

	function scrollPageIntoView(target: HTMLElement, block: 'start' | 'center') {
		if (!pdfScrollContainer) return;
		const centerOffset =
			block === 'center'
				? Math.max(0, (pdfScrollContainer.clientHeight - target.clientHeight) / 2)
				: 0;
		const top = Math.max(0, target.offsetTop - centerOffset);
		pdfScrollContainer.scrollTo({ top, behavior: 'smooth' });
	}

	function updateCurrentPageFromScroll() {
		if (!pdfScrollContainer || !pageShellNodes.size) return;
		const viewportCenter = pdfScrollContainer.scrollTop + pdfScrollContainer.clientHeight / 2;
		let nearestPage = currentPage;
		let nearestDistance = Number.POSITIVE_INFINITY;

		for (const [pageNumber, node] of pageShellNodes) {
			const pageCenter = node.offsetTop + node.clientHeight / 2;
			const distance = Math.abs(pageCenter - viewportCenter);
			if (distance < nearestDistance) {
				nearestDistance = distance;
				nearestPage = pageNumber;
			}
		}

		currentPage = nearestPage;
	}

	function changeZoom(delta: number) {
		const index = zoomLevels.indexOf(zoom);
		const nextIndex = Math.max(0, Math.min(zoomLevels.length - 1, index + delta));
		zoom = zoomLevels[nextIndex] ?? '100%';
	}

	function sourceSearchResults(
		sourcePages: WorkbenchPdfPage[],
		query: string
	): SourceSearchMatch[] {
		const needle = query.trim().toLowerCase();
		if (!needle) return [];

		const matches: SourceSearchMatch[] = [];
		for (const page of sourcePages) {
			for (const paragraph of page.paragraphs) {
				const haystack = `${paragraph.section ?? ''} ${paragraph.text}`.toLowerCase();
				if (!haystack.includes(needle)) continue;
				matches.push({
					pageNumber: page.page_number,
					sourceSpanId: paragraph.source_span_id
				});
				if (matches.length >= 50) return matches;
			}
		}
		return matches;
	}

	async function toggleSourceSearch() {
		sourceSearchOpen = !sourceSearchOpen;
		if (sourceSearchOpen) {
			await tick();
			searchInput?.focus();
		}
	}

	async function focusSearchMatch(delta: number) {
		if (!sourceSearchMatches.length) return;
		searchMatchIndex =
			(searchMatchIndex + delta + sourceSearchMatches.length) % sourceSearchMatches.length;
		const match = sourceSearchMatches[searchMatchIndex];
		if (match.sourceSpanId) {
			onSelectSourceSpan(match.sourceSpanId);
			return;
		}
		await scrollToPage(match.pageNumber);
	}

	function handleSearchKeydown(event: KeyboardEvent) {
		if (event.key !== 'Enter') return;
		event.preventDefault();
		void focusSearchMatch(event.shiftKey ? -1 : 1);
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

	function selectParsedSource(pageNumber: number, sourceSpanId: string | null) {
		currentPage = pageNumber;
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

	function pageShell(node: HTMLElement, pageNumber: number) {
		node.dataset.pageNumber = String(pageNumber);
		pageShellNodes.set(pageNumber, node);
		pageObserver?.observe(node);

		return {
			update(nextPageNumber: number) {
				pageObserver?.unobserve(node);
				pageShellNodes.delete(pageNumber);
				pageNumber = nextPageNumber;
				node.dataset.pageNumber = String(pageNumber);
				pageShellNodes.set(pageNumber, node);
				pageObserver?.observe(node);
			},
			destroy() {
				pageObserver?.unobserve(node);
				pageShellNodes.delete(pageNumber);
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
				<button type="button" aria-label={$t('workbench.starPaper')}>
					<span class="toolbar-icon toolbar-icon--star" aria-hidden="true"></span>
				</button>
				<button type="button" aria-label={$t('workbench.bookmarkPaper')}>
					<span class="toolbar-icon toolbar-icon--bookmark" aria-hidden="true"></span>
				</button>
			</div>
		</header>

		<div class="pdf-toolbar" aria-label={$t('workbench.readerToolbarLabel')}>
			<div class="page-control" data-testid="pdf-current-page">{currentPage}</div>
			<span class="toolbar-muted">/ {totalPages}</span>
			{#if hasParsedSource && hasPdfSource && !pdfError}
				<button
					type="button"
					class="reader-view-toggle"
					aria-pressed={readerView === 'source'}
					aria-label={readerView === 'source'
						? $t('workbench.viewPdf')
						: $t('workbench.viewSourceText')}
					on:click={() => (readerView = readerView === 'source' ? 'pdf' : 'source')}
				>
					{readerView === 'source' ? $t('workbench.pdfView') : $t('workbench.sourceTextView')}
				</button>
			{/if}
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.zoomOut')}
				on:click={() => changeZoom(-1)}
			>
				<span class="toolbar-icon toolbar-icon--minus" aria-hidden="true"></span>
			</button>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.zoomIn')}
				on:click={() => changeZoom(1)}
			>
				<span class="toolbar-icon toolbar-icon--plus" aria-hidden="true"></span>
			</button>
			<select bind:value={zoom} aria-label={$t('workbench.zoomLabel')}>
				{#each zoomLevels as level}
					<option value={level}>{level}</option>
				{/each}
			</select>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.fitWidth')}
				on:click={() => (zoom = 'Fit')}
			>
				<span class="toolbar-icon toolbar-icon--fit" aria-hidden="true"></span>
			</button>
			<button
				type="button"
				class="icon-button"
				aria-label={$t('workbench.searchSource')}
				on:click={toggleSourceSearch}
			>
				<span class="toolbar-icon toolbar-icon--search" aria-hidden="true"></span>
			</button>
			{#if sourceFileUrl}
				<a class="icon-button" href={sourceFileUrl} aria-label={$t('workbench.downloadSource')}>
					<span class="toolbar-icon toolbar-icon--download" aria-hidden="true"></span>
				</a>
			{:else}
				<button type="button" class="icon-button" aria-label={$t('workbench.downloadSource')}>
					<span class="toolbar-icon toolbar-icon--download" aria-hidden="true"></span>
				</button>
			{/if}
			{#if activePendingAnchor}
				<span class="source-pending-badge">{$t('workbench.preciseRegionPending')}</span>
			{/if}
			{#if sourceSearchOpen}
				<label class="source-search-control">
					<span class="visually-hidden">{$t('workbench.searchSource')}</span>
					<input
						bind:this={searchInput}
						bind:value={sourceSearchQuery}
						placeholder={$t('workbench.searchSource')}
						on:keydown={handleSearchKeydown}
					/>
					<button
						type="button"
						aria-label={$t('workbench.searchSource')}
						disabled={!sourceSearchMatches.length}
						on:click={() => focusSearchMatch(1)}
					>
						{sourceSearchMatches.length}
					</button>
				</label>
			{/if}
		</div>

		<div
			class="pdf-scroll-container"
			bind:this={pdfScrollContainer}
			on:scroll={updateCurrentPageFromScroll}
		>
			{#if showPdfView}
				<div class="reader-tool-rail" aria-label={$t('workbench.readerToolsLabel')}>
					<button type="button" aria-label={$t('workbench.selectTool')}>
						<span class="toolbar-icon toolbar-icon--select" aria-hidden="true"></span>
					</button>
					<button type="button" aria-label={$t('workbench.panTool')}>
						<span class="toolbar-icon toolbar-icon--pan" aria-hidden="true"></span>
					</button>
					<button type="button" aria-label={$t('workbench.commentTool')}>
						<span class="toolbar-icon toolbar-icon--comment" aria-hidden="true"></span>
					</button>
					<button type="button" aria-label={$t('workbench.penTool')}>
						<span class="toolbar-icon toolbar-icon--pen" aria-hidden="true"></span>
					</button>
					<button type="button" aria-label={$t('workbench.searchTool')}>
						<span class="toolbar-icon toolbar-icon--search" aria-hidden="true"></span>
					</button>
				</div>
			{/if}

			{#if showPdfView && pdfPageStates.length}
				{#each pdfPageStates as page}
					<section
						class="pdf-page-shell"
						data-testid="pdf-page-shell"
						id={`pdf-page-${page.pageNumber}`}
						aria-label={page.label}
						style={`width: ${page.width}px; height: ${page.height}px;`}
						use:pageShell={page.pageNumber}
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
						{:else if page.status !== 'rendered'}
							<div class="page-loading" aria-hidden="true"></div>
						{/if}
					</section>
				{/each}
			{:else if showPdfView && pdfLoading}
				<div class="empty-state empty-state--reader">
					<div class="skeleton skeleton--wide"></div>
					<div class="skeleton"></div>
					<p>{$t('workbench.pdfLoading')}</p>
				</div>
			{:else if showParsedSourceView}
				<div class="parsed-source-fallback" data-testid="parsed-source-fallback">
					<header>
						<h3>
							{showParsedSourceFallback
								? $t('workbench.parsedSourceFallback')
								: $t('workbench.parsedSourceView')}
						</h3>
						<p>
							{#if pdfError}
								{$t('workbench.pdfLoadFailed')}
							{:else if showParsedSourceFallback}
								{$t('workbench.sourceUnavailableBody')}
							{:else}
								{$t('workbench.parsedSourceViewBody')}
							{/if}
						</p>
					</header>
					{#each pages as page}
						<section
							class="parsed-source-page"
							id={`pdf-page-${page.page_number}`}
							aria-label={page.label}
						>
							<div class="parsed-source-page__label">{page.label}</div>
							{#each page.paragraphs as paragraph}
								<button
									type="button"
									class="parsed-source-paragraph"
									class:active={paragraph.source_span_id === activeSourceSpanId}
									on:click={() => selectParsedSource(page.page_number, paragraph.source_span_id)}
								>
									<span>{paragraph.section || $t('workbench.sectionFallback')}</span>
									<p>{paragraph.text}</p>
								</button>
							{/each}
						</section>
					{/each}
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

	.toolbar-icon {
		position: relative;
		display: block;
		width: 16px;
		height: 16px;
		color: currentColor;
	}

	.toolbar-icon::before,
	.toolbar-icon::after {
		position: absolute;
		content: '';
		box-sizing: border-box;
	}

	.toolbar-icon--minus::before,
	.toolbar-icon--plus::before {
		left: 3px;
		top: 7px;
		width: 10px;
		height: 2px;
		border-radius: 2px;
		background: currentColor;
	}

	.toolbar-icon--plus::after {
		left: 7px;
		top: 3px;
		width: 2px;
		height: 10px;
		border-radius: 2px;
		background: currentColor;
	}

	.toolbar-icon--fit {
		border: 2px solid currentColor;
		border-radius: 4px;
	}

	.toolbar-icon--fit::before,
	.toolbar-icon--fit::after {
		width: 5px;
		height: 5px;
		border-color: currentColor;
	}

	.toolbar-icon--fit::before {
		left: 2px;
		top: 2px;
		border-top: 2px solid;
		border-left: 2px solid;
	}

	.toolbar-icon--fit::after {
		right: 2px;
		bottom: 2px;
		border-right: 2px solid;
		border-bottom: 2px solid;
	}

	.toolbar-icon--search::before {
		left: 2px;
		top: 2px;
		width: 9px;
		height: 9px;
		border: 2px solid currentColor;
		border-radius: 999px;
	}

	.toolbar-icon--search::after {
		left: 10px;
		top: 10px;
		width: 6px;
		height: 2px;
		border-radius: 2px;
		background: currentColor;
		transform: rotate(45deg);
		transform-origin: left center;
	}

	.toolbar-icon--download::before {
		left: 7px;
		top: 2px;
		width: 2px;
		height: 9px;
		border-radius: 2px;
		background: currentColor;
	}

	.toolbar-icon--download::after {
		left: 3px;
		top: 8px;
		width: 10px;
		height: 10px;
		border-right: 2px solid currentColor;
		border-bottom: 2px solid currentColor;
		transform: rotate(45deg);
	}

	.toolbar-icon--star {
		background: currentColor;
		clip-path: polygon(
			50% 4%,
			61% 36%,
			95% 36%,
			67% 55%,
			78% 88%,
			50% 68%,
			22% 88%,
			33% 55%,
			5% 36%,
			39% 36%
		);
	}

	.toolbar-icon--bookmark {
		border: 2px solid currentColor;
		border-bottom: 0;
		border-radius: 3px 3px 1px 1px;
	}

	.toolbar-icon--bookmark::before {
		left: 2px;
		bottom: -1px;
		width: 8px;
		height: 8px;
		border-left: 2px solid currentColor;
		border-bottom: 2px solid currentColor;
		transform: rotate(-45deg);
	}

	.toolbar-icon--select {
		clip-path: polygon(2px 1px, 14px 8px, 9px 10px, 11px 15px, 8px 16px, 6px 11px, 2px 14px);
		background: currentColor;
	}

	.toolbar-icon--pan::before,
	.toolbar-icon--pan::after {
		background: currentColor;
	}

	.toolbar-icon--pan::before {
		left: 7px;
		top: 1px;
		width: 2px;
		height: 14px;
	}

	.toolbar-icon--pan::after {
		left: 1px;
		top: 7px;
		width: 14px;
		height: 2px;
	}

	.toolbar-icon--comment {
		border: 2px solid currentColor;
		border-radius: 4px;
	}

	.toolbar-icon--comment::before {
		left: 3px;
		bottom: -4px;
		width: 7px;
		height: 7px;
		border-left: 2px solid currentColor;
		border-bottom: 2px solid currentColor;
		background: #ffffff;
		transform: rotate(-35deg);
	}

	.toolbar-icon--pen::before {
		left: 7px;
		top: 1px;
		width: 3px;
		height: 14px;
		border-radius: 2px;
		background: currentColor;
		transform: rotate(38deg);
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

	.reader-view-toggle {
		display: inline-flex;
		height: 32px;
		align-items: center;
		padding: 0 10px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		white-space: nowrap;
		cursor: pointer;
	}

	.reader-view-toggle[aria-pressed='true'] {
		border-color: #60a5fa;
		background: #eff6ff;
		color: #1d4ed8;
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

	.source-search-control {
		display: flex;
		width: min(260px, 38vw);
		height: 32px;
		align-items: center;
		overflow: hidden;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
	}

	.source-search-control input {
		min-width: 0;
		flex: 1;
		height: 100%;
		padding: 0 10px;
		border: 0;
		outline: 0;
		color: #0f172a;
		font-size: 13px;
	}

	.source-search-control button {
		display: grid;
		width: 42px;
		height: 100%;
		place-items: center;
		border: 0;
		border-left: 1px solid #dbeafe;
		background: #eff6ff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		cursor: pointer;
	}

	.source-search-control button:disabled {
		color: #94a3b8;
		cursor: default;
	}

	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
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

	.page-loading {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		background: linear-gradient(90deg, #f8fafc, #eef4fb, #f8fafc);
		background-size: 220% 100%;
		animation: page-loading 1.3s ease-in-out infinite;
	}

	.page-loading::before {
		width: 42%;
		height: 14px;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.32);
		content: '';
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

	.parsed-source-fallback {
		display: grid;
		max-width: 760px;
		margin: 0 auto;
		gap: 16px;
	}

	.parsed-source-fallback > header {
		display: grid;
		gap: 4px;
		padding: 14px 16px;
		border: 1px solid #dbeafe;
		border-radius: 12px;
		background: #ffffff;
	}

	.parsed-source-fallback h3,
	.parsed-source-fallback p {
		margin: 0;
	}

	.parsed-source-fallback h3 {
		color: #0f172a;
		font-size: 15px;
		line-height: 22px;
	}

	.parsed-source-fallback > header p {
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.parsed-source-page {
		display: grid;
		gap: 10px;
		padding: 16px;
		border: 1px solid #e2e8f0;
		border-radius: 12px;
		background: #ffffff;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.05);
	}

	.parsed-source-page__label {
		color: #64748b;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
		text-transform: uppercase;
	}

	.parsed-source-paragraph {
		display: grid;
		width: 100%;
		gap: 4px;
		padding: 10px 12px;
		border: 1px solid transparent;
		border-radius: 10px;
		background: #f8fafc;
		color: #334155;
		text-align: left;
		cursor: pointer;
	}

	.parsed-source-paragraph.active {
		border-color: #60a5fa;
		background: #eff6ff;
	}

	.parsed-source-paragraph span {
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
	}

	.parsed-source-paragraph p {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
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

	@keyframes page-loading {
		0% {
			background-position: 0% 50%;
		}
		100% {
			background-position: 200% 50%;
		}
	}

	@media (max-width: 1024px) {
		.paper-reader-grid {
			grid-template-columns: 1fr;
			grid-template-rows: auto minmax(0, 1fr);
		}

		.thumbnail-rail {
			width: 100%;
			height: auto;
			min-height: 0;
			display: grid;
			grid-template-columns: auto minmax(0, 1fr);
			gap: 10px;
			padding: 8px;
			overflow: hidden;
		}

		.thumbnail-tabs {
			width: 96px;
			margin-bottom: 0;
		}

		.page-thumbnails,
		.outline-list {
			display: flex;
			gap: 10px;
			overflow-x: auto;
			padding-bottom: 2px;
			scrollbar-width: none;
		}

		.page-thumbnails::-webkit-scrollbar,
		.outline-list::-webkit-scrollbar {
			display: none;
		}

		.page-thumbnail {
			flex: 0 0 72px;
			width: 72px;
		}

		.thumbnail-paper {
			width: 64px;
			height: 78px;
			gap: 6px;
			padding: 10px 9px;
		}

		.rail-bottom {
			display: none;
		}

		.pdf-header {
			height: auto;
			min-height: 92px;
			padding: 18px 16px 10px;
		}

		.pdf-header h1,
		.paper-meta {
			max-width: 100%;
		}

		.paper-meta {
			flex-wrap: wrap;
			overflow: visible;
			white-space: normal;
		}

		.pdf-toolbar {
			min-height: 52px;
			overflow-x: auto;
			overflow-y: hidden;
			padding: 0 12px;
			scrollbar-width: none;
		}

		.pdf-toolbar::-webkit-scrollbar {
			display: none;
		}

		.pdf-toolbar > * {
			flex: 0 0 auto;
		}
	}
</style>
