<script lang="ts">
	import type { DocumentSourceSelection } from '../../../../../_shared/documents';
	import { t } from '../../../../../_shared/i18n';
	export let selection: DocumentSourceSelection;
	export let selectedKeys: string[] = [];
	export let disabled = false;
	export let onToggle: (selection: DocumentSourceSelection) => void;
	export let onAsk: (selection: DocumentSourceSelection) => void;
	$: key = `${['table', 'figure'].includes(selection.source_kind) ? selection.source_kind : 'text_window'}:${selection.source_ref}`;
</script>

<span class="source-selection">
	<label title={$t('researchAgent.paperScope.selectBlock')}>
		<input
			type="checkbox"
			checked={selectedKeys.includes(key)}
			{disabled}
			on:change={() => onToggle(selection)}
			aria-label={$t('researchAgent.paperScope.selectBlock')}
		/>
	</label>
	<button
		type="button"
		{disabled}
		data-testid={`ask-research-agent-source-${selection.source_ref}`}
		on:click={() => onAsk(selection)}>{$t('workbench.askResearchAgent')}</button
	>
</span>

<style>
	.source-selection {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-inline-start: 8px;
		vertical-align: middle;
		font-size: 11px;
	}
	label {
		display: inline-flex;
		align-items: center;
		padding: 5px;
		cursor: pointer;
	}
	input {
		width: 15px;
		height: 15px;
		margin: 0;
		accent-color: var(--brand-primary);
	}
	button {
		padding: 3px 6px;
		border: 0;
		border-radius: 4px;
		font: inherit;
		color: var(--brand-primary);
		background: transparent;
		cursor: pointer;
	}
	button:hover {
		background: var(--brand-soft);
	}
	button:disabled,
	input:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	button:focus-visible,
	input:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
</style>
