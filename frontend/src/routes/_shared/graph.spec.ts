import { describe, expect, it } from 'vitest';
import {
	buildCollectionGraphmlUrl,
	buildCytoscapeElements,
	buildGraphMeta,
	buildMaterialCentricGraph,
	buildNodeTypeCounts,
	filterGraphElements,
	formatGraphLabel,
	getNodeDescription,
	parseGraphNodeId,
	runGraphLayout,
	type GraphResponse
} from './graph';

const graph: GraphResponse = {
	collection_id: 'col-1',
	nodes: [
		{ id: 'doc:paper-1', label: 'Paper one', type: 'document', degree: 1 },
		{ id: 'evi:evidence-1', label: 'Density reached 99.6%', type: 'evidence', degree: 2 },
		{ id: 'cmp:comparison-1', label: '316L / density', type: 'comparison', degree: 4 },
		{ id: 'mat:316l', label: '316L stainless steel', type: 'material', degree: 1 },
		{ id: 'prop:density', label: 'relative_density', type: 'property', degree: 1 },
		{ id: 'obj:objective-1', label: 'How does VED affect density?', type: 'objective', degree: 0 }
	],
	edges: [
		{
			id: 'edge-1',
			source: 'doc:paper-1',
			target: 'evi:evidence-1',
			weight: 1,
			edge_description: 'document_to_evidence'
		},
		{
			id: 'edge-2',
			source: 'evi:evidence-1',
			target: 'cmp:comparison-1',
			weight: 1,
			edge_description: 'evidence_to_comparison'
		},
		{
			id: 'edge-3',
			source: 'cmp:comparison-1',
			target: 'mat:316l',
			weight: 1,
			edge_description: 'comparison_to_material'
		},
		{
			id: 'edge-4',
			source: 'cmp:comparison-1',
			target: 'prop:density',
			weight: 1,
			edge_description: 'comparison_to_property'
		}
	],
	truncated: false
};

describe('graph shared helpers', () => {
	it('builds GraphML URLs with bounded graph query parameters', () => {
		expect(buildCollectionGraphmlUrl('col one', { maxNodes: 80, minWeight: 0.25 })).toContain(
			'/collections/col%20one/graphml?max_nodes=80&min_weight=0.25'
		);
	});

	it('parses only node kinds emitted by the backend graph', () => {
		expect(parseGraphNodeId('obj:objective-1')).toEqual({
			kind: 'objective',
			resourceId: 'objective-1'
		});
		expect(parseGraphNodeId('evi:evidence-1')).toEqual({
			kind: 'evidence',
			resourceId: 'evidence-1'
		});
		expect(parseGraphNodeId('chain:old')).toEqual({ kind: 'unknown', resourceId: 'old' });
	});

	it('formats labels and reports graph counts', () => {
		expect(formatGraphLabel('relative_density')).toBe('Relative Density');
		expect(buildGraphMeta(graph)).toEqual({
			nodeCount: 6,
			edgeCount: 4,
			nodeTypeCount: 6,
			truncated: false
		});
		expect(buildNodeTypeCounts(graph)).toMatchObject({
			objective: 1,
			document: 1,
			evidence: 1,
			comparison: 1,
			material: 1,
			property: 1,
			unknown: 0
		});
	});

	it('filters nodes and drops edges whose endpoints are hidden', () => {
		const filtered = filterGraphElements(graph, {
			search: 'density',
			visibleNodeTypes: { objective: false },
			maxNodes: 20,
			minWeight: 0
		});
		expect(filtered.nodes.map((node) => node.id)).toEqual([
			'evi:evidence-1',
			'cmp:comparison-1',
			'prop:density'
		]);
		expect(filtered.edges.map((edge) => edge.id)).toEqual(['edge-2', 'edge-4']);
	});

	it('builds a material-centered connected subgraph from current node types', () => {
		const projected = buildMaterialCentricGraph(graph, { maxNodes: 5 });
		expect(projected.nodes.map((node) => node.id)).toEqual([
			'doc:paper-1',
			'evi:evidence-1',
			'cmp:comparison-1',
			'mat:316l',
			'prop:density'
		]);
		expect(projected.nodes.some((node) => node.type === 'objective')).toBe(false);
		expect(projected.truncated).toBe(true);
	});

	it('projects canonical graph records without removed analysis identities', () => {
		const elements = buildCytoscapeElements(graph);
		const evidence = elements.find(
			(element) => element.group === 'nodes' && element.data?.id === 'evi:evidence-1'
		);
		const edge = elements.find(
			(element) => element.group === 'edges' && element.data?.id === 'edge-2'
		);
		expect(evidence?.data).toMatchObject({
			entityType: 'evidence',
			fullLabel: 'Density Reached 99.6%'
		});
		expect(evidence?.data).not.toHaveProperty('logicChainId');
		expect(edge?.data).toMatchObject({
			edgeDescription: 'evidence_to_comparison',
			label: 'supports comparison'
		});
	});

	it('describes objective and evidence nodes by their current meaning', () => {
		expect(getNodeDescription(graph.nodes[0])).toContain('source paper');
		expect(getNodeDescription(graph.nodes[1])).toContain('source evidence');
	});

	it('uses a breadth-first renderer for the layered layout', async () => {
		let layoutOptions: Record<string, unknown> | null = null;
		let onStop: (() => void) | null = null;
		const renderer = {
			nodes: () => ({ length: 3 }),
			layout: (options: Record<string, unknown>) => {
				layoutOptions = options;
				return {
					on: (_event: string, callback: () => void) => {
						onStop = callback;
					},
					run: () => onStop?.()
				};
			}
		};
		await runGraphLayout(renderer as never, 'layered');
		expect(layoutOptions).toMatchObject({ name: 'breadthfirst', directed: true });
	});
});
