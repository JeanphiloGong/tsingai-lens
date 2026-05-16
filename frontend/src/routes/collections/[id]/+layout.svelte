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
	import {
		fetchWorkspaceOverview,
		getOverviewReadinessState,
		type WorkspaceOverview
	} from '../../_shared/workspace';

	let deleteLoading = false;
	let deleteError = '';
	let workspace: WorkspaceOverview | null = null;
	let loadedWorkspaceId = '';

	$: collectionId = $page.params.id ?? '';
	$: storeCollection = $collections.find((item) => item.id === collectionId);
	$: collection = workspace?.collection
		? {
				...workspace.collection,
				status: storeCollection?.status ?? workspace.collection.status
			}
		: storeCollection;
	$: collectionName = collection?.name;
	$: effectiveDocumentCount = Math.max(
		workspace?.document_summary.total_documents ?? 0,
		workspace?.file_count ?? 0,
		collection?.paper_count ?? 0,
		storeCollection?.paper_count ?? 0
	);
	$: stateWorkspace = workspace ? { ...workspace, file_count: effectiveDocumentCount } : null;
	$: documentCount = effectiveDocumentCount;
	$: storeReadinessState = readinessFromCollectionStatus(storeCollection?.status);
	$: readinessState = storeReadinessState
		? storeReadinessState
		: stateWorkspace
			? getOverviewReadinessState(stateWorkspace)
			: null;
	$: statusLabel = readinessState
		? $t(`overview.readinessLabels.${readinessState}`)
		: formatStatus(collection?.status);
	$: statusTone = readinessState ?? 'pending';
	$: updatedAt = collection?.updated_at || workspace?.artifacts.updated_at || '';
	$: evidenceHref = workspace?.links.evidence ?? `/collections/${collectionId}/evidence`;
	$: moreActive =
		$page.url.pathname.startsWith(`/collections/${collectionId}/materials`) ||
		$page.url.pathname.startsWith(`/collections/${collectionId}/comparisons`) ||
		$page.url.pathname.startsWith(`/collections/${collectionId}/evidence`) ||
		$page.url.pathname.startsWith(`/collections/${collectionId}/results`);
	$: downstreamUnlocked = readinessState === 'ready';
	$: currentPath = $page.url.pathname;
	$: isOverviewRoute = currentPath === `/collections/${collectionId}`;
	$: lockReason = buildLockReason(readinessState);
	$: readinessKnown = Boolean(readinessState);
	$: showLockedSurface =
		collectionId && !isOverviewRoute && (!readinessKnown || !downstreamUnlocked);

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

	function readinessFromCollectionStatus(status?: string | null) {
		const normalized = String(status ?? '').trim();
		if (['processing', 'running', 'queued', 'started', 'in_progress'].includes(normalized)) {
			return 'processing';
		}
		if (['idle', 'pending', 'uploaded', 'ready_to_process'].includes(normalized)) {
			return 'ready_to_process';
		}
		if (['ready', 'complete', 'completed', 'document_profiled', 'graph_ready'].includes(normalized)) {
			return 'ready';
		}
		if (['failed', 'error', 'attention_required'].includes(normalized)) {
			return 'failed';
		}
		return null;
	}

	function buildLockReason(state: typeof readinessState) {
		if (state === 'processing') return $t('collection.lock.processing');
		if (state === 'failed') return $t('collection.lock.failed');
		if (state === 'empty') return $t('collection.lock.empty');
		if (state === 'ready_to_process') return $t('collection.lock.readyToProcess');
		return $t('collection.lock.readyToProcess');
	}

	function tabClass(pathPrefix: string) {
		return currentPath.startsWith(pathPrefix) ? 'active' : '';
	}

	function handleLockedTabClick(event: MouseEvent) {
		if (!downstreamUnlocked) {
			event.preventDefault();
		}
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
		href={resolve('/collections/[id]/objectives', { id: collectionId })}
		class={`${tabClass(`/collections/${collectionId}/objectives`)} ${downstreamUnlocked ? '' : 'locked'}`}
		aria-disabled={downstreamUnlocked ? undefined : 'true'}
		tabindex={downstreamUnlocked ? undefined : -1}
		title={downstreamUnlocked ? undefined : lockReason}
		on:click={handleLockedTabClick}
	>
		{$t('collection.tabs.objectives')}
	</a>
	<a
		href={`/collections/${collectionId}/documents`}
		class={`${tabClass(`/collections/${collectionId}/documents`)} ${downstreamUnlocked ? '' : 'locked'}`}
		aria-disabled={downstreamUnlocked ? undefined : 'true'}
		tabindex={downstreamUnlocked ? undefined : -1}
		title={downstreamUnlocked ? undefined : lockReason}
		on:click={handleLockedTabClick}
	>
		{$t('collection.tabs.papers')}
	</a>
	<a
		href={`/collections/${collectionId}/assistant`}
		class={`${tabClass(`/collections/${collectionId}/assistant`)} ${downstreamUnlocked ? '' : 'locked'}`}
		aria-disabled={downstreamUnlocked ? undefined : 'true'}
		tabindex={downstreamUnlocked ? undefined : -1}
		title={downstreamUnlocked ? undefined : lockReason}
		on:click={handleLockedTabClick}
	>
		{$t('collection.tabs.assistant')}
	</a>
	<a
		href={`/collections/${collectionId}/graph`}
		class={`${tabClass(`/collections/${collectionId}/graph`)} ${downstreamUnlocked ? '' : 'locked'}`}
		aria-disabled={downstreamUnlocked ? undefined : 'true'}
		tabindex={downstreamUnlocked ? undefined : -1}
		title={downstreamUnlocked ? undefined : lockReason}
		on:click={handleLockedTabClick}
	>
		{$t('collection.tabs.graph')}
	</a>
	<details class="collection-tabs__more" class:active={moreActive}>
		<summary>{$t('collection.moreLabel')}</summary>
		<div class="collection-tabs__menu">
			<a
				href={`/collections/${collectionId}/materials`}
				class={`${tabClass(`/collections/${collectionId}/materials`)} ${downstreamUnlocked ? '' : 'locked'}`}
				aria-disabled={downstreamUnlocked ? undefined : 'true'}
				tabindex={downstreamUnlocked ? undefined : -1}
				title={downstreamUnlocked ? undefined : lockReason}
				on:click={handleLockedTabClick}
			>
				{$t('collection.tabs.materials')}
			</a>
			<a
				href={`/collections/${collectionId}/comparisons`}
				class={`${tabClass(`/collections/${collectionId}/comparisons`)} ${downstreamUnlocked ? '' : 'locked'}`}
				aria-disabled={downstreamUnlocked ? undefined : 'true'}
				tabindex={downstreamUnlocked ? undefined : -1}
				title={downstreamUnlocked ? undefined : lockReason}
				on:click={handleLockedTabClick}
			>
				{$t('collection.tabs.allComparisons')}
			</a>
			<a
				href={evidenceHref}
				class={`${tabClass(`/collections/${collectionId}/evidence`)} ${downstreamUnlocked ? '' : 'locked'}`}
				aria-disabled={downstreamUnlocked ? undefined : 'true'}
				tabindex={downstreamUnlocked ? undefined : -1}
				title={downstreamUnlocked ? undefined : lockReason}
				on:click={handleLockedTabClick}
			>
				{$t('collection.tabs.evidence')}
			</a>
			<a
				href={`/collections/${collectionId}/results`}
				class={`${tabClass(`/collections/${collectionId}/results`)} ${downstreamUnlocked ? '' : 'locked'}`}
				aria-disabled={downstreamUnlocked ? undefined : 'true'}
				tabindex={downstreamUnlocked ? undefined : -1}
				title={downstreamUnlocked ? undefined : lockReason}
				on:click={handleLockedTabClick}
			>
				{$t('collection.tabs.extractedFacts')}
			</a>
		</div>
	</details>
</nav>

<div class="collection-panel">
	{#if showLockedSurface}
		<section class="collection-locked-surface" aria-labelledby="collection-locked-title">
			<p class="collection-locked-surface__eyebrow">{$t('collection.lock.eyebrow')}</p>
			<h2 id="collection-locked-title">{$t('collection.lock.title')}</h2>
			<p>{lockReason}</p>
			<a class="btn btn--primary" href={`/collections/${collectionId}`}>
				{$t('collection.lock.backToWorkspace')}
			</a>
		</section>
	{:else}
		<slot />
	{/if}
</div>
