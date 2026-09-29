<script lang="ts">
	import { page } from '$app/stores';
	import { ArrowLeft, CheckCircle2, Clock3, FileText, RefreshCw, TriangleAlert } from '@lucide/svelte';
	import { errorMessage, isHttpStatusError } from '../../../../../_shared/api';
	import {
		confirmDatasetSample,
		actOnDatasetSample,
		fetchDatasetSample,
		fetchDatasetSamples,
		fetchFeedbackDataset,
		updateDatasetSample,
		type DatasetSample,
		type DatasetSampleAction,
		type DatasetSampleDetail,
		type FeedbackDataset,
		type SftRevisionContent
	} from '../../../../../_shared/feedbackDatasets';
	import SftAnnotation from './_components/SftAnnotation.svelte';

	let dataset: FeedbackDataset | null = null;
	let samples: DatasetSample[] = [];
	let selectedSample: DatasetSample | null = null;
	let sampleDetail: DatasetSampleDetail | null = null;
	let loading = true;
	let detailLoading = false;
	let saving = false;
	let confirming = false;
	let acting = false;
	let pendingAction: { key: string; sampleId: string; action: DatasetSampleAction; reason: string } | null = null;
	let error = '';
	let editorError = '';
	let notice = '';
	let loadedDatasetId = '';
	let loadGeneration = 0;

	$: collectionId = $page.params.id ?? '';
	$: datasetId = $page.params.dataset_id ?? '';
	$: pendingCount = samples.filter((item) => item.status === 'needs_confirmation').length;
	$: inputCount = samples.filter((item) => item.status === 'needs_input').length;
	$: confirmedCount = samples.filter((item) => item.status === 'confirmed').length;

	$: if (datasetId && datasetId !== loadedDatasetId) {
		loadedDatasetId = datasetId;
		const generation = ++loadGeneration;
		reset();
		void load(generation);
	}

	function reset() {
		dataset = null;
		samples = [];
		selectedSample = null;
		sampleDetail = null;
		loading = true;
		detailLoading = false;
		saving = false;
		confirming = false;
		acting = false;
		pendingAction = null;
		error = '';
		editorError = '';
		notice = '';
	}

	async function load(generation = loadGeneration) {
		loading = true;
		error = '';
		try {
			const [loadedDataset, response] = await Promise.all([
				fetchFeedbackDataset(datasetId),
				fetchDatasetSamples(datasetId, { limit: 200 })
			]);
			if (generation !== loadGeneration) return;
			dataset = loadedDataset;
			samples = response.items;
			const current = selectedSample
				? samples.find((item) => item.sample_id === selectedSample?.sample_id)
				: undefined;
			const first = current ?? samples.find((item) => item.status === 'needs_confirmation') ?? samples[0];
			if (first) await selectSample(first, generation);
		} catch (err) {
			if (generation === loadGeneration) error = errorMessage(err);
		} finally {
			if (generation === loadGeneration) loading = false;
		}
	}

	async function refresh() {
		const generation = loadGeneration;
		await load(generation);
	}

	async function selectSample(item: DatasetSample, generation = loadGeneration) {
		if (detailLoading && item.sample_id === selectedSample?.sample_id) return;
		selectedSample = item;
		detailLoading = true;
		editorError = '';
		notice = '';
		sampleDetail = null;
		try {
			const detail = await fetchDatasetSample(datasetId, item.sample_id);
			if (generation !== loadGeneration || item.sample_id !== selectedSample?.sample_id) return;
			sampleDetail = detail;
		} catch (err) {
			if (generation === loadGeneration) editorError = errorMessage(err);
		} finally {
			if (generation === loadGeneration) detailLoading = false;
		}
	}

	async function saveSample(event: CustomEvent<{ content: SftRevisionContent }>) {
		if (!sampleDetail?.sample.current_revision_id || saving || confirming || acting) return;
		const generation = loadGeneration;
		saving = true;
		editorError = '';
		notice = '';
		try {
			await updateDatasetSample(datasetId, sampleDetail.sample.sample_id, {
				expected_revision_id: sampleDetail.sample.current_revision_id,
				content: event.detail.content
			});
			await reloadSelected(generation, '修改已保存，请重新确认这个版本。');
		} catch (err) {
			if (generation === loadGeneration) {
				editorError = isHttpStatusError(err, 409)
					? '这个样本已经产生了新版本，请先重新加载再保存。'
					: errorMessage(err);
			}
		} finally {
			if (generation === loadGeneration) saving = false;
		}
	}

	async function confirmSample(event: CustomEvent<{ next: boolean }>) {
		if (!sampleDetail?.sample.current_revision_id || confirming || saving || acting) return;
		const generation = loadGeneration;
		const sampleId = sampleDetail.sample.sample_id;
		const revisionId = sampleDetail.sample.current_revision_id;
		confirming = true;
		editorError = '';
		notice = '';
		try {
			await confirmDatasetSample(datasetId, sampleId, revisionId);
			await load(generation);
			if (event.detail.next && generation === loadGeneration) {
				const next = samples.find(
					(item) => item.sample_id !== sampleId && item.status === 'needs_confirmation'
				);
				if (next) await selectSample(next, generation);
				else notice = '当前队列中的候选都已处理。';
			}
		} catch (err) {
			if (generation === loadGeneration) {
				editorError = isHttpStatusError(err, 409)
					? '这个样本已经产生了新版本，请重新打开后确认。'
					: errorMessage(err);
			}
		} finally {
			if (generation === loadGeneration) confirming = false;
		}
	}

	async function performAction(event: CustomEvent<{ action: DatasetSampleAction; reason?: string }>) {
		if (!sampleDetail || saving || confirming || acting) return;
		const generation = loadGeneration;
		const sampleId = sampleDetail.sample.sample_id;
		const action = event.detail.action;
		const reason = (event.detail.reason ?? '').trim();
		const samePending = pendingAction?.sampleId === sampleId && pendingAction.action === action && pendingAction.reason === reason;
		const key = samePending ? pendingAction!.key : crypto.randomUUID();
		pendingAction = { key, sampleId, action, reason };
		acting = true;
		editorError = '';
		notice = '';
		try {
			await actOnDatasetSample(datasetId, sampleId, {
				action,
				expected_revision_id: sampleDetail.sample.current_revision_id,
				...(reason ? { reason } : {})
			}, key);
			pendingAction = null;
			await reloadSelected(generation, action === 'discard' ? '样本已丢弃，可在队列中恢复。' : action === 'restore' ? '样本已恢复，请重新核对后确认。' : '构建任务已提交。');
		} catch (err) {
			if (generation === loadGeneration) {
				editorError = isHttpStatusError(err, 409)
					? '样本状态已变化，请刷新后再操作。'
					: errorMessage(err);
			}
		} finally {
			if (generation === loadGeneration) acting = false;
		}
	}

	async function reloadSelected(generation: number, message = '') {
		if (!sampleDetail) return;
		const sampleId = sampleDetail.sample.sample_id;
		const [detail, response] = await Promise.all([
			fetchDatasetSample(datasetId, sampleId),
			fetchDatasetSamples(datasetId, { limit: 200 })
		]);
		if (generation !== loadGeneration) return;
		sampleDetail = detail;
		samples = response.items;
		selectedSample = samples.find((item) => item.sample_id === sampleId) ?? selectedSample;
		notice = message;
	}

	function statusLabel(status: string) {
		return (
			{
				pending: '等待构建',
				building: '构建中',
				needs_confirmation: '待确认',
				needs_input: '待补充',
				confirmed: '已确认',
				discarded: '已丢弃',
				build_failed: '构建失败'
			}[status] ?? status
		);
	}

	function formatDate(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}
