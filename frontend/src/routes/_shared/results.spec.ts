import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({
	requestJson
}));

const { fetchCollectionResults, fetchCollectionResult } = await import('./results');

describe('results shared helpers', () => {
	beforeEach(() => {
		requestJson.mockReset();
	});

	it('normalizes collection results list payloads into product-facing result items', async () => {
		requestJson.mockResolvedValue({
			collection_id: 'col_123',
			total: 1,
			count: 1,
			items: [
				{
					result_id: 'cres_1',
					document_id: 'doc_1',
					document_title: 'Paper A',
					material_label: 'oxide cathode',
					property: 'conductivity',
					value: 12,
					unit: 'mS/cm',
					baseline: 'as-prepared',
					test_condition: 'EIS',
					process: '700 C',
					traceability_status: 'direct',
					comparability_status: 'comparable',
					variant_label: 'Sample A',
					summary: '12 mS/cm'
				}
			]
		});

		const response = await fetchCollectionResults('col_123');

		expect(response.collection_id).toBe('col_123');
		expect(response.items[0]).toMatchObject({
			result_id: 'cres_1',
			document_id: 'doc_1',
			document_title: 'Paper A',
			material_label: 'oxide cathode',
			property: 'conductivity',
			value: 12,
			unit: 'mS/cm',
			comparability_status: 'comparable'
		});
	});

	it('normalizes result detail payloads into the product-facing drilldown model', async () => {
		requestJson.mockResolvedValue({
			result_id: 'cres_1',
			document: {
				document_id: 'doc_1',
				title: 'Paper A',
				source_filename: 'paper-a.pdf'
			},
			material: {
				label: 'oxide cathode',
				variant_id: 'var_1',
				variant_label: 'Sample A'
			},
			measurement: {
				property: 'conductivity',
				value: 12,
				unit: 'mS/cm',
				result_type: 'scalar',
				summary: '12 mS/cm'
			},
			context: {
				process: '700 C',
				baseline: 'as-prepared',
				test_condition: 'EIS',
				axis_name: null,
				axis_value: null,
				axis_unit: null
			},
			assessment: {
				comparability_status: 'comparable',
				warnings: [],
				missing_context: [],
				requires_expert_review: false
			},
			evidence: [
				{
					evidence_id: 'ev_1',
					traceability_status: 'direct',
					source_type: 'text',
					anchor_ids: ['anchor_1']
				}
			],
			actions: {
				open_document: '/collections/col_123/documents/doc_1',
				open_comparisons: '/collections/col_123/comparisons?property_normalized=conductivity'
			}
		});

		const detail = await fetchCollectionResult('col_123', 'cres_1');

		expect(detail.result_id).toBe('cres_1');
		expect(detail.document.title).toBe('Paper A');
		expect(detail.measurement.property).toBe('conductivity');
		expect(detail.assessment.comparability_status).toBe('comparable');
		expect(detail.actions.open_document).toContain('/collections/col_123/documents/doc_1');
	});
});
