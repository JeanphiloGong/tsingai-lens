import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({
	requestJson
}));

const { fetchDocumentComparisonSemantics } = await import('./documents');

describe('documents shared helpers', () => {
	beforeEach(() => {
		requestJson.mockReset();
	});

	it('normalizes grouped document comparison semantics into variant dossiers', async () => {
		requestJson.mockResolvedValue({
			collection_id: 'col_123',
			document_id: 'doc_1',
			total: 1,
			count: 1,
			items: [],
			variant_dossiers: [
				{
					variant_id: 'var_1',
					variant_label: 'optimized VED + HIP',
					material: {
						label: 'Ti-6Al-4V',
						composition: 'Ti-6Al-4V'
					},
					shared_process_state: {
						laser_power_w: 280
					},
					shared_missingness: ['surface state'],
					series: [
						{
							series_key: 'yield_strength:test_temperature_c',
							property_family: 'yield strength',
							test_family: 'tensile',
							varying_axis: {
								axis_name: 'test_temperature_c',
								axis_unit: 'C'
							},
							chains: [
								{
									result_id: 'cres_1',
									source_result_id: 'mr_1',
									measurement: {
										property: 'yield strength',
										value: 940,
										unit: 'MPa',
										result_type: 'scalar',
										summary: 'YS = 940 MPa'
									},
									test_condition: {
										test_method: 'tensile',
										test_temperature_c: 25,
										'strain_rate_s-1': 0.001
									},
									baseline: {
										label: 'optimized VED without HIP',
										reference: 'S2',
										baseline_type: 'same_document',
										resolved: true
									},
									assessment: {
										comparability_status: 'limited',
										warnings: ['orientation missing'],
										basis: ['same paper'],
										missing_context: ['sample orientation'],
										requires_expert_review: true,
										assessment_epistemic_status: 'grounded'
									},
									value_provenance: {
										value_origin: 'reported',
										source_value_text: '940',
										source_unit_text: 'MPa'
									},
									evidence: {
										evidence_ids: ['ev_1'],
										direct_anchor_ids: ['anc_1'],
										contextual_anchor_ids: [],
										structure_feature_ids: ['sf_1'],
										characterization_observation_ids: [],
										traceability_status: 'direct'
									}
								}
							]
						}
					]
				}
			]
		});

		const response = await fetchDocumentComparisonSemantics('col_123', 'doc_1', {
			includeGroupedProjections: true
		});

		expect(requestJson).toHaveBeenCalledWith(
			'/collections/col_123/documents/doc_1/comparison-semantics?include_grouped_projections=true',
			{ method: 'GET' }
		);
		expect(response.variant_dossiers[0].variant_label).toBe('optimized VED + HIP');
		expect(response.variant_dossiers[0].shared_process_state.laser_power_w).toBe(280);
		expect(response.variant_dossiers[0].series[0].chains[0].test_condition.strain_rate_s_1).toBe(
			0.001
		);
		expect(response.variant_dossiers[0].series[0].chains[0].assessment.comparability_status).toBe(
			'limited'
		);
	});
});
