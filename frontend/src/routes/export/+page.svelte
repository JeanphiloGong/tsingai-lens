<script lang="ts">
  import { errorMessage } from '../_shared/api';
  import { getBaseUrlValue, validateBaseUrl } from '../_shared/base';
  import { t } from '../_shared/i18n';

  let outputPath = '';
  let maxNodes = 200;
  let minWeight = 0;
  let communityId = '';

  let loading = false;
  let error = '';
  let status = '';

  async function download() {
    error = '';
    status = '';
    loading = true;

    try {
      const params = new URLSearchParams();
      if (outputPath.trim()) {
        params.set('output_path', outputPath.trim());
      }
      const maxValue = Number.isFinite(maxNodes) ? maxNodes : 200;
      const minValue = Number.isFinite(minWeight) ? minWeight : 0;
      params.set('max_nodes', String(maxValue));
      params.set('min_weight', String(minValue));
      if (communityId.trim()) {
        params.set('community_id', communityId.trim());
      }

      const base = validateBaseUrl(getBaseUrlValue());
      const url = `${base}/retrieval/graphml?${params.toString()}`;
      const response = await fetch(url);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const fileName = `graph-${Date.now()}.graphml`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(objectUrl);
      status = $t('export.downloaded', { filename: fileName });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('export.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('export.eyebrow')}</p>
    <h1>{$t('export.title')}</h1>
    <p class="lead">{$t('export.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">GET /retrieval/graphml</span>
  <h3>{$t('export.cardTitle')}</h3>
  <div class="field">
    <label for="graph-output">{$t('export.outputLabel')}</label>
    <input id="graph-output" class="input" bind:value={outputPath} placeholder="/path" />
  </div>
  <div class="field">
    <label for="graph-max">{$t('export.maxNodesLabel')}</label>
    <input id="graph-max" class="input" type="number" bind:value={maxNodes} min="1" />
  </div>
  <div class="field">
    <label for="graph-weight">{$t('export.minWeightLabel')}</label>
    <input id="graph-weight" class="input" type="number" bind:value={minWeight} step="0.1" />
  </div>
  <div class="field">
    <label for="graph-community">{$t('export.communityLabel')}</label>
    <input id="graph-community" class="input" bind:value={communityId} />
  </div>
  <button class="btn btn--primary" type="button" on:click={download} disabled={loading}>
    {loading ? $t('export.preparing') : $t('export.download')}
  </button>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
  {#if status}
    <div class="status" role="status" aria-live="polite">{status}</div>
  {/if}
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/index">{ $t('actions.backIndex') }</a>
  <a class="btn btn--primary" href="/">{ $t('actions.done') }</a>
</div>
