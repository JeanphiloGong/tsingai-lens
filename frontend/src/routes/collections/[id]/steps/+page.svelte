<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import {
    listProtocolSteps,
    searchProtocolSteps,
    type NormalizedValueItem,
    type ProtocolSearchResponse,
    type ProtocolStepItem
  } from '../../../_shared/protocol';
  import { t } from '../../../_shared/i18n';
  import { fetchWorkspaceOverview, type WorkspaceOverview } from '../../../_shared/workspace';

  $: collectionId = $page.params.id ?? '';

  let workspace: WorkspaceOverview | null = null;
  let query = '';
  let blockType = '';
  let limit = 20;
  let offset = 0;
  let loading = false;
  let error = '';
  let total = 0;
  let steps: ProtocolStepItem[] = [];
  let searchResult: ProtocolSearchResponse | null = null;
  let loadedCollectionId = '';

  function canViewProtocolSteps() {
    return Boolean(workspace?.capabilities.can_view_protocol_steps || workspace?.artifacts.protocol_steps_ready);
  }

  function formatConfidence(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return value.toFixed(2);
  }

  function formatScore(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return value.toFixed(3);
  }

  function hasConfidence(value?: number | null) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function paperLabel(paperTitle?: string | null) {
    return paperTitle?.trim() || $t('steps.unknownPaper');
  }

  function formatConditionValue(value?: NormalizedValueItem | null) {
    if (!value) return '';
    if (value.raw_value) return value.raw_value;
    if (typeof value.value === 'number' && value.unit) return `${value.value} ${value.unit}`;
    if (typeof value.value === 'number') return String(value.value);
    return value.status || '';
  }

  function summarizeConditions(step: ProtocolStepItem) {
    const conditions = step.conditions;
    if (!conditions) return [];

    return [
      ['T', formatConditionValue(conditions.temperature)],
      ['t', formatConditionValue(conditions.duration)],
      ['P', formatConditionValue(conditions.pressure)],
      ['atm', conditions.atmosphere || ''],
      ['env', conditions.environment || '']
    ].filter(([, value]) => Boolean(value));
  }

  function summarizeMaterials(step: ProtocolStepItem) {
    return step.materials
      .map((item) => item.name || item.formula || item.role || '')
      .filter((item) => item.trim() !== '')
      .slice(0, 5);
  }

  async function loadSteps() {
    loading = true;
    error = '';
    try {
      workspace = await fetchWorkspaceOverview(collectionId);
      if (!canViewProtocolSteps()) {
        steps = [];
        total = 0;
        searchResult = null;
        return;
      }

      const [stepResponse, stepSearchResponse] = await Promise.all([
        listProtocolSteps(collectionId, {
          blockType: blockType.trim(),
          limit,
          offset
        }),
        query.trim()
          ? searchProtocolSteps(collectionId, {
              query: query.trim(),
              limit: Math.min(limit, 10)
            })
          : Promise.resolve(null)
      ]);

      steps = stepResponse.items;
      total = stepResponse.count;
      searchResult = stepSearchResponse;
    } catch (err) {
      error = errorMessage(err);
      steps = [];
      total = 0;
      searchResult = null;
    } finally {
      loading = false;
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadSteps();
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    offset = 0;
    await loadSteps();
  }
</script>

<svelte:head>
  <title>{$t('steps.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('steps.title')}</h2>
      <p class="lead">{$t('steps.lead')}</p>
      <p class="note">{$t('steps.purpose')}</p>
    </div>
    {#if canViewProtocolSteps()}
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/sop`}>
        {$t('steps.nextSop')}
      </a>
    {:else}
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
        {$t('steps.backToWorkspace')}
      </a>
    {/if}
  </div>

  <form on:submit={submit}>
    <div class="form-grid">
      <div class="field">
        <label for="query">{$t('search.inputLabel')}</label>
        <input
          id="query"
          class="input"
          bind:value={query}
          placeholder={$t('search.placeholder')}
          disabled={!canViewProtocolSteps()}
        />
        <span class="meta-text">{$t('steps.searchHelper')}</span>
      </div>
      <div class="field">
        <label for="blockType">{$t('steps.blockTypeLabel')}</label>
        <input
          id="blockType"
          class="input"
          bind:value={blockType}
          placeholder={$t('steps.blockTypePlaceholder')}
          disabled={!canViewProtocolSteps()}
        />
      </div>
      <div class="field">
        <label for="limit">{$t('steps.limitLabel')}</label>
        <input id="limit" class="input" type="number" min="1" max="100" bind:value={limit} disabled={!canViewProtocolSteps()} />
      </div>
    </div>
    <div class="table-actions">
      <button class="btn btn--primary" type="submit" disabled={loading || !canViewProtocolSteps()}>
        {loading ? $t('steps.loading') : $t('steps.submit')}
      </button>
    </div>
  </form>

  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if workspace && !canViewProtocolSteps()}
    <div class="status" role="status">{$t('steps.notReadyBody')}</div>
  {/if}
</section>

{#if canViewProtocolSteps() && query.trim()}
  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('search.resultTitle')}</h3>
        <p class="meta-text">{$t('search.resultCount', { count: searchResult?.count ?? 0 })}</p>
      </div>
    </div>

    {#if loading}
      <div class="status" role="status" aria-live="polite">{$t('search.searching')}</div>
    {:else if searchResult && searchResult.items.length}
      <div class="result-grid">
        {#each searchResult.items as item}
          <article class="result-card">
            <div class="table-main">
              <div class="table-title">{item.action}</div>
              <div class="table-sub">{paperLabel(item.paper_title)}</div>
            </div>
            <dl class="detail-list">
              <div class="detail-row">
                <dt>{$t('search.sourcePaperLabel')}</dt>
                <dd>{paperLabel(item.paper_title)}</dd>
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

<section class="card">
  <div class="card-header-inline">
    <div>
      <h3>{$t('steps.resultTitle')}</h3>
      <p class="meta-text">{$t('steps.resultCount', { count: total })}</p>
    </div>
    {#if canViewProtocolSteps()}
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/sop`}>
        {$t('steps.nextSop')}
      </a>
    {:else}
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
        {$t('steps.backToWorkspace')}
      </a>
    {/if}
  </div>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('steps.loading')}</div>
  {:else if workspace && !canViewProtocolSteps()}
    <div class="detail-section">
      <div class="detail-section__title">{$t('steps.notReadyTitle')}</div>
      <p class="meta-text">{$t('steps.notReadyBody')}</p>
    </div>
  {:else if !steps.length}
    <p class="note">{$t('steps.empty')}</p>
  {:else}
    <div class="result-grid">
      {#each steps as step}
        <article class="result-card">
          <div class="table-main">
            <div class="table-title">
              {step.order ? `${step.order}. ` : ''}{step.action}
            </div>
            <div class="table-sub">{paperLabel(step.paper_title)}</div>
          </div>

          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('steps.sourcePaperLabel')}</dt>
              <dd>{paperLabel(step.paper_title)}</dd>
            </div>
            {#if step.phase}
              <div class="detail-row">
                <dt>{$t('steps.phaseLabel')}</dt>
                <dd>{step.phase}</dd>
              </div>
            {/if}
            {#if hasConfidence(step.confidence_score)}
              <div class="detail-row">
                <dt>{$t('steps.confidenceLabel')}</dt>
                <dd>{formatConfidence(step.confidence_score)}</dd>
              </div>
            {/if}
          </dl>

          {#if summarizeMaterials(step).length}
            <div class="detail-section">
              <div class="detail-section__title">{$t('steps.materialsTitle')}</div>
              <div class="detail-chips">
                {#each summarizeMaterials(step) as material}
                  <span class="detail-chip">{material}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if summarizeConditions(step).length}
            <div class="detail-section">
              <div class="detail-section__title">{$t('steps.conditionsTitle')}</div>
              <div class="detail-chips">
                {#each summarizeConditions(step) as [label, value]}
                  <span class="detail-chip">{label}: {value}</span>
                {/each}
              </div>
            </div>
          {/if}

          {#if step.purpose}
            <p class="result-text">{step.purpose}</p>
          {/if}

          {#if step.expected_output}
            <p class="meta-text">{$t('steps.outputLabel')}: {step.expected_output}</p>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</section>
