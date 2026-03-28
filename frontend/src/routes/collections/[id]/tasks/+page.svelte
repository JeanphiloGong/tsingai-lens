<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { getTask, getTaskArtifacts, isTaskActive, listCollectionTasks, type ArtifactStatus, type Task } from '../../../_shared/tasks';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let status = '';
  let limit = 20;
  let loading = false;
  let error = '';
  let tasks: Task[] = [];
  let selectedTask: Task | null = null;
  let selectedArtifacts: ArtifactStatus | null = null;
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
      refreshSelectedTask(taskId).catch(() => null);
    }, 2500);
  }

  onDestroy(() => {
    clearPoll();
  });

  function formatDate(value?: string | null) {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function formatPercent(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return `${Math.round(value)}%`;
  }

  function formatTaskStatus(value?: string | null) {
    if (!value) return $t('tasks.statusUnknown');
    const key = `tasks.status.${value}`;
    const translated = $t(key);
    return translated === key ? value : translated;
  }

  function formatTaskStage(value?: string | null) {
    if (!value) return $t('tasks.stageUnknown');
    const key = `tasks.stage.${value}`;
    const translated = $t(key);
    return translated === key ? value : translated;
  }

  async function refreshSelectedTask(taskId: string) {
    const [task, artifacts] = await Promise.all([getTask(taskId), getTaskArtifacts(taskId).catch(() => null)]);
    selectedTask = task;
    selectedArtifacts = artifacts;
    tasks = tasks.map((item) => (item.task_id === task.task_id ? task : item));

    if (isTaskActive(task)) {
      schedulePoll(task.task_id);
    } else {
      clearPoll();
    }
  }

  async function loadTasks() {
    loading = true;
    error = '';
    try {
      const response = await listCollectionTasks(collectionId, {
        status: status.trim(),
        limit,
        offset: 0
      });
      tasks = response.items;
      selectedTask = tasks[0] ?? null;
      selectedArtifacts = selectedTask ? await getTaskArtifacts(selectedTask.task_id).catch(() => null) : null;
      if (selectedTask && isTaskActive(selectedTask)) {
        schedulePoll(selectedTask.task_id);
      } else {
        clearPoll();
      }
    } catch (err) {
      error = errorMessage(err);
      tasks = [];
      selectedTask = null;
      selectedArtifacts = null;
    } finally {
      loading = false;
    }
  }

  function selectTask(task: Task) {
    selectedTask = task;
    getTaskArtifacts(task.task_id)
      .then((artifacts) => {
        selectedArtifacts = artifacts;
      })
      .catch(() => {
        selectedArtifacts = null;
      });

    if (isTaskActive(task)) {
      schedulePoll(task.task_id);
    } else {
      clearPoll();
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadTasks();
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    await loadTasks();
  }
</script>

<svelte:head>
  <title>{$t('tasks.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('tasks.title')}</h2>
  <p class="lead">{$t('tasks.lead')}</p>
  <form on:submit={submit}>
    <div class="form-grid">
      <div class="field">
        <label for="taskStatus">{$t('tasks.filterStatusLabel')}</label>
        <select id="taskStatus" class="select" bind:value={status}>
          <option value="">{$t('tasks.filterStatusAll')}</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="completed">completed</option>
          <option value="partial_success">partial_success</option>
          <option value="failed">failed</option>
        </select>
      </div>
      <div class="field">
        <label for="taskLimit">{$t('tasks.limitLabel')}</label>
        <input id="taskLimit" class="input" type="number" min="1" max="100" bind:value={limit} />
      </div>
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('tasks.loading') : $t('tasks.submit')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

<section class="card">
  <div class="card-header-inline">
    <h3>{$t('tasks.resultTitle')}</h3>
    <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/documents`}>
      {$t('tasks.backToDocuments')}
    </a>
  </div>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('tasks.loading')}</div>
  {:else if !tasks.length}
    <p class="note">{$t('tasks.empty')}</p>
  {:else}
    <div class="result-grid result-grid--tasks">
      <div class="result-card">
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>{$t('tasks.tableTask')}</th>
                <th>{$t('tasks.tableStatus')}</th>
                <th>{$t('tasks.tableStage')}</th>
                <th>{$t('tasks.tableProgress')}</th>
              </tr>
            </thead>
            <tbody>
              {#each tasks as task}
                <tr
                  class:selected-row={selectedTask?.task_id === task.task_id}
                  on:click={() => selectTask(task)}
                >
                  <td>{task.task_id}</td>
                  <td>{formatTaskStatus(task.status)}</td>
                  <td>{formatTaskStage(task.current_stage)}</td>
                  <td>{formatPercent(task.progress_percent)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>

      <div class="result-card">
        {#if selectedTask}
          <div class="table-main">
            <div class="table-title">{selectedTask.task_id}</div>
            <div class="table-sub">{formatTaskStatus(selectedTask.status)}</div>
          </div>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('tasks.tableCreated')}</dt>
              <dd>{formatDate(selectedTask.created_at)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableStarted')}</dt>
              <dd>{formatDate(selectedTask.started_at)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableFinished')}</dt>
              <dd>{formatDate(selectedTask.finished_at)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('tasks.tableOutput')}</dt>
              <dd>{selectedTask.output_path || '--'}</dd>
            </div>
          </dl>

          {#if selectedTask.errors.length}
            <div class="status status--error" role="alert">{selectedTask.errors.join(' | ')}</div>
          {/if}
          {#if selectedTask.warnings.length}
            <div class="status" role="status">{selectedTask.warnings.join(' | ')}</div>
          {/if}

          {#if selectedArtifacts}
            <div class="detail-section">
              <div class="detail-section__title">{$t('tasks.artifactsTitle')}</div>
              <div class="detail-chips">
                <span class={`detail-chip ${selectedArtifacts.documents_ready ? '' : 'detail-chip--muted'}`}>
                  {$t('overview.artifacts.documents')}
                </span>
                <span class={`detail-chip ${selectedArtifacts.graph_ready ? '' : 'detail-chip--muted'}`}>
                  {$t('overview.artifacts.graph')}
                </span>
                <span class={`detail-chip ${selectedArtifacts.graphml_ready ? '' : 'detail-chip--muted'}`}>
                  {$t('overview.artifacts.graphml')}
                </span>
                <span class={`detail-chip ${selectedArtifacts.protocol_steps_ready ? '' : 'detail-chip--muted'}`}>
                  {$t('overview.artifacts.protocolSteps')}
                </span>
              </div>
            </div>
          {/if}
        {/if}
      </div>
    </div>
  {/if}
</section>
