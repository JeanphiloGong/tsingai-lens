import { describe, expect, it } from 'vitest';
import {
	buildCollectionOverviewGraph,
	buildCollectionGraphmlUrl,
	buildCytoscapeElements,
	buildGraphMeta,
	buildNodeTypeCounts,
	filterGraphElements,
	formatGraphLabel,
	getLinkedComparisons,
	getNodeTypeStyle,
	parseGraphNodeId,
	type GraphResponse
} from './graph';
import type { ComparisonRow } from './comparisons';

describe('graph shared helpers', () => {
	it('builds graphml urls with only lean graph query parameters', () => {
		const url = buildCollectionGraphmlUrl('col_123', { maxNodes: 50, minWeight: 0.75 });

		expect(url).toContain('/api/v1/collections/col_123/graphml?');
		expect(url).toContain('max_nodes=50');
		expect(url).toContain('min_weight=0.75');
		expect(url).not.toContain('community_id');
	});

	it('parses canonical node prefixes into resource references', () => {
		expect(parseGraphNodeId('doc:paper-1')).toEqual({
			kind: 'document',
			resourceId: 'paper-1'
		});
		expect(parseGraphNodeId('evi:ev-1')).toEqual({
			kind: 'evidence',
			resourceId: 'ev-1'
		});
		expect(parseGraphNodeId('cmp:row-1')).toEqual({
			kind: 'comparison',
			resourceId: 'row-1'
		});
		expect(parseGraphNodeId('mat:abc')).toEqual({
			kind: 'material',
			resourceId: 'abc'
		});
		expect(parseGraphNodeId('prop:def')).toEqual({
			kind: 'property',
			resourceId: 'def'
		});
		expect(parseGraphNodeId('tc:ghi')).toEqual({
			kind: 'test_condition',
			resourceId: 'ghi'
		});
		expect(parseGraphNodeId('base:jkl')).toEqual({
			kind: 'baseline',
			resourceId: 'jkl'
		});
		expect(parseGraphNodeId('weird')).toEqual({
			kind: 'unknown',
			resourceId: ''
		});
	});

	it('formats raw graph labels for display', () => {
		expect(formatGraphLabel('process_complexity_equipment_cost')).toBe(
			'Process Complexity Equipment Cost'
		);
		expect(formatGraphLabel(' total_crack_length ')).toBe('Total Crack Length');
		expect(formatGraphLabel('17-4 PH steel')).toBe('17-4 PH Steel');
	});

	it('builds graph exploration meta, type counts, and filtered visible elements', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'doc:d1', label: 'Paper A', type: 'document', degree: 1 },
				{ id: 'cmp:c1', label: 'Strength result', type: 'comparison', degree: 2 },
				{ id: 'mat:steel', label: 'steel', type: 'material', degree: 1 }
			],
			edges: [
				{
					id: 'e1',
					source: 'doc:d1',
					target: 'cmp:c1',
					weight: 0.8,
					edge_description: 'document_to_evidence'
				},
				{
					id: 'e2',
					source: 'cmp:c1',
					target: 'mat:steel',
					weight: 0.2,
					edge_description: 'comparison_to_material'
				}
			]
		};

		expect(buildGraphMeta(graph)).toEqual({
			nodeCount: 3,
			edgeCount: 2,
			nodeTypeCount: 3,
			truncated: false
		});
		expect(buildNodeTypeCounts(graph)).toMatchObject({
			document: 1,
			comparison: 1,
			material: 1
		});
		expect(getNodeTypeStyle('material').color).toBe('#8B5CF6');

		const filtered = filterGraphElements(graph, {
			minWeight: 0.5,
			visibleNodeTypes: { document: true, comparison: true, material: true }
		});
		expect(filtered.nodes).toHaveLength(3);
		expect(filtered.edges.map((edge) => edge.id)).toEqual(['e1']);
	});

	it('initializes unknown node counts for overview metrics', () => {
		expect(buildNodeTypeCounts(null).unknown).toBe(0);
		expect(
			buildNodeTypeCounts({
				nodes: [{ id: 'weird:1', label: 'Unresolved', type: 'unexpected', degree: 0 }]
			}).unknown
		).toBe(1);
	});

	it('uses short canvas labels while preserving full graph labels', () => {
		const [element] = buildCytoscapeElements({
			nodes: [
				{
					id: 'tc:tensile',
					type: 'test_condition',
					label:
						'details: tensile specimens were tested to failure with a long protocol description; instrument: INSTRON mechanical testing machine with a 50 N load cell; method: tensile testing; standard: ASTM E8M',
					degree: 2
				}
			],
			edges: []
		});

		expect(element.data?.label).toBe('Tensile Testing');
		expect(element.data?.fullLabel).toContain('Details: Tensile Specimens');
	});

	it('projects collection graphs into aggregate overview maps', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'doc:d1', label: 'Paper A', type: 'document', degree: 1 },
				{ id: 'evi:ev1', label: 'Evidence 1', type: 'evidence', degree: 2 },
				{ id: 'cmp:c1', label: 'Hardness result', type: 'comparison', degree: 4 },
				{ id: 'mat:steel', label: '316L stainless steel', type: 'material', degree: 1 },
				{ id: 'prop:hardness', label: 'hardness', type: 'property', degree: 1 },
				{ id: 'tc:lpbf', label: 'LPBF', type: 'test_condition', degree: 1 }
			],
			edges: [
				{
					id: 'e1',
					source: 'doc:d1',
					target: 'evi:ev1',
					weight: 0.9,
					edge_description: 'document_to_evidence'
				},
				{
					id: 'e2',
					source: 'evi:ev1',
					target: 'cmp:c1',
					weight: 0.9,
					edge_description: 'evidence_to_comparison'
				},
				{
					id: 'e3',
					source: 'cmp:c1',
					target: 'mat:steel',
					weight: 0.9,
					edge_description: 'comparison_to_material'
				},
				{
					id: 'e4',
					source: 'cmp:c1',
					target: 'prop:hardness',
					weight: 0.9,
					edge_description: 'comparison_to_property'
				},
				{
					id: 'e5',
					source: 'cmp:c1',
					target: 'tc:lpbf',
					weight: 0.9,
					edge_description: 'comparison_to_test_condition'
				}
			]
		};

		const overview = buildCollectionOverviewGraph(graph);

		expect(overview.nodes.map((node) => node.type)).toEqual([
			'document',
			'material',
			'property',
			'test_condition'
		]);
		expect(overview.edges.map((edge) => edge.edge_description).sort()).toEqual([
			'overview_document_material',
			'overview_material_context',
			'overview_material_property'
		]);
		expect(overview.edges).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ source: 'doc:d1', target: 'mat:steel' }),
				expect.objectContaining({ source: 'mat:steel', target: 'prop:hardness' }),
				expect.objectContaining({ source: 'mat:steel', target: 'tc:lpbf' })
			])
		);
	});

	it('links selected aggregate nodes to comparison rows', () => {
		const row = {
			row_id: 'row_1',
			result_id: 'res_1',
			collection_id: 'col_1',
			source_document_id: 'doc_1',
			confidence: 0.8,
			display: {
				material_system_normalized: 'steel',
				process_normalized: 'annealing',
				variant_id: null,
				variant_label: null,
				variable_axis: null,
				variable_value: null,
				property_normalized: 'yield strength',
				result_type: 'property',
				result_summary: 'Yield strength increased.',
				value: null,
				unit: null,
				test_condition_normalized: 'room temperature',
				baseline_reference: null,
				baseline_normalized: 'untreated'
			},
			evidence_bundle: {
				result_source_type: 'text',
				supporting_evidence_ids: ['ev_1'],
				supporting_anchor_ids: [],
				characterization_observation_ids: [],
				structure_feature_ids: []
			},
			assessment: {
				comparability_status: 'comparable',
				comparability_warnings: [],
				comparability_basis: [],
				requires_expert_review: false,
				assessment_epistemic_status: 'grounded'
			},
			uncertainty: {
				missing_critical_context: [],
				unresolved_fields: [],
				unresolved_baseline_link: false,
				unresolved_condition_link: false
			}
		} satisfies ComparisonRow;

		const linked = getLinkedComparisons(
			{ kind: 'node', node: { id: 'mat:steel', label: 'steel', type: 'material' } },
			[row]
		);

		expect(linked.map((item) => item.row_id)).toEqual(['row_1']);
	});
});
