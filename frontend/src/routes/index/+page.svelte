<script lang="ts">
  import { t } from '../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('index.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('index.eyebrow')}</p>
    <h1>{$t('index.title')}</h1>
    <p class="lead">{$t('index.lead')}</p>
  </div>
</section>

<section class="grid">
  <a class="card link-card fade-up" href="/index/config">
    <span class="pill">{$t('index.configTag')}</span>
    <h3>{$t('index.configTitle')}</h3>
    <p>{$t('index.configDesc')}</p>
  </a>
  <a class="card link-card fade-up delay-1" href="/index/upload">
    <span class="pill">{$t('index.uploadTag')}</span>
    <h3>{$t('index.uploadTitle')}</h3>
    <p>{$t('index.uploadDesc')}</p>
  </a>
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/upload">{ $t('actions.backUpload') }</a>
  <a class="btn btn--primary" href="/export">{ $t('actions.nextExport') }</a>
</div>
