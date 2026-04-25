import { describe, expect, it } from 'vitest';
import {
	buildComparisonConclusion,
	buildComparisonQualitySummary,
	filterComparisonItems,
	formatComparisonConfidence,
	formatComparisonValue,
	getComparisonActions,
	getComparisonContext,
	getComparisonNote,
	getComparisonStatus,
	getComparisonStatusBadge,
	getMissingContextChips,
	getResultTypeBadge,
	sortComparisonItems,
	type ComparisonFilters,
	type ComparisonRow,
	type ComparisonValueLabels
} from './comparisons';

function row(overrides: Partial<ComparisonRow> = {}): ComparisonRow {
	return {
		row_id: 'cmp_1',
		result_id: 'cres_1',
		collection_id: 'col_1',
		source_document_id: 'doc_1',
		confidence: 0.9,
		display: {
			material_system_normalized: 'Ni-based alloy',
			process_normalized: 'LPBF process',
			variant_id: 'var_1',
			variant_label: 'Sample A',
			variable_axis: null,
			variable_value: null,
			property_normalized: 'thermoelectric_magnetic_effects',
			result_type: 'process',
			result_summary:
				'The dendrites at the tail of the melt pool perform the strongest thermoelectric magnetic effects.',
			value: null,
			unit: null,
			test_condition_normalized: 'test condition',
			baseline_reference: 'baseline',
			baseline_normalized: 'baseline'
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
		},
		...overrides
	};
}

const emptyFilters: ComparisonFilters = {
	search: '',
	status: '',
	material: '',
	resultType: '',
	testCondition: '',
	baseline: '',
	missingContext: ''
};

const zhValueLabels: ComparisonValueLabels = {
	material: '未指定材料体系',
	process: '未指定处理方式',
	baseline: '未指定基准对象',
	test_condition: '未指定测试条件',
	generic: '未指定'
};

describe('comparison shared helpers', () => {
	it('formats raw comparison values and extracts review context', () => {
		const item = row({
			display: {
				...row().display,
				material_system_normalized: 'unspecified material system',
				process_normalized: 'unspecified process',
				baseline_normalized: 'unspecified baseline',
				test_condition_normalized: 'unspecified test condition',
				property_normalized: 'volume_fraction_of_the_laves_phases'
			}
		});

		expect(formatComparisonValue('long_striped_laves_phases', 'result')).toBe(
			'Long striped Laves phases'
		);
		expect(getComparisonContext(item, zhValueLabels)).toMatchObject({
			materialSystem: '未指定材料体系',
			process: '未指定处理方式',
			baseline: '未指定基准对象',
			testCondition: '未指定测试条件'
		});
	});

	it('derives status, missing context chips, summary, conclusion, and actions', () => {
		const direct = row({ row_id: 'direct' });
		const limited = row({
			row_id: 'limited',
			confidence: 0.86,
			display: { ...row().display, value: 12, unit: null },
			assessment: { ...row().assessment, comparability_status: 'limited' }
		});
		const insufficient = row({
			row_id: 'insufficient',
			display: { ...row().display, baseline_normalized: 'unspecified baseline' },
			uncertainty: { ...row().uncertainty, unresolved_baseline_link: true }
		});
		const notComparable = row({
			row_id: 'not_comparable',
			assessment: { ...row().assessment, comparability_status: 'not_comparable' }
		});

		expect(getComparisonStatus(direct)).toBe('comparable');
		expect(getComparisonStatus(limited)).toBe('limited');
		expect(getComparisonStatus(insufficient)).toBe('insufficient');
		expect(getComparisonStatus(notComparable)).toBe('not_comparable');
		expect(getMissingContextChips(insufficient).map((chip) => chip.key)).toContain('baseline');
		expect(getComparisonStatusBadge('comparable')).toMatchObject({ tone: 'success' });
		expect(getResultTypeBadge('process')).toMatchObject({
			labelKey: 'comparison.resultTypes.process'
		});
		expect(formatComparisonConfidence(limited)).toBe('86%');
		expect(getComparisonActions(insufficient).map((action) => action.key)).toEqual([
			'view_evidence',
			'view_missing',
			'mark_issue'
		]);
		expect(getComparisonNote(insufficient)).toContain('baseline');

		const summary = buildComparisonQualitySummary([direct, limited, insufficient, notComparable]);
		expect(summary).toMatchObject([
			{ key: 'comparable', value: 1, percent: 25 },
			{ key: 'limited', value: 1, percent: 25 },
			{ key: 'not_comparable', value: 1, percent: 25 },
			{ key: 'insufficient', value: 1, percent: 25 }
		]);
		expect(buildComparisonConclusion(summary)).toMatchObject({
			tone: 'success',
			bodyKey: 'comparison.conclusion.directBody'
		});
	});

	it('filters and sorts comparison rows for the review page', () => {
		const direct = row({ row_id: 'direct', confidence: 0.91 });
		const insufficient = row({
			row_id: 'insufficient',
			confidence: 0.7,
			display: { ...row().display, baseline_normalized: 'unspecified baseline' },
			uncertainty: {
				...row().uncertainty,
				missing_critical_context: ['baseline_reference'],
				unresolved_baseline_link: true
			}
		});

		expect(
			filterComparisonItems([direct, insufficient], {
				...emptyFilters,
				search: 'dendrites',
				status: 'comparable',
				material: 'Ni-based alloy',
				resultType: 'process'
			}).map((item) => item.row_id)
		).toEqual(['direct']);
		expect(
			filterComparisonItems([direct, insufficient], {
				...emptyFilters,
				missingContext: 'baseline'
			}).map((item) => item.row_id)
		).toEqual(['insufficient']);
		expect(
			sortComparisonItems([insufficient, direct], 'confidence_desc').map((item) => item.row_id)
		).toEqual(['direct', 'insufficient']);
		expect(
			sortComparisonItems([insufficient, direct], 'completeness').map((item) => item.row_id)
		).toEqual(['direct', 'insufficient']);
	});
});
