<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { listCollectionFiles, uploadCollectionFiles, type CollectionFile } from '../../../_shared/files';
  import { t } from '../../../_shared/i18n';
  import {
    createIndexTask,
    getTask,
    getTaskArtifacts,
    isTaskActive,
    listCollectionTasks,
    type ArtifactStatus,
    type Task
  } from '../../../_shared/tasks';

  let collectionId = '';

  $: collectionId = $page.params.id ?? '';

  let showModal = false;
  let selectedFiles: File[] = [];
  let isDragging = false;
  let indexAfterUpload = true;
  let indexMode: 'update' | 'rebuild' = 'update';
  let method = 'standard';
  let uploadLoading = false;
  let uploadError = '';
  let uploadResult: { count: number; items: CollectionFile[] } | null = null;
  let fileInput: HTMLInputElement | null = null;
  let collectionFiles: CollectionFile[] = [];
  let filesLoading = false;
  let filesError = '';
  let currentTask: Task | null = null;
  let currentArtifacts: ArtifactStatus | null = null;
  let taskLoading = false;
  let taskError = '';
  let loadedCollectionId = '';
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  function clearPoll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function schedulePoll(taskId: string) {
    clearPoll();
    pollTimer = setTimeout(() => {
      refreshTask(taskId).catch(() => null);
    }, 2500);
  }

  onDestroy(() => {
    clearPoll();
  });

  function openModal() {
    showModal = true;
    selectedFiles = [];
    isDragging = false;
    indexAfterUpload = true;
    indexMode = 'update';
    method = 'standard';
    uploadError = '';
    uploadResult = null;
  }

  function closeModal() {
    showModal = false;
  }

  function handleBackdropKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeModal();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      closeModal();
    }
  }

  function handleFiles(fileList: FileList | null) {
    selectedFiles = fileList ? Array.from(fileList) : [];
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

  function browseFiles() {
    fileInput?.click();
  }

  function formatDate(value?: string | null) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function formatBytes(value?: number) {
    if (value === undefined || value === null || Number.isNaN(value)) return '-';
    if (value < 1024) return `${value} B`;
    const kb = value / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    const gb = mb / 1024;
    return `${gb.toFixed(1)} GB`;
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

  function formatPercent(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return `${Math.max(0, Math.min(100, Math.round(value)))}%`;
  }

  function getFileLabel(file: CollectionFile) {
    return file.original_filename || file.stored_filename || file.file_id || $t('documents.untitledFile');
  }

  function getFileSub(file: CollectionFile) {
    return file.stored_filename || file.stored_path || '';
  }

  async function loadFiles() {
    filesLoading = true;
    filesError = '';
    try {
      const data = await listCollectionFiles(collectionId);
      collectionFiles = data.items;
    } catch (err) {
      filesError = errorMessage(err);
    } finally {
      filesLoading = false;
    }
  }

  async function loadLatestTask() {
    taskError = '';
    taskLoading = true;
    try {
      const tasks = await listCollectionTasks(collectionId, { limit: 1, offset: 0 });
      currentTask = tasks.items[0] ?? null;
      currentArtifacts = currentTask ? await getTaskArtifacts(currentTask.task_id).catch(() => null) : null;
      if (currentTask && isTaskActive(currentTask)) {
        schedulePoll(currentTask.task_id);
      } else {
        clearPoll();
      }
    } catch (err) {
      taskError = errorMessage(err);
    } finally {
      taskLoading = false;
    }
  }

  async function refreshTask(taskId: string) {
    const [task, artifacts] = await Promise.all([getTask(taskId), getTaskArtifacts(taskId).catch(() => null)]);
    currentTask = task;
    currentArtifacts = artifacts;

    if (isTaskActive(task)) {
      schedulePoll(task.task_id);
    } else {
      clearPoll();
      await loadFiles();
    }
  }

  async function startIndexRun() {
    taskError = '';
    try {
      currentTask = await createIndexTask(collectionId, {
        method,
        isUpdateRun: indexMode === 'update',
        verbose: false
      });
      currentArtifacts = await getTaskArtifacts(currentTask.task_id).catch(() => null);
      schedulePoll(currentTask.task_id);
    } catch (err) {
      taskError = errorMessage(err);
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    clearPoll();
    loadFiles();
    loadLatestTask();
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
      await loadFiles();
      if (indexAfterUpload) {
        await startIndexRun();
      }
      closeModal();
    } catch (err) {
      uploadError = errorMessage(err);
    } finally {
      uploadLoading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('documents.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('documents.title')}</h2>
      <p class="lead">{$t('documents.lead')}</p>
    </div>
    <div class="table-actions">
      <button class="btn btn--ghost" type="button" on:click={startIndexRun} disabled={!collectionFiles.length}>
        {$t('documents.startIndex')}
      </button>
      <button class="btn btn--primary" type="button" on:click={openModal}>
        {$t('documents.addFiles')}
      </button>
    </div>
  </div>
</section>

<section class="card">
  <h3>{$t('documents.processingTitle')}</h3>
  {#if taskLoading}
    <div class="status" role="status" aria-live="polite">{$t('documents.processingLoading')}</div>
  {:else if taskError}
    <div class="status status--error" role="alert">{taskError}</div>
  {:else if currentTask}
    <div class="result-grid">
      <div class="result-card">
        <div class="table-main">
          <div class="table-title">{currentTask.task_id}</div>
          <div class="table-sub">{formatTaskStatus(currentTask.status)}</div>
        </div>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>{$t('tasks.tableStage')}</dt>
            <dd>{formatTaskStage(currentTask.current_stage)}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('tasks.tableProgress')}</dt>
            <dd>{formatPercent(currentTask.progress_percent)}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('tasks.tableCreated')}</dt>
            <dd>{formatDate(currentTask.created_at)}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('tasks.tableFinished')}</dt>
            <dd>{formatDate(currentTask.finished_at)}</dd>
          </div>
        </dl>
        {#if currentTask.errors.length}
          <div class="status status--error" role="alert">{currentTask.errors.join(' | ')}</div>
        {/if}
        {#if currentTask.warnings.length}
          <div class="status" role="status">{currentTask.warnings.join(' | ')}</div>
        {/if}
      </div>
      <div class="result-card">
        <h4>{$t('documents.artifactsTitle')}</h4>
        <div class="detail-chips">
          <span class={`detail-chip ${currentArtifacts?.documents_ready ? '' : 'detail-chip--muted'}`}>
            {$t('overview.artifacts.documents')}
          </span>
          <span class={`detail-chip ${currentArtifacts?.graph_ready ? '' : 'detail-chip--muted'}`}>
            {$t('overview.artifacts.graph')}
          </span>
          <span class={`detail-chip ${currentArtifacts?.graphml_ready ? '' : 'detail-chip--muted'}`}>
            {$t('overview.artifacts.graphml')}
          </span>
          <span class={`detail-chip ${currentArtifacts?.protocol_steps_ready ? '' : 'detail-chip--muted'}`}>
            {$t('overview.artifacts.protocolSteps')}
          </span>
        </div>
      </div>
    </div>
  {:else}
    <p class="note">{$t('documents.processingEmpty')}</p>
  {/if}
</section>

<section class="card">
  <h3>{$t('documents.listTitle')}</h3>
  {#if filesLoading}
    <div class="status" role="status" aria-live="polite">{$t('documents.listLoading')}</div>
  {:else if filesError}
    <div class="status status--error" role="alert">{filesError}</div>
  {:else if !collectionFiles.length}
    <p class="note">{$t('documents.listEmptyTitle')}</p>
    <p class="meta-text">{$t('documents.listEmptyDesc')}</p>
  {:else}
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
              <td>
                <div class="table-main">
                  <div class="table-title">{getFileLabel(file)}</div>
                  {#if getFileSub(file)}
                    <div class="table-sub file-meta">{getFileSub(file)}</div>
                  {/if}
                </div>
              </td>
              <td>{file.status}</td>
              <td>{formatBytes(file.size_bytes)}</td>
              <td>{formatDate(file.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

{#if uploadResult}
  <section class="card">
    <h3>{$t('documents.uploadResultTitle')}</h3>
    <p class="meta-text">{$t('documents.uploadResultDesc', { count: uploadResult.count })}</p>
    <ul class="result-list">
      {#each uploadResult.items as item}
        <li>{item.original_filename || item.stored_filename}</li>
      {/each}
    </ul>
  </section>
{/if}

{#if showModal}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="0"
    aria-label={$t('create.cancel')}
    on:click|self={closeModal}
    on:keydown={handleBackdropKeydown}
  >
    <div class="modal" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal-header">
        <div class="modal-title">
          <h3>{$t('documents.modalTitle')}</h3>
          <p class="meta-text">{$t('documents.modalLead')}</p>
        </div>
      </div>
      <div
        class={`dropzone ${isDragging ? 'dropzone--active' : ''}`}
        on:drop={handleDrop}
        on:dragover={handleDragOver}
        on:dragleave={handleDragLeave}
        on:click={browseFiles}
        role="button"
        tabindex="0"
        on:keydown={(event) => event.key === 'Enter' && browseFiles()}
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

      <div class="toggle-row">
        <label>
          <input type="checkbox" bind:checked={indexAfterUpload} />
          {$t('documents.indexAfterLabel')}
        </label>
      </div>

      <fieldset class="field fieldset">
        <legend>{$t('documents.indexModeLabel')}</legend>
        <div class="radio-group">
          <label>
            <input
              type="radio"
              name="index-mode"
              value="update"
              bind:group={indexMode}
              disabled={!indexAfterUpload}
            />
            {$t('documents.indexModeUpdate')}
          </label>
          <label>
            <input
              type="radio"
              name="index-mode"
              value="rebuild"
              bind:group={indexMode}
              disabled={!indexAfterUpload}
            />
            {$t('documents.indexModeRebuild')}
          </label>
        </div>
      </fieldset>

      <div class="field">
        <label for="index-method">{$t('documents.methodLabel')}</label>
        <select id="index-method" class="select" bind:value={method} disabled={!indexAfterUpload}>
          <option value="standard">{$t('documents.methodStandard')}</option>
          <option value="fast">{$t('documents.methodFast')}</option>
        </select>
      </div>

      {#if uploadError}
        <div class="status status--error" role="alert">{uploadError}</div>
      {/if}

      <div class="modal-actions">
        <button class="btn btn--ghost" type="button" on:click={closeModal}>
          {$t('create.cancel')}
        </button>
        <button class="btn btn--primary" type="button" on:click={submitUpload} disabled={uploadLoading}>
          {uploadLoading ? $t('documents.uploading') : $t('documents.upload')}
        </button>
      </div>
    </div>
  </div>
{/if}
