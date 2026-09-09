<script lang="ts">
	import { tick } from 'svelte';
	import { FileText, X } from '@lucide/svelte';
	import { t } from '../../../_shared/i18n';
	import type { DocumentTab } from './documentAgent';
	export let tabs: DocumentTab[];
	export let activeId: string;
	export let comparisonId = '';
	export let onSelect: (tab: DocumentTab) => void;
	export let onClose: (id: string) => void;
	let tablist: HTMLDivElement;
	$: if (activeId && tablist) {
		tabs;
		void revealActiveTab();
	}

	async function revealActiveTab() {
		await tick();
		tablist?.querySelector<HTMLElement>('.document-tab.active')?.scrollIntoView({
			block: 'nearest',
			inline: 'nearest'
		});
	}

	function keydown(event: KeyboardEvent, index: number) {
		if (event.key === 'Delete') {
			event.preventDefault();
			onClose(tabs[index].documentId);
			void tick().then(() => {
				const remaining = tablist?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
				remaining?.[Math.min(index, remaining.length - 1)]?.focus();
			});
			return;
		}
		const next =
			event.key === 'Home'
				? 0
				: event.key === 'End'
					? tabs.length - 1
					: event.key === 'ArrowRight'
						? (index + 1) % tabs.length
						: event.key === 'ArrowLeft'
							? (index + tabs.length - 1) % tabs.length
							: -1;
		if (next < 0) return;
		event.preventDefault();
		tablist.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
		onSelect(tabs[next]);
	}
</script>

<div
	class="document-tabs"
	role="tablist"
	aria-label={$t('researchAgent.workspace.openPapers')}
	bind:this={tablist}
>
	{#each tabs as tab, index (tab.documentId)}
		<div
			class="document-tab"
			class:active={tab.documentId === activeId}
			class:compared={tab.documentId === comparisonId}
			role="presentation"
		>
			<button
				class="tab-title"
				id={`document-tab-${encodeURIComponent(tab.documentId)}`}
				role="tab"
				type="button"
				aria-selected={tab.documentId === activeId}
				aria-controls={`document-panel-${encodeURIComponent(tab.documentId)}`}
				tabindex={tab.documentId === activeId || (!activeId && index === 0) ? 0 : -1}
				title={tab.title}
				on:click={() => onSelect(tab)}
				on:keydown={(event) => keydown(event, index)}
				><FileText size={15} aria-hidden="true" /><span>{tab.title}</span></button
			>
			<button
				class="close-tab"
				type="button"
				tabindex="-1"
				aria-label={$t('researchAgent.workspace.closePaper', { title: tab.title })}
				title={$t('researchAgent.workspace.closePaper', { title: tab.title })}
				on:click={() => onClose(tab.documentId)}><X size={14} /></button
			>
		</div>
	{/each}
</div>

<style>
	.document-tabs {
		display: flex;
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: thin;
		align-self: stretch;
	}
	.document-tab {
		display: flex;
		flex: 0 0 auto;
		max-width: 220px;
		min-width: 112px;
		align-items: center;
		border-inline-end: 1px solid var(--border-default);
		border-bottom: 2px solid transparent;
	}
	.document-tab.active {
		background: var(--surface-card);
		border-bottom-color: var(--brand-primary);
	}
	.document-tab.compared:not(.active) {
		border-bottom-color: var(--text-tertiary);
	}
	.tab-title {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		flex: 1;
		height: 42px;
		border: 0;
		padding: 0 10px;
		background: transparent;
		color: var(--text-secondary);
		font-size: 12px;
		text-align: left;
		cursor: pointer;
	}
	.tab-title :global(svg) {
		flex-shrink: 0;
	}
	.tab-title span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.active .tab-title {
		color: var(--text-primary);
	}
	.close-tab {
		display: grid;
		place-items: center;
		flex: 0 0 28px;
		width: 28px;
		height: 28px;
		margin-inline-end: 4px;
		border: 0;
		border-radius: 4px;
		background: transparent;
		color: var(--text-tertiary);
		cursor: pointer;
	}
	.close-tab:hover {
		color: var(--text-primary);
		background: var(--bg-subtle);
	}
	button:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: -2px;
	}
	@media (max-width: 640px) {
		.document-tab {
			max-width: 170px;
		}
	}
</style>
