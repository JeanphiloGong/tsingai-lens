<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/stores';
  import Graph from 'graphology';
  import forceAtlas2 from 'graphology-layout-forceatlas2';
  import Sigma from 'sigma';
  import { errorMessage } from '../../../_shared/api';
  import { getBaseUrlValue, validateBaseUrl } from '../../../_shared/base';
  import { parseGraphml } from '../../../_shared/graphml';
  import { t } from '../../../_shared/i18n';

  const palette = [
    '#2b6ff7',
    '#3cc9f5',
    '#5aa2ff',
    '#31d0aa',
    '#f2b646',
    '#f08a5d',
    '#f55f8d',
    '#8c7bff',
    '#4b8bff',
    '#4ab4d3'
  ];

  $: collectionId = $page.params.id;

  let maxNodes = 200;
  let minWeight = 0;
  let communityId = '';
  let includeCommunity = true;
  let loading = false;
  let error = '';
  let status = '';

  let previewLoading = false;
  let previewError = '';
  let previewStatus = '';
  let previewStatusTimeout: ReturnType<typeof setTimeout> | null = null;
  let previewQuery = '';
  let communityFilter = 'all';
  let communityOptions: string[] = [];
  let colorByCommunity = true;
  let visibleNodes = 0;
  let visibleEdges = 0;
  let exportImageStatus = '';
  let layoutStatus = '';
  let graphContainer: HTMLDivElement | null = null;
  let renderer: Sigma | null = null;
  let graph: Graph | null = null;

  function disposeRenderer() {
    if (renderer) {
      renderer.kill();
      renderer = null;
    }
  }

  onDestroy(() => {
    if (previewStatusTimeout) {
      clearTimeout(previewStatusTimeout);
    }
    disposeRenderer();
    graph = null;
  });

  onMount(() => {
    loadPreview();
  });

  function setPreviewStatus(message: string) {
    if (previewStatusTimeout) {
      clearTimeout(previewStatusTimeout);
      previewStatusTimeout = null;
    }
    previewStatus = message;
    if (!message) return;
    previewStatusTimeout = setTimeout(() => {
      previewStatus = '';
      previewStatusTimeout = null;
    }, 2600);
  }

  function dismissPreviewStatus() {
    setPreviewStatus('');
  }

  function getGraphUrl() {
    const params = new URLSearchParams();
    params.set('collection_id', collectionId);
    params.set('max_nodes', String(maxNodes));
    params.set('min_weight', String(minWeight));
    if (communityId.trim()) {
      params.set('community_id', communityId.trim());
    }
    params.set('include_community', includeCommunity ? 'true' : 'false');

    const base = validateBaseUrl(getBaseUrlValue());
    return `${base}/retrieval/graphml?${params.toString()}`;
  }

  function buildGraph() {
    if (!graph) return;

    graph.forEachNode((node) => {
      const degree = graph ? graph.degree(node) : 0;
      const size = Math.max(4, Math.min(18, degree + 4));
      graph?.setNodeAttribute(node, 'size', size);
      graph?.setNodeAttribute(node, 'x', Math.random());
      graph?.setNodeAttribute(node, 'y', Math.random());
    });
  }

  function updateCommunityOptions() {
    if (!graph) {
      communityOptions = [];
      return;
    }
    const set = new Set<string>();
    graph.forEachNode((_node, attrs) => {
      if (!attrs.community && attrs.community !== 0) return;
      const value = String(attrs.community).trim();
      if (value) set.add(value);
    });
    communityOptions = Array.from(set).sort((a, b) => a.localeCompare(b));
  }

  function applyColors() {
    if (!graph) return;
    const colorMap = new Map<string, string>();
    communityOptions.forEach((community, index) => {
      colorMap.set(community, palette[index % palette.length]);
    });

    graph.forEachNode((node, attrs) => {
      const community = attrs.community ? String(attrs.community) : '';
      const color = colorByCommunity && community
        ? colorMap.get(community) ?? palette[0]
        : palette[0];
      graph?.setNodeAttribute(node, 'color', color);
      graph?.setNodeAttribute(node, 'label', attrs.label ?? node);
    });
    renderer?.refresh();
  }

  function applyViewFilters() {
    if (!graph) return;
    const query = previewQuery.trim().toLowerCase();
    const community = communityFilter;

    graph.forEachNode((node, attrs) => {
      const label = String(attrs.label ?? node).toLowerCase();
      const matchQuery = !query || label.includes(query);
      const matchCommunity = community === 'all' || String(attrs.community ?? '') === community;
      graph?.setNodeAttribute(node, 'hidden', !(matchQuery && matchCommunity));
    });

    graph.forEachEdge((edge, attrs, source, target) => {
      const weight = Number(attrs.weight ?? 1);
      const hidden =
        graph?.getNodeAttribute(source, 'hidden') ||
        graph?.getNodeAttribute(target, 'hidden') ||
        weight < minWeight;
      graph?.setEdgeAttribute(edge, 'hidden', hidden);
    });

    updateVisibleCounts();
    renderer?.refresh();
  }

  function updateVisibleCounts() {
    if (!graph) {
      visibleNodes = 0;
      visibleEdges = 0;
      return;
    }
    let nodes = 0;
    let edges = 0;
    graph.forEachNode((_node, attrs) => {
      if (!attrs.hidden) nodes += 1;
    });
    graph.forEachEdge((_edge, attrs) => {
      if (!attrs.hidden) edges += 1;
    });
    visibleNodes = nodes;
    visibleEdges = edges;
  }

  async function runLayout() {
    if (!graph) return;
    layoutStatus = '';
    try {
      forceAtlas2.assign(graph, {
        iterations: 120,
        settings: {
          scalingRatio: 6,
          gravity: 1.2,
          strongGravityMode: true
        }
      });
      layoutStatus = $t('graph.layoutDone');
      renderer?.refresh();
    } catch (err) {
      layoutStatus = errorMessage(err);
    }
  }

  function resetFilters() {
    previewQuery = '';
    communityFilter = 'all';
    applyViewFilters();
  }

  async function loadPreview() {
    previewError = '';
    setPreviewStatus('');
    exportImageStatus = '';
    previewLoading = true;

    try {
      const response = await fetch(getGraphUrl());
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const text = await response.text();
      const parsed = parseGraphml(text);
      const nextGraph = new Graph({ type: parsed.edgeDefault, multi: true });

      parsed.nodes.forEach((node) => {
        if (!nextGraph.hasNode(node.id)) {
          nextGraph.addNode(node.id, {
            label: node.label,
            community: node.community
          });
        }
      });

      parsed.edges.forEach((edge) => {
        if (!nextGraph.hasNode(edge.source) || !nextGraph.hasNode(edge.target)) return;
        if (nextGraph.hasEdge(edge.id)) return;
        nextGraph.addEdgeWithKey(edge.id, edge.source, edge.target, { weight: edge.weight });
      });

      graph = nextGraph;
      buildGraph();
      updateCommunityOptions();
      applyColors();
      forceAtlas2.assign(graph, {
        iterations: 120,
        settings: {
          scalingRatio: 6,
          gravity: 1.2,
          strongGravityMode: true
        }
      });

      disposeRenderer();
      if (graphContainer) {
        renderer = new Sigma(graph, graphContainer, {
          labelRenderedSizeThreshold: 6,
          renderEdgeLabels: false
        });
      }

      communityFilter = 'all';
      applyViewFilters();
      setPreviewStatus($t('graph.previewLoaded'));
    } catch (err) {
      previewError = errorMessage(err);
    } finally {
      previewLoading = false;
    }
  }

  function exportPreviewImage() {
    exportImageStatus = '';
    if (!graphContainer) return;
    const canvases = Array.from(graphContainer.querySelectorAll('canvas'));
    if (!canvases.length) return;

    const baseCanvas = canvases[0];
    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = baseCanvas.width;
    exportCanvas.height = baseCanvas.height;
    const context = exportCanvas.getContext('2d');
    if (!context) return;

    canvases.forEach((canvas) => {
      context.drawImage(canvas, 0, 0);
    });

    const fileName = `graph-${collectionId}-${Date.now()}.png`;
    const link = document.createElement('a');
    link.href = exportCanvas.toDataURL('image/png');
    link.download = fileName;
    link.click();
    exportImageStatus = $t('graph.imageExported');
  }

  async function downloadGraph() {
    error = '';
    status = '';
    loading = true;

    try {
      const response = await fetch(getGraphUrl());
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const fileName = `graph-${collectionId}-${Date.now()}.graphml`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(objectUrl);
      status = $t('graph.downloaded', { filename: fileName });
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{$t('graph.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="graph-preview-header">
    <div>
      <h2>{$t('graph.previewTitle')}</h2>
      <p class="lead">{$t('graph.previewLead')}</p>
    </div>
    <div class="preview-actions">
      <button class="btn btn--ghost" type="button" on:click={loadPreview} disabled={previewLoading}>
        {$t('graph.previewLoad')}
      </button>
      <button class="btn btn--ghost" type="button" on:click={exportPreviewImage} disabled={!graph}>
        {$t('graph.exportImage')}
      </button>
    </div>
  </div>

  <div class="graph-preview-body">
    <div class="graph-controls">
      <div class="field">
        <label for="preview-search">{$t('graph.searchLabel')}</label>
        <input
          id="preview-search"
          class="input"
          bind:value={previewQuery}
          placeholder={$t('graph.searchPlaceholder')}
          on:input={applyViewFilters}
          disabled={!graph}
        />
      </div>
      <div class="field">
        <label for="community-filter">{$t('graph.communityFilterLabel')}</label>
        <select
          id="community-filter"
          class="select"
          bind:value={communityFilter}
          on:change={applyViewFilters}
          disabled={!graph}
        >
          <option value="all">{$t('graph.communityAll')}</option>
          {#each communityOptions as community}
            <option value={community}>{community}</option>
          {/each}
        </select>
      </div>
      <div class="field">
        <label for="preview-min-weight">{$t('graph.minWeightLabel')}</label>
        <input
          id="preview-min-weight"
          class="input"
          type="number"
          step="0.1"
          bind:value={minWeight}
          on:input={applyViewFilters}
        />
      </div>
      <div class="toggle-row">
        <label>
          <input type="checkbox" bind:checked={colorByCommunity} on:change={applyColors} />
          {$t('graph.colorByCommunityLabel')}
        </label>
      </div>
      <div class="action-grid">
        <button class="btn btn--ghost btn--small" type="button" on:click={resetFilters} disabled={!graph}>
          {$t('graph.resetFilters')}
        </button>
        <button class="btn btn--ghost btn--small" type="button" on:click={runLayout} disabled={!graph}>
          {$t('graph.layoutRun')}
        </button>
      </div>
      <div class="graph-stats">
        <span>{$t('graph.visibleNodes')}: {visibleNodes}</span>
        <span>{$t('graph.visibleEdges')}: {visibleEdges}</span>
      </div>
      {#if graph && (!includeCommunity || !communityOptions.length)}
        <p class="note">{$t('graph.previewTipNoCommunity')}</p>
      {/if}
      {#if previewLoading}
        <div class="status" role="status" aria-live="polite">{$t('graph.previewLoading')}</div>
      {/if}
      {#if previewStatus}
        <div class="status status--dismissible" role="status" aria-live="polite">
          <span>{previewStatus}</span>
          <button
            class="status__close"
            type="button"
            aria-label={$t('graph.previewStatusClose')}
            on:click={dismissPreviewStatus}
          >
            x
          </button>
        </div>
      {/if}
      {#if previewError}
        <div class="status status--error" role="alert">{previewError}</div>
      {/if}
      {#if exportImageStatus}
        <div class="status" role="status" aria-live="polite">{exportImageStatus}</div>
      {/if}
      {#if layoutStatus}
        <div class="status" role="status" aria-live="polite">{layoutStatus}</div>
      {/if}
    </div>
    <div class="graph-canvas" bind:this={graphContainer} aria-label={$t('graph.previewCanvasLabel')}>
      {#if !graph && !previewLoading}
        <div class="graph-empty">{$t('graph.previewEmpty')}</div>
      {/if}
    </div>
  </div>
</section>

<section class="card">
  <h3>{$t('graph.title')}</h3>
  <p class="lead">{$t('graph.lead')}</p>
  <button class="btn btn--primary" type="button" on:click={downloadGraph} disabled={loading}>
    {loading ? $t('graph.downloading') : $t('graph.download')}
  </button>
  {#if status}
    <div class="status" role="status" aria-live="polite">{status}</div>
  {/if}
  {#if error}
    <div class="status status--error" role="alert">{error}</div>
  {/if}
</section>

<section class="card">
  <h3>{$t('graph.filtersTitle')}</h3>
  <p class="note">{$t('graph.filtersNote')}</p>
  <details class="advanced">
    <summary>{$t('graph.filtersTitle')}</summary>
    <div class="field">
      <label for="maxNodes">{$t('graph.maxNodesLabel')}</label>
      <input id="maxNodes" class="input" type="number" min="1" bind:value={maxNodes} />
    </div>
    <div class="field">
      <label for="minWeight">{$t('graph.minWeightLabel')}</label>
      <input
        id="minWeight"
        class="input"
        type="number"
        step="0.1"
        bind:value={minWeight}
        on:input={applyViewFilters}
      />
    </div>
    <div class="field">
      <label for="communityId">{$t('graph.communityLabel')}</label>
      <input id="communityId" class="input" bind:value={communityId} />
    </div>
    <div class="toggle-row">
      <label>
        <input type="checkbox" bind:checked={includeCommunity} />
        {$t('graph.includeCommunityLabel')}
      </label>
    </div>
  </details>
</section>

<section class="card">
  <h3>{$t('graph.statsTitle')}</h3>
  <p class="note">{$t('graph.statsPlaceholder')}</p>
</section>

<section class="card">
  <h3>{$t('graph.tipsTitle')}</h3>
  <ul class="result-list">
    <li>{$t('graph.tip1')}</li>
    <li>{$t('graph.tip2')}</li>
    <li>{$t('graph.tip3')}</li>
  </ul>
</section>
