<script lang="ts">
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { ArrowLeft, ArrowRight, Database, Plus, RefreshCw, TriangleAlert } from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		createFeedbackDataset,
		fetchFeedbackDatasets,
		type FeedbackDataset,
		type FeedbackDatasetTaskType
	} from '../../../_shared/feedbackDatasets';
	import { goto } from '$app/navigation';

	let datasets: FeedbackDataset[] = [];
	let name = '';
	let taskType: FeedbackDatasetTaskType = 'sft';
	let loading = true;
	let creating = false;
	let error = '';
	let loadedCollectionId = '';
	let loadGeneration = 0;
	$: visibleDatasets = datasets.filter((item) => item.task_type === taskType);

	$: collectionId = $page.params.id ?? '';
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		const generation = ++loadGeneration;
		void load(generation);
	}

	async function load(generation = loadGeneration) {
		loading = true;
		error = '';
		try {
			const items: FeedbackDataset[] = [];
			let response;
			do {
				response = await fetchFeedbackDatasets(collectionId, { limit: 200, offset: items.length });
				items.push(...response.items);
			} while (response.items.length === 200);
			if (generation !== loadGeneration) return;
			datasets = items;
		} catch (err) {
			if (generation === loadGeneration) error = errorMessage(err);
		} finally {
			if (generation === loadGeneration) loading = false;
		}
	}

	async function createDataset() {
		const cleaned = name.trim();
		if (!cleaned || creating) return;
		creating = true;
		error = '';
		try {
			const dataset = await createFeedbackDataset(collectionId, cleaned, taskType, {
				language: 'zh-CN',
				source_kinds: ['feedback_case']
			});
			datasets = [dataset, ...datasets.filter((item) => item.dataset_id !== dataset.dataset_id)];
			name = '';
			await goto(`/collections/${encodeURIComponent(collectionId)}/feedback/datasets/${encodeURIComponent(dataset.dataset_id)}`);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			creating = false;
		}
	}

	function taskLabel(value: FeedbackDatasetTaskType) {
		return $t(`taskDatasets.type.${value}`);
	}

	function formatDate(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}
</script>

<svelte:head>
	<title>{$t('taskDatasets.title')} | Lens</title>
</svelte:head>

