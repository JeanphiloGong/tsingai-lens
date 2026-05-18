import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	buildCollectionOverviewGraph,
	buildCollectionGraphmlUrl,
	buildMaterialCentricGraph,
	buildCytoscapeElements,
	buildCytoscapeStyles,
	buildGraphMeta,
	buildKeyChainGraph,
	buildNodeTypeCounts,
	filterGraphElements,
	formatGraphLabel,
	getLinkedComparisons,
	getNodeTypeStyle,
	parseGraphNodeId,
	runGraphLayout,
	type GraphResponse
} from './graph';
import type { ComparisonRow } from './comparisons';
import type { Core } from 'cytoscape';

describe('graph shared helpers', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

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
		expect(parseGraphNodeId('obj:objective-1')).toEqual({
			kind: 'objective',
			resourceId: 'objective-1'
		});
		expect(parseGraphNodeId('chain:chain-1')).toEqual({
			kind: 'logic_chain',
			resourceId: 'chain-1'
		});
		expect(parseGraphNodeId('material_system:hash')).toEqual({
			kind: 'material_system',
			resourceId: 'hash'
		});
		expect(parseGraphNodeId('step:chain-1:measurement_results')).toEqual({
			kind: 'measurement_results',
			resourceId: 'chain-1:measurement_results'
		});
		expect(parseGraphNodeId('proc:hash-1')).toEqual({
			kind: 'process',
			resourceId: 'hash-1'
		});
		expect(parseGraphNodeId('sample:hash-2')).toEqual({
			kind: 'sample',
			resourceId: 'hash-2'
		});
		expect(parseGraphNodeId('weird')).toEqual({
			kind: 'unknown',
			resourceId: ''
		});
	});

	it('recognizes semantic chain graph nodes from the backend contract', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'obj:o1', label: 'Objective', type: 'objective', degree: 1 },
				{
					id: 'step:c1:measurement_results',
					label: 'Measurement results',
					type: 'measurement_results',
					role: 'measurement_results',
					summary: '1 measurement row supports this chain step.',
					metrics: { row_count: 1, paper_count: 1, evidence_count: 1 },
					detail_rows: [
						{
							evidence_unit_id: 'oeu-1',
							property: 'yield strength',
							value: '365.6 MPa'
						}
					],
					degree: 1
				}
			],
			edges: []
		};

		expect(buildGraphMeta(graph)).toMatchObject({
			nodeCount: 2,
			nodeTypeCount: 2
		});
		expect(buildNodeTypeCounts(graph)).toMatchObject({
			objective: 1,
			measurement_results: 1,
			unknown: 0
		});
		expect(getNodeTypeStyle('measurement_results').icon).toBe('measurement-results');
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

	it('positions objective semantic chain nodes from canonical ids', () => {
		const elements = buildCytoscapeElements({
			nodes: [
				{ id: 'obj:o1', label: 'Objective A', type: 'objective', degree: 1 },
				{
					id: 'material_system:steel',
					label: '316L stainless steel',
					type: 'material_system',
					degree: 2
				},
				{
					id: 'step:chain-a:measurement_results',
					label: 'Measurement results',
					type: 'measurement_results',
					degree: 1
				},
				{
					id: 'step:chain-a:material_scope',
					label: 'Material scope',
					type: 'material_scope',
					degree: 1
				}
			],
			edges: [
				{
					id: 'e1',
					source: 'obj:o1',
					target: 'material_system:steel',
					weight: 1,
					edge_description: 'objective_to_material_system',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e2',
					source: 'material_system:steel',
					target: 'step:chain-a:material_scope',
					weight: 1,
					edge_description: 'material_system_to_material_scope',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e3',
					source: 'step:chain-a:material_scope',
					target: 'step:chain-a:measurement_results',
					weight: 1,
					edge_description: 'semantic_chain_step_to_step',
					source_role: 'material_scope',
					target_role: 'measurement_results'
				}
			]
		});

		const byId = new Map(elements.map((element) => [String(element.data?.id), element]));

		expect(byId.get('obj:o1')?.position).toEqual({ x: 0, y: 0 });
		expect(byId.get('material_system:steel')?.position).toEqual({ x: 270, y: 0 });
		expect(byId.get('step:chain-a:material_scope')?.position).toEqual({ x: 478, y: 0 });
		expect(byId.get('step:chain-a:measurement_results')?.position).toEqual({ x: 1310, y: 0 });
		expect(byId.get('step:chain-a:measurement_results')?.data?.detailRows).toEqual([]);
		expect(byId.get('step:chain-a:measurement_results')?.data?.targetRole).toBeUndefined();
	});

	it('centers shared material nodes across objective chains', () => {
		const elements = buildCytoscapeElements({
			nodes: [
				{ id: 'obj:o1', label: 'Objective A', type: 'objective', degree: 1 },
				{ id: 'obj:o2', label: 'Objective B', type: 'objective', degree: 1 },
				{
					id: 'material_system:steel',
					label: '316L stainless steel',
					type: 'material_system',
					degree: 4
				},
				{
					id: 'step:chain-a:material_scope',
					label: 'Material scope',
					type: 'material_scope',
					degree: 1
				},
				{
					id: 'step:chain-b:material_scope',
					label: 'Material scope',
					type: 'material_scope',
					degree: 1
				}
			],
			edges: [
				{
					id: 'e1',
					source: 'obj:o1',
					target: 'material_system:steel',
					edge_description: 'objective_to_material_system',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e2',
					source: 'obj:o2',
					target: 'material_system:steel',
					edge_description: 'objective_to_material_system',
					logic_chain_id: 'chain-b'
				},
				{
					id: 'e3',
					source: 'material_system:steel',
					target: 'step:chain-a:material_scope',
					edge_description: 'material_system_to_material_scope',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e4',
					source: 'material_system:steel',
					target: 'step:chain-b:material_scope',
					edge_description: 'material_system_to_material_scope',
					logic_chain_id: 'chain-b'
				}
			]
		});

		const byId = new Map(elements.map((element) => [String(element.data?.id), element]));

		expect(byId.get('obj:o1')?.position).toEqual({ x: 0, y: 0 });
		expect(byId.get('obj:o2')?.position).toEqual({ x: 0, y: 128 });
		expect(byId.get('material_system:steel')?.position).toEqual({ x: 270, y: 64 });
		expect(byId.get('step:chain-a:material_scope')?.position).toEqual({ x: 478, y: 0 });
		expect(byId.get('step:chain-b:material_scope')?.position).toEqual({ x: 478, y: 128 });
	});

	it('does not emit unsupported Cytoscape shadow style properties', () => {
		const styleKeys = buildCytoscapeStyles().flatMap((entry) =>
			Object.keys((entry as { style?: Record<string, unknown> }).style ?? {})
		);

		expect(styleKeys).not.toEqual(expect.arrayContaining(['shadow-blur', 'shadow-color']));
		expect(styleKeys).toEqual(expect.arrayContaining(['underlay-color', 'underlay-opacity']));
	});

	it('finishes graph layout if the renderer omits layoutstop', async () => {
		vi.useFakeTimers();
		const run = vi.fn();
		const cy = {
			nodes: () => ({ length: 2 }),
			layout: () => ({
				on: vi.fn(),
				run
			})
		} as unknown as Core;

		const layout = runGraphLayout(cy, 'grid');
		await vi.advanceTimersByTimeAsync(1600);

		await expect(layout).resolves.toBeUndefined();
		expect(run).toHaveBeenCalledOnce();
	});

	it('uses a simple layout for tiny default graphs', async () => {
		vi.useFakeTimers();
		let layoutName = '';
		const cy = {
			nodes: () => ({ length: 2 }),
			layout: (options: { name?: string }) => {
				layoutName = options.name ?? '';
				return {
					on: vi.fn(),
					run: vi.fn()
				};
			}
		} as unknown as Core;

		const layout = runGraphLayout(cy, 'fcose');
		await vi.advanceTimersByTimeAsync(1600);

		await expect(layout).resolves.toBeUndefined();
		expect(layoutName).toBe('grid');
	});

	it('uses a simple layout for large complete graphs', async () => {
		vi.useFakeTimers();
		let layoutName = '';
		const cy = {
			nodes: () => ({ length: 1200 }),
			layout: (options: { name?: string }) => {
				layoutName = options.name ?? '';
				return {
					on: vi.fn(),
					run: vi.fn()
				};
			}
		} as unknown as Core;

		const layout = runGraphLayout(cy, 'fcose');
		await vi.advanceTimersByTimeAsync(1600);

		await expect(layout).resolves.toBeUndefined();
		expect(layoutName).toBe('grid');
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

	it('projects objective-first evidence units into aggregate overview maps', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'obj:o1', label: 'LPBF 316L mechanical objective', type: 'objective', degree: 1 },
				{ id: 'chain:c1', label: 'Density to strength chain', type: 'logic_chain', degree: 1 },
				{ id: 'doc:d1', label: 'Paper A', type: 'document', degree: 1 },
				{ id: 'evi:m1', label: 'Yield strength | 365.6 MPa', type: 'measurement', degree: 5 },
				{ id: 'mat:steel', label: '316L stainless steel', type: 'material', degree: 1 },
				{ id: 'prop:yield', label: 'yield strength', type: 'property', degree: 1 },
				{ id: 'proc:scan', label: 'scan speed: 900 mm/s', type: 'process', degree: 1 },
				{ id: 'sample:case15', label: 'Case: 15', type: 'sample', degree: 1 }
			],
			edges: [
				{
					id: 'e1',
					source: 'obj:o1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'objective_to_evidence'
				},
				{
					id: 'e2',
					source: 'chain:c1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'logic_chain_to_evidence'
				},
				{
					id: 'e3',
					source: 'doc:d1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'document_to_evidence'
				},
				{
					id: 'e4',
					source: 'evi:m1',
					target: 'mat:steel',
					weight: 1,
					edge_description: 'evidence_to_material'
				},
				{
					id: 'e5',
					source: 'evi:m1',
					target: 'prop:yield',
					weight: 1,
					edge_description: 'evidence_to_property'
				},
				{
					id: 'e6',
					source: 'evi:m1',
					target: 'proc:scan',
					weight: 1,
					edge_description: 'evidence_to_process'
				},
				{
					id: 'e7',
					source: 'evi:m1',
					target: 'sample:case15',
					weight: 1,
					edge_description: 'evidence_to_sample'
				}
			]
		};

		const overview = buildCollectionOverviewGraph(graph);

		expect(overview.nodes.map((node) => node.type)).toEqual([
			'objective',
			'logic_chain',
			'document',
			'material',
			'property',
			'process',
			'sample'
		]);
		expect(overview.edges).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					source: 'obj:o1',
					target: 'mat:steel',
					edge_description: 'overview_objective_material'
				}),
				expect.objectContaining({
					source: 'chain:c1',
					target: 'mat:steel',
					edge_description: 'overview_logic_chain_material'
				}),
				expect.objectContaining({
					source: 'doc:d1',
					target: 'mat:steel',
					edge_description: 'overview_document_material'
				}),
				expect.objectContaining({
					source: 'mat:steel',
					target: 'prop:yield',
					edge_description: 'overview_material_property'
				}),
				expect.objectContaining({
					source: 'mat:steel',
					target: 'proc:scan',
					edge_description: 'overview_material_context'
				}),
				expect.objectContaining({
					source: 'mat:steel',
					target: 'sample:case15',
					edge_description: 'overview_material_context'
				})
			])
		);
	});

	it('projects objective-first graphs into key chain maps', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'obj:o1', label: 'LPBF 316L mechanical objective', type: 'objective', degree: 3 },
				{ id: 'chain:c1', label: 'Density to strength chain', type: 'logic_chain', degree: 2 },
				{ id: 'doc:d1', label: 'Paper A', type: 'document', degree: 2 },
				{ id: 'evi:m1', label: 'Yield strength | 365.6 MPa', type: 'measurement', degree: 8 },
				{ id: 'mat:steel', label: '316L stainless steel', type: 'material', degree: 3 },
				{ id: 'prop:yield', label: 'yield strength', type: 'property', degree: 2 },
				{ id: 'proc:scan', label: 'scan speed: 900 mm/s', type: 'process', degree: 2 },
				{ id: 'sample:case15', label: 'Case: 15', type: 'sample', degree: 1 },
				{ id: 'tc:tensile', label: 'method: tensile test', type: 'test_condition', degree: 1 },
				{ id: 'evi:orphan', label: 'Unscoped note', type: 'measurement', degree: 1 },
				{ id: 'x:unknown', label: 'Unresolved', type: 'unknown', degree: 1 }
			],
			edges: [
				{
					id: 'e1',
					source: 'obj:o1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'objective_to_evidence'
				},
				{
					id: 'e2',
					source: 'chain:c1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'logic_chain_to_evidence'
				},
				{
					id: 'e3',
					source: 'doc:d1',
					target: 'evi:m1',
					weight: 1,
					edge_description: 'document_to_evidence'
				},
				{
					id: 'e4',
					source: 'evi:m1',
					target: 'mat:steel',
					weight: 1,
					edge_description: 'evidence_to_material'
				},
				{
					id: 'e5',
					source: 'evi:m1',
					target: 'prop:yield',
					weight: 1,
					edge_description: 'evidence_to_property'
				},
				{
					id: 'e6',
					source: 'evi:m1',
					target: 'proc:scan',
					weight: 1,
					edge_description: 'evidence_to_process'
				},
				{
					id: 'e7',
					source: 'evi:m1',
					target: 'sample:case15',
					weight: 1,
					edge_description: 'evidence_to_sample'
				},
				{
					id: 'e8',
					source: 'evi:m1',
					target: 'tc:tensile',
					weight: 1,
					edge_description: 'evidence_to_test_condition'
				},
				{
					id: 'e9',
					source: 'evi:orphan',
					target: 'x:unknown',
					weight: 1,
					edge_description: 'related_to'
				}
			]
		};

		const keyChain = buildKeyChainGraph(graph, { maxNodes: 8 });

		expect(keyChain.truncated).toBe(true);
		expect(keyChain.nodes.map((node) => node.id)).toEqual([
			'obj:o1',
			'chain:c1',
			'doc:d1',
			'evi:m1',
			'mat:steel',
			'prop:yield',
			'proc:scan',
			'sample:case15'
		]);
		expect(keyChain.edges).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ source: 'obj:o1', target: 'evi:m1' }),
				expect.objectContaining({ source: 'chain:c1', target: 'evi:m1' }),
				expect.objectContaining({ source: 'doc:d1', target: 'evi:m1' }),
				expect.objectContaining({ source: 'evi:m1', target: 'mat:steel' })
			])
		);
		expect(keyChain.nodes.some((node) => node.id === 'evi:orphan')).toBe(false);
		expect(keyChain.nodes.some((node) => node.type === 'unknown')).toBe(false);
	});

	it('projects shared material hubs into material-centric maps', () => {
		const graph: GraphResponse = {
			collection_id: 'col_1',
			truncated: false,
			nodes: [
				{ id: 'obj:o1', label: 'Objective A', type: 'objective', degree: 1 },
				{ id: 'obj:o2', label: 'Objective B', type: 'objective', degree: 1 },
				{ id: 'material_system:steel', label: '316L stainless steel', type: 'material_system', degree: 4 },
				{ id: 'step:chain-a:material_scope', label: 'Material scope', type: 'material_scope', logic_chain_id: 'chain-a', degree: 1 },
				{ id: 'step:chain-a:measurement_results', label: 'Measurement results', type: 'measurement_results', logic_chain_id: 'chain-a', degree: 1 },
				{ id: 'step:chain-b:material_scope', label: 'Material scope', type: 'material_scope', logic_chain_id: 'chain-b', degree: 1 },
				{ id: 'step:chain-b:mechanism_interpretation', label: 'Mechanism', type: 'mechanism_interpretation', logic_chain_id: 'chain-b', degree: 1 },
				{ id: 'doc:d1', label: 'Paper A', type: 'document', degree: 1 }
			],
			edges: [
				{
					id: 'e1',
					source: 'obj:o1',
					target: 'material_system:steel',
					edge_description: 'objective_to_material_system',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e2',
					source: 'obj:o2',
					target: 'material_system:steel',
					edge_description: 'objective_to_material_system',
					logic_chain_id: 'chain-b'
				},
				{
					id: 'e3',
					source: 'material_system:steel',
					target: 'step:chain-a:material_scope',
					edge_description: 'material_system_to_material_scope',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e4',
					source: 'material_system:steel',
					target: 'step:chain-b:material_scope',
					edge_description: 'material_system_to_material_scope',
					logic_chain_id: 'chain-b'
				},
				{
					id: 'e5',
					source: 'step:chain-a:material_scope',
					target: 'step:chain-a:measurement_results',
					edge_description: 'semantic_chain_step_to_step',
					logic_chain_id: 'chain-a'
				},
				{
					id: 'e6',
					source: 'step:chain-b:material_scope',
					target: 'step:chain-b:mechanism_interpretation',
					edge_description: 'semantic_chain_step_to_step',
					logic_chain_id: 'chain-b'
				}
			]
		};

		const materialGraph = buildMaterialCentricGraph(graph, { maxNodes: 20 });

		expect(materialGraph.nodes.map((node) => node.id)).toEqual([
			'obj:o1',
			'obj:o2',
			'material_system:steel',
			'step:chain-a:material_scope',
			'step:chain-a:measurement_results',
			'step:chain-b:material_scope',
			'step:chain-b:mechanism_interpretation'
		]);
		expect(materialGraph.edges).toHaveLength(6);
		expect(materialGraph.nodes.some((node) => node.type === 'document')).toBe(false);
		expect(materialGraph.nodes.find((node) => node.id === 'material_system:steel')?.position).toEqual({
			x: 0,
			y: 0
		});
		expect(materialGraph.nodes.find((node) => node.id === 'obj:o1')?.position?.x).toBeLessThan(0);
		expect(
			materialGraph.nodes.find((node) => node.id === 'step:chain-a:measurement_results')?.position
				?.x
		).toBeGreaterThan(0);
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

	it('matches formatted aggregate condition labels to comparison rows', () => {
		const rawCondition =
			'details: tensile specimens were tested to failure; method_family: tensile_mechanics; test_method: tensile testing';
		const row = {
			row_id: 'row_2',
			result_id: 'res_2',
			source_document_id: 'doc_1',
			display: {
				material_system_normalized: '',
				process_normalized: '',
				property_normalized: '',
				result_summary: '',
				test_condition_normalized: rawCondition,
				baseline_normalized: ''
			}
		} as ComparisonRow;

		const linked = getLinkedComparisons(
			{
				kind: 'node',
				node: {
					id: 'tc:tensile',
					label: formatGraphLabel(rawCondition),
					type: 'test_condition'
				}
			},
			[row]
		);

		expect(linked.map((item) => item.row_id)).toEqual(['row_2']);
	});
});
