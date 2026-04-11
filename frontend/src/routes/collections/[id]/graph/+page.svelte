<script lang="ts">
  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import Graph from 'graphology';
  import forceAtlas2 from 'graphology-layout-forceatlas2';
  import Sigma from 'sigma';
  import { errorMessage, isHttpStatusError } from '../../../_shared/api';
  import { buildCollectionGraphmlUrl, fetchCollectionGraph, type GraphEdge, type GraphNode } from '../../../_shared/graph';
  import { t } from '../../../_shared/i18n';
  import {
    fetchWorkspaceOverview,
    getWorkspaceSurfaceState,
    type WorkspaceOverview
  } from '../../../_shared/workspace';

  const palette = ['#2b6ff7', '#3cc9f5', '#31d0aa', '#f2b646', '#f55f8d', '#8c7bff'];

  type NodeDetail = GraphNode;
  type EdgeDetail = GraphEdge & { sourceLabel: string; targetLabel: string };

  let collectionId = '';

  $: collectionId = $page.params.id ?? '';

  let maxNodes = 200;
  let minWeight = 0;
  let communityId = '';
  let previewQuery = '';
  let loading = false;
  let error = '';
  let status = '';
  let workspace: WorkspaceOverview | null = null;
  let notFound = false;
  let visibleNodes = 0;
  let visibleEdges = 0;
  let graphContainer: HTMLDivElement | null = null;
  let renderer: Sigma | null = null;
  let graph: Graph | null = null;
  let graphMeta: { truncated: boolean; community?: string | null } | null = null;
  let selectedNode: NodeDetail | null = null;
  let selectedEdge: EdgeDetail | null = null;
  let loadedCollectionId = '';
  $: surfaceState = getWorkspaceSurfaceState(workspace, 'graph');
  $: showFallbackState =
    Boolean(workspace) &&
    !loading &&
    !visibleNodes &&
    (surfaceState !== 'ready' || notFound);

  function disposeRenderer() {
    if (renderer) {
      renderer.kill();
      renderer = null;
    }
  }

  function nodeColor(type?: string | null) {
    if (!type) return palette[0];
    const sum = type.split('').reduce((acc, item) => acc + item.charCodeAt(0), 0);
    return palette[sum % palette.length];
  }

  function getNodeLabel(nodeId: string) {
    if (!graph) return nodeId;
    const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
    return String(attrs.label ?? nodeId);
  }

  function selectNode(nodeId: string) {
    if (!graph) return;
    const attrs = graph.getNodeAttributes(nodeId) as Record<string, unknown>;
    selectedEdge = null;
    selectedNode = {
      id: nodeId,
      label: String(attrs.label ?? nodeId),
      type: typeof attrs.entityType === 'string' ? attrs.entityType : null,
      description: typeof attrs.description === 'string' ? attrs.description : null,
      degree: typeof attrs.degree === 'number' ? attrs.degree : null,
      frequency: typeof attrs.frequency === 'number' ? attrs.frequency : null,
      x: typeof attrs.x === 'number' ? attrs.x : null,
      y: typeof attrs.y === 'number' ? attrs.y : null
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
      weight: typeof attrs.weight === 'number' ? attrs.weight : null,
      description: typeof attrs.description === 'string' ? attrs.description : null,
      rank: typeof attrs.rank === 'number' ? attrs.rank : null
    };
  }

  function clearSelection() {
    selectedNode = null;
    selectedEdge = null;
  }

  function updateVisibility() {
    if (!graph) return;

    const query = previewQuery.trim().toLowerCase();

    graph.forEachNode((node, attrs) => {
      const label = String(attrs.label ?? '').toLowerCase();
      const matches = !query || label.includes(query) || String(node).toLowerCase().includes(query);
      graph?.setNodeAttribute(node, 'hidden', !matches);
    });

    graph.forEachEdge((edge, _attrs, source, target) => {
      const hidden = graph?.getNodeAttribute(source, 'hidden') || graph?.getNodeAttribute(target, 'hidden');
      graph?.setEdgeAttribute(edge, 'hidden', Boolean(hidden));
    });

    visibleNodes = graph.filterNodes((node) => !graph?.getNodeAttribute(node, 'hidden')).length;
    visibleEdges = graph.filterEdges((edge) => !graph?.getEdgeAttribute(edge, 'hidden')).length;
    renderer?.refresh();
  }

  function attachRendererEvents() {
    if (!renderer) return;
    renderer.on('clickNode', (payload) => selectNode(payload.node));
    renderer.on('clickEdge', (payload) => selectEdge(payload.edge));
    renderer.on('clickStage', () => clearSelection());
  }

  function renderGraph(nodes: GraphNode[], edges: GraphEdge[]) {
    disposeRenderer();
    clearSelection();
    graph = new Graph();

    for (const node of nodes) {
      graph.addNode(node.id, {
        label: node.label,
        type: 'circle',
        entityType: node.type,
        description: node.description,
        degree: node.degree ?? 0,
        frequency: node.frequency ?? 0,
        x: typeof node.x === 'number' ? node.x : Math.random(),
        y: typeof node.y === 'number' ? node.y : Math.random(),
        size: Math.max(4, Math.min(18, (node.degree ?? 1) + 4)),
        color: nodeColor(node.type)
      });
    }

    for (const edge of edges) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const edgeId = edge.id || `${edge.source}-${edge.target}`;
      if (graph.hasEdge(edgeId)) continue;
      graph.addEdgeWithKey(edgeId, edge.source, edge.target, {
        weight: edge.weight ?? 1,
        description: edge.description,
        rank: edge.rank ?? 0,
        size: Math.max(1, Math.min(8, edge.weight ?? 1)),
        color: 'rgba(15, 27, 45, 0.25)'
      });
    }

    if (graph.order > 1) {
      forceAtlas2.assign(graph, 80);
    }

    if (graphContainer) {
      renderer = new Sigma(graph, graphContainer, {
        renderLabels: true,
        labelSize: 12,
        defaultEdgeType: 'line'
      });
      attachRendererEvents();
    }

    updateVisibility();
  }

  async function loadGraph() {
    loading = true;
    error = '';
    status = '';
    notFound = false;

    const [graphResult, workspaceResult] = await Promise.allSettled([
      fetchCollectionGraph(collectionId, {
        maxNodes,
        minWeight,
        communityId: communityId.trim()
      }),
      fetchWorkspaceOverview(collectionId)
    ]);

    workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

    try {
      if (graphResult.status !== 'fulfilled') {
        throw graphResult.reason;
      }

      const response = graphResult.value;
      graphMeta = {
        truncated: response.truncated,
        community: response.community
      };
      renderGraph(response.nodes, response.edges);
      status = response.truncated ? $t('graph.previewLoadedTruncated') : $t('graph.previewLoaded');
    } catch (err) {
      error = errorMessage(err);
      notFound = isHttpStatusError(err, 404);
      graphMeta = null;
      disposeRenderer();
      graph = null;
      visibleNodes = 0;
      visibleEdges = 0;
    } finally {
      loading = false;
    }
  }

  async function downloadGraphml() {
    try {
      status = $t('graph.downloading');
      const response = await fetch(
        buildCollectionGraphmlUrl(collectionId, {
          maxNodes,
          minWeight,
          communityId: communityId.trim()
        })
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const disposition = response.headers.get('content-disposition') ?? '';
      const matched = disposition.match(/filename="(.+?)"/i);
      const fileName = matched?.[1] ?? `graph-${collectionId}.graphml`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(url);
      status = $t('graph.downloaded', { filename: fileName });
    } catch (err) {
      error = errorMessage(err);
    }
  }

  function exportImage() {
    const canvas = graphContainer?.querySelector('canvas');
    if (!(canvas instanceof HTMLCanvasElement)) return;

    const url = canvas.toDataURL('image/png');
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `graph-${collectionId}.png`;
    anchor.click();
    status = $t('graph.imageExported');
  }

  function resetFilters() {
    previewQuery = '';
    updateVisibility();
  }

  function stateCardTitle() {
    return $t(`overview.surfaceStateCards.${surfaceState}.title`);
  }

  function stateCardBody() {
    return $t(`overview.surfaceStateCards.${surfaceState}.body`);
  }

  $: if (graph) {
    updateVisibility();
  }

  $: if (collectionId && collectionId !== loadedCollectionId) {
    loadedCollectionId = collectionId;
    loadGraph();
  }

  onDestroy(() => {
    disposeRenderer();
    graph = null;
  });
</script>

<svelte:head>
  <title>{$t('graph.title')}</title>
</svelte:head>

<section class="card fade-up">
  <div class="graph-preview-header">
    <div>
      <h2>{$t('graph.title')}</h2>
      <p class="lead">{$t('graph.lead')}</p>
    </div>
    <div class="preview-actions">
      <button class="btn btn--ghost" type="button" on:click={loadGraph}>
        {$t('graph.previewLoad')}
      </button>
      <button class="btn btn--ghost" type="button" on:click={exportImage} disabled={!visibleNodes}>
        {$t('graph.exportImage')}
      </button>
      <button class="btn btn--primary" type="button" on:click={downloadGraphml}>
        {$t('graph.download')}
      </button>
    </div>
  </div>
</section>

{#if showFallbackState}
  <section class="card">
    <article class="result-card">
      <h3>{stateCardTitle()}</h3>
      <p class="result-text">{stateCardBody()}</p>
      <div class="table-actions">
        <a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
          {$t('overview.goToWorkspace')}
        </a>
      </div>
    </article>
  </section>
{:else}
  <section class="card">
    <div class="graph-preview-body">
      <div class="graph-controls">
        <div class="field">
          <label for="maxNodes">{$t('graph.maxNodesLabel')}</label>
          <input id="maxNodes" class="input" type="number" min="1" max="2000" bind:value={maxNodes} />
        </div>
        <div class="field">
          <label for="minWeight">{$t('graph.minWeightLabel')}</label>
          <input id="minWeight" class="input" type="number" min="0" step="0.1" bind:value={minWeight} />
        </div>
        <div class="field">
          <label for="communityId">{$t('graph.communityLabel')}</label>
          <input
            id="communityId"
            class="input"
            bind:value={communityId}
            placeholder={$t('graph.communityPlaceholder')}
          />
        </div>
        <div class="field">
          <label for="previewQuery">{$t('graph.searchLabel')}</label>
          <input
            id="previewQuery"
            class="input"
            bind:value={previewQuery}
            placeholder={$t('graph.searchPlaceholder')}
          />
        </div>
        <div class="table-actions">
          <button class="btn btn--ghost btn--small" type="button" on:click={resetFilters}>
            {$t('graph.resetFilters')}
          </button>
        </div>
        <div class="graph-stats">
          <span>{$t('graph.visibleNodes')}: {visibleNodes}</span>
          <span>{$t('graph.visibleEdges')}: {visibleEdges}</span>
          {#if graphMeta?.community}
            <span>{$t('graph.communityScope')}: {graphMeta.community}</span>
          {/if}
          {#if graphMeta?.truncated}
            <span>{$t('graph.truncated')}</span>
          {/if}
        </div>
        {#if status}
          <div class="status" role="status">{status}</div>
        {/if}
        {#if error}
          <div class="status status--error" role="alert">{error}</div>
        {/if}
      </div>

      <div class="graph-canvas" bind:this={graphContainer} aria-label={$t('graph.previewCanvasLabel')}>
        {#if loading}
          <div class="graph-empty">{$t('graph.previewLoading')}</div>
        {:else if !visibleNodes}
          <div class="graph-empty">{$t('graph.previewEmpty')}</div>
        {/if}
      </div>
    </div>
  </section>

  <section class="card">
    <h3>{$t('graph.detailsTitle')}</h3>
    <div class="graph-details">
      {#if selectedNode}
        <div class="graph-details__header">
          <span>{$t('graph.detailsNode')}</span>
          <button class="btn btn--ghost btn--small" type="button" on:click={clearSelection}>
            {$t('graph.detailsClear')}
          </button>
        </div>
        <div class="detail-primary">
          <span class="detail-name">{selectedNode.label}</span>
          {#if selectedNode.type}
            <span class="detail-tag">{selectedNode.type}</span>
          {/if}
        </div>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>{$t('graph.detailDegree')}</dt>
            <dd>{selectedNode.degree ?? '--'}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('graph.detailFrequency')}</dt>
            <dd>{selectedNode.frequency ?? '--'}</dd>
          </div>
          <div class="detail-row detail-row--wide">
            <dt>{$t('graph.detailDescription')}</dt>
            <dd>{selectedNode.description || '--'}</dd>
          </div>
        </dl>
      {:else if selectedEdge}
        <div class="graph-details__header">
          <span>{$t('graph.detailsEdge')}</span>
          <button class="btn btn--ghost btn--small" type="button" on:click={clearSelection}>
            {$t('graph.detailsClear')}
          </button>
        </div>
        <div class="detail-primary">
          <span class="detail-name">{selectedEdge.sourceLabel} -> {selectedEdge.targetLabel}</span>
        </div>
        <dl class="detail-list">
          <div class="detail-row">
            <dt>{$t('graph.detailWeight')}</dt>
            <dd>{selectedEdge.weight ?? '--'}</dd>
          </div>
          <div class="detail-row">
            <dt>{$t('graph.detailRank')}</dt>
            <dd>{selectedEdge.rank ?? '--'}</dd>
          </div>
          <div class="detail-row detail-row--wide">
            <dt>{$t('graph.detailDescription')}</dt>
            <dd>{selectedEdge.description || '--'}</dd>
          </div>
        </dl>
      {:else}
        <div class="graph-empty">{$t('graph.detailsEmpty')}</div>
      {/if}
    </div>
  </section>
{/if}
