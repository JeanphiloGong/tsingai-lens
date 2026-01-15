<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../_shared/api';
  import { t } from '../_shared/i18n';

  let files: File[] = [];
  let loading = false;
  let error = '';
  let result: unknown = null;

  function handleFilesChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    files = target.files ? Array.from(target.files) : [];
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!files.length) {
      error = $t('upload.errorNoFiles');
      return;
    }

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    loading = true;
    try {
      result = await requestJson('/retrieval/input/upload', {
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
  <title>{$t('upload.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('upload.eyebrow')}</p>
    <h1>{$t('upload.title')}</h1>
    <p class="lead">{$t('upload.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">POST /retrieval/input/upload</span>
  <h3>{$t('upload.cardTitle')}</h3>
  <p>{$t('upload.cardDesc')}</p>
  <form on:submit={submit}>
    <div class="field">
      <label for="input-files">{$t('upload.fileLabel')}</label>
      <input
        id="input-files"
        class="input"
        type="file"
        multiple
        on:change={handleFilesChange}
      />
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading
        ? $t('upload.uploading')
        : `${$t('upload.submit')}${files.length ? ` (${files.length})` : ''}`}
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
  <a class="btn btn--ghost" href="/">{ $t('actions.backHome') }</a>
  <a class="btn btn--primary" href="/index">{ $t('actions.nextIndex') }</a>
</div>
