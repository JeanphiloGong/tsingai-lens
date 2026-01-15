<script lang="ts">
  import { errorMessage, formatResult, requestJson } from '../../_shared/api';
  import { t } from '../../_shared/i18n';

  let configPath = '';
  let method = 'standard';
  let updateRun = false;
  let verbose = false;
  let additionalContextText = '';

  let loading = false;
  let error = '';
  let result: unknown = null;

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    const trimmedPath = configPath.trim();
    if (!trimmedPath) {
      error = $t('indexConfig.errorConfigPath');
      return;
    }

    let additionalContext: unknown = undefined;
    if (additionalContextText.trim()) {
      try {
        additionalContext = JSON.parse(additionalContextText);
      } catch {
        error = $t('indexConfig.errorContextJson');
        return;
      }
    }

    loading = true;
    try {
      const payload: Record<string, unknown> = {
        config_path: trimmedPath,
        method,
        is_update_run: updateRun,
        verbose
      };
      if (additionalContext !== undefined) {
        payload.additional_context = additionalContext;
      }
      result = await requestJson('/retrieval/index', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('indexConfig.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('indexConfig.eyebrow')}</p>
    <h1>{$t('indexConfig.title')}</h1>
    <p class="lead">{$t('indexConfig.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">POST /retrieval/index</span>
  <h3>{$t('indexConfig.cardTitle')}</h3>
  <form on:submit={submit}>
    <div class="field">
      <label for="config-path">{$t('indexConfig.configPathLabel')}</label>
      <input
        id="config-path"
        class="input"
        bind:value={configPath}
        placeholder="/path/to/config.yaml"
        required
      />
    </div>
    <div class="field">
      <label for="index-method">{$t('indexConfig.methodLabel')}</label>
      <select id="index-method" class="select" bind:value={method}>
        <option value="standard">standard</option>
        <option value="fast">fast</option>
        <option value="standard-update">standard-update</option>
        <option value="fast-update">fast-update</option>
      </select>
    </div>
    <div class="field">
      <label for="additional-context">{$t('indexConfig.additionalContextLabel')}</label>
      <textarea
        id="additional-context"
        class="textarea"
        bind:value={additionalContextText}
        placeholder={'{"project":"alpha"}'}
      ></textarea>
    </div>
    <div class="toggle-row">
      <label>
        <input type="checkbox" bind:checked={updateRun} />
        {$t('indexConfig.updateRun')}
      </label>
      <label>
        <input type="checkbox" bind:checked={verbose} />
        {$t('indexConfig.verbose')}
      </label>
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('indexConfig.running') : $t('indexConfig.submit')}
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
