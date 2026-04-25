<script lang="ts">
	import { goto } from '$app/navigation';
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
	import {
		fetchWorkspaceOverview,
		getOverviewReadinessState,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../_shared/workspace';

	let deleteLoading = false;
	let deleteError = '';
	let workspace: WorkspaceOverview | null = null;
	let loadedWorkspaceId = '';

	$: collectionId = $page.params.id ?? '';
	$: collection = workspace?.collection ?? $collections.find((item) => item.id === collectionId);
	$: collectionName = collection?.name;
	$: documentCount =
		workspace?.document_summary.total_documents ??
		collection?.paper_count ??
		workspace?.file_count ??
		0;
	$: readinessState = workspace ? getOverviewReadinessState(workspace) : null;
	$: statusLabel = readinessState
		? $t(`overview.readinessLabels.${readinessState}`)
		: formatStatus(collection?.status);
	$: statusTone = readinessState ?? 'pending';
	$: updatedAt = collection?.updated_at || workspace?.artifacts.updated_at || '';
	$: resultsVisible =
		!workspace || getWorkspaceSurfaceState(workspace, 'results') !== 'not_applicable';
	$: protocolVisible =
		!workspace || getWorkspaceSurfaceState(workspace, 'protocol') !== 'not_applicable';
	$: evidenceHref = workspace?.links.evidence ?? `/collections/${collectionId}/evidence`;
	$: moreActive =
		$page.url.pathname.startsWith(`/collections/${collectionId}/evidence`) ||
		$page.url.pathname.startsWith(`/collections/${collectionId}/results`) ||
		$page.url.pathname.startsWith(`/collections/${collectionId}/protocol`);

	$: if (collectionId && collectionId !== loadedWorkspaceId) {
		loadedWorkspaceId = collectionId;
		void loadWorkspace();
	}

	onMount(() => {
		if (!$collections.length) {
			fetchCollections().catch(() => null);
		}
		if (collectionId) {
			fetchCollection(collectionId).catch(() => null);
		}
	});

	async function loadWorkspace() {
		try {
			workspace = await fetchWorkspaceOverview(collectionId);
		} catch {
			workspace = null;
		}
	}

	function formatStatus(status?: string | null) {
		if (!status) return $t('overview.statusUnknown');
		const key = `overview.status.${status}`;
		const translated = $t(key);
		return translated === key ? status : translated;
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
			await goto('/');
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
			<button
				class="icon-button icon-button--subtle"
				type="button"
				aria-label={$t('collection.editName')}
			>
				<span class="edit-icon" aria-hidden="true"></span>
			</button>
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
		<a class="btn btn--ghost" href="/">{$t('collection.backToCollections')}</a>
		<button
			class="btn btn--danger"
			type="button"
			disabled={deleteLoading}
			on:click={removeCurrentCollection}
		>
			{deleteLoading ? $t('collection.deleting') : $t('collection.delete')}
		</button>
		<button
			class="icon-button icon-button--subtle"
			type="button"
			aria-label={$t('collection.moreActions')}
		>
			<span aria-hidden="true">...</span>
		</button>
	</div>
</section>

{#if deleteError}
	<div class="status status--error" role="alert">{deleteError}</div>
{/if}

<nav class="collection-tabs" aria-label={$t('collection.tabsLabel')}>
	<a
		href={`/collections/${collectionId}`}
		class:active={$page.url.pathname === `/collections/${collectionId}`}
	>
		{$t('collection.tabs.overview')}
	</a>
	<a
		href={`/collections/${collectionId}/documents`}
		class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/documents`)}
	>
		{$t('collection.tabs.documents')}
	</a>
	<a
		href={`/collections/${collectionId}/comparisons`}
		class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/comparisons`)}
	>
		{$t('collection.tabs.comparisons')}
	</a>
	<a
		href={`/collections/${collectionId}/graph`}
		class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/graph`)}
	>
		{$t('collection.tabs.graph')}
	</a>
	<details class="collection-tabs__more" class:active={moreActive}>
		<summary>{$t('collection.moreLabel')}</summary>
		<div class="collection-tabs__menu">
			<a
				href={evidenceHref}
				class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/evidence`)}
			>
				{$t('collection.tabs.evidence')}
			</a>
			{#if resultsVisible}
				<a
					href={`/collections/${collectionId}/results`}
					class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/results`)}
				>
					{$t('collection.tabs.results')}
				</a>
			{/if}
			{#if protocolVisible}
				<a
					href={`/collections/${collectionId}/protocol`}
					class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/protocol`)}
				>
					{$t('collection.tabs.protocol')}
				</a>
			{/if}
		</div>
	</details>
</nav>

<div class="collection-panel">
	<slot />
</div>
