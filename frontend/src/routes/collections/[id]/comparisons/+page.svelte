<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage, isHttpStatusError } from '../../../_shared/api';
  import {
    fetchComparisons,
    type ComparisonRow,
    type ComparisonsResponse
  } from '../../../_shared/comparisons';
  import { t } from '../../../_shared/i18n';
  import {
    fetchWorkspaceOverview,
    getWorkspaceSurfaceState,
    type WorkspaceOverview
  } from '../../../_shared/workspace';

  $: collectionId = $page.params.id ?? '';

  let response: ComparisonsResponse | null = null;
  let workspace: WorkspaceOverview | null = null;
  let loading = false;
  let error = '';
  let statusFilter = '';
  let materialFilter = '';
  let propertyFilter = '';
  let loadedCollectionId = '';
  let notFound = false;

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
  $: surfaceState = getWorkspaceSurfaceState(workspace, 'comparisons');
  $: showFallbackState =
    Boolean(workspace) &&
    !loading &&
    !items.length &&
    (surfaceState !== 'ready' || notFound);

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadComparisons();
  }

  async function loadComparisons() {
    loading = true;
    error = '';
    notFound = false;

    const [comparisonsResult, workspaceResult] = await Promise.allSettled([
      fetchComparisons(collectionId),
      fetchWorkspaceOverview(collectionId)
    ]);

    workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

    if (comparisonsResult.status === 'fulfilled') {
      response = comparisonsResult.value;
      loading = false;
      return;
    }

    response = null;
    notFound = isHttpStatusError(comparisonsResult.reason, 404);
    error = errorMessage(comparisonsResult.reason);
    loading = false;
  }

  function warningText(row: ComparisonRow) {
    return row.comparability_warnings.join(' | ') || '--';
  }

  function evidenceCount(row: ComparisonRow) {
    return row.supporting_evidence_ids.length;
  }

  function comparabilityLabel(status: ComparisonRow['comparability_status']) {
    if (status === 'comparable') return $t('comparisons.comparable');
    if (status === 'limited') return $t('comparisons.limited');
    if (status === 'not_comparable') return $t('comparisons.notComparable');
    return $t('comparisons.insufficient');
  }

  function stateCardTitle() {
    return $t(`overview.surfaceStateCards.${surfaceState}.title`);
  }

  function stateCardBody() {
    return $t(`overview.surfaceStateCards.${surfaceState}.body`);
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

  {#if workspace && (surfaceState === 'limited' || surfaceState === 'processing') && items.length}
    <div class="status" role="status">{stateCardBody()}</div>
  {/if}

  <div class="form-grid">
    <div class="field">
      <label for="statusFilter">{$t('comparisons.filterStatus')}</label>
      <select id="statusFilter" class="select" bind:value={statusFilter}>
        <option value="">{$t('comparisons.allOption')}</option>
        <option value="comparable">{$t('comparisons.comparable')}</option>
        <option value="limited">{$t('comparisons.limited')}</option>
        <option value="not_comparable">{$t('comparisons.notComparable')}</option>
        <option value="insufficient">{$t('comparisons.insufficient')}</option>
      </select>
    </div>
    <div class="field">
      <label for="materialFilter">{$t('comparisons.filterMaterial')}</label>
      <select id="materialFilter" class="select" bind:value={materialFilter}>
        <option value="">{$t('comparisons.allOption')}</option>
        {#each materials as item}
          <option value={item}>{item}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="propertyFilter">{$t('comparisons.filterProperty')}</label>
      <select id="propertyFilter" class="select" bind:value={propertyFilter}>
        <option value="">{$t('comparisons.allOption')}</option>
        {#each properties as item}
          <option value={item}>{item}</option>
        {/each}
      </select>
    </div>
  </div>

  {#if error && !showFallbackState}
    <div class="status status--error" role="alert">{error}</div>
  {:else if loading}
    <div class="status" role="status">{$t('comparisons.loading')}</div>
  {:else if showFallbackState}
    <article class="result-card">
      <h3>{stateCardTitle()}</h3>
      <p class="result-text">{stateCardBody()}</p>
      <div class="table-actions">
        <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
          {$t('overview.goToWorkspace')}
        </a>
      </div>
    </article>
  {:else if items.length}
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('comparisons.tableMaterial')}</th>
            <th>{$t('comparisons.tableProcess')}</th>
            <th>{$t('comparisons.tableProperty')}</th>
            <th>{$t('comparisons.tableBaseline')}</th>
            <th>{$t('comparisons.tableTest')}</th>
            <th>{$t('comparisons.tableStatus')}</th>
            <th>{$t('comparisons.warningsLabel')}</th>
            <th>{$t('comparisons.tableActions')}</th>
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
              <td>{comparabilityLabel(item.comparability_status)}</td>
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
