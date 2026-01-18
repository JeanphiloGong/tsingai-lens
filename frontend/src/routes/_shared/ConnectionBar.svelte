<script lang="ts">
  import { baseUrl, DEFAULT_BASE_URL, validateBaseUrl } from './base';
  import { errorMessage } from './api';
  import { t } from './i18n';
  import { onMount } from 'svelte';

  let draft = DEFAULT_BASE_URL;
  let status = '';
  let error = '';
  let isOpen = false;

  onMount(() => {
    draft = $baseUrl;
  });

  function openModal() {
    draft = $baseUrl;
    status = '';
    error = '';
    isOpen = true;
  }

  function closeModal() {
    isOpen = false;
  }

  function handleBackdropKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeModal();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      closeModal();
    }
  }

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

<button class="btn btn--ghost btn--small" type="button" on:click={openModal}>
  {$t('connection.title')}
</button>

{#if isOpen}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="0"
    aria-label={$t('create.cancel')}
    on:click={closeModal}
    on:keydown={handleBackdropKeydown}
  >
    <div class="modal" role="dialog" aria-modal="true" tabindex="-1" on:click|stopPropagation>
      <div class="modal-header">
        <h3>{$t('connection.title')}</h3>
        <p class="meta-text">{$t('connection.helper')}</p>
      </div>
      <form class="modal-form" on:submit|preventDefault={save}>
        <div class="field">
          <label for="base-url">{$t('connection.baseUrlLabel')}</label>
          <input id="base-url" class="input" bind:value={draft} placeholder={DEFAULT_BASE_URL} />
        </div>
        {#if status}
          <div class="status" role="status" aria-live="polite">{status}</div>
        {/if}
        {#if error}
          <div class="status status--error" role="alert">{error}</div>
        {/if}
        <div class="modal-actions">
          <button class="btn btn--ghost" type="button" on:click={closeModal}>
            {$t('create.cancel')}
          </button>
          <button class="btn btn--ghost" type="button" on:click={reset}>
            {$t('connection.reset')}
          </button>
          <button class="btn btn--primary" type="submit">{$t('connection.save')}</button>
        </div>
      </form>
    </div>
  </div>
{/if}
