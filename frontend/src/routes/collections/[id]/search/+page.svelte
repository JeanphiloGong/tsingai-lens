<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { searchProtocolSteps, type ProtocolSearchResponse } from '../../../_shared/protocol';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let query = '';
  let paperId = '';
  let limit = 10;
  let loading = false;
  let error = '';
  let result: ProtocolSearchResponse | null = null;

  function formatScore(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return value.toFixed(3);
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!query.trim()) {
      error = $t('search.errorNoQuery');
      return;
    }

    loading = true;
    try {
      result = await searchProtocolSteps(collectionId, {
        query: query.trim(),
        paperId: paperId.trim(),
        limit
      });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('search.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('search.title')}</h2>
  <p class="lead">{$t('search.lead')}</p>
  <form on:submit={submit}>
    <div class="field">
      <label for="query">{$t('search.inputLabel')}</label>
      <input id="query" class="input" bind:value={query} placeholder={$t('search.placeholder')} />
      <span class="meta-text">{$t('search.exampleText')}</span>
    </div>

    <details class="advanced">
      <summary>{$t('search.advanced')}</summary>
      <div class="field">
        <label for="paperId">{$t('search.paperIdLabel')}</label>
        <input id="paperId" class="input" bind:value={paperId} placeholder={$t('search.paperIdPlaceholder')} />
      </div>
      <div class="field">
        <label for="limit">{$t('search.limitLabel')}</label>
        <input id="limit" class="input" type="number" min="1" max="100" bind:value={limit} />
      </div>
    </details>

    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('search.searching') : $t('search.submit')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

{#if result}
  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('search.resultTitle')}</h3>
        <p class="meta-text">{$t('search.resultCount', { count: result.count })}</p>
      </div>
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/steps`}>
        {$t('search.viewSteps')}
      </a>
    </div>

    {#if result.items.length}
      <div class="result-grid">
        {#each result.items as item}
          <article class="result-card">
            <div class="table-main">
              <div class="table-title">{item.action}</div>
              <div class="table-sub">{item.step_id}</div>
            </div>
            <dl class="detail-list">
              <div class="detail-row">
                <dt>{$t('search.paperIdLabel')}</dt>
                <dd>{item.paper_id}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('search.matchFieldsLabel')}</dt>
                <dd>{item.matched_fields.join(', ') || '--'}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('search.scoreLabel')}</dt>
                <dd>{formatScore(item.score)}</dd>
              </div>
            </dl>
            {#if item.excerpt}
              <p class="result-text">{item.excerpt}</p>
            {/if}
          </article>
        {/each}
      </div>
    {:else}
      <p class="note">{$t('search.noResults')}</p>
    {/if}
  </section>
{/if}
