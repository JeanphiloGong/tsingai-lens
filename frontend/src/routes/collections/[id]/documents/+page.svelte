<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage, formatResult, requestJson } from '../../../_shared/api';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id;

  let showModal = false;
  let files: File[] = [];
  let isDragging = false;
  let indexAfterUpload = true;
  let indexMode: 'update' | 'rebuild' = 'update';
  let method = 'standard';
  let uploadLoading = false;
  let uploadError = '';
  let uploadResult: unknown = null;
  let indexResult: unknown = null;
  let indexStatus = '';
  let fileInput: HTMLInputElement | null = null;

  function openModal() {
    showModal = true;
    files = [];
    isDragging = false;
    indexAfterUpload = true;
    indexMode = 'update';
    method = 'standard';
    uploadError = '';
    uploadResult = null;
    indexResult = null;
    indexStatus = '';
  }

  function closeModal() {
    showModal = false;
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

  function handleFiles(fileList: FileList | null) {
    files = fileList ? Array.from(fileList) : [];
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    handleFiles(event.dataTransfer?.files ?? null);
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    isDragging = true;
  }

  function handleDragLeave(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
  }

  function browseFiles() {
    fileInput?.click();
  }

  async function submitUpload() {
    uploadError = '';
    uploadResult = null;
    indexResult = null;
    indexStatus = '';

    if (!files.length) {
      uploadError = $t('documents.errorNoFiles');
      return;
    }

    const formData = new FormData();
    formData.append('collection_id', collectionId);
    files.forEach((file) => formData.append('files', file));

    uploadLoading = true;
    try {
      uploadResult = await requestJson('/retrieval/input/upload', {
        method: 'POST',
        body: formData
      });
      indexStatus = $t('documents.uploadDone');
      if (indexAfterUpload) {
        indexStatus = $t('documents.indexing');
        indexResult = await requestJson('/retrieval/index', {
          method: 'POST',
          body: JSON.stringify({
            collection_id: collectionId,
            method,
            is_update_run: indexMode === 'update',
            verbose: false
          })
        });
        indexStatus = $t('documents.indexDone');
      }
    } catch (err) {
      uploadError = errorMessage(err);
    } finally {
      uploadLoading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('documents.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('documents.title')}</h2>
  <p class="lead">{$t('documents.lead')}</p>
  <button class="btn btn--primary" type="button" on:click={openModal}>
    {$t('documents.addFiles')}
  </button>
</section>

<section class="card">
  <h3>{$t('documents.listTitle')}</h3>
  <p class="note">{$t('documents.listPlaceholder')}</p>
  <p class="meta-text">{$t('documents.listHelper')}</p>
</section>

{#if uploadResult !== null || indexResult !== null || uploadError}
  <section class="card">
    <h3>{$t('documents.upload')}</h3>
    {#if uploadError}
      <div class="status status--error" role="alert">{uploadError}</div>
    {/if}
    {#if indexStatus}
      <div class="status" role="status" aria-live="polite">{indexStatus}</div>
    {/if}
    {#if uploadResult !== null}
      <pre class="code-block">{formatResult(uploadResult)}</pre>
    {/if}
    {#if indexResult !== null}
      <pre class="code-block">{formatResult(indexResult)}</pre>
    {/if}
  </section>
{/if}

{#if indexResult}
  <section class="card">
    <h3>{$t('overview.nextActionsTitle')}</h3>
    <div class="action-grid">
      <a class="btn btn--primary" href={`/collections/${collectionId}/search`}>
        {$t('overview.nextSearch')}
      </a>
      <a class="btn btn--ghost" href={`/collections/${collectionId}/graph`}>
        {$t('overview.nextExport')}
      </a>
    </div>
  </section>
{/if}

{#if showModal}
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
        <h3>{$t('documents.modalTitle')}</h3>
        <p class="meta-text">{$t('documents.modalLead')}</p>
      </div>
      <div
        class={`dropzone ${isDragging ? 'dropzone--active' : ''}`}
        on:drop={handleDrop}
        on:dragover={handleDragOver}
        on:dragleave={handleDragLeave}
        on:click={browseFiles}
        role="button"
        tabindex="0"
        on:keydown={(event) => event.key === 'Enter' && browseFiles()}
      >
        <input
          class="dropzone-input"
          bind:this={fileInput}
          type="file"
          multiple
          on:change={(event) => handleFiles((event.currentTarget as HTMLInputElement).files)}
        />
        <div class="dropzone-title">{$t('documents.dropHint')}</div>
        <div class="dropzone-sub">{$t('documents.browse')}</div>
        {#if files.length}
          <div class="dropzone-files">{$t('documents.selectedCount', { count: files.length })}</div>
        {/if}
      </div>

      <div class="toggle-row">
        <label>
          <input type="checkbox" bind:checked={indexAfterUpload} />
          {$t('documents.indexAfterLabel')}
        </label>
      </div>

      <div class="field">
        <label>{$t('documents.indexModeLabel')}</label>
        <div class="radio-group">
          <label>
            <input
              type="radio"
              name="index-mode"
              value="update"
              bind:group={indexMode}
              disabled={!indexAfterUpload}
            />
            {$t('documents.indexModeUpdate')}
          </label>
          <label>
            <input
              type="radio"
              name="index-mode"
              value="rebuild"
              bind:group={indexMode}
              disabled={!indexAfterUpload}
            />
            {$t('documents.indexModeRebuild')}
          </label>
        </div>
      </div>

      <div class="field">
        <label for="index-method">{$t('documents.methodLabel')}</label>
        <select id="index-method" class="select" bind:value={method} disabled={!indexAfterUpload}>
          <option value="standard">{$t('documents.methodStandard')}</option>
          <option value="fast">{$t('documents.methodFast')}</option>
        </select>
      </div>

      {#if uploadError}
        <div class="status status--error" role="alert">{uploadError}</div>
      {/if}

      <div class="modal-actions">
        <button class="btn btn--ghost" type="button" on:click={closeModal}>
          {$t('create.cancel')}
        </button>
        <button class="btn btn--primary" type="button" on:click={submitUpload} disabled={uploadLoading}>
          {uploadLoading ? $t('documents.uploading') : $t('documents.upload')}
        </button>
      </div>
    </div>
  </div>
{/if}
