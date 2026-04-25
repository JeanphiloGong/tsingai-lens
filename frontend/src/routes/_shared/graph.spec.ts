import { describe, expect, it } from 'vitest';
import {
	buildCollectionGraphmlUrl,
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
