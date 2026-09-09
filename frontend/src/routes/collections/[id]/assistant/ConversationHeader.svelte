<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';

	export let collectionId = '';
	export let objectiveId = '';
</script>

<header class="conversation-header">
	<div class="conversation-header-inner">
		<div class="conversation-heading">
			<h2>{$t('researchAgent.title')}</h2>
			<p>{$t('researchAgent.headerPrefix')} <strong>{collectionId}</strong></p>
		</div>
		{#if objectiveId}
			<a
				class="objective-link"
				href={resolve('/collections/[id]/objectives/[objective_id]', {
					id: collectionId,
					objective_id: objectiveId
				})}
			>
				{$t('researchAgent.objectiveScope')}
			</a>
		{/if}
	</div>
</header>

<style>
	.conversation-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		min-height: 76px;
		padding: 14px 32px;
		border-bottom: 1px solid var(--border-default);
		background: var(--surface-card);
	}

	.conversation-header-inner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		width: min(100%, 900px);
		margin: 0 auto;
	}

	.conversation-heading {
		min-width: 0;
	}

	.conversation-header h2 {
		margin: 0;
		font-size: 18px;
		line-height: 26px;
	}

	.conversation-header p {
		margin: 3px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.objective-link {
		color: var(--brand-primary);
		font-weight: 700;
		text-decoration: none;
		transition: color 140ms ease;
	}

	.objective-link:hover {
		text-decoration: underline;
	}

	@media (max-width: 820px) {
		.conversation-header {
			padding-left: 18px;
			padding-right: 18px;
		}
	}

	@media (max-width: 560px) {
		.conversation-header {
			align-items: flex-start;
			flex-direction: column;
			gap: 6px;
		}

		.conversation-header-inner {
			align-items: flex-start;
			flex-direction: column;
			gap: 8px;
		}
	}
</style>
