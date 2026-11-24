<script lang="ts">
	import { t } from '../../../_shared/i18n';
	export let warnings: string[] = [];
</script>

{#if warnings.length}<div class="warnings">
		<strong>{$t('researchAgent.warnings')}</strong>
		<ul>
			{#each warnings as warning, index (index)}<li>{warning}</li>{/each}
		</ul>
	</div>{/if}

<style>
	.warnings {
		margin-top: 12px;
		padding: 10px 12px;
		border-left: 3px solid var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 12px;
	}

	.warnings ul {
		margin: 5px 0 0;
		padding-left: 18px;
	}
</style>
