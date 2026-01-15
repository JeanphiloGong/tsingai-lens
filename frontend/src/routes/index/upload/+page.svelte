<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let file: File | null = null;
  let method = 'standard';
  let updateRun = false;
  let verbose = false;

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
      error = $t('indexUpload.errorFile');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('method', method);
    formData.append('is_update_run', String(updateRun));
    formData.append('verbose', String(verbose));

    loading = true;
    try {
      result = await requestJson('/retrieval/index/upload', {
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
  <title>{$t('indexUpload.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('indexUpload.eyebrow')}</p>
    <h1>{$t('indexUpload.title')}</h1>
    <p class="lead">{$t('indexUpload.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">POST /retrieval/index/upload</span>
  <h3>{$t('indexUpload.cardTitle')}</h3>
  <form on:submit={submit}>
    <div class="field">
      <label for="index-file">{$t('indexUpload.fileLabel')}</label>
      <input id="index-file" class="input" type="file" on:change={handleFileChange} />
    </div>
    <div class="field">
      <label for="index-method">{$t('indexUpload.methodLabel')}</label>
      <select id="index-method" class="select" bind:value={method}>
        <option value="standard">standard</option>
        <option value="fast">fast</option>
        <option value="standard-update">standard-update</option>
        <option value="fast-update">fast-update</option>
      </select>
    </div>
    <div class="toggle-row">
      <label>
        <input type="checkbox" bind:checked={updateRun} />
        {$t('indexUpload.updateRun')}
      </label>
      <label>
        <input type="checkbox" bind:checked={verbose} />
        {$t('indexUpload.verbose')}
      </label>
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('indexUpload.uploading') : $t('indexUpload.submit')}
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
  <a class="btn btn--ghost" href="/index">{ $t('actions.backIndex') }</a>
  <a class="btn btn--primary" href="/export">{ $t('actions.nextExport') }</a>
</div>
