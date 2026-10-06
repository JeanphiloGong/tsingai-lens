<script lang="ts">
	import { page } from '$app/stores';
	import { t } from '../../../_shared/i18n';
	import OperationPermissions from '../assistant/OperationPermissions.svelte';

	$: collectionId = $page.params.id ?? '';
</script>

<svelte:head><title>{$t('agentPermission.defaultTitle')}</title></svelte:head>

<section class="settings-page" aria-labelledby="agent-permission-title">
	<div class="settings-heading">
		<p class="eyebrow">{$t('collection.tabs.settings')}</p>
		<h2 id="agent-permission-title">{$t('agentPermission.defaultTitle')}</h2>
		<p>{$t('agentPermission.defaultScope')}</p>
	</div>
	{#key collectionId}
		<OperationPermissions {collectionId} scope="collection" standalone={true} />
	{/key}
</section>

<style>
	.settings-page {
		max-width: 760px;
		margin: 0 auto;
		padding: 28px 24px 48px;
	}
	.settings-heading {
		margin-bottom: 20px;
	}
	.eyebrow {
		margin: 0 0 6px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	h2 {
		margin: 0;
		color: var(--text-primary);
		font-size: 24px;
	}
	.settings-heading p:last-child {
		max-width: 680px;
		margin: 10px 0 0;
		color: var(--text-secondary);
		line-height: 1.55;
	}
</style>
