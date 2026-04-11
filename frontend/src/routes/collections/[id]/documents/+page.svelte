<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import {
    fetchDocumentProfiles,
    type DocumentProfile,
    type DocumentProfilesResponse
  } from '../../../_shared/documents';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let response: DocumentProfilesResponse | null = null;
  let loading = false;
  let error = '';
  let docType = '';
  let extractable = '';
  let loadedCollectionId = '';

  $: items = (response?.items ?? []).filter((item) => {
    if (docType && item.doc_type !== docType) return false;
    if (extractable && item.protocol_extractable !== extractable) return false;
    return true;
  });

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadProfiles();
  }

  async function loadProfiles() {
    loading = true;
    error = '';
    try {
      response = await fetchDocumentProfiles(collectionId);
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

  function warningsFor(profile: DocumentProfile) {
    return profile.parsing_warnings.join(' | ') || '--';
  }
</script>

<svelte:head>
  <title>{$t('profiles.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('profiles.title')}</h2>
      <p class="lead">{$t('profiles.lead')}</p>
    </div>
    <button class="btn btn--ghost btn--small" type="button" on:click={loadProfiles}>
      {$t('overview.refresh')}
    </button>
  </div>

  <div class="form-grid">
    <div class="field">
      <label for="docType">{$t('profiles.filterDocType')}</label>
      <select id="docType" class="select" bind:value={docType}>
        <option value="">All</option>
        <option value="experimental">experimental</option>
        <option value="review">review</option>
        <option value="mixed">mixed</option>
        <option value="uncertain">uncertain</option>
      </select>
    </div>
    <div class="field">
      <label for="extractable">{$t('profiles.filterExtractable')}</label>
      <select id="extractable" class="select" bind:value={extractable}>
        <option value="">All</option>
        <option value="yes">yes</option>
        <option value="partial">partial</option>
        <option value="no">no</option>
        <option value="uncertain">uncertain</option>
      </select>
    </div>
  </div>

  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if loading}
    <div class="status" role="status">{$t('profiles.loading')}</div>
  {:else if response}
    <div class="result-grid result-grid--tasks">
      <article class="result-card">
        <h3>{$t('profiles.summaryTitle')}</h3>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>Total</dt>
            <dd>{response.summary.total_documents}</dd>
          </div>
          <div class="detail-row">
            <dt>experimental</dt>
            <dd>{response.summary.doc_type_counts.experimental}</dd>
          </div>
          <div class="detail-row">
            <dt>review</dt>
            <dd>{response.summary.doc_type_counts.review}</dd>
          </div>
          <div class="detail-row">
            <dt>mixed</dt>
            <dd>{response.summary.doc_type_counts.mixed}</dd>
          </div>
          <div class="detail-row">
            <dt>uncertain</dt>
            <dd>{response.summary.doc_type_counts.uncertain}</dd>
          </div>
        </dl>
      </article>

      <article class="result-card">
        <h3>{$t('profiles.filterExtractable')}</h3>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>yes</dt>
            <dd>{response.summary.protocol_extractable_counts.yes}</dd>
          </div>
          <div class="detail-row">
            <dt>partial</dt>
            <dd>{response.summary.protocol_extractable_counts.partial}</dd>
          </div>
          <div class="detail-row">
            <dt>no</dt>
            <dd>{response.summary.protocol_extractable_counts.no}</dd>
          </div>
          <div class="detail-row">
            <dt>uncertain</dt>
            <dd>{response.summary.protocol_extractable_counts.uncertain}</dd>
          </div>
        </dl>
      </article>

      <article class="result-card">
        <h3>{$t('profiles.warningsTitle')}</h3>
        {#if response.summary.warnings.length}
          <ul class="result-list">
            {#each response.summary.warnings as item}
              <li>{item}</li>
            {/each}
          </ul>
        {:else}
          <p class="note">{$t('profiles.emptyWarnings')}</p>
        {/if}
      </article>
    </div>

    {#if items.length}
      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Type</th>
              <th>Protocol</th>
              <th>Confidence</th>
              <th>Warnings</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each items as item}
              <tr>
                <td>
                  <div class="table-main">
                    <div class="table-title">{item.title || item.document_id}</div>
                    <div class="table-sub">{item.document_id}</div>
                  </div>
                </td>
                <td>{item.doc_type}</td>
                <td>{item.protocol_extractable}</td>
                <td>{formatConfidence(item.confidence)}</td>
                <td>{warningsFor(item)}</td>
                <td>
                  <div class="table-actions">
                    <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/evidence`}>
                      {$t('overview.nextEvidence')}
                    </a>
                    <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/comparisons`}>
                      {$t('overview.nextComparisons')}
                    </a>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p class="note">{$t('profiles.empty')}</p>
    {/if}
  {/if}
</section>
