<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { getBaseUrlValue, validateBaseUrl } from '../../../_shared/base';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id;

  let maxNodes = 200;
  let minWeight = 0;
  let communityId = '';
  let includeCommunity = true;
  let loading = false;
  let error = '';
  let status = '';

  async function downloadGraph() {
    error = '';
    status = '';
    loading = true;

    try {
      const params = new URLSearchParams();
      params.set('collection_id', collectionId);
      params.set('max_nodes', String(maxNodes));
      params.set('min_weight', String(minWeight));
      if (communityId.trim()) {
        params.set('community_id', communityId.trim());
      }
      params.set('include_community', includeCommunity ? 'true' : 'false');

      const base = validateBaseUrl(getBaseUrlValue());
      const response = await fetch(`${base}/retrieval/graphml?${params.toString()}`);
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
      status = $t('graph.downloaded', { filename: fileName });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('graph.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('graph.title')}</h2>
  <p class="lead">{$t('graph.lead')}</p>
  <button class="btn btn--primary" type="button" on:click={downloadGraph} disabled={loading}>
    {loading ? $t('graph.downloading') : $t('graph.download')}
  </button>
  {#if status}
    <div class="status" role="status" aria-live="polite">{status}</div>
  {/if}
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

<section class="card">
  <h3>{$t('graph.filtersTitle')}</h3>
  <details class="advanced">
    <summary>{$t('graph.filtersTitle')}</summary>
    <div class="field">
      <label for="maxNodes">{$t('graph.maxNodesLabel')}</label>
      <input id="maxNodes" class="input" type="number" min="1" bind:value={maxNodes} />
    </div>
    <div class="field">
      <label for="minWeight">{$t('graph.minWeightLabel')}</label>
      <input id="minWeight" class="input" type="number" step="0.1" bind:value={minWeight} />
    </div>
    <div class="field">
      <label for="communityId">{$t('graph.communityLabel')}</label>
      <input id="communityId" class="input" bind:value={communityId} />
    </div>
    <div class="toggle-row">
      <label>
        <input type="checkbox" bind:checked={includeCommunity} />
        {$t('graph.includeCommunityLabel')}
      </label>
    </div>
  </details>
</section>

<section class="card">
  <h3>{$t('graph.statsTitle')}</h3>
  <p class="note">{$t('graph.statsPlaceholder')}</p>
</section>

<section class="card">
  <h3>{$t('graph.tipsTitle')}</h3>
  <ul class="result-list">
    <li>{$t('graph.tip1')}</li>
    <li>{$t('graph.tip2')}</li>
    <li>{$t('graph.tip3')}</li>
  </ul>
</section>
