<script lang="ts">
	import { setContext, tick } from 'svelte';
	import { writable } from 'svelte/store';
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { authState } from '../../../_shared/auth';
	import { collections } from '../../../_shared/collections';
	import { t } from '../../../_shared/i18n';
	import {
		readPendingChatSourceContexts,
		storePendingChatSourceContexts,
		type ChatSourceContext
	} from '../../../_shared/chatSessions';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { X, Library, Columns2, PanelLeft, MessageSquare, ListChecks } from '@lucide/svelte';
	import ResearchConversation from '../assistant/ResearchConversation.svelte';
	import DocumentReader from './[document_id]/DocumentReader.svelte';
	import DocumentTabs from './DocumentTabs.svelte';
	import { DOCUMENT_AGENT, type DocumentAgentState, type DocumentTab } from './documentAgent';

	const agent = writable<DocumentAgentState>({
		open: false,
		papers: [],
		sourceVersion: 0,
		busy: false
	});
	setContext(DOCUMENT_AGENT, agent);
	let mountedAgent = false;
	let owner = '';
	let tabs: DocumentTab[] = [];
	let primaryId = '';
	let secondaryId = '';
	let comparing = false;
	let handledRoute = '';
	let showSelection = false;
	let selectedSources: ChatSourceContext[] = [];
	let panel: HTMLElement;
	let workspace: HTMLDivElement;
	let readers: HTMLDivElement;
	let returnFocus: HTMLElement | null = null;
	let wasOpen = false;
	let viewportWidth = 0;
	let paperRatio = 50;
	let readerWidth = 0;
	let agentWidth = 420;
	let resizing: 'papers' | 'agent' | null = null;
	$: collectionId = $page.params.id ?? '';
	$: documentId = $page.params.document_id ?? '';
	$: collectionName =
		$collections.find((item) => item.id === collectionId)?.name || $t('collection.unknownName');
	$: userId = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: currentOwner = `${userId}:${collectionId}`;
	$: if (currentOwner !== owner) {
		owner = currentOwner;
		agent.set({ open: false, papers: [], sourceVersion: 0, busy: false });
		mountedAgent = false;
		tabs = [];
		primaryId = '';
		secondaryId = '';
		comparing = false;
		handledRoute = '';
		showSelection = false;
	}
	$: routeKey = JSON.stringify([currentOwner, documentId, $page.url.search]);
	$: if (userId && documentId && routeKey !== handledRoute) {
		handledRoute = routeKey;
		openDocument(documentId, $page.url.search);
	}
	$: dual = comparing && Boolean(secondaryId) && viewportWidth >= 1100 && Boolean(documentId);
	$: expanded = tabs.length > 0 || $agent.open;
	$: activeTitle = tabs.find((tab) => tab.documentId === documentId)?.title;
	$: conversationWidth = Math.min(agentWidth, Math.max(320, viewportWidth * 0.46));
	$: minimumPaperRatio = Math.min(
		50,
		Math.max(30, Math.ceil((300 / Math.max(1, readerWidth - 6)) * 100))
	);
	$: paperRatio = Math.max(minimumPaperRatio, Math.min(100 - minimumPaperRatio, paperRatio));
	$: {
		$agent.sourceVersion;
		selectedSources = readPendingChatSourceContexts(userId, collectionId);
	}
	$: if ($agent.open) mountedAgent = true;
	$: if ($agent.open !== wasOpen && panel) {
		wasOpen = $agent.open;
		if (wasOpen) void focusComposer(panel);
	}

	function documentHref(tab: DocumentTab) {
		return `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(tab.documentId)}${tab.search}`;
	}
	function openDocument(id: string, search: string, repeat = false) {
		const existing = tabs.find((tab) => tab.documentId === id);
		if (!existing) {
			tabs = [
				...tabs,
				{
					documentId: id,
					title:
						$agent.papers.find((paper) => paper.document_id === id)?.title ||
						$t('workbench.loading'),
					search,
					navigationVersion: 0
				}
			];
		} else if (existing.search !== search || repeat) {
			tabs = tabs.map((tab) =>
				tab.documentId === id
					? { ...tab, search, navigationVersion: tab.navigationVersion + 1 }
					: tab
			);
		}
		if (id !== primaryId && id !== secondaryId) primaryId = id;
		if (!primaryId) primaryId = id;
	}
	function updateTitle(id: string, title: string) {
		if (tabs.find((tab) => tab.documentId === id)?.title === title) return;
		tabs = tabs.map((tab) => (tab.documentId === id ? { ...tab, title } : tab));
	}
	function selectTab(tab: DocumentTab) {
		void goto(documentHref(tab), { noScroll: true, keepFocus: true });
	}
	function closeTab(id: string) {
		const index = tabs.findIndex((tab) => tab.documentId === id);
		tabs = tabs.filter((tab) => tab.documentId !== id);
		if (secondaryId === id) {
			secondaryId = '';
			comparing = false;
		}
		if (primaryId === id) {
			primaryId = secondaryId || tabs[Math.min(index, tabs.length - 1)]?.documentId || '';
			secondaryId = '';
			comparing = false;
		}
		if (documentId === id) {
			const next = tabs.find((tab) => tab.documentId === primaryId) || tabs[0];
			if (next) selectTab(next);
			else void goto(`/collections/${collectionId}/documents`, { noScroll: true });
		}
	}
	function toggleComparison() {
		if (comparing) {
			comparing = false;
			return;
		}
		primaryId = documentId || tabs[0]?.documentId || '';
		secondaryId = tabs.find((tab) => tab.documentId !== primaryId)?.documentId || '';
		comparing = Boolean(secondaryId);
		paperRatio = 50;
	}
	function sourcesChanged() {
		agent.update((state) => ({ ...state, sourceVersion: state.sourceVersion + 1 }));
	}
	function busyChanged(busy: boolean) {
		agent.update((state) => (state.busy === busy ? state : { ...state, busy }));
	}
	function removeSource(index: number) {
		if ($agent.busy) return;
		storePendingChatSourceContexts(
			userId,
			collectionId,
			selectedSources.filter((_, candidate) => candidate !== index)
		);
		sourcesChanged();
	}
	async function focusComposer(node: HTMLElement) {
		returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		await tick();
		node.querySelector<HTMLTextAreaElement>('textarea')?.focus({ preventScroll: true });
	}
	function closeAgent() {
		agent.update((state) => ({ ...state, open: false }));
		returnFocus?.focus({ preventScroll: true });
	}
	function beginResize(event: PointerEvent, kind: 'papers' | 'agent') {
		if (event.button !== 0) return;
		event.preventDefault();
		resizing = kind;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
	}
	function resize(event: PointerEvent) {
		if (resizing === 'papers') {
			const rect = readers.getBoundingClientRect();
			paperRatio = Math.max(
				minimumPaperRatio,
				Math.min(100 - minimumPaperRatio, ((event.clientX - rect.left) / rect.width) * 100)
			);
		} else if (resizing === 'agent') {
			agentWidth = Math.max(
				320,
				Math.min(viewportWidth * 0.46, workspace.getBoundingClientRect().right - event.clientX)
			);
		}
	}
	function resizeKey(event: KeyboardEvent, kind: 'papers' | 'agent') {
		if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
		event.preventDefault();
		const direction = event.key === 'ArrowLeft' ? -1 : 1;
		if (kind === 'papers')
			paperRatio =
				event.key === 'Home'
					? minimumPaperRatio
					: event.key === 'End'
						? 100 - minimumPaperRatio
						: Math.max(
								minimumPaperRatio,
								Math.min(100 - minimumPaperRatio, paperRatio + direction * 5)
							);
		else
			agentWidth =
				event.key === 'Home'
					? 320
					: event.key === 'End'
						? viewportWidth * 0.46
						: Math.max(320, Math.min(viewportWidth * 0.46, agentWidth - direction * 24));
	}

	beforeNavigate(({ to, cancel }) => {
		if (to?.url.pathname === `/collections/${collectionId}/assistant` && !to.url.search) {
			cancel();
			agent.update((state) => ({ ...state, open: true, sourceVersion: state.sourceVersion + 1 }));
		} else if (to?.url.pathname.startsWith(`/collections/${collectionId}/documents/`)) {
			if (to.url.href === $page.url.href && documentId)
				openDocument(documentId, to.url.search, true);
			if (viewportWidth <= 820) agent.update((state) => ({ ...state, open: false }));
			showSelection = false;
		}
	});
