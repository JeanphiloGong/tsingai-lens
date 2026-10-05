import type { ExperimentAnalysisProjection, ExperimentComparison, ExperimentMeasurement, ExperimentSource, PaperExperimentRevision } from './researchView';

export type ExperimentResultRow = {
	key: string;
	selectionIds: string[];
	experiment: PaperExperimentRevision;
	outcome: string;
	comparison: ExperimentComparison | null;
	before: ExperimentMeasurement[];
	after: ExperimentMeasurement[];
	sources: ExperimentSource[];
	missing: string[];
};

// Resolve only the exact revision and keys frozen by the published analysis.
export function experimentResultRows(projection: ExperimentAnalysisProjection, selectionIds?: string[]) {
	const rows = new Map<string, ExperimentResultRow>();
	for (const selection of projection.selections) {
		if (selectionIds && !selectionIds.includes(selection.selection_id)) continue;
		const experiment = projection.experiments.find(item => item.experiment_id === selection.experiment_id && item.experiment_version === selection.experiment_version);
		if (!experiment) continue;
		const selected = experiment.measurements.filter(item => selection.measurement_keys.includes(item.measurement_key));
		const used = new Set<string>();
		function add(suffix: string, comparison: ExperimentComparison | null, before: ExperimentMeasurement[], after: ExperimentMeasurement[]) {
			const key = `${experiment!.experiment_id}:${experiment!.experiment_version}:${suffix}`;
			const existing = rows.get(key);
			if (existing) { existing.selectionIds.push(selection.selection_id); existing.missing = [...new Set([...existing.missing, ...selection.missing_context])]; return; }
			const sources = new Map<string, ExperimentSource>();
			for (const source of [...(comparison?.source_refs ?? []), ...before.flatMap(item => item.source_refs), ...after.flatMap(item => item.source_refs)]) {
				sources.set(`${source.document_id}:${source.source_ref}:${source.quote}`, source);
			}
			rows.set(key, { key, selectionIds: [selection.selection_id], experiment: experiment!, outcome: selection.outcome, comparison, before, after, sources: [...sources.values()], missing: [...selection.missing_context] });
		}
		for (const comparison of experiment.comparisons.filter(item => selection.comparison_keys.includes(item.comparison_key))) {
			const before = selected.filter(item => comparison.baseline_measurement_keys.includes(item.measurement_key));
			const after = selected.filter(item => comparison.target_measurement_keys.includes(item.measurement_key));
			[...before, ...after].forEach(item => used.add(item.measurement_key));
			add(`comparison:${comparison.comparison_key}`, comparison, before, after);
		}
		for (const measurement of selected.filter(item => !used.has(item.measurement_key))) add(`measurement:${measurement.measurement_key}`, null, [], [measurement]);
	}
	return [...rows.values()];
}

export function experimentValue(value: unknown): string {
	if (value === null || value === undefined || value === '') return '';
	if (typeof value === 'object') return JSON.stringify(value);
	return String(value);
}

function numeric(value: unknown) {
	if (typeof value === 'number') return Number.isFinite(value) ? value : null;
	if (typeof value !== 'string' || !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
	const number = Number(value);
	return Number.isFinite(number) ? number : null;
}

export function numericExperimentPair(row: ExperimentResultRow) {
	const comparison = row.comparison;
	if (!comparison || comparison.status !== 'ready' || !['direct', 'derived'].includes(comparison.relation_status)) return null;
	if (comparison.baseline_measurement_keys.length !== 1 || comparison.target_measurement_keys.length !== 1 || row.before.length !== 1 || row.after.length !== 1) return null;
	const [before, after] = [row.before[0], row.after[0]];
	if (before.variant_key !== comparison.baseline_variant_key || after.variant_key !== comparison.target_variant_key) return null;
	if (!before.test_key || before.test_key !== after.test_key || before.outcome !== after.outcome) return null;
	if (!before.unit || before.unit !== after.unit || before.result_kind !== 'measured' || after.result_kind !== 'measured') return null;
	if (![before, after].every(item => ['direct', 'derived'].includes(item.binding_status))) return null;
	const start = numeric(before.value), end = numeric(after.value);
	if (start === null || end === null || !Number.isFinite(end - start)) return null;
	return { before: start, after: end, unit: before.unit, delta: end - start };
}
