<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { errorMessage } from '../../_shared/api';
  import { collections, deleteCollection, fetchCollection, fetchCollections } from '../../_shared/collections';
  import { t } from '../../_shared/i18n';

  let deleteLoading = false;
  let deleteError = '';

  $: collectionId = $page.params.id ?? '';
  $: collectionName = $collections.find((item) => item.id === collectionId)?.name;

  onMount(() => {
    if (!$collections.length) {
      fetchCollections().catch(() => null);
    }
    if (collectionId) {
      fetchCollection(collectionId).catch(() => null);
    }
  });

  async function removeCurrentCollection() {
    const name = collectionName || collectionId;
    if (!window.confirm($t('collection.deleteConfirm', { name }))) {
      return;
    }

    deleteLoading = true;
    deleteError = '';

    try {
      await deleteCollection(collectionId);
      await goto('/');
    } catch (err) {
      deleteError = errorMessage(err);
    } finally {
      deleteLoading = false;
    }
  }
</script>

<section class="collection-header">
  <div>
    <p class="eyebrow">{$t('collection.eyebrow')}</p>
    <h1>{collectionName || $t('collection.unknownName')}</h1>
    <div class="collection-meta">
      <span class="pill">{$t('collection.idLabel')}: {collectionId}</span>
    </div>
  </div>
  <div class="collection-actions">
    <a class="btn btn--ghost" href="/">{$t('collection.backToCollections')}</a>
    <button class="btn btn--danger" type="button" disabled={deleteLoading} on:click={removeCurrentCollection}>
      {deleteLoading ? $t('collection.deleting') : $t('collection.delete')}
    </button>
  </div>
</section>

{#if deleteError}
  <div class="status status--error" role="alert">{deleteError}</div>
{/if}

<nav class="subnav">
  <a
    href={`/collections/${collectionId}`}
    class:active={$page.url.pathname === `/collections/${collectionId}`}
  >
    {$t('collection.tabs.overview')}
  </a>
  <a
    href={`/collections/${collectionId}/steps`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/steps`)}
  >
    {$t('collection.tabs.steps')}
  </a>
  <a
    href={`/collections/${collectionId}/sop`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/sop`)}
  >
    {$t('collection.tabs.sop')}
  </a>
  <a
    href={`/collections/${collectionId}/graph`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/graph`)}
  >
    {$t('collection.tabs.graph')}
  </a>
</nav>

<div class="collection-panel">
  <slot />
</div>
