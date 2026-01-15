<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let file: File | null = null;
  let loading = false;
  let error = '';
  let result: unknown = null;

  function handleFileChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    file = target.files?.[0] ?? null;
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!file) {
      error = $t('configsUpload.errorFile');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    loading = true;
    try {
      result = await requestJson('/retrieval/configs/upload', {
        method: 'POST',
        body: formData
      });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('configsUpload.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('configsUpload.eyebrow')}</p>
    <h1>{$t('configsUpload.title')}</h1>
    <p class="lead">{$t('configsUpload.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">POST /retrieval/configs/upload</span>
  <h3>{$t('configsUpload.cardTitle')}</h3>
  <form on:submit={submit}>
    <div class="field">
      <label for="config-upload">{$t('configsUpload.fileLabel')}</label>
      <input
        id="config-upload"
        class="input"
        type="file"
        on:change={handleFileChange}
      />
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('configsUpload.uploading') : $t('configsUpload.submit')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
  {#if result !== null}
    <pre class="code-block">{formatResult(result)}</pre>
  {/if}
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/configs">{ $t('actions.backConfigs') }</a>
  <a class="btn btn--primary" href="/configs/list">{ $t('actions.listConfigs') }</a>
</div>
