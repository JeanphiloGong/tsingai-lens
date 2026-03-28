<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { errorMessage } from './_shared/api';
  import { createCollection, collections, fetchCollections, type Collection } from './_shared/collections';
  import { buildCollectionGraphmlUrl } from './_shared/graph';
  import { language, t } from './_shared/i18n';
  import { createIndexTask } from './_shared/tasks';

  let loading = false;
  let error = '';
  let isCreateOpen = false;
  let name = '';
  let description = '';
  let defaultMethod = 'standard';
  let createLoading = false;
  let createError = '';
  let rowMessages: Record<string, { message: string; type: 'info' | 'error' }> = {};

  $: locale = $language === 'zh' ? 'zh-CN' : 'en-US';

  onMount(async () => {
    await loadCollections();
  });

  async function loadCollections() {
    error = '';
    loading = true;
    try {
      await fetchCollections();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }

  function openCreate() {
    isCreateOpen = true;
    createError = '';
  }

  function closeCreate() {
    isCreateOpen = false;
    name = '';
    description = '';
    defaultMethod = 'standard';
    createError = '';
  }

  function openCollection(collectionId: string) {
    goto(`/collections/${collectionId}`);
  }

  function handleRowKeydown(event: KeyboardEvent, collectionId: string) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openCollection(collectionId);
    }
  }

  function handleBackdropKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeCreate();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      closeCreate();
    }
  }

  async function submitCreate(event: SubmitEvent) {
    event.preventDefault();
    createError = '';

    if (!name.trim()) {
      createError = $t('create.errorName');
      return;
    }

    createLoading = true;
    try {
      const result = await createCollection({
        name: name.trim(),
        description: description.trim(),
        defaultMethod
      });
      closeCreate();
      await loadCollections();
      await goto(`/collections/${result.id}`);
    } catch (err) {
      createError = errorMessage(err);
    } finally {
      createLoading = false;
    }
  }

  function formatDate(value?: string) {
    if (!value) return $t('home.updatedPlaceholder');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(locale);
  }

  function formatStatus(status?: string | null) {
    if (!status) return $t('home.statusUnknown');

    const key = `home.status.${status}`;
    const translated = $t(key);
    return translated === key ? status : translated;
  }

  function formatCount(value: unknown) {
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    if (typeof value === 'string' && value.trim() !== '') return value;
    return $t('home.metricsPlaceholder');
  }

  function setRowMessage(id: string, message: string, type: 'info' | 'error' = 'info') {
    rowMessages = { ...rowMessages, [id]: { message, type } };
    window.setTimeout(() => {
      const { [id]: _, ...rest } = rowMessages;
      rowMessages = rest;
    }, 3000);
  }

  async function exportGraph(collectionId: string) {
    try {
      setRowMessage(collectionId, $t('home.exporting'));
      const response = await fetch(buildCollectionGraphmlUrl(collectionId, { maxNodes: 200, minWeight: 0 }));
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get('content-disposition') ?? '';
      const matched = disposition.match(/filename="(.+?)"/i);
      const fileName = matched?.[1] ?? `graph-${collectionId}-${Date.now()}.graphml`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(objectUrl);
      setRowMessage(collectionId, $t('home.exported'));
    } catch (err) {
      setRowMessage(collectionId, errorMessage(err), 'error');
    }
  }

  async function runIndex(collection: Collection) {
    if (!collection.paper_count) {
      setRowMessage(collection.id, $t('home.indexNoFiles'), 'error');
      return;
    }

    try {
      setRowMessage(collection.id, $t('home.indexing'));
      const task = await createIndexTask(collection.id, {
        method: collection.default_method ?? 'standard',
        isUpdateRun: false,
        verbose: false
      });
      setRowMessage(collection.id, $t('home.indexStarted', { taskId: task.task_id }));
    } catch (err) {
      setRowMessage(collection.id, errorMessage(err), 'error');
    }
  }
</script>

