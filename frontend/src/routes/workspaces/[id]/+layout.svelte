<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { errorMessage } from '../../_shared/api';
	import {
		workspaces,
		deleteWorkspace,
		fetchWorkspace,
		fetchWorkspaces
	} from '$lib/workspace/workspaces';
	import { t } from '../../_shared/i18n';

	let deleteLoading = false;
	let deleteError = '';

	$: workspaceId = $page.params.id ?? '';
	$: workspace = $workspaces.find((item) => item.workspace_id === workspaceId);
	$: workspaceName = workspace?.name;
	$: documentCount = workspace?.documents.length ?? workspace?.paper_count ?? 0;
	$: readyDocumentCount =
		workspace?.documents.filter((document) => document.status === 'ready').length ?? 0;
	$: processingDocumentCount =
		workspace?.documents.filter((document) => document.status === 'processing').length ?? 0;
	$: currentPath = $page.url.pathname;
	$: isFindingRoute = Boolean($page.params.objective_id);
	$: isObjectivesRoute = currentPath.startsWith(`/workspaces/${workspaceId}/objectives`);
	$: isMoreRoute = ['graph'].some((route) =>
		currentPath.startsWith(`/workspaces/${workspaceId}/${route}`)
	);
	let moreMenu: HTMLDetailsElement;
	$: statusTone = processingDocumentCount ? 'processing' : readyDocumentCount ? 'ready' : 'pending';
	$: statusLabel = processingDocumentCount
		? $t('overview.currentModel.status.processing')
		: readyDocumentCount
			? $t('overview.currentModel.status.ready')
			: documentCount
				? $t('overview.currentModel.status.stored')
				: $t('overview.readinessLabels.empty');
	$: updatedAt = workspace?.updated_at || '';

	onMount(() => {
		if (!$workspaces.length) {
			fetchWorkspaces().catch(() => null);
		}
		if (workspaceId) {
			fetchWorkspace(workspaceId).catch(() => null);
		}
	});

	function closeMoreOnEscape(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			moreMenu.open = false;
			moreMenu.querySelector('summary')?.focus();
		}
	}

	function formatDate(value?: string | null) {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString();
	}

	async function removeCurrentWorkspace() {
		const name = workspaceName || $t('workspace.unknownName');
		if (!window.confirm($t('workspace.deleteConfirm', { name }))) {
			return;
		}

		deleteLoading = true;
		deleteError = '';

		try {
			await deleteWorkspace(workspaceId);
			await goto(resolve('/'));
		} catch (err) {
			deleteError = errorMessage(err);
		} finally {
			deleteLoading = false;
		}
	}
</script>

{#if isObjectivesRoute}
	<div class="workspace-context-bar">
		<a
			href={resolve('/workspaces/[id]', { id: workspaceId })}
			title={workspaceName || $t('workspace.unknownName')}
		>
			{workspaceName || $t('workspace.unknownName')}
		</a>
		<span>{$t('workspace.metaDocuments', { count: documentCount })}</span>
	</div>
{:else}
	<section class="workspace-header">
		<div class="workspace-header__main">
			<div class="workspace-title-row">
				<h1>{workspaceName || $t('workspace.unknownName')}</h1>
			</div>
			<p class="workspace-subtitle">
				{workspace?.description || $t('workspace.defaultSubtitle')}
			</p>
			<div class="workspace-meta-row">
				<span>{$t('workspace.metaDocuments', { count: documentCount })}</span>
				<span class={`status-badge status-badge--${statusTone}`}>{statusLabel}</span>
				<span>{$t('workspace.metaUpdated', { time: formatDate(updatedAt) })}</span>
			</div>
		</div>
		<div class="workspace-actions" aria-label={$t('workspace.actionsLabel')}>
			<a class="btn btn--ghost" href={resolve('/')}>{$t('workspace.backToWorkspaces')}</a>
			<button
				class="btn btn--danger"
				type="button"
				disabled={deleteLoading}
				on:click={removeCurrentWorkspace}
			>
				{deleteLoading ? $t('workspace.deleting') : $t('workspace.delete')}
			</button>
		</div>
	</section>
{/if}

{#if deleteError}
	<div class="status status--error" role="alert">{deleteError}</div>
{/if}

<nav
	class="workspace-tabs"
	class:workspace-tabs--compact={isFindingRoute}
	aria-label={$t('workspace.tabsLabel')}
>
	{#each [['', 'overview'], ['/documents', 'papers'], ['/objectives', 'objectives'], ['/assistant', 'assistant']] as [suffix, label] (suffix)}
		{@const href = `/workspaces/${workspaceId}${suffix}`}
		{@const active = suffix ? currentPath.startsWith(href) : currentPath === href}
		<a
			href={resolve(href as `/workspaces/${string}`)}
			class:active
			aria-current={active ? 'page' : undefined}>{$t(`workspace.tabs.${label}`)}</a
		>
	{/each}
	<details class="workspace-tabs__more" class:active={isMoreRoute} bind:this={moreMenu}>
		<summary on:keydown={closeMoreOnEscape}>{$t('workspace.moreLabel')}</summary>
		<div class="workspace-tabs__menu">
			{#each ['graph'] as route (route)}
				{@const href = `/workspaces/${workspaceId}/${route}`}
				{@const active = currentPath.startsWith(href)}
				<a
					href={resolve(href as `/workspaces/${string}`)}
					class:active
					aria-current={active ? 'page' : undefined}
					on:keydown={closeMoreOnEscape}
					on:click={() => (moreMenu.open = false)}>{$t(`workspace.tabs.${route}`)}</a
				>
			{/each}
		</div>
	</details>
</nav>

<div class="workspace-panel">
	<slot />
</div>

<style>
	.workspace-context-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		min-width: 0;
		font-size: 13px;
		line-height: 24px;
	}
	.workspace-context-bar a {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-primary);
		font-weight: 600;
	}
	.workspace-context-bar span {
		flex-shrink: 0;
		color: var(--text-secondary);
		font-size: 12px;
	}
	.workspace-tabs--compact {
		min-width: 0;
		border-radius: 6px;
		box-shadow: none;
	}
</style>
