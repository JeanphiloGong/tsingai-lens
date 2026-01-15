<script lang="ts">
  import { baseUrl, DEFAULT_BASE_URL, validateBaseUrl } from './base';
  import { errorMessage } from './api';
  import { t } from './i18n';
  import { onMount } from 'svelte';

  let draft = DEFAULT_BASE_URL;
  let status = '';
  let error = '';

  onMount(() => {
    draft = $baseUrl;
  });

  function setStatus(message: string) {
    status = message;
    if (!message) return;
    window.setTimeout(() => {
      status = '';
    }, 2200);
  }

  function save() {
    error = '';
    try {
      const normalized = validateBaseUrl(draft);
      baseUrl.set(normalized);
      draft = normalized;
      setStatus($t('connection.saved'));
    } catch (err) {
      error = errorMessage(err);
    }
  }

  function reset() {
    error = '';
    draft = DEFAULT_BASE_URL;
    baseUrl.set(DEFAULT_BASE_URL);
    setStatus($t('connection.resetStatus'));
  }
</script>

<form class="card connection-bar" on:submit|preventDefault={save}>
  <div class="connection-title">
    <span class="pill">{$t('connection.title')}</span>
    <span class="meta-text">{$t('connection.helper')}</span>
  </div>
  <div class="connection-controls">
    <div class="field connection-field">
      <label for="base-url">{$t('connection.baseUrlLabel')}</label>
      <input id="base-url" class="input" bind:value={draft} placeholder={DEFAULT_BASE_URL} />
    </div>
    <div class="connection-actions">
      <button class="btn btn--primary" type="submit">{$t('connection.save')}</button>
      <button class="btn btn--ghost" type="button" on:click={reset}>{$t('connection.reset')}</button>
    </div>
  </div>
  {#if status}
    <div class="status" role="status" aria-live="polite">{status}</div>
  {/if}
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</form>
