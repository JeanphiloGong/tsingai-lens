<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type { WorkbenchTab } from '../../../../../_shared/documents';

	export let activeTab: WorkbenchTab = 'summary';
	export let onChange: (tab: WorkbenchTab) => void = () => {};

	const tabs: { id: WorkbenchTab; labelKey: string }[] = [
		{ id: 'summary', labelKey: 'workbench.tabSummary' },
		{ id: 'methods', labelKey: 'workbench.tabMethods' },
		{ id: 'results', labelKey: 'workbench.tabResults' },
		{ id: 'evidence', labelKey: 'workbench.tabEvidence' },
		{ id: 'qa', labelKey: 'workbench.tabQa' }
	];
</script>

<div class="tabs-bar" role="tablist" aria-label={$t('workbench.extractionTabsLabel')}>
	{#each tabs as tab}
		<button
			type="button"
			role="tab"
			aria-selected={activeTab === tab.id}
			class:active={activeTab === tab.id}
			on:click={() => onChange(tab.id)}
		>
			{$t(tab.labelKey)}
		</button>
	{/each}
</div>

<style>
	.tabs-bar {
		display: flex;
		height: 56px;
		gap: 8px;
		padding: 10px 16px;
		overflow-x: auto;
		border-bottom: 1px solid #e2e8f0;
	}

	button {
		min-width: 0;
		flex: 1 1 0;
		height: 36px;
		padding: 0 10px;
		border: 0;
		border-radius: 999px;
		background: #f8fafc;
		color: #475569;
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}

	button.active {
		background: #2563eb;
		color: #ffffff;
		box-shadow: 0 6px 14px rgba(37, 99, 235, 0.22);
	}
</style>
