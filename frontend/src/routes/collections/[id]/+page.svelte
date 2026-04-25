<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { errorMessage } from '../../_shared/api';
	import {
		listCollectionFiles,
		uploadCollectionFiles,
		type CollectionFile
	} from '../../_shared/files';
	import { t } from '../../_shared/i18n';
	import { createBuildTask, getTask, isTaskActive, type Task } from '../../_shared/tasks';
	import {
		buildOverviewPipelineSteps,
		fetchWorkspaceOverview,
		getOverviewReadinessState,
		getWorkspaceSurfaceState,
		type OverviewPipelineStatus,
		type OverviewPipelineStep,
		type OverviewReadinessState,
		type WorkspaceOverview,
		type WorkspaceSurfaceKey,
		type WorkspaceSurfaceState
	} from '../../_shared/workspace';

	type PaperMixRow = {
		key: 'review' | 'experimental' | 'mixed' | 'uncertain' | 'benchmark';
		label: string;
		count: number;
	};

	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let actionStatus = '';
	let loadedCollectionId = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	let selectedFiles: File[] = [];
	let isDragging = false;
	let uploadLoading = false;
	let uploadError = '';
	let uploadResult: { count: number; items: CollectionFile[] } | null = null;
	let fileInput: HTMLInputElement | null = null;
	let collectionFiles: CollectionFile[] = [];
	let filesLoading = false;
	let filesError = '';

	$: collectionId = $page.params.id ?? '';
	$: effectiveFileCount = Math.max(workspace?.file_count ?? 0, collectionFiles.length);
	$: stateWorkspace = workspace ? { ...workspace, file_count: effectiveFileCount } : null;
	$: readinessState = getOverviewReadinessState(stateWorkspace);
	$: pipelineSteps = buildOverviewPipelineSteps(stateWorkspace);
	$: paperCount = stateWorkspace?.document_summary.total_documents ?? effectiveFileCount;
	$: showUploadPanel =
		readinessState === 'empty' ||
		readinessState === 'ready_to_process' ||
		selectedFiles.length > 0 ||
		Boolean(uploadError || uploadResult);
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		clearPoll();
		void Promise.all([loadWorkspace(), loadFiles()]);
	}

	onDestroy(() => {
		clearPoll();
	});

	function clearPoll() {
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
	}

	function schedulePoll(taskId: string) {
		clearPoll();
		pollTimer = setTimeout(() => {
			void refreshTask(taskId);
		}, 2500);
	}

	function mergeTask(task: Task) {
		if (!workspace) return;
		const recent = [
			task,
			...workspace.recent_tasks.filter((item) => item.task_id !== task.task_id)
		].slice(0, 5);
		workspace = {
			...workspace,
			latest_task: task,
			recent_tasks: recent
		};
	}

	async function refreshTask(taskId: string) {
		const task = await getTask(taskId);
		mergeTask(task);

		if (isTaskActive(task)) {
			schedulePoll(task.task_id);
		} else {
			clearPoll();
			await Promise.all([loadWorkspace(false), loadFiles(false)]);
		}
	}

	async function loadWorkspace(showLoading = true) {
		error = '';
		if (showLoading) loading = true;
		try {
			workspace = await fetchWorkspaceOverview(collectionId);
			const latestTask = workspace.latest_task;
			if (latestTask && isTaskActive(latestTask)) {
				schedulePoll(latestTask.task_id);
			} else {
				clearPoll();
			}
		} catch (err) {
			error = errorMessage(err);
			workspace = null;
		} finally {
			loading = false;
		}
	}

	async function loadFiles(showLoading = true) {
		if (showLoading) filesLoading = true;
		filesError = '';
		try {
			const data = await listCollectionFiles(collectionId);
			collectionFiles = data.items;
		} catch (err) {
			filesError = errorMessage(err);
			collectionFiles = [];
		} finally {
			filesLoading = false;
		}
	}

	async function refreshAll() {
		await Promise.all([loadWorkspace(), loadFiles()]);
	}

	function browseFiles() {
		fileInput?.click();
	}

	function handleFiles(fileList: FileList | null) {
		selectedFiles = fileList ? Array.from(fileList) : [];
		uploadError = '';
	}

	function handleDrop(event: DragEvent) {
		event.preventDefault();
		isDragging = false;
		handleFiles(event.dataTransfer?.files ?? null);
	}

	function handleDragOver(event: DragEvent) {
		event.preventDefault();
		isDragging = true;
	}

	function handleDragLeave(event: DragEvent) {
		event.preventDefault();
		isDragging = false;
	}

	function handleDropzoneKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			browseFiles();
		}
	}

	async function startBuildRun() {
		if (!effectiveFileCount) {
			actionStatus = $t('overview.indexNoFiles');
			return;
		}

		actionStatus = '';
		try {
			const task = await createBuildTask(collectionId);
			mergeTask(task);
			actionStatus = $t('documents.indexing');
			schedulePoll(task.task_id);
		} catch (err) {
			actionStatus = errorMessage(err);
		}
	}

	async function submitUpload() {
		uploadError = '';
		uploadResult = null;

		if (!selectedFiles.length) {
			uploadError = $t('documents.errorNoFiles');
			return;
		}

		uploadLoading = true;
		try {
			uploadResult = await uploadCollectionFiles(collectionId, selectedFiles);
			selectedFiles = [];
			if (fileInput) fileInput.value = '';
			await Promise.all([loadFiles(false), loadWorkspace(false)]);
			actionStatus = $t('documents.uploadDone');
		} catch (err) {
			uploadError = errorMessage(err);
		} finally {
			uploadLoading = false;
		}
	}

	async function handleUploadPrimary() {
		if (selectedFiles.length) {
			await submitUpload();
			return;
		}
		browseFiles();
	}

	function formatPercent(value?: number | null) {
		if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
		return `${Math.max(0, Math.min(100, Math.round(value)))}%`;
	}

	function formatTaskStatus(status?: string | null) {
		if (!status) return $t('tasks.statusUnknown');
		const key = `tasks.status.${status}`;
		const translated = $t(key);
		return translated === key ? status : translated;
	}

	function formatTaskStage(stage?: string | null) {
		if (!stage) return $t('tasks.stageUnknown');
		const key = `tasks.stage.${stage}`;
		const translated = $t(key);
		return translated === key ? stage : translated;
	}

	function getFileLabel(file: CollectionFile) {
		return file.original_filename || $t('documents.untitledFile');
	}

	function pipelineStepLabel(step: OverviewPipelineStep) {
		return $t(`overview.pipeline.steps.${step.key}`);
	}

	function pipelineStatusLabel(status: OverviewPipelineStatus) {
		return $t(`overview.pipeline.statuses.${status}`);
	}

	function readinessTitle(state: OverviewReadinessState) {
		return $t(`overview.readiness.${state}.title`);
	}

	function readinessBody(state: OverviewReadinessState) {
		return $t(`overview.readiness.${state}.body`, { count: paperCount });
	}

	function readyPrimaryHref() {
		if (!stateWorkspace) return '#';
		if (stateWorkspace.capabilities.can_view_comparisons) return stateWorkspace.links.comparisons;
		if (stateWorkspace.capabilities.can_view_documents) return stateWorkspace.links.documents;
		return stateWorkspace.links.workspace;
	}

	function readyPrimaryLabel() {
		if (stateWorkspace?.capabilities.can_view_comparisons) {
			return $t('overview.actions.enterComparisons');
		}
		if (stateWorkspace?.capabilities.can_view_documents) {
			return $t('overview.actions.viewDocuments');
		}
		return $t('overview.actions.refreshStatus');
	}

	function evidenceHref() {
		return stateWorkspace?.links.evidence ?? stateWorkspace?.links.documents ?? '#';
	}

	function surfaceStatus(surface: WorkspaceSurfaceKey): WorkspaceSurfaceState {
		return getWorkspaceSurfaceState(stateWorkspace, surface);
	}

	function surfaceLabel(surface: WorkspaceSurfaceKey) {
		return $t(`overview.surfaceStates.${surfaceStatus(surface)}`);
	}

	function surfaceTone(surface: WorkspaceSurfaceKey) {
		const status = surfaceStatus(surface);
		if (status === 'ready' || status === 'limited') return 'ready';
		if (status === 'processing') return 'processing';
		if (status === 'failed') return 'failed';
		return 'pending';
	}

	function stepStatus(key: OverviewPipelineStep['key']) {
		return pipelineSteps.find((step) => step.key === key)?.status ?? 'pending';
	}

	function statusChecklist() {
		return [
			{
				label: $t('overview.cards.currentStatus.uploaded', { count: paperCount }),
				done: stepStatus('upload') === 'completed'
			},
			{
				label: $t('overview.cards.currentStatus.parsed'),
				done: stepStatus('parse') === 'completed'
			},
			{
				label: $t('overview.cards.currentStatus.evidence'),
				done: stepStatus('evidence') === 'completed'
			},
			{
				label: $t('overview.cards.currentStatus.comparison'),
				done: stepStatus('comparisons') === 'completed'
			},
			{
				label: $t('overview.cards.currentStatus.graph'),
				done: stepStatus('graph') === 'completed'
			}
		];
	}

	function paperMixRows(): PaperMixRow[] {
		const counts = stateWorkspace?.document_summary.doc_type_counts ?? {
			experimental: 0,
			review: 0,
			mixed: 0,
			uncertain: 0
		};
		return [
			{ key: 'review', label: $t('overview.docTypeReview'), count: counts.review },
			{ key: 'experimental', label: $t('overview.docTypeExperimental'), count: counts.experimental },
			{ key: 'mixed', label: $t('overview.docTypeMixed'), count: counts.mixed },
			{ key: 'uncertain', label: $t('overview.docTypeUncertain'), count: counts.uncertain },
			{ key: 'benchmark', label: $t('overview.docTypeBenchmark'), count: 0 }
		];
	}

	function paperMixMax() {
		return Math.max(1, ...paperMixRows().map((row) => row.count));
	}

	function isReviewDominant() {
		const rows = paperMixRows();
		const review = rows.find((row) => row.key === 'review')?.count ?? 0;
		return paperCount > 0 && review >= Math.max(1, paperCount / 2);
	}

	function nextStepItems() {
		if (readinessState === 'empty') {
			return [
				$t('overview.cards.next.emptyUpload'),
				$t('overview.cards.next.emptyDescribe'),
				$t('overview.cards.next.emptyStart')
			];
		}
		if (readinessState === 'processing' || readinessState === 'ready_to_process') {
			return [
				$t('overview.cards.next.processingWait'),
				$t('overview.cards.next.processingLogs'),
				$t('overview.cards.next.processingRefresh')
			];
		}
		if (readinessState === 'failed') {
			return [
				$t('overview.cards.next.failedErrors'),
				$t('overview.cards.next.failedRetry'),
				$t('overview.cards.next.failedEvidence')
			];
		}
		return [
			$t('overview.cards.next.readyTypes'),
			$t('overview.cards.next.readyEvidence'),
			$t('overview.cards.next.readyCompare')
		];
	}

	function actionStatusTone(value: string) {
		return value.startsWith('4') || value.startsWith('5') ? 'status--error' : '';
	}
