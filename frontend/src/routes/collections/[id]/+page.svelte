<script lang="ts">
	import { onDestroy } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../_shared/api';
	import {
		listCollectionDocuments,
		uploadCollectionDocuments,
		type CollectionDocument
	} from '../../_shared/collectionDocuments';
	import { t } from '../../_shared/i18n';
	import {
		discoverCollectionObjectives,
		fetchCollectionObjectives,
		type ObjectiveList
	} from '../../_shared/researchView';
	import {
		getTask,
		isTaskActive,
		listCollectionTasks,
		prepareCollectionDocument,
		type Task
	} from '../../_shared/tasks';

	let documents: CollectionDocument[] = [];
	let tasks: Task[] = [];
	let objectiveList: ObjectiveList | null = null;
	let selectedFiles: File[] = [];
	let loading = false;
	let uploadLoading = false;
	let preparationLoading = false;
	let discoveryLoading = false;
	let error = '';
	let notice = '';
	let loadedCollectionId = '';
	let fileInput: HTMLInputElement | null = null;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let collectionId = '';

	type PreparationProgressSummary = {
		ready: number;
		total: number;
		active: number;
		percent: number;
		message: string;
	};

	$: readyDocuments = documents.filter((document) => document.status === 'ready');
	$: activeTasks = tasks.filter(isTaskActive);
	$: activeDocumentIds = new Set(
		activeTasks
			.map((task) => task.document_id)
			.filter((documentId): documentId is string => Boolean(documentId))
	);
	$: processingDocuments = documents.filter(
		(document) => document.status === 'processing' || activeDocumentIds.has(document.document_id)
	);
	$: attentionDocuments = documents.filter(
		(document) =>
			['stored', 'uploaded', 'failed'].includes(document.status) &&
			!activeDocumentIds.has(document.document_id)
	);
	$: objectiveCount = objectiveList?.objectives.length ?? 0;
	$: collectionStage = objectiveCount
		? 'objectives'
		: processingDocuments.length
			? 'processing'
			: attentionDocuments.length
				? 'attention'
				: readyDocuments.length
					? 'ready'
					: 'empty';
	$: preparationProgress = buildPreparationProgress(documents, activeTasks);

	const unsubscribePage = page.subscribe((currentPage) => {
		const nextCollectionId = currentPage.params.id ?? '';
		if (!nextCollectionId || nextCollectionId === loadedCollectionId) return;
		collectionId = nextCollectionId;
		loadedCollectionId = nextCollectionId;
		void refreshAll();
	});

	onDestroy(() => {
		unsubscribePage();
		clearPoll();
	});

	function clearPoll() {
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = null;
	}

	function schedulePoll() {
		clearPoll();
		if (!tasks.some(isTaskActive)) return;
		pollTimer = setTimeout(() => void pollTasks(), 2500);
	}

	async function pollTasks() {
		const active = tasks.filter(isTaskActive);
		if (!active.length) return;
		try {
			const refreshed = await Promise.all(active.map((task) => getTask(task.task_id)));
			const refreshedById = new Map(refreshed.map((task) => [task.task_id, task]));
			tasks = tasks.map((task) => refreshedById.get(task.task_id) ?? task);
			await Promise.all([loadDocuments(), loadObjectives()]);
		} catch (err) {
			error = errorMessage(err);
		}
		schedulePoll();
	}

	async function refreshAll() {
		loading = true;
		error = '';
		try {
			await Promise.all([loadDocuments(), loadTasks(), loadObjectives()]);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
			schedulePoll();
		}
	}

	async function loadDocuments() {
		documents = (await listCollectionDocuments(collectionId)).items;
	}

	async function loadTasks() {
		tasks = (await listCollectionTasks(collectionId, { limit: 100 })).items;
	}

	async function loadObjectives() {
		try {
			objectiveList = await fetchCollectionObjectives(collectionId);
		} catch {
			objectiveList = null;
		}
	}

	function taskFor(documentId: string) {
		return tasks.find((task) => task.document_id === documentId) ?? null;
	}

	async function prepareDocuments(targets: CollectionDocument[]) {
		if (!targets.length || preparationLoading) return;
		preparationLoading = true;
		error = '';
		notice = '';
		try {
			const queued = await Promise.all(
				targets.map((document) => prepareCollectionDocument(collectionId, document.document_id))
			);
			const queuedIds = new Set(queued.map((task) => task.task_id));
			tasks = [...queued, ...tasks.filter((task) => !queuedIds.has(task.task_id))];
			await loadDocuments();
			notice = $t('overview.currentModel.preparationQueued', { count: queued.length });
			schedulePoll();
		} catch (err) {
			error = errorMessage(err);
		} finally {
			preparationLoading = false;
		}
	}

	async function discoverObjectives() {
		if (!readyDocuments.length || discoveryLoading) return;
		discoveryLoading = true;
		error = '';
		notice = '';
		try {
			const documentIds = readyDocuments.map((document) => document.document_id);
			const result = await discoverCollectionObjectives(collectionId, documentIds);
			await loadObjectives();
			notice = $t('overview.currentModel.discoveryComplete', { count: result.objectives.length });
		} catch (err) {
			error = errorMessage(err);
		} finally {
			discoveryLoading = false;
		}
	}

	async function upload() {
		if (!selectedFiles.length || uploadLoading) return;
		uploadLoading = true;
		error = '';
		notice = '';
		try {
			const result = await uploadCollectionDocuments(collectionId, selectedFiles);
			selectedFiles = [];
			if (fileInput) fileInput.value = '';
			await loadDocuments();
			notice = $t('overview.currentModel.uploadComplete', { count: result.count });
		} catch (err) {
			error = errorMessage(err);
		} finally {
			uploadLoading = false;
		}
	}

	function documentStatus(document: CollectionDocument) {
		const key = `overview.currentModel.status.${document.status}`;
		const translated = $t(key);
		return translated === key ? document.status : translated;
	}

	function buildPreparationProgress(
		items: CollectionDocument[],
		active: Task[]
	): PreparationProgressSummary | null {
		if (!active.length) return null;

		const activeDocumentIds = new Set(
			active
				.map((task) => task.document_id)
				.filter((documentId): documentId is string => Boolean(documentId))
		);
		const ready = items.filter(
			(document) => document.status === 'ready' && !activeDocumentIds.has(document.document_id)
		).length;
		const total = Math.max(items.length, ready + active.length);
		const activeProgress = active.reduce(
			(sum, task) => sum + Math.max(0, Math.min(100, Number(task.progress_percent) || 0)) / 100,
			0
		);
		const percent = Math.round(((ready + activeProgress) / total) * 100);
		const message =
			active.find((task) => task.progress_detail?.message)?.progress_detail?.message ?? '';

		return {
			ready,
			total,
			active: active.length,
			percent: Math.max(0, Math.min(100, percent)),
			message
		};
	}
