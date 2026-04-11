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

  function docTypeLabel(value: DocumentProfile['doc_type']) {
    if (value === 'experimental') return $t('profiles.docTypeExperimental');
    if (value === 'review') return $t('profiles.docTypeReview');
    if (value === 'mixed') return $t('profiles.docTypeMixed');
    return $t('profiles.docTypeUncertain');
  }

  function extractableLabel(value: DocumentProfile['protocol_extractable']) {
    if (value === 'yes') return $t('profiles.extractableYes');
    if (value === 'partial') return $t('profiles.extractablePartial');
    if (value === 'no') return $t('profiles.extractableNo');
    return $t('profiles.extractableUncertain');
  }

  function warningsFor(profile: DocumentProfile) {
    return profile.parsing_warnings.join(' | ') || '--';
  }

  function signalsFor(profile: DocumentProfile) {
    return profile.protocol_extractability_signals.join(' | ') || '--';
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
        <option value="">{$t('profiles.allOption')}</option>
        <option value="experimental">{$t('profiles.docTypeExperimental')}</option>
        <option value="review">{$t('profiles.docTypeReview')}</option>
        <option value="mixed">{$t('profiles.docTypeMixed')}</option>
        <option value="uncertain">{$t('profiles.docTypeUncertain')}</option>
      </select>
    </div>
    <div class="field">
      <label for="extractable">{$t('profiles.filterExtractable')}</label>
      <select id="extractable" class="select" bind:value={extractable}>
        <option value="">{$t('profiles.allOption')}</option>
        <option value="yes">{$t('profiles.extractableYes')}</option>
        <option value="partial">{$t('profiles.extractablePartial')}</option>
        <option value="no">{$t('profiles.extractableNo')}</option>
        <option value="uncertain">{$t('profiles.extractableUncertain')}</option>
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
            <dt>{$t('profiles.totalLabel')}</dt>
            <dd>{response.summary.total_documents}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.docTypeExperimental')}</dt>
            <dd>{response.summary.doc_type_counts.experimental}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.docTypeReview')}</dt>
            <dd>{response.summary.doc_type_counts.review}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.docTypeMixed')}</dt>
            <dd>{response.summary.doc_type_counts.mixed}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.docTypeUncertain')}</dt>
            <dd>{response.summary.doc_type_counts.uncertain}</dd>
          </div>
        </dl>
      </article>

      <article class="result-card">
        <h3>{$t('profiles.filterExtractable')}</h3>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>{$t('profiles.extractableYes')}</dt>
            <dd>{response.summary.protocol_extractable_counts.yes}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.extractablePartial')}</dt>
            <dd>{response.summary.protocol_extractable_counts.partial}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.extractableNo')}</dt>
            <dd>{response.summary.protocol_extractable_counts.no}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('profiles.extractableUncertain')}</dt>
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
              <th>{$t('profiles.tableDocument')}</th>
              <th>{$t('profiles.tableType')}</th>
              <th>{$t('profiles.tableProtocol')}</th>
              <th>{$t('profiles.tableConfidence')}</th>
              <th>{$t('profiles.tableWarnings')}</th>
              <th>{$t('profiles.tableActions')}</th>
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
                <td>{docTypeLabel(item.doc_type)}</td>
                <td>
                  <div class="table-main">
                    <div class="table-title">{extractableLabel(item.protocol_extractable)}</div>
                    <div class="table-sub">{$t('profiles.signalsLabel')}: {signalsFor(item)}</div>
                  </div>
                </td>
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
