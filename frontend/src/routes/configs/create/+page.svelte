<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let filename = '';
  let content = '';
  let loading = false;
  let error = '';
  let result: unknown = null;

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!filename.trim()) {
      error = $t('configsCreate.errorFilename');
      return;
    }

    if (!content.trim()) {
      error = $t('configsCreate.errorContent');
      return;
    }

    loading = true;
    try {
      result = await requestJson('/retrieval/configs', {
        method: 'POST',
        body: JSON.stringify({
          filename: filename.trim(),
          content
        })
      });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('configsCreate.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('configsCreate.eyebrow')}</p>
    <h1>{$t('configsCreate.title')}</h1>
    <p class="lead">{$t('configsCreate.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">POST /retrieval/configs</span>
  <h3>{$t('configsCreate.cardTitle')}</h3>
  <form on:submit={submit}>
    <div class="field">
      <label for="config-filename">{$t('configsCreate.filenameLabel')}</label>
      <input
        id="config-filename"
        class="input"
        bind:value={filename}
        placeholder="my-config.yaml"
        required
      />
    </div>
    <div class="field">
      <label for="config-content">{$t('configsCreate.contentLabel')}</label>
      <textarea
        id="config-content"
        class="textarea"
        bind:value={content}
        placeholder="# yaml here"
      ></textarea>
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('configsCreate.saving') : $t('configsCreate.save')}
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
