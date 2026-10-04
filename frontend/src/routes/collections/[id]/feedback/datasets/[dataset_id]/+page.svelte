<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		CheckCircle2,
		LayoutGrid,
		MessageCircle,
		Download,
		FileJson,
		FileText,
		Search,
		RefreshCw,
		ShieldCheck,
		TriangleAlert
	} from '@lucide/svelte';
	import { errorMessage, isHttpStatusError } from '../../../../../_shared/api';
	import { t } from '../../../../../_shared/i18n';
	import {
		confirmDatasetSample,
		actOnDatasetSample,
		downloadFeedbackDatasetExport,
		fetchFeedbackDatasetExports,
		fetchFeedbackDatasets,
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
		type DatasetExportFormat,
		type FeedbackDataset,
		type FeedbackDatasetTaskType,
		type RevisionContent
	} from '../../../../../_shared/feedbackDatasets';
	import SftAnnotation from './_components/SftAnnotation.svelte';
	import PreferenceAnnotation from './_components/PreferenceAnnotation.svelte';
	import EvaluationAnnotation from './_components/EvaluationAnnotation.svelte';

	let dataset: FeedbackDataset | null = null;
	let relatedDatasets: FeedbackDataset[] = [];
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
	let chosenExports: string[] = [];
	let polling = false;
	let caseQuestions: Record<string, string> = {};
	let statusFilter = 'all';
	let searchQuery = '';
	let exportPanel: HTMLDetailsElement;

	async function readSamples() {
		const requestedDatasetId = datasetId;
		const items: DatasetSample[] = [];
		let response;
		do {
			response = await fetchDatasetSamples(requestedDatasetId, { limit: 200, offset: items.length });
			items.push(...response.items);
		} while (response.items.length === 200 && items.length < response.total);
		return { items };
	}

	async function hydrateQueueQuestions(items: DatasetSample[], generation: number) {
		const candidates = items.filter((item) => !caseQuestions[item.source_case_id]).slice(0, 30);
		if (!candidates.length) return;
		const updates = await Promise.all(candidates.map(async (item) => {
			try {
				const detail = await fetchDatasetSample(datasetId, item.sample_id);
				return [item.source_case_id, detail.source_case.question] as const;
			} catch {
				return null;
			}
		}));
		if (generation !== loadGeneration) return;
		const next = Object.fromEntries(updates.filter((entry): entry is readonly [string, string] => Boolean(entry)));
		if (Object.keys(next).length) caseQuestions = { ...caseQuestions, ...next };
	}
	$: exportSelection = chosenExports.filter((id) => samples.some((item) => item.sample_id === id && item.status === 'confirmed'));

	onMount(() => {
		const timer = setInterval(() => { void pollBuilds(); }, 2500);
		return () => clearInterval(timer);
	});

	async function pollBuilds() {
		if (polling || loading || !samples.some((item) => ['pending', 'building'].includes(item.status))) return;
		polling = true;
		const generation = loadGeneration;
		try {
			const response = await readSamples();
			if (generation !== loadGeneration) return;
			samples = response.items;
			void hydrateQueueQuestions(samples, generation);
			const updated = samples.find((item) => item.sample_id === selectedSample?.sample_id);
			if (updated && ['pending', 'building'].includes(selectedSample?.status ?? '') && updated.status !== selectedSample?.status) await selectSample(updated, generation);
		} catch (err) { if (generation === loadGeneration) error = errorMessage(err); }
		finally { polling = false; }
	}

	$: collectionId = $page.params.id ?? '';
	$: datasetId = $page.params.dataset_id ?? '';
	$: pendingCount = samples.filter((item) => item.status === 'needs_confirmation').length;
	$: inputCount = samples.filter((item) => item.status === 'needs_input').length;
	$: confirmedCount = samples.filter((item) => item.status === 'confirmed').length;
	$: failedCount = samples.filter((item) => item.status === 'build_failed').length;
	$: filteredSamples = samples.filter((item) => {
		const statusMatches = statusFilter === 'all' || item.status === statusFilter;
		const query = searchQuery.trim().toLowerCase();
		const question = (caseQuestions[item.source_case_id] ?? '').toLowerCase();
		return statusMatches && (!query || question.includes(query));
	});
	$: currentTaskType = dataset?.task_type ?? 'sft';
	$: taskTabs = (['sft', 'preference', 'evaluation'] as FeedbackDatasetTaskType[]).map((taskType) => ({
		taskType,
		label: taskLabel(taskType),
		dataset: relatedDatasets.find((item) => item.task_type === taskType && item.construction_spec?.mode === 'automatic_feedback_workbench')
	}));

	$: if (datasetId && datasetId !== loadedDatasetId) {
		loadedDatasetId = datasetId;
		const generation = ++loadGeneration;
		reset();
		void load(generation);
	}

	function reset() {
		caseQuestions = {};
		chosenExports = [];
		dataset = null;
		relatedDatasets = [];
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
		statusFilter = 'all';
		searchQuery = '';
	}

	async function load(generation = loadGeneration) {
		loading = true;
		error = '';
		try {
			const [loadedDataset, response] = await Promise.all([
				fetchFeedbackDataset(datasetId),
				readSamples()
			]);
			if (generation !== loadGeneration) return;
			dataset = loadedDataset;
			samples = response.items;
			void hydrateQueueQuestions(samples, generation);
			try {
				const related = await fetchFeedbackDatasets(collectionId, { limit: 200 });
				if (generation === loadGeneration) relatedDatasets = Array.isArray(related.items) ? related.items : [];
			} catch {
				// Older deployments may not expose the collection dataset listing here.
				relatedDatasets = [];
			}
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
		if (exportLoading || exportPublishing || exportSelection.length === 0) return;
		exportLoading = true;
		exportError = '';
		exportNotice = '';
		allowPartialExport = false;
		try {
			exportPreview = await previewFeedbackDatasetExport(datasetId, exportSelection);
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

	async function downloadExport(item: DatasetExportSummary, format: DatasetExportFormat) {
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
			caseQuestions = { ...caseQuestions, [item.source_case_id]: detail.source_case.question };
		} catch (err) {
			if (generation === loadGeneration) editorError = errorMessage(err);
		} finally {
			if (generation === loadGeneration) detailLoading = false;
		}
	}

	async function saveSample(event: CustomEvent<{ content: RevisionContent }>) {
		if (!sampleDetail || saving || confirming || acting) return;
		const generation = loadGeneration;
		saving = true;
		editorError = '';
		notice = '';
		try {
			await updateDatasetSample(datasetId, sampleDetail.sample.sample_id, {
				expected_revision_id: sampleDetail.sample.current_revision_id,
				expected_generation: sampleDetail.sample.generation,
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

	async function confirmSample(event: CustomEvent<{ next: boolean; content?: RevisionContent }>) {
		if (!sampleDetail?.sample.current_revision_id || confirming || saving || acting) return;
		const generation = loadGeneration;
		const requestedDatasetId = datasetId;
		const sampleId = sampleDetail.sample.sample_id;
		let revisionId = sampleDetail.sample.current_revision_id;
		confirming = true;
		editorError = '';
		notice = '';
		try {
			if (event.detail.content) {
				const saved = await updateDatasetSample(requestedDatasetId, sampleId, {
					expected_revision_id: revisionId,
					expected_generation: sampleDetail.sample.generation,
					content: event.detail.content
				});
				if (!saved.current_revision_id) throw new Error('sample_current_revision_missing');
				revisionId = saved.current_revision_id;
				if (generation !== loadGeneration || selectedSample?.sample_id !== sampleId) return;
				await reloadSelected(generation);
				if (generation !== loadGeneration || selectedSample?.sample_id !== sampleId) return;
			}
			await confirmDatasetSample(requestedDatasetId, sampleId, revisionId);
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
			readSamples()
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

	function openTask(taskType: FeedbackDatasetTaskType) {
		const target = taskTabs.find((item) => item.taskType === taskType)?.dataset;
		if (!target || target.dataset_id === datasetId) return;
		void goto(resolve('/collections/[id]/feedback/datasets/[dataset_id]', {
			id: collectionId,
			dataset_id: target.dataset_id
		}));
	}

	function openFullExport() {
		chosenExports = samples.filter((item) => item.status === 'confirmed').map((item) => item.sample_id);
		exportPreview = null;
		if (exportPanel) {
			exportPanel.open = true;
			exportPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
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
	<title>{taskLabel(dataset?.task_type) || '反馈任务工作台'} | Lens</title>
</svelte:head>

<main class="page-shell">
	<header class="page-header">
		<div>
			<h1>{taskLabel(dataset?.task_type) || '加载工作台…'}</h1>
			<p class="page-subtitle">逐条核对候选回答，确认后再交付训练文件</p>
		</div>
		<div class="header-actions">
			<button class="toolbar-button toolbar-button--icon" type="button" on:click={refresh} disabled={loading} title="刷新样本队列" aria-label="刷新样本队列">
				<span class:spin={loading}><RefreshCw size={17} aria-hidden="true" /></span>
			</button>
			<button class="toolbar-button" type="button" on:click={openFullExport} disabled={confirmedCount === 0} title="导出全部已确认样本">
				<Download size={16} aria-hidden="true" /><span class="export-label">导出全部已确认</span><span class="toolbar-count">{confirmedCount}</span>
			</button>
		</div>
	</header>

	{#if error}
		<div class="alert alert--error" role="alert"><TriangleAlert size={17} aria-hidden="true" />{error}</div>
	{/if}
	{#if loading}
		<div class="loading" role="status"><span></span><span></span><span></span></div>
	{:else}
			<nav class="task-tabs" aria-label="反馈任务类型">
				{#each taskTabs as tab (tab.taskType)}
					<button class:active={tab.taskType === currentTaskType} class="task-tab" type="button" on:click={() => openTask(tab.taskType)} disabled={!tab.dataset || tab.taskType === currentTaskType} aria-current={tab.taskType === currentTaskType ? 'page' : undefined}>
						{#if tab.taskType === 'sft'}<MessageCircle size={16} aria-hidden="true" />{:else if tab.taskType === 'preference'}<LayoutGrid size={16} aria-hidden="true" />{:else}<CheckCircle2 size={16} aria-hidden="true" />{/if}
						<span>{tab.label}</span>
					</button>
				{/each}
			</nav>

			<section class="workbench-toolbar" aria-label="样本筛选">
				<div class="status-tabs" role="tablist" aria-label="样本状态">
					<button class:active={statusFilter === 'all'} type="button" role="tab" aria-selected={statusFilter === 'all'} on:click={() => statusFilter = 'all'}>全部 <span>{samples.length}</span></button>
					<button class:active={statusFilter === 'needs_confirmation'} type="button" role="tab" aria-selected={statusFilter === 'needs_confirmation'} on:click={() => statusFilter = 'needs_confirmation'}>待确认 <span>{pendingCount}</span></button>
					<button class:active={statusFilter === 'needs_input'} type="button" role="tab" aria-selected={statusFilter === 'needs_input'} on:click={() => statusFilter = 'needs_input'}>待补充 <span>{inputCount}</span></button>
					<button class:active={statusFilter === 'build_failed'} type="button" role="tab" aria-selected={statusFilter === 'build_failed'} on:click={() => statusFilter = 'build_failed'}>构建失败 <span>{failedCount}</span></button>
					<button class:active={statusFilter === 'confirmed'} type="button" role="tab" aria-selected={statusFilter === 'confirmed'} on:click={() => statusFilter = 'confirmed'}>已确认 <span>{confirmedCount}</span></button>
				</div>
				<label class="search-field" aria-label="搜索问题">
					<Search size={16} aria-hidden="true" />
					<input type="search" bind:value={searchQuery} placeholder="搜索问题" />
				</label>
			</section>

			<details class="export-panel" bind:this={exportPanel}>
				<summary>{$t('taskDatasets.exportTitle')} · {confirmedCount}</summary>
				<div class="export-heading">
					<div>
						<div class="eyebrow">交付训练文件</div>
						<h2 id="export-title">导出已确认样本</h2>
						<p>{$t('taskDatasets.selected', { count: exportSelection.length })}</p>
					</div>
					<div class="export-heading-meta">
						<span class="export-count"><ShieldCheck size={15} aria-hidden="true" />{confirmedCount} 条已确认</span>
						<span>{$t('taskDatasets.selected', { count: exportSelection.length })}</span>
						<button class="secondary-button" type="button" on:click={openFullExport} disabled={confirmedCount === 0}>{$t('taskDatasets.selectAll')}</button>
						<button class="secondary-button" type="button" on:click={runExportPreview} disabled={exportLoading || exportPublishing || exportSelection.length === 0}>
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
									<button class="download-button download-button--quiet" type="button" on:click={() => downloadExport(item, 'manifest')} disabled={downloadingExport !== ''}><Download size={14} aria-hidden="true" />清单</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</details>

			<div class="workbench">
			<aside class="queue" aria-labelledby="queue-title">
				<div class="queue-header">
					<div><div class="eyebrow">样本队列</div><h2 id="queue-title">逐条确认</h2></div>
					<span>{samples.length}</span>
				</div>
				{#if !samples.length}
					<div class="queue-empty"><FileText size={22} aria-hidden="true" /><p>还没有候选样本。</p><small>后台 Worker 会持续整理当前 Collection 的反馈案例。</small></div>
				{:else if !filteredSamples.length}
					<div class="queue-empty"><Search size={22} aria-hidden="true" /><p>没有匹配的样本。</p><small>调整状态筛选或搜索关键词后再试。</small></div>
				{:else}
					<div class="queue-list">
						{#each filteredSamples as item (item.sample_id)}
							<div class="queue-row">
								{#if item.status === 'confirmed'}<input type="checkbox" aria-label={$t('taskDatasets.selectExport')} value={item.sample_id} bind:group={chosenExports} on:change={() => exportPreview = null} />{/if}
							<button class:active={selectedSample?.sample_id === item.sample_id} class="queue-item" type="button" on:click={() => selectSample(item)}>
								<span class="queue-copy"><strong title={caseQuestions[item.source_case_id]}>{caseQuestions[item.source_case_id] || statusLabel(item.status)}</strong><small>更新于 {formatDate(item.updated_at)}</small></span>
								<span class="queue-status queue-status--{item.status}">{statusLabel(item.status)}</span>
							</button>
							</div>
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
	.export-panel > summary { cursor: pointer; font-size: 14px; font-weight: 700; color: var(--brand-primary); padding: 12px 16px; }
	.queue-row { display: flex; align-items: center; }
	.queue-row > input { flex: 0 0 auto; margin-left: 12px; }
	.queue-row .queue-item { flex: 1; min-width: 0; }
	:global(button) { font: inherit; }
	.page-shell { display: flex; flex-direction: column; width: 100%; box-sizing: border-box; margin: 0; background: var(--bg-page); color: var(--text-primary); font-size: 13px; }
	.page-header { display: flex; justify-content: space-between; gap: 24px; align-items: center; padding: 24px 32px 20px; }
	.eyebrow { color: var(--brand-primary); font-size: 11px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; }
	h1 { margin: 0 0 4px; font-size: 24px; line-height: 1.3; letter-spacing: 0; }
	.page-subtitle { margin: 0; color: var(--text-secondary); font-size: 13px; }
	.header-actions { display: flex; gap: 8px; align-items: center; }
	.toolbar-button { display: inline-flex; gap: 8px; align-items: center; justify-content: center; min-height: 36px; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--surface-card); color: var(--text-primary); padding: 0 12px; font-size: 12px; font-weight: 500; text-decoration: none; cursor: pointer; }
	.toolbar-button:hover:not(:disabled) { border-color: var(--brand-primary); color: var(--brand-primary); }
	.toolbar-button--icon { width: 36px; padding: 0; }
	.toolbar-button:disabled { cursor: not-allowed; opacity: .5; }
	.toolbar-count { min-width: 20px; border-radius: 3px; background: var(--success-bg); color: var(--success-text); padding: 2px 5px; text-align: center; font-size: 10px; }
	.spin { display: inline-flex; }
	.spin :global(svg) { animation: spin 1s linear infinite; }
	.task-tabs { display: flex; gap: 2px; margin: 0 32px; padding: 3px; border-radius: 6px; background: var(--border-default); overflow-x: auto; }
	.task-tab { display: inline-flex; gap: 8px; align-items: center; min-height: 34px; border: 0; border-radius: 4px; background: transparent; color: var(--text-secondary); padding: 0 16px; font-size: 12px; font-weight: 500; white-space: nowrap; cursor: pointer; }
	.task-tab:hover:not(:disabled) { color: var(--brand-primary); }
	.task-tab.active { background: var(--surface-card); color: var(--brand-primary); box-shadow: 0 1px 2px rgb(15 23 42 / 6%); }
	.task-tab:disabled { cursor: default; }
	.workbench-toolbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 0 32px 18px; }
	.status-tabs { display: flex; gap: 4px; min-width: 0; overflow-x: auto; }
	.status-tabs button { display: inline-flex; gap: 6px; align-items: center; min-height: 36px; border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; color: var(--text-secondary); padding: 0 8px; font-size: 12px; white-space: nowrap; cursor: pointer; }
	.status-tabs button:hover { background: var(--bg-subtle); color: var(--text-primary); }
	.status-tabs button.active { border-bottom-color: var(--brand-primary); color: var(--brand-primary); }
	.status-tabs span { color: var(--text-tertiary, var(--text-secondary)); font-variant-numeric: tabular-nums; }
	.search-field { display: flex; flex: 0 1 280px; gap: 8px; align-items: center; min-width: 0; min-height: 34px; box-sizing: border-box; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--surface-card); color: var(--text-secondary); padding: 0 10px; }
	.search-field input { width: 100%; min-width: 0; border: 0; outline: 0; background: transparent; padding: 0; }
	.alert { display: flex; gap: 8px; align-items: center; margin-bottom: 18px; border: 1px solid var(--danger-border); border-radius: 7px; background: var(--danger-bg); color: var(--danger-text); padding: 11px 13px; font-size: 13px; }
	.workbench { display: grid; grid-template-columns: 255px minmax(0, 1fr); align-items: stretch; gap: 0; border-block: 1px solid var(--border-default); background: var(--surface-card); }
	.queue { border-right: 1px solid var(--border-default); background: var(--bg-page); overflow: hidden; }
	.queue-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 18px 18px 15px; border-bottom: 1px solid var(--border-default); }
	.queue-header h2 { margin: 3px 0 0; font-size: 16px; }
	.queue-header > span { color: var(--text-primary); font-size: 12px; }
	.queue-list { max-height: max(580px, calc(100dvh - 415px)); overflow-y: auto; }
	.queue-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; width: 100%; min-height: 106px; align-items: end; border: 0; border-bottom: 1px solid var(--border-default); background: transparent; color: var(--text-primary); padding: 18px 20px; text-align: left; cursor: pointer; }
	.queue-item:hover { background: var(--bg-subtle); }
	.queue-item.active { box-shadow: inset 3px 0 var(--brand-primary); background: var(--brand-soft); }
	.queue-copy { display: grid; min-width: 0; gap: 4px; }
	.queue-copy strong { display: -webkit-box; line-clamp: 3; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; color: var(--text-primary); font-size: 13px; font-weight: 500; overflow-wrap: anywhere; }
	.queue-copy small { color: var(--text-secondary); font-size: 11px; }
	.queue-status { border-radius: 3px; padding: 3px 6px; color: var(--text-secondary); background: var(--bg-subtle); font-size: 10px; white-space: nowrap; }
	.queue-status--needs_confirmation { color: var(--warning-text); background: var(--warning-bg); }
	.queue-status--confirmed { color: var(--success-text); background: var(--success-bg); }
	.queue-status--needs_input { color: var(--warning-text); background: var(--warning-bg); }
	.queue-empty { display: grid; justify-items: center; padding: 40px 20px; color: var(--text-secondary); text-align: center; }
	.queue-empty p { margin: 12px 0 4px; color: var(--text-primary); font-size: 14px; font-weight: 700; }
	.queue-empty small { line-height: 1.55; }
	.editor-area { min-width: 0; }
	.editor-area :global(.annotation-grid) { grid-template-columns: minmax(0, 1fr) 300px; grid-template-rows: auto 1fr; gap: 0; min-height: 660px; border: 0; border-radius: 0; background: var(--surface-card); }
	.editor-area :global(.question-column), .editor-area :global(.editor-column), .editor-area :global(.evidence-column) { background: var(--surface-card); padding: 24px; }
	.editor-area :global(.evidence-column) { box-sizing: border-box; max-height: max(660px, calc(100dvh - 335px)); overflow-y: auto; }
	.editor-area :global(.question-column) { border-bottom: 0; }
	.editor-area :global(.editor-column) { padding-top: 0; }
	.editor-area :global(.question) { font-size: 14px; line-height: 1.7; }
	.editor-area :global(h2) { font-size: 16px; margin-bottom: 12px; }
	.editor-area :global(textarea), .editor-area :global(input) { font-size: 13px; font-weight: 400; border-radius: 5px; }
	.editor-area :global(.original-answer) { margin-top: 16px; padding-top: 14px; }
	.editor-area :global(.original-answer > summary) { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 13px; cursor: pointer; }
	.editor-area :global(.source-meta) { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; border-top: 0; padding-top: 0; color: var(--text-secondary); font-size: 12px; }
	.editor-area :global(.section-heading) { align-items: center; margin-bottom: 12px; }
	.editor-area :global(.section-heading .section-kicker) { display: none; }
	.editor-area :global(.status) { border: 0; border-radius: 3px; background: var(--warning-bg); color: var(--warning-text); padding: 3px 7px; font-size: 11px; }
	.editor-area :global(.status--confirmed) { background: var(--success-bg); color: var(--success-text); }
	.editor-area :global(.response-grid textarea) { height: 214px; }
	.editor-area :global(#sft-target), .editor-area :global(#evaluation-reference) { height: 214px; }
	.editor-area :global(.evidence-card) { padding: 0 0 18px; border-left: 0; border-bottom: 1px solid var(--border-default); }
	.editor-area :global(.evidence-card textarea) { height: 140px; font-size: 12px; }
	.editor-area :global(.actions) { justify-content: flex-end; padding-top: 16px; border-top: 1px solid var(--border-default); }
	.editor-area :global(.sample-options) { margin-top: 16px; padding-top: 0; border-top: 0; }
	.detail-loading { display: grid; justify-items: center; gap: 11px; padding: 90px 24px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--surface-card); color: var(--text-secondary); }
	.detail-loading span, .loading span { display: block; width: 72%; height: 10px; border-radius: 99px; background: var(--border-default); animation: pulse 1.2s ease-in-out infinite; }
	.detail-loading span:nth-child(2), .loading span:nth-child(2) { width: 52%; animation-delay: .15s; }
	.detail-loading span:nth-child(3), .loading span:nth-child(3) { width: 64%; animation-delay: .3s; }
	.detail-loading p { margin: 5px 0 0; font-size: 13px; }
	.detail-error { display: grid; justify-items: center; gap: 10px; padding: 72px 24px; border: 1px solid var(--danger-border); border-radius: 8px; background: var(--surface-card); color: var(--danger-text); text-align: center; }
	.detail-error p { margin: 0; color: var(--danger-text); }
	.detail-error button { border: 1px solid var(--danger-text); border-radius: 6px; background: var(--surface-card); color: var(--danger-text); padding: 8px 12px; cursor: pointer; }
	.loading { display: grid; justify-items: center; gap: 12px; padding: 60px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--surface-card); }
	.export-panel { order: 1; border-top: 1px solid var(--border-default); background: var(--surface-card); overflow: hidden; }
	.export-heading { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; padding: 20px 22px 18px; border-bottom: 1px solid var(--border-default); background: var(--bg-subtle); }
	.export-heading h2 { margin: 5px 0 5px; font-size: 19px; }
	.export-heading p { max-width: 760px; margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
	.export-heading-meta { display: flex; flex: 0 0 auto; gap: 12px; align-items: center; }
	.export-count { display: inline-flex; gap: 6px; align-items: center; color: var(--brand-primary); font-size: 12px; font-weight: 700; white-space: nowrap; }
	.secondary-button, .primary-button--compact { display: inline-flex; gap: 7px; align-items: center; justify-content: center; border-radius: 6px; padding: 9px 13px; font-size: 13px; font-weight: 700; cursor: pointer; }
	.secondary-button { border: 1px solid var(--brand-primary); background: var(--surface-card); color: var(--brand-primary); }
	.secondary-button:hover:not(:disabled) { background: var(--brand-soft); }
	.secondary-button:disabled, .primary-button--compact:disabled, .download-button:disabled { cursor: not-allowed; opacity: .48; }
	.export-alert { display: flex; gap: 8px; align-items: center; margin: 14px 22px 0; border-radius: 6px; padding: 10px 12px; font-size: 13px; }
	.export-alert--error { border: 1px solid var(--danger-border); background: var(--danger-bg); color: var(--danger-text); }
	.export-alert--success { border: 1px solid var(--brand-border); background: var(--brand-soft); color: var(--brand-primary); }
	.export-preview { padding: 18px 22px 20px; }
	.export-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin-bottom: 18px; border: 1px solid var(--border-default); border-radius: 7px; background: var(--border-default); overflow: hidden; }
	.export-metrics > div { display: grid; gap: 4px; background: var(--surface-card); padding: 11px 13px; }
	.export-metrics strong { font-size: 21px; line-height: 1; }
	.export-metrics span { color: var(--text-secondary); font-size: 11px; }
	.metric--ready strong { color: var(--brand-primary); }
	.metric--warning strong { color: var(--warning-text); }
	.export-subheading { display: flex; justify-content: space-between; gap: 14px; align-items: baseline; margin-bottom: 9px; }
	.export-subheading strong { color: var(--text-primary); font-size: 13px; }
	.export-subheading span { color: var(--text-secondary); font-size: 11px; }
	.export-issues { margin-bottom: 18px; border: 1px solid var(--warning-border); border-radius: 7px; background: var(--warning-bg); padding: 13px 14px; }
	.export-issue, .preview-row, .export-history-row { display: flex; justify-content: space-between; gap: 14px; align-items: center; border-top: 1px solid var(--border-default); padding: 10px 0; }
	.export-issue:first-of-type, .preview-row:first-of-type, .export-history-row:first-of-type { border-top: 0; }
	.export-issue > div, .preview-row > div, .export-history-row > div { display: grid; min-width: 0; gap: 3px; }
	.export-issue strong, .preview-row strong, .export-history-row strong { overflow: hidden; color: var(--text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
	.export-issue span, .preview-row span, .export-history-row span { color: var(--text-secondary); font-size: 11px; }
	.link-button { flex: 0 0 auto; border: 0; background: transparent; color: var(--brand-primary); padding: 4px 0; font-size: 12px; font-weight: 700; cursor: pointer; }
	.link-button:hover { color: var(--brand-primary); text-decoration: underline; }
	.partial-choice { display: flex; gap: 9px; align-items: flex-start; margin-top: 11px; border-top: 1px solid var(--border-default); padding-top: 12px; color: var(--warning-text); cursor: pointer; }
	.partial-choice input { width: 16px; height: 16px; margin-top: 1px; accent-color: var(--brand-primary); }
	.partial-choice span { display: grid; gap: 3px; }
	.partial-choice strong { font-size: 12px; }
	.partial-choice small { color: var(--text-secondary); font-size: 11px; line-height: 1.45; }
	.export-ready, .export-empty { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 17px; border: 1px solid var(--brand-border); border-radius: 7px; background: var(--brand-soft); color: var(--brand-primary); padding: 12px 13px; }
	.export-ready > div, .export-empty > div { display: grid; gap: 3px; }
	.export-ready strong, .export-empty strong { color: var(--brand-primary); font-size: 13px; }
	.export-ready span, .export-empty span { color: var(--text-secondary); font-size: 11px; }
	.export-empty { margin: 18px 22px 20px; border-color: var(--border-default); background: var(--bg-subtle); color: var(--text-secondary); }
	.export-empty--neutral { margin: 0; }
	.export-empty--neutral strong { color: var(--text-primary); }
	.export-empty--neutral span { color: var(--text-secondary); }
	.preview-rows { margin-bottom: 17px; }
	.preview-row { border-color: var(--bg-subtle); }
	.preview-row > div { max-width: 80%; }
	.preview-row span { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.export-footer { display: flex; justify-content: space-between; gap: 14px; align-items: center; border-top: 1px solid var(--border-default); padding-top: 15px; }
	.export-footer small { color: var(--text-secondary); font-size: 11px; }
	.primary-button--compact { border: 1px solid var(--brand-primary); background: var(--brand-primary); color: white; }
	.primary-button--compact:hover:not(:disabled) { background: var(--brand-primary); }
	.export-history { border-top: 1px solid var(--border-default); margin: 0 22px; padding: 17px 0 2px; }
	.export-history-row { border-color: var(--bg-subtle); }
	.download-actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
	.download-button { display: inline-flex; gap: 5px; align-items: center; border: 1px solid var(--border-strong); border-radius: 5px; background: var(--surface-card); color: var(--text-secondary); padding: 6px 8px; font-size: 11px; font-weight: 700; cursor: pointer; }
	.download-button:hover:not(:disabled) { border-color: var(--brand-primary); color: var(--brand-primary); }
	.download-button--quiet { border-color: var(--border-default); color: var(--text-secondary); }
	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse { 0%, 100% { opacity: .55; } 50% { opacity: 1; } }
	@media (max-width: 1100px) and (min-width: 901px) { .workbench { grid-template-columns: 220px minmax(0, 1fr); } .editor-area :global(.annotation-grid) { grid-template-columns: minmax(0, 1fr) 260px; } .editor-area :global(.question-column), .editor-area :global(.editor-column), .editor-area :global(.evidence-column) { padding: 20px; } }
	@media (max-width: 900px) { .workbench { grid-template-columns: 1fr; } .queue { border-right: 0; border-bottom: 1px solid var(--border-default); } .queue-header { padding: 12px 16px; } .queue-list { display: flex; max-height: none; overflow-x: auto; } .queue-row { flex: 0 0 245px; width: 245px; } .queue-item { min-width: 245px; border-right: 1px solid var(--bg-subtle); border-bottom: 0; } }
	@media (max-width: 760px) { .editor-area :global(.annotation-grid) { display: block; min-height: 0; } .editor-area :global(.question-column), .editor-area :global(.editor-column), .editor-area :global(.evidence-column) { padding: 18px 16px; } .editor-area :global(.evidence-column) { max-height: none; overflow-y: visible; } .editor-area :global(.response-grid) { grid-template-columns: 1fr; } .editor-area :global(.choice-grid) { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
	@media (max-width: 760px) { .export-heading { display: block; } .export-heading-meta { justify-content: space-between; margin-top: 14px; } .export-subheading { display: block; } .export-subheading span { display: block; margin-top: 3px; } .export-footer { align-items: flex-start; flex-direction: column; } .export-history-row { align-items: flex-start; flex-direction: column; } .download-actions { justify-content: flex-start; } }
	@media (max-width: 560px) { .page-header { display: block; padding: 20px 16px 16px; } .header-actions { justify-content: space-between; margin-top: 15px; } .header-actions .toolbar-button { min-width: 0; padding-inline: 8px; } .header-actions .toolbar-button--icon { flex: 0 0 36px; } .task-tabs { margin-inline: 16px; } .task-tab { padding-inline: 10px; } .workbench-toolbar { display: block; padding: 0 16px 16px; } .status-tabs { padding-bottom: 4px; } .search-field { max-width: none; margin-top: 8px; } .queue-item { min-width: 230px; } .export-heading, .export-preview { padding-left: 16px; padding-right: 16px; } .export-history { margin-left: 16px; margin-right: 16px; } .export-metrics strong { font-size: 18px; } .export-issue, .preview-row { align-items: flex-start; flex-direction: column; gap: 6px; } .preview-row > div { max-width: 100%; } }
</style>
