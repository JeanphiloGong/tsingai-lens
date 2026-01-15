<script lang="ts">
  import { t } from '../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('configs.title')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('configs.eyebrow')}</p>
    <h1>{$t('configs.title')}</h1>
    <p class="lead">{$t('configs.lead')}</p>
  </div>
</section>

<section class="grid">
  <a class="card link-card fade-up" href="/configs/list">
    <span class="pill">GET</span>
    <h3>{$t('configs.listTitle')}</h3>
    <p>{$t('configs.listDesc')}</p>
  </a>
  <a class="card link-card fade-up delay-1" href="/configs/view">
    <span class="pill">GET</span>
    <h3>{$t('configs.viewTitle')}</h3>
    <p>{$t('configs.viewDesc')}</p>
  </a>
  <a class="card link-card fade-up delay-2" href="/configs/create">
    <span class="pill">POST</span>
    <h3>{$t('configs.createTitle')}</h3>
    <p>{$t('configs.createDesc')}</p>
  </a>
  <a class="card link-card fade-up delay-3" href="/configs/upload">
    <span class="pill">POST</span>
    <h3>{$t('configs.uploadTitle')}</h3>
    <p>{$t('configs.uploadDesc')}</p>
  </a>
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/">{ $t('actions.backHome') }</a>
  <a class="btn btn--primary" href="/docs">{ $t('actions.openDocs') }</a>
</div>
