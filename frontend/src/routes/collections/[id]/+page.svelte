<script lang="ts">
  import { page } from '$app/stores';
  import { collections } from '../../_shared/collections';
  import { t } from '../../_shared/i18n';

  $: collectionId = $page.params.id;
  $: collection = $collections.find((item) => item.id === collectionId);

  function formatStatus(status?: string) {
    if (!status) return $t('overview.statusUnknown');
    if (status === 'ready') return $t('overview.statusReady');
    if (status === 'empty') return $t('overview.statusEmpty');
    return status;
  }

  function formatCount(value: unknown) {
    if (typeof value === 'number') return String(value);
    if (typeof value === 'string' && value.trim() !== '') return value;
    return '--';
  }
</script>

<svelte:head>
  <title>{$t('overview.title')}</title>
</svelte:head>

<section class="card fade-up">
  <p class="lead">{$t('overview.lead')}</p>
  <div class="status-row">
    <span class="label">{$t('overview.statusLabel')}</span>
    <span class="status status--neutral">{formatStatus(collection?.status)}</span>
  </div>
  <div class="stat-grid">
    <div class="stat-card">
      <div class="stat-value">{formatCount(collection?.document_count)}</div>
      <div class="stat-label">{$t('overview.metricPapers')}</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">{formatCount(collection?.entity_count)}</div>
      <div class="stat-label">{$t('overview.metricEntities')}</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">--</div>
      <div class="stat-label">{$t('overview.metricRelations')}</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">--</div>
      <div class="stat-label">{$t('overview.metricCommunities')}</div>
    </div>
  </div>
  <div class="note">{$t('overview.metricNote')}</div>
</section>

<section class="card">
  <h3>{$t('overview.nextActionsTitle')}</h3>
  <div class="action-grid">
    <a class="btn btn--primary" href={`/collections/${collectionId}/search`}>
      {$t('overview.nextSearch')}
    </a>
    <a class="btn btn--ghost" href={`/collections/${collectionId}/graph`}>
      {$t('overview.nextExport')}
    </a>
    <a class="btn btn--ghost" href={`/collections/${collectionId}/documents`}>
      {$t('overview.nextUpload')}
    </a>
  </div>
</section>
