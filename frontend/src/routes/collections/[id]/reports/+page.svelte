<script lang="ts">
  import { t } from '../../../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('reports.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('reports.title')}</h2>
  <p class="lead">{$t('reports.lead')}</p>
  <p class="note">{$t('reports.placeholder')}</p>
</section>