</script>

<svelte:head><title>{$t('overview.title')}</title></svelte:head>

<section class="overview-page fade-up">
	<header class="overview-heading">
		<div>
			<h2>{$t('overview.currentModel.title')}</h2>
			<p>{$t('overview.currentModel.lead')}</p>
		</div>
		<div class="header-actions">
			<input
				class="file-input"
				bind:this={fileInput}
				type="file"
				multiple
				aria-label={$t('overview.actions.uploadDocuments')}
				on:change={(event) =>
					(selectedFiles = Array.from((event.currentTarget as HTMLInputElement).files ?? []))}
			/>
			<button class="btn btn--ghost" type="button" on:click={() => fileInput?.click()}>
				{$t('overview.actions.uploadDocuments')}
			</button>
			<button class="btn btn--ghost" type="button" on:click={refreshAll} disabled={loading}>
				{$t('overview.actions.refreshStatus')}
			</button>
		</div>
	</header>

	{#if selectedFiles.length}
		<div class="upload-selection" role="status">
			<span>{$t('overview.currentModel.uploadReady', { count: selectedFiles.length })}</span>
			<button
				class="btn btn--primary btn--small"
				type="button"
				on:click={upload}
				disabled={uploadLoading}
			>
				{uploadLoading
					? $t('documents.uploading')
					: $t('overview.currentModel.uploadSelected', { count: selectedFiles.length })}
			</button>
		</div>
	{/if}

	{#if error}<p class="state state--error" role="alert">{error}</p>{/if}
	{#if notice}<p class="state state--notice" role="status" aria-live="polite">{notice}</p>{/if}

	<section class={`research-state research-state--${collectionStage}`} aria-live="polite">
		<div class="research-state__copy">
			<span class="eyebrow">{$t('overview.currentModel.stateEyebrow')}</span>
			<h3>{$t(`overview.currentModel.state.${collectionStage}.title`)}</h3>
			<p>
				{$t(`overview.currentModel.state.${collectionStage}.body`, {
					papers: documents.length,
					ready: readyDocuments.length,
					processing: processingDocuments.length,
					objectives: objectiveCount
				})}
			</p>
			{#if preparationProgress}
				<div
					class="active-progress"
					role="status"
					aria-label={$t('overview.currentModel.preparationProgressTitle')}
				>
					<div class="active-progress__header">
						<span>{$t('overview.currentModel.preparationProgressTitle')}</span>
						<strong>{preparationProgress.percent}%</strong>
					</div>
					<div
						class="active-progress__track"
						role="progressbar"
						aria-label={$t('overview.currentModel.preparationProgressTitle')}
						aria-valuemin="0"
						aria-valuemax="100"
						aria-valuenow={preparationProgress.percent}
						aria-valuetext={`${preparationProgress.percent}%`}
					>
						<span style={`width: ${preparationProgress.percent}%`}></span>
					</div>
					<div class="active-progress__meta">
						<span>
							{$t('overview.currentModel.preparationProgressReady', {
								ready: preparationProgress.ready,
								total: preparationProgress.total
							})}
						</span>
						<span>
							{$t('overview.currentModel.preparationProgressActive', {
								count: preparationProgress.active
							})}
						</span>
					</div>
					{#if preparationProgress.message}<small>{preparationProgress.message}</small>{/if}
				</div>
			{/if}
		</div>

		<div class="research-state__actions">
			{#if objectiveCount}
				<a
					class="btn btn--primary"
					href={resolve('/collections/[id]/objectives', { id: collectionId })}
				>
					{$t('overview.currentModel.openObjectives')}
				</a>
			{:else if attentionDocuments.length}
				<button
					class="btn btn--primary"
					type="button"
					disabled={preparationLoading}
					on:click={() => prepareDocuments(attentionDocuments)}
				>
					{$t('overview.currentModel.preparePending', { count: attentionDocuments.length })}
				</button>
			{:else if readyDocuments.length}
				<button
					class="btn btn--primary"
					type="button"
					disabled={discoveryLoading}
					on:click={discoverObjectives}
				>
					{discoveryLoading
						? $t('overview.currentModel.discovering')
						: $t('overview.currentModel.discover', { count: readyDocuments.length })}
				</button>
			{:else if !documents.length}
				<button class="btn btn--primary" type="button" on:click={() => fileInput?.click()}>
					{$t('overview.actions.uploadDocuments')}
				</button>
			{/if}

			{#if !objectiveCount && readyDocuments.length && attentionDocuments.length}
				<button
					class="btn btn--ghost"
					type="button"
					on:click={discoverObjectives}
					disabled={discoveryLoading}
				>
					{$t('overview.currentModel.discover', { count: readyDocuments.length })}
				</button>
			{/if}
		</div>
	</section>

	<div class="research-progress" aria-label={$t('overview.currentModel.summaryLabel')}>
		<div class:complete={documents.length > 0}>
			<span>1</span>
			<div>
				<strong>{$t('overview.currentModel.progress.collected')}</strong><small
					>{documents.length}</small
				>
			</div>
		</div>
		<div class:complete={readyDocuments.length > 0} class:active={processingDocuments.length > 0}>
			<span>2</span>
			<div>
				<strong>{$t('overview.currentModel.progress.understood')}</strong><small
					>{readyDocuments.length}</small
				>
			</div>
		</div>
		<div class:complete={objectiveCount > 0}>
			<span>3</span>
			<div>
				<strong>{$t('overview.currentModel.progress.objectives')}</strong><small
					>{objectiveCount}</small
				>
			</div>
		</div>
		<div>
			<span>4</span>
			<div><strong>{$t('overview.currentModel.progress.analysis')}</strong><small>--</small></div>
		</div>
	</div>

	{#if attentionDocuments.length}
		<details class="attention-panel">
			<summary>
				<span>
					<strong
						>{$t('overview.currentModel.attentionTitle', {
							count: attentionDocuments.length
						})}</strong
					>
					<small>{$t('overview.currentModel.attentionLead')}</small>
				</span>
			</summary>
			<div class="attention-list">
				{#each attentionDocuments as document (document.document_id)}
					<div class="attention-row">
						<div>
							<strong>{document.original_filename}</strong>
							<span>{documentStatus(document)}</span>
							{#if taskFor(document.document_id)?.errors[0]}
								<small class="failure">{taskFor(document.document_id)?.errors[0]}</small>
							{/if}
						</div>
						<button
							class="btn btn--ghost btn--small"
							type="button"
							disabled={preparationLoading}
							on:click={() => prepareDocuments([document])}
						>
							{$t(
								document.status === 'failed'
									? 'overview.currentModel.retry'
									: 'overview.currentModel.prepare'
							)}
						</button>
					</div>
				{/each}
			</div>
		</details>
	{/if}
</section>

<style>
	.overview-page {
		width: min(1120px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 20px;
	}

	.overview-heading,
	.header-actions,
	.upload-selection,
	.research-state,
	.research-state__actions,
	.active-progress,
	.attention-row {
		display: flex;
		align-items: center;
	}

	.overview-heading,
	.research-state,
	.attention-row {
		justify-content: space-between;
	}

	.overview-heading {
		align-items: flex-start;
		gap: 20px;
		padding-bottom: 16px;
		border-bottom: 1px solid var(--border-default);
	}

	h2,
	h3,
	p {
		margin: 0;
	}

	.overview-heading p,
	.research-state p,
	.attention-panel small {
		color: var(--text-secondary);
	}

	.overview-heading p {
		max-width: 720px;
		margin-top: 6px;
		line-height: 1.5;
	}

	.header-actions,
	.research-state__actions {
		flex-wrap: wrap;
		gap: 8px;
	}

	.file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
	}

	.upload-selection,
	.state {
		padding: 10px 12px;
		border: 1px solid var(--border-default);
	}

	.upload-selection {
		justify-content: space-between;
		gap: 16px;
	}

	.state {
		color: var(--text-secondary);
	}

	.state--error,
	.failure {
		color: var(--danger-text, #b42318);
	}

	.state--notice {
		color: var(--success-text, #256346);
	}

	.research-state {
		min-height: 170px;
		gap: 32px;
		padding: 28px 0;
		border-bottom: 1px solid var(--border-default);
	}

	.research-state__copy {
		max-width: 680px;
	}

	.eyebrow {
		display: block;
		margin-bottom: 8px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
	}

	.research-state h3 {
		font-size: 24px;
		line-height: 1.3;
	}

	.research-state p {
		margin-top: 8px;
		line-height: 1.6;
	}

	.active-progress {
		max-width: 560px;
		display: grid;
		gap: 8px;
		margin-top: 16px;
		padding-top: 12px;
		border-top: 1px solid var(--border-default);
		font-size: 13px;
	}

	.active-progress__header,
	.active-progress__meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		min-width: 0;
	}

	.active-progress__meta {
		flex-wrap: wrap;
	}

	.active-progress__header strong {
		color: var(--text-primary);
		font-size: 15px;
	}

	.active-progress__track {
		height: 8px;
		overflow: hidden;
		border-radius: 4px;
		background: var(--border-default);
	}

	.active-progress__track span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent-primary, #2563eb);
		transition: width 180ms ease;
	}

	.active-progress__meta,
	.active-progress small {
		color: var(--text-secondary);
		font-size: 12px;
	}

	.active-progress small {
		overflow-wrap: anywhere;
	}

	.research-progress {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}

	.research-progress > div {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 14px 16px;
		border-right: 1px solid var(--border-default);
		color: var(--text-secondary);
	}

	.research-progress > div:last-child {
		border-right: 0;
	}

	.research-progress > div > span {
		display: grid;
		width: 24px;
		height: 24px;
		place-items: center;
		border: 1px solid currentColor;
		border-radius: 50%;
		font-size: 11px;
	}

	.research-progress > div.complete,
	.research-progress > div.active {
		color: var(--text-primary);
	}

	.research-progress > div.complete > span {
		border-color: #3a7d5d;
		background: #3a7d5d;
		color: white;
	}

	.research-progress div div {
		display: grid;
		gap: 2px;
	}

	.research-progress strong {
		font-size: 13px;
	}

	.research-progress small {
		font-size: 11px;
	}

	.attention-panel {
		border-block: 1px solid var(--border-default);
	}

	.attention-panel summary {
		cursor: pointer;
		padding: 16px 4px;
	}

	.attention-panel summary span {
		display: inline-grid;
		gap: 3px;
		margin-left: 8px;
	}

	.attention-list {
		border-top: 1px solid var(--border-default);
	}

	.attention-row {
		gap: 20px;
		padding: 12px 4px;
		border-bottom: 1px solid var(--border-default);
	}

	.attention-row:last-child {
		border-bottom: 0;
	}

	.attention-row > div {
		min-width: 0;
		display: grid;
		gap: 3px;
	}

	.attention-row strong,
	.attention-row small {
		overflow-wrap: anywhere;
	}

	.attention-row span,
	.attention-row small {
		font-size: 12px;
	}

	@media (max-width: 760px) {
		.overview-page {
			gap: 14px;
		}

		.overview-heading,
		.research-state,
		.upload-selection,
		.attention-row {
			align-items: stretch;
			flex-direction: column;
		}

		.header-actions,
		.research-state__actions {
			width: 100%;
		}

		.header-actions .btn,
		.research-state__actions .btn {
			flex: 1;
		}

		.research-state {
			min-height: 0;
			padding: 18px 0;
		}

		.research-state h3 {
			font-size: 20px;
		}

		.research-progress {
			grid-template-columns: 1fr 1fr;
		}

		.research-progress > div:nth-child(2) {
			border-right: 0;
		}

		.research-progress > div:nth-child(-n + 2) {
			border-bottom: 1px solid var(--border-default);
		}
	}
</style>
