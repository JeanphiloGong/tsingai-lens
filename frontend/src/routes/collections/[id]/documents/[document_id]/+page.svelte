<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import {
		buildDocumentWorkbenchModel,
		fetchDocumentContent,
		fetchDocumentMarkdown,
		type DocumentContentResponse,
		type DocumentMarkdownResponse,
		type DocumentMarkdownSourceMapItem,
		type DocumentSourceSelection,
		type DocumentWorkbenchModel,
		type SourceAnchor
	} from '../../../../_shared/documents';
	import {
		storePendingChatSourceContext,
		type ChatSourceContext
	} from '../../../../_shared/chatSessions';
	import { t } from '../../../../_shared/i18n';
	import MarkdownPaperReader from './_components/MarkdownPaperReader.svelte';
	import PaperReader from './_components/PaperReader.svelte';

	let model: DocumentWorkbenchModel | null = null;
	let content: DocumentContentResponse | null = null;
	let markdown: DocumentMarkdownResponse | null = null;
	let selectedSourceSpanId = '';
	let sourceJumpToken = 0;
	let loading = false;
	let loadError = '';
	let loadedDocumentKey = '';
	let appliedRequestKey = '';
	let loadGeneration = 0;
	let readerMode: 'parsed-paper' | 'pdf-preview' = 'parsed-paper';

	$: collectionId = $page.params.id ?? '';
	$: documentId = $page.params.document_id ?? '';
	$: requestedSourceRef = $page.url.searchParams.get('source_ref')?.trim() ?? '';
	$: requestedSourceQuote = $page.url.searchParams.get('quote')?.trim() ?? '';
	$: requestedPageNumber = positivePageParam($page.url.searchParams.get('page'));
	$: requestedReaderMode = readerModeParam($page.url.searchParams.get('view'));
	$: requestedReturnTo = safeReturnTo($page.url.searchParams.get('return_to'));
	$: documentKey = `${collectionId}:${documentId}`;
	$: requestKey = `${documentKey}:${requestedSourceRef}:${requestedSourceQuote}:${requestedPageNumber ?? ''}:${requestedReaderMode ?? ''}`;
	$: hasMarkdown = Boolean(markdown?.markdown);
	$: hasSource = Boolean(content || markdown?.markdown);
	$: selectedSourceAnchor = sourceAnchorForSelection(model, selectedSourceSpanId);
	$: selectedSourceSpan =
		model?.source_spans.find((span) => span.id === selectedSourceSpanId) ?? null;

	$: if (browser && collectionId && documentId && documentKey !== loadedDocumentKey) {
		loadedDocumentKey = documentKey;
		appliedRequestKey = '';
		void loadSource();
	}
	$: if (model && documentKey === loadedDocumentKey && requestKey !== appliedRequestKey) {
		appliedRequestKey = requestKey;
		applyRequestedSource();
	}

	function backHref() {
		return requestedReturnTo || `/collections/${collectionId}/documents`;
	}

	async function loadSource() {
		const generation = ++loadGeneration;
		loading = true;
		loadError = '';
		model = null;
		content = null;
		markdown = null;
		selectedSourceSpanId = '';
		readerMode = requestedReaderMode ?? (requestedSourceRef ? 'parsed-paper' : 'parsed-paper');

		const [contentResult, markdownResult] = await Promise.allSettled([
			fetchDocumentContent(collectionId, documentId),
			fetchDocumentMarkdown(collectionId, documentId)
		]);
		if (generation !== loadGeneration) return;

		content = contentResult.status === 'fulfilled' ? contentResult.value : null;
		markdown = markdownResult.status === 'fulfilled' ? markdownResult.value : null;
		model = buildDocumentWorkbenchModel({
			collectionId,
			documentId,
			content
		});
		if (!content && !markdown?.markdown) {
			const failure = contentResult.status === 'rejected' ? contentResult.reason : markdownResult;
			loadError =
				failure instanceof Error ? failure.message : $t('workbench.sourceContentUnavailableBody');
		}
		applyRequestedSource();
		appliedRequestKey = requestKey;
		loading = false;
	}

	function applyRequestedSource() {
		if (!model) return;
		if (!selectRequestedSourceRef(model)) selectRequestedPage(model);
	}

	function selectRequestedSourceRef(currentModel: DocumentWorkbenchModel) {
		if (!requestedSourceRef) return false;
		const sourceMapItem = markdownSourceMapItemForRef(
			markdown,
			normalizeSourceRefMatchKey(requestedSourceRef)
		);
		const sourceSpan = sourceSpanForSourceRef(currentModel, markdown, requestedSourceRef);
		if (!sourceSpan && !sourceMapItem) return false;
		selectedSourceSpanId = sourceSpan?.id ?? '';
		readerMode = requestedReaderMode ?? 'parsed-paper';
		sourceJumpToken += 1;
		return true;
	}

	function selectRequestedPage(currentModel: DocumentWorkbenchModel) {
		if (!requestedPageNumber) return false;
		const sourceSpan = currentModel.source_spans.find((span) => span.page === requestedPageNumber);
		if (!sourceSpan) return false;
		selectedSourceSpanId = sourceSpan.id;
		readerMode = requestedReaderMode ?? 'pdf-preview';
		sourceJumpToken += 1;
		return true;
	}

	function sourceAnchorForSelection(
		currentModel: DocumentWorkbenchModel | null,
		sourceSpanId: string
	): SourceAnchor | null {
		if (!currentModel || !sourceSpanId) return null;
		return currentModel.source_anchors_by_span_id[sourceSpanId] ?? null;
	}

	function selectSourceSpan(sourceSpanId: string) {
		selectedSourceSpanId = sourceSpanId;
		readerMode = 'pdf-preview';
		sourceJumpToken += 1;
	}

	function showParsedPaper() {
		if (hasMarkdown) readerMode = 'parsed-paper';
	}

	function showPdfPreview() {
		readerMode = 'pdf-preview';
	}

	function handSourceToResearchAgent(selection: DocumentSourceSelection) {
		if (!browser || !model) return;
		const sourceRef = selection.source_ref.trim();
		const sourceQuote = selection.quote.trim();
		if (!sourceRef || !sourceQuote) return;
		const sourceUrl = new URL(
			`/collections/${collectionId}/documents/${documentId}`,
			window.location.origin
		);
		sourceUrl.searchParams.set('view', 'parsed-paper');
		sourceUrl.searchParams.set('source_ref', sourceRef);
		if (selection.page) sourceUrl.searchParams.set('page', String(selection.page));
		const context: ChatSourceContext = {
			resource_ref: {
				resource_type: 'source',
				resource_id: `${documentId}:${sourceRef}`,
				href: `${sourceUrl.pathname}${sourceUrl.search}`
			},
			collection_id: collectionId,
			document_id: documentId,
			document_title: model.title,
			source_kind: selection.source_kind,
			source_ref: sourceRef,
			page: selection.page,
			quote: sourceQuote.slice(0, 6000),
			heading_path: selection.heading_path,
			quote_truncated: sourceQuote.length > 6000
		};
		storePendingChatSourceContext(context);
	}

	function positivePageParam(rawValue: string | null) {
		const value = Number(rawValue ?? NaN);
		if (!Number.isInteger(value) || value < 1) return null;
		return value;
	}

	function readerModeParam(rawValue: string | null): 'parsed-paper' | 'pdf-preview' | null {
		if (rawValue === 'parsed-paper' || rawValue === 'pdf-preview') return rawValue;
		if (rawValue === 'markdown') return 'parsed-paper';
		if (rawValue === 'pdf') return 'pdf-preview';
		return null;
	}

	function normalizeSourceRefMatchKey(value: string | null | undefined) {
		return (value ?? '').trim().toLowerCase();
	}

	function sourceSpanForSourceRef(
		currentModel: DocumentWorkbenchModel,
		markdownSource: DocumentMarkdownResponse | null,
		sourceRef: string
	) {
		const target = normalizeSourceRefMatchKey(sourceRef);
		if (!target) return null;

		const exactSpan = currentModel.source_spans.find((span) =>
			[
				span.id,
				span.block_id,
				span.anchor_id,
				span.target.sourceRef,
				span.target.headingPath,
				span.target.label
			].some((value) => normalizeSourceRefMatchKey(value) === target)
		);
		if (exactSpan) return exactSpan;

		const sourceMapItem = markdownSourceMapItemForRef(markdownSource, target);
		if (!sourceMapItem?.block_id) return null;
		return (
			currentModel.source_spans.find(
				(candidate) =>
					normalizeSourceRefMatchKey(candidate.block_id) ===
					normalizeSourceRefMatchKey(sourceMapItem.block_id)
			) ?? null
		);
	}

	function markdownSourceMapItemForRef(
		markdownSource: DocumentMarkdownResponse | null,
		target: string
	): DocumentMarkdownSourceMapItem | null {
		return (
			markdownSource?.source_map.find((item) =>
				[
					item.markdown_anchor,
					item.artifact_id,
					item.block_id,
					item.table_id,
					item.figure_id,
					item.heading_path
				].some((value) => normalizeSourceRefMatchKey(value) === target)
			) ?? null
		);
	}

	function safeReturnTo(rawValue: string | null) {
		const value = rawValue?.trim() ?? '';
		if (!value || !value.startsWith('/') || value.startsWith('//')) return '';
		return value;
	}
