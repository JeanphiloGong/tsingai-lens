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

  type NodeDetail = {
    id: string;
    label: string;
    type?: string;
    description?: string;
    community?: string;
    degree?: number;
    frequency?: number;
    node_text_unit_ids?: string;
    node_text_unit_count?: number;
    node_document_ids?: string;
    node_document_titles?: string;
    node_document_count?: number;
  };

  type EdgeDetail = {
    id: string;
    source: string;
    target: string;
    sourceLabel: string;
    targetLabel: string;
    weight?: number;
    edge_description?: string;
    edge_text_unit_ids?: string;
    edge_text_unit_count?: number;
    edge_document_ids?: string;
    edge_document_titles?: string;
    edge_document_count?: number;
  };

  type EvidencePreview = {
    items: string[];
    extra: number;
  };

  const listPreviewLimit = 4;
  const emptyPreview: EvidencePreview = { items: [], extra: 0 };

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
  let themeObserver: MutationObserver | null = null;
  let selectedNode: NodeDetail | null = null;
  let selectedEdge: EdgeDetail | null = null;
  let nodeDocumentPreview: EvidencePreview = emptyPreview;
  let nodeTextUnitPreview: EvidencePreview = emptyPreview;
  let edgeDocumentPreview: EvidencePreview = emptyPreview;
  let edgeTextUnitPreview: EvidencePreview = emptyPreview;

  $: nodeDocumentPreview = selectedNode
    ? buildPreview(selectedNode.node_document_titles || selectedNode.node_document_ids)
    : emptyPreview;
  $: nodeTextUnitPreview = selectedNode ? buildPreview(selectedNode.node_text_unit_ids) : emptyPreview;
  $: edgeDocumentPreview = selectedEdge
    ? buildPreview(selectedEdge.edge_document_titles || selectedEdge.edge_document_ids)
    : emptyPreview;
  $: edgeTextUnitPreview = selectedEdge ? buildPreview(selectedEdge.edge_text_unit_ids) : emptyPreview;

  function disposeRenderer() {
    if (renderer) {
      renderer.kill();
      renderer = null;
    }
  }

  function getThemeInk() {
    if (typeof window === 'undefined') return '#0f1b2d';
    const value = getComputedStyle(document.documentElement).getPropertyValue('--color-ink').trim();
    return value || '#0f1b2d';
  }

  function applyRendererTheme() {
    if (!renderer) return;
    const ink = getThemeInk();
    renderer.setSetting('labelColor', { color: ink });
    renderer.setSetting('edgeLabelColor', { color: ink });
    renderer.setSetting('defaultEdgeColor', ink);
  }

  function toText(value: unknown) {
    if (value === undefined || value === null) return undefined;
    const text = String(value).trim();
    return text ? text : undefined;
  }

  function toNumber(value: unknown) {
    if (value === undefined || value === null) return undefined;
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  function splitList(value?: string) {
    if (!value) return [];
    const trimmed = value.trim();
    if (!trimmed) return [];
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed)) {
          return parsed.map((item) => String(item).trim()).filter(Boolean);
        }
      } catch {
        // fall through to delimiter handling
      }
    }
    const separators = ['|', ';', ','];
    for (const separator of separators) {
      if (trimmed.includes(separator)) {
        return trimmed
          .split(separator)
          .map((item) => item.trim())
          .filter(Boolean);
      }
    }
    return [trimmed];
  }

  function buildPreview(value?: string): EvidencePreview {
    const items = splitList(value);
    const limited = items.slice(0, listPreviewLimit);
    return {
      items: limited,
      extra: Math.max(0, items.length - limited.length)
    };
  }

  function getNodeLabel(nodeId: string) {
    if (!graph) return nodeId;
    const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
    return String(attrs.label ?? nodeId);
  }

  function clearSelection() {
    selectedNode = null;
    selectedEdge = null;
  }

  function selectNode(nodeId: string) {
    if (!graph) return;
    const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
    selectedEdge = null;
    selectedNode = {
      id: nodeId,
      label: String(attrs.label ?? nodeId),
      type: toText(attrs.type),
      description: toText(attrs.description),
      community: toText(attrs.community),
      degree: toNumber(attrs.degree) ?? graph.degree(nodeId),
      frequency: toNumber(attrs.frequency),
      node_text_unit_ids: toText(attrs.node_text_unit_ids),
      node_text_unit_count: toNumber(attrs.node_text_unit_count),
      node_document_ids: toText(attrs.node_document_ids),
      node_document_titles: toText(attrs.node_document_titles),
      node_document_count: toNumber(attrs.node_document_count)
    };
  }

  function selectEdge(edgeId: string) {
    if (!graph) return;
    const attrs = graph.getEdgeAttributes(edgeId) as Record<string, unknown>;
    const source = graph.source(edgeId) as string;
    const target = graph.target(edgeId) as string;
    selectedNode = null;
    selectedEdge = {
      id: edgeId,
      source,
      target,
      sourceLabel: getNodeLabel(source),
      targetLabel: getNodeLabel(target),
      weight: toNumber(attrs.weight),
      edge_description: toText(attrs.edge_description),
      edge_text_unit_ids: toText(attrs.edge_text_unit_ids),
      edge_text_unit_count: toNumber(attrs.edge_text_unit_count),
      edge_document_ids: toText(attrs.edge_document_ids),
      edge_document_titles: toText(attrs.edge_document_titles),
      edge_document_count: toNumber(attrs.edge_document_count)
    };
  }

  function attachRendererEvents() {
    if (!renderer) return;
    renderer.on('clickNode', (payload) => {
      selectNode(payload.node);
    });
    renderer.on('clickEdge', (payload) => {
      selectEdge(payload.edge);
    });
    renderer.on('clickStage', () => {
      clearSelection();
    });
  }

  onDestroy(() => {
    if (previewStatusTimeout) {
      clearTimeout(previewStatusTimeout);
    }
    if (themeObserver) {
      themeObserver.disconnect();
      themeObserver = null;
    }
    disposeRenderer();
    graph = null;
  });

  onMount(() => {
    loadPreview();
    if (typeof MutationObserver !== 'undefined') {
      themeObserver = new MutationObserver(() => {
        applyRendererTheme();
      });
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
      });
    }
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

    graph.forEachNode((node, attrs) => {
      const degree = graph ? graph.degree(node) : 0;
      const size = Math.max(4, Math.min(18, degree + 4));
      graph?.setNodeAttribute(node, 'size', size);
      if (typeof attrs.x !== 'number') {
        graph?.setNodeAttribute(node, 'x', Math.random());
      }
      if (typeof attrs.y !== 'number') {
        graph?.setNodeAttribute(node, 'y', Math.random());
      }
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
    clearSelection();
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
            community: node.community,
            type: node.type,
            description: node.description,
            degree: node.degree,
            frequency: node.frequency,
            x: node.x,
            y: node.y,
            node_text_unit_ids: node.node_text_unit_ids,
            node_text_unit_count: node.node_text_unit_count,
            node_document_ids: node.node_document_ids,
            node_document_titles: node.node_document_titles,
            node_document_count: node.node_document_count
          });
        }
      });

      parsed.edges.forEach((edge) => {
        if (!nextGraph.hasNode(edge.source) || !nextGraph.hasNode(edge.target)) return;
        if (nextGraph.hasEdge(edge.id)) return;
        nextGraph.addEdgeWithKey(edge.id, edge.source, edge.target, {
          weight: edge.weight,
          edge_description: edge.edge_description,
          edge_text_unit_ids: edge.edge_text_unit_ids,
          edge_text_unit_count: edge.edge_text_unit_count,
          edge_document_ids: edge.edge_document_ids,
          edge_document_titles: edge.edge_document_titles,
          edge_document_count: edge.edge_document_count
        });
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
          renderEdgeLabels: false,
          enableEdgeClickEvents: true
        });
        applyRendererTheme();
        attachRendererEvents();
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
      <div class="graph-details">
        <div class="graph-details__header">
          <span>{$t('graph.detailsTitle')}</span>
          {#if selectedNode || selectedEdge}
            <button class="btn btn--ghost btn--small" type="button" on:click={clearSelection}>
              {$t('graph.detailsClear')}
            </button>
          {/if}
        </div>
        {#if selectedNode}
          <div class="detail-primary">
            <span class="detail-tag">{$t('graph.detailsNode')}</span>
            <span class="detail-name">{selectedNode.label}</span>
          </div>
          <dl class="detail-list">
            {#if selectedNode.type}
              <div class="detail-row">
                <dt>{$t('graph.detailType')}</dt>
                <dd>{selectedNode.type}</dd>
              </div>
            {/if}
            {#if selectedNode.community}
              <div class="detail-row">
                <dt>{$t('graph.detailCommunity')}</dt>
                <dd>{selectedNode.community}</dd>
              </div>
            {/if}
            {#if typeof selectedNode.degree === 'number'}
              <div class="detail-row">
                <dt>{$t('graph.detailDegree')}</dt>
                <dd>{selectedNode.degree}</dd>
              </div>
            {/if}
            {#if typeof selectedNode.frequency === 'number'}
              <div class="detail-row">
                <dt>{$t('graph.detailFrequency')}</dt>
                <dd>{selectedNode.frequency}</dd>
              </div>
            {/if}
            {#if selectedNode.description}
              <div class="detail-row detail-row--wide">
                <dt>{$t('graph.detailDescription')}</dt>
                <dd>{selectedNode.description}</dd>
              </div>
            {/if}
          </dl>
          {#if typeof selectedNode.node_document_count === 'number' || nodeDocumentPreview.items.length}
            <div class="detail-section">
              <div class="detail-section__title">
                {$t('graph.detailDocuments')}
                {#if typeof selectedNode.node_document_count === 'number'}
                  <span class="detail-count">{selectedNode.node_document_count}</span>
                {/if}
              </div>
              {#if nodeDocumentPreview.items.length}
                <div class="detail-chips">
                  {#each nodeDocumentPreview.items as item}
                    <span class="detail-chip">{item}</span>
                  {/each}
                  {#if nodeDocumentPreview.extra > 0}
                    <span class="detail-chip detail-chip--muted">+{nodeDocumentPreview.extra}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
          {#if typeof selectedNode.node_text_unit_count === 'number' || nodeTextUnitPreview.items.length}
            <div class="detail-section">
              <div class="detail-section__title">
                {$t('graph.detailTextUnits')}
                {#if typeof selectedNode.node_text_unit_count === 'number'}
                  <span class="detail-count">{selectedNode.node_text_unit_count}</span>
                {/if}
              </div>
              {#if nodeTextUnitPreview.items.length}
                <div class="detail-chips">
                  {#each nodeTextUnitPreview.items as item}
                    <span class="detail-chip">{item}</span>
                  {/each}
                  {#if nodeTextUnitPreview.extra > 0}
                    <span class="detail-chip detail-chip--muted">+{nodeTextUnitPreview.extra}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        {:else if selectedEdge}
          <div class="detail-primary">
            <span class="detail-tag">{$t('graph.detailsEdge')}</span>
            <span class="detail-name">{selectedEdge.sourceLabel} -> {selectedEdge.targetLabel}</span>
          </div>
          <dl class="detail-list">
            {#if typeof selectedEdge.weight === 'number'}
              <div class="detail-row">
                <dt>{$t('graph.detailWeight')}</dt>
                <dd>{selectedEdge.weight}</dd>
              </div>
            {/if}
            {#if selectedEdge.edge_description}
              <div class="detail-row detail-row--wide">
                <dt>{$t('graph.detailDescription')}</dt>
                <dd>{selectedEdge.edge_description}</dd>
              </div>
            {/if}
          </dl>
          {#if typeof selectedEdge.edge_document_count === 'number' || edgeDocumentPreview.items.length}
            <div class="detail-section">
              <div class="detail-section__title">
                {$t('graph.detailDocuments')}
                {#if typeof selectedEdge.edge_document_count === 'number'}
                  <span class="detail-count">{selectedEdge.edge_document_count}</span>
                {/if}
              </div>
              {#if edgeDocumentPreview.items.length}
                <div class="detail-chips">
                  {#each edgeDocumentPreview.items as item}
                    <span class="detail-chip">{item}</span>
                  {/each}
                  {#if edgeDocumentPreview.extra > 0}
                    <span class="detail-chip detail-chip--muted">+{edgeDocumentPreview.extra}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
          {#if typeof selectedEdge.edge_text_unit_count === 'number' || edgeTextUnitPreview.items.length}
            <div class="detail-section">
              <div class="detail-section__title">
                {$t('graph.detailTextUnits')}
                {#if typeof selectedEdge.edge_text_unit_count === 'number'}
                  <span class="detail-count">{selectedEdge.edge_text_unit_count}</span>
                {/if}
              </div>
              {#if edgeTextUnitPreview.items.length}
                <div class="detail-chips">
                  {#each edgeTextUnitPreview.items as item}
                    <span class="detail-chip">{item}</span>
                  {/each}
                  {#if edgeTextUnitPreview.extra > 0}
                    <span class="detail-chip detail-chip--muted">+{edgeTextUnitPreview.extra}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        {:else}
          <p class="meta-text">{$t('graph.detailsEmpty')}</p>
        {/if}
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
