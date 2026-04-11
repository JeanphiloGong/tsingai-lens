<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import {
    fetchWorkspaceOverview,
    getWorkspaceSurfaceState,
    stageIsActionable,
    type WorkspaceOverview
  } from '../../../_shared/workspace';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let workspace: WorkspaceOverview | null = null;
  let loading = false;
  let error = '';
  let loadedCollectionId = '';

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    void loadWorkspace();
  }

  async function loadWorkspace() {
    loading = true;
    error = '';
    try {
      workspace = await fetchWorkspaceOverview(collectionId);
    } catch (err) {
      error = errorMessage(err);
      workspace = null;
    } finally {
      loading = false;
    }
  }

  $: protocolReady = stageIsActionable(workspace?.workflow.protocol);
  $: protocolState = getWorkspaceSurfaceState(workspace, 'protocol');

  function stateCardTitle() {
    return protocolReady
      ? $t('protocolHub.readyTitle')
      : $t(`overview.surfaceStateCards.${protocolState}.title`);
  }

  function stateCardBody() {
    return protocolReady
      ? $t('protocolHub.readyBody')
      : $t(`overview.surfaceStateCards.${protocolState}.body`);
  }
</script>

<svelte:head>
  <title>{$t('protocolHub.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('protocolHub.title')}</h2>
      <p class="lead">{$t('protocolHub.lead')}</p>
    </div>
    <button class="btn btn--ghost btn--small" type="button" on:click={loadWorkspace}>
      {$t('overview.refresh')}
    </button>
  </div>

  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {:else if loading}
    <div class="status" role="status">{$t('overview.loading')}</div>
  {:else if workspace}
    <div class="result-grid result-grid--tasks">
      <article class="result-card">
        <h3>{stateCardTitle()}</h3>
        <p class="result-text">{stateCardBody()}</p>
      </article>

      <article class="result-card">
        <h3>{$t('protocolHub.actionsTitle')}</h3>
        <div class="table-actions">
          <a class="btn btn--ghost btn--small" href={workspace.links.comparisons}>
            {$t('overview.nextComparisons')}
          </a>
          <a class="btn btn--ghost btn--small" href={workspace.links.evidence}>
            {$t('overview.nextEvidence')}
          </a>
          <a class="btn btn--ghost btn--small" href={workspace.links.documents}>
            {$t('overview.nextDocuments')}
          </a>
          {#if protocolReady}
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/protocol/steps`}>
              {$t('protocolHub.stepsCta')}
            </a>
            <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/protocol/sop`}>
              {$t('protocolHub.sopCta')}
            </a>
          {/if}
        </div>
        {#if !protocolReady}
          <p class="note">{$t('protocolHub.limitedBody')}</p>
        {/if}
      </article>
    </div>
  {/if}
</section>
