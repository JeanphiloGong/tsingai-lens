<script lang="ts">
	import { onMount } from 'svelte';
	import { errorMessage } from '../../../_shared/api';
	import { createFindingVersion, fetchExperimentAnalysis, type ExperimentAnalysisProjection, type FindingAuthoringResult } from '../../../_shared/researchView';

	export let collectionId: string;
	export let objectiveId: string;
	export let analysisVersion: number;
	export let onSaved: (result: FindingAuthoringResult) => void | Promise<void> = () => {};
	export let onCancel: () => void = () => {};

	let projection: ExperimentAnalysisProjection | null = null;
	let selectionIds: string[] = [];
	let comparisonGroupIds: string[] = [];
	let saving = false;
	let loading = true;
	let formError = '';

	onMount(async () => {
		try {
			projection = await fetchExperimentAnalysis(collectionId, objectiveId, analysisVersion);
		} catch (error) {
			formError = errorMessage(error);
		} finally {
			loading = false;
		}
	});

	function toggle(values: string[], value: string): string[] {
		return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
	}

	async function submit() {
		formError = '';
		if (!selectionIds.length) { formError = '至少选择一个实验结果。'; return; }
		saving = true;
		try {
			const result = await createFindingVersion(collectionId, objectiveId, { source_analysis_version: analysisVersion, selection_ids: selectionIds, comparison_group_ids: comparisonGroupIds });
			await onSaved(result);
		} catch (error) { formError = errorMessage(error); } finally { saving = false; }
	}
</script>

<section class="authoring-editor" aria-label="从实验选择创建 Finding">
	<header><div><h3>从实验选择创建 Finding</h3><p>结论由固定实验选择和比较组聚合生成。</p></div><button type="button" on:click={onCancel} aria-label="取消">取消</button></header>
	{#if loading}<p class="state">正在加载实验分析...</p>
	{:else if projection}
		<div class="picker">
			<h4>实验选择</h4>
			{#each projection.selections as selection (selection.selection_id)}
				<label class="option"><input type="checkbox" checked={selectionIds.includes(selection.selection_id)} on:change={() => (selectionIds = toggle(selectionIds, selection.selection_id))} /><span>{selection.selection_id} · {selection.outcome}</span></label>
			{:else}<p class="state">当前版本没有可选实验结果。</p>{/each}
			<h4>比较组（可选）</h4>
			{#each projection.comparison_groups as group (group.group_id)}
				<label class="option"><input type="checkbox" checked={comparisonGroupIds.includes(group.group_id)} on:change={() => (comparisonGroupIds = toggle(comparisonGroupIds, group.group_id))} /><span>{group.group_id} · {group.outcome}</span></label>
			{/each}
		</div>
	{:else}<p class="error">{formError}</p>{/if}
	{#if formError && projection}<p class="error">{formError}</p>{/if}
	<footer><button type="button" on:click={submit} disabled={saving || loading || !selectionIds.length}>{saving ? '正在创建...' : '创建 Finding'}</button></footer>
</section>

<style>
	.authoring-editor { display: grid; gap: 1rem; padding: 1rem; border: 1px solid var(--border-subtle, #d7dce2); border-radius: 8px; }
	header, footer { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
	h3, h4, p { margin: 0; } h3 { font-size: 1rem; } h4 { margin-top: .5rem; font-size: .9rem; }
	.picker { display: grid; gap: .55rem; } .option { display: flex; gap: .5rem; align-items: flex-start; padding: .45rem; }
	.state { color: var(--text-muted, #667085); } .error { color: var(--color-danger, #b42318); } button { padding: .45rem .8rem; }
</style>
