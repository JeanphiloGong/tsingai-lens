<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { GitBranch } from '@lucide/svelte';

	export let collectionId = '';
	export let objectiveId = '';
	export let title = '';
	export let disabled = false;
	export let onOpenTree: () => void = () => {};
</script>

<header class="conversation-header">
	<div class="conversation-header-inner">
		{#if title}<h2 {title}>{title}</h2>{/if}
		<IconButton label={$t('researchAgent.tree.title')} {disabled} onClick={onOpenTree}>
			<GitBranch size={17} />
		</IconButton>
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
		flex: 0 0 auto;
		align-items: center;
		min-height: 44px;
		padding: 8px 32px;
		box-sizing: border-box;
	}

	.conversation-header-inner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: min(100%, 900px);
		margin: 0 auto;
	}

	.conversation-header h2 {
		flex: 1;
		min-width: 0;
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-secondary);
		font-size: 14px;
		font-weight: 500;
		line-height: 20px;
	}

	.objective-link {
		margin-left: auto;
		max-width: 100%;
		overflow-wrap: anywhere;
		color: var(--brand-primary);
		font-size: 12px;
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
</style>
