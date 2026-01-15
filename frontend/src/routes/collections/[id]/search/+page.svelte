<script lang="ts">
  import { page } from '$app/stores';
  import { errorMessage, formatResult, requestJson } from '../../../_shared/api';
  import { t } from '../../../_shared/i18n';

  $: collectionId = $page.params.id;

  let query = '';
  let method = 'global';
  let responseType = 'List of 5-7 Points';
  let communityLevel = 2;
  let includeContext = false;
  let dynamicCommunity = false;
  let verbose = false;
  let loading = false;
  let error = '';
  let result: Record<string, unknown> | null = null;

  function extractEvidence(contextData: unknown) {
    if (!contextData) return [];
    if (Array.isArray(contextData)) {
      return contextData.map((item) => normalizeEvidenceItem(item));
    }
    if (typeof contextData === 'object') {
      const record = contextData as Record<string, unknown>;
      const keys = ['evidence', 'sources', 'documents', 'docs', 'chunks', 'passages'];
      for (const key of keys) {
        const value = record[key];
        if (Array.isArray(value)) {
          return value.map((item) => normalizeEvidenceItem(item));
        }
      }
    }
    return [];
  }

  function normalizeEvidenceItem(item: unknown) {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return String(item);
    const record = item as Record<string, unknown>;
    const text =
      record.snippet ||
      record.text ||
      record.content ||
      record.quote ||
      record.summary ||
      record.title;
    if (typeof text === 'string') return text;
    return JSON.stringify(record);
  }

  function extractCommunities(contextData: unknown) {
    if (!contextData || typeof contextData !== 'object') return [];
    const record = contextData as Record<string, unknown>;
    const candidates = record.communities || record.community || record.community_ids;
    if (Array.isArray(candidates)) {
      return candidates.map((item) => String(item));
    }
    if (typeof candidates === 'string' || typeof candidates === 'number') {
      return [String(candidates)];
    }
    return [];
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    result = null;

    if (!query.trim()) {
      error = $t('search.errorNoQuery');
      return;
    }

    loading = true;
    try {
      result = (await requestJson('/retrieval/query', {
        method: 'POST',
        body: JSON.stringify({
          collection_id: collectionId,
          query: query.trim(),
          method,
          response_type: responseType,
          community_level: communityLevel,
          dynamic_community_selection: dynamicCommunity,
          include_context: includeContext,
          verbose
        })
      })) as Record<string, unknown>;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('search.title')}</title>
</svelte:head>

<section class="card fade-up">
  <h2>{$t('search.title')}</h2>
  <p class="lead">{$t('search.lead')}</p>
  <form on:submit={submit}>
    <div class="field">
      <label for="query">{$t('search.inputLabel')}</label>
      <input id="query" class="input" bind:value={query} placeholder={$t('search.placeholder')} />
      <span class="meta-text">{$t('search.exampleText')}</span>
    </div>
    <details class="advanced">
      <summary>{$t('search.advanced')}</summary>
      <div class="field">
        <label for="method">{$t('search.methodLabel')}</label>
        <select id="method" class="select" bind:value={method}>
          <option value="global">global</option>
          <option value="local">local</option>
          <option value="drift">drift</option>
          <option value="basic">basic</option>
        </select>
      </div>
      <div class="field">
        <label for="responseType">{$t('search.responseTypeLabel')}</label>
        <input id="responseType" class="input" bind:value={responseType} />
      </div>
      <div class="field">
        <label for="communityLevel">{$t('search.communityLevelLabel')}</label>
        <input
          id="communityLevel"
          class="input"
          type="number"
          min="1"
          bind:value={communityLevel}
        />
      </div>
      <div class="toggle-row">
        <label>
          <input type="checkbox" bind:checked={includeContext} />
          {$t('search.includeContextLabel')}
        </label>
        <label>
          <input type="checkbox" bind:checked={dynamicCommunity} disabled={method !== 'global'} />
          {$t('search.dynamicCommunityLabel')}
        </label>
        <label>
          <input type="checkbox" bind:checked={verbose} />
          {$t('search.verboseLabel')}
        </label>
      </div>
    </details>
    <button class="btn btn--primary" type="submit" disabled={loading}>
      {loading ? $t('search.searching') : $t('search.submit')}
    </button>
  </form>
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

{#if result}
  <section class="card">
    <h3>{$t('search.resultTitle')}</h3>
    <div class="result-grid">
      <div class="result-card">
        <h4>{$t('search.summaryTitle')}</h4>
        <p class="result-text">
          {typeof result.answer === 'string' ? result.answer : formatResult(result.answer)}
        </p>
      </div>
      <div class="result-card">
        <h4>{$t('search.evidenceTitle')}</h4>
        {#if result.context_data && extractEvidence(result.context_data).length}
          <ul class="result-list">
            {#each extractEvidence(result.context_data) as item}
              <li>{item}</li>
            {/each}
          </ul>
        {:else}
          <p class="meta-text">{$t('search.noEvidence')}</p>
        {/if}
      </div>
      <div class="result-card">
        <h4>{$t('search.communitiesTitle')}</h4>
        {#if result.context_data && extractCommunities(result.context_data).length}
          <ul class="result-list">
            {#each extractCommunities(result.context_data) as item}
              <li>{item}</li>
            {/each}
          </ul>
        {:else}
          <p class="meta-text">{$t('search.noEvidence')}</p>
        {/if}
      </div>
    </div>
    <details class="advanced">
      <summary>{$t('search.rawResponse')}</summary>
      <pre class="code-block">{formatResult(result)}</pre>
    </details>
    {#if result.context_data}
      <details class="advanced">
        <summary>{$t('search.rawContext')}</summary>
        <pre class="code-block">{formatResult(result.context_data)}</pre>
      </details>
    {/if}
  </section>
{/if}
