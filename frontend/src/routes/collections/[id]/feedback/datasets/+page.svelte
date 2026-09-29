<script lang="ts">
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { ArrowLeft, ArrowRight, Database, Plus, RefreshCw, TriangleAlert } from '@lucide/svelte';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		createFeedbackDataset,
		fetchFeedbackDatasets,
		type FeedbackDataset,
		type FeedbackDatasetTaskType
	} from '../../../../_shared/feedbackDatasets';

	let datasets: FeedbackDataset[] = [];
	let name = '';
	let taskType: FeedbackDatasetTaskType = 'sft';
	let loading = true;
	let creating = false;
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
			const response = await fetchFeedbackDatasets(collectionId, { limit: 200 });
			if (generation !== loadGeneration) return;
			datasets = response.items;
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
			<a class="back-link" href={resolve('/collections/[id]/feedback', { id: collectionId })}>
				<ArrowLeft size={15} aria-hidden="true" />{$t('taskDatasets.back')}
			</a>
			<p class="eyebrow">{$t('taskDatasets.eyebrow')}</p>
			<h1 id="datasets-title">{$t('taskDatasets.title')}</h1>
			<p class="lede">{$t('taskDatasets.lede')}</p>
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

	<div class="workspace-grid">
		<section class="create-panel" aria-labelledby="create-title">
			<div class="panel-icon" aria-hidden="true"><Plus size={18} /></div>
			<div class="panel-copy">
				<p class="eyebrow">{$t('taskDatasets.createTitle')}</p>
				<h2 id="create-title">{$t('taskDatasets.createTitle')}</h2>
				<p>{$t('taskDatasets.createDetail')}</p>
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
				<label for="dataset-task-type">{$t('taskDatasets.taskTypeLabel')}</label>
				<select id="dataset-task-type" bind:value={taskType}>
					<option value="sft">{$t('taskDatasets.type.sft')}</option>
					<option value="preference">{$t('taskDatasets.type.preference')}</option>
					<option value="evaluation">{$t('taskDatasets.type.evaluation')}</option>
				</select>
				<button class="primary-button" type="submit" disabled={creating || !name.trim()}>
					<Plus size={16} aria-hidden="true" />{creating ? $t('taskDatasets.creating') : $t('taskDatasets.create')}
				</button>
			</form>
		</section>

		<section class="list-panel" aria-labelledby="list-title">
			<div class="section-heading">
				<div>
					<p class="eyebrow">{$t('taskDatasets.title')}</p>
					<h2 id="list-title">{$t('taskDatasets.title')}</h2>
				</div>
				<span class="count">{datasets.length}</span>
			</div>

			{#if loading}
				<div class="empty-state" aria-live="polite"><span class="loader"></span><span>Loading…</span></div>
			{:else if datasets.length === 0}
				<div class="empty-state">
					<Database size={22} aria-hidden="true" />
					<strong>{$t('taskDatasets.emptyTitle')}</strong>
					<span>{$t('taskDatasets.emptyDetail')}</span>
				</div>
			{:else}
				<div class="dataset-list">
					{#each datasets as dataset (dataset.dataset_id)}
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
	:global(body) { background: #f6f8fb; }
	.datasets { max-width: 1180px; margin: 0 auto; padding: 34px 28px 72px; color: #253347; }
	.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 28px; }
	.page-heading { min-width: 0; }
	.back-link { display: inline-flex; gap: 7px; align-items: center; color: #557086; font-size: 13px; font-weight: 700; text-decoration: none; }
	.back-link:hover { color: #147d74; }
	.eyebrow { margin: 18px 0 7px; color: #168278; font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
	h1, h2, p { margin: 0; }
	h1 { color: #18273a; font-size: clamp(28px, 4vw, 42px); line-height: 1.08; letter-spacing: 0; }
	.lede { max-width: 690px; margin-top: 12px; color: #607086; font-size: 15px; line-height: 1.65; }
	.icon-button { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; flex: 0 0 auto; border: 1px solid #d6e0ea; border-radius: 7px; background: #fff; color: #476277; cursor: pointer; }
	.icon-button:hover:not(:disabled) { border-color: #7dc8bf; color: #147d74; }
	.icon-button:disabled { cursor: wait; opacity: .58; }
	.spin { display: inline-flex; }
	.spin :global(svg) { animation: spin 1s linear infinite; }
	.notice { display: flex; gap: 9px; align-items: center; margin-bottom: 20px; border: 1px solid #fecaca; border-radius: 7px; background: #fff5f5; color: #b42318; padding: 11px 13px; font-size: 13px; }
	.workspace-grid { display: grid; grid-template-columns: minmax(260px, .72fr) minmax(0, 1.28fr); gap: 18px; align-items: start; }
	.create-panel, .list-panel { border: 1px solid #dce4ed; border-radius: 8px; background: #fff; box-shadow: 0 7px 24px rgba(35, 53, 71, .06); }
	.create-panel { display: grid; gap: 14px; padding: 22px; }
	.panel-icon, .dataset-card__icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 7px; background: #e8f6f4; color: #147d74; }
	.panel-copy h2, .section-heading h2 { color: #223249; font-size: 18px; line-height: 1.25; }
	.panel-copy p:last-child { margin-top: 8px; color: #718096; font-size: 13px; line-height: 1.55; }
	.create-form { display: grid; gap: 8px; margin-top: 3px; }
	.create-form label { color: #52647a; font-size: 12px; font-weight: 750; }
	.create-form input, .create-form select { width: 100%; box-sizing: border-box; border: 1px solid #cbd7e3; border-radius: 6px; background: #fff; color: #253347; padding: 10px 11px; font: inherit; font-size: 13px; }
	.create-form input:focus, .create-form select:focus { outline: 3px solid rgba(34, 153, 141, .16); border-color: #299e91; }
	.primary-button { display: inline-flex; gap: 7px; align-items: center; justify-content: center; margin-top: 6px; border: 1px solid #147d74; border-radius: 6px; background: #147d74; color: #fff; padding: 10px 13px; font-size: 13px; font-weight: 800; cursor: pointer; }
	.primary-button:hover:not(:disabled) { background: #10685f; }
	.primary-button:disabled { cursor: not-allowed; opacity: .48; }
	.list-panel { min-height: 300px; padding: 22px; }
	.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e5ebf1; padding-bottom: 15px; }
	.section-heading .eyebrow { margin: 0 0 6px; }
	.count { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; height: 28px; border-radius: 999px; background: #e8f6f4; color: #147d74; font-size: 12px; font-weight: 800; }
	.dataset-list { display: grid; gap: 10px; padding-top: 15px; }
	.dataset-card { display: flex; align-items: center; gap: 12px; min-width: 0; border: 1px solid #e0e7ef; border-radius: 7px; background: #fff; color: inherit; padding: 14px; text-decoration: none; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
	.dataset-card:hover { border-color: #7dc8bf; box-shadow: 0 6px 15px rgba(20, 125, 116, .09); transform: translateY(-1px); }
	.dataset-card__body { min-width: 0; flex: 1; }
	.dataset-card__topline { display: flex; gap: 12px; align-items: baseline; justify-content: space-between; }
	.dataset-card__topline strong { min-width: 0; overflow: hidden; color: #253347; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
	.dataset-card__topline span { flex: 0 0 auto; color: #147d74; font-size: 11px; font-weight: 800; }
	.dataset-card__meta { display: flex; flex-wrap: wrap; gap: 5px 14px; margin-top: 7px; color: #7b8b9f; font-size: 11px; }
	.dataset-card > :global(svg) { color: #91a1b3; }
	.empty-state { display: grid; justify-items: center; gap: 8px; min-height: 220px; align-content: center; color: #7b8b9f; text-align: center; font-size: 13px; }
	.empty-state strong { color: #3b4b60; font-size: 14px; }
	.empty-state :global(svg) { color: #6e9e9a; }
	.loader { width: 19px; height: 19px; border: 2px solid #d8ebe8; border-top-color: #168278; border-radius: 50%; animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 760px) {
		.datasets { padding: 24px 16px 52px; }
		.page-header { gap: 12px; }
		.workspace-grid { grid-template-columns: 1fr; }
		.create-panel, .list-panel { padding: 18px; }
		.dataset-card__topline { display: grid; gap: 5px; }
		.dataset-card__topline strong { white-space: normal; overflow: visible; }
	}
</style>