</script>

<svelte:head><title>{model?.title ?? $t('workbench.pageTitle')}</title></svelte:head>

<div class="document-reader-root">
	<header class="reader-header">
		<a class="reader-logo" href={`/collections/${collectionId}`} aria-label="Lens">L</a>
		<div class="reader-title">
			<nav aria-label={$t('workbench.breadcrumbLabel')}>
				<a href={`/collections/${collectionId}`}>{$t('workbench.workspace')}</a>
				<span>/</span>
				<a href={backHref()}>{$t('workbench.documents')}</a>
			</nav>
			<strong>{model?.title ?? documentId}</strong>
		</div>
		<a class="btn btn--ghost btn--small" href={backHref()}>{$t('workbench.documents')}</a>
	</header>

	{#if loading && !model}
		<main class="reader-state" aria-busy="true">{$t('workbench.loading')}</main>
	{:else if model && hasSource}
		<main class="reader-main">
			<div class="reader-mode-tabs" role="tablist" aria-label={$t('workbench.readerModeLabel')}>
				<button
					type="button"
					role="tab"
					aria-selected={readerMode === 'parsed-paper'}
					class:active={readerMode === 'parsed-paper'}
					disabled={!hasMarkdown}
					on:click={showParsedPaper}
				>
					{$t('workbench.parsedPaperView')}
				</button>
				<button
					type="button"
					role="tab"
					aria-selected={readerMode === 'pdf-preview'}
					class:active={readerMode === 'pdf-preview'}
					on:click={showPdfPreview}
				>
					{$t('workbench.pdfPreview')}
				</button>
			</div>

			<section class="reader-surface">
				{#if readerMode === 'parsed-paper' && hasMarkdown}
					<MarkdownPaperReader
						{markdown}
						sourceFileUrl={model.sourceFileUrl}
						activeSourceRef={requestedSourceRef}
						activeSourceQuote={requestedSourceQuote}
						activeSourceSpan={selectedSourceSpan}
						{collectionId}
						onAskSource={handSourceToResearchAgent}
						onShowPdf={showPdfPreview}
					/>
				{:else}
					<PaperReader
						title={model.title}
						metadata={model.metadata}
						pages={model.pages}
						sourceFileUrl={model.sourceFileUrl}
						sourceFilename={model.source_filename}
						activeSourceSpanId={selectedSourceSpanId}
						activeSourceAnchor={selectedSourceAnchor}
						{sourceJumpToken}
						{collectionId}
						onAskSource={handSourceToResearchAgent}
						onSelectSourceSpan={selectSourceSpan}
					/>
				{/if}
			</section>
		</main>
	{:else}
		<main class="reader-state reader-state--error" role="alert">
			<h2>{$t('workbench.sourceContentUnavailableTitle')}</h2>
			<p>{loadError || $t('workbench.sourceContentUnavailableBody')}</p>
			<a href={backHref()}>{$t('workbench.documents')}</a>
		</main>
	{/if}
</div>

<style>
	.document-reader-root {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: grid;
		grid-template-rows: 64px minmax(0, 1fr);
		background: #f6f9fd;
		color: #0f172a;
	}

	.reader-header {
		display: grid;
		grid-template-columns: 36px minmax(0, 1fr) auto;
		align-items: center;
		gap: 14px;
		padding: 0 22px;
		border-bottom: 1px solid #e2e8f0;
		background: rgba(255, 255, 255, 0.96);
	}

	.reader-logo {
		display: grid;
		width: 32px;
		height: 32px;
		place-items: center;
		border-radius: 8px;
		background: #2563eb;
		color: #fff;
		font-weight: 800;
	}

	.reader-title {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.reader-title nav {
		display: flex;
		gap: 7px;
		color: #64748b;
		font-size: 12px;
	}

	.reader-title strong {
		overflow: hidden;
		font-size: 14px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.reader-main {
		min-height: 0;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		gap: 10px;
		padding: 12px 20px 20px;
	}

	.reader-mode-tabs {
		display: inline-flex;
		width: fit-content;
		gap: 4px;
		padding: 4px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #fff;
	}

	.reader-mode-tabs button {
		min-height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: 6px;
		background: transparent;
		color: #475569;
		font-size: 13px;
		font-weight: 700;
		cursor: pointer;
	}

	.reader-mode-tabs button.active {
		background: #eff6ff;
		color: #1d4ed8;
	}

	.reader-mode-tabs button:disabled {
		color: #94a3b8;
		cursor: not-allowed;
	}

	.reader-surface {
		min-height: 0;
		overflow: hidden;
		border: 1px solid #dbe4f0;
		border-radius: 8px;
		background: #fff;
	}

	.reader-state {
		display: grid;
		place-content: center;
		gap: 8px;
		padding: 32px;
		color: #64748b;
		text-align: center;
	}

	.reader-state h2,
	.reader-state p {
		margin: 0;
	}

	.reader-state--error {
		color: #991b1b;
	}

	@media (max-width: 640px) {
		.reader-header {
			padding-inline: 12px;
		}

		.reader-header > .btn {
			display: none;
		}

		.reader-main {
			padding: 10px;
		}
	}
</style>
