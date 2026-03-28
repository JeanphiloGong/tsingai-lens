<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { errorMessage } from '../../_shared/api';
  import { t } from '../../_shared/i18n';
  import { createIndexTask, getTask, getTaskArtifacts, isTaskActive, type ArtifactStatus, type Task } from '../../_shared/tasks';
  import { fetchWorkspaceOverview, type WorkspaceOverview } from '../../_shared/workspace';

  let workspace: WorkspaceOverview | null = null;
  let loading = false;
  let error = '';
  let latestArtifacts: ArtifactStatus | null = null;
  let actionStatus = '';
  let loadedCollectionId = '';
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  $: collectionId = $page.params.id ?? '';
  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadWorkspace();
  }

  onDestroy(() => {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
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
      refreshTask(taskId).catch(() => null);
    }, 2500);
  }

  async function refreshTask(taskId: string) {
    const [task, artifacts] = await Promise.all([getTask(taskId), getTaskArtifacts(taskId)]);
    latestArtifacts = artifacts;

    if (workspace) {
      workspace = {
        ...workspace,
        latest_task: task,
        recent_tasks: workspace.recent_tasks.map((item, index) => (index === 0 ? task : item))
      };
    }

    if (isTaskActive(task)) {
      schedulePoll(task.task_id);
    } else {
      clearPoll();
      await loadWorkspace(false);
    }
  }

  async function loadWorkspace(showLoading = true) {
    error = '';
    if (showLoading) loading = true;
    try {
      workspace = await fetchWorkspaceOverview(collectionId);
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
    } finally {
      loading = false;
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

  async function startIndex() {
    if (!workspace?.file_count) {
      actionStatus = $t('overview.indexNoFiles');
      return;
    }

    actionStatus = '';
    try {
      const task = await createIndexTask(collectionId, {
        method: workspace.collection.default_method ?? 'standard',
        isUpdateRun: false,
        verbose: false
      });
      actionStatus = $t('overview.indexStarted', { taskId: task.task_id });
      workspace = {
        ...workspace,
        latest_task: task,
        recent_tasks: [task, ...workspace.recent_tasks.filter((item) => item.task_id !== task.task_id)].slice(0, 5)
      };
      schedulePoll(task.task_id);
    } catch (err) {
      actionStatus = errorMessage(err);
    }
  }
</script>

<svelte:head>
  <title>{$t('overview.title')}</title>
</svelte:head>

<section class="card fade-up">
  <p class="lead">{$t('overview.lead')}</p>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('overview.loading')}</div>
  {:else if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if workspace}
    <div class="status-row">
      <span class="label">{$t('overview.statusLabel')}</span>
      <span class="status status--neutral">{formatStatus(workspace.status_summary)}</span>
      <span class="meta-text">{$t('overview.updatedAt', { time: formatDate(workspace.artifacts.updated_at) })}</span>
    </div>

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
        <h3>{$t('overview.artifactsTitle')}</h3>
        <p class="meta-text">{$t('overview.artifactsLead')}</p>
      </div>
      <button class="btn btn--ghost btn--small" type="button" on:click={() => loadWorkspace()}>
        {$t('overview.refresh')}
      </button>
    </div>
    <div class="detail-chips">
      {#each artifactRows() as [key, ready]}
        <span class={`detail-chip ${ready ? '' : 'detail-chip--muted'}`}>
          {$t(`overview.artifacts.${key}`)}: {ready ? $t('overview.ready') : $t('overview.pending')}
        </span>
      {/each}
    </div>
  </section>

  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('overview.latestTaskTitle')}</h3>
        <p class="meta-text">{$t('overview.latestTaskLead')}</p>
      </div>
      {#if workspace.file_count > 0}
        <button class="btn btn--primary btn--small" type="button" on:click={startIndex}>
          {$t('overview.startIndex')}
        </button>
      {/if}
    </div>

    {#if actionStatus}
      <div class={`status ${actionStatus.startsWith('4') || actionStatus.startsWith('5') ? 'status--error' : ''}`} role="status">
        {actionStatus}
      </div>
    {/if}

    {#if workspace.latest_task}
      <div class="result-grid">
        <div class="result-card">
          <div class="table-main">
            <div class="table-title">{workspace.latest_task.task_id}</div>
            <div class="table-sub">{formatTaskStatus(workspace.latest_task.status)}</div>
          </div>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('tasks.tableStage')}</dt>
              <dd>{formatTaskStage(workspace.latest_task.current_stage)}</dd>
            </div>
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
            <div class="status status--error" role="alert">
              {workspace.latest_task.errors.join(' | ')}
            </div>
          {/if}
          {#if workspace.latest_task.warnings.length}
            <div class="status" role="status">{workspace.latest_task.warnings.join(' | ')}</div>
          {/if}
        </div>
        <div class="result-card">
          <h4>{$t('overview.capabilitiesTitle')}</h4>
          <div class="detail-chips">
            <span class={`detail-chip ${workspace.capabilities.can_view_graph ? '' : 'detail-chip--muted'}`}>
              {$t('overview.capabilities.graph')}
            </span>
            <span
              class={`detail-chip ${workspace.capabilities.can_view_protocol_steps ? '' : 'detail-chip--muted'}`}
            >
              {$t('overview.capabilities.steps')}
            </span>
            <span class={`detail-chip ${workspace.capabilities.can_search_protocol ? '' : 'detail-chip--muted'}`}>
              {$t('overview.capabilities.search')}
            </span>
            <span class={`detail-chip ${workspace.capabilities.can_generate_sop ? '' : 'detail-chip--muted'}`}>
              {$t('overview.capabilities.sop')}
            </span>
          </div>
        </div>
      </div>
    {:else}
      <p class="note">{$t('overview.noTasks')}</p>
    {/if}
  </section>

  <section class="card">
    <h3>{$t('overview.nextActionsTitle')}</h3>
    <div class="action-grid">
      <a class="btn btn--primary" href={`/collections/${collectionId}/documents`}>
        {$t('overview.nextUpload')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/tasks`}>
        {$t('overview.nextTasks')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/steps`}>
        {$t('overview.nextSteps')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/search`}>
        {$t('overview.nextSearch')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/sop`}>
        {$t('overview.nextSop')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/graph`}>
        {$t('overview.nextGraph')}
      </a>
    </div>
  </section>
{/if}
