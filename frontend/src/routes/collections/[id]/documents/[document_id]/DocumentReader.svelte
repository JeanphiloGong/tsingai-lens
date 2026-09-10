<script lang="ts">
	import { authState } from '../../../../_shared/auth';
	import { browser } from '$app/environment';
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
		storePendingChatSourceContexts,
		readPendingChatSourceContexts,
		MAX_CHAT_SOURCE_CONTEXTS,
		type ChatSourceContext
	} from '../../../../_shared/chatSessions';
	import { t } from '../../../../_shared/i18n';
	import MarkdownPaperReader from './_components/MarkdownPaperReader.svelte';
	import PaperReader from './_components/PaperReader.svelte';
	import { getContext, onDestroy } from 'svelte';
	import { ArrowLeft, MessageSquare } from '@lucide/svelte';
	import IconButton from '../../../../_shared/IconButton.svelte';
	import { DOCUMENT_AGENT, type DocumentAgent } from '../documentAgent';
	export let collectionId: string;
	export let documentId: string;
	export let search = '';
	export let navigationVersion = 0;
	export let onTitle: (title: string) => void = () => {};
	const agent = getContext<DocumentAgent>(DOCUMENT_AGENT);
	let selectedSources: ChatSourceContext[] = [];
	let selectionError = '';
	$: {
		$agent.sourceVersion;
		selectedSources = readPendingChatSourceContexts($authState.user?.user_id ?? '', collectionId);
	}
	$: selectedSourceKeys = selectedSources
		.filter((source) => source.document_id === documentId)
		.map((source) => `${source.source_kind}:${source.source_ref}`);

	function toggleSource(selection: DocumentSourceSelection, open = false) {
		if ($agent.busy) return;
		const context = sourceContext(selection);
		const userId = $authState.user?.user_id;
		if (!context || !userId) return;
		const exists = selectedSources.some(
			(item) =>
				item.document_id === context.document_id &&
				item.source_kind === context.source_kind &&
				item.source_ref === context.source_ref
		);
		if (!exists && selectedSources.length >= MAX_CHAT_SOURCE_CONTEXTS) {
			selectionError = $t('researchAgent.paperScope.blockLimit', {
				count: MAX_CHAT_SOURCE_CONTEXTS
			});
			return;
		}
		selectionError = '';
		const next = exists
			? open
				? selectedSources
				: selectedSources.filter(
						(item) =>
							!(
								item.document_id === context.document_id &&
								item.source_kind === context.source_kind &&
								item.source_ref === context.source_ref
							)
					)
			: [...selectedSources, context];
		storePendingChatSourceContexts(userId, collectionId, next);
		agent.update((state) => ({
			...state,
			open: open || state.open,
			sourceVersion: state.sourceVersion + 1
		}));
	}

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

	$: params = new URLSearchParams(search);
	$: requestedSourceRef = params.get('source_ref')?.trim() ?? '';
	$: requestedSourceQuote = params.get('quote')?.trim() ?? '';
	$: requestedPageNumber = positivePageParam(params.get('page'));
	$: requestedReaderMode = readerModeParam(params.get('view'));
	$: requestedReturnTo = safeReturnTo(params.get('return_to'));
	$: documentKey = `${collectionId}:${documentId}`;
	$: requestKey = `${documentKey}:${navigationVersion}:${search}`;
	$: if (model)
		onTitle(
			content?.title ||
				markdown?.title ||
				content?.source_filename ||
				markdown?.source_filename ||
				$t('workbench.sourceContentUnavailableTitle')
		);
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
	onDestroy(() => {
		loadGeneration += 1;
	});

	async function loadSource() {
		const generation = ++loadGeneration;
		loading = true;
		loadError = '';
		model = null;
		content = null;
		markdown = null;
		selectedSourceSpanId = '';
		readerMode = requestedReaderMode ?? 'parsed-paper';

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
			loadError = $t('workbench.sourceContentUnavailableBody');
		}
		applyRequestedSource();
		appliedRequestKey = requestKey;
		loading = false;
	}

	function applyRequestedSource() {
		if (!model) return;
		if (requestedReaderMode) readerMode = requestedReaderMode;
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

	function sourceContext(selection: DocumentSourceSelection): ChatSourceContext | null {
		const userId = $authState.user?.user_id;
		if (!browser || !model || !userId) return null;
		const sourceRef = selection.source_ref.trim();
		const sourceQuote = selection.quote.trim();
		if (!sourceRef || !sourceQuote) return null;
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
			source_kind: ['table', 'figure'].includes(selection.source_kind)
				? selection.source_kind
				: 'text_window',
			source_ref: sourceRef,
			page: selection.page,
			quote: sourceQuote.slice(0, 6000),
			heading_path: selection.heading_path,
			quote_truncated: sourceQuote.length > 6000,
			source_digest: null
		};
		return context;
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

<div class="document-reader-root">
	<header class="reader-header">
		<a
			class="reader-back"
			href={backHref()}
			aria-label={$t('workbench.documents')}
			title={$t('workbench.documents')}><ArrowLeft size={17} /></a
		>
		<div class="reader-mode-tabs" role="tablist" aria-label={$t('workbench.readerModeLabel')}>
			<button
				type="button"
				role="tab"
				aria-selected={readerMode === 'parsed-paper'}
				class:active={readerMode === 'parsed-paper'}
				disabled={!hasMarkdown}
				on:click={showParsedPaper}>{$t('workbench.parsedPaperView')}</button
			>
			<button
				type="button"
				role="tab"
				aria-selected={readerMode === 'pdf-preview'}
				class:active={readerMode === 'pdf-preview'}
				disabled={!hasSource}
				on:click={showPdfPreview}>{$t('workbench.pdfPreview')}</button
			>
		</div>
		<IconButton
			label={$t('workbench.askResearchAgent')}
			tooltipAlign="end"
			onClick={() => agent.update((state) => ({ ...state, open: true }))}
			><MessageSquare size={17} /></IconButton
		>
	</header>
	{#if selectionError}<p class="selection-error" role="alert">{selectionError}</p>{/if}

	{#if loading && !model}
		<main class="reader-state" aria-busy="true">{$t('workbench.loading')}</main>
	{:else if model && hasSource}
		<main class="reader-main">
			<section class="reader-surface">
				{#if readerMode === 'parsed-paper' && hasMarkdown}
					<MarkdownPaperReader
						{markdown}
						sourceFileUrl={model.sourceFileUrl}
						activeSourceRef={requestedSourceRef}
						activeSourceQuote={requestedSourceQuote}
						activeSourceSpan={selectedSourceSpan}
						{sourceJumpToken}
						onAskSource={(selection) => toggleSource(selection, true)}
						onToggleSource={toggleSource}
						{selectedSourceKeys}
						selectionDisabled={$agent.busy}
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
						onAskSource={(selection) => toggleSource(selection, true)}
						onToggleSource={toggleSource}
						{selectedSourceKeys}
						selectionDisabled={$agent.busy}
						onSelectSourceSpan={selectSourceSpan}
					/>
				{/if}
			</section>
		</main>
	{:else}
		<main class="reader-state reader-state--error" role="alert">
			<h2>{$t('workbench.sourceContentUnavailableTitle')}</h2>
			<p>{loadError || $t('workbench.sourceContentUnavailableBody')}</p>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadSource}
				>{$t('researchAgent.workspace.retryPaper')}</button
			>
			<a href={backHref()}>{$t('workbench.documents')}</a>
		</main>
	{/if}
</div>

<style>
	.document-reader-root {
		position: relative;
		height: 100%;
		min-height: 0;
		container: document-reader / inline-size;
		display: grid;
		grid-template-rows: 44px minmax(0, 1fr);
		background: #f6f9fd;
		color: #0f172a;
	}
	.selection-error {
		position: absolute;
		top: 44px;
		inset-inline: 12px;
		z-index: 10;
		padding: 12px;
		border: 1px solid var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.reader-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
		padding: 0 8px;
		border-bottom: 1px solid #e2e8f0;
		background: rgba(255, 255, 255, 0.96);
	}
	.reader-back {
		display: grid;
		width: 32px;
		height: 32px;
		flex-shrink: 0;
		place-items: center;
		color: var(--text-secondary);
	}

	.reader-main {
		min-height: 0;
		display: grid;
		grid-template-rows: minmax(0, 1fr);
	}

	.reader-mode-tabs {
		display: inline-flex;
		min-width: 0;
		gap: 4px;
		background: #fff;
	}

	.reader-mode-tabs button {
		min-height: 32px;
		padding: 0 8px;
		border: 0;
		border-radius: 6px;
		background: transparent;
		color: #475569;
		font-size: 12px;
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
</style>
