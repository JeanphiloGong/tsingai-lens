<script lang="ts">
  import { page } from '$app/stores';
  import { collections, fetchCollection } from '../../../_shared/collections';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';
  $: collection = $collections.find((item) => item.id === collectionId);
  $: if (collectionId && !collection) {
    fetchCollection(collectionId).catch(() => null);
  }

  function formatDate(value?: string) {
    if (!value) return '--';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }
</script>

<svelte:head>
  <title>{$t('settings.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('settings.title')}</h2>
  <p class="lead">{$t('settings.lead')}</p>

  <dl class="detail-list">
    <div class="detail-row">
      <dt>{$t('create.nameLabel')}</dt>
      <dd>{collection?.name || '--'}</dd>
    </div>
    <div class="detail-row">
      <dt>{$t('create.descLabel')}</dt>
      <dd>{collection?.description || '--'}</dd>
    </div>
    <div class="detail-row">
      <dt>{$t('create.methodLabel')}</dt>
      <dd>{collection?.default_method || 'standard'}</dd>
    </div>
    <div class="detail-row">
      <dt>{$t('tasks.tableCreated')}</dt>
      <dd>{formatDate(collection?.created_at)}</dd>
    </div>
    <div class="detail-row">
      <dt>{$t('home.tableUpdated')}</dt>
      <dd>{formatDate(collection?.updated_at)}</dd>
    </div>
  </dl>

  <details class="advanced">
    <summary>{$t('settings.advancedTitle')}</summary>
    <p class="note">{$t('settings.advancedHelper')}</p>
  </details>
</section>
