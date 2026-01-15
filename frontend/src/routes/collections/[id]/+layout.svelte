<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { collections, fetchCollections } from '../../_shared/collections';
  import { t } from '../../_shared/i18n';

  $: collectionId = $page.params.id;
  $: collectionName = $collections.find((item) => item.id === collectionId)?.name;

  onMount(() => {
    if (!$collections.length) {
      fetchCollections().catch(() => null);
    }
  });
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
  </div>
</section>

<nav class="subnav">
  <a
    href={`/collections/${collectionId}`}
    class:active={$page.url.pathname === `/collections/${collectionId}`}
  >
    {$t('collection.tabs.overview')}
  </a>
  <a
    href={`/collections/${collectionId}/documents`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/documents`)}
  >
    {$t('collection.tabs.documents')}
  </a>
  <a
    href={`/collections/${collectionId}/search`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/search`)}
  >
    {$t('collection.tabs.search')}
  </a>
  <a
    href={`/collections/${collectionId}/graph`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/graph`)}
  >
    {$t('collection.tabs.graph')}
  </a>
  <a
    href={`/collections/${collectionId}/reports`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/reports`)}
  >
    {$t('collection.tabs.reports')}
  </a>
  <a
    href={`/collections/${collectionId}/settings`}
    class:active={$page.url.pathname.startsWith(`/collections/${collectionId}/settings`)}
  >
    {$t('collection.tabs.settings')}
  </a>
</nav>

<div class="collection-panel">
  <slot />
</div>
