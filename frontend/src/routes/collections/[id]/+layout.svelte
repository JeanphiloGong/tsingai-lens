<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { errorMessage } from '../../_shared/api';
	import {
		collections,
		deleteCollection,
		fetchCollection,
		fetchCollections
	} from '../../_shared/collections';
	import { t } from '../../_shared/i18n';

	let deleteLoading = false;
	let deleteError = '';

	$: collectionId = $page.params.id ?? '';
	$: collection = $collections.find((item) => item.id === collectionId);
	$: collectionName = collection?.name;
	$: documentCount = collection?.documents.length ?? collection?.paper_count ?? 0;
	$: readyDocumentCount =
		collection?.documents.filter((document) => document.status === 'ready').length ?? 0;
	$: processingDocumentCount =
		collection?.documents.filter((document) => document.status === 'processing').length ?? 0;
	$: currentPath = $page.url.pathname;
	$: statusTone = processingDocumentCount ? 'processing' : readyDocumentCount ? 'ready' : 'pending';
	$: statusLabel = processingDocumentCount
		? $t('overview.currentModel.status.processing')
		: readyDocumentCount
			? $t('overview.currentModel.status.ready')
			: documentCount
				? $t('overview.currentModel.status.stored')
				: $t('overview.readinessLabels.empty');
	$: updatedAt = collection?.updated_at || '';

	onMount(() => {
		if (!$collections.length) {
			fetchCollections().catch(() => null);
		}
		if (collectionId) {
			fetchCollection(collectionId).catch(() => null);
		}
	});

	function tabClass(pathPrefix: string) {
		return currentPath.startsWith(pathPrefix) ? 'active' : '';
	}

	function formatDate(value?: string | null) {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString();
	}

	async function removeCurrentCollection() {
		const name = collectionName || $t('collection.unknownName');
		if (!window.confirm($t('collection.deleteConfirm', { name }))) {
			return;
		}

		deleteLoading = true;
		deleteError = '';

		try {
			await deleteCollection(collectionId);
			await goto(resolve('/'));
		} catch (err) {
			deleteError = errorMessage(err);
		} finally {
			deleteLoading = false;
		}
	}
</script>

<section class="collection-header">
	<div class="collection-header__main">
		<p class="collection-eyebrow">{$t('collection.eyebrow')}</p>
		<div class="collection-title-row">
			<h1>{collectionName || $t('collection.unknownName')}</h1>
		</div>
		<p class="collection-subtitle">
			{collection?.description || $t('collection.defaultSubtitle')}
		</p>
		<div class="collection-meta-row">
			<span>{$t('collection.metaDocuments', { count: documentCount })}</span>
			<span class={`status-badge status-badge--${statusTone}`}>{statusLabel}</span>
			<span>{$t('collection.metaUpdated', { time: formatDate(updatedAt) })}</span>
		</div>
	</div>
	<div class="collection-actions" aria-label={$t('collection.actionsLabel')}>
		<a class="btn btn--ghost" href={resolve('/')}>{$t('collection.backToCollections')}</a>
		<button
			class="btn btn--danger"
			type="button"
			disabled={deleteLoading}
			on:click={removeCurrentCollection}
		>
			{deleteLoading ? $t('collection.deleting') : $t('collection.delete')}
		</button>
	</div>
</section>

{#if deleteError}
	<div class="status status--error" role="alert">{deleteError}</div>
{/if}

<nav class="collection-tabs" aria-label={$t('collection.tabsLabel')}>
	<a
		href={resolve('/collections/[id]', { id: collectionId })}
		class:active={$page.url.pathname === `/collections/${collectionId}`}
	>
		{$t('collection.tabs.overview')}
	</a>
	<a
		href={resolve('/collections/[id]/objectives', { id: collectionId })}
		class={tabClass(`/collections/${collectionId}/objectives`)}
	>
		{$t('collection.tabs.objectives')}
	</a>
	<a
		href={resolve('/collections/[id]/comparisons', { id: collectionId })}
		class={tabClass(`/collections/${collectionId}/comparisons`)}
	>
		{$t('collection.tabs.comparisons')}
	</a>
	<a
		href={resolve('/collections/[id]/graph', { id: collectionId })}
		class={tabClass(`/collections/${collectionId}/graph`)}
	>
		{$t('collection.tabs.graph')}
	</a>
	<a
		href={resolve('/collections/[id]/documents', { id: collectionId })}
		class={tabClass(`/collections/${collectionId}/documents`)}
	>
		{$t('collection.tabs.papers')}
	</a>
	<a
		href={resolve('/collections/[id]/assistant', { id: collectionId })}
		class={tabClass(`/collections/${collectionId}/assistant`)}
	>
		{$t('collection.tabs.assistant')}
	</a>
</nav>

<div class="collection-panel">
	<slot />
</div>
