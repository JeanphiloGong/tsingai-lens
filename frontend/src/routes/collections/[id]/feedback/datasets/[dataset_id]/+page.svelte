<script lang="ts">
	import { page } from '$app/stores';
	import { ArrowLeft, RefreshCw } from '@lucide/svelte';
	import { errorMessage } from '../../../../../_shared/api';
	import { t } from '../../../../../_shared/i18n';
	import { fetchFeedbackDataset, type FeedbackDataset } from '../../../../../_shared/feedbackDatasets';

	let dataset: FeedbackDataset | null = null;
	let loading = true;
	let error = '';

	$: collectionId = $page.params.id ?? '';
	$: datasetId = $page.params.dataset_id ?? '';

	async function load() {
		loading = true;
		error = '';
		try {
			dataset = await fetchFeedbackDataset(datasetId);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	$: if (datasetId && !dataset) void load();
</script>

<svelte:head>
	<title>{dataset?.name ?? 'Dataset'} | Lens</title>
</svelte:head>

<main class="dataset-detail">
	<a class="back-link" href={`/collections/${encodeURIComponent(collectionId)}/feedback/datasets`}>
		<ArrowLeft size={16} />
		<span>返回数据集</span>
	</a>
	{#if loading}
		<p class="state">正在加载数据集…</p>
	{:else if error}
		<section class="notice" role="alert">
			<p>{error}</p>
			<button type="button" on:click={load}><RefreshCw size={16} />重试</button>
		</section>
	{:else if dataset}
		<header>
			<p class="eyebrow">文献问答 SFT</p>
			<h1>{dataset.name}</h1>
			<p>这个数据集固定使用 SFT 构建规则。下一步由 Worker 收集素材并生成待确认样本。</p>
		</header>
		<section class="empty-state" aria-labelledby="next-step">
			<h2 id="next-step">还没有样本</h2>
			<p>先从反馈案例收集素材，完成后这里会显示候选回答和证据。</p>
			<span>构建规则版本 {dataset.spec_version}</span>
		</section>
	{/if}
</main>

<style>
	:global(body) { background: #f6f7f9; }
	.dataset-detail { max-width: 960px; margin: 0 auto; padding: 32px 24px 80px; color: #1f2937; }
	.back-link { display: inline-flex; gap: 8px; align-items: center; color: #475569; text-decoration: none; margin-bottom: 32px; }
	header { background: white; border: 1px solid #dbe1e8; border-radius: 8px; padding: 28px; }
	.eyebrow { color: #0f766e; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
	h1 { margin: 8px 0; font-size: 32px; line-height: 1.15; }
	header p:last-child { color: #64748b; max-width: 680px; }
	.empty-state { margin-top: 20px; padding: 28px; border: 1px dashed #b8c3d1; border-radius: 8px; background: #fff; }
	.empty-state h2 { margin: 0 0 8px; font-size: 20px; }
	.empty-state p { color: #64748b; }
	.empty-state span { color: #0f766e; font-size: 13px; }
	.notice { padding: 20px; background: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; }
	.notice button { display: inline-flex; gap: 8px; align-items: center; padding: 8px 12px; border: 1px solid #c2410c; background: white; color: #9a3412; border-radius: 6px; cursor: pointer; }
	.state { color: #64748b; }
	@media (max-width: 640px) { .dataset-detail { padding: 20px 16px 56px; } h1 { font-size: 26px; } }
</style>
