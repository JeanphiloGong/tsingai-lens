<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage } from '../../../_shared/api';
  import {
    getCommunityReportDetail,
    listCommunityReports,
    listReportPatterns,
    type ReportCommunityDetailResponse,
    type ReportCommunitySummary,
    type ReportPatternItem
  } from '../../../_shared/reports';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id ?? '';

  let level = 2;
  let sort = 'rating';
  let loading = false;
  let error = '';
  let patterns: ReportPatternItem[] = [];
  let communities: ReportCommunitySummary[] = [];
  let selectedCommunity: ReportCommunityDetailResponse | null = null;
  let detailLoading = false;
  let loadedCollectionId = '';

  async function loadReports() {
    loading = true;
    error = '';
    try {
      const [patternResponse, communityResponse] = await Promise.all([
        listReportPatterns(collectionId, { level, limit: 6, sort }),
        listCommunityReports(collectionId, { level, limit: 12, offset: 0, minSize: 0, sort })
      ]);
      patterns = patternResponse.items;
      communities = communityResponse.items;
      const first = communities[0];
      if (first?.community_id !== undefined && first.community_id !== null) {
        await selectCommunity(String(first.community_id));
      } else {
        selectedCommunity = null;
      }
    } catch (err) {
      error = errorMessage(err);
      patterns = [];
      communities = [];
      selectedCommunity = null;
    } finally {
      loading = false;
    }
  }

  async function selectCommunity(communityId: string) {
    detailLoading = true;
    try {
      selectedCommunity = await getCommunityReportDetail(collectionId, communityId, {
        level,
        entityLimit: 10,
        relationshipLimit: 10,
        documentLimit: 10
      });
    } catch (err) {
      error = errorMessage(err);
      selectedCommunity = null;
    } finally {
      detailLoading = false;
    }
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadReports();
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    await loadReports();
  }
</script>

<svelte:head>
  <title>{$t('reports.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('reports.title')}</h2>
  <p class="lead">{$t('reports.lead')}</p>
  <form on:submit={submit}>
    <div class="form-grid">
      <div class="field">
        <label for="reportLevel">{$t('reports.levelLabel')}</label>
        <input id="reportLevel" class="input" type="number" min="1" max="10" bind:value={level} />
      </div>
      <div class="field">
        <label for="reportSort">{$t('reports.sortLabel')}</label>
        <select id="reportSort" class="select" bind:value={sort}>
          <option value="rating">rating</option>
          <option value="size">size</option>
        </select>
      </div>
    </div>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('reports.loading') : $t('reports.submit')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

<section class="card">
  <h3>{$t('reports.patternsTitle')}</h3>
  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('reports.loading')}</div>
  {:else if !patterns.length}
    <p class="note">{$t('reports.emptyPatterns')}</p>
  {:else}
    <div class="result-grid">
      {#each patterns as item}
        <article class="result-card">
          <div class="table-title">{item.title || `${$t('reports.communityLabel')} ${item.community_id ?? '--'}`}</div>
          <div class="table-sub">rating: {item.rating ?? '--'} · size: {item.size ?? '--'}</div>
          <p class="result-text">{item.summary || '--'}</p>
        </article>
      {/each}
    </div>
  {/if}
</section>

<section class="card">
  <div class="card-header-inline">
    <h3>{$t('reports.communitiesTitle')}</h3>
    <span class="meta-text">{$t('reports.resultCount', { count: communities.length })}</span>
  </div>

  {#if loading}
    <div class="status" role="status" aria-live="polite">{$t('reports.loading')}</div>
  {:else if !communities.length}
    <p class="note">{$t('reports.emptyCommunities')}</p>
  {:else}
    <div class="result-grid result-grid--tasks">
      <div class="result-card">
        <div class="table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>{$t('reports.communityLabel')}</th>
                <th>{$t('reports.ratingLabel')}</th>
                <th>{$t('reports.sizeLabel')}</th>
              </tr>
            </thead>
            <tbody>
              {#each communities as item}
                <tr
                  class:selected-row={selectedCommunity?.community_id === item.community_id}
                  on:click={() => item.community_id !== undefined && item.community_id !== null && selectCommunity(String(item.community_id))}
                >
                  <td>{item.title || item.community_id || '--'}</td>
                  <td>{item.rating ?? '--'}</td>
                  <td>{item.size ?? '--'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>

      <div class="result-card">
        {#if detailLoading}
          <div class="status" role="status" aria-live="polite">{$t('reports.detailLoading')}</div>
        {:else if selectedCommunity}
          <div class="table-main">
            <div class="table-title">{selectedCommunity.title || selectedCommunity.community_id}</div>
            <div class="table-sub">
              {$t('reports.ratingLabel')}: {selectedCommunity.rating ?? '--'} · {$t('reports.sizeLabel')}: {selectedCommunity.size ?? '--'}
            </div>
          </div>
          <p class="result-text">{selectedCommunity.summary || '--'}</p>
          <div class="detail-chips">
            <span class="detail-chip">{$t('reports.entitiesLabel')}: {selectedCommunity.entities.length}</span>
            <span class="detail-chip">{$t('reports.relationshipsLabel')}: {selectedCommunity.relationships.length}</span>
            <span class="detail-chip">{$t('reports.documentsLabel')}: {selectedCommunity.documents.length}</span>
          </div>
        {:else}
          <p class="note">{$t('reports.emptyDetail')}</p>
        {/if}
      </div>
    </div>
  {/if}
</section>
