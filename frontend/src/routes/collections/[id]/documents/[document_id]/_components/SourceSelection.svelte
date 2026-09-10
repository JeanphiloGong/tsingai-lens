<script lang="ts">
	import type { DocumentSourceSelection } from '../../../../../_shared/documents';
	import { t } from '../../../../../_shared/i18n';
	import { MessageSquare } from '@lucide/svelte';
	export let selection: DocumentSourceSelection;
	export let selectedKeys: string[] = [];
	export let disabled = false;
	export let onToggle: (selection: DocumentSourceSelection) => void;
	export let onAsk: (selection: DocumentSourceSelection) => void;
	$: key = `${['table', 'figure'].includes(selection.source_kind) ? selection.source_kind : 'text_window'}:${selection.source_ref}`;
</script>

<span class="source-selection" data-selected={selectedKeys.includes(key)}>
	<button
		class="keyboard-selection"
		type="button"
		{disabled}
		aria-pressed={selectedKeys.includes(key)}
		aria-label={$t('researchAgent.paperScope.selectBlock')}
		on:click={() => onToggle(selection)}
	></button>
	<button
		class="ask-source"
		type="button"
		{disabled}
		aria-label={$t('workbench.askResearchAgent')}
		title={$t('workbench.askResearchAgent')}
		data-testid={`ask-research-agent-source-${selection.source_ref}`}
		on:click={() => onAsk(selection)}><MessageSquare size={15} /></button
	>
</span>

<style>
	.source-selection {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin-inline-start: 8px;
		vertical-align: middle;
		font-size: 11px;
	}
	.keyboard-selection {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		overflow: hidden;
		clip-path: inset(50%);
	}
	.ask-source {
		display: inline-grid;
		place-items: center;
		width: 26px;
		height: 26px;
		padding: 0;
		border: 0;
		border-radius: 4px;
		font: inherit;
		color: var(--brand-primary);
		background: transparent;
		cursor: pointer;
	}
	.ask-source:hover {
		background: var(--brand-soft);
	}
	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.ask-source:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	:global(.source-selectable) {
		cursor: pointer;
		border-radius: 4px;
		transition:
			background-color 120ms ease,
			box-shadow 120ms ease;
	}
	:global(.source-selectable:not(.source-selection-disabled):hover) {
		background: var(--bg-subtle);
	}
	:global(.source-selectable:has(.source-selection[data-selected='true'])) {
		background: color-mix(in srgb, var(--brand-soft) 65%, transparent);
		box-shadow: -2px 0 0 var(--brand-primary);
	}
	:global(.source-selectable:has(.keyboard-selection:focus-visible)) {
		outline: 2px solid var(--brand-primary);
		outline-offset: 4px;
	}
	@media (hover: hover) {
		.ask-source {
			opacity: 0;
		}
		:global(.source-selectable:hover) .ask-source,
		:global(.source-selectable:focus-within) .ask-source {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		:global(.source-selectable) {
			transition: none;
		}
	}
</style>
