<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import { generateProtocolSop, type SOPDraftResponse } from '../../../_shared/protocol';
  import { t } from '../../../_shared/i18n';
  import { fetchWorkspaceOverview, type WorkspaceOverview } from '../../../_shared/workspace';

  $: collectionId = $page.params.id ?? '';

  let workspace: WorkspaceOverview | null = null;
  let goal = '';
  let targetProperties = '';
  let maxSteps = 8;
  let workspaceLoading = false;
  let loading = false;
  let error = '';
  let result: SOPDraftResponse | null = null;
  let loadedCollectionId = '';

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadWorkspace();
  }

  function canGenerateSop() {
    return Boolean(workspace?.capabilities.can_generate_sop || workspace?.artifacts.protocol_steps_ready);
  }

  function toList(value: string) {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function loadExampleGoal() {
    goal = $t('sop.goalPlaceholder');
    targetProperties = $t('sop.targetPropertiesPlaceholder');
    maxSteps = 8;
    error = '';
  }

  function paperLabel(paperTitle?: string | null) {
    return paperTitle?.trim() || $t('sop.unknownPaper');
  }

  async function loadWorkspace() {
    error = '';
    workspaceLoading = true;
    try {
      workspace = await fetchWorkspaceOverview(collectionId);
    } catch (err) {
      workspace = null;
      error = errorMessage(err);
    } finally {
      workspaceLoading = false;
    }
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!canGenerateSop()) {
      error = $t('sop.notReadyError');
      return;
    }

    if (!goal.trim()) {
      error = $t('sop.errorGoal');
      return;
    }

    loading = true;
    try {
      result = await generateProtocolSop(collectionId, {
        goal: goal.trim(),
        targetProperties: toList(targetProperties),
        paperIds: [],
        maxSteps
      });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('sop.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('sop.title')}</h2>
      <p class="lead">{$t('sop.lead')}</p>
      <p class="note">{$t('sop.purpose')}</p>
    </div>
    <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
      {$t('sop.backToWorkspace')}
    </a>
  </div>

  {#if workspaceLoading}
    <div class="status" role="status">{$t('sop.readinessLoading')}</div>
  {:else if canGenerateSop()}
    <form on:submit={submit}>
      <div class="field">
        <label for="goal">{$t('sop.goalLabel')}</label>
        <textarea
          id="goal"
          class="textarea"
          rows="3"
          bind:value={goal}
          placeholder={$t('sop.goalPlaceholder')}
        ></textarea>
      </div>
      <p class="meta-text">{$t('sop.collectionScopeNote')}</p>
      <details class="advanced">
        <summary>{$t('sop.advancedTitle')}</summary>
        <p class="meta-text">{$t('sop.advancedLead')}</p>
        <div class="form-grid">
          <div class="field">
            <label for="targetProperties">{$t('sop.targetPropertiesLabel')}</label>
            <input
              id="targetProperties"
              class="input"
              bind:value={targetProperties}
              placeholder={$t('sop.targetPropertiesPlaceholder')}
            />
          </div>
          <div class="field">
            <label for="maxSteps">{$t('sop.maxStepsLabel')}</label>
            <input id="maxSteps" class="input" type="number" min="1" max="50" bind:value={maxSteps} />
          </div>
        </div>
      </details>
      <div class="table-actions">
        <button class="btn btn--primary" type="submit" disabled={loading}>
          {loading ? $t('sop.generating') : $t('sop.submit')}
        </button>
        <button class="btn btn--ghost" type="button" on:click={loadExampleGoal}>
          {$t('sop.loadExample')}
        </button>
      </div>
      <p class="meta-text">{$t('sop.loadExampleNote')}</p>
    </form>
  {:else}
    <div class="result-grid">
      <article class="result-card">
        <h3>{$t('sop.notReadyTitle')}</h3>
        <p class="result-text">{$t('sop.notReadyBody')}</p>
        <ul class="result-list">
          <li>{$t('sop.notReadyStepOne')}</li>
          <li>{$t('sop.notReadyStepTwo')}</li>
          <li>{$t('sop.notReadyStepThree')}</li>
        </ul>
        <div class="table-actions">
          <a class="btn btn--primary" href={`/collections/${collectionId}`}>
            {$t('sop.goProcess')}
          </a>
        </div>
      </article>
    </div>
  {/if}
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

{#if !result}
  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('sop.exampleTitle')}</h3>
        <p class="meta-text">{$t('sop.exampleLead')}</p>
      </div>
      <span class="detail-count">{$t('sop.exampleTag')}</span>
    </div>

    <div class="result-grid">
      <article class="result-card">
        <h4>{$t('sop.objectiveTitle')}</h4>
        <p class="result-text">{$t('sop.exampleObjective')}</p>
        <h4>{$t('sop.hypothesisTitle')}</h4>
        <p class="result-text">{$t('sop.exampleHypothesis')}</p>
      </article>
      <article class="result-card">
        <h4>{$t('sop.measurementTitle')}</h4>
        <ul class="result-list">
          <li>{$t('sop.exampleMeasurement')}</li>
        </ul>
        <h4>{$t('sop.risksTitle')}</h4>
        <ul class="result-list">
          <li>{$t('sop.exampleRisk')}</li>
        </ul>
      </article>
    </div>

    <section class="detail-section">
      <div class="detail-section__title">{$t('sop.stepsTitle')}</div>
      <ul class="result-list">
        <li>{$t('sop.exampleStepOne')}</li>
        <li>{$t('sop.exampleStepTwo')}</li>
        <li>{$t('sop.exampleStepThree')}</li>
      </ul>
    </section>
  </section>
{/if}

{#if result}
  <section class="card">
    <div class="card-header-inline">
      <div>
        <h3>{$t('sop.resultTitle')}</h3>
        <p class="meta-text">{result.sop_draft.review_status || 'draft'}</p>
      </div>
      <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/steps`}>
        {$t('sop.viewSteps')}
      </a>
    </div>

    <div class="result-grid">
      <div class="result-card">
        <h4>{$t('sop.objectiveTitle')}</h4>
        <p class="result-text">{result.sop_draft.objective || '--'}</p>
        <h4>{$t('sop.hypothesisTitle')}</h4>
        <p class="result-text">{result.sop_draft.hypothesis || '--'}</p>
      </div>
      <div class="result-card">
        <h4>{$t('sop.risksTitle')}</h4>
        {#if result.sop_draft.risks.length}
          <ul class="result-list">
            {#each result.sop_draft.risks as risk}
              <li>{risk}</li>
            {/each}
          </ul>
        {:else}
          <p class="note">{$t('sop.emptyRisks')}</p>
        {/if}

        <h4>{$t('sop.questionsTitle')}</h4>
        {#if result.sop_draft.open_questions.length}
          <ul class="result-list">
            {#each result.sop_draft.open_questions as question}
              <li>{question}</li>
            {/each}
          </ul>
        {:else}
          <p class="note">{$t('sop.emptyQuestions')}</p>
        {/if}
      </div>
    </div>

    <section class="detail-section">
      <div class="detail-section__title">{$t('sop.stepsTitle')}</div>
      {#if result.sop_draft.steps.length}
        <div class="result-grid">
          {#each result.sop_draft.steps as step}
            <article class="result-card">
              <div class="table-title">{step.order ? `${step.order}. ` : ''}{step.action}</div>
              <div class="table-sub">{$t('sop.sourcePaperLabel')}: {paperLabel(step.paper_title)}</div>
              {#if step.purpose}
                <p class="result-text">{step.purpose}</p>
              {/if}
            </article>
          {/each}
        </div>
      {:else}
        <p class="note">{$t('sop.emptySteps')}</p>
      {/if}
    </section>

    <section class="detail-section">
      <div class="detail-section__title">{$t('sop.measurementTitle')}</div>
      {#if result.sop_draft.measurement_plan.length}
        <ul class="result-list">
          {#each result.sop_draft.measurement_plan as item}
            <li>{item.method || item.target_property || item.instrument || '--'}</li>
          {/each}
        </ul>
      {:else}
        <p class="note">{$t('sop.emptyMeasurement')}</p>
      {/if}
    </section>

    {#if result.warnings.length}
      <div class="status" role="status">{result.warnings.join(' | ')}</div>
    {/if}
  </section>
{/if}
