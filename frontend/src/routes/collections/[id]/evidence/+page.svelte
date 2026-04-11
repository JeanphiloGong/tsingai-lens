<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { fetchEvidenceCards, type EvidenceCard, type EvidenceCardsResponse } from '../../../_shared/evidence';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let response: EvidenceCardsResponse | null = null;
  let loading = false;
  let error = '';
  let claimType = '';
  let traceability = '';
  let sourceType = '';
  let loadedCollectionId = '';

  $: items = (response?.items ?? []).filter((item) => {
    if (claimType && item.claim_type !== claimType) return false;
    if (traceability && item.traceability_status !== traceability) return false;
    if (sourceType && item.evidence_source_type !== sourceType) return false;
    return true;
  });

  $: claimTypes = Array.from(new Set((response?.items ?? []).map((item) => item.claim_type))).sort();

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadEvidence();
  }

  async function loadEvidence() {
    loading = true;
    error = '';
    try {
      response = await fetchEvidenceCards(collectionId);
    } catch (err) {
      error = errorMessage(err);
      response = null;
    } finally {
      loading = false;
    }
  }

  function formatConfidence(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    return value.toFixed(2);
  }

  function traceabilityLabel(value: EvidenceCard['traceability_status']) {
    if (value === 'direct') return $t('evidence.traceabilityDirect');
    if (value === 'partial') return $t('evidence.traceabilityPartial');
    return $t('evidence.traceabilityMissing');
  }

  function sourceTypeLabel(value: EvidenceCard['evidence_source_type']) {
    if (value === 'figure') return $t('evidence.sourceFigure');
    if (value === 'table') return $t('evidence.sourceTable');
    if (value === 'method') return $t('evidence.sourceMethod');
    return $t('evidence.sourceText');
  }

  function contextRows(card: EvidenceCard): Array<[string, string[]]> {
    const rows: Array<[string, string[]]> = [
      [$t('evidence.contextProcess'), card.condition_context.process],
      [$t('evidence.contextBaseline'), card.condition_context.baseline],
      [$t('evidence.contextTest'), card.condition_context.test]
    ];

    return rows.filter(([, values]) => values.length > 0);
  }
</script>

<svelte:head>
  <title>{$t('evidence.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('evidence.title')}</h2>
      <p class="lead">{$t('evidence.lead')}</p>
    </div>
    <button class="btn btn--ghost btn--small" type="button" on:click={loadEvidence}>
      {$t('overview.refresh')}
    </button>
  </div>

  <div class="form-grid">
    <div class="field">
      <label for="claimType">{$t('evidence.filterClaimType')}</label>
      <select id="claimType" class="select" bind:value={claimType}>
        <option value="">{$t('evidence.allOption')}</option>
        {#each claimTypes as item}
          <option value={item}>{item}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="traceability">{$t('evidence.filterTraceability')}</label>
      <select id="traceability" class="select" bind:value={traceability}>
        <option value="">{$t('evidence.allOption')}</option>
        <option value="direct">{$t('evidence.traceabilityDirect')}</option>
        <option value="partial">{$t('evidence.traceabilityPartial')}</option>
        <option value="missing">{$t('evidence.traceabilityMissing')}</option>
      </select>
    </div>
    <div class="field">
      <label for="sourceType">{$t('evidence.filterSourceType')}</label>
      <select id="sourceType" class="select" bind:value={sourceType}>
        <option value="">{$t('evidence.allOption')}</option>
        <option value="figure">{$t('evidence.sourceFigure')}</option>
        <option value="table">{$t('evidence.sourceTable')}</option>
        <option value="method">{$t('evidence.sourceMethod')}</option>
        <option value="text">{$t('evidence.sourceText')}</option>
      </select>
    </div>
  </div>

  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if loading}
    <div class="status" role="status">{$t('evidence.loading')}</div>
  {:else if items.length}
    <div class="result-grid">
      {#each items as item}
        <article class="result-card">
          <div class="table-main">
            <div class="table-title">{item.claim_text}</div>
            <div class="table-sub">{item.material_system}</div>
          </div>

          <dl class="detail-list">
            <div class="detail-row">
              <dt>{$t('evidence.fieldClaimType')}</dt>
              <dd>{item.claim_type}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('evidence.fieldSource')}</dt>
              <dd>{sourceTypeLabel(item.evidence_source_type)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('evidence.fieldTraceability')}</dt>
              <dd>{traceabilityLabel(item.traceability_status)}</dd>
            </div>
            <div class="detail-row">
              <dt>{$t('evidence.fieldConfidence')}</dt>
              <dd>{formatConfidence(item.confidence)}</dd>
            </div>
          </dl>

          <section class="detail-section">
            <div class="detail-section__title">{$t('evidence.anchorsTitle')}</div>
            <ul class="result-list">
              {#each item.evidence_anchors as anchor}
                <li>{anchor.label}</li>
              {/each}
            </ul>
          </section>

          {#if contextRows(item).length}
            <section class="detail-section">
              <div class="detail-section__title">{$t('evidence.contextTitle')}</div>
              <dl class="detail-list">
                {#each contextRows(item) as [label, values]}
                  <div class="detail-row">
                    <dt>{label}</dt>
                    <dd>{values.join(', ')}</dd>
                  </div>
                {/each}
              </dl>
            </section>
          {/if}

          <div class="table-actions">
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/comparisons`}>
              {$t('overview.nextComparisons')}
            </a>
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/documents`}>
              {$t('overview.nextDocuments')}
            </a>
          </div>
        </article>
      {/each}
    </div>
  {:else}
    <p class="note">{$t('evidence.empty')}</p>
  {/if}
</section>
