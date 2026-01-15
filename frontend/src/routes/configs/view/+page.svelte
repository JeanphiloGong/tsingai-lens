<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage, requestText } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let filename = '';
  let loading = false;
  let error = '';
  let content = '';

  $: if (!filename) {
    const suggested = $page.url.searchParams.get('name');
    if (suggested) filename = suggested;
  }

  async function loadConfig(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    content = '';

    if (!filename.trim()) {
      error = $t('configsView.errorFilename');
      return;
    }

    loading = true;
    try {
      content = await requestText(`/retrieval/configs/${encodeURIComponent(filename.trim())}`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('configsView.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('configsView.eyebrow')}</p>
    <h1>{$t('configsView.title')}</h1>
    <p class="lead">{$t('configsView.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">GET /retrieval/configs/{filename}</span>
  <h3>{$t('configsView.cardTitle')}</h3>
  <form on:submit={loadConfig}>
    <div class="field">
      <label for="config-name">{$t('configsView.filenameLabel')}</label>
      <input
        id="config-name"
        class="input"
        bind:value={filename}
        placeholder="default.yaml"
        required
      />
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('configsView.loading') : $t('configsView.load')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
  {#if content}
    <pre class="code-block">{content}</pre>
  {/if}
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/configs">{ $t('actions.backConfigs') }</a>
  <a class="btn btn--primary" href="/configs/list">{ $t('actions.listConfigs') }</a>
</div>