</script>

<svelte:window bind:innerWidth={viewportWidth} />
<svelte:head><title>{activeTitle || $t('collection.tabs.papers')}</title></svelte:head>

<div
	class="document-workspace"
	class:expanded
	class:agent-open={$agent.open}
	class:resizing={Boolean(resizing)}
	style:--agent-width={`${conversationWidth}px`}
	bind:this={workspace}
>
	<div class="document-pane">
		{#if tabs.length}
			<div class="workspace-toolbar">
				<a
					class="library-link"
					href={`/collections/${collectionId}/documents`}
					aria-label={$t('collection.tabs.papers')}
					title={$t('collection.tabs.papers')}><Library size={18} /></a
				>
				<DocumentTabs
					{tabs}
					activeId={documentId}
					comparisonId={dual ? secondaryId : ''}
					onSelect={selectTab}
					onClose={closeTab}
				/>
				<div class="workspace-actions">
					{#if dual}
						<select
							class="comparison-picker"
							aria-label={$t('researchAgent.workspace.comparisonPaper')}
							title={$t('researchAgent.workspace.comparisonPaper')}
							value={secondaryId}
							on:change={(event) => {
								secondaryId = event.currentTarget.value;
								const next = tabs.find((item) => item.documentId === secondaryId);
								if (next) selectTab(next);
							}}
						>
							{#each tabs.filter((item) => item.documentId !== primaryId) as option}
								<option value={option.documentId}>{option.title}</option>
							{/each}
						</select>
					{/if}
					{#if documentId && viewportWidth >= 1100}
						<IconButton
							label={$t(
								comparing ? 'researchAgent.workspace.single' : 'researchAgent.workspace.compare'
							)}
							pressed={comparing}
							disabled={tabs.length < 2}
							onClick={toggleComparison}
						>
							{#if comparing}<PanelLeft size={17} />{:else}<Columns2 size={17} />{/if}
						</IconButton>
					{/if}
					<IconButton
						label={$t('researchAgent.workspace.reviewSelection')}
						pressed={showSelection}
						onClick={() => (showSelection = !showSelection)}><ListChecks size={17} /></IconButton
					>
					<IconButton
						label={$t('workbench.askResearchAgent')}
						pressed={$agent.open}
						onClick={() => agent.update((state) => ({ ...state, open: !state.open }))}
						><MessageSquare size={17} /></IconButton
					>
				</div>
			</div>
		{/if}
		{#if showSelection}
			<section class="selection-tray" aria-label={$t('researchAgent.workspace.reviewSelection')}>
				<header>
					<strong
						>{$t('researchAgent.workspace.selectedBlocks', {
							count: selectedSources.length
						})}</strong
					><IconButton
						label={$t('researchAgent.workspace.reviewSelection')}
						pressed={true}
						onClick={() => (showSelection = false)}><X size={16} /></IconButton
					>
				</header>
				<ul>
					{#each selectedSources as source, index (`${source.document_id}:${source.source_kind}:${source.source_ref}`)}
						<li>
							<a
								href={source.resource_ref.href ||
									`/collections/${collectionId}/documents/${source.document_id}?source_ref=${encodeURIComponent(source.source_ref)}`}
								><strong>{source.document_title}</strong><span
									>{source.heading_path || source.source_ref}</span
								>
								<p>{source.quote}</p></a
							><IconButton
								label={$t('researchAgent.workspace.removeBlock', { title: source.document_title })}
								disabled={$agent.busy}
								onClick={() => removeSource(index)}><X size={14} /></IconButton
							>
						</li>
					{/each}
				</ul>
			</section>
		{/if}
		<div class="paper-list" hidden={Boolean(documentId)}><slot /></div>
		<div
			class="readers"
			class:dual
			hidden={!documentId}
			bind:this={readers}
			bind:clientWidth={readerWidth}
			style:--paper-ratio={`${paperRatio}fr`}
			style:--other-ratio={`${100 - paperRatio}fr`}
		>
			{#each tabs as tab (tab.documentId)}
				<div
					class="reader-pane"
					class:secondary={tab.documentId === secondaryId && dual}
					hidden={!documentId ||
						(dual
							? tab.documentId !== primaryId && tab.documentId !== secondaryId
							: tab.documentId !== documentId)}
					role="tabpanel"
					id={`document-panel-${encodeURIComponent(tab.documentId)}`}
					aria-labelledby={`document-tab-${encodeURIComponent(tab.documentId)}`}
					data-document-id={tab.documentId}
				>
					<DocumentReader
						{collectionId}
						documentId={tab.documentId}
						search={tab.search}
						navigationVersion={tab.navigationVersion}
						onTitle={(title) => updateTitle(tab.documentId, title)}
					/>
				</div>
			{/each}
			{#if dual}
				<!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions (WAI-ARIA window splitters are focusable separators with keyboard resizing.) -->
				<div
					class="splitter paper-splitter"
					role="separator"
					tabindex="0"
					aria-orientation="vertical"
					aria-label={$t('researchAgent.workspace.resizePapers')}
					aria-valuemin={minimumPaperRatio}
					aria-valuemax={100 - minimumPaperRatio}
					aria-valuenow={Math.round(paperRatio)}
					on:pointerdown={(event) => beginResize(event, 'papers')}
					on:pointermove={resize}
					on:pointerup={() => (resizing = null)}
					on:lostpointercapture={() => (resizing = null)}
					on:keydown={(event) => resizeKey(event, 'papers')}
				></div>
			{/if}
		</div>
	</div>
	{#if mountedAgent}
		{#if $agent.open}
			<!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions (WAI-ARIA window splitters are focusable separators with keyboard resizing.) -->
			<div
				class="splitter agent-splitter"
				role="separator"
				tabindex="0"
				aria-orientation="vertical"
				aria-label={$t('researchAgent.workspace.resizeAgent')}
				aria-valuemin="320"
				aria-valuemax={Math.round(viewportWidth * 0.46)}
				aria-valuenow={Math.round(conversationWidth)}
				on:pointerdown={(event) => beginResize(event, 'agent')}
				on:pointermove={resize}
				on:pointerup={() => (resizing = null)}
				on:lostpointercapture={() => (resizing = null)}
				on:keydown={(event) => resizeKey(event, 'agent')}
			></div>
		{/if}
		<aside
			class="agent-pane"
			class:closed={!$agent.open}
			aria-label={$t('researchAgent.title')}
			bind:this={panel}
		>
			<header class="agent-pane-header">
				<div>
					<strong>{$t('researchAgent.title')}</strong><span title={collectionName}
						>{collectionName}</span
					>
				</div>
				<IconButton
					label={$t('researchAgent.paperScope.close')}
					tooltipAlign="end"
					onClick={closeAgent}><X size={18} /></IconButton
				>
			</header>
			<ResearchConversation
				embedded
				selectedPapers={$agent.papers}
				sourceContextVersion={$agent.sourceVersion}
				onSourcesChanged={sourcesChanged}
				onBusyChange={busyChanged}
				onRemovePaper={(id) =>
					agent.update((state) => ({
						...state,
						papers: state.papers.filter((paper) => paper.document_id !== id)
					}))}
			/>
		</aside>
	{/if}
</div>

<style>
	:global(.app-shell:has(.document-workspace.expanded) .site-header),
	:global(.app-shell:has(.document-workspace.expanded) .site-footer),
	:global(.collection-header:has(~ .collection-panel .document-workspace.expanded)),
	:global(.collection-tabs:has(~ .collection-panel .document-workspace.expanded)) {
		display: none;
	}
	.document-workspace,
	.document-pane {
		min-width: 0;
	}
	.document-workspace.expanded {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		height: 100dvh;
		background: var(--bg-page);
	}
	.expanded.agent-open {
		grid-template-columns: minmax(0, 1fr) 6px var(--agent-width);
	}
	.expanded .document-pane {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		position: relative;
	}
	.workspace-toolbar {
		display: flex;
		flex-shrink: 0;
		height: 44px;
		gap: 4px;
		align-items: center;
		border-bottom: 1px solid var(--border-default);
		background: var(--bg-subtle);
	}
	.workspace-toolbar :global(.document-tabs) {
		flex: 1;
	}
	.library-link {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		flex-shrink: 0;
		color: var(--text-secondary);
	}
	.workspace-actions {
		display: flex;
		align-items: center;
		flex-shrink: 0;
		gap: 0;
		padding-inline: 2px;
	}
	.workspace-actions :global(.icon-tooltip) {
		top: calc(100% + 8px);
		bottom: auto;
		z-index: 20;
	}
	.paper-list {
		min-height: 0;
		overflow: auto;
	}
	.expanded .paper-list {
		padding: 24px;
		flex: 1;
	}
	.readers {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr);
	}
	.readers.dual {
		grid-template-columns: minmax(0, var(--paper-ratio)) 6px minmax(0, var(--other-ratio));
	}
	.reader-pane {
		grid-area: 1 / 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}
	.reader-pane :global(.document-reader-root) {
		flex: 1;
		min-height: 0;
	}
	.reader-pane.secondary {
		grid-column: 3;
	}
	[hidden] {
		display: none !important;
	}
	.comparison-picker {
		width: 150px;
		height: 30px;
		padding: 0 4px;
		color: var(--text-primary);
		background: transparent;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		font-size: 12px;
	}
	.splitter {
		position: relative;
		background: var(--border-default);
		cursor: col-resize;
		touch-action: none;
		z-index: 2;
	}
	.splitter::after {
		content: '';
		position: absolute;
		inset: 0 -3px;
	}
	.splitter:hover,
	.splitter:focus-visible {
		background: var(--brand-primary);
		outline: none;
	}
	.paper-splitter {
		grid-area: 1 / 2;
	}
	.agent-splitter {
		grid-column: 2;
	}
	.resizing {
		user-select: none;
		cursor: col-resize;
	}
	.selection-tray {
		position: absolute;
		top: 44px;
		inset-inline: 12px;
		z-index: 20;
		max-height: min(420px, 65%);
		overflow: auto;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		box-shadow: var(--shadow-sm);
	}
	.selection-tray header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 12px;
		border-bottom: 1px solid var(--border-default);
		font-size: 12px;
	}
	.selection-tray ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.selection-tray li {
		display: flex;
		align-items: start;
		gap: 8px;
		padding: 10px 12px;
		border-bottom: 1px solid var(--border-default);
	}
	.selection-tray a {
		flex: 1;
		min-width: 0;
		color: var(--text-primary);
		text-decoration: none;
		font-size: 12px;
	}
	.selection-tray a > span {
		display: block;
		margin-top: 4px;
		color: var(--text-secondary);
	}
	.selection-tray p {
		margin: 6px 0 0;
		max-height: 60px;
		overflow: auto;
		line-height: 20px;
		overflow-wrap: anywhere;
	}
	.agent-pane {
		display: grid;
		grid-template-rows: 52px minmax(0, 1fr);
		min-width: 0;
		min-height: 0;
		background: var(--bg-page);
		animation: pane-enter 180ms ease-out;
	}
	.agent-pane.closed {
		display: none;
	}
	.agent-pane-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 0 12px 0 16px;
		border-bottom: 1px solid var(--border-default);
	}
	.agent-pane-header > div {
		display: flex;
		align-items: baseline;
		gap: 12px;
		min-width: 0;
	}
	.agent-pane-header strong {
		font-size: 13px;
		white-space: nowrap;
	}
	.agent-pane-header span {
		min-width: 0;
		font-size: 12px;
		color: var(--text-tertiary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	@keyframes pane-enter {
		from {
			opacity: 0;
			transform: translateX(12px);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}
	@media (max-width: 820px) {
		.expanded.agent-open {
			grid-template-columns: minmax(0, 1fr);
		}
		.agent-open .document-pane,
		.agent-splitter {
			display: none;
		}
		.expanded .paper-list {
			padding: 16px;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.agent-pane {
			animation: none;
		}
	}
</style>
