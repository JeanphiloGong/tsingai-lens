<script lang="ts">
  import { t } from '../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('docs.pageTitle')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('docs.eyebrow')}</p>
    <h1>{$t('docs.title')}</h1>
    <p class="lead">{$t('docs.lead')}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">{$t('docs.quickNotesTitle')}</span>
  <h3>{$t('docs.quickNotesSub')}</h3>
  <div class="flow">
    <div class="flow-step">{$t('docs.quickNote1')}</div>
    <div class="flow-step">{$t('docs.quickNote2')}</div>
    <div class="flow-step">{$t('docs.quickNote3')}</div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.workflowTitle')}</h2>
    <p class="section-sub">{$t('docs.workflowSub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">01</span>
      <h3>{$t('docs.workflowCreateTitle')}</h3>
      <p>{$t('docs.workflowCreateDesc')}</p>
    </article>

    <article class="card">
      <span class="pill">02</span>
      <h3>{$t('docs.workflowUploadTitle')}</h3>
      <p>{$t('docs.workflowUploadDesc')}</p>
    </article>

    <article class="card">
      <span class="pill">03</span>
      <h3>{$t('docs.workflowIndexTitle')}</h3>
      <p>{$t('docs.workflowIndexDesc')}</p>
    </article>

    <article class="card">
      <span class="pill">04</span>
      <h3>{$t('docs.workflowSearchTitle')}</h3>
      <p>{$t('docs.workflowSearchDesc')}</p>
    </article>

    <article class="card">
      <span class="pill">05</span>
      <h3>{$t('docs.workflowGraphTitle')}</h3>
      <p>{$t('docs.workflowGraphDesc')}</p>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.navTitle')}</h2>
    <p class="section-sub">{$t('docs.navSub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <h3>{$t('docs.navOverview')}</h3>
    </article>
    <article class="card">
      <h3>{$t('docs.navDocuments')}</h3>
    </article>
    <article class="card">
      <h3>{$t('docs.navSearch')}</h3>
    </article>
    <article class="card">
      <h3>{$t('docs.navGraph')}</h3>
    </article>
    <article class="card">
      <h3>{$t('docs.navReports')}</h3>
    </article>
    <article class="card">
      <h3>{$t('docs.navSettings')}</h3>
    </article>
  </div>
  <p class="note">{$t('docs.navNote')}</p>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.tutorialTitle')}</h2>
    <p class="section-sub">{$t('docs.tutorialSub')}</p>
  </div>
  <div class="card">
    <ol class="tutorial-list">
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep1Title')}</strong>
        <p>{$t('docs.tutorialStep1Desc1')}</p>
        <p>{$t('docs.tutorialStep1Desc2')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep2Title')}</strong>
        <p>{$t('docs.tutorialStep2Desc')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep3Title')}</strong>
        <p>{$t('docs.tutorialStep3Desc1')}</p>
        <p>{$t('docs.tutorialStep3Desc2')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep4Title')}</strong>
        <p>{$t('docs.tutorialStep4Desc1')}</p>
        <p>{$t('docs.tutorialStep4Desc2')}</p>
        <p>{$t('docs.tutorialStep4Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep5Title')}</strong>
        <p>{$t('docs.tutorialStep5Desc1')}</p>
        <p>{$t('docs.tutorialStep5Desc2')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep6Title')}</strong>
        <p>{$t('docs.tutorialStep6Desc1')}</p>
        <p>{$t('docs.tutorialStep6Desc2')}</p>
        <p>{$t('docs.tutorialStep6Desc3')}</p>
        <p>{$t('docs.tutorialStep6Desc4')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep7Title')}</strong>
        <p>{$t('docs.tutorialStep7Desc1')}</p>
        <p>{$t('docs.tutorialStep7Desc2')}</p>
        <p>{$t('docs.tutorialStep7Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep8Title')}</strong>
        <p>{$t('docs.tutorialStep8Desc1')}</p>
        <p>{$t('docs.tutorialStep8Desc2')}</p>
        <p>{$t('docs.tutorialStep8Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep9Title')}</strong>
        <p>{$t('docs.tutorialStep9Desc1')}</p>
        <p>{$t('docs.tutorialStep9Desc2')}</p>
        <p>{$t('docs.tutorialStep9Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep10Title')}</strong>
        <p>{$t('docs.tutorialStep10Desc1')}</p>
        <p>{$t('docs.tutorialStep10Desc2')}</p>
      </li>
    </ol>
  </div>
</section>
