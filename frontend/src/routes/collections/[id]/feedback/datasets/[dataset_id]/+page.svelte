<script lang="ts">
	import { page } from '$app/stores';
	import {
		ArrowLeft,
		CheckCircle2,
		Clock3,
		Download,
		FileJson,
		FileText,
		RefreshCw,
		ShieldCheck,
		TriangleAlert
	} from '@lucide/svelte';
	import { errorMessage, isHttpStatusError } from '../../../../../_shared/api';
	import {
		confirmDatasetSample,
		actOnDatasetSample,
		downloadFeedbackDatasetExport,
		fetchFeedbackDatasetExports,
		fetchDatasetSample,
		fetchDatasetSamples,
		fetchFeedbackDataset,
		previewFeedbackDatasetExport,
		publishFeedbackDatasetExport,
		updateDatasetSample,
		type DatasetSample,
		type DatasetSampleAction,
		type DatasetSampleDetail,
		type DatasetExportPreview,
		type DatasetExportSummary,
		type FeedbackDataset,
		type RevisionContent
	} from '../../../../../_shared/feedbackDatasets';
	import SftAnnotation from './_components/SftAnnotation.svelte';
	import PreferenceAnnotation from './_components/PreferenceAnnotation.svelte';
	import EvaluationAnnotation from './_components/EvaluationAnnotation.svelte';

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
	let exportPreview: DatasetExportPreview | null = null;
	let exportItems: DatasetExportSummary[] = [];
	let exportLoading = false;
	let exportPublishing = false;
	let exportError = '';
	let exportNotice = '';
	let allowPartialExport = false;
	let downloadingExport = '';
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
		exportPreview = null;
		exportItems = [];
		exportLoading = false;
		exportPublishing = false;
		exportError = '';
		exportNotice = '';
		allowPartialExport = false;
		downloadingExport = '';
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
			try {
				const exports = await fetchFeedbackDatasetExports(datasetId, { limit: 50 });
				if (generation === loadGeneration) exportItems = exports.items;
			} catch {
				// The sample editor remains usable when an older API has no export history yet.
				exportItems = [];
			}
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

	async function runExportPreview() {
		if (exportLoading || exportPublishing || confirmedCount === 0) return;
		exportLoading = true;
		exportError = '';
		exportNotice = '';
		allowPartialExport = false;
		try {
			exportPreview = await previewFeedbackDatasetExport(datasetId);
			if (exportPreview.issues.length === 0) {
				exportNotice = '预检完成，所有已确认样本都可以导出。';
			}
		} catch (err) {
			exportError = errorMessage(err);
			exportPreview = null;
		} finally {
			exportLoading = false;
		}
	}

	async function publishExport() {
		if (!exportPreview || exportPublishing || exportPreview.exportable_count === 0) return;
		if (exportPreview.issues.length > 0 && !allowPartialExport) return;
		exportPublishing = true;
		exportError = '';
		exportNotice = '';
		try {
			const published = await publishFeedbackDatasetExport(
				datasetId,
				{
					preview_id: exportPreview.preview_id,
					preview_digest: exportPreview.preview_digest,
					allow_partial: allowPartialExport
				},
				crypto.randomUUID()
			);
			exportItems = [published, ...exportItems.filter((item) => item.export_id !== published.export_id)];
			exportNotice = `已发布 ${published.row_count} 条训练样本。可以按需下载主文件或追溯包。`;
			exportPreview = null;
			allowPartialExport = false;
		} catch (err) {
			exportError = errorMessage(err);
		} finally {
			exportPublishing = false;
		}
	}

	async function downloadExport(item: DatasetExportSummary, format: 'jsonl' | 'json' | 'provenance') {
		const key = `${item.export_id}:${format}`;
		if (downloadingExport) return;
		downloadingExport = key;
		exportError = '';
		try {
			await downloadFeedbackDatasetExport(datasetId, item, format);
		} catch (err) {
			exportError = errorMessage(err);
		} finally {
			downloadingExport = '';
		}
	}

	async function openExportSample(sampleId: string) {
		const item = samples.find((candidate) => candidate.sample_id === sampleId);
		if (!item) return;
		await selectSample(item);
		if (typeof document !== 'undefined') {
			document.querySelector('.editor-area')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
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

	async function saveSample(event: CustomEvent<{ content: RevisionContent }>) {
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

	function taskLabel(taskType: FeedbackDataset['task_type'] | undefined) {
		return {
			sft: '文献问答 · SFT',
			preference: '回答偏好',
			evaluation: '评测'
		}[taskType ?? 'sft'];
	}

	function previewRowSummary(row: DatasetExportPreview['sample_rows'][number]) {
		if (dataset?.task_type === 'preference') {
			return `A：${row.response_a_preview || '无'} · B：${row.response_b_preview || '无'} · 选择：${row.human_preference ?? '未选择'} · 证据 ${row.evidence_count} 段`;
		}
		if (dataset?.task_type === 'evaluation') {
			return `参考：${row.reference_preview || '无'} · 证据 ${row.evidence_count} 段`;
		}
		return `回答：${row.target_preview || '无'} · 证据 ${row.evidence_count} 段`;
	}
</script>

<svelte:head>
	<title>{dataset?.name ?? '任务数据集'} | Lens</title>
</svelte:head>

<main class="page-shell">
	<header class="page-header">
		<div>
			<a class="back-link" href={`/collections/${encodeURIComponent(collectionId)}/feedback/datasets`}>
				<ArrowLeft size={16} aria-hidden="true" />返回数据集
			</a>
			<div class="eyebrow">{taskLabel(dataset?.task_type)}</div>
			<h1>{dataset?.name ?? '加载数据集…'}</h1>
			<p class="lede">核对 Worker 生成的候选内容，按任务类型修改后确认。</p>
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

			<section class="export-panel" aria-labelledby="export-title">
				<div class="export-heading">
					<div>
						<div class="eyebrow">交付训练文件</div>
						<h2 id="export-title">导出已确认样本</h2>
						<p>先检查当前确认版本，再发布一个不可变导出。主文件只放模型可读内容，追溯信息单独下载。</p>
					</div>
					<div class="export-heading-meta">
						<span class="export-count"><ShieldCheck size={15} aria-hidden="true" />{confirmedCount} 条已确认</span>
						<button class="secondary-button" type="button" on:click={runExportPreview} disabled={exportLoading || exportPublishing || confirmedCount === 0}>
							<FileJson size={16} aria-hidden="true" />{exportLoading ? '正在检查…' : '检查导出'}
						</button>
					</div>
				</div>

				{#if exportError}
					<div class="export-alert export-alert--error" role="alert"><TriangleAlert size={16} aria-hidden="true" />{exportError}</div>
				{/if}
				{#if exportNotice}
					<div class="export-alert export-alert--success" role="status"><CheckCircle2 size={16} aria-hidden="true" />{exportNotice}</div>
				{/if}

				{#if exportPreview}
					<div class="export-preview">
						<div class="export-metrics" aria-label="导出预检摘要">
							<div><strong>{exportPreview.requested_count}</strong><span>确认集合</span></div>
							<div class="metric--ready"><strong>{exportPreview.exportable_count}</strong><span>可导出</span></div>
							<div class:metric--warning={exportPreview.issues.length > 0}><strong>{exportPreview.issues.length}</strong><span>需要处理的问题</span></div>
						</div>

						{#if exportPreview.issues.length > 0}
							<div class="export-issues">
								<div class="export-subheading"><strong>有样本还不能进入文件</strong><span>先打开样本修正；也可以明确同意只发布其余可用样本。</span></div>
								{#each exportPreview.issues as issue (issue.sample_id + issue.code)}
									<div class="export-issue">
										<div><strong>{issue.question || '未能读取问题摘要'}</strong><span>{issue.message}</span></div>
										<button class="link-button" type="button" on:click={() => openExportSample(issue.sample_id)}>打开样本</button>
									</div>
								{/each}
								<label class="partial-choice">
									<input type="checkbox" bind:checked={allowPartialExport} />
									<span><strong>我确认只发布可用样本</strong><small>问题样本会留在队列中，修正后可以发布新的版本。</small></span>
								</label>
							</div>
						{:else}
							<div class="export-ready"><CheckCircle2 size={18} aria-hidden="true" /><div><strong>全部样本通过预检</strong><span>问题、可读文献片段和追溯关系都已准备好。</span></div></div>
						{/if}

						<div class="preview-rows">
							<div class="export-subheading"><strong>文件内容预览</strong><span>展示前几条模型输入，完整内容会写入发布文件。</span></div>
							{#each exportPreview.sample_rows.slice(0, 5) as row (row.sample_id)}
								<div class="preview-row">
									<div><strong>{row.question || '未命名问题'}</strong><span>{previewRowSummary(row)}</span></div>
									<button class="link-button" type="button" on:click={() => openExportSample(row.sample_id)}>查看</button>
								</div>
							{/each}
						</div>
						<div class="export-footer">
							<small>预检有效期至 {new Date(exportPreview.expires_at).toLocaleTimeString()}</small>
							<button class="primary-button primary-button--compact" type="button" on:click={publishExport} disabled={exportPublishing || exportPreview.exportable_count === 0 || (exportPreview.issues.length > 0 && !allowPartialExport)}>
								<Download size={16} aria-hidden="true" />{exportPublishing ? '正在发布…' : `发布 ${exportPreview.exportable_count} 条`}
							</button>
						</div>
					</div>
				{:else if confirmedCount === 0}
					<div class="export-empty"><FileJson size={20} aria-hidden="true" /><div><strong>还没有可发布的样本</strong><span>先在上方队列中确认至少一个 Worker 候选。</span></div></div>
				{:else}
					<div class="export-empty export-empty--neutral"><FileJson size={20} aria-hidden="true" /><div><strong>导出前先做一次预检</strong><span>服务器会重新读取确认版本，避免页面中的旧内容被发布。</span></div></div>
				{/if}

				{#if exportItems.length}
					<div class="export-history">
						<div class="export-subheading"><strong>已发布版本</strong><span>已发布文件不会随当前样本修改而变化。</span></div>
						{#each exportItems as item (item.export_id)}
							<div class="export-history-row">
								<div><strong>版本 {item.export_no}</strong><span>{item.row_count} 条 · {formatDate(item.created_at)}</span></div>
								<div class="download-actions">
									<button class="download-button" type="button" on:click={() => downloadExport(item, 'jsonl')} disabled={downloadingExport !== ''}><Download size={14} aria-hidden="true" />JSONL</button>
									<button class="download-button" type="button" on:click={() => downloadExport(item, 'json')} disabled={downloadingExport !== ''}><Download size={14} aria-hidden="true" />JSON</button>
									<button class="download-button download-button--quiet" type="button" on:click={() => downloadExport(item, 'provenance')} disabled={downloadingExport !== ''}><Download size={14} aria-hidden="true" />追溯包</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
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
						{#if dataset?.task_type === 'preference'}
							<PreferenceAnnotation sample={sampleDetail} {saving} {confirming} {acting} error={editorError} {notice} on:save={saveSample} on:confirm={confirmSample} on:action={performAction} />
						{:else if dataset?.task_type === 'evaluation'}
							<EvaluationAnnotation sample={sampleDetail} {saving} {confirming} {acting} error={editorError} {notice} on:save={saveSample} on:confirm={confirmSample} on:action={performAction} />
						{:else}
							<SftAnnotation sample={sampleDetail} {saving} {confirming} {acting} error={editorError} {notice} on:save={saveSample} on:confirm={confirmSample} on:action={performAction} />
						{/if}
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
	.export-panel { margin-bottom: 18px; border: 1px solid #cbdedb; border-radius: 10px; background: #fff; overflow: hidden; }
	.export-heading { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; padding: 20px 22px 18px; border-bottom: 1px solid #e4eeec; background: #f7fbfa; }
	.export-heading h2 { margin: 5px 0 5px; font-size: 19px; }
	.export-heading p { max-width: 760px; margin: 0; color: #64748b; font-size: 13px; line-height: 1.6; }
	.export-heading-meta { display: flex; flex: 0 0 auto; gap: 12px; align-items: center; }
	.export-count { display: inline-flex; gap: 6px; align-items: center; color: #0f766e; font-size: 12px; font-weight: 700; white-space: nowrap; }
	.secondary-button, .primary-button--compact { display: inline-flex; gap: 7px; align-items: center; justify-content: center; border-radius: 6px; padding: 9px 13px; font-size: 13px; font-weight: 700; cursor: pointer; }
	.secondary-button { border: 1px solid #0f766e; background: #fff; color: #0f766e; }
	.secondary-button:hover:not(:disabled) { background: #f0fdfa; }
	.secondary-button:disabled, .primary-button--compact:disabled, .download-button:disabled { cursor: not-allowed; opacity: .48; }
	.export-alert { display: flex; gap: 8px; align-items: center; margin: 14px 22px 0; border-radius: 6px; padding: 10px 12px; font-size: 13px; }
	.export-alert--error { border: 1px solid #fecaca; background: #fff1f2; color: #b42318; }
	.export-alert--success { border: 1px solid #b7e4d9; background: #f0fdfa; color: #0f766e; }
	.export-preview { padding: 18px 22px 20px; }
	.export-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin-bottom: 18px; border: 1px solid #dbe3ec; border-radius: 7px; background: #dbe3ec; overflow: hidden; }
	.export-metrics > div { display: grid; gap: 4px; background: #fff; padding: 11px 13px; }
	.export-metrics strong { font-size: 21px; line-height: 1; }
	.export-metrics span { color: #718096; font-size: 11px; }
	.metric--ready strong { color: #0f766e; }
	.metric--warning strong { color: #b45309; }
	.export-subheading { display: flex; justify-content: space-between; gap: 14px; align-items: baseline; margin-bottom: 9px; }
	.export-subheading strong { color: #29364a; font-size: 13px; }
	.export-subheading span { color: #8793a3; font-size: 11px; }
	.export-issues { margin-bottom: 18px; border: 1px solid #fed7aa; border-radius: 7px; background: #fffaf5; padding: 13px 14px; }
	.export-issue, .preview-row, .export-history-row { display: flex; justify-content: space-between; gap: 14px; align-items: center; border-top: 1px solid #f0e5da; padding: 10px 0; }
	.export-issue:first-of-type, .preview-row:first-of-type, .export-history-row:first-of-type { border-top: 0; }
	.export-issue > div, .preview-row > div, .export-history-row > div { display: grid; min-width: 0; gap: 3px; }
	.export-issue strong, .preview-row strong, .export-history-row strong { overflow: hidden; color: #38465a; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
	.export-issue span, .preview-row span, .export-history-row span { color: #7c6c5c; font-size: 11px; }
	.link-button { flex: 0 0 auto; border: 0; background: transparent; color: #0f766e; padding: 4px 0; font-size: 12px; font-weight: 700; cursor: pointer; }
	.link-button:hover { color: #115e59; text-decoration: underline; }
	.partial-choice { display: flex; gap: 9px; align-items: flex-start; margin-top: 11px; border-top: 1px solid #f0e5da; padding-top: 12px; color: #704f21; cursor: pointer; }
	.partial-choice input { width: 16px; height: 16px; margin-top: 1px; accent-color: #0f766e; }
	.partial-choice span { display: grid; gap: 3px; }
	.partial-choice strong { font-size: 12px; }
	.partial-choice small { color: #8b7356; font-size: 11px; line-height: 1.45; }
	.export-ready, .export-empty { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 17px; border: 1px solid #b7e4d9; border-radius: 7px; background: #f0fdfa; color: #0f766e; padding: 12px 13px; }
	.export-ready > div, .export-empty > div { display: grid; gap: 3px; }
	.export-ready strong, .export-empty strong { color: #155e55; font-size: 13px; }
	.export-ready span, .export-empty span { color: #52756f; font-size: 11px; }
	.export-empty { margin: 18px 22px 20px; border-color: #dbe3ec; background: #f8fafc; color: #64748b; }
	.export-empty--neutral { margin: 0; }
	.export-empty--neutral strong { color: #344257; }
	.export-empty--neutral span { color: #718096; }
	.preview-rows { margin-bottom: 17px; }
	.preview-row { border-color: #eef2f6; }
	.preview-row > div { max-width: 80%; }
	.preview-row span { color: #718096; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.export-footer { display: flex; justify-content: space-between; gap: 14px; align-items: center; border-top: 1px solid #e7edf3; padding-top: 15px; }
	.export-footer small { color: #8793a3; font-size: 11px; }
	.primary-button--compact { border: 1px solid #0f766e; background: #0f766e; color: #fff; }
	.primary-button--compact:hover:not(:disabled) { background: #115e59; }
	.export-history { border-top: 1px solid #e7edf3; margin: 0 22px; padding: 17px 0 2px; }
	.export-history-row { border-color: #eef2f6; }
	.download-actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
	.download-button { display: inline-flex; gap: 5px; align-items: center; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; color: #526174; padding: 6px 8px; font-size: 11px; font-weight: 700; cursor: pointer; }
	.download-button:hover:not(:disabled) { border-color: #0f766e; color: #0f766e; }
	.download-button--quiet { border-color: #dbe3ec; color: #718096; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
	@media (max-width: 900px) { .page-shell { padding: 22px 17px 56px; } .workbench { grid-template-columns: 1fr; } .queue { position: static; } .queue-list { display: flex; max-height: none; overflow-x: auto; } .queue-item { min-width: 245px; border-right: 1px solid #eef2f6; border-bottom: 0; } }
	@media (max-width: 760px) { .export-heading { display: block; } .export-heading-meta { justify-content: space-between; margin-top: 14px; } .export-subheading { display: block; } .export-subheading span { display: block; margin-top: 3px; } .export-footer { align-items: flex-start; flex-direction: column; } .export-history-row { align-items: flex-start; flex-direction: column; } .download-actions { justify-content: flex-start; } }
	@media (max-width: 560px) { .page-header { display: block; } .header-actions { justify-content: space-between; margin-top: 15px; } .summary-strip { display: grid; grid-template-columns: repeat(2, 1fr); } .summary-strip > div { min-width: 0; } .queue-list { display: grid; } .queue-item { min-width: 0; border-right: 0; border-bottom: 1px solid #eef2f6; } .export-heading, .export-preview { padding-left: 16px; padding-right: 16px; } .export-history { margin-left: 16px; margin-right: 16px; } .export-metrics strong { font-size: 18px; } .export-issue, .preview-row { align-items: flex-start; flex-direction: column; gap: 6px; } .preview-row > div { max-width: 100%; } }
</style>
