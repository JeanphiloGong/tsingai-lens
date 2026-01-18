<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { errorMessage } from './_shared/api';
  import { createCollection, collections, fetchCollections } from './_shared/collections';
  import type { Collection } from './_shared/collections';
  import { getBaseUrlValue, validateBaseUrl } from './_shared/base';
  import { language, t } from './_shared/i18n';

  let loading = false;
  let error = '';
  let isCreateOpen = false;
  let name = '';
  let description = '';
  let defaultConfig = true;
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
    defaultConfig = true;
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
      const result = await createCollection(name.trim());
      await loadCollections();
      closeCreate();
      if (result?.id) {
        await goto(`/collections/${result.id}`);
      }
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

  function formatStatus(status?: string) {
    if (!status) return $t('home.statusUnknown');
    if (status === 'ready') return $t('home.statusReady');
    if (status === 'empty') return $t('home.statusEmpty');
    return status;
  }

  function formatCount(value: unknown) {
    if (typeof value === 'number') return String(value);
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
      const base = validateBaseUrl(getBaseUrlValue());
      const url = `${base}/retrieval/graphml?collection_id=${encodeURIComponent(
        collectionId
      )}&include_community=true`;
      const response = await fetch(url);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const fileName = `graph-${collectionId}-${Date.now()}.graphml`;
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

  function hasArtifacts(collection: Collection) {
    if (collection.status === 'ready') return true;
    if (typeof collection.entity_count === 'number') return collection.entity_count > 0;
    if (typeof collection.document_count === 'number') return collection.document_count > 0;
    return false;
  }

  async function runIndex(collectionId: string, isUpdateRun: boolean) {
    try {
      setRowMessage(collectionId, isUpdateRun ? $t('home.reindexing') : $t('home.indexing'));
      await fetch(`${validateBaseUrl(getBaseUrlValue())}/retrieval/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          collection_id: collectionId,
          method: 'standard',
          is_update_run: isUpdateRun,
          verbose: false
        })
      }).then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
      });
      setRowMessage(collectionId, isUpdateRun ? $t('home.reindexStarted') : $t('home.indexStarted'));
    } catch (err) {
      setRowMessage(collectionId, errorMessage(err), 'error');
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
            <th>{$t('home.tableEntities')}</th>
            <th>{$t('home.tableUpdated')}</th>
            <th>{$t('home.tableActions')}</th>
          </tr>
        </thead>
        <tbody>
          {#each $collections as collection}
            <tr>
              <td>
                <div class="table-main">
                  <div class="table-title">{collection.name || collection.id}</div>
                  <div class="table-sub">{collection.id}</div>
                </div>
              </td>
              <td>{formatStatus(collection.status)}</td>
              <td>{formatCount(collection.document_count)}</td>
              <td>{formatCount(collection.entity_count)}</td>
              <td>{formatDate(collection.updated_at || collection.created_at)}</td>
              <td>
                <div class="table-actions">
                  <a class="btn btn--ghost btn--small" href={`/collections/${collection.id}`}>
                    {$t('home.actionOpen')}
                  </a>
                  <button
                    class="btn btn--ghost btn--small"
                    type="button"
                    on:click={() => exportGraph(collection.id)}
                  >
                    {$t('home.actionExport')}
                  </button>
                  <button
                    class="btn btn--ghost btn--small"
                    type="button"
                    on:click={() => runIndex(collection.id, hasArtifacts(collection))}
                  >
                    {hasArtifacts(collection) ? $t('home.actionReindex') : $t('home.actionIndex')}
                  </button>
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
    on:click={closeCreate}
    on:keydown={handleBackdropKeydown}
  >
    <div class="modal" role="dialog" aria-modal="true" tabindex="-1" on:click|stopPropagation>
      <div class="modal-header">
        <h3>{$t('create.title')}</h3>
      </div>
      <form on:submit={submitCreate}>
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
          <input
            id="collection-desc"
            class="input"
            bind:value={description}
            placeholder={$t('create.descPlaceholder')}
            disabled
          />
          <p class="meta-text">{$t('create.descHelper')}</p>
        </div>
        <div class="toggle-row">
          <label>
            <input type="checkbox" bind:checked={defaultConfig} disabled />
            {$t('create.defaultConfigLabel')}
          </label>
          <span class="meta-text">{$t('create.defaultConfigHelper')}</span>
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
