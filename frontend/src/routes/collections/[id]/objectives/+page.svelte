<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		confirmObjective,
		fetchCollectionObjectives,
		runObjectiveAnalysis,
		type ObjectiveList,
		type ObjectiveSummary
	} from '../../../_shared/researchView';

	let objectiveList: ObjectiveList | null = null;
	let loading = false;
	let actionObjectiveId = '';
	let error = '';
	let loadedCollectionId = '';

	$: collectionId = $page.params.id ?? '';
	$: objectives = objectiveList?.objectives ?? [];
	$: confirmedCount = objectives.filter(
		(objective) => objective.confirmation_status === 'confirmed'
	).length;
	$: publishedCount = objectives.filter(
		(objective) => objective.published_analysis_version !== null
	).length;
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadObjectives();
	}

	async function loadObjectives() {
		loading = true;
		error = '';
		try {
			objectiveList = await fetchCollectionObjectives(collectionId);
		} catch (err) {
			objectiveList = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function objectiveHref(objectiveId: string) {
		return resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: objectiveId
		});
	}

	async function startAnalysis(objective: ObjectiveSummary) {
		if (actionObjectiveId) return;
		actionObjectiveId = objective.objective_id;
		error = '';
		try {
			if (objective.confirmation_status === 'candidate') {
				await confirmObjective(collectionId, objective.objective_id);
			}
			await runObjectiveAnalysis(collectionId, objective.objective_id);
			await goto(objectiveHref(objective.objective_id));
		} catch (err) {
			error = errorMessage(err);
		} finally {
			actionObjectiveId = '';
		}
	}

	function joined(items: string[]) {
		return items.length ? items.join(', ') : '-';
	}
</script>

<svelte:head><title>研究目标</title></svelte:head>

<section class="objectives-page">
	<header>
		<div>
			<h2>研究目标</h2>
			<p>确认研究问题后，系统将逐篇文献提取证据并生成可审计的 Findings。</p>
		</div>
		<button class="btn btn--ghost" type="button" on:click={loadObjectives}>刷新</button>
	</header>

	{#if loading}
		<p class="state" aria-busy="true">正在加载...</p>
	{:else if error}
		<p class="state state--error" role="alert">{error}</p>
	{:else if !objectives.length}
		<p class="state">当前 collection 尚未生成研究目标。</p>
	{:else}
		<div class="summary" aria-label="研究目标概览">
			<div><strong>{objectives.length}</strong><span>研究目标</span></div>
			<div><strong>{confirmedCount}</strong><span>已确认</span></div>
			<div><strong>{publishedCount}</strong><span>已有结果</span></div>
		</div>

		<div class="objective-list">
			{#each objectives as objective (objective.objective_id)}
				<article>
					<div class="heading">
						<div>
							<h3>{objective.question}</h3>
							<p>{objective.comparison_intent || '尚未设置比较意图'}</p>
						</div>
						<span class:published={objective.published_analysis_version !== null}>
							{objective.published_analysis_version !== null
								? `结果 v${objective.published_analysis_version}`
								: objective.confirmation_status === 'confirmed'
									? '已确认'
									: '待确认'}
						</span>
					</div>
					<dl>
						<div><dt>材料</dt><dd>{joined(objective.material_scope)}</dd></div>
						<div><dt>变量</dt><dd>{joined(objective.process_axes)}</dd></div>
						<div><dt>结果</dt><dd>{joined(objective.property_axes)}</dd></div>
						<div><dt>文献范围</dt><dd>{objective.seed_document_ids.length} 篇</dd></div>
					</dl>
					<div class="actions">
						{#if objective.published_analysis_version === null}
							<button
								class="btn btn--primary btn--small"
								type="button"
								disabled={Boolean(actionObjectiveId)}
								on:click={() => startAnalysis(objective)}
							>
								{actionObjectiveId === objective.objective_id ? '正在启动...' : '确认并分析'}
							</button>
						{/if}
						<a class="btn btn--ghost btn--small" href={objectiveHref(objective.objective_id)}>
							{objective.published_analysis_version === null ? '查看状态' : '查看 Findings'}
						</a>
					</div>
				</article>
			{/each}
		</div>
	{/if}
</section>

<style>
	.objectives-page { width: min(1120px, 100%); margin: 0 auto; display: grid; gap: 20px; }
	header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; border-bottom: 1px solid var(--border-default); padding-bottom: 16px; }
	h2, h3, p { margin: 0; }
	header p, article p, dt, .summary span { color: var(--text-secondary); }
	header p { margin-top: 6px; max-width: 720px; }
	.state { padding: 28px 0; color: var(--text-secondary); }
	.state--error { color: var(--danger, #b42318); }
	.summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-block: 1px solid var(--border-default); }
	.summary div { display: grid; gap: 2px; padding: 14px 18px; border-right: 1px solid var(--border-default); }
	.summary div:last-child { border-right: 0; }
	.summary strong { font-size: 20px; }
	.objective-list { display: grid; gap: 10px; }
	article { border-bottom: 1px solid var(--border-default); padding: 18px 0; display: grid; gap: 16px; }
	.heading { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
	.heading h3 { font-size: 17px; line-height: 1.45; }
	.heading p { margin-top: 5px; }
	.heading > span { white-space: nowrap; padding: 4px 8px; border: 1px solid var(--border-default); font-size: 12px; }
	.heading > span.published { border-color: #3a7d5d; color: #256346; }
	dl { margin: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
	dt { font-size: 12px; margin-bottom: 4px; }
	dd { margin: 0; line-height: 1.45; overflow-wrap: anywhere; }
	.actions { display: flex; gap: 8px; }
	@media (max-width: 760px) {
		header, .heading { flex-direction: column; }
		dl { grid-template-columns: 1fr 1fr; }
		.summary { grid-template-columns: 1fr; }
		.summary div { border-right: 0; border-bottom: 1px solid var(--border-default); }
	}
</style>
