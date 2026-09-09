<script lang="ts">
	import { setContext, tick } from 'svelte';
	import { writable } from 'svelte/store';
	import { beforeNavigate } from '$app/navigation';
	import { page } from '$app/stores';
	import { authState } from '../../../_shared/auth';
	import { collections } from '../../../_shared/collections';
	import { t } from '../../../_shared/i18n';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { X } from '@lucide/svelte';
	import ResearchConversation from '../assistant/ResearchConversation.svelte';
	import { DOCUMENT_AGENT, type DocumentAgentState } from './documentAgent';

	const agent = writable<DocumentAgentState>({
		open: false,
		papers: [],
		sourceVersion: 0,
		busy: false
	});
	setContext(DOCUMENT_AGENT, agent);
	let mountedAgent = false;
	let owner = '';
	let panel: HTMLElement;
	let returnFocus: HTMLElement | null = null;
	let wasOpen = false;
	$: collectionId = $page.params.id ?? '';
	$: collectionName =
		$collections.find((item) => item.id === collectionId)?.name || $t('collection.unknownName');
	$: currentOwner = `${$authState.user?.user_id ?? ''}:${collectionId}`;
	$: if (currentOwner !== owner) {
		owner = currentOwner;
		agent.set({ open: false, papers: [], sourceVersion: 0, busy: false });
		mountedAgent = false;
	}
	$: if ($agent.open) mountedAgent = true;
	$: if ($agent.open !== wasOpen && panel) {
		wasOpen = $agent.open;
		if (wasOpen) void focusComposer(panel);
	}
	function sourcesChanged() {
		agent.update((state) => ({ ...state, sourceVersion: state.sourceVersion + 1 }));
	}
	function busyChanged(busy: boolean) {
		agent.update((state) => (state.busy === busy ? state : { ...state, busy }));
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

	// Collection Agent links open alongside the paper without destroying its reader.
	beforeNavigate(({ to, cancel }) => {
		if (to?.url.pathname === `/collections/${collectionId}/assistant` && !to.url.search) {
			cancel();
			agent.update((state) => ({ ...state, open: true, sourceVersion: state.sourceVersion + 1 }));
		} else if (
			to?.url.pathname.startsWith(`/collections/${collectionId}/documents/`) &&
			window.matchMedia('(max-width: 820px)').matches
		) {
			agent.update((state) => ({ ...state, open: false }));
		}
	});
</script>

<div class="document-workspace" class:agent-open={$agent.open}>
	<div class="document-pane"><slot /></div>
	{#if mountedAgent}
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
	:global(.app-shell:has(.document-workspace.agent-open) .site-header),
	:global(.app-shell:has(.document-workspace.agent-open) .site-footer),
	:global(.collection-header:has(~ .collection-panel .document-workspace.agent-open)),
	:global(.collection-tabs:has(~ .collection-panel .document-workspace.agent-open)) {
		display: none;
	}
	.document-workspace {
		min-width: 0;
	}
	.document-pane {
		min-width: 0;
	}
	.document-workspace.agent-open {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(380px, 38%);
		height: 100dvh;
		background: var(--bg-page);
	}
	.agent-open .document-pane {
		overflow: auto;
		overscroll-behavior: contain;
		min-height: 0;
		padding: 24px;
	}
	.agent-open .document-pane:has(:global(.document-reader-root)) {
		padding: 0;
		overflow: hidden;
	}
	.agent-open :global(.document-reader-root) {
		position: relative;
		inset: auto;
		height: 100%;
		z-index: auto;
	}
	.agent-pane {
		display: grid;
		grid-template-rows: 52px minmax(0, 1fr);
		min-width: 0;
		min-height: 0;
		border-left: 1px solid var(--border-default);
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
		.document-workspace.agent-open {
			grid-template-columns: minmax(0, 1fr);
		}
		.agent-open .document-pane {
			display: none;
		}
		.agent-pane {
			border-left: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.agent-pane {
			animation: none;
		}
	}
</style>
