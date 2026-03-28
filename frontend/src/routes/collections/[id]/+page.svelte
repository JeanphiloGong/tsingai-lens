<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { errorMessage } from '../../_shared/api';
  import { listCollectionFiles, uploadCollectionFiles, type CollectionFile } from '../../_shared/files';
  import { t } from '../../_shared/i18n';
  import {
    getCommunityReportDetail,
    listCommunityReports,
    listReportPatterns,
    type ReportCommunityDetailResponse,
    type ReportCommunitySummary,
    type ReportPatternItem
  } from '../../_shared/reports';
  import {
    createIndexTask,
    getTask,
    getTaskArtifacts,
    isTaskActive,
    type ArtifactStatus,
    type Task
  } from '../../_shared/tasks';
  import { fetchWorkspaceOverview, type WorkspaceOverview } from '../../_shared/workspace';

  let workspace: WorkspaceOverview | null = null;
  let loading = false;
  let error = '';
  let latestArtifacts: ArtifactStatus | null = null;
  let actionStatus = '';
  let loadedCollectionId = '';
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

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

  let advancedOpen = false;
  let reportsLoading = false;
  let reportsLoaded = false;
  let reportsError = '';
  let detailLoading = false;
  let patterns: ReportPatternItem[] = [];
  let communities: ReportCommunitySummary[] = [];
  let selectedCommunity: ReportCommunityDetailResponse | null = null;

  $: collectionId = $page.params.id ?? '';
  $: if ($page.url.hash.startsWith('#advanced')) {
    advancedOpen = true;
  }
  $: if (advancedOpen && collectionId && !reportsLoaded && !reportsLoading) {
    void loadReports();
  }
  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    resetReports();
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

  function resetReports() {
    reportsLoading = false;
    reportsLoaded = false;
    reportsError = '';
    detailLoading = false;
    patterns = [];
    communities = [];
    selectedCommunity = null;
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
    const [task, artifacts] = await Promise.all([getTask(taskId), getTaskArtifacts(taskId).catch(() => null)]);
    latestArtifacts = artifacts;
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
      method = workspace.collection.default_method ?? 'standard';
      latestArtifacts = null;
      const latestTask = workspace.latest_task;
      if (latestTask) {
        latestArtifacts = await getTaskArtifacts(latestTask.task_id).catch(() => null);
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
      latestArtifacts = null;
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

  async function loadReports(force = false) {
    if (!force && (reportsLoading || reportsLoaded || !collectionId)) return;

    reportsLoading = true;
    reportsError = '';
    try {
      const [patternResponse, communityResponse] = await Promise.all([
        listReportPatterns(collectionId, { level: 2, limit: 6, sort: 'rating' }),
        listCommunityReports(collectionId, { level: 2, limit: 12, offset: 0, minSize: 0, sort: 'rating' })
      ]);
      patterns = patternResponse.items;
      communities = communityResponse.items;
      reportsLoaded = true;

      const first = communityResponse.items[0];
      if (first?.community_id !== undefined && first.community_id !== null) {
        await selectCommunity(String(first.community_id));
      } else {
        selectedCommunity = null;
      }
    } catch (err) {
      reportsError = errorMessage(err);
      patterns = [];
      communities = [];
      selectedCommunity = null;
    } finally {
      reportsLoading = false;
    }
  }

  async function selectCommunity(communityId: string) {
    detailLoading = true;
    reportsError = '';
    try {
      selectedCommunity = await getCommunityReportDetail(collectionId, communityId, {
        level: 2,
        entityLimit: 10,
        relationshipLimit: 10,
        documentLimit: 10
      });
    } catch (err) {
      reportsError = errorMessage(err);
      selectedCommunity = null;
    } finally {
      detailLoading = false;
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

  function artifactRows() {
    const artifacts = latestArtifacts ?? workspace?.artifacts;
    if (!artifacts) return [];

    return [
      ['documents', artifacts.documents_ready],
      ['graph', artifacts.graph_ready],
      ['graphml', artifacts.graphml_ready],
      ['sections', artifacts.sections_ready],
      ['procedureBlocks', artifacts.procedure_blocks_ready],
      ['protocolSteps', artifacts.protocol_steps_ready]
    ] as Array<[string, boolean]>;
  }

  function getFileLabel(file: CollectionFile) {
    return file.original_filename || file.stored_filename || file.file_id || $t('documents.untitledFile');
  }

  function getFileSub(file: CollectionFile) {
    return file.stored_filename || file.stored_path || '';
  }

  function primaryActionLabel() {
    if (!workspace) return $t('overview.primaryActionUpload');
    if (!workspace.file_count) return $t('overview.primaryActionUpload');
    if (workspace.latest_task && isTaskActive(workspace.latest_task)) return $t('overview.primaryActionTrack');
    if (workspace.capabilities.can_generate_sop) return $t('overview.primaryActionSop');
    if (workspace.capabilities.can_view_protocol_steps) return $t('overview.primaryActionSteps');
    return $t('overview.primaryActionProcess');
  }

  function primaryActionHelper() {
    if (!workspace) return $t('overview.primaryActionHelperUpload');
    if (!workspace.file_count) return $t('overview.primaryActionHelperUpload');
    if (workspace.latest_task && isTaskActive(workspace.latest_task)) return $t('overview.primaryActionHelperTrack');
    if (workspace.capabilities.can_generate_sop || workspace.capabilities.can_view_protocol_steps) {
      return $t('overview.primaryActionHelperResults');
    }
    return $t('overview.primaryActionHelperProcess');
  }

  function openPrimaryAction() {
    const latestTask = workspace?.latest_task;
    if (!workspace) return;

    if (!workspace.file_count) {
      location.hash = 'files';
      return;
    }

    if (latestTask && isTaskActive(latestTask)) {
      location.hash = 'activity';
      return;
    }

    if (workspace.capabilities.can_generate_sop) {
      location.href = `/collections/${collectionId}/sop`;
      return;
    }

    if (workspace.capabilities.can_view_protocol_steps) {
      location.href = `/collections/${collectionId}/steps`;
      return;
    }

    void startIndexRun();
  }

  async function startIndexRun() {
    if (!workspace?.file_count) {
      actionStatus = $t('overview.indexNoFiles');
      return;
    }

    actionStatus = '';
    try {
      const task = await createIndexTask(collectionId, {
        method,
        isUpdateRun: indexMode === 'update',
        verbose: false
      });
      mergeTask(task);
      latestArtifacts = await getTaskArtifacts(task.task_id).catch(() => latestArtifacts);
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
      if (indexAfterUpload) {
        await startIndexRun();
      }
    } catch (err) {
      uploadError = errorMessage(err);
    } finally {
      uploadLoading = false;
    }
  }

</script>

<svelte:head>
  <title>{$t('overview.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <p class="lead">{$t('overview.lead')}</p>
      {#if workspace}
        <div class="status-row">
          <span class="label">{$t('overview.statusLabel')}</span>
          <span class="status status--neutral">{formatStatus(workspace.status_summary)}</span>
          <span class="meta-text">{$t('overview.updatedAt', { time: formatDate(workspace.artifacts.updated_at) })}</span>
        </div>
      {/if}
    </div>
    <button class="btn btn--ghost btn--small" type="button" on:click={() => Promise.all([loadWorkspace(), loadFiles()])}>
      {$t('overview.refresh')}
    </button>
  </div>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('overview.loading')}</div>
  {:else if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if workspace}
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-value">{formatCount(workspace.collection.paper_count)}</div>
        <div class="stat-label">{$t('overview.metricPapers')}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{formatCount(workspace.file_count)}</div>
        <div class="stat-label">{$t('overview.metricFiles')}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{workspace.recent_tasks.length}</div>
        <div class="stat-label">{$t('overview.metricTasks')}</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{workspace.collection.default_method || 'standard'}</div>
        <div class="stat-label">{$t('overview.metricMethod')}</div>
      </div>
    </div>

    {#if workspace.collection.description}
      <p class="note">{workspace.collection.description}</p>
    {/if}
  {/if}
</section>

{#if workspace}
  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('overview.controlTitle')}</h3>
        <p class="meta-text">{$t('overview.controlLead')}</p>
      </div>
      <button class="btn btn--primary" type="button" on:click={openPrimaryAction}>
        {primaryActionLabel()}
      </button>
    </div>

    <p class="note">{primaryActionHelper()}</p>

    {#if actionStatus}
      <div class={`status ${actionStatus.startsWith('4') || actionStatus.startsWith('5') ? 'status--error' : ''}`} role="status">
        {actionStatus}
      </div>
    {/if}

    <div class="detail-chips">
      <span class={`detail-chip ${workspace.capabilities.can_view_protocol_steps ? '' : 'detail-chip--muted'}`}>
        {$t('overview.capabilities.steps')}
      </span>
      <span class={`detail-chip ${workspace.capabilities.can_generate_sop ? '' : 'detail-chip--muted'}`}>
        {$t('overview.capabilities.sop')}
      </span>
      <span class={`detail-chip ${workspace.capabilities.can_view_graph ? '' : 'detail-chip--muted'}`}>
        {$t('overview.capabilities.graph')}
      </span>
      <span class={`detail-chip ${workspace.capabilities.can_search_protocol ? '' : 'detail-chip--muted'}`}>
        {$t('overview.capabilities.search')}
      </span>
    </div>
  </section>

  <section id="files" class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('documents.title')}</h3>
        <p class="meta-text">{$t('overview.filesLead')}</p>
      </div>
      {#if collectionFiles.length}
        <button class="btn btn--ghost btn--small" type="button" on:click={startIndexRun}>
          {$t('documents.startIndex')}
        </button>
      {/if}
    </div>

    <div class="result-grid result-grid--tasks">
      <div class="result-card">
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
              <input type="radio" name="index-mode" value="update" bind:group={indexMode} disabled={!indexAfterUpload} />
              {$t('documents.indexModeUpdate')}
            </label>
            <label>
              <input type="radio" name="index-mode" value="rebuild" bind:group={indexMode} disabled={!indexAfterUpload} />
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

        <div class="table-actions">
          <button class="btn btn--primary" type="button" on:click={submitUpload} disabled={uploadLoading}>
            {uploadLoading ? $t('documents.uploading') : $t('documents.upload')}
          </button>
          <button class="btn btn--ghost" type="button" on:click={() => Promise.all([loadFiles(), loadWorkspace()])}>
            {$t('documents.listTitle')}
          </button>
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
      </div>

      <div class="result-card">
        <div class="card-header-inline">
          <div>
            <h4>{$t('documents.listTitle')}</h4>
            <p class="meta-text">{$t('overview.filesCount', { count: collectionFiles.length })}</p>
          </div>
        </div>

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
      </div>
    </div>
  </section>

  <section id="activity" class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('tasks.title')}</h3>
        <p class="meta-text">{$t('overview.activityLead')}</p>
      </div>
      {#if workspace.file_count > 0 && !(workspace.latest_task && isTaskActive(workspace.latest_task))}
        <button class="btn btn--ghost btn--small" type="button" on:click={startIndexRun}>
          {$t('overview.primaryActionProcess')}
        </button>
      {/if}
    </div>

    {#if workspace.latest_task}
      <div class="result-grid result-grid--tasks">
        <div class="result-card">
          <div class="table-main">
            <div class="table-title">{formatTaskStatus(workspace.latest_task.status)}</div>
            <div class="table-sub">{formatTaskStage(workspace.latest_task.current_stage)}</div>
          </div>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('tasks.tableProgress')}</dt>
              <dd>{formatPercent(workspace.latest_task.progress_percent)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableStarted')}</dt>
              <dd>{formatDate(workspace.latest_task.started_at || workspace.latest_task.created_at)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableFinished')}</dt>
              <dd>{formatDate(workspace.latest_task.finished_at)}</dd>
            </div>
          </dl>

          {#if workspace.latest_task.errors.length}
            <div class="status status--error" role="alert">{workspace.latest_task.errors.join(' | ')}</div>
          {/if}
          {#if workspace.latest_task.warnings.length}
            <div class="status" role="status">{workspace.latest_task.warnings.join(' | ')}</div>
          {/if}
        </div>

        <div class="result-card">
          <div class="card-header-inline">
            <div>
              <h4>{$t('overview.recentActivityTitle')}</h4>
              <p class="meta-text">{$t('tasks.resultTitle')}</p>
            </div>
          </div>

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
        </div>
      </div>
    {:else}
      <p class="note">{$t('overview.noTasks')}</p>
    {/if}
  </section>

  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('overview.artifactsTitle')}</h3>
        <p class="meta-text">{$t('overview.artifactsLead')}</p>
      </div>
    </div>

    <div class="detail-chips">
      {#each artifactRows() as [key, ready]}
        <span class={`detail-chip ${ready ? '' : 'detail-chip--muted'}`}>
          {$t(`overview.artifacts.${key}`)}: {ready ? $t('overview.ready') : $t('overview.pending')}
        </span>
      {/each}
    </div>

    <div class="result-grid result-grid--tasks">
      <div class="result-card">
        <h4>{$t('overview.capabilitiesTitle')}</h4>
        <div class="detail-chips">
          <span class={`detail-chip ${workspace.capabilities.can_view_protocol_steps ? '' : 'detail-chip--muted'}`}>
            {$t('overview.capabilities.steps')}
          </span>
          <span class={`detail-chip ${workspace.capabilities.can_search_protocol ? '' : 'detail-chip--muted'}`}>
            {$t('overview.capabilities.search')}
          </span>
          <span class={`detail-chip ${workspace.capabilities.can_generate_sop ? '' : 'detail-chip--muted'}`}>
            {$t('overview.capabilities.sop')}
          </span>
          <span class={`detail-chip ${workspace.capabilities.can_view_graph ? '' : 'detail-chip--muted'}`}>
            {$t('overview.capabilities.graph')}
          </span>
        </div>
      </div>

      <div class="result-card">
        <h4>{$t('overview.nextActionsTitle')}</h4>
        <div class="action-grid">
          <a class="btn btn--ghost btn--small" href="#files">{$t('overview.nextUpload')}</a>
          <a class="btn btn--ghost btn--small" href="#activity">{$t('overview.nextTrack')}</a>
          {#if workspace.capabilities.can_view_protocol_steps}
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/steps`}>
              {$t('overview.nextSteps')}
            </a>
          {/if}
          {#if workspace.capabilities.can_generate_sop}
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/sop`}>
              {$t('overview.nextSop')}
            </a>
          {/if}
          {#if workspace.capabilities.can_view_graph}
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/graph`}>
              {$t('overview.nextGraph')}
            </a>
          {/if}
          <a class="btn btn--ghost btn--small" href="#advanced-settings">{$t('overview.nextAdvanced')}</a>
        </div>
      </div>
    </div>
  </section>

  <section class="card">
    <details class="advanced" bind:open={advancedOpen}>
      <summary>{$t('overview.advancedTitle')}</summary>
      <p class="note">{$t('overview.advancedLead')}</p>

      <div class="result-grid result-grid--tasks">
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
              <dt>{$t('create.methodLabel')}</dt>
              <dd>{workspace.collection.default_method || 'standard'}</dd>
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

        <section class="result-card">
          <h4>{$t('overview.debugTitle')}</h4>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('overview.debugTaskId')}</dt>
              <dd>{workspace.latest_task?.task_id || '--'}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableOutput')}</dt>
              <dd>{latestArtifacts?.output_path || workspace.artifacts.output_path || '--'}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('overview.debugCollectionId')}</dt>
              <dd>{collectionId}</dd>
            </div>
          </dl>
        </section>
      </div>

      <section id="advanced-reports" class="result-grid result-grid--tasks">
        <div class="result-card">
          <div class="card-header-inline">
            <div>
              <h4>{$t('reports.title')}</h4>
              <p class="meta-text">{$t('reports.lead')}</p>
            </div>
            <button class="btn btn--ghost btn--small" type="button" on:click={() => loadReports(true)}>
              {$t('reports.submit')}
            </button>
          </div>

          {#if reportsLoading}
            <div class="status" role="status" aria-live="polite">{$t('reports.loading')}</div>
          {:else if reportsError}
            <div class="status status--error" role="alert">{reportsError}</div>
          {:else if !patterns.length && !communities.length}
            <p class="note">{$t('reports.emptyCommunities')}</p>
          {:else}
            <div class="detail-section">
              <div class="detail-section__title">{$t('reports.patternsTitle')}</div>
              <div class="result-grid">
                {#each patterns as item}
                  <article class="result-card">
                    <div class="table-title">{item.title || `${$t('reports.communityLabel')} ${item.community_id ?? '--'}`}</div>
                    <div class="table-sub">rating: {item.rating ?? '--'} · size: {item.size ?? '--'}</div>
                    <p class="result-text">{item.summary || '--'}</p>
                  </article>
                {/each}
              </div>
            </div>

            <div class="detail-section">
              <div class="detail-section__title">{$t('reports.communitiesTitle')}</div>
              <div class="table-wrapper">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>{$t('reports.communityLabel')}</th>
                      <th>{$t('reports.ratingLabel')}</th>
                      <th>{$t('reports.sizeLabel')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each communities as item}
                      <tr
                        class:selected-row={selectedCommunity?.community_id === item.community_id}
                        on:click={() => item.community_id !== undefined && item.community_id !== null && selectCommunity(String(item.community_id))}
                      >
                        <td>{item.title || item.community_id || '--'}</td>
                        <td>{item.rating ?? '--'}</td>
                        <td>{item.size ?? '--'}</td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </div>
          {/if}
        </div>

        <div class="result-card">
          {#if detailLoading}
            <div class="status" role="status" aria-live="polite">{$t('reports.detailLoading')}</div>
          {:else if selectedCommunity}
            <div class="table-main">
              <div class="table-title">{selectedCommunity.title || selectedCommunity.community_id}</div>
              <div class="table-sub">
                {$t('reports.ratingLabel')}: {selectedCommunity.rating ?? '--'} · {$t('reports.sizeLabel')}: {selectedCommunity.size ?? '--'}
              </div>
            </div>
            <p class="result-text">{selectedCommunity.summary || '--'}</p>
            <div class="detail-chips">
              <span class="detail-chip">{$t('reports.entitiesLabel')}: {selectedCommunity.entities.length}</span>
              <span class="detail-chip">{$t('reports.relationshipsLabel')}: {selectedCommunity.relationships.length}</span>
              <span class="detail-chip">{$t('reports.documentsLabel')}: {selectedCommunity.documents.length}</span>
            </div>
          {:else}
            <p class="note">{$t('reports.emptyDetail')}</p>
          {/if}
        </div>
      </section>
    </details>
  </section>
{/if}
