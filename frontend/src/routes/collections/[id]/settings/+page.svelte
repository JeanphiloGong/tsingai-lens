<script lang="ts">
  import { t } from '../../../_shared/i18n';

  let defaultConfig = true;
</script>

<svelte:head>
  <title>{$t('settings.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('settings.title')}</h2>
  <p class="lead">{$t('settings.lead')}</p>
  <div class="toggle-row">
    <label>
      <input type="checkbox" bind:checked={defaultConfig} disabled />
      {$t('settings.defaultConfigLabel')}
    </label>
    <span class="meta-text">{$t('settings.defaultConfigHelper')}</span>
  </div>
  <details class="advanced">
    <summary>{$t('settings.advancedTitle')}</summary>
    <p class="note">{$t('settings.advancedHelper')}</p>
  </details>
  <p class="note">{$t('settings.placeholder')}</p>
</section>
