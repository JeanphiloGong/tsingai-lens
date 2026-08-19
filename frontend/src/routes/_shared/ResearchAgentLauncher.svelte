<script lang="ts">
	import { resolve } from '$app/paths';
	import './ResearchAgentLauncher.css';
	import { errorMessage } from './api';
	import { collections, fetchCollections } from './collections';
	import { t } from './i18n';

	export let collectionId = '';

	let dialog: HTMLDialogElement | null = null;
	let loading = false;
	let loadError = '';

	$: currentAgentHref = collectionId
		? resolve('/collections/[id]/assistant', { id: collectionId })
		: '';

	function openWorkspacePicker() {
		dialog?.showModal();
		void loadWorkspaces();
	}

	function closeWorkspacePicker() {
		dialog?.close();
	}

	async function loadWorkspaces() {
		loading = true;
		loadError = '';
		try {
			await fetchCollections();
		} catch (error) {
			loadError = errorMessage(error);
		} finally {
			loading = false;
		}
	}

	function closeFromBackdrop(event: MouseEvent) {
		if (event.target === dialog) closeWorkspacePicker();
	}
</script>

{#if collectionId}
	<a class="agent-launcher" href={currentAgentHref} aria-label={$t('researchAgent.title')}>
		<span class="agent-launcher__mark" aria-hidden="true">AI</span>
		<span class="agent-launcher__label">{$t('researchAgent.title')}</span>
	</a>
{:else}
	<button
		class="agent-launcher"
		type="button"
		aria-label={$t('researchAgent.title')}
		on:click={openWorkspacePicker}
	>
		<span class="agent-launcher__mark" aria-hidden="true">AI</span>
		<span class="agent-launcher__label">{$t('researchAgent.title')}</span>
	</button>

	<dialog
		class="workspace-picker"
		bind:this={dialog}
		aria-labelledby="research-agent-workspace-title"
		on:click={closeFromBackdrop}
	>
		<div class="workspace-picker__surface">
			<header class="workspace-picker__header">
				<div>
					<p>{$t('researchAgent.launcher.eyebrow')}</p>
					<h2 id="research-agent-workspace-title">{$t('researchAgent.launcher.title')}</h2>
				</div>
				<button
					class="workspace-picker__close"
					type="button"
					aria-label={$t('researchAgent.launcher.close')}
					on:click={closeWorkspacePicker}
				>
					<span aria-hidden="true">×</span>
				</button>
			</header>

			<p class="workspace-picker__description">{$t('researchAgent.launcher.description')}</p>

			<div class="workspace-picker__body" aria-busy={loading}>
				{#if loading && !$collections.length}
					<p class="workspace-picker__state" role="status">
						{$t('researchAgent.launcher.loading')}
					</p>
				{:else if loadError}
					<div class="workspace-picker__state workspace-picker__state--error" role="alert">
						<p>{loadError}</p>
						<button type="button" on:click={loadWorkspaces}>
							{$t('researchAgent.launcher.retry')}
						</button>
					</div>
				{:else if !$collections.length}
					<div class="workspace-picker__state">
						<p>{$t('researchAgent.launcher.empty')}</p>
						<a href="/" on:click={closeWorkspacePicker}>
							{$t('researchAgent.launcher.manageCollections')}
						</a>
					</div>
				{:else}
					<ul class="workspace-list">
						{#each $collections as collection (collection.id)}
							<li>
								<a
									href={resolve('/collections/[id]/assistant', { id: collection.id })}
									on:click={closeWorkspacePicker}
								>
									<span class="workspace-list__name">
										{collection.name || $t('collection.unknownName')}
									</span>
									<span class="workspace-list__meta">
										{$t('researchAgent.launcher.paperCount', {
											count: collection.paper_count ?? 0
										})}
										<span aria-hidden="true">·</span>
										{collection.status || $t('overview.statusUnknown')}
									</span>
									<span class="workspace-list__arrow" aria-hidden="true">→</span>
								</a>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	</dialog>
{/if}
