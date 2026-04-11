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
    const name = collectionName || $t('collection.unknownName');
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
    href={`/collections/${collectionId}/comparisons`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/comparisons`)}
  >
    {$t('collection.tabs.comparisons')}
  </a>
  <a
    href={`/collections/${collectionId}/evidence`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/evidence`)}
  >
    {$t('collection.tabs.evidence')}
  </a>
  <a
    href={`/collections/${collectionId}/documents`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/documents`)}
  >
    {$t('collection.tabs.documents')}
  </a>
  <a
    href={`/collections/${collectionId}/protocol`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/protocol`)}
  >
    {$t('collection.tabs.protocol')}
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
