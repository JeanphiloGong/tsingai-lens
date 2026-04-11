<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import {
    fetchComparisons,
    type ComparisonRow,
    type ComparisonsResponse
  } from '../../../_shared/comparisons';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let response: ComparisonsResponse | null = null;
  let loading = false;
  let error = '';
  let statusFilter = '';
  let materialFilter = '';
  let propertyFilter = '';
  let loadedCollectionId = '';

  $: materials = Array.from(
    new Set((response?.items ?? []).map((item) => item.material_system_normalized))
  ).sort();
  $: properties = Array.from(
    new Set((response?.items ?? []).map((item) => item.property_normalized))
  ).sort();

  $: items = (response?.items ?? []).filter((item) => {
    if (statusFilter && item.comparability_status !== statusFilter) return false;
    if (materialFilter && item.material_system_normalized !== materialFilter) return false;
    if (propertyFilter && item.property_normalized !== propertyFilter) return false;
    return true;
  });

  $: comparableCount = (response?.items ?? []).filter((item) => item.comparability_status === 'comparable').length;
  $: limitedCount = (response?.items ?? []).filter((item) => item.comparability_status === 'limited').length;
  $: notComparableCount = (response?.items ?? []).filter(
    (item) => item.comparability_status === 'not_comparable'
  ).length;
  $: insufficientCount = (response?.items ?? []).filter(
    (item) => item.comparability_status === 'insufficient'
  ).length;

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadComparisons();
  }

  async function loadComparisons() {
    loading = true;
    error = '';
    try {
      response = await fetchComparisons(collectionId);
    } catch (err) {
      error = errorMessage(err);
      response = null;
    } finally {
      loading = false;
    }
  }

  function warningText(row: ComparisonRow) {
    return row.comparability_warnings.join(' | ') || '--';
  }

  function evidenceCount(row: ComparisonRow) {
    return row.supporting_evidence_ids.length;
  }
</script>

<svelte:head>
  <title>{$t('comparisons.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('comparisons.title')}</h2>
      <p class="lead">{$t('comparisons.lead')}</p>
    </div>
    <button class="btn btn--ghost btn--small" type="button" on:click={loadComparisons}>
      {$t('overview.refresh')}
    </button>
  </div>

  <div class="result-grid result-grid--tasks">
    <article class="result-card">
      <h3>{$t('comparisons.summaryTitle')}</h3>
      <dl class="detail-list">
        <div class="detail-row">
          <dt>{$t('comparisons.comparable')}</dt>
          <dd>{comparableCount}</dd>
        </div>
        <div class="detail-row">
          <dt>{$t('comparisons.limited')}</dt>
          <dd>{limitedCount}</dd>
        </div>
        <div class="detail-row">
          <dt>{$t('comparisons.notComparable')}</dt>
          <dd>{notComparableCount}</dd>
        </div>
        <div class="detail-row">
          <dt>{$t('comparisons.insufficient')}</dt>
          <dd>{insufficientCount}</dd>
        </div>
      </dl>
    </article>
  </div>

  <div class="form-grid">
    <div class="field">
      <label for="statusFilter">{$t('comparisons.filterStatus')}</label>
      <select id="statusFilter" class="select" bind:value={statusFilter}>
        <option value="">All</option>
        <option value="comparable">comparable</option>
        <option value="limited">limited</option>
        <option value="not_comparable">not_comparable</option>
        <option value="insufficient">insufficient</option>
      </select>
    </div>
    <div class="field">
      <label for="materialFilter">{$t('comparisons.filterMaterial')}</label>
      <select id="materialFilter" class="select" bind:value={materialFilter}>
        <option value="">All</option>
        {#each materials as item}
          <option value={item}>{item}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="propertyFilter">{$t('comparisons.filterProperty')}</label>
      <select id="propertyFilter" class="select" bind:value={propertyFilter}>
        <option value="">All</option>
        {#each properties as item}
          <option value={item}>{item}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if loading}
    <div class="status" role="status">{$t('comparisons.loading')}</div>
  {:else if items.length}
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>Material</th>
            <th>Process</th>
            <th>Property</th>
            <th>Baseline</th>
            <th>Test</th>
            <th>Status</th>
            <th>{$t('comparisons.warningsLabel')}</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each items as item}
            <tr>
              <td>{item.material_system_normalized}</td>
              <td>{item.process_normalized}</td>
              <td>{item.property_normalized}</td>
              <td>{item.baseline_normalized}</td>
              <td>{item.test_condition_normalized}</td>
              <td>{item.comparability_status}</td>
              <td>{warningText(item)}</td>
              <td>
                <div class="table-actions">
                  <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/evidence`}>
                    {$t('overview.nextEvidence')} ({evidenceCount(item)})
                  </a>
                  <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/documents`}>
                    {$t('overview.nextDocuments')}
                  </a>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <p class="note">{$t('comparisons.empty')}</p>
  {/if}
</section>
