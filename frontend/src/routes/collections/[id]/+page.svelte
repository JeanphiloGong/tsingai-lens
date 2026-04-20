<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { errorMessage } from '../../_shared/api';
  import { listCollectionFiles, uploadCollectionFiles, type CollectionFile } from '../../_shared/files';
  import { t } from '../../_shared/i18n';
  import {
    createBuildTask,
    getTask,
    isTaskActive,
    type Task
  } from '../../_shared/tasks';
  import {
    countActionablePrimaryViews,
    fetchWorkspaceOverview,
    getCollectionWorkspaceState,
    getWorkspaceSurfaceState,
    stageIsActionable,
    type CollectionWorkspaceState,
    type WorkspaceSurfaceState,
    type WorkspaceOverview
  } from '../../_shared/workspace';

  let workspace: WorkspaceOverview | null = null;
  let loading = false;
  let error = '';
  let actionStatus = '';
  let loadedCollectionId = '';
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  let selectedFiles: File[] = [];
  let isDragging = false;
  let buildAfterUpload = true;
  let uploadLoading = false;
  let uploadError = '';
  let uploadResult: { count: number; items: CollectionFile[] } | null = null;
  let fileInput: HTMLInputElement | null = null;
  let collectionFiles: CollectionFile[] = [];
  let filesLoading = false;
  let filesError = '';

  let advancedOpen = false;
  const primaryViewKeys = ['comparisons', 'evidence', 'documents'] as const;
  const setupPreviewKeys = ['comparisons', 'evidence', 'documents', 'protocol'] as const;

  $: collectionId = $page.params.id ?? '';
  $: if ($page.url.hash.startsWith('#advanced')) {
    advancedOpen = true;
  }
  $: effectiveFileCount = Math.max(workspace?.file_count ?? 0, collectionFiles.length);
  $: stateWorkspace = workspace ? { ...workspace, file_count: effectiveFileCount } : null;
  $: workspaceState = getCollectionWorkspaceState(stateWorkspace);
  $: actionablePrimaryViews = countActionablePrimaryViews(stateWorkspace);
  $: protocolState = getWorkspaceSurfaceState(stateWorkspace, 'protocol');
  $: graphState = getWorkspaceSurfaceState(stateWorkspace, 'graph');
  $: isEmptyState = workspaceState === 'empty';
  $: isReadyToProcessState = workspaceState === 'ready_to_process';
  $: isProcessingState = workspaceState === 'processing';
  $: isAnalysisState =
    workspaceState === 'ready' ||
    workspaceState === 'ready_with_limits' ||
    workspaceState === 'failed';
  $: showAdditionalViews = Boolean(
    workspace &&
      isAnalysisState &&
      (protocolState !== 'not_applicable' || graphState === 'ready')
  );
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
    const recent = [task, ...workspace.recent_tasks.filter((item) => item.task_id !== task.task_id)].slice(0, 5);
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
      if (latestTask) {
        if (isTaskActive(latestTask)) {
          schedulePoll(latestTask.task_id);
        } else {
          clearPoll();
        }
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

  function formatStatus(status?: string | null) {
    if (!status) return $t('overview.statusUnknown');
    const key = `overview.status.${status}`;
    const translated = $t(key);
    return translated === key ? status : translated;
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

  function formatCount(value?: number | null) {
    return typeof value === 'number' && Number.isFinite(value) ? String(value) : '--';
  }

  function formatDate(value?: string | null) {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function formatPercent(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return `${Math.max(0, Math.min(100, Math.round(value)))}%`;
  }

  function formatBytes(value?: number) {
    if (value === undefined || value === null || Number.isNaN(value)) return '--';
    if (value < 1024) return `${value} B`;
    const kb = value / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    return `${(mb / 1024).toFixed(1)} GB`;
  }

  function workflowRows() {
    if (!workspace) return [];
    return [
      ['documents', workspace.workflow.documents],
      ['evidence', workspace.workflow.evidence],
      ['comparisons', workspace.workflow.comparisons],
      ['protocol', workspace.workflow.protocol]
    ] as Array<[string, string]>;
  }

  function formatWorkflowStatus(status?: string | null) {
    if (!status) return $t('overview.statusUnknown');
    const key = `overview.workflowStates.${status}`;
    const translated = $t(key);
    return translated === key ? status : translated;
  }

  function documentTypeRows() {
    if (!workspace) return [];
    const counts = workspace.document_summary.doc_type_counts;
    const rows: Array<[string, number]> = [
      [$t('overview.docTypeExperimental'), counts.experimental],
      [$t('overview.docTypeReview'), counts.review],
      [$t('overview.docTypeMixed'), counts.mixed],
      [$t('overview.docTypeUncertain'), counts.uncertain]
    ];
    return rows.filter(([, count]) => count > 0);
  }

  function protocolSuitabilityRows() {
    if (!workspace) return [];
    const counts = workspace.document_summary.protocol_extractable_counts;
    const rows: Array<[string, number]> = [
      [$t('overview.protocolExtractableYes'), counts.yes],
      [$t('overview.protocolExtractablePartial'), counts.partial],
      [$t('overview.protocolExtractableNo'), counts.no],
      [$t('overview.protocolExtractableUncertain'), counts.uncertain]
    ];
    return rows.filter(([, count]) => count > 0);
  }

  function getFileLabel(file: CollectionFile) {
    return file.original_filename || $t('documents.untitledFile');
  }

  function primaryActionLabel() {
    if (!workspace) return $t('overview.primaryActionUpload');
    if (!effectiveFileCount) return $t('overview.primaryActionUpload');
    if (workspace.latest_task && isTaskActive(workspace.latest_task)) return $t('overview.primaryActionTrack');
    if (workspace.capabilities.can_view_comparisons) return $t('overview.primaryActionComparisons');
    if (workspace.capabilities.can_view_evidence) return $t('overview.primaryActionEvidence');
    if (workspace.capabilities.can_view_documents) return $t('overview.primaryActionDocuments');
    if (workspace.capabilities.can_generate_sop || workspace.capabilities.can_view_protocol_steps) {
      return $t('overview.primaryActionProtocol');
    }
    return $t('overview.primaryActionProcess');
  }

  function openPrimaryAction() {
    const latestTask = workspace?.latest_task;
    if (!workspace) return;

    if (!effectiveFileCount) {
      location.hash = 'files';
      return;
    }

    if (latestTask && isTaskActive(latestTask)) {
      location.hash = 'status';
      return;
    }

    if (workspace.capabilities.can_view_comparisons) {
      location.href = workspace.links.comparisons;
      return;
    }

    if (workspace.capabilities.can_view_evidence) {
      location.href = workspace.links.evidence;
      return;
    }

    if (workspace.capabilities.can_view_documents) {
      location.href = workspace.links.documents;
      return;
    }

    if (workspace.capabilities.can_generate_sop || workspace.capabilities.can_view_protocol_steps) {
      location.href = workspace.links.protocol;
      return;
    }

    void startBuildRun();
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
      if (buildAfterUpload) {
        await startBuildRun();
      }
    } catch (err) {
      uploadError = errorMessage(err);
    } finally {
      uploadLoading = false;
    }
  }

  function collectionStateLabel(state: CollectionWorkspaceState) {
    return $t(`overview.collectionStates.${state}.label`);
  }

  function collectionStateTitle(state: CollectionWorkspaceState) {
    return $t(`overview.collectionStates.${state}.title`);
  }

  function collectionStateBody(state: CollectionWorkspaceState) {
    return $t(`overview.collectionStates.${state}.body`);
  }

  function surfaceStatusLabel(status: WorkspaceSurfaceState) {
    return $t(`overview.surfaceStates.${status}`);
  }

  function surfaceStatusNote(status: WorkspaceSurfaceState) {
    return $t(`overview.surfaceStateNotes.${status}`);
  }

  function viewLink(key: (typeof primaryViewKeys)[number] | 'protocol' | 'graph') {
    if (!workspace) return '#';
    if (key === 'graph') return `/collections/${collectionId}/graph`;
    return workspace.links[key];
  }

  function viewLead(key: (typeof primaryViewKeys)[number] | 'protocol' | 'graph') {
    if (key === 'comparisons') return $t('overview.resultComparisonsLead');
    if (key === 'evidence') return $t('overview.resultEvidenceLead');
    if (key === 'documents') return $t('overview.resultDocumentsLead');
    if (key === 'protocol') return $t('overview.resultProtocolLead');
    return $t('overview.resultGraphLead');
  }

  function viewState(key: (typeof primaryViewKeys)[number] | 'protocol' | 'graph') {
    if (key === 'graph') return graphState;
    if (key === 'protocol') return protocolState;
    return stateWorkspace ? getWorkspaceSurfaceState(stateWorkspace, key) : 'empty';
  }

  function showViewAction(key: (typeof primaryViewKeys)[number] | 'protocol' | 'graph') {
    return viewState(key) === 'ready' || viewState(key) === 'limited';
  }

  function viewActionLabel(key: (typeof primaryViewKeys)[number] | 'protocol' | 'graph') {
    if (key === 'comparisons') return $t('overview.nextComparisons');
    if (key === 'evidence') return $t('overview.nextEvidence');
    if (key === 'documents') return $t('overview.nextDocuments');
    if (key === 'protocol') return $t('overview.nextProtocol');
    return $t('overview.nextGraph');
  }

  function actionStatusTone(value: string) {
    return value.startsWith('4') || value.startsWith('5') ? 'status--error' : '';
  }

  function compactPreviewLead(key: (typeof setupPreviewKeys)[number]) {
    if (key === 'comparisons') return $t('overview.previewComparisonsLead');
    if (key === 'evidence') return $t('overview.previewEvidenceLead');
    if (key === 'documents') return $t('overview.previewDocumentsLead');
    return $t('overview.previewProtocolLead');
  }

  function setupTitle() {
    if (isReadyToProcessState) return $t('overview.setupReadyTitle');
    return $t('overview.setupEmptyTitle');
  }

  function setupBody() {
    if (isReadyToProcessState) return $t('overview.setupReadyLead');
    return $t('overview.setupEmptyLead');
  }

  function processingTitle() {
    return $t('overview.processingTitle');
  }

  function processingBody() {
    return $t('overview.processingLead');
  }

  function setupPrimaryLabel() {
    if (selectedFiles.length) {
      return uploadLoading ? $t('documents.uploading') : $t('overview.startUploadCta');
    }
    if (isReadyToProcessState) {
      return $t('overview.startAnalysisCta');
    }
    return $t('overview.addPapersCta');
  }

  async function handleSetupPrimaryAction() {
    if (selectedFiles.length) {
      await submitUpload();
      return;
    }
    if (isReadyToProcessState) {
      await startBuildRun();
      return;
    }
    browseFiles();
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
{:else if workspace}
  <section id="status" class="card fade-up">
    <div class="card-header-inline">
      <div>
        <h2>{workspace.collection.name || $t('collection.unknownName')}</h2>
        <p class="lead">{$t('overview.lead')}</p>
        {#if workspace.collection.description}
          <p class="note">{workspace.collection.description}</p>
        {/if}
        <div class="detail-chips">
          <span class="detail-chip">{collectionStateLabel(workspaceState)}</span>
          <span class="detail-chip detail-chip--muted">{formatStatus(workspace.status_summary)}</span>
          <span class="detail-chip detail-chip--muted">{$t('overview.filesCount', { count: effectiveFileCount })}</span>
          <span class="detail-chip detail-chip--muted">
            {$t('overview.readyViewsCount', { count: actionablePrimaryViews })}
          </span>
        </div>
      </div>
      <div class="table-actions">
        <button class="btn btn--ghost btn--small" type="button" on:click={() => Promise.all([loadWorkspace(), loadFiles()])}>
          {$t('overview.refresh')}
        </button>
        {#if !isEmptyState && !isReadyToProcessState}
          <button class="btn btn--primary" type="button" on:click={openPrimaryAction}>
            {primaryActionLabel()}
          </button>
        {/if}
      </div>
    </div>
  </section>

  {#if isEmptyState || isReadyToProcessState}
    <section id="files" class="card">
      <div class="workspace-setup">
        <article class="result-card workspace-setup__hero">
          <h3>{setupTitle()}</h3>
          <p class="lead">{setupBody()}</p>
          <p class="note">
            {#if isReadyToProcessState}
              {$t('overview.setupReadyHint')}
            {:else}
              {$t('overview.setupEmptyHint')}
            {/if}
          </p>

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
              <div class="dropzone-files">{$t('documents.selectedCount', { count: selectedFiles.length })}</div>
            {/if}
          </div>

          {#if !isReadyToProcessState}
            <div class="toggle-row">
              <label>
                <input type="checkbox" bind:checked={buildAfterUpload} />
                {$t('documents.indexAfterLabel')}
              </label>
            </div>
          {/if}

          {#if uploadError}
            <div class="status status--error" role="alert">{uploadError}</div>
          {/if}
          {#if actionStatus}
            <div class={`status ${actionStatusTone(actionStatus)}`} role="status">{actionStatus}</div>
          {/if}

          <div class="table-actions">
            <button
              class="btn btn--primary"
              type="button"
              on:click={handleSetupPrimaryAction}
              disabled={uploadLoading}
            >
              {setupPrimaryLabel()}
            </button>
            {#if isReadyToProcessState}
              <button class="btn btn--ghost" type="button" on:click={browseFiles}>
                {$t('overview.addMorePapersCta')}
              </button>
            {/if}
          </div>

          {#if uploadResult}
            <div class="detail-section">
              <div class="detail-section__title">{$t('documents.uploadResultTitle')}</div>
              <p class="meta-text">{$t('documents.uploadResultDesc', { count: uploadResult.count })}</p>
              <ul class="result-list">
                {#each uploadResult.items as item}
                  <li>{item.original_filename || item.stored_filename}</li>
                {/each}
              </ul>
            </div>
          {/if}
        </article>

        <article class="result-card workspace-setup__sidebar">
          <h4>{$t('overview.statusTitle')}</h4>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('overview.statusLabel')}</dt>
              <dd>{collectionStateLabel(workspaceState)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusFiles')}</dt>
              <dd>{formatCount(effectiveFileCount)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusUpdated')}</dt>
              <dd>{formatDate(workspace.collection.updated_at || workspace.artifacts.updated_at)}</dd>
            </div>
          </dl>

          {#if filesLoading}
            <div class="status" role="status" aria-live="polite">{$t('documents.listLoading')}</div>
          {:else if filesError}
            <div class="status status--error" role="alert">{filesError}</div>
          {:else if collectionFiles.length}
            <div class="detail-section">
              <div class="detail-section__title">{$t('documents.listTitle')}</div>
              <ul class="result-list workspace-file-list">
                {#each collectionFiles.slice(0, 6) as file}
                  <li>{getFileLabel(file)}</li>
                {/each}
              </ul>
            </div>
          {:else}
            <p class="note">{$t('documents.listEmptyDesc')}</p>
          {/if}
        </article>
      </div>
    </section>

    <section class="card">
      <div class="card-header-inline">
        <div>
          <h3>{$t('overview.afterUploadTitle')}</h3>
          <p class="meta-text">{$t('overview.afterUploadLead')}</p>
        </div>
      </div>

      <div class="workspace-preview-grid">
        {#each setupPreviewKeys as key}
          <article class="result-card workspace-preview-card">
            <div class="table-title">{$t(`overview.capabilities.${key}`)}</div>
            <p class="result-text">{compactPreviewLead(key)}</p>
          </article>
        {/each}
      </div>
    </section>
  {:else if isProcessingState}
    <section class="card">
      <div class="result-grid result-grid--tasks">
        <article class="result-card">
          <h3>{processingTitle()}</h3>
          <p class="result-text">{processingBody()}</p>

          {#if actionStatus}
            <div class={`status ${actionStatusTone(actionStatus)}`} role="status">{actionStatus}</div>
          {/if}

          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('overview.statusLatestTask')}</dt>
              <dd>{workspace.latest_task ? formatTaskStatus(workspace.latest_task.status) : '--'}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusStage')}</dt>
              <dd>{workspace.latest_task ? formatTaskStage(workspace.latest_task.current_stage) : '--'}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusProgress')}</dt>
              <dd>{workspace.latest_task ? formatPercent(workspace.latest_task.progress_percent) : '--'}</dd>
            </div>
          </dl>

          <div class="detail-section">
            <div class="detail-section__title">{$t('overview.statusWorkflowTitle')}</div>
            <div class="detail-chips">
              {#each workflowRows() as [key, status]}
                <span class={`detail-chip ${stageIsActionable(status as any) ? '' : 'detail-chip--muted'}`}>
                  {$t(`collection.tabs.${key}`)}: {formatWorkflowStatus(status)}
                </span>
              {/each}
            </div>
          </div>

          {#if workspace.latest_task?.errors.length}
            <div class="status status--error" role="alert">{workspace.latest_task.errors.join(' | ')}</div>
          {:else if workspace.latest_task?.warnings.length}
            <div class="status" role="status">{workspace.latest_task.warnings.join(' | ')}</div>
          {/if}
        </article>

        <article class="result-card">
          <h3>{$t('documents.listTitle')}</h3>
          <p class="meta-text">{$t('overview.filesCount', { count: collectionFiles.length })}</p>

          {#if filesLoading}
            <div class="status" role="status" aria-live="polite">{$t('documents.listLoading')}</div>
          {:else if filesError}
            <div class="status status--error" role="alert">{filesError}</div>
          {:else if !collectionFiles.length}
            <p class="note">{$t('documents.listEmptyDesc')}</p>
          {:else}
            <div class="table-wrapper">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>{$t('documents.tableName')}</th>
                    <th>{$t('documents.tableStatus')}</th>
                    <th>{$t('documents.tableCreated')}</th>
                  </tr>
                </thead>
                <tbody>
                  {#each collectionFiles as file}
                    <tr>
                      <td>{getFileLabel(file)}</td>
                      <td>{file.status}</td>
                      <td>{formatDate(file.created_at)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </article>
      </div>

      {#if workspace.warnings.length}
        <div class="detail-section">
          <div class="detail-section__title">{$t('overview.warningsTitle')}</div>
          <ul class="result-list">
            {#each workspace.warnings as item}
              <li>{item}</li>
            {/each}
          </ul>
        </div>
      {/if}
    </section>
  {:else}
    <section class="card">
      <div class="result-grid result-grid--tasks">
        <article class="result-card">
          <h4>{$t('overview.statusTitle')}</h4>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('overview.statusLabel')}</dt>
              <dd>{formatStatus(workspace.status_summary)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusFiles')}</dt>
              <dd>{formatCount(effectiveFileCount)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.statusUpdated')}</dt>
              <dd>{formatDate(workspace.collection.updated_at || workspace.artifacts.updated_at)}</dd>
            </div>
            {#if workspace.latest_task}
              <div class="detail-row">
                <dt>{$t('overview.statusLatestTask')}</dt>
                <dd>{formatTaskStatus(workspace.latest_task.status)}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('overview.statusStage')}</dt>
                <dd>{formatTaskStage(workspace.latest_task.current_stage)}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('overview.statusProgress')}</dt>
                <dd>{formatPercent(workspace.latest_task.progress_percent)}</dd>
              </div>
            {/if}
          </dl>
        </article>

        <article class="result-card">
          <h4>{collectionStateTitle(workspaceState)}</h4>
          <p class="result-text">{collectionStateBody(workspaceState)}</p>

          {#if actionStatus}
            <div class={`status ${actionStatusTone(actionStatus)}`} role="status">{actionStatus}</div>
          {/if}

          <div class="detail-section">
            <div class="detail-section__title">{$t('overview.statusWorkflowTitle')}</div>
            <p class="meta-text">{$t('overview.statusWorkflowLead')}</p>
          </div>
          <div class="detail-chips">
            {#each workflowRows() as [key, status]}
              <span class={`detail-chip ${stageIsActionable(status as any) ? '' : 'detail-chip--muted'}`}>
                {$t(`collection.tabs.${key}`)}: {formatWorkflowStatus(status)}
              </span>
            {/each}
          </div>
        </article>

        <article class="result-card">
          <h4>{$t('overview.documentSummaryTitle')}</h4>
          <p class="meta-text">{$t('overview.documentSummaryLead')}</p>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('overview.documentSummaryTotal')}</dt>
              <dd>{workspace.document_summary.total_documents}</dd>
            </div>
            {#each documentTypeRows() as [label, count]}
              <div class="detail-row">
                <dt>{label}</dt>
                <dd>{count}</dd>
              </div>
            {/each}
          </dl>

          {#if protocolSuitabilityRows().length}
            <div class="detail-section">
              <div class="detail-section__title">{$t('overview.protocolSuitabilityTitle')}</div>
              <div class="detail-chips">
                {#each protocolSuitabilityRows() as [label, count]}
                  <span class="detail-chip">{label}: {count}</span>
                {/each}
              </div>
            </div>
          {/if}
        </article>
      </div>

      {#if workspace.warnings.length}
        <div class="detail-section">
          <div class="detail-section__title">{$t('overview.warningsTitle')}</div>
          <ul class="result-list">
            {#each workspace.warnings as item}
              <li>{item}</li>
            {/each}
          </ul>
        </div>
      {/if}
    </section>

    <section class="card">
      <div class="card-header-inline">
        <div>
          <h3>{$t('overview.primaryViewsTitle')}</h3>
          <p class="meta-text">{$t('overview.primaryViewsLead')}</p>
          <p class="note">{$t('overview.resultsFlow')}</p>
        </div>
      </div>

      <div class="result-grid result-grid--tasks">
        {#each primaryViewKeys as key}
          <article class="result-card">
            <div class="table-main">
              <div class="table-title">{$t(`overview.capabilities.${key}`)}</div>
              <div class="table-sub">{viewLead(key)}</div>
            </div>
            <div class="detail-section">
              <div class="detail-section__title">{$t('overview.viewStatusTitle')}</div>
              <div class="detail-chips">
                <span class={`detail-chip ${showViewAction(key) ? '' : 'detail-chip--muted'}`}>
                  {surfaceStatusLabel(viewState(key))}
                </span>
              </div>
              <p class="note">{surfaceStatusNote(viewState(key))}</p>
            </div>
            {#if showViewAction(key)}
              <div class="table-actions">
                <a class="btn btn--ghost btn--small" href={viewLink(key)}>
                  {viewActionLabel(key)}
                </a>
              </div>
            {/if}
          </article>
        {/each}
      </div>
    </section>

    {#if showAdditionalViews}
      <section class="card">
        <div class="card-header-inline">
          <div>
            <h3>{$t('overview.additionalViewsTitle')}</h3>
            <p class="meta-text">{$t('overview.additionalViewsLead')}</p>
          </div>
        </div>

        <div class="result-grid result-grid--tasks">
          {#if protocolState !== 'not_applicable'}
            <article class="result-card">
              <div class="table-main">
                <div class="table-title">{$t('overview.capabilities.protocol')}</div>
                <div class="table-sub">{viewLead('protocol')}</div>
              </div>
              <div class="detail-section">
                <div class="detail-section__title">{$t('overview.viewStatusTitle')}</div>
                <div class="detail-chips">
                  <span class={`detail-chip ${showViewAction('protocol') ? '' : 'detail-chip--muted'}`}>
                    {surfaceStatusLabel(protocolState)}
                  </span>
                </div>
                <p class="note">{surfaceStatusNote(protocolState)}</p>
              </div>
              {#if showViewAction('protocol')}
                <div class="table-actions">
                  <a class="btn btn--ghost btn--small" href={viewLink('protocol')}>
                    {viewActionLabel('protocol')}
                  </a>
                </div>
              {/if}
            </article>
          {/if}

          {#if graphState === 'ready'}
            <article class="result-card">
              <div class="table-main">
                <div class="table-title">{$t('overview.capabilities.graph')}</div>
                <div class="table-sub">{viewLead('graph')}</div>
              </div>
              <div class="detail-section">
                <div class="detail-section__title">{$t('overview.viewStatusTitle')}</div>
                <div class="detail-chips">
                  <span class="detail-chip">{surfaceStatusLabel(graphState)}</span>
                </div>
                <p class="note">{surfaceStatusNote(graphState)}</p>
              </div>
              <div class="table-actions">
                <a class="btn btn--ghost btn--small" href={viewLink('graph')}>
                  {viewActionLabel('graph')}
                </a>
              </div>
            </article>
          {/if}
        </div>
      </section>
    {/if}

    <section id="files" class="card">
      <details class="advanced">
        <summary>{$t('overview.uploadTitle')}</summary>
        <p class="note">{$t('overview.uploadLead')}</p>

        <div class="table-actions">
          <button class="btn btn--ghost btn--small" type="button" on:click={browseFiles}>
            {$t('overview.addMorePapersCta')}
          </button>
        </div>

        {#if uploadError}
          <div class="status status--error" role="alert">{uploadError}</div>
        {/if}

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
            <div class="dropzone-files">{$t('documents.selectedCount', { count: selectedFiles.length })}</div>
          {/if}
        </div>

        <div class="table-actions">
          <button class="btn btn--primary" type="button" on:click={submitUpload} disabled={uploadLoading || !selectedFiles.length}>
            {uploadLoading ? $t('documents.uploading') : $t('documents.upload')}
          </button>
        </div>

        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>{$t('documents.tableName')}</th>
                <th>{$t('documents.tableStatus')}</th>
                <th>{$t('documents.tableSize')}</th>
                <th>{$t('documents.tableCreated')}</th>
              </tr>
            </thead>
            <tbody>
              {#each collectionFiles as file}
                <tr>
                  <td>{getFileLabel(file)}</td>
                  <td>{file.status}</td>
                  <td>{formatBytes(file.size_bytes)}</td>
                  <td>{formatDate(file.created_at)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </details>
    </section>

    <section class="card">
      <details class="advanced" bind:open={advancedOpen}>
        <summary>{$t('overview.advancedTitle')}</summary>
        <p class="note">{$t('overview.advancedLead')}</p>

        <div class="result-grid result-grid--tasks">
          <section class="result-card">
            <h4>{$t('tasks.title')}</h4>
            {#if workspace.recent_tasks.length}
              <div class="table-wrapper">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>{$t('tasks.tableStatus')}</th>
                      <th>{$t('tasks.tableStage')}</th>
                      <th>{$t('tasks.tableProgress')}</th>
                      <th>{$t('home.tableUpdated')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each workspace.recent_tasks as task}
                      <tr>
                        <td>{formatTaskStatus(task.status)}</td>
                        <td>{formatTaskStage(task.current_stage)}</td>
                        <td>{formatPercent(task.progress_percent)}</td>
                        <td>{formatDate(task.finished_at || task.updated_at || task.created_at)}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {:else}
              <p class="note">{$t('overview.noTasks')}</p>
            {/if}
          </section>

          <section id="advanced-settings" class="result-card">
            <h4>{$t('settings.title')}</h4>
            <dl class="detail-list">
              <div class="detail-row">
                <dt>{$t('create.nameLabel')}</dt>
                <dd>{workspace.collection.name || '--'}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('create.descLabel')}</dt>
                <dd>{workspace.collection.description || '--'}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('tasks.tableCreated')}</dt>
                <dd>{formatDate(workspace.collection.created_at)}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('home.tableUpdated')}</dt>
                <dd>{formatDate(workspace.collection.updated_at)}</dd>
              </div>
            </dl>
          </section>
        </div>

        <section id="advanced-reports" class="result-grid result-grid--tasks">
          <div class="result-card">
            <h4>{$t('reports.title')}</h4>
            <p class="meta-text">{$t('reports.degradedLead')}</p>
            <p class="note">{$t('reports.degradedNote')}</p>
          </div>

          <div class="result-card">
            <div class="detail-section">
              <div class="detail-section__title">{$t('reports.degradedTitle')}</div>
              <p class="result-text">{$t('reports.degradedBody')}</p>
            </div>
          </div>
        </section>
      </details>
    </section>
  {/if}
{/if}