<section class="datasets" aria-labelledby="datasets-title">
	<header class="page-header">
		<div class="page-heading">
			<a class="back-link" href={resolve('/collections/[id]', { id: collectionId })}>
				<ArrowLeft size={15} aria-hidden="true" />{$t('taskDatasets.back')}
			</a>
			<h1 id="datasets-title">{$t('taskDatasets.title')}</h1>
		</div>
		<button
			class="icon-button"
			type="button"
			title={$t('taskDatasets.refresh')}
			aria-label={$t('taskDatasets.refresh')}
			on:click={() => load()}
			disabled={loading}
		>
			<span class:spin={loading}><RefreshCw size={17} aria-hidden="true" /></span>
		</button>
	</header>

	{#if error}
		<div class="notice" role="alert">
			<TriangleAlert size={17} aria-hidden="true" /><span>{error}</span>
		</div>
	{/if}

	<nav class="task-tabs" aria-label={$t('taskDatasets.taskTypeLabel')}>
		{#each ['sft', 'preference', 'evaluation'] as kind}
			<button type="button" class:active={taskType === kind} aria-pressed={taskType === kind} on:click={() => taskType = kind as FeedbackDatasetTaskType}>{taskLabel(kind as FeedbackDatasetTaskType)} <span>{datasets.filter((item) => item.task_type === kind).length}</span></button>
		{/each}
	</nav>
	<div class="workspace-grid">
		<section class="create-panel" aria-labelledby="create-title">
			<div class="panel-copy">
				<h2 id="create-title">{$t('taskDatasets.createTitle')}</h2>
			</div>
			<form class="create-form" on:submit|preventDefault={createDataset}>
				<label for="dataset-name">{$t('taskDatasets.nameLabel')}</label>
				<input
					id="dataset-name"
					bind:value={name}
					maxlength="120"
					placeholder={$t('taskDatasets.namePlaceholder')}
					required
				/>
				<button class="primary-button" type="submit" disabled={creating || !name.trim()}>
					<Plus size={16} aria-hidden="true" />{creating ? $t('taskDatasets.creating') : $t('taskDatasets.create')}
				</button>
			</form>
		</section>

		<section class="list-panel" aria-labelledby="list-title">
			<div class="section-heading">
				<div>
					<h2 id="list-title">{taskLabel(taskType)}</h2>
				</div>
				<span class="count">{visibleDatasets.length}</span>
			</div>

			{#if loading}
				<div class="empty-state" aria-live="polite"><span class="loader"></span><span>Loading…</span></div>
			{:else if visibleDatasets.length === 0}
				<div class="empty-state">
					<Database size={22} aria-hidden="true" />
					<strong>{$t('taskDatasets.emptyTitle')}</strong>
					<span>{$t('taskDatasets.emptyDetail')}</span>
				</div>
			{:else}
				<div class="dataset-list">
					{#each visibleDatasets as dataset (dataset.dataset_id)}
						<a
							class="dataset-card"
							href={`/collections/${encodeURIComponent(collectionId)}/feedback/datasets/${encodeURIComponent(dataset.dataset_id)}`}
						>
							<div class="dataset-card__icon" aria-hidden="true"><Database size={18} /></div>
							<div class="dataset-card__body">
								<div class="dataset-card__topline">
									<strong>{dataset.name}</strong>
									<span>{taskLabel(dataset.task_type)}</span>
								</div>
								<div class="dataset-card__meta">
									<span>{$t('taskDatasets.specVersion', { version: dataset.spec_version })}</span>
									<span>{$t('taskDatasets.updated', { date: formatDate(dataset.updated_at) })}</span>
								</div>
							</div>
							<ArrowRight size={17} aria-hidden="true" />
						</a>
					{/each}
				</div>
			{/if}
		</section>
	</div>
</section>

<style>
	.datasets { width: 100%; box-sizing: border-box; padding: 24px; color: var(--text-primary); background: var(--surface-card); border-block: 1px solid var(--border-default); }
	.page-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; }
	.page-heading { min-width: 0; }
	.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 12px; text-decoration: none; }
	.back-link:hover { color: var(--brand-primary); }
	h1 { margin: 8px 0 0; font-size: 28px; line-height: 36px; }
	h2 { margin: 0; font-size: 16px; line-height: 24px; }
	.icon-button { display: inline-grid; place-items: center; flex: 0 0 auto; width: 36px; height: 36px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-card); color: var(--text-secondary); cursor: pointer; }
	.icon-button:hover:not(:disabled) { color: var(--brand-primary); border-color: var(--brand-primary); }
	button:disabled { opacity: .5; cursor: not-allowed; }
	.spin { display: inline-flex; }
	.spin :global(svg) { animation: spin 1s linear infinite; }
	.notice { display: flex; align-items: center; gap: 8px; padding: 12px; margin-bottom: 16px; border: 1px solid var(--danger-border); border-radius: 6px; color: var(--danger-text); background: var(--danger-bg); font-size: 13px; }
	.task-tabs { display: flex; flex-wrap: wrap; gap: 8px; border-bottom: 1px solid var(--border-default); margin-bottom: 24px; }
	.task-tabs button { display: inline-flex; align-items: center; gap: 8px; padding: 12px 16px; border: 0; border-bottom: 2px solid transparent; color: var(--text-secondary); background: transparent; font: inherit; font-size: 14px; cursor: pointer; }
	.task-tabs button.active { border-bottom-color: var(--brand-primary); color: var(--brand-primary); font-weight: 600; }
	.task-tabs button:hover { background: var(--bg-subtle); }
	.task-tabs span { display: grid; place-items: center; min-width: 20px; height: 20px; padding-inline: 4px; box-sizing: border-box; border-radius: 4px; background: var(--bg-subtle); font-size: 12px; }
	.workspace-grid { display: grid; gap: 24px; }
	.create-panel { display: grid; grid-template-columns: 160px minmax(0, 1fr); align-items: center; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--border-default); }
	.create-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 8px 12px; max-width: 720px; }
	.create-form label { grid-column: 1 / -1; color: var(--text-secondary); font-size: 12px; font-weight: 600; }
	.create-form input { width: 100%; min-width: 0; box-sizing: border-box; height: 40px; border: 1px solid var(--border-strong); border-radius: 6px; padding: 8px 12px; background: var(--surface-card); color: var(--text-primary); font: inherit; font-size: 14px; }
	.primary-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; height: 40px; padding: 8px 16px; border: 1px solid var(--brand-primary); border-radius: 6px; background: var(--brand-primary); color: white; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; }
	.primary-button:hover:not(:disabled) { background: var(--brand-primary-hover); }
	.section-heading { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; }
	.count { color: var(--text-secondary); font-size: 13px; }
	.dataset-list { display: grid; }
	.dataset-card { display: flex; align-items: center; gap: 16px; padding: 20px 12px; border-top: 1px solid var(--border-default); color: var(--text-primary); text-decoration: none; min-width: 0; }
	.dataset-card:hover { background: var(--bg-subtle); }
	.dataset-card__icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 auto; color: var(--brand-primary); background: var(--brand-soft); border-radius: 6px; }
	.dataset-card__body { flex: 1; min-width: 0; }
	.dataset-card__topline { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; }
	.dataset-card__topline strong { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
	.dataset-card__topline span { font-size: 12px; color: var(--text-secondary); flex: 0 0 auto; }
	.dataset-card__meta { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 6px; color: var(--text-secondary); font-size: 12px; }
	.dataset-card > :global(svg) { flex: 0 0 auto; color: var(--text-secondary); }
	.empty-state { display: grid; justify-items: center; align-content: center; gap: 12px; min-height: 180px; color: var(--text-secondary); font-size: 13px; text-align: center; }
	.empty-state strong { font-size: 14px; color: var(--text-primary); }
	.loader { width: 20px; height: 20px; border: 2px solid var(--border-default); border-top-color: var(--brand-primary); border-radius: 50%; animation: spin 1s linear infinite; }
	button:focus-visible, a:focus-visible, input:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 3px; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 760px) { .create-panel { grid-template-columns: 1fr; gap: 12px; } .dataset-card__topline { display: grid; gap: 4px; } }
	@media (max-width: 480px) { .datasets { padding: 16px; } .task-tabs { gap: 0; } .task-tabs button { padding: 12px 8px; font-size: 12px; gap: 4px; } .create-form { grid-template-columns: 1fr; } .create-form label { grid-column: auto; } .dataset-card { padding: 16px 0; gap: 12px; } h1 { font-size: 24px; } }
</style>
