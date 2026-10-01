<script lang="ts">
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { ArrowLeft, ArrowRight, Database, RefreshCw, TriangleAlert } from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchFeedbackDatasets,
		type FeedbackDataset,
		type FeedbackDatasetTaskType
	} from '../../../_shared/feedbackDatasets';
	import { goto } from '$app/navigation';

	let datasets: FeedbackDataset[] = [];
	let loading = true;
	let error = '';
	let loadedCollectionId = '';
	let loadGeneration = 0;
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

	function openTask(kind: FeedbackDatasetTaskType) {
		const dataset = datasets.find(
			(item) =>
				item.task_type === kind &&
				item.construction_spec?.mode === 'automatic_feedback_workbench'
		);
		if (!dataset) return;
		void goto(
			resolve('/collections/[id]/feedback/datasets/[dataset_id]', {
				id: collectionId,
				dataset_id: dataset.dataset_id
			})
		);
	}

	function taskLabel(value: FeedbackDatasetTaskType) {
		return $t(`taskDatasets.type.${value}`);
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

	<section class="task-grid" aria-labelledby="task-list-title">
		<div class="section-heading"><div><h2 id="task-list-title">{$t('taskDatasets.chooseTask')}</h2><p>{$t('taskDatasets.chooseTaskDetail')}</p></div></div>
		{#if loading}
			<div class="empty-state" aria-live="polite"><span class="loader"></span><span>{$t('taskDatasets.loadingWorkbenches')}</span></div>
		{:else}
			<div class="task-list">
				{#each ['sft', 'preference', 'evaluation'] as kind (kind)}
					{@const typed = kind as FeedbackDatasetTaskType}
					{@const items = datasets.filter((item) => item.task_type === typed && item.construction_spec?.mode === 'automatic_feedback_workbench')}
					<button class="task-card" type="button" on:click={() => openTask(typed)} disabled={items.length === 0}>
						<span class="task-card__icon" aria-hidden="true"><Database size={18} /></span>
						<span class="task-card__body"><strong>{taskLabel(typed)}</strong><small>{items.length ? $t('taskDatasets.workbenchCount', { count: items.length }) : $t('taskDatasets.waitingForWorkers')}</small></span>
						<ArrowRight size={17} aria-hidden="true" />
					</button>
				{/each}
			</div>
		{/if}
	</section>
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
	.task-grid { display: grid; gap: 24px; }
	.task-grid p { margin: 6px 0 0; color: var(--text-secondary); font-size: 13px; }
	.section-heading { display: flex; align-items: center; gap: 12px; padding-bottom: 16px; }
	.task-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
	.task-card { display: flex; align-items: center; gap: 14px; min-height: 104px; padding: 18px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); text-align: left; cursor: pointer; }
	.task-card:hover:not(:disabled) { border-color: var(--brand-primary); background: var(--bg-subtle); }
	.task-card:disabled { cursor: not-allowed; opacity: .58; }
	.task-card__icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 auto; color: var(--brand-primary); background: var(--brand-soft); border-radius: 6px; }
	.task-card__body { display: grid; gap: 5px; flex: 1; min-width: 0; }
	.task-card__body strong { font-size: 14px; }
	.task-card__body small { color: var(--text-secondary); font-size: 12px; }
	.task-card > :global(svg) { flex: 0 0 auto; color: var(--text-secondary); }
	.empty-state { display: grid; justify-items: center; align-content: center; gap: 12px; min-height: 180px; color: var(--text-secondary); font-size: 13px; text-align: center; }
	.loader { width: 20px; height: 20px; border: 2px solid var(--border-default); border-top-color: var(--brand-primary); border-radius: 50%; animation: spin 1s linear infinite; }
	button:focus-visible, a:focus-visible { outline: 2px solid var(--brand-primary); outline-offset: 3px; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 760px) { .task-list { grid-template-columns: 1fr; } }
	@media (max-width: 480px) { .datasets { padding: 16px; } h1 { font-size: 24px; } }
</style>
