<script lang="ts">
  import { t } from '../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('system.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('system.title')}</h2>
  <p class="lead">{$t('system.lead')}</p>
  <p class="note">{$t('system.placeholder')}</p>
</section>