<svelte:head>
  <title>{$t('home.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('home.eyebrow')}</p>
    <h1>{$t('home.title')}</h1>
    <p class="lead">{$t('home.lead')}</p>
  </div>
</section>

<section class="collection-toolbar">
  <button class="btn btn--primary" type="button" on:click={openCreate}>
    {$t('home.primaryAction')}
  </button>
</section>

{#if loading}
  <div class="status" role="status" aria-live="polite">{$t('home.loading')}</div>
{/if}

{#if error}
  <div class="status status--error" role="alert">{error}</div>
{/if}

{#if !$collections.length && !loading}
  <section class="card empty-state">
    <h3>{$t('home.emptyTitle')}</h3>
    <p>{$t('home.emptyDesc')}</p>
    <button class="btn btn--primary" type="button" on:click={openCreate}>
      {$t('home.emptyCta')}
    </button>
  </section>
{:else if $collections.length}
  <section class="card">
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('home.tableName')}</th>
            <th>{$t('home.tableStatus')}</th>
            <th>{$t('home.tableDocs')}</th>
            <th>{$t('home.tableMethod')}</th>
            <th>{$t('home.tableUpdated')}</th>
            <th>{$t('home.tableActions')}</th>
          </tr>
        </thead>
        <tbody>
          {#each $collections as collection}
            <tr
              class="data-row data-row--clickable"
              role="link"
              tabindex="0"
              aria-label={$t('home.openRowLabel', { name: collection.name || collection.id })}
              on:click={() => openCollection(collection.id)}
              on:keydown={(event) => handleRowKeydown(event, collection.id)}
            >
              <td>
                <div class="table-main">
                  <div class="table-title">{collection.name || collection.id}</div>
                  <div class="table-sub">{collection.id}</div>
                  {#if collection.description}
                    <div class="table-sub">{collection.description}</div>
                  {/if}
                </div>
              </td>
              <td>{formatStatus(collection.status)}</td>
              <td>{formatCount(collection.paper_count)}</td>
              <td>{collection.default_method || 'standard'}</td>
              <td>{formatDate(collection.updated_at || collection.created_at)}</td>
              <td>
                <div class="table-actions">
                  <button
                    class="btn btn--ghost btn--small"
                    type="button"
                    on:click|stopPropagation={() => exportGraph(collection.id)}
                  >
                    {$t('home.actionExport')}
                  </button>
                  <button
                    class="btn btn--ghost btn--small"
                    type="button"
                    on:click|stopPropagation={() => runIndex(collection)}
                  >
                    {$t('home.actionIndex')}
                  </button>
                  <a
                    class="btn btn--ghost btn--small"
                    href={`/collections/${collection.id}/tasks`}
                    on:click|stopPropagation
                  >
                    {$t('home.actionTasks')}
                  </a>
                </div>
                {#if rowMessages[collection.id]}
                  <div
                    class={`status ${rowMessages[collection.id].type === 'error' ? 'status--error' : ''}`}
                    role="status"
                    aria-live="polite"
                  >
                    {rowMessages[collection.id].message}
                  </div>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{/if}

{#if isCreateOpen}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="0"
    aria-label={$t('create.cancel')}
    on:click|self={closeCreate}
    on:keydown={handleBackdropKeydown}
  >
    <div class="modal" role="dialog" aria-modal="true" tabindex="-1">
      <div class="modal-header">
        <h3>{$t('create.title')}</h3>
      </div>
      <form class="modal-form" on:submit={submitCreate}>
        <div class="field">
          <label for="collection-name">{$t('create.nameLabel')}</label>
          <input
            id="collection-name"
            class="input"
            bind:value={name}
            placeholder={$t('create.namePlaceholder')}
            required
          />
        </div>
        <div class="field">
          <label for="collection-desc">{$t('create.descLabel')}</label>
          <textarea
            id="collection-desc"
            class="textarea"
            bind:value={description}
            placeholder={$t('create.descPlaceholder')}
            rows="3"
          ></textarea>
          <span class="meta-text">{$t('create.descHelper')}</span>
        </div>
        <div class="field">
          <label for="collection-method">{$t('create.methodLabel')}</label>
          <select id="collection-method" class="select" bind:value={defaultMethod}>
            <option value="standard">standard</option>
            <option value="fast">fast</option>
          </select>
        </div>

        {#if createError}
          <div class="status status--error" role="alert">{createError}</div>
        {/if}

        <div class="modal-actions">
          <button class="btn btn--ghost" type="button" on:click={closeCreate}>
            {$t('create.cancel')}
          </button>
          <button class="btn btn--primary" type="submit" disabled={createLoading}>
            {createLoading ? $t('create.creating') : $t('create.submit')}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}
