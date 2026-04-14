<script lang="ts">
  import { browser } from '$app/environment';
  import { page } from '$app/stores';
  import { tick } from 'svelte';
  import { errorMessage } from '../../../../_shared/api';
  import { t } from '../../../../_shared/i18n';
  import {
    buildDocumentViewerHref,
    fetchDocumentContent,
    fetchEvidenceTraceback,
    type DocumentContentResponse,
    type DocumentContentSection,
    type EvidenceTracebackResponse,
    type TracebackAnchor
  } from '../../../../_shared/traceback';

  let content: DocumentContentResponse | null = null;
  let traceback: EvidenceTracebackResponse | null = null;
  let loading = false;
  let contentError = '';
  let tracebackError = '';
  let loadedKey = '';
  let selectedAnchorId = '';
  let resolvedDocumentId = '';

  $: collectionId = $page.params.id ?? '';
  $: routeDocumentId = $page.params.document_id ?? '';
  $: evidenceId = $page.url.searchParams.get('evidence_id')?.trim() ?? '';
  $: requestedAnchorId = $page.url.searchParams.get('anchor_id')?.trim() ?? '';
  $: loadKey = [collectionId, routeDocumentId, evidenceId, requestedAnchorId].join(':');
  $: selectedAnchor =
    traceback?.anchors.find((anchor) => anchor.anchor_id === selectedAnchorId) ?? traceback?.anchors[0] ?? null;
  $: if (collectionId && routeDocumentId && loadKey !== loadedKey) {
    loadedKey = loadKey;
    void loadDocumentViewer();
  }

  function defaultReturnTo() {
    return `/collections/${collectionId}/documents`;
  }

  function backHref() {
    const target = $page.url.searchParams.get('return_to')?.trim();
    if (target && target.startsWith(`/collections/${collectionId}`)) {
      return target;
    }
    return defaultReturnTo();
  }

  async function loadDocumentViewer() {
    loading = true;
    contentError = '';
    tracebackError = '';
    content = null;
    traceback = null;
    selectedAnchorId = '';
    resolvedDocumentId = routeDocumentId;
    let initialAnchor: TracebackAnchor | null = null;

    if (evidenceId) {
      try {
        traceback = await fetchEvidenceTraceback(collectionId, evidenceId);
        initialAnchor =
          traceback.anchors.find((anchor) => anchor.anchor_id === requestedAnchorId) ?? traceback.anchors[0] ?? null;
        selectedAnchorId = initialAnchor?.anchor_id ?? '';
        if (initialAnchor?.document_id) {
          resolvedDocumentId = initialAnchor.document_id;
        }
      } catch (err) {
        tracebackError = errorMessage(err);
      }
    }

    try {
      content = await fetchDocumentContent(collectionId, resolvedDocumentId);
      resolvedDocumentId = content.document_id;
      if (browser && resolvedDocumentId !== routeDocumentId) {
        history.replaceState(
          history.state,
          '',
          buildDocumentViewerHref(collectionId, resolvedDocumentId, {
            evidenceId,
            anchorId: selectedAnchorId || requestedAnchorId || null,
            returnTo: backHref()
          })
        );
      }
    } catch (err) {
      contentError = errorMessage(err);
    } finally {
      loading = false;
    }

    if (initialAnchor?.section_id) {
      await scrollToSection(initialAnchor.section_id);
    }
  }

  function traceStatusLabel(status?: EvidenceTracebackResponse['traceback_status'] | null) {
    if (status === 'ready') return $t('traceback.statusReady');
    if (status === 'partial') return $t('traceback.statusPartial');
    return $t('traceback.statusUnavailable');
  }

  function traceStatusBody(status?: EvidenceTracebackResponse['traceback_status'] | null) {
    if (status === 'ready') return $t('traceback.statusReadyBody');
    if (status === 'partial') return $t('traceback.statusPartialBody');
    return $t('traceback.statusUnavailableBody');
  }

  function locatorLabel(anchor: TracebackAnchor) {
    if (anchor.locator_type === 'char_range') return $t('traceback.locatorCharRange');
    if (anchor.locator_type === 'bbox') return $t('traceback.locatorBBox');
    return $t('traceback.locatorSection');
  }

  function confidenceLabel(anchor: TracebackAnchor) {
    if (anchor.locator_confidence === 'high') return $t('traceback.confidenceHigh');
    if (anchor.locator_confidence === 'medium') return $t('traceback.confidenceMedium');
    return $t('traceback.confidenceLow');
  }

  function highlightParts(text: string, quote: string | null) {
    const normalizedQuote = quote?.trim();
    if (!normalizedQuote) return null;

    const index = text.indexOf(normalizedQuote);
    if (index < 0) return null;

    return {
      before: text.slice(0, index),
      match: text.slice(index, index + normalizedQuote.length),
      after: text.slice(index + normalizedQuote.length)
    };
  }

  function highlightFor(section: DocumentContentSection) {
    if (!selectedAnchor || selectedAnchor.section_id !== section.section_id) return null;
    return highlightParts(section.text, selectedAnchor.quote);
  }

  function sectionTitle(section: DocumentContentSection) {
    return section.title || section.section_type || section.section_id;
  }

  function pageLabel(section: DocumentContentSection) {
    if (section.page === null) return null;
    return $t('traceback.pageLabel', { page: section.page });
  }

  async function scrollToSection(sectionId: string) {
    if (!browser) return;
    await tick();
    const target = document.getElementById(`section-${sectionId}`);
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function selectAnchor(anchor: TracebackAnchor) {
    selectedAnchorId = anchor.anchor_id;
    if (anchor.section_id) {
      await scrollToSection(anchor.section_id);
    }
  }

  function documentTitle() {
    return content?.title || routeDocumentId;
  }

  function documentSubtitle() {
    return content?.source_filename || null;
  }

  function sectionCount() {
    return content?.sections.length ?? 0;
  }

  function showTracebackPanel() {
    return Boolean(evidenceId || traceback || tracebackError);
  }
</script>

<svelte:head>
  <title>{$t('traceback.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="card-header-inline">
    <div>
      <h2>{$t('traceback.title')}</h2>
      <p class="lead">{$t('traceback.lead')}</p>
    </div>
    <a class="btn btn--ghost btn--small" href={backHref()}>
      {$t('traceback.back')}
    </a>
  </div>

  {#if loading}
    <div class="status" role="status">{$t('traceback.loading')}</div>
  {:else}
    {#if contentError}
      <div class="status status--error" role="alert">{contentError}</div>
    {/if}

    {#if tracebackError}
      <div class="status status--error" role="alert">{tracebackError}</div>
    {/if}

    <div class="result-grid result-grid--tasks">
      <article class="result-card">
        <h3>{$t('traceback.documentCardTitle')}</h3>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>{$t('traceback.documentLabel')}</dt>
            <dd>{documentTitle()}</dd>
          </div>
          {#if documentSubtitle()}
            <div class="detail-row">
              <dt>{$t('traceback.sourceFileLabel')}</dt>
              <dd>{documentSubtitle()}</dd>
            </div>
          {/if}
          <div class="detail-row">
            <dt>{$t('traceback.sectionCountLabel')}</dt>
            <dd>{sectionCount()}</dd>
          </div>
          {#if content?.page_count !== null}
            <div class="detail-row">
              <dt>{$t('traceback.pageCountLabel')}</dt>
              <dd>{content?.page_count}</dd>
            </div>
          {/if}
        </dl>
      </article>

      {#if showTracebackPanel()}
        <article class="result-card">
          <h3>{$t('traceback.traceCardTitle')}</h3>
          <p class="result-text">{traceStatusLabel(traceback?.traceback_status)}</p>
          <p class="note">{traceStatusBody(traceback?.traceback_status)}</p>
          {#if selectedAnchor}
            <dl class="detail-list">
              <div class="detail-row">
                <dt>{$t('traceback.locatorLabel')}</dt>
                <dd>{locatorLabel(selectedAnchor)}</dd>
              </div>
              <div class="detail-row">
                <dt>{$t('traceback.precisionLabel')}</dt>
                <dd>{confidenceLabel(selectedAnchor)}</dd>
              </div>
              {#if selectedAnchor.page !== null}
                <div class="detail-row">
                  <dt>{$t('traceback.pageNumberLabel')}</dt>
                  <dd>{selectedAnchor.page}</dd>
                </div>
              {/if}
            </dl>
          {/if}
        </article>
      {/if}
    </div>

    {#if showTracebackPanel() && traceback?.anchors.length}
      <section class="detail-section">
        <div class="detail-section__title">{$t('traceback.anchorsTitle')}</div>
        <div class="result-grid">
          {#each traceback.anchors as anchor}
            <button
              class:selected-anchor={selectedAnchor?.anchor_id === anchor.anchor_id}
              class="result-card traceback-anchor"
              type="button"
              on:click={() => void selectAnchor(anchor)}
            >
              <div class="table-main">
                <div class="table-title">{locatorLabel(anchor)}</div>
                <div class="table-sub">{confidenceLabel(anchor)}</div>
              </div>
              {#if anchor.quote}
                <p class="result-text">{anchor.quote}</p>
              {/if}
              <div class="note">
                {#if anchor.page !== null}
                  {$t('traceback.pageLabel', { page: anchor.page })}
                {/if}
                {#if anchor.section_id}
                  {anchor.page !== null ? ' · ' : ''}{$t('traceback.sectionLabel', { section: anchor.section_id })}
                {/if}
              </div>
            </button>
          {/each}
        </div>
      </section>
    {/if}

    {#if content?.sections.length}
      <section class="detail-section">
        <div class="detail-section__title">{$t('traceback.sectionsTitle')}</div>
        <div class="section-nav">
          {#each content.sections as section}
            <button class="btn btn--ghost btn--small" type="button" on:click={() => void scrollToSection(section.section_id)}>
              {sectionTitle(section)}
            </button>
          {/each}
        </div>
      </section>

      <section class="result-grid">
        {#each content.sections as section}
          <article
            class:document-section--active={selectedAnchor?.section_id === section.section_id}
            class="result-card document-section"
            id={`section-${section.section_id}`}
          >
            <div class="table-main">
              <div class="table-title">{sectionTitle(section)}</div>
              {#if pageLabel(section)}
                <div class="table-sub">{pageLabel(section)}</div>
              {/if}
            </div>

            {#if highlightFor(section)}
              {@const parts = highlightFor(section)}
              {#if parts}
                <p class="document-text">{parts.before}<mark>{parts.match}</mark>{parts.after}</p>
              {:else}
                <p class="document-text">{section.text}</p>
              {/if}
            {:else}
              <p class="document-text">{section.text}</p>
            {/if}

            {#if selectedAnchor?.section_id === section.section_id && selectedAnchor.quote && !highlightFor(section)}
              <section class="detail-section">
                <div class="detail-section__title">{$t('traceback.quoteTitle')}</div>
                <p class="result-text">{selectedAnchor.quote}</p>
              </section>
            {/if}
          </article>
        {/each}
      </section>
    {:else if !contentError}
      <p class="note">{$t('traceback.empty')}</p>
    {/if}
  {/if}
</section>

<style>
  .traceback-anchor {
    width: 100%;
    text-align: left;
  }

  .selected-anchor {
    border-color: var(--accent, #2f5bd2);
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent, #2f5bd2) 40%, transparent);
  }

  .section-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .document-section {
    scroll-margin-top: 5rem;
  }

  .document-section--active {
    border-color: var(--accent, #2f5bd2);
  }

  .document-text {
    white-space: pre-wrap;
    line-height: 1.7;
  }
</style>
