<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let loading = false;
  let error = '';
  let result: unknown = null;
  let configs: string[] = [];

  async function loadConfigs() {
    error = '';
    result = null;
    configs = [];

    loading = true;
    try {
      const data = await requestJson('/retrieval/configs', { method: 'GET' });
      result = data;
      if (Array.isArray(data)) {
        configs = data.map(String);
      } else if (data && typeof data === 'object') {
        const record = data as Record<string, unknown>;
        const list = record.configs ?? record.items ?? record.files ?? [];
        if (Array.isArray(list)) {
          configs = list.map(String);
        }
      }
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('configsList.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('configsList.eyebrow')}</p>
    <h1>{$t('configsList.title')}</h1>
    <p class="lead">{$t('configsList.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">GET /retrieval/configs</span>
  <h3>{$t('configsList.cardTitle')}</h3>
  <button class="btn btn--primary" type="button" on:click={loadConfigs} disabled={loading}>
    {loading ? $t('configsList.loading') : $t('configsList.load')}
  </button>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
  {#if configs.length}
    <div class="list">
      {#each configs as config}
        <a class="btn btn--ghost list-button" href={`/configs/view?name=${encodeURIComponent(config)}`}>
          {config}
        </a>
      {/each}
    </div>
  {:else if result !== null}
    <pre class="code-block">{formatResult(result)}</pre>
  {/if}
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/configs">{ $t('actions.backConfigs') }</a>
  <a class="btn btn--primary" href="/configs/view">{ $t('actions.viewConfig') }</a>
</div>
