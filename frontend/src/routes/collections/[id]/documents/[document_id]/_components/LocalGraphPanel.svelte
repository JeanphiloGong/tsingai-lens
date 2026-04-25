<script lang="ts">
	import { t } from '../../../../../_shared/i18n';
	import type { WorkbenchGraphNode, WorkbenchLocalGraph } from '../../../../../_shared/documents';

	export let graph: WorkbenchLocalGraph | null = null;
	export let selectedNodeId = '';
	export let collapsed = false;
	export let onToggleCollapse: () => void = () => {};
	export let onSelectNode: (nodeId: string) => void = () => {};
	export let onSelectItem: (itemId: string) => void = () => {};
	export let onJumpToSource: (sourceSpanId: string) => void = () => {};

	$: selectedNode =
		graph?.nodes.find((node) => node.id === selectedNodeId) ??
		graph?.nodes.find((node) => node.position === 'center') ??
		null;

	function handleNodeClick(node: WorkbenchGraphNode) {
		onSelectNode(node.id);
		if (node.source_item_id) {
			onSelectItem(node.source_item_id);
		} else if (node.source_span_id) {
			onJumpToSource(node.source_span_id);
		}
	}
</script>

<aside class="graph-panel" aria-label={$t('workbench.graphLabel')}>
	<header class="graph-header">
		<h2>{$t('workbench.localGraph')}</h2>
		<button type="button" on:click={onToggleCollapse}>
			{collapsed ? $t('workbench.expand') : $t('workbench.collapse')}
		</button>
	</header>

	{#if !collapsed}
		<div class="legend" aria-label={$t('workbench.graphLegend')}>
			<span><i class="dot dot--task"></i>{$t('workbench.nodeTask')}</span>
			<span><i class="dot dot--method"></i>{$t('workbench.nodeMethod')}</span>
			<span><i class="dot dot--material"></i>{$t('workbench.nodeMaterial')}</span>
			<span><i class="dot dot--result"></i>{$t('workbench.nodeResult')}</span>
			<span><i class="dot dot--concept"></i>{$t('workbench.nodeConcept')}</span>
		</div>

		{#if graph}
			<div class="graph-canvas">
				<svg viewBox="0 0 420 470" aria-hidden="true">
					<defs>
						<marker
							id="graph-arrow"
							viewBox="0 0 10 10"
							refX="8"
							refY="5"
							markerWidth="5"
							markerHeight="5"
							orient="auto-start-reverse"
						>
							<path d="M 0 0 L 10 5 L 0 10 z"></path>
						</marker>
					</defs>
					<line x1="210" y1="235" x2="210" y2="75"></line>
					<line x1="210" y1="235" x2="84" y2="197"></line>
					<line x1="210" y1="235" x2="336" y2="197"></line>
					<line x1="210" y1="235" x2="126" y2="357"></line>
					<line x1="210" y1="235" x2="294" y2="357"></line>
					<text x="222" y="154">goal</text>
					<text x="126" y="196">uses</text>
					<text x="282" y="196">uses</text>
					<text x="136" y="296">produces</text>
					<text x="280" y="296">source</text>
				</svg>

				{#each graph.nodes as node}
					<button
						type="button"
						class={`graph-node graph-node--${node.position} graph-node--${node.type}`}
						class:active={selectedNode?.id === node.id}
						on:click={() => handleNodeClick(node)}
					>
						{node.label}
					</button>
				{/each}
			</div>

			<section class="node-detail" aria-label={$t('workbench.nodeDetailLabel')}>
				{#if selectedNode}
					<div class="node-detail-card">
						<div class="node-title-row">
							<h3>{selectedNode.label}</h3>
							<span>{selectedNode.type}</span>
						</div>
						<p>{selectedNode.detail}</p>
						<div class="related-row">
							<span>{$t('workbench.relatedEvidence')}</span>
							<strong>{graph.edges.length}</strong>
						</div>
						<div class="related-row">
							<span>{$t('workbench.relatedResults')}</span>
							<strong>{graph.nodes.filter((node) => node.type === 'result').length}</strong>
						</div>
						<button class="view-all" type="button">{$t('workbench.viewAllRelated')}</button>
					</div>
				{/if}
			</section>
		{:else}
			<div class="empty-state">
				<h3>{$t('workbench.graphEmptyTitle')}</h3>
				<p>{$t('workbench.graphEmptyBody')}</p>
			</div>
		{/if}
	{/if}
</aside>

<style>
	.graph-panel {
		display: flex;
		min-width: 300px;
		height: 100%;
		overflow: hidden;
		flex-direction: column;
		border: 1px solid #e2e8f0;
		border-radius: 16px;
		background: #ffffff;
	}

	.graph-header {
		display: flex;
		height: 56px;
		align-items: center;
		justify-content: space-between;
		padding: 0 18px;
		border-bottom: 1px solid #e2e8f0;
	}

	h2 {
		margin: 0;
		color: #0f172a;
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
	}

	.graph-header button,
	.view-all {
		height: 32px;
		padding: 0 10px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
		color: #334155;
		font-size: 13px;
		font-weight: 600;
		cursor: pointer;
	}

	.legend {
		display: flex;
		min-height: 44px;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		padding: 0 18px;
		color: #64748b;
		font-size: 12px;
	}

	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 999px;
	}

	.dot--task {
		background: #10b981;
	}

	.dot--method {
		background: #06b6d4;
	}

	.dot--material {
		background: #8b5cf6;
	}

	.dot--result {
		background: #f59e0b;
	}

	.dot--concept {
		background: #14b8a6;
	}

	.graph-canvas {
		position: relative;
		height: 470px;
		padding: 16px;
		background: linear-gradient(#ffffff, #fbfdff);
	}

	svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}

	line {
		stroke: #94a3b8;
		stroke-width: 1.4;
		marker-end: url(#graph-arrow);
	}

	path {
		fill: #94a3b8;
	}

	text {
		fill: #64748b;
		font-size: 12px;
	}

	.graph-node {
		position: absolute;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 96px;
		height: 96px;
		padding: 8px;
		border: 1px solid;
		border-radius: 999px;
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
		font-size: 13px;
		font-weight: 600;
		line-height: 1.35;
		text-align: center;
		cursor: pointer;
		transform: translate(-50%, -50%);
	}

	.graph-node.graph-node--center {
		left: 50%;
		top: 50%;
		width: 118px;
		height: 118px;
		border-color: #93c5fd;
		background: #eff6ff;
		color: #2563eb;
		font-size: 16px;
		font-weight: 800;
	}

	.graph-node--top {
		left: 50%;
		top: 16%;
	}

	.graph-node--left {
		left: 20%;
		top: 42%;
	}

	.graph-node--right {
		left: 80%;
		top: 42%;
	}

	.graph-node--bottom-left {
		left: 30%;
		top: 76%;
	}

	.graph-node--bottom-right {
		left: 70%;
		top: 76%;
	}

	.graph-node--task {
		border-color: #a7f3d0;
		background: #ecfdf5;
		color: #059669;
	}

	.graph-node--method {
		border-color: #a5f3fc;
		background: #ecfeff;
		color: #0891b2;
	}

	.graph-node--material {
		border-color: #ddd6fe;
		background: #f5f3ff;
		color: #7c3aed;
	}

	.graph-node--result {
		border-color: #fed7aa;
		background: #fff7ed;
		color: #ea580c;
	}

	.graph-node--scenario,
	.graph-node--concept {
		border-color: #99f6e4;
		background: #f0fdfa;
		color: #0d9488;
	}

	.graph-node.active {
		box-shadow:
			0 8px 20px rgba(15, 23, 42, 0.06),
			0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.node-detail {
		flex: 1;
		overflow-y: auto;
		border-top: 1px solid #e2e8f0;
		padding: 18px;
	}

	.node-detail-card,
	.empty-state {
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		background: #ffffff;
		padding: 16px;
	}

	.node-title-row {
		display: flex;
		margin-bottom: 8px;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

	.node-title-row h3 {
		margin: 0;
		color: #0f172a;
		font-size: 18px;
		font-weight: 700;
	}

	.node-title-row span {
		display: inline-flex;
		height: 22px;
		align-items: center;
		padding: 0 8px;
		border-radius: 999px;
		background: #dcfce7;
		color: #15803d;
		font-size: 11px;
		font-weight: 700;
	}

	p {
		margin: 0 0 12px;
		color: #475569;
		font-size: 14px;
		line-height: 22px;
	}

	.related-row {
		display: flex;
		height: 44px;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid #e2e8f0;
		color: #334155;
		font-size: 13px;
	}

	.view-all {
		width: 100%;
		height: 38px;
		margin-top: 12px;
		border-radius: 10px;
		font-size: 14px;
	}

	.empty-state {
		margin: 18px;
		border-style: dashed;
		background: #f8fafc;
		text-align: center;
	}
</style>
