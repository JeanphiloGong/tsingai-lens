import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DocumentProfile } from './documents';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({
	requestJson
}));

const {
	buildDocumentTypeStats,
	buildProfileConclusion,
	buildProtocolSuitabilityStats,
	fetchDocumentComparisonSemantics,
	formatConfidence,
	getDocumentNextActions,
	getDocumentTypeBadge,
	getSuitabilityBadge
} = await import('./documents');

function profile(overrides: Partial<DocumentProfile>): DocumentProfile {
	return {
		document_id: 'doc_1',
		collection_id: 'col_123',
		title: null,
		source_filename: null,
		doc_type: 'uncertain',
		protocol_extractable: 'uncertain',
		protocol_extractability_signals: [],
		parsing_warnings: [],
		confidence: null,
		...overrides
	};
}

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

	it('builds document profile stats with percentages and dominant rows', () => {
		const profiles = [
			profile({ document_id: 'review', doc_type: 'review', protocol_extractable: 'no' }),
			profile({ document_id: 'exp', doc_type: 'experimental', protocol_extractable: 'yes' }),
			profile({ document_id: 'method', doc_type: 'method', protocol_extractable: 'partial' }),
			profile({
				document_id: 'computational',
				doc_type: 'computational',
				protocol_extractable: 'uncertain'
			})
		];

		const documentTypes = buildDocumentTypeStats(profiles);
		const suitability = buildProtocolSuitabilityStats(profiles);

		expect(documentTypes.find((item) => item.key === 'review')).toMatchObject({
			count: 1,
			percent: 25,
			dominant: true
		});
		expect(documentTypes.find((item) => item.key === 'mixed')).toMatchObject({
			count: 0,
			percent: 0,
			dominant: false
		});
		expect(suitability.find((item) => item.key === 'no')).toMatchObject({
			count: 1,
			percent: 25,
			tone: 'warning'
		});
	});

	it('chooses profile conclusions from collection-level usability signals', () => {
		const reviewProfiles = [profile({ doc_type: 'review', protocol_extractable: 'no' })];
		const reviewStats = {
			total: reviewProfiles.length,
			documentTypeStats: buildDocumentTypeStats(reviewProfiles),
			protocolSuitabilityStats: buildProtocolSuitabilityStats(reviewProfiles)
		};

		expect(buildProfileConclusion(reviewStats)).toMatchObject({
			tone: 'warning',
			messageKey: 'profiles.conclusion.reviewRisk',
			actionKeys: ['upload_more', 'view_evidence']
		});

		const readyProfiles = [profile({ doc_type: 'experimental', protocol_extractable: 'yes' })];
		const readyStats = {
			total: readyProfiles.length,
			documentTypeStats: buildDocumentTypeStats(readyProfiles),
			protocolSuitabilityStats: buildProtocolSuitabilityStats(readyProfiles)
		};

		expect(buildProfileConclusion(readyStats)).toMatchObject({
			tone: 'ready',
			messageKey: 'profiles.conclusion.ready',
			actionKeys: ['view_evidence', 'open_comparison']
		});
	});

	it('returns document-specific next actions instead of always opening comparisons', () => {
		expect(
			getDocumentNextActions(profile({ doc_type: 'review', protocol_extractable: 'no' }))
		).toEqual(['view_document', 'view_evidence']);
		expect(
			getDocumentNextActions(profile({ doc_type: 'experimental', protocol_extractable: 'yes' }))
		).toEqual(['view_evidence', 'open_comparison']);
		expect(
			getDocumentNextActions(profile({ doc_type: 'uncertain', protocol_extractable: 'uncertain' }))
		).toEqual(['view_document', 'manual_mark']);
		expect(getDocumentNextActions(profile({ processing_status: 'processing' }))).toEqual([
			'view_progress',
			'refresh'
		]);
		expect(getDocumentNextActions(profile({ processing_status: 'failed' }))).toEqual([
			'view_error',
			'retry_processing'
		]);
	});

	it('formats confidence and badge metadata for the profile page', () => {
		expect(formatConfidence(0.904)).toBe('90%');
		expect(formatConfidence(86)).toBe('86%');
		expect(formatConfidence(null)).toBe('--');
		expect(getDocumentTypeBadge('method')).toMatchObject({
			labelKey: 'profiles.docTypes.method',
			tone: 'method'
		});
		expect(getSuitabilityBadge('no')).toMatchObject({
			labelKey: 'profiles.suitability.no',
			tone: 'warning'
		});
	});
});
