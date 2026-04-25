<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { errorMessage } from './_shared/api';
  import {
    createCollection,
    collections,
    deleteCollection,
    fetchCollections,
    type Collection
  } from './_shared/collections';
  import { buildCollectionGraphmlUrl } from './_shared/graph';
  import { language, t } from './_shared/i18n';
  import { createBuildTask } from './_shared/tasks';

  const statusFilters = ['all', 'complete', 'processing', 'attention'] as const;
  type StatusFilter = (typeof statusFilters)[number];

  const futureCards = [
    {
      key: 'researchFactDb',
      icon: 'DB'
    },
    {
      key: 'benchmark',
      icon: 'BM'
    },
    {
      key: 'experimentPlan',
      icon: 'EX'
    },
    {
      key: 'closedLoop',
      icon: 'AI'
    }
  ];

  let loading = false;
  let error = '';
  let isCreateOpen = false;
  let name = '';
  let description = '';
  let createLoading = false;
  let createError = '';
  let notice = '';
  let deletingCollectionId = '';
  let rowMessages: Record<string, { message: string; type: 'info' | 'error' }> = {};
  let searchTerm = '';
  let statusFilter: StatusFilter = 'all';
  let openRowMenuId = '';

  $: locale = $language === 'zh' ? 'zh-CN' : 'en-US';
  $: sortedCollections = [...$collections].sort(compareCollectionsByUpdated);
  $: latestCollectionId = sortedCollections[0]?.id ?? '';
  $: visibleCollections = sortedCollections.filter((collection) => {
    const query = searchTerm.trim().toLowerCase();
    const matchesQuery =
      !query ||
      collection.name?.toLowerCase().includes(query) ||
      collection.description?.toLowerCase().includes(query);

    return matchesQuery && matchesStatusFilter(collection.status, statusFilter);
  });
  $: if (
    $page.url?.pathname === '/' &&
    $page.url.searchParams.get('create') === 'collection' &&
    !isCreateOpen
  ) {
    openCreate();
  }

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

  function compareCollectionsByUpdated(left: Collection, right: Collection) {
    const leftTime = left.updated_at ?? left.created_at ?? '';
    const rightTime = right.updated_at ?? right.created_at ?? '';
    return rightTime.localeCompare(leftTime);
  }

  function setNotice(message: string) {
    notice = message;
    window.setTimeout(() => {
      if (notice === message) {
        notice = '';
      }
    }, 3000);
  }

  function openCreate() {
    isCreateOpen = true;
    createError = '';
    openRowMenuId = '';
  }

  function closeCreate() {
    isCreateOpen = false;
    name = '';
    description = '';
    createError = '';

    if ($page.url?.searchParams.get('create') === 'collection') {
      void goto('/', { replaceState: true, noScroll: true });
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
        description: description.trim()
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
    return new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    })
      .format(date)
      .replace(',', '');
  }

  function formatCount(value: unknown) {
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    if (typeof value === 'string' && value.trim() !== '') return value;
    return $t('home.metricsPlaceholder');
  }

  function getStatusGroup(status?: string | null) {
    const normalized = status?.toLowerCase() ?? '';
    if (normalized === 'processing') return 'processing';
    if (normalized === 'attention_required' || normalized === 'failed') return 'attention';
    if (
      normalized === 'ready' ||
      normalized === 'graph_ready' ||
      normalized === 'document_profiled' ||
      normalized === 'comparison_pending' ||
      normalized === 'partial_ready'
    ) {
      return 'complete';
    }
    return 'neutral';
  }

  function matchesStatusFilter(status: string | null | undefined, filter: StatusFilter) {
    if (filter === 'all') return true;
    return getStatusGroup(status) === filter;
  }

  function statusLabel(status?: string | null) {
    const group = getStatusGroup(status);
    if (group === 'complete') return $t('home.statusDisplay.complete');
    if (group === 'processing') return $t('home.statusDisplay.processing');
    if (group === 'attention') return $t('home.statusDisplay.attention');
    return $t('home.statusDisplay.pending');
  }

  function nextStep(collection: Collection) {
    const group = getStatusGroup(collection.status);
    if (group === 'processing') {
      return {
        label: $t('home.nextProgress'),
        href: `/collections/${collection.id}`
      };
    }

    if (group === 'complete') {
      return {
        label: $t('home.nextCompare'),
        href: `/collections/${collection.id}/comparisons`
      };
    }

    return {
      label: $t('home.nextWorkspace'),
      href: `/collections/${collection.id}`
    };
  }

  function toggleRowMenu(collectionId: string) {
    openRowMenuId = openRowMenuId === collectionId ? '' : collectionId;
  }

  function setRowMessage(id: string, message: string, type: 'info' | 'error' = 'info') {
    rowMessages = { ...rowMessages, [id]: { message, type } };
    window.setTimeout(() => {
      const { [id]: _, ...rest } = rowMessages;
      rowMessages = rest;
    }, 3000);
  }

  async function exportGraph(collectionId: string) {
    openRowMenuId = '';
    try {
      setRowMessage(collectionId, $t('home.exporting'));
      const response = await fetch(
        buildCollectionGraphmlUrl(collectionId, { maxNodes: 200, minWeight: 0 })
      );
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

  async function runBuild(collection: Collection) {
    openRowMenuId = '';
    if (!collection.paper_count) {
      setRowMessage(collection.id, $t('home.indexNoFiles'), 'error');
      return;
    }

    try {
      setRowMessage(collection.id, $t('home.indexing'));
      await createBuildTask(collection.id);
      setRowMessage(collection.id, $t('home.indexStarted'));
    } catch (err) {
      setRowMessage(collection.id, errorMessage(err), 'error');
    }
  }

  async function removeCollection(collection: Collection) {
    openRowMenuId = '';
    if (deletingCollectionId) return;

    const name = collection.name?.trim() || $t('collection.unknownName');
    if (!window.confirm($t('home.deleteConfirm', { name }))) {
      return;
    }

    deletingCollectionId = collection.id;
    setRowMessage(collection.id, $t('home.deleting'));

    try {
      await deleteCollection(collection.id);
      setNotice($t('home.deleted', { name }));
    } catch (err) {
      setRowMessage(collection.id, errorMessage(err), 'error');
    } finally {
      deletingCollectionId = '';
    }
  }
</script>

<svelte:head>
  <title>{$t('home.title')}</title>
</svelte:head>

<section class="home-hero">
  <p class="home-eyebrow">{$t('home.eyebrow')}</p>
  <h1>{$t('home.title')}</h1>
  <p class="home-lead">{$t('home.lead')}</p>
  <div class="home-actions" aria-label={$t('home.heroActionsLabel')}>
    <button class="home-button home-button--primary" type="button" on:click={openCreate}>
      <span aria-hidden="true">+</span>
      {$t('home.primaryAction')}
    </button>
    {#if latestCollectionId}
      <a
        class="home-button home-button--secondary"
        href={`/collections/${latestCollectionId}/documents`}
      >
        <span aria-hidden="true">^</span>
        {$t('home.secondaryAction')}
      </a>
    {:else}
      <button class="home-button home-button--secondary" type="button" on:click={openCreate}>
        <span aria-hidden="true">^</span>
        {$t('home.secondaryAction')}
      </button>
    {/if}
  </div>
</section>

<section class="recent-card" aria-labelledby="recent-collections-title">
  <div class="recent-card__header">
    <div class="section-heading">
      <span class="section-icon" aria-hidden="true">R</span>
      <div>
        <h2 id="recent-collections-title">{$t('home.recentTitle')}</h2>
        <p>{$t('home.recentSubtitle')}</p>
      </div>
    </div>
    <div class="recent-controls">
      <label class="sr-only" for="collection-search">{$t('home.searchLabel')}</label>
      <div class="search-field">
        <span aria-hidden="true">/</span>
        <input
          id="collection-search"
          bind:value={searchTerm}
          type="search"
          placeholder={$t('home.searchPlaceholder')}
        />
      </div>
      <label class="sr-only" for="collection-status-filter">{$t('home.filterLabel')}</label>
      <select id="collection-status-filter" bind:value={statusFilter} class="filter-select">
        {#each statusFilters as filter}
          <option value={filter}>{$t(`home.filter.${filter}`)}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if loading}
    <div class="home-status" role="status" aria-live="polite">{$t('home.loading')}</div>
  {/if}

  {#if error}
    <div class="home-status home-status--error" role="alert">{error}</div>
  {/if}

  {#if notice}
    <div class="home-status" role="status" aria-live="polite">{notice}</div>
  {/if}

  {#if !visibleCollections.length && !loading}
    <div class="empty-panel">
      <h3>{$collections.length ? $t('home.noResultsTitle') : $t('home.emptyTitle')}</h3>
      <p>{$collections.length ? $t('home.noResultsDesc') : $t('home.emptyDesc')}</p>
      {#if !$collections.length}
        <button class="home-button home-button--primary" type="button" on:click={openCreate}>
          <span aria-hidden="true">+</span>
          {$t('home.emptyCta')}
        </button>
      {/if}
    </div>
  {:else if visibleCollections.length}
    <div class="collections-table-wrap">
      <table class="collections-table">
        <thead>
          <tr>
            <th>{$t('home.tableName')}</th>
            <th>{$t('home.tableStatus')}</th>
            <th>{$t('home.tableDocs')}</th>
            <th>{$t('home.tableUpdated')}</th>
            <th>{$t('home.tableNext')}</th>
            <th>{$t('home.tableActions')}</th>
          </tr>
        </thead>
        <tbody>
          {#each visibleCollections as collection}
            {@const step = nextStep(collection)}
            {@const statusGroup = getStatusGroup(collection.status)}
            <tr>
              <td>
                <div class="collection-main">
                  <span>{collection.name || $t('collection.unknownName')}</span>
                  {#if collection.description}
                    <small>{collection.description}</small>
                  {/if}
                </div>
              </td>
              <td>
                <span
                  class="status-badge"
                  class:complete={statusGroup === 'complete'}
                  class:processing={statusGroup === 'processing'}
                  class:attention={statusGroup === 'attention'}
                  class:neutral={statusGroup === 'neutral'}
                >
                  {statusLabel(collection.status)}
                </span>
              </td>
              <td>{formatCount(collection.paper_count)}</td>
              <td>{formatDate(collection.updated_at || collection.created_at)}</td>
              <td>
                <a class="next-link" href={step.href}>
                  {step.label}
                  <span aria-hidden="true">&gt;</span>
                </a>
              </td>
              <td>
                <div class="row-actions">
                  <a class="enter-link" href={`/collections/${collection.id}`}
                    >{$t('home.actionEnter')}</a
                  >
                  <div class="row-menu">
                    <button
                      class="icon-button"
                      type="button"
                      aria-label={$t('home.moreActions', {
                        name: collection.name || $t('collection.unknownName')
                      })}
                      aria-expanded={openRowMenuId === collection.id}
                      on:click={() => toggleRowMenu(collection.id)}
                    >
                      ...
                    </button>
                    {#if openRowMenuId === collection.id}
                      <div class="row-menu__panel">
                        <button type="button" on:click={() => runBuild(collection)}>
                          {$t('home.actionIndex')}
                        </button>
                        <button type="button" on:click={() => exportGraph(collection.id)}>
                          {$t('home.actionExport')}
                        </button>
                        <button
                          type="button"
                          class="danger-menu-item"
                          disabled={deletingCollectionId === collection.id}
                          on:click={() => removeCollection(collection)}
                        >
                          {deletingCollectionId === collection.id
                            ? $t('home.deleting')
                            : $t('home.actionDelete')}
                        </button>
                      </div>
                    {/if}
                  </div>
                </div>
                {#if rowMessages[collection.id]}
                  <div
                    class={`row-message ${rowMessages[collection.id].type === 'error' ? 'row-message--error' : ''}`}
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

    <div class="collection-list">
      {#each visibleCollections as collection}
        {@const step = nextStep(collection)}
        {@const statusGroup = getStatusGroup(collection.status)}
        <article class="collection-list-card">
          <div class="collection-list-card__header">
            <div class="collection-main">
              <span>{collection.name || $t('collection.unknownName')}</span>
              {#if collection.description}
                <small>{collection.description}</small>
              {/if}
            </div>
            <span
              class="status-badge"
              class:complete={statusGroup === 'complete'}
              class:processing={statusGroup === 'processing'}
              class:attention={statusGroup === 'attention'}
              class:neutral={statusGroup === 'neutral'}
            >
              {statusLabel(collection.status)}
            </span>
          </div>
          <div class="collection-list-card__meta">
            <span>{$t('home.tableDocs')}: {formatCount(collection.paper_count)}</span>
            <span
              >{$t('home.tableUpdated')}: {formatDate(
                collection.updated_at || collection.created_at
              )}</span
            >
          </div>
          <div class="collection-list-card__actions">
            <a class="next-link" href={step.href}>
              {step.label}
              <span aria-hidden="true">&gt;</span>
            </a>
            <a class="enter-link" href={`/collections/${collection.id}`}>{$t('home.actionEnter')}</a
            >
          </div>
          {#if rowMessages[collection.id]}
            <div
              class={`row-message ${rowMessages[collection.id].type === 'error' ? 'row-message--error' : ''}`}
              role="status"
              aria-live="polite"
            >
              {rowMessages[collection.id].message}
            </div>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</section>

<section class="future-workspace" aria-labelledby="future-workspace-title">
  <div class="section-heading section-heading--future">
    <span class="section-icon" aria-hidden="true">*</span>
    <div>
      <h2 id="future-workspace-title">{$t('home.futureTitle')}</h2>
      <p>{$t('home.futureSubtitle')}</p>
    </div>
  </div>
  <div class="future-grid">
    {#each futureCards as card}
      <article class="future-card">
        <div class="future-card__icon" aria-hidden="true">{card.icon}</div>
        <h3>{$t(`home.future.${card.key}.title`)}</h3>
        <p>{$t(`home.future.${card.key}.desc`)}</p>
        <span>{$t('home.comingSoon')}</span>
      </article>
    {/each}
  </div>
</section>

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

<style>
  .home-hero {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 8px 0 0;
  }

  .home-eyebrow {
    margin: 0;
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 500;
    line-height: 16px;
  }

  .home-hero h1 {
    margin: 0;
    color: var(--text-primary);
    font-size: 48px;
    font-weight: 700;
    line-height: 56px;
    letter-spacing: 0;
  }

  .home-lead {
    max-width: 680px;
    margin: 0;
    color: var(--text-secondary);
    font-size: 18px;
    line-height: 28px;
  }

  .home-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 8px;
  }

  .home-button,
  .enter-link,
  .icon-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid transparent;
    cursor: pointer;
    font-weight: 600;
    transition:
      background 0.18s ease,
      border-color 0.18s ease,
      color 0.18s ease,
      transform 0.18s ease,
      box-shadow 0.18s ease;
  }

  .home-button {
    min-height: 44px;
    gap: 8px;
    padding: 0 18px;
    border-radius: var(--radius-md);
    font-size: 14px;
    line-height: 20px;
  }

  .home-button--primary {
    border-color: var(--brand-primary);
    background: var(--brand-primary);
    color: #fff;
    box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
  }

  .home-button--primary:hover {
    border-color: var(--brand-primary-hover);
    background: var(--brand-primary-hover);
  }

  .home-button--secondary {
    border-color: var(--border-strong);
    background: #fff;
    color: var(--text-primary);
  }

  .home-button--secondary:hover {
    border-color: #cbd5e1;
    background: #f8fafc;
  }

  .home-button:active,
  .enter-link:active,
  .icon-button:active {
    transform: scale(0.98);
  }

  .recent-card {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 24px;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    background: var(--surface-card);
    box-shadow: 0 6px 20px rgba(15, 23, 42, 0.05);
  }

  .recent-card__header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }

  .section-heading {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    min-width: 0;
  }

  .section-heading h2 {
    margin: 0;
    color: var(--text-primary);
    font-size: 24px;
    font-weight: 600;
    line-height: 32px;
  }

  .section-heading p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 22px;
  }

  .section-icon {
    display: inline-flex;
    width: 40px;
    height: 40px;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--brand-border);
    border-radius: 999px;
    background: var(--brand-soft);
    color: var(--brand-primary);
    font-size: 12px;
    font-weight: 700;
    line-height: 1;
  }

  .recent-controls {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 12px;
  }

  .search-field {
    display: flex;
    width: 280px;
    height: 40px;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: #fff;
    color: var(--text-tertiary);
    transition:
      border-color 0.18s ease,
      box-shadow 0.18s ease;
  }

  .search-field:focus-within {
    border-color: var(--brand-primary);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
  }

  .search-field input {
    width: 100%;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text-primary);
    font-size: 14px;
    line-height: 22px;
  }

  .search-field input::placeholder {
    color: var(--text-tertiary);
  }

  .filter-select {
    width: 132px;
    height: 40px;
    padding: 0 12px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: #fff;
    color: var(--text-primary);
    font-size: 14px;
    font-weight: 500;
    line-height: 22px;
  }

  .filter-select:focus {
    border-color: var(--brand-primary);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
    outline: 0;
  }

  .home-status {
    border: 1px solid var(--info-border);
    border-radius: var(--radius-md);
    background: var(--info-bg);
    color: var(--info-text);
    padding: 10px 12px;
    font-size: 14px;
    line-height: 22px;
  }

  .home-status--error {
    border-color: var(--danger-border);
    background: var(--danger-bg);
    color: var(--danger-text);
  }

  .empty-panel {
    display: grid;
    justify-items: center;
    gap: 10px;
    padding: 36px 16px;
    text-align: center;
  }

  .empty-panel h3 {
    margin: 0;
    color: var(--text-primary);
    font-size: 18px;
    font-weight: 600;
    line-height: 26px;
  }

  .empty-panel p {
    max-width: 460px;
    margin: 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 22px;
  }

  .collections-table-wrap {
    overflow-x: auto;
  }

  .collections-table {
    width: 100%;
    min-width: 820px;
    border-collapse: collapse;
    color: var(--text-primary);
  }

  .collections-table th,
  .collections-table td {
    height: 56px;
    padding: 0 16px;
    border-bottom: 1px solid #eef2f7;
    text-align: left;
    vertical-align: middle;
    font-size: 14px;
    font-weight: 500;
    line-height: 22px;
    white-space: nowrap;
  }

  .collections-table th {
    height: 44px;
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
    line-height: 18px;
  }

  .collections-table tbody tr {
    transition: background 0.18s ease;
  }

  .collections-table tbody tr:hover {
    background: #f8fafc;
  }

  .collections-table tbody tr:last-child td {
    border-bottom: 0;
  }

  .collection-main {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
  }

  .collection-main span {
    color: var(--text-primary);
    font-weight: 600;
  }

  .collection-main small {
    max-width: 280px;
    overflow: hidden;
    color: var(--text-tertiary);
    font-size: 12px;
    font-weight: 400;
    line-height: 18px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .status-badge {
    display: inline-flex;
    height: 24px;
    align-items: center;
    border: 1px solid var(--border-default);
    border-radius: 999px;
    padding: 0 8px;
    font-size: 12px;
    font-weight: 500;
    line-height: 18px;
  }

  .status-badge.complete {
    border-color: var(--success-border);
    background: var(--success-bg);
    color: var(--success-text);
  }

  .status-badge.processing {
    border-color: var(--warning-border);
    background: var(--warning-bg);
    color: var(--warning-text);
  }

  .status-badge.attention {
    border-color: var(--danger-border);
    background: var(--danger-bg);
    color: var(--danger-text);
  }

  .status-badge.neutral {
    border-color: #e2e8f0;
    background: #f1f5f9;
    color: var(--text-secondary);
  }

  .next-link {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--brand-primary);
    font-size: 14px;
    font-weight: 600;
    line-height: 22px;
  }

  .next-link:hover {
    color: var(--brand-primary-hover);
  }

  .row-actions {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .enter-link {
    height: 36px;
    padding: 0 16px;
    border-color: var(--border-strong);
    border-radius: var(--radius-sm);
    background: #fff;
    color: var(--text-primary);
    font-size: 14px;
    line-height: 22px;
  }

  .enter-link:hover {
    border-color: #cbd5e1;
    background: #f8fafc;
  }

  .icon-button {
    width: 36px;
    height: 36px;
    border-color: transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: 15px;
    letter-spacing: 1px;
  }

  .icon-button:hover {
    border-color: var(--border-strong);
    background: #f8fafc;
    color: var(--text-primary);
  }

  .row-menu {
    position: relative;
  }

  .row-menu__panel {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 5;
    display: grid;
    min-width: 148px;
    gap: 4px;
    padding: 6px;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-md);
    background: #fff;
    box-shadow: var(--shadow-sm);
  }

  .row-menu__panel button {
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--text-primary);
    cursor: pointer;
    padding: 8px 10px;
    text-align: left;
    font-size: 13px;
    line-height: 20px;
  }

  .row-menu__panel button:hover {
    background: #f8fafc;
  }

  .row-menu__panel button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .row-menu__panel .danger-menu-item {
    color: var(--danger-text);
  }

  .row-message {
    margin-top: 8px;
    color: var(--info-text);
    font-size: 12px;
    line-height: 18px;
    white-space: normal;
  }

  .row-message--error {
    color: var(--danger-text);
  }

  .collection-list {
    display: none;
  }

  .future-workspace {
    display: grid;
    gap: 16px;
    margin-top: -8px;
  }

  .section-heading--future .section-icon {
    background: #fff;
  }

  .future-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }

  .future-card {
    display: flex;
    min-height: 170px;
    flex-direction: column;
    gap: 12px;
    padding: 20px;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    background: #fff;
    transition:
      border-color 0.18s ease,
      box-shadow 0.18s ease,
      transform 0.18s ease;
  }

  .future-card:hover {
    border-color: #d0dbea;
    box-shadow: var(--shadow-sm);
    transform: translateY(-2px);
  }

  .future-card__icon {
    display: inline-flex;
    width: 40px;
    height: 40px;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--brand-border);
    border-radius: var(--radius-md);
    background: var(--brand-soft);
    color: var(--brand-primary);
    font-size: 12px;
    font-weight: 700;
  }

  .future-card h3 {
    margin: 0;
    color: var(--text-primary);
    font-size: 18px;
    font-weight: 600;
    line-height: 26px;
  }

  .future-card p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 22px;
  }

  .future-card span {
    display: inline-flex;
    width: max-content;
    height: 24px;
    align-items: center;
    margin-top: auto;
    border-radius: 999px;
    background: #f1f5f9;
    color: var(--text-tertiary);
    padding: 0 8px;
    font-size: 12px;
    font-weight: 500;
    line-height: 18px;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
  }

  :global(:root[data-theme='dark']) .recent-card,
  :global(:root[data-theme='dark']) .future-card,
  :global(:root[data-theme='dark']) .collection-list-card {
    border-color: var(--border-default);
    background: var(--surface-card);
  }

  :global(:root[data-theme='dark']) .home-button--secondary,
  :global(:root[data-theme='dark']) .search-field,
  :global(:root[data-theme='dark']) .filter-select,
  :global(:root[data-theme='dark']) .enter-link,
  :global(:root[data-theme='dark']) .row-menu__panel {
    border-color: var(--border-strong);
    background: rgba(12, 20, 34, 0.82);
    color: var(--text-primary);
  }

  :global(:root[data-theme='dark']) .collections-table tbody tr:hover,
  :global(:root[data-theme='dark']) .row-menu__panel button:hover,
  :global(:root[data-theme='dark']) .icon-button:hover {
    background: rgba(90, 150, 255, 0.14);
  }

  :global(:root[data-theme='dark']) .collections-table th,
  :global(:root[data-theme='dark']) .collections-table td {
    border-bottom-color: var(--border-default);
  }

  :global(:root[data-theme='dark']) .status-badge.neutral,
  :global(:root[data-theme='dark']) .future-card span {
    border-color: var(--border-default);
    background: rgba(120, 140, 180, 0.16);
    color: var(--text-tertiary);
  }

  @media (max-width: 1279px) {
    .home-hero h1 {
      font-size: 40px;
      line-height: 48px;
    }

    .future-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 900px) {
    .recent-card__header {
      align-items: flex-start;
      flex-direction: column;
    }

    .recent-controls {
      width: 100%;
      justify-content: flex-start;
    }

    .search-field {
      width: min(100%, 360px);
    }
  }

  @media (max-width: 767px) {
    .home-hero h1 {
      font-size: 32px;
      line-height: 40px;
    }

    .home-lead {
      font-size: 16px;
      line-height: 24px;
    }

    .home-actions,
    .recent-controls {
      align-items: stretch;
      flex-direction: column;
    }

    .home-button,
    .search-field,
    .filter-select {
      width: 100%;
    }

    .recent-card {
      padding: 20px;
    }

    .collections-table-wrap {
      display: none;
    }

    .collection-list {
      display: grid;
      gap: 12px;
    }

    .collection-list-card {
      display: grid;
      gap: 12px;
      padding: 16px;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: #fff;
    }

    .collection-list-card__header,
    .collection-list-card__actions {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .collection-list-card__meta {
      display: grid;
      gap: 4px;
      color: var(--text-tertiary);
      font-size: 12px;
      line-height: 18px;
    }

    .future-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
