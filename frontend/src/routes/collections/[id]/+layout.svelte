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
	$: workspaceUpdatedAt =
		workspace?.latest_task?.updated_at ||
		workspace?.collection.updated_at ||
		workspace?.artifacts.updated_at ||
		'';
	$: storeHasNewerWorkspaceState = isLaterTimestamp(
		storeCollection?.updated_at,
		workspaceUpdatedAt
	);
	$: currentPath = $page.url.pathname;
	$: isOverviewRoute = currentPath === `/collections/${collectionId}`;
	$: isAssistantRoute = currentPath.startsWith(`/collections/${collectionId}/assistant`);
	$: readinessState =
		stateWorkspace && !(storeHasNewerWorkspaceState && storeReadinessState)
			? getOverviewReadinessState(stateWorkspace)
			: storeReadinessState;
	$: statusLabel = readinessState
		? $t(`overview.readinessLabels.${readinessState}`)
		: formatStatus(collection?.status);
	$: statusTone = readinessState ?? 'pending';
	$: updatedAt = collection?.updated_at || workspace?.artifacts.updated_at || '';
	$: downstreamUnlocked = readinessState === 'ready';
	$: lockReason = buildLockReason(readinessState);
	$: readinessKnown = Boolean(readinessState);
	$: showLockedSurface =
		collectionId &&
		!isOverviewRoute &&
		!isAssistantRoute &&
		(!readinessKnown || !downstreamUnlocked);

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
		if (
			['ready', 'complete', 'completed', 'document_profiled', 'graph_ready'].includes(normalized)
		) {
			return 'ready';
		}
		if (['failed', 'error', 'attention_required'].includes(normalized)) {
			return 'failed';
		}
		return null;
	}

	function isLaterTimestamp(candidate?: string | null, current?: string | null) {
		if (!candidate) return false;
		if (!current) return false;
		const candidateTime = Date.parse(candidate);
		const currentTime = Date.parse(current);
		if (Number.isNaN(candidateTime) || Number.isNaN(currentTime)) return candidate > current;
		return candidateTime > currentTime;
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
		href={`/collections/${collectionId}/comparisons`}
		class={`${tabClass(`/collections/${collectionId}/comparisons`)} ${downstreamUnlocked ? '' : 'locked'}`}
		aria-disabled={downstreamUnlocked ? undefined : 'true'}
		tabindex={downstreamUnlocked ? undefined : -1}
		title={downstreamUnlocked ? undefined : lockReason}
		on:click={handleLockedTabClick}
	>
		{$t('collection.tabs.comparisons')}
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
		class={tabClass(`/collections/${collectionId}/assistant`)}
	>
		{$t('collection.tabs.assistant')}
	</a>
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