</script>

<svelte:head>
	<title>{$t('overview.title')}</title>
</svelte:head>

{#if loading}
	<section class="card fade-up">
		<div class="status" role="status" aria-live="polite">{$t('overview.loading')}</div>
	</section>
{:else if error}
	<section class="card fade-up">
		<div class="status status--error" role="alert">{error}</div>
	</section>
{:else if stateWorkspace}
	<section class="overview-stack fade-up">
		<article class={`readiness-card readiness-card--${readinessState}`}>
			<div class="readiness-card__icon" aria-hidden="true">
				<span></span>
			</div>
			<div class="readiness-card__body">
				<h2>{readinessTitle(readinessState)}</h2>
				<p>{readinessBody(readinessState)}</p>
			</div>
			<div class="readiness-card__actions">
				{#if readinessState === 'ready'}
					<a class="btn btn--primary" href={readyPrimaryHref()}>
						{readyPrimaryLabel()}
						<span aria-hidden="true">-&gt;</span>
					</a>
					<a class="btn btn--ghost" href={evidenceHref()}>{$t('overview.actions.viewEvidence')}</a>
					<button class="btn btn--ghost" type="button" on:click={refreshAll}>
						{$t('overview.actions.refreshStatus')}
					</button>
				{:else if readinessState === 'processing'}
					<a class="btn btn--primary" href="#pipeline">{$t('overview.actions.viewProgress')}</a>
					<button class="btn btn--ghost" type="button" on:click={refreshAll}>
						{$t('overview.actions.refreshStatus')}
					</button>
				{:else if readinessState === 'ready_to_process'}
					<button class="btn btn--primary" type="button" on:click={startBuildRun}>
						{$t('overview.actions.startProcessing')}
					</button>
					<button class="btn btn--ghost" type="button" on:click={browseFiles}>
						{$t('overview.actions.uploadDocuments')}
					</button>
				{:else if readinessState === 'failed'}
					<a class="btn btn--primary" href="#status-card">{$t('overview.actions.viewErrors')}</a>
					<button class="btn btn--ghost" type="button" on:click={startBuildRun}>
						{$t('overview.actions.retryProcessing')}
					</button>
				{:else}
					<button
						class="btn btn--primary"
						type="button"
						disabled={uploadLoading}
						on:click={handleUploadPrimary}
					>
						{selectedFiles.length ? $t('documents.upload') : $t('overview.actions.uploadDocuments')}
					</button>
					<a class="btn btn--ghost" href="/">{$t('collection.backToCollections')}</a>
				{/if}
			</div>
		</article>

		{#if actionStatus}
			<div class={`status ${actionStatusTone(actionStatus)}`} role="status">{actionStatus}</div>
		{/if}

		{#if showUploadPanel}
			<section id="upload" class="overview-card overview-upload-card">
				<div>
					<h2>{$t('overview.uploadFormTitle')}</h2>
					<p>{$t('overview.uploadFormLead')}</p>
				</div>
				<div
					class={`dropzone ${isDragging ? 'dropzone--active' : ''}`}
					on:drop={handleDrop}
					on:dragover={handleDragOver}
					on:dragleave={handleDragLeave}
					on:click={browseFiles}
					on:keydown={handleDropzoneKeydown}
					role="button"
					tabindex="0"
				>
					<input
						class="dropzone-input"
						bind:this={fileInput}
						type="file"
						multiple
						on:change={(event) => handleFiles((event.currentTarget as HTMLInputElement).files)}
					/>
					<div class="dropzone-title">{$t('documents.dropHint')}</div>
					<div class="dropzone-sub">{$t('documents.browse')}</div>
					{#if selectedFiles.length}
						<div class="dropzone-files">
							{$t('documents.selectedCount', { count: selectedFiles.length })}
						</div>
					{/if}
				</div>
				<div class="table-actions">
					<button
						class="btn btn--primary"
						type="button"
						on:click={submitUpload}
						disabled={uploadLoading || !selectedFiles.length}
					>
						{uploadLoading ? $t('documents.uploading') : $t('documents.upload')}
					</button>
					{#if effectiveFileCount > 0}
						<button class="btn btn--ghost" type="button" on:click={startBuildRun}>
							{$t('overview.actions.startProcessing')}
						</button>
					{/if}
				</div>
				{#if uploadError}
					<div class="status status--error" role="alert">{uploadError}</div>
				{/if}
				{#if filesLoading}
					<div class="status" role="status">{$t('documents.listLoading')}</div>
				{:else if filesError}
					<div class="status status--error" role="alert">{filesError}</div>
				{:else if uploadResult}
					<div class="detail-section">
						<div class="detail-section__title">{$t('documents.uploadResultTitle')}</div>
						<ul class="result-list">
							{#each uploadResult.items as item}
								<li>{getFileLabel(item)}</li>
							{/each}
						</ul>
					</div>
				{/if}
			</section>
		{/if}

		<section id="pipeline" class="overview-card pipeline-card">
			<div class="overview-card__header">
				<h2>{$t('overview.pipeline.title')}</h2>
			</div>
			<ol class="pipeline-steps">
				{#each pipelineSteps as step}
					<li class={`pipeline-step pipeline-step--${step.status}`}>
						<div class="pipeline-step__marker" aria-hidden="true"><span></span></div>
						<div class="pipeline-step__content">
							<div class="pipeline-step__title">{pipelineStepLabel(step)}</div>
							<div class="pipeline-step__status">{pipelineStatusLabel(step.status)}</div>
						</div>
					</li>
				{/each}
			</ol>
		</section>

		<section class="overview-card-grid">
			<article id="status-card" class="overview-card overview-info-card">
				<h3>{$t('overview.cards.currentStatus.title')}</h3>
				<ul class="check-list">
					{#each statusChecklist() as item}
						<li class:complete={item.done}>
							<span aria-hidden="true"></span>
							{item.label}
						</li>
					{/each}
				</ul>
				<a class="btn btn--ghost btn--small card-action" href="#pipeline">
					{$t('overview.cards.currentStatus.logs')}
				</a>
				{#if stateWorkspace.latest_task}
					<div class="task-mini">
						<div>
							<span>{$t('overview.statusLatestTask')}</span>
							<strong>{formatTaskStatus(stateWorkspace.latest_task.status)}</strong>
						</div>
						<div>
							<span>{$t('overview.statusStage')}</span>
							<strong>{formatTaskStage(stateWorkspace.latest_task.current_stage)}</strong>
						</div>
						<div>
							<span>{$t('overview.statusProgress')}</span>
							<strong>{formatPercent(stateWorkspace.latest_task.progress_percent)}</strong>
						</div>
					</div>
					{#if stateWorkspace.latest_task.errors.length}
						<div class="status status--error" role="alert">
							{stateWorkspace.latest_task.errors.join(' | ')}
						</div>
					{/if}
				{/if}
			</article>

			<article class="overview-card overview-info-card">
				<h3>{$t('overview.cards.trust.title')}</h3>
				<p>{$t('overview.cards.trust.body')}</p>
				<div class="trust-chip-row">
					<span class={`trust-chip trust-chip--${surfaceTone('comparisons')}`}>
						{$t('overview.cards.trust.comparison')}: {surfaceLabel('comparisons')}
					</span>
					<span class={`trust-chip trust-chip--${surfaceTone('evidence')}`}>
						{$t('overview.cards.trust.evidence')}: {surfaceLabel('evidence')}
					</span>
					<span class={`trust-chip trust-chip--${surfaceTone('documents')}`}>
						{$t('overview.cards.trust.documents')}: {surfaceLabel('documents')}
					</span>
					<span class={`trust-chip trust-chip--${surfaceTone('protocol')}`}>
						Protocol: {surfaceLabel('protocol')}
					</span>
				</div>
				<div class="split-actions">
					<a class="btn btn--ghost btn--small" href={evidenceHref()}>
						{$t('overview.actions.viewEvidence')}
					</a>
					<a class="btn btn--primary btn--small" href={readyPrimaryHref()}>
						{$t('overview.actions.enterComparisonShort')}
					</a>
				</div>
			</article>

			<article class="overview-card overview-info-card">
				<h3>{$t('overview.cards.paperMix.title')}</h3>
				<p>{$t('overview.cards.paperMix.body')}</p>
				<div class="paper-mix">
					{#each paperMixRows() as row}
						<div class="paper-mix__row">
							<span>{row.label}</span>
							<div class="paper-mix__bar" aria-hidden="true">
								<span style={`width: ${(row.count / paperMixMax()) * 100}%`}></span>
							</div>
							<strong>{row.count}</strong>
						</div>
					{/each}
				</div>
				{#if isReviewDominant()}
					<p class="overview-hint">{$t('overview.cards.paperMix.reviewHint')}</p>
				{/if}
				<a class="btn btn--ghost btn--small card-action" href={stateWorkspace.links.documents}>
					{$t('overview.actions.viewDocumentList')}
				</a>
			</article>

			<article class="overview-card overview-info-card">
				<h3>{$t('overview.cards.next.title')}</h3>
				<ul class="next-list">
					{#each nextStepItems() as item}
						<li>{item}</li>
					{/each}
				</ul>
				<a class="guide-link" href="/docs">
					{$t('overview.cards.next.guide')}
					<span aria-hidden="true">-&gt;</span>
				</a>
			</article>
		</section>

		<div class="overview-footer-note">{$t('overview.footerNote')}</div>
	</section>
{/if}
