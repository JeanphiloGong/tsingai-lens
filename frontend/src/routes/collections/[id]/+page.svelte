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
	let selectedDocumentIds: string[] = [];
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
	$: readyDocuments = documents.filter((document) => document.status === 'ready');
	$: pendingDocuments = documents.filter((document) =>
		['stored', 'uploaded', 'failed'].includes(document.status)
	);
	$: processingDocuments = documents.filter((document) => document.status === 'processing');
	$: selectedReadyCount = selectedDocumentIds.filter((documentId) =>
		readyDocuments.some((document) => document.document_id === documentId)
	).length;
	const unsubscribePage = page.subscribe((currentPage) => {
		const nextCollectionId = currentPage.params.id ?? '';
		if (!nextCollectionId || nextCollectionId === loadedCollectionId) return;
		collectionId = nextCollectionId;
		loadedCollectionId = nextCollectionId;
		selectedDocumentIds = [];
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
			await loadDocuments();
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
		const response = await listCollectionDocuments(collectionId);
		documents = response.items;
		const readyIds = new Set(
			documents.filter((item) => item.status === 'ready').map((item) => item.document_id)
		);
		selectedDocumentIds = selectedDocumentIds.filter((documentId) => readyIds.has(documentId));
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

	function toggleDocument(documentId: string) {
		selectedDocumentIds = selectedDocumentIds.includes(documentId)
			? selectedDocumentIds.filter((item) => item !== documentId)
			: [...selectedDocumentIds, documentId];
	}

	function toggleAllReady() {
		selectedDocumentIds =
			selectedReadyCount === readyDocuments.length
				? []
				: readyDocuments.map((document) => document.document_id);
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
		if (!selectedReadyCount || discoveryLoading) return;
		discoveryLoading = true;
		error = '';
		notice = '';
		try {
			const result = await discoverCollectionObjectives(collectionId, selectedDocumentIds);
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

	function taskProgress(document: CollectionDocument) {
		const task = taskFor(document.document_id);
		if (!task || !isTaskActive(task)) return '';
		return task.progress_detail?.message || `${task.progress_percent}%`;
	}

	function formatSize(size: number) {
		if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
		return `${(size / (1024 * 1024)).toFixed(1)} MB`;
	}
</script>

<svelte:head><title>{$t('overview.title')}</title></svelte:head>

<section class="workspace-page fade-up">
	<header class="workspace-heading">
		<div>
			<h2>{$t('overview.currentModel.title')}</h2>
			<p>{$t('overview.currentModel.lead')}</p>
		</div>
		<button class="btn btn--ghost" type="button" on:click={refreshAll} disabled={loading}>
			{$t('overview.actions.refreshStatus')}
		</button>
	</header>

	{#if error}<p class="state state--error" role="alert">{error}</p>{/if}
	{#if notice}<p class="state" role="status" aria-live="polite">{notice}</p>{/if}

	<div class="scope-summary" aria-label={$t('overview.currentModel.summaryLabel')}>
		<div><strong>{documents.length}</strong><span>{$t('overview.currentModel.total')}</span></div>
		<div>
			<strong>{readyDocuments.length}</strong><span>{$t('overview.currentModel.ready')}</span>
		</div>
		<div>
			<strong>{processingDocuments.length}</strong><span
				>{$t('overview.currentModel.processing')}</span
			>
		</div>
		<div>
			<strong>{selectedReadyCount}</strong><span>{$t('overview.currentModel.selected')}</span>
		</div>
	</div>

	<section class="action-band" aria-labelledby="collection-action-title">
		<div>
			<h3 id="collection-action-title">{$t('overview.currentModel.actionsTitle')}</h3>
			<p>{$t('overview.currentModel.actionsLead')}</p>
		</div>
		<div class="actions">
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
			{#if selectedFiles.length}
				<button class="btn btn--primary" type="button" on:click={upload} disabled={uploadLoading}>
					{uploadLoading
						? $t('documents.uploading')
						: $t('overview.currentModel.uploadSelected', { count: selectedFiles.length })}
				</button>
			{/if}
			<button
				class="btn btn--ghost"
				type="button"
				disabled={!pendingDocuments.length || preparationLoading}
				on:click={() => prepareDocuments(pendingDocuments)}
			>
				{$t('overview.currentModel.preparePending', { count: pendingDocuments.length })}
			</button>
			<button
				class="btn btn--primary"
				type="button"
				disabled={!selectedReadyCount || discoveryLoading}
				on:click={discoverObjectives}
			>
				{discoveryLoading
					? $t('overview.currentModel.discovering')
					: $t('overview.currentModel.discover', { count: selectedReadyCount })}
			</button>
		</div>
	</section>

	<section class="document-scope" aria-labelledby="document-scope-title">
		<header>
			<div>
				<h3 id="document-scope-title">{$t('overview.currentModel.documentsTitle')}</h3>
				<p>{$t('overview.currentModel.documentsLead')}</p>
			</div>
			<label class="select-all">
				<input
					type="checkbox"
					checked={readyDocuments.length > 0 && selectedReadyCount === readyDocuments.length}
					disabled={!readyDocuments.length}
					on:change={toggleAllReady}
				/>
				{$t('overview.currentModel.selectAllReady')}
			</label>
		</header>

		{#if loading}
			<p class="state" aria-busy="true">{$t('overview.loading')}</p>
		{:else if !documents.length}
			<p class="state">{$t('overview.currentModel.empty')}</p>
		{:else}
			<div class="document-list">
				{#each documents as document (document.document_id)}
					<div class="document-row">
						<label class="document-select" aria-label={$t('overview.currentModel.selectDocument')}>
							<input
								type="checkbox"
								checked={selectedDocumentIds.includes(document.document_id)}
								disabled={document.status !== 'ready'}
								aria-label={`${$t('overview.currentModel.selectDocument')}: ${document.original_filename}`}
								on:change={() => toggleDocument(document.document_id)}
							/>
						</label>
						<div class="document-identity">
							<strong>{document.original_filename}</strong>
							<span>{formatSize(document.size_bytes)}</span>
						</div>
						<div class="document-state">
							<span class={`status-mark status-mark--${document.status}`}>
								{documentStatus(document)}
							</span>
							{#if taskProgress(document)}<small>{taskProgress(document)}</small>{/if}
							{#if taskFor(document.document_id)?.errors[0]}
								<small class="failure">{taskFor(document.document_id)?.errors[0]}</small>
							{/if}
						</div>
						<div class="row-actions">
							{#if ['stored', 'uploaded', 'failed'].includes(document.status)}
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
							{:else if document.status === 'ready'}
								<a
									class="btn btn--ghost btn--small"
									href={resolve('/collections/[id]/documents/[document_id]', {
										id: collectionId,
										document_id: document.document_id
									})}
								>
									{$t('research.documents.openPaper')}
								</a>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>

	{#if objectiveList?.objectives.length}
		<footer class="objective-link">
			<span
				>{$t('overview.currentModel.objectiveCount', {
					count: objectiveList.objectives.length
				})}</span
			>
			<a
				class="btn btn--ghost"
				href={resolve('/collections/[id]/objectives', { id: collectionId })}
			>
				{$t('overview.actions.enterObjectives')}
			</a>
		</footer>
	{/if}
</section>

<style>
	.workspace-page {
		width: min(1120px, 100%);
		margin: 0 auto;
		display: grid;
		gap: 22px;
	}
	.workspace-heading,
	.document-scope > header,
	.objective-link {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
	}
	h2,
	h3,
	p {
		margin: 0;
	}
	.workspace-heading p,
	.action-band p,
	.document-scope header p {
		margin-top: 5px;
		color: var(--text-secondary);
		line-height: 1.5;
	}
	.state {
		margin: 0;
		padding: 12px 0;
		color: var(--text-secondary);
	}
	.state--error,
	.failure {
		color: var(--danger-text, #b42318);
	}
	.scope-summary {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		border-block: 1px solid var(--border-default);
	}
	.scope-summary div {
		display: grid;
		gap: 2px;
		padding: 14px 18px;
		border-right: 1px solid var(--border-default);
	}
	.scope-summary div:last-child {
		border-right: 0;
	}
	.scope-summary strong {
		font-size: 20px;
	}
	.scope-summary span {
		color: var(--text-secondary);
		font-size: 12px;
	}
	.action-band {
		display: grid;
		gap: 14px;
		padding-bottom: 20px;
		border-bottom: 1px solid var(--border-default);
	}
	.actions,
	.row-actions {
		display: flex;
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
	.document-scope {
		display: grid;
		gap: 12px;
	}
	.select-all,
	.document-select {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		color: var(--text-secondary);
	}
	.document-list {
		display: grid;
		border-top: 1px solid var(--border-default);
	}
	.document-row {
		display: grid;
		grid-template-columns: 28px minmax(0, 1fr) minmax(180px, 0.7fr) auto;
		align-items: center;
		gap: 14px;
		min-height: 72px;
		padding: 12px 4px;
		border-bottom: 1px solid var(--border-default);
	}
	.document-identity,
	.document-state {
		min-width: 0;
		display: grid;
		gap: 4px;
	}
	.document-identity strong {
		overflow-wrap: anywhere;
	}
	.document-identity span,
	.document-state small {
		color: var(--text-secondary);
		font-size: 12px;
		overflow-wrap: anywhere;
	}
	.status-mark {
		width: fit-content;
		border: 1px solid var(--border-default);
		padding: 3px 7px;
		font-size: 12px;
	}
	.status-mark--ready {
		border-color: #3a7d5d;
		color: #256346;
	}
	.status-mark--processing {
		border-color: #917427;
		color: #725b1d;
	}
	.status-mark--failed {
		border-color: var(--danger-text, #b42318);
		color: var(--danger-text, #b42318);
	}
	.objective-link {
		align-items: center;
		padding-top: 6px;
	}
	@media (max-width: 760px) {
		.workspace-heading,
		.document-scope > header,
		.objective-link {
			flex-direction: column;
		}
		.scope-summary {
			grid-template-columns: 1fr 1fr;
		}
		.scope-summary div:nth-child(2) {
			border-right: 0;
		}
		.document-row {
			grid-template-columns: 28px minmax(0, 1fr);
			align-items: start;
		}
		.document-state,
		.row-actions {
			grid-column: 2;
		}
	}
</style>