</script>

<svelte:head>
	<title>{dataset?.name ?? 'SFT 样本'} | Lens</title>
</svelte:head>

<main class="page-shell">
	<header class="page-header">
		<div>
			<a class="back-link" href={`/collections/${encodeURIComponent(collectionId)}/feedback/datasets`}>
				<ArrowLeft size={16} aria-hidden="true" />返回数据集
			</a>
			<div class="eyebrow">文献问答 · SFT</div>
			<h1>{dataset?.name ?? '加载数据集…'}</h1>
			<p class="lede">核对 Worker 生成的候选回答，修改后确认可进入训练数据。</p>
		</div>
		<div class="header-actions">
			{#if dataset}<span class="spec">构建规则 v{dataset.spec_version}</span>{/if}
			<button class="icon-button" type="button" on:click={refresh} disabled={loading} title="刷新样本队列" aria-label="刷新样本队列">
				<span class:spin={loading}><RefreshCw size={17} aria-hidden="true" /></span>
			</button>
		</div>
	</header>

	{#if error}
		<div class="alert alert--error" role="alert"><TriangleAlert size={17} aria-hidden="true" />{error}</div>
	{/if}
	{#if loading}
		<div class="loading" role="status"><span></span><span></span><span></span></div>
	{:else}
		<section class="summary-strip" aria-label="样本状态">
			<div><strong>{samples.length}</strong><span>全部样本</span></div>
			<div class="summary--attention"><strong>{pendingCount}</strong><span>待确认</span></div>
			<div class="summary--input"><strong>{inputCount}</strong><span>待补充</span></div>
			<div class="summary--done"><strong>{confirmedCount}</strong><span>已确认</span></div>
		</section>

		<div class="workbench">
			<aside class="queue" aria-labelledby="queue-title">
				<div class="queue-header">
					<div><div class="eyebrow">样本队列</div><h2 id="queue-title">逐条确认</h2></div>
					<span>{samples.length}</span>
				</div>
				{#if !samples.length}
					<div class="queue-empty"><FileText size={22} aria-hidden="true" /><p>还没有候选样本。</p><small>先从反馈案例收集素材并运行 Worker。</small></div>
				{:else}
					<div class="queue-list">
						{#each samples as item (item.sample_id)}
							<button class:active={selectedSample?.sample_id === item.sample_id} class="queue-item" type="button" on:click={() => selectSample(item)}>
								<span class="queue-icon">
									{#if item.status === 'confirmed'}<CheckCircle2 size={16} aria-hidden="true" />{:else if item.status === 'pending' || item.status === 'building'}<Clock3 size={16} aria-hidden="true" />{:else}<FileText size={16} aria-hidden="true" />{/if}
								</span>
								<span class="queue-copy"><strong>{item.status === 'needs_confirmation' ? '候选回答' : statusLabel(item.status)}</strong><small>更新于 {formatDate(item.updated_at)}</small></span>
								<span class="queue-status queue-status--{item.status}">{statusLabel(item.status)}</span>
							</button>
						{/each}
					</div>
				{/if}
			</aside>

			<section class="editor-area" aria-label="样本编辑器">
				{#if detailLoading}
					<div class="detail-loading" role="status"><span></span><span></span><span></span><p>正在读取样本内容…</p></div>
				{:else if editorError && !sampleDetail}
					<div class="detail-error" role="alert"><TriangleAlert size={22} aria-hidden="true" /><p>{editorError}</p><button type="button" on:click={() => selectedSample && selectSample(selectedSample)}>重新加载</button></div>
				{:else}
					<SftAnnotation sample={sampleDetail} {saving} {confirming} {acting} error={editorError} {notice} on:save={saveSample} on:confirm={confirmSample} on:action={performAction} />
				{/if}
			</section>
		</div>
	{/if}
</main>

<style>
	:global(body) { background: #f4f7fa; }
	:global(button) { font: inherit; }
	.page-shell { max-width: 1480px; margin: 0 auto; padding: 28px 28px 72px; color: #172033; }
	.page-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
	.back-link { display: inline-flex; gap: 7px; align-items: center; color: #526174; font-size: 13px; text-decoration: none; }
	.back-link:hover { color: #0f766e; }
	.eyebrow { color: #0f766e; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
	h1 { margin: 7px 0 5px; font-size: clamp(25px, 3vw, 36px); line-height: 1.15; letter-spacing: 0; }
	.lede { margin: 0; color: #657387; font-size: 14px; }
	.header-actions { display: flex; gap: 12px; align-items: center; }
	.spec { border: 1px solid #d7e0e9; border-radius: 999px; background: #fff; color: #617085; padding: 7px 11px; font-size: 12px; }
	.icon-button { display: inline-grid; place-items: center; width: 36px; height: 36px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: #526174; cursor: pointer; }
	.icon-button:hover:not(:disabled) { border-color: #0f766e; color: #0f766e; }
	.icon-button:disabled { cursor: not-allowed; opacity: .5; }
	.spin { display: inline-flex; }
	.spin :global(svg) { animation: spin 1s linear infinite; }
	.alert { display: flex; gap: 8px; align-items: center; margin-bottom: 18px; border: 1px solid #fecaca; border-radius: 7px; background: #fff1f2; color: #b42318; padding: 11px 13px; font-size: 13px; }
	.summary-strip { display: flex; gap: 1px; margin-bottom: 18px; border: 1px solid #dbe3ec; border-radius: 9px; background: #dbe3ec; overflow: hidden; }
	.summary-strip > div { display: flex; flex: 1; min-width: 110px; flex-direction: column; gap: 2px; background: #fff; padding: 13px 16px; }
	.summary-strip strong { font-size: 21px; line-height: 1; }
	.summary-strip span { color: #718096; font-size: 12px; }
	.summary--attention strong { color: #b45309; }
	.summary--input strong { color: #a16207; }
	.summary--done strong { color: #0f766e; }
	.workbench { display: grid; grid-template-columns: minmax(270px, 330px) minmax(0, 1fr); align-items: start; gap: 18px; }
	.queue { position: sticky; top: 18px; border: 1px solid #dbe3ec; border-radius: 10px; background: #fff; overflow: hidden; }
	.queue-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 18px 18px 15px; border-bottom: 1px solid #e7edf3; }
	.queue-header h2 { margin: 5px 0 0; font-size: 19px; }
	.queue-header > span { min-width: 25px; border-radius: 999px; background: #eef2f6; color: #526174; padding: 4px 8px; text-align: center; font-size: 12px; }
	.queue-list { max-height: calc(100vh - 245px); overflow-y: auto; }
	.queue-item { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 9px; width: 100%; align-items: center; border: 0; border-bottom: 1px solid #eef2f6; background: #fff; color: #243149; padding: 13px 14px; text-align: left; cursor: pointer; }
	.queue-item:hover { background: #f8fafc; }
	.queue-item.active { box-shadow: inset 3px 0 #0f766e; background: #f0fdfa; }
	.queue-icon { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 6px; background: #eef2f6; color: #708096; }
	.queue-item.active .queue-icon { background: #ccfbf1; color: #0f766e; }
	.queue-copy { display: grid; min-width: 0; gap: 4px; }
	.queue-copy strong { overflow: hidden; color: #27344a; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
	.queue-copy small { color: #8793a3; font-size: 11px; }
	.queue-status { border-radius: 999px; padding: 4px 7px; color: #64748b; background: #f1f5f9; font-size: 10px; white-space: nowrap; }
	.queue-status--needs_confirmation { color: #9a5b00; background: #fff7ed; }
	.queue-status--confirmed { color: #0f766e; background: #f0fdfa; }
	.queue-status--needs_input { color: #9a6700; background: #fefce8; }
	.queue-empty { display: grid; justify-items: center; padding: 40px 20px; color: #708096; text-align: center; }
	.queue-empty p { margin: 12px 0 4px; color: #344257; font-size: 14px; font-weight: 700; }
	.queue-empty small { line-height: 1.55; }
	.editor-area { min-width: 0; }
	.detail-loading { display: grid; justify-items: center; gap: 11px; padding: 90px 24px; border: 1px solid #dbe3ec; border-radius: 10px; background: #fff; color: #64748b; }
	.detail-loading span, .loading span { display: block; width: 72%; height: 10px; border-radius: 99px; background: #e7edf3; animation: pulse 1.2s ease-in-out infinite; }
	.detail-loading span:nth-child(2), .loading span:nth-child(2) { width: 52%; animation-delay: .15s; }
	.detail-loading span:nth-child(3), .loading span:nth-child(3) { width: 64%; animation-delay: .3s; }
	.detail-loading p { margin: 5px 0 0; font-size: 13px; }
	.detail-error { display: grid; justify-items: center; gap: 10px; padding: 72px 24px; border: 1px solid #fecaca; border-radius: 10px; background: #fff; color: #b42318; text-align: center; }
	.detail-error p { margin: 0; color: #7f1d1d; }
	.detail-error button { border: 1px solid #b42318; border-radius: 6px; background: #fff; color: #b42318; padding: 8px 12px; cursor: pointer; }
	.loading { display: grid; justify-items: center; gap: 12px; padding: 60px; border: 1px solid #dbe3ec; border-radius: 10px; background: #fff; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
	@media (max-width: 900px) { .page-shell { padding: 22px 17px 56px; } .workbench { grid-template-columns: 1fr; } .queue { position: static; } .queue-list { display: flex; max-height: none; overflow-x: auto; } .queue-item { min-width: 245px; border-right: 1px solid #eef2f6; border-bottom: 0; } }
	@media (max-width: 560px) { .page-header { display: block; } .header-actions { justify-content: space-between; margin-top: 15px; } .summary-strip { display: grid; grid-template-columns: repeat(2, 1fr); } .summary-strip > div { min-width: 0; } .queue-list { display: grid; } .queue-item { min-width: 0; border-right: 0; border-bottom: 1px solid #eef2f6; } }
</style>
