import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
	requestJson: vi.fn()
}));

vi.mock('./api', () => ({
	requestJson
}));

const {
	fetchCollectionMaterials,
	fetchCollectionResearchView,
	fetchDocumentResearchView,
	fetchMaterialResearchView,
	formatShortIdentifier,
	formatEvidenceBackedValue,
	getResearchViewStateTone,
	hasObservedValue,
	normalizeCollectionAggregation,
	normalizeEvidenceBackedValue,
	normalizePaperAggregation
} = await import('./researchView');

describe('research view shared helpers', () => {
	beforeEach(() => {
		requestJson.mockReset();
	});

	it('fetches collection and document research views through same-origin api paths', async () => {
		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			state: 'ready',
			overview: {
				material_systems: ['316L stainless steel']
			}
		});

		const collection = await fetchCollectionResearchView('col_123');

		expect(requestJson).toHaveBeenCalledWith('/collections/col_123/research-view');
		expect(collection.state).toBe('ready');
		expect(collection.overview.material_systems).toEqual(['316L stainless steel']);

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			document_id: 'doc_1',
			state: 'partial',
			paper_title: 'SLM 316L'
		});

		const paper = await fetchDocumentResearchView('col_123', 'doc_1');

		expect(requestJson).toHaveBeenLastCalledWith(
			'/collections/col_123/documents/doc_1/research-view'
		);
		expect(paper.paper_title).toBe('SLM 316L');

		requestJson.mockResolvedValueOnce({
			items: [
				{
					material_id: 'mat_316l',
					canonical_name: '316L stainless steel',
					aliases: ['316L'],
					paper_count: 2,
					sample_count: 6,
					evidence_coverage: 0.8,
					state: 'ready'
				}
			]
		});

		const materials = await fetchCollectionMaterials('col_123');

		expect(requestJson).toHaveBeenLastCalledWith('/collections/col_123/materials');
		expect(materials[0]).toMatchObject({
			material_id: 'mat_316l',
			canonical_name: '316L stainless steel',
			sample_count: 6
		});

		requestJson.mockResolvedValueOnce({
			collection_id: 'col_123',
			material_id: 'mat_316l',
			canonical_name: '316L stainless steel',
			state: 'ready',
			papers: [{ document_id: 'doc_1', source_filename: 'paper-a.pdf', state: 'ready' }],
			sample_matrix: {
				rows: [{ row_id: 'row_1', sample_id: 'S1', sample_label: 'S1', material: '316L' }]
			}
		});

		const materialProfile = await fetchMaterialResearchView('col_123', 'mat_316l');

		expect(requestJson).toHaveBeenLastCalledWith(
			'/collections/col_123/materials/mat_316l/research-view'
		);
		expect(materialProfile.papers[0].document_id).toBe('doc_1');
		expect(materialProfile.papers[0].title).toBe('paper-a.pdf');
		expect(materialProfile.papers[0].source_filename).toBe('paper-a.pdf');
		expect(materialProfile.sample_matrix.rows[0].sample_id).toBe('S1');
	});

	it('shortens long internal identifiers for display fallback', () => {
		expect(formatShortIdentifier('8a5426cb65c3c0ae6ddc934a84fbbcd2b0cc4')).toBe(
			'8a5426cb65...2b0cc4'
		);
		expect(formatShortIdentifier('doc_1')).toBe('doc_1');
	});

	it('normalizes collection aggregation into coverage, groups, matrices, and warnings', () => {
		const collection = normalizeCollectionAggregation(
			{
				collection_id: 'col_123',
				state: 'partial',
				overview: {
					document_count: 1,
					sample_count: 2,
					measurement_count: 3,
					material_systems: ['316L stainless steel'],
					process_families: ['LPBF'],
					variable_axes: ['scanning speed'],
					measured_properties: ['density']
				},
				materials: [
					{
						material_id: 'mat_316l',
						canonical_name: '316L stainless steel',
						paper_count: 1,
						sample_count: 2
					}
				],
				paper_coverage: [
					{
						document_id: 'doc_1',
						title: 'Paper A',
						state: 'ready',
						sample_count: 2,
						measurement_count: 3,
						primary_warnings: ['condition missing']
					}
				],
				comparable_groups: [
					{
						group_id: 'grp_1',
						title: 'Scanning speed vs density',
						material_system: '316L stainless steel',
						process_family: 'LPBF',
						variable_axis: 'scanning speed',
						comparability_status: 'comparable',
						matrix: {
							matrix_id: 'mx_1',
							group_id: 'grp_1',
							columns: [{ value_key: 'density', role: 'property', label: 'Density' }],
							rows: [
								{
									row_id: 'row_1',
									document_id: 'doc_1',
									sample_id: 'S1',
									process_family: 'LPBF',
									property: 'density',
									result: {
										value: 99.1,
										unit: '%',
										status: 'observed',
										evidence_refs: [{ evidence_ref_id: 'ev_1', anchor_ids: ['anc_1'] }]
									}
								}
							]
						}
					}
				],
				warnings: [{ code: 'partial_binding', message: 'Some cells need review.' }]
			},
			'col_123'
		);

		expect(collection.overview.variable_axes).toEqual(['scanning speed']);
		expect(collection.materials[0].material_id).toBe('mat_316l');
		expect(collection.paper_coverage[0].primary_warnings[0].message).toBe('condition missing');
		expect(collection.comparable_groups[0].matrix.columns[0]).toMatchObject({
			key: 'density',
			kind: 'property'
		});
		expect(collection.comparable_groups[0].matrix.rows[0].result.value).toBe(99.1);
		expect(collection.comparable_groups[0].matrix.rows[0].process_context).toEqual({
			process: 'LPBF'
		});
		expect(collection.warnings[0]).toMatchObject({
			code: 'partial_binding',
			message: 'Some cells need review.'
		});
	});

	it('normalizes paper aggregation with sample matrix and condition series', () => {
		const paper = normalizePaperAggregation(
			{
				collection_id: 'col_123',
				document_id: 'doc_1',
				paper_title: 'Paper A',
				state: 'ready',
				overview: {
					material_systems: ['316L'],
					sample_variant_count: 1,
					main_process_variables: ['temperature'],
					measured_properties: ['yield strength'],
					condition_families: ['test temperature']
				},
				materials: [
					{
						material_id: 'mat_316l',
						canonical_name: '316L',
						sample_count: 1,
						measured_properties: ['yield strength']
					}
				],
				sample_matrix: {
					matrix_id: 'sample_mx',
					columns: [
						{ value_key: 'yield_strength', role: 'property', label: 'Yield strength', unit: 'MPa' }
					],
					rows: [
						{
							row_id: 'sample_1',
							sample_id: 'S1',
							sample_label: 'Sample A',
							material: '316L',
							process_context: { temperature: '70 C' },
							values: {
								yield_strength: {
									display_value: '940 MPa',
									status: 'observed',
									duplicate_count: 2
								}
							}
						}
					]
				},
				condition_series: [
					{
						series_id: 'series_1',
						sample_id: 'S1',
						property: 'yield strength',
						condition_axis: { axis_name: 'temperature' },
						points: [
							{
								condition_value: 50,
								condition_unit: 'C',
								result: { value: 940, unit: 'MPa' }
							}
						]
					}
				]
			},
			'col_123',
			'doc_1'
		);

		expect(paper.materials[0].canonical_name).toBe('316L');
		expect(paper.sample_matrix.rows[0].values.yield_strength.duplicate_count).toBe(2);
		expect(paper.sample_matrix.columns[0]).toMatchObject({
			key: 'yield_strength',
			kind: 'property'
		});
		expect(paper.condition_series[0].condition_axis).toBe('temperature');
		expect(paper.condition_series[0].points[0].result.unit).toBe('MPa');
	});

	it('formats and classifies evidence-backed values and states', () => {
		const observed = normalizeEvidenceBackedValue({
			value: 70,
			unit: 'J/mm3',
			status: 'normalized'
		});
		const missing = normalizeEvidenceBackedValue({ status: 'missing' });

		expect(formatEvidenceBackedValue(observed)).toBe('70 J/mm3');
		expect(hasObservedValue(observed)).toBe(true);
		expect(hasObservedValue(missing)).toBe(false);
		expect(getResearchViewStateTone('ready')).toBe('ready');
		expect(getResearchViewStateTone('partial')).toBe('processing');
		expect(getResearchViewStateTone('failed')).toBe('failed');
	});
});
