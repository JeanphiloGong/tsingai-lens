<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage, formatResult, requestJson } from '../../../_shared/api';
  import {
    deleteCollectionFile,
    listCollectionFiles,
    uploadCollectionFiles,
    type CollectionFile
  } from '../../../_shared/files';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id;

  let showModal = false;
  let selectedFiles: File[] = [];
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
  let collectionFiles: CollectionFile[] = [];
  let filesLoading = false;
  let filesError = '';
  let deleteTarget: CollectionFile | null = null;
  let deleteLoading = false;
  let deleteError = '';
  let loadedCollectionId = '';

  function openModal() {
    showModal = true;
    selectedFiles = [];
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
    selectedFiles = fileList ? Array.from(fileList) : [];
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

  function formatDate(value?: string) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function formatBytes(value?: number) {
    if (value === undefined || value === null) return '-';
    if (value < 1024) return `${value} B`;
    const kb = value / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    const gb = mb / 1024;
    return `${gb.toFixed(1)} GB`;
  }

  function getFileLabel(file: CollectionFile) {
    return file.original_filename || file.key || file.stored_path || $t('documents.untitledFile');
  }

  function getFileSub(file: CollectionFile) {
    return file.key || file.stored_path || '';
  }

  async function loadFiles() {
    filesLoading = true;
    filesError = '';
    try {
      const data = await listCollectionFiles(collectionId);
      collectionFiles = Array.isArray(data.items) ? data.items : [];
    } catch (err) {
      filesError = errorMessage(err);
    } finally {
      filesLoading = false;
    }
  }

  function openDelete(file: CollectionFile) {
    deleteTarget = file;
    deleteError = '';
  }

  function closeDelete() {
    deleteTarget = null;
    deleteLoading = false;
    deleteError = '';
  }

  function handleDeleteBackdropKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeDelete();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      closeDelete();
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    deleteLoading = true;
    deleteError = '';
    try {
      await deleteCollectionFile(collectionId, deleteTarget.key);
      closeDelete();
      await loadFiles();
    } catch (err) {
      deleteError = errorMessage(err);
      deleteLoading = false;
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadFiles();
  }

  async function submitUpload() {
    uploadError = '';
    uploadResult = null;
    indexResult = null;
    indexStatus = '';

    if (!selectedFiles.length) {
      uploadError = $t('documents.errorNoFiles');
      return;
    }

    uploadLoading = true;
    try {
      uploadResult = await uploadCollectionFiles(collectionId, selectedFiles);
      await loadFiles();
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
  {#if filesLoading}
    <div class="status" role="status" aria-live="polite">{$t('documents.listLoading')}</div>
  {:else if filesError}
    <div class="status status--error" role="alert">{filesError}</div>
  {:else if !collectionFiles.length}
    <p class="note">{$t('documents.listEmptyTitle')}</p>
    <p class="meta-text">{$t('documents.listEmptyDesc')}</p>
  {:else}
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('documents.tableName')}</th>
            <th>{$t('documents.tableSize')}</th>
            <th>{$t('documents.tableCreated')}</th>
            <th>{$t('documents.tableActions')}</th>
          </tr>
        </thead>
        <tbody>
          {#each collectionFiles as file}
            <tr>
              <td>
                <div class="table-main">
                  <div class="table-title">{getFileLabel(file)}</div>
                  {#if getFileSub(file)}
                    <div class="table-sub file-meta">{getFileSub(file)}</div>
                  {/if}
                </div>
              </td>
              <td>{formatBytes(file.size_bytes)}</td>
              <td>{formatDate(file.created_at)}</td>
              <td>
                <div class="table-actions">
                  <button class="btn btn--ghost btn--small btn--danger" type="button" on:click={() => openDelete(file)}>
                    {$t('documents.actionDelete')}
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
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
        {#if selectedFiles.length}
          <div class="dropzone-files">{$t('documents.selectedCount', { count: selectedFiles.length })}</div>
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

{#if deleteTarget}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="0"
    aria-label={$t('documents.deleteCancel')}
    on:click={closeDelete}
    on:keydown={handleDeleteBackdropKeydown}
  >
    <div class="modal" role="dialog" aria-modal="true" tabindex="-1" on:click|stopPropagation>
      <div class="modal-header">
        <div class="modal-title">
          <h3>{$t('documents.deleteTitle')}</h3>
          <p class="meta-text">
            {$t('documents.deleteDesc', { name: getFileLabel(deleteTarget) })}
          </p>
        </div>
        <button class="modal-close" type="button" on:click={closeDelete} aria-label={$t('documents.deleteCancel')}>
          x
        </button>
      </div>

      {#if deleteError}
        <div class="status status--error" role="alert">{deleteError}</div>
      {/if}

      <div class="modal-actions">
        <button class="btn btn--ghost" type="button" on:click={closeDelete}>
          {$t('documents.deleteCancel')}
        </button>
        <button class="btn btn--danger" type="button" on:click={confirmDelete} disabled={deleteLoading}>
          {deleteLoading ? $t('documents.deleting') : $t('documents.deleteConfirm')}
        </button>
      </div>
    </div>
  </div>
{/if}
