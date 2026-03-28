<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { listProtocolSteps, type NormalizedValueItem, type ProtocolStepItem } from '../../../_shared/protocol';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let paperId = '';
  let blockType = '';
  let limit = 20;
  let offset = 0;
  let loading = false;
  let error = '';
  let total = 0;
  let steps: ProtocolStepItem[] = [];
  let loadedCollectionId = '';

  function formatConfidence(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return value.toFixed(2);
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
      const response = await listProtocolSteps(collectionId, {
        paperId: paperId.trim(),
        blockType: blockType.trim(),
        limit,
        offset
      });
      steps = response.items;
      total = response.count;
    } catch (err) {
      error = errorMessage(err);
      steps = [];
      total = 0;
    } finally {
      loading = false;
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadSteps();
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
  <h2>{$t('steps.title')}</h2>
  <p class="lead">{$t('steps.lead')}</p>
  <form on:submit={submit}>
    <div class="form-grid">
      <div class="field">
        <label for="paperId">{$t('steps.paperIdLabel')}</label>
        <input id="paperId" class="input" bind:value={paperId} placeholder={$t('steps.paperIdPlaceholder')} />
      </div>
      <div class="field">
        <label for="blockType">{$t('steps.blockTypeLabel')}</label>
        <input
          id="blockType"
          class="input"
          bind:value={blockType}
          placeholder={$t('steps.blockTypePlaceholder')}
        />
      </div>
      <div class="field">
        <label for="limit">{$t('steps.limitLabel')}</label>
        <input id="limit" class="input" type="number" min="1" max="100" bind:value={limit} />
      </div>
    </div>
    <div class="table-actions">
      <button class="btn btn--primary" type="submit" disabled={loading}>
        {loading ? $t('steps.loading') : $t('steps.submit')}
      </button>
    </div>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

<section class="card">
  <div class="card-header-inline">
    <div>
      <h3>{$t('steps.resultTitle')}</h3>
      <p class="meta-text">{$t('steps.resultCount', { count: total })}</p>
    </div>
    <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/sop`}>
      {$t('steps.nextSop')}
    </a>
  </div>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('steps.loading')}</div>
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
            <div class="table-sub">{step.step_id}</div>
          </div>
          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('steps.paperIdLabel')}</dt>
              <dd>{step.paper_id}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('steps.phaseLabel')}</dt>
              <dd>{step.phase || '--'}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('steps.confidenceLabel')}</dt>
              <dd>{formatConfidence(step.confidence_score)}</dd>
            </div>
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
