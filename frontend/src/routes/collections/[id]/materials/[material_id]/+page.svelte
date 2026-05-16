<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import { errorMessage, isHttpStatusError } from '../../../../_shared/api';
	import { language, t } from '../../../../_shared/i18n';
	import {
		buildMaterialReviewMarkdownUrl,
		buildMaterialReviewPdfUrl,
		createMaterialReviewReport,
		fetchMaterialReviewReport,
		type MaterialReviewReport
	} from '../../../../_shared/materialReviewReport';
	import {
		fetchMaterialResearchView,
		formatEvidenceBackedValue,
		formatShortIdentifier,
		type EvidenceBackedValue,
		type EvidenceReference,
		type MaterialPaperCoverage,
		type MaterialProfile,
		type PropertySummary,
		type SampleMatrixColumn,
		type SampleMatrixRow
	} from '../../../../_shared/researchView';

	type Translate = (key: string, vars?: Record<string, string | number>) => string;

	type MaterialDossierTab = 'structured' | 'narrative';

	type PropertyColumn = {
		key: string;
		label: string;
		shortLabel: string;
		unit: string | null;
	};

	type ProcessSummary = {
		controlledKeys: string[];
		controlledLabels: string[];
		changedKeys: string[];
		changedLabels: string[];
		changedVariable: string;
	};

	type EvidenceDrawerDetail = {
		title: string;
		sample: string;
		source: string;
		location: string;
		anchor: string;
		confidence: string;
		excerpt: string;
		href: string | null;
	};

	type EvidenceLocatorRow = {
		key: string;
		code: string;
		claim: string;
		type: string;
		location: string;
		confidence: string;
		href: string | null;
		detail: EvidenceDrawerDetail;
	};

	type ComparisonRow = {
		key: string;
		variable: string;
		property: string;
		observation: string;
		conclusion: string;
		firstLabel: string;
		secondLabel: string;
		firstValue: number | null;
		secondValue: number | null;
		maxValue: number;
	};

	type ComparisonPair = {
		first: SampleMatrixRow;
		second: SampleMatrixRow;
		variableLabel: string;
	};

	type SupportedValue = {
		key: string;
		row: SampleMatrixRow;
		column: PropertyColumn;
		value: EvidenceBackedValue;
		sample: string;
		property: string;
		displayValue: string;
		evidenceCode: string;
	};

	type KeyFinding = {
		key: string;
		title: string;
		body: string;
		type: string;
		confidence: string;
		supportedValues: SupportedValue[];
		evidenceCodes: string[];
	};

	type MaterialGraphNodeKind = 'material' | 'process' | 'sample' | 'property' | 'finding';

	type MaterialGraphNode = {
		id: string;
		kind: MaterialGraphNodeKind;
		label: string;
		meta: string;
		detail: string;
		evidenceCodes: string[];
	};

	type MaterialGraph = Record<MaterialGraphNodeKind, MaterialGraphNode[]>;

	type MaterialGraphColumn = {
		kind: MaterialGraphNodeKind;
		title: string;
		nodes: MaterialGraphNode[];
	};

	const PROCESS_UNITS: Record<string, string> = {
		laser_power_w: 'W',
		scan_speed_mm_s: 'mm/s',
		energy_density_j_mm3: 'J/mm3',
		layer_thickness_um: 'um',
		hatch_spacing_um: 'mm',
		preheat_temperature_c: 'C',
		oxygen_level_ppm: 'ppm',
		powder_size_distribution_um: 'um'
	};

	const PROCESS_BRIEF_KEYS = [
		'scan_speed_mm_s',
		'energy_density_j_mm3',
		'layer_thickness_um',
		'hatch_spacing_um',
		'laser_power_w'
	];

	const PREFERRED_PROPERTY_GROUPS = [
		{
			id: 'relative_density',
			labelKey: 'research.materialDossier.properties.relativeDensity',
			shortLabelKey: 'research.materialDossier.properties.relativeDensityShort',
			aliases: ['relative_density', 'relative density', 'density']
		},
		{
			id: 'hardness',
			labelKey: 'research.materialDossier.properties.hardness',
			shortLabelKey: 'research.materialDossier.properties.hardnessShort',
			aliases: ['hardness', 'hv', 'vickers']
		},
		{
			id: 'yield_strength',
			labelKey: 'research.materialDossier.properties.yieldStrength',
			shortLabelKey: 'research.materialDossier.properties.yieldStrengthShort',
			aliases: ['yield_strength', 'yield strength', 'yield']
		},
		{
			id: 'tensile_strength',
			labelKey: 'research.materialDossier.properties.tensileStrength',
			shortLabelKey: 'research.materialDossier.properties.tensileStrengthShort',
			aliases: ['tensile_strength', 'ultimate_tensile_strength', 'uts', 'tensile strength']
		},
		{
			id: 'elongation',
			labelKey: 'research.materialDossier.properties.elongation',
			shortLabelKey: 'research.materialDossier.properties.elongationShort',
			aliases: ['elongation', 'strain_to_failure', 'fracture_strain']
		}
	];

	let materialProfile: MaterialProfile | null = null;
	let selectedEvidence: EvidenceDrawerDetail | null = null;
	let pdfDrawerOpen = false;
	let pdfReport: MaterialReviewReport | null = null;
	let pdfReportLoading = false;
	let pdfReportError = '';
	let pdfReportPollTimer: number | null = null;
	let loading = false;
	let error = '';
	let loadedKey = '';
	let activeDossierTab: MaterialDossierTab = 'structured';
	let selectedGraphNodeId = '';

	$: collectionId = $page.params.id ?? '';
	$: materialId = $page.params.material_id ?? '';
	$: loadKey = `${collectionId}:${materialId}`;
	$: sampleRows = materialProfile?.sample_matrix.rows ?? [];
	$: sampleColumns = sampleMatrixColumns(materialProfile, sampleRows);
	$: propertySummaries = materialProfile?.measured_properties ?? [];
	$: propertyColumns = materialPropertyColumns(materialProfile, sampleRows, sampleColumns, $t);
	$: evidenceCodeMap = buildEvidenceCodeMap(sampleRows, propertyColumns, propertySummaries);
	$: evidenceRows = buildEvidenceRows(
		sampleRows,
		propertyColumns,
		evidenceCodeMap,
		collectionId,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId
	);
	$: processSummary = buildProcessSummary(sampleRows, $t);
	$: comparisonRows = buildComparisonRows(sampleRows, propertyColumns, processSummary, $t);
	$: trendRows = trendComparisonRows(comparisonRows);
	$: keyFindings = buildKeyFindings(
		sampleRows,
		propertyColumns,
		processSummary,
		evidenceCodeMap,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId
	);
	$: bestPropertyValues = buildBestPropertyValues(
		sampleRows,
		propertyColumns,
		evidenceCodeMap,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId
	);
	$: materialGraph = buildMaterialGraph(
		materialProfile,
		sampleRows,
		propertyColumns,
		processSummary,
		keyFindings,
		bestPropertyValues,
		evidenceCodeMap,
		$t
	);
	$: materialGraphColumns = materialGraphColumnList(materialGraph, $t);
	$: selectedMaterialGraphNode = findMaterialGraphNode(materialGraph, selectedGraphNodeId);
	$: materialTags = buildMaterialTags(materialProfile, $t);
	$: paperCount = materialProfile?.overview.paper_count || materialPapers().length;
	$: sampleCount = materialProfile?.overview.sample_count || sampleRows.length;
	$: evidenceCount =
		materialProfile?.overview.evidence_count ||
		materialProfile?.evidence_refs.length ||
		evidenceRows.length;
	$: measuredPropertyCount =
		materialProfile?.overview.measured_properties.length ||
		propertySummaries.length ||
		propertyColumns.length;
	$: if (collectionId && materialId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		resetPdfReportState();
		void loadMaterialPage();
	}
	$: pdfReportReady = pdfReport?.status === 'ready' || pdfReport?.status === 'ready_with_warnings';
	$: pdfReportGenerating = pdfReport?.status === 'generating';
	$: pdfReportBusy = pdfReportLoading || pdfReportGenerating;

	onDestroy(clearReportPoll);

	async function loadMaterialPage() {
		await loadMaterialProfile();
	}

	async function loadMaterialProfile() {
		loading = true;
		error = '';
		selectedEvidence = null;
		selectedGraphNodeId = '';
		pdfDrawerOpen = false;
		try {
			materialProfile = await fetchMaterialResearchView(collectionId, materialId);
		} catch (err) {
			materialProfile = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function loadPdfReportStatus() {
		if (!collectionId || !materialId) return;
		const requestedCollection = collectionId;
		const requestedMaterial = materialId;
		pdfReportLoading = true;
		pdfReportError = '';
		try {
			const report = await fetchMaterialReviewReport(requestedCollection, requestedMaterial);
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			pdfReport = report;
			updateReportPolling(report);
		} catch (err) {
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			clearReportPoll();
			if (isHttpStatusError(err, 404)) {
				pdfReport = null;
			} else {
				pdfReportError = errorMessage(err);
			}
		} finally {
			if (requestedCollection === collectionId && requestedMaterial === materialId) {
				pdfReportLoading = false;
			}
		}
	}

	function resetPdfReportState() {
		clearReportPoll();
		pdfReport = null;
		pdfReportLoading = false;
		pdfReportError = '';
	}

	function updateReportPolling(report: MaterialReviewReport | null) {
		if (report?.status === 'generating') {
			scheduleReportPoll();
		} else {
			clearReportPoll();
		}
	}

	function scheduleReportPoll() {
		if (!browser) return;
		clearReportPoll();
		pdfReportPollTimer = window.setTimeout(() => {
			pdfReportPollTimer = null;
			void loadPdfReportStatus();
		}, 2500);
	}

	function clearReportPoll() {
		if (browser && pdfReportPollTimer !== null) {
			window.clearTimeout(pdfReportPollTimer);
		}
		pdfReportPollTimer = null;
	}

	function materialPapers(): MaterialPaperCoverage[] {
		return materialProfile?.papers ?? [];
	}

	function sampleMatrixColumns(
		profile: MaterialProfile | null,
		rows: SampleMatrixRow[]
	): SampleMatrixColumn[] {
		if (profile?.sample_matrix.columns.length) {
			return profile.sample_matrix.columns;
		}

		const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row.values))));
		return keys.map((key) => ({
			column_id: key,
			key,
			label: key,
			kind: 'value',
			unit: null
		}));
	}

	function buildMaterialTags(profile: MaterialProfile | null, translate: Translate) {
		const tags: string[] = [];
		const name = profile?.canonical_name.toLowerCase() ?? '';
		if (name.includes('steel')) tags.push(translate('research.materialDossier.tags.alloySteel'));
		for (const process of profile?.overview.process_families ?? []) {
			if (!tags.includes(process)) tags.push(process);
		}
		if (!tags.length) tags.push(...(profile?.aliases.slice(0, 2) ?? []));
		return tags.slice(0, 2);
	}

	function normalizeForMatch(value: string) {
		return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
	}

	function labelFromColumn(key: string, columns: SampleMatrixColumn[], translate: Translate) {
		const column = columns.find((item) => item.key === key);
		const label = column?.label || key;
		const translated = translate(`research.materialDossier.properties.${normalizeForMatch(label)}`);
		return translated.startsWith('research.') ? label.replace(/_/g, ' ') : translated;
	}

	function propertySummaryColumnKey(property: string) {
		return `summary:${normalizeForMatch(property) || 'property'}`;
	}

	function propertyLabelFromName(name: string, translate: Translate) {
		const translated = translate(`research.materialDossier.properties.${normalizeForMatch(name)}`);
		return translated.startsWith('research.') ? name.replace(/_/g, ' ') : translated;
	}

	function propertyColumnFromName(
		key: string,
		name: string,
		unit: string | null,
		translate: Translate
	): PropertyColumn {
		const searchable = normalizeForMatch(name);
		const group = PREFERRED_PROPERTY_GROUPS.find((item) =>
			item.aliases.some((alias) => {
				const normalizedAlias = normalizeForMatch(alias);
				return searchable.includes(normalizedAlias) || normalizedAlias.includes(searchable);
			})
		);
		return {
			key,
			label: group ? translate(group.labelKey) : propertyLabelFromName(name, translate),
			shortLabel: group ? translate(group.shortLabelKey) : propertyLabelFromName(name, translate),
			unit
		};
	}

	function propertySummaryAlreadySelected(summary: PropertySummary, columns: PropertyColumn[]) {
		const summaryText = normalizeForMatch(summary.property);
		return columns.some((column) => {
			const columnText = normalizeForMatch(`${column.key} ${column.label} ${column.shortLabel}`);
			return (
				columnText.includes(summaryText) ||
				summaryText.includes(normalizeForMatch(column.key)) ||
				summaryText.includes(normalizeForMatch(column.shortLabel))
			);
		});
	}

	function materialPropertyColumns(
		profile: MaterialProfile | null,
		rows: SampleMatrixRow[],
		columns: SampleMatrixColumn[],
		translate: Translate
	): PropertyColumn[] {
		const valueKeys = Array.from(new Set(rows.flatMap((row) => Object.keys(row.values))));
		const used = new Set<string>();
		const selected: PropertyColumn[] = [];

		for (const group of PREFERRED_PROPERTY_GROUPS) {
			const key = valueKeys.find((candidate) => {
				if (used.has(candidate)) return false;
				const column = columns.find((item) => item.key === candidate);
				const searchable = normalizeForMatch(`${candidate} ${column?.label ?? ''}`);
				return group.aliases.some((alias) => searchable.includes(normalizeForMatch(alias)));
			});
			if (key) {
				used.add(key);
				selected.push({
					key,
					label: translate(group.labelKey),
					shortLabel: translate(group.shortLabelKey),
					unit: columns.find((item) => item.key === key)?.unit ?? null
				});
			}
		}

		for (const summary of profile?.measured_properties ?? []) {
			if (propertySummaryAlreadySelected(summary, selected)) continue;
			selected.push(
				propertyColumnFromName(
					propertySummaryColumnKey(summary.property),
					summary.property,
					summary.unit,
					translate
				)
			);
		}

		for (const key of valueKeys) {
			if (used.has(key)) continue;
			selected.push({
				key,
				label: labelFromColumn(key, columns, translate),
				shortLabel: labelFromColumn(key, columns, translate),
				unit: columns.find((item) => item.key === key)?.unit ?? null
			});
		}

		return selected.slice(0, 6);
	}

	function processLabel(key: string, translate: Translate) {
		const label = translate(`research.materialDossier.process.${key}`);
		return label.startsWith('research.') ? key.replace(/_/g, ' ') : label;
	}

	function processValue(row: SampleMatrixRow, key: string) {
		const value = row.process_context[key];
		if (value === null || value === undefined || value === '') return '--';
		return String(value);
	}

	function processValueWithUnit(row: SampleMatrixRow, key: string) {
		const value = processValue(row, key);
		if (value === '--') return value;
		if (/[a-zA-Z%]/.test(value)) return value;
		const unit = PROCESS_UNITS[key];
		return unit ? `${value} ${unit}` : value;
	}

	function sampleConditionLabel(row: SampleMatrixRow, translate: Translate) {
		const candidates = [
			row.variable_value ? String(row.variable_value) : '',
			row.process_context.scan_strategy,
			row.process_context.post_treatment_summary,
			row.process_context.build_orientation,
			row.process_context.energy_density_j_mm3
				? `${processLabel('energy_density_j_mm3', translate)} ${processValueWithUnit(
						row,
						'energy_density_j_mm3'
					)}`
				: ''
		].filter(Boolean);
		return candidates[0] || '';
	}

	function sampleDisplayLabel(row: SampleMatrixRow, translate: Translate, index?: number) {
		const rawLabel = row.sample_label || row.sample_id || '';
		const condition = sampleConditionLabel(row, translate);
		if (
			rawLabel &&
			condition &&
			!normalizeForMatch(rawLabel).includes(normalizeForMatch(condition))
		) {
			return `${rawLabel} · ${condition}`;
		}
		if (condition) return condition;
		if (rawLabel) return rawLabel;
		return translate('research.materialDossier.table.sampleFallback', {
			index: (index ?? 0) + 1
		});
	}

	function variableSummary(row: SampleMatrixRow, summary: ProcessSummary, translate: Translate) {
		if (summary.changedKeys.length) {
			return summary.changedKeys
				.map((key) => `${processLabel(key, translate)} = ${processValueWithUnit(row, key)}`)
				.join('; ');
		}
		if (row.variable_axis && row.variable_value !== null) {
			return `${row.variable_axis} = ${row.variable_value}`;
		}
		return sampleConditionLabel(row, translate) || '--';
	}

	function processBrief(row: SampleMatrixRow) {
		const parts = PROCESS_BRIEF_KEYS.map((key) => processValueWithUnit(row, key)).filter(
			(value) => value !== '--'
		);
		return parts.join(' · ') || '--';
	}

	function buildProcessSummary(rows: SampleMatrixRow[], translate: Translate): ProcessSummary {
		const keys = Array.from(
			new Set(rows.flatMap((row) => Object.keys(row.process_context)))
		).filter((key) => rows.some((row) => processValue(row, key) !== '--'));
		const controlledKeys: string[] = [];
		const changedKeys: string[] = [];
		const controlledLabels: string[] = [];
		const changedLabels: string[] = [];

		for (const key of keys) {
			const values = Array.from(
				new Set(rows.map((row) => processValue(row, key)).filter((value) => value !== '--'))
			);
			if (values.length === 1) {
				controlledKeys.push(key);
				controlledLabels.push(processLabel(key, translate));
			}
			if (values.length > 1) {
				changedKeys.push(key);
				changedLabels.push(processLabel(key, translate));
			}
		}

		return {
			controlledKeys,
			controlledLabels,
			changedKeys,
			changedLabels,
			changedVariable:
				changedLabels[0] || translate('research.materialDossier.comparison.defaultVariable')
		};
	}

	function numericValue(value: EvidenceBackedValue | undefined) {
		if (!value) return null;
		const raw = value.normalized_value ?? value.value;
		if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
		if (typeof raw === 'string' && raw.trim()) {
			const parsed = Number(raw);
			if (Number.isFinite(parsed)) return parsed;
		}
		const match = formatEvidenceBackedValue(value).match(/-?\d+(?:\.\d+)?/);
		return match ? Number(match[0]) : null;
	}

	function comparisonPair(
		rows: SampleMatrixRow[],
		summary: ProcessSummary,
		translate: Translate
	): ComparisonPair | null {
		if (rows.length < 2) return null;

		for (const key of summary.changedKeys) {
			for (let firstIndex = 0; firstIndex < rows.length - 1; firstIndex += 1) {
				for (let secondIndex = firstIndex + 1; secondIndex < rows.length; secondIndex += 1) {
					const firstValue = processValueWithUnit(rows[firstIndex], key);
					const secondValue = processValueWithUnit(rows[secondIndex], key);
					if (firstValue === '--' || secondValue === '--' || firstValue === secondValue) {
						continue;
					}
					return {
						first: rows[firstIndex],
						second: rows[secondIndex],
						variableLabel: processLabel(key, translate)
					};
				}
			}
		}

		if (!summary.changedKeys.length) {
			return {
				first: rows[0],
				second: rows[1],
				variableLabel: summary.changedVariable
			};
		}

		return null;
	}

	function buildComparisonRows(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		summary: ProcessSummary,
		translate: Translate
	): ComparisonRow[] {
		const pair = comparisonPair(rows, summary, translate);
		if (!pair) return [];
		const { first, second, variableLabel } = pair;
		const firstLabel = sampleDisplayLabel(first, translate, 0);
		const secondLabel = sampleDisplayLabel(second, translate, 1);

		return columns
			.map((column) => {
				const firstValue = numericValue(first.values[column.key]);
				const secondValue = numericValue(second.values[column.key]);
				const firstDisplay = first.values[column.key]
					? formatEvidenceBackedValue(first.values[column.key])
					: '--';
				const secondDisplay = second.values[column.key]
					? formatEvidenceBackedValue(second.values[column.key])
					: '--';
				const maxValue = Math.max(firstValue ?? 0, secondValue ?? 0, 1);
				const winner =
					firstValue !== null && secondValue !== null
						? firstValue === secondValue
							? translate('research.materialDossier.comparison.noClearWinner')
							: firstValue > secondValue
								? firstLabel
								: secondLabel
						: translate('research.materialDossier.comparison.needsEvidence');
				const conclusion =
					winner === translate('research.materialDossier.comparison.noClearWinner') ||
					winner === translate('research.materialDossier.comparison.needsEvidence')
						? winner
						: translate('research.materialDossier.comparison.higherConclusion', {
								sample: winner,
								property: column.shortLabel
							});

				return {
					key: column.key,
					variable: `${variableLabel}: ${firstLabel} vs ${secondLabel}`,
					property: column.label,
					observation: `${firstDisplay} -> ${secondDisplay}`,
					conclusion,
					firstLabel,
					secondLabel,
					firstValue,
					secondValue,
					maxValue
				};
			})
			.filter((row) => row.firstValue !== null || row.secondValue !== null);
	}

	function trendComparisonRows(rows: ComparisonRow[]) {
		const hardness = rows.find((row) => normalizeForMatch(row.property).includes('hardness'));
		return hardness ? [hardness] : rows.slice(0, 1);
	}

	function propertyRole(column: PropertyColumn) {
		const text = normalizeForMatch(`${column.key} ${column.label} ${column.shortLabel}`);
		if (text.includes('density')) return 'density';
		if (text.includes('elongation') || text.includes('strain')) return 'elongation';
		if (text.includes('yield') || text.includes('tensile') || text.includes('uts')) {
			return 'strength';
		}
		if (text.includes('hardness')) return 'hardness';
		return 'other';
	}

	function bestValueForColumn(rows: SampleMatrixRow[], column: PropertyColumn) {
		return rows
			.map((row) => ({
				row,
				column,
				value: row.values[column.key],
				numeric: numericValue(row.values[column.key])
			}))
			.filter((item) => item.value && item.numeric !== null)
			.sort((first, second) => (second.numeric ?? 0) - (first.numeric ?? 0))[0];
	}

	function buildBestPropertyValues(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		codeMap: Map<string, string>,
		translate: Translate,
		summaries: PropertySummary[],
		materialName: string
	) {
		const rowValues = columns
			.map((column) => bestValueForColumn(rows, column))
			.filter((item): item is NonNullable<ReturnType<typeof bestValueForColumn>> => Boolean(item))
			.map((item) => supportedValue(item.row, item.column, item.value, codeMap, translate))
			.slice(0, 6);
		return uniqueSupportedValues([
			...rowValues,
			...summarySupportedValues(summaries, columns, codeMap, materialName, translate)
		]).slice(0, 6);
	}

	function propertySummaryValue(summary: PropertySummary): EvidenceBackedValue {
		const value = summary.max_value ?? summary.min_value ?? summary.display_range;
		return {
			display_value: summary.display_range,
			value,
			unit: summary.unit,
			normalized_value: summary.max_value ?? summary.min_value,
			normalized_unit: summary.unit,
			status: summary.display_range && summary.display_range !== '--' ? 'observed' : 'missing',
			confidence: summary.evidence_refs[0]?.confidence ?? null,
			evidence_refs: summary.evidence_refs,
			duplicate_count: 0,
			conflict_status: null,
			warnings: summary.warnings
		};
	}

	function summarySampleRow(
		summary: PropertySummary,
		column: PropertyColumn,
		value: EvidenceBackedValue,
		materialName: string,
		translate: Translate
	): SampleMatrixRow {
		return {
			row_id: `summary:${summary.property}`,
			document_id: value.evidence_refs[0]?.document_id ?? null,
			sample_id: 'collection-summary',
			sample_label: translate('research.materialDossier.table.collectionSummary'),
			material: materialName,
			process_context: {},
			variable_axis: null,
			variable_value: null,
			values: { [column.key]: value },
			evidence_refs: value.evidence_refs,
			warnings: summary.warnings
		};
	}

	function summaryColumnForProperty(summary: PropertySummary, columns: PropertyColumn[]) {
		const key = propertySummaryColumnKey(summary.property);
		return (
			columns.find((column) => column.key === key) ??
			columns.find((column) => propertySummaryAlreadySelected(summary, [column]))
		);
	}

	function summarySupportedValues(
		summaries: PropertySummary[],
		columns: PropertyColumn[],
		codeMap: Map<string, string>,
		materialName: string,
		translate: Translate
	): SupportedValue[] {
		return summaries
			.map((summary) => {
				const column = summaryColumnForProperty(summary, columns);
				if (!column) return null;
				const value = propertySummaryValue(summary);
				if (!value.evidence_refs.length && !value.display_value) return null;
				return supportedValue(
					summarySampleRow(summary, column, value, materialName, translate),
					column,
					value,
					codeMap,
					translate
				);
			})
			.filter((item): item is SupportedValue => item !== null);
	}

	function supportedValue(
		row: SampleMatrixRow,
		column: PropertyColumn,
		value: EvidenceBackedValue,
		codeMap: Map<string, string>,
		translate: Translate
	): SupportedValue {
		const ref = value.evidence_refs[0];
		return {
			key: `${row.row_id}:${column.key}`,
			row,
			column,
			value,
			sample: sampleDisplayLabel(row, translate),
			property: column.shortLabel,
			displayValue: formatEvidenceBackedValue(value),
			evidenceCode: evidenceCode(ref, codeMap)
		};
	}

	function uniqueSupportedValues(values: SupportedValue[]) {
		const seen = new Set<string>();
		return values.filter((value) => {
			if (seen.has(value.key)) return false;
			seen.add(value.key);
			return true;
		});
	}

	function evidenceCodesForValues(values: SupportedValue[]) {
		return Array.from(
			new Set(values.map((value) => value.evidenceCode).filter((value) => value !== '--'))
		);
	}

	function supportedValueSummary(values: SupportedValue[]) {
		return values.map((value) => `${value.property} = ${value.displayValue}`).join(', ');
	}

	function findingConfidence(values: SupportedValue[], translate: Translate) {
		const confidences = values
			.map((item) => item.value.confidence ?? item.value.evidence_refs[0]?.confidence)
			.filter((item): item is number => item !== null && item !== undefined);
		if (!confidences.length) return '--';
		return confidenceLabel(Math.min(...confidences), translate);
	}

	function finding(
		key: string,
		title: string,
		body: string,
		typeKey: string,
		values: SupportedValue[],
		translate: Translate
	): KeyFinding {
		const supportedValues = uniqueSupportedValues(values);
		return {
			key,
			title,
			body,
			type: translate(typeKey),
			confidence: findingConfidence(supportedValues, translate),
			supportedValues,
			evidenceCodes: evidenceCodesForValues(supportedValues)
		};
	}

	function buildKeyFindings(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		summary: ProcessSummary,
		codeMap: Map<string, string>,
		translate: Translate,
		summaries: PropertySummary[],
		materialName: string
	): KeyFinding[] {
		const bestByColumn = columns
			.map((column) => bestValueForColumn(rows, column))
			.filter((item): item is NonNullable<ReturnType<typeof bestValueForColumn>> => Boolean(item));
		const valuesForBest = (items: typeof bestByColumn) =>
			items.map((item) => supportedValue(item.row, item.column, item.value, codeMap, translate));
		const findings: KeyFinding[] = [];
		const strengthBest = bestByColumn.filter((item) => propertyRole(item.column) === 'strength');
		const elongationBest = bestByColumn.filter(
			(item) => propertyRole(item.column) === 'elongation'
		);
		const densityBest = bestByColumn.find((item) => propertyRole(item.column) === 'density');

		if (strengthBest.length) {
			const values = valuesForBest(strengthBest);
			const firstSample = values[0].sample;
			const allSameSample = values.every((value) => value.sample === firstSample);
			findings.push(
				finding(
					'highest-strength',
					allSameSample
						? translate('research.materialDossier.findings.highestStrengthTitle', {
								sample: firstSample
							})
						: translate('research.materialDossier.findings.splitStrengthTitle'),
					translate('research.materialDossier.findings.supportedByValues', {
						values: supportedValueSummary(values),
						evidence: evidenceCodesForValues(values).join(', ') || '--'
					}),
					'research.materialDossier.findings.types.directObservation',
					values,
					translate
				)
			);
		}

		if (elongationBest.length) {
			const values = valuesForBest(elongationBest);
			findings.push(
				finding(
					'highest-elongation',
					translate('research.materialDossier.findings.highestElongationTitle', {
						sample: values[0].sample
					}),
					translate('research.materialDossier.findings.supportedByValues', {
						values: supportedValueSummary(values),
						evidence: evidenceCodesForValues(values).join(', ') || '--'
					}),
					'research.materialDossier.findings.types.directObservation',
					values,
					translate
				)
			);
		}

		if (densityBest && strengthBest.length) {
			const densityValue = supportedValue(
				densityBest.row,
				densityBest.column,
				densityBest.value,
				codeMap,
				translate
			);
			const strengthValues = valuesForBest(strengthBest);
			const strengthSample = strengthValues[0].sample;
			if (densityValue.sample !== strengthSample) {
				const values = [densityValue, ...strengthValues];
				findings.push(
					finding(
						'density-strength-mismatch',
						translate('research.materialDossier.findings.densityMismatchTitle'),
						translate('research.materialDossier.findings.densityMismatchBody', {
							densitySample: densityValue.sample,
							densityValue: densityValue.displayValue,
							strengthSample,
							strengthValues: supportedValueSummary(strengthValues),
							evidence: evidenceCodesForValues(values).join(', ') || '--'
						}),
						'research.materialDossier.findings.types.comparativeInference',
						values,
						translate
					)
				);
			}
		}

		if (strengthBest.length && elongationBest.length) {
			const strengthValues = valuesForBest(strengthBest);
			const elongationValues = valuesForBest(elongationBest);
			if (strengthValues[0].sample !== elongationValues[0].sample) {
				const values = [...strengthValues, ...elongationValues];
				findings.push(
					finding(
						'strength-ductility-tradeoff',
						translate('research.materialDossier.findings.tradeoffTitle'),
						translate('research.materialDossier.findings.tradeoffBody', {
							strengthSample: strengthValues[0].sample,
							elongationSample: elongationValues[0].sample,
							evidence: evidenceCodesForValues(values).join(', ') || '--'
						}),
						'research.materialDossier.findings.types.trendHypothesis',
						values,
						translate
					)
				);
			}
		}

		for (const item of bestByColumn) {
			if (findings.length >= 4) break;
			const value = supportedValue(item.row, item.column, item.value, codeMap, translate);
			const exists = findings.some((existing) =>
				existing.supportedValues.some((supported) => supported.key === value.key)
			);
			if (exists) continue;
			findings.push(
				finding(
					`highest-${item.column.key}`,
					translate('research.materialDossier.findings.highestPropertyTitle', {
						sample: value.sample,
						property: value.property
					}),
					translate('research.materialDossier.findings.supportedByValues', {
						values: `${value.property} = ${value.displayValue}`,
						evidence: value.evidenceCode
					}),
					'research.materialDossier.findings.types.directObservation',
					[value],
					translate
				)
			);
		}

		for (const value of summarySupportedValues(
			summaries,
			columns,
			codeMap,
			materialName,
			translate
		)) {
			if (findings.length >= 4) break;
			const exists = findings.some((existing) =>
				existing.supportedValues.some((supported) => supported.key === value.key)
			);
			if (exists) continue;
			findings.push(
				finding(
					`summary-${value.column.key}`,
					translate('research.materialDossier.findings.summaryPropertyTitle', {
						property: value.property
					}),
					translate('research.materialDossier.findings.summaryPropertyBody', {
						property: value.property,
						value: value.displayValue,
						evidence: value.evidenceCode
					}),
					'research.materialDossier.findings.types.directObservation',
					[value],
					translate
				)
			);
		}

		if (findings.length === 0 && summary.changedLabels.length) {
			return [
				{
					key: 'process-structure',
					title: translate('research.materialDossier.findings.processOnlyTitle'),
					body: translate('research.materialDossier.findings.processOnlyBody', {
						changed: summary.changedLabels.join(', ')
					}),
					type: translate('research.materialDossier.findings.types.structuralObservation'),
					confidence: '--',
					supportedValues: [],
					evidenceCodes: []
				}
			];
		}

		return findings.slice(0, 4);
	}

	function buildEvidenceCodeMap(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		summaries: PropertySummary[]
	) {
		const ids: string[] = [];
		for (const row of rows) {
			for (const column of columns) {
				for (const ref of row.values[column.key]?.evidence_refs ?? []) {
					if (ref.evidence_ref_id && !ids.includes(ref.evidence_ref_id))
						ids.push(ref.evidence_ref_id);
				}
			}
		}
		for (const summary of summaries) {
			for (const ref of summary.evidence_refs) {
				if (ref.evidence_ref_id && !ids.includes(ref.evidence_ref_id))
					ids.push(ref.evidence_ref_id);
			}
		}
		return new Map(ids.map((id, index) => [id, `E${String(index + 1).padStart(2, '0')}`]));
	}

	function evidenceCode(ref: EvidenceReference | undefined, codeMap: Map<string, string>) {
		if (!ref) return '--';
		return codeMap.get(ref.evidence_ref_id) ?? formatShortIdentifier(ref.evidence_ref_id);
	}

	function evidenceHref(ref: EvidenceReference | undefined, collection: string) {
		if (!ref?.document_id) return null;
		return resolve('/collections/[id]/documents/[document_id]', {
			id: collection,
			document_id: ref.document_id
		});
	}

	function paperTitle(ref: EvidenceReference | undefined) {
		if (!ref?.document_id) return '--';
		return (
			materialPapers().find((paper) => paper.document_id === ref.document_id)?.title ||
			formatShortIdentifier(ref.document_id)
		);
	}

	function sourceTypeLabel(ref: EvidenceReference | undefined, translate: Translate) {
		const sourceKind = ref?.source_kind?.toLowerCase() ?? '';
		if (sourceKind.includes('table'))
			return translate('research.materialDossier.evidence.tableData');
		if (sourceKind.includes('text') || sourceKind.includes('paragraph')) {
			return translate('research.materialDossier.evidence.textConclusion');
		}
		return translate('research.materialDossier.evidence.sourceEvidence');
	}

	function confidenceLabel(confidence: number | null | undefined, translate: Translate) {
		if (confidence === null || confidence === undefined) return '--';
		if (confidence >= 0.85) return translate('research.materialDossier.confidence.high');
		if (confidence >= 0.6) return translate('research.materialDossier.confidence.medium');
		return translate('research.materialDossier.confidence.low');
	}

	function confidenceScore(confidence: number | null | undefined) {
		if (confidence === null || confidence === undefined) return '--';
		return `${Math.max(1, Math.min(5, Math.round(confidence * 5)))}/5`;
	}

	function drawerDetailForValue(
		row: SampleMatrixRow,
		column: PropertyColumn,
		value: EvidenceBackedValue,
		codeMap: Map<string, string>,
		collection: string,
		translate: Translate
	): EvidenceDrawerDetail {
		const ref = value.evidence_refs[0];
		return {
			title: `${column.shortLabel} = ${formatEvidenceBackedValue(value)}`,
			sample: sampleDisplayLabel(row, translate),
			source: paperTitle(ref),
			location: ref?.locator || '--',
			anchor: evidenceCode(ref, codeMap),
			confidence: confidenceLabel(value.confidence ?? ref?.confidence, translate),
			excerpt: translate('research.materialDossier.evidence.contextUnavailable'),
			href: evidenceHref(ref, collection)
		};
	}

	function buildEvidenceRows(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		codeMap: Map<string, string>,
		collection: string,
		translate: Translate,
		summaries: PropertySummary[],
		materialName: string
	): EvidenceLocatorRow[] {
		const items: EvidenceLocatorRow[] = [];
		for (const row of rows) {
			for (const column of columns) {
				const value = row.values[column.key];
				if (!value?.evidence_refs.length) continue;
				const ref = value.evidence_refs[0];
				const detail = drawerDetailForValue(row, column, value, codeMap, collection, translate);
				items.push({
					key: `${row.row_id}:${column.key}:${ref.evidence_ref_id}`,
					code: evidenceCode(ref, codeMap),
					claim: `${sampleDisplayLabel(row, translate)} ${column.shortLabel} ${formatEvidenceBackedValue(value)}`,
					type: sourceTypeLabel(ref, translate),
					location: ref.locator || '--',
					confidence: confidenceScore(value.confidence ?? ref.confidence),
					href: detail.href,
					detail
				});
			}
		}
		for (const summary of summaries) {
			const column = summaryColumnForProperty(summary, columns);
			if (!column) continue;
			const value = propertySummaryValue(summary);
			const row = summarySampleRow(summary, column, value, materialName, translate);
			for (const ref of value.evidence_refs) {
				const detail = drawerDetailForValue(row, column, value, codeMap, collection, translate);
				items.push({
					key: `${row.row_id}:${column.key}:${ref.evidence_ref_id}`,
					code: evidenceCode(ref, codeMap),
					claim: `${materialName} ${column.shortLabel} ${formatEvidenceBackedValue(value)}`,
					type: sourceTypeLabel(ref, translate),
					location: ref.locator || '--',
					confidence: confidenceScore(value.confidence ?? ref.confidence),
					href: detail.href,
					detail
				});
			}
		}
		return items.slice(0, 8);
	}

	function rowEvidenceLabels(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		codeMap: Map<string, string>
	) {
		const labels: string[] = [];
		for (const column of columns) {
			for (const ref of row.values[column.key]?.evidence_refs ?? []) {
				const label = evidenceCode(ref, codeMap);
				if (!labels.includes(label)) labels.push(label);
			}
		}
		return labels.join(', ') || '--';
	}

	function openEvidenceCode(code: string) {
		const row = evidenceRows.find((item) => item.code === code);
		if (row) openEvidenceRow(row);
	}

	function uniqueList(values: string[]) {
		return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
	}

	function evidenceCodesFromRefs(refs: EvidenceReference[], codeMap: Map<string, string>) {
		return uniqueList(refs.map((ref) => evidenceCode(ref, codeMap)).filter((code) => code !== '--'));
	}

	function rowEvidenceCodes(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		codeMap: Map<string, string>
	) {
		return evidenceCodesFromRefs(
			columns.flatMap((column) => row.values[column.key]?.evidence_refs ?? []),
			codeMap
		);
	}

	function propertyEvidenceCodes(
		rows: SampleMatrixRow[],
		column: PropertyColumn,
		codeMap: Map<string, string>
	) {
		return evidenceCodesFromRefs(
			rows.flatMap((row) => row.values[column.key]?.evidence_refs ?? []),
			codeMap
		);
	}

	function graphNodeTypeLabel(kind: MaterialGraphNodeKind, translate: Translate) {
		return translate(`research.materialDossier.graph.types.${kind}`);
	}

	function selectGraphNode(node: MaterialGraphNode) {
		selectedGraphNodeId = node.id;
	}

	function materialGraphColumnList(
		graph: MaterialGraph,
		translate: Translate
	): MaterialGraphColumn[] {
		return [
			{
				kind: 'material',
				title: translate('research.materialDossier.graph.columns.material'),
				nodes: graph.material
			},
			{
				kind: 'process',
				title: translate('research.materialDossier.graph.columns.process'),
				nodes: graph.process
			},
			{
				kind: 'sample',
				title: translate('research.materialDossier.graph.columns.samples'),
				nodes: graph.sample
			},
			{
				kind: 'property',
				title: translate('research.materialDossier.graph.columns.properties'),
				nodes: graph.property
			},
			{
				kind: 'finding',
				title: translate('research.materialDossier.graph.columns.findings'),
				nodes: graph.finding
			}
		];
	}

	function findMaterialGraphNode(graph: MaterialGraph, nodeId: string) {
		if (!nodeId) return null;
		return Object.values(graph)
			.flat()
			.find((node) => node.id === nodeId) ?? null;
	}

	function buildMaterialGraph(
		profile: MaterialProfile | null,
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		summary: ProcessSummary,
		findings: KeyFinding[],
		bestValues: SupportedValue[],
		codeMap: Map<string, string>,
		translate: Translate
	): MaterialGraph {
		const graph: MaterialGraph = {
			material: [],
			process: [],
			sample: [],
			property: [],
			finding: []
		};
		if (!profile) return graph;

		graph.material = [
			{
				id: 'material:current',
				kind: 'material',
				label: profile.canonical_name,
				meta: translate('research.materialDossier.graph.materialMeta', {
					papers: profile.overview.paper_count || profile.papers.length,
					samples: profile.overview.sample_count || rows.length,
					properties: profile.overview.measured_properties.length || columns.length
				}),
				detail: joinedList(profile.aliases, translate('research.emptyValue')),
				evidenceCodes: []
			}
		];

		const processKeys = summary.changedKeys.length ? summary.changedKeys : summary.controlledKeys;
		graph.process = processKeys.map((key) => {
			const values = uniqueList(rows.map((row) => processValueWithUnit(row, key))).filter(
				(value) => value !== '--'
			);
			return {
				id: `process:${key}`,
				kind: 'process',
				label: processLabel(key, translate),
				meta: values.join(' / ') || translate('research.emptyValue'),
				detail: summary.changedKeys.includes(key)
					? translate('research.materialDossier.graph.changedVariable')
					: translate('research.materialDossier.graph.controlledVariable'),
				evidenceCodes: []
			};
		});
		if (!graph.process.length) {
			graph.process = profile.overview.process_families.slice(0, 4).map((process) => ({
				id: `process:${process}`,
				kind: 'process',
				label: process,
				meta: translate('research.materialDossier.graph.processFamily'),
				detail: translate('research.materialDossier.graph.processFamilyDetail'),
				evidenceCodes: []
			}));
		}

		graph.sample = rows.map((row, index) => ({
			id: `sample:${row.row_id}`,
			kind: 'sample',
			label: sampleDisplayLabel(row, translate, index),
			meta: variableSummary(row, summary, translate),
			detail: processBrief(row),
			evidenceCodes: rowEvidenceCodes(row, columns, codeMap)
		}));

		graph.property = columns.map((column) => {
			const best = bestValues.find((value) => value.column.key === column.key);
			const evidenceCodes = propertyEvidenceCodes(rows, column, codeMap);
			if (!evidenceCodes.length && best?.evidenceCode && best.evidenceCode !== '--') {
				evidenceCodes.push(best.evidenceCode);
			}
			return {
				id: `property:${column.key}`,
				kind: 'property',
				label: column.shortLabel,
				meta: best
					? translate('research.materialDossier.graph.bestValue', {
							sample: best.sample,
							value: best.displayValue
						})
					: translate('research.materialDossier.graph.noPropertyValue'),
				detail: column.unit
					? translate('research.materialDossier.graph.propertyUnit', { unit: column.unit })
					: translate('research.materialDossier.graph.propertyNoUnit'),
				evidenceCodes
			};
		});

		graph.finding = findings.map((finding) => ({
			id: `finding:${finding.key}`,
			kind: 'finding',
			label: finding.title,
			meta: `${finding.type} · ${finding.confidence}`,
			detail: finding.body,
			evidenceCodes: finding.evidenceCodes
		}));

		return graph;
	}

	function joinedList(values: string[], fallback: string) {
		const cleaned = values.map((value) => value.trim()).filter(Boolean);
		return cleaned.length ? cleaned.join(', ') : fallback;
	}

	function narrativeLead(profile: MaterialProfile, translate: Translate) {
		return translate('research.materialDossier.narrative.lead', {
			material: profile.canonical_name,
			processes: joinedList(
				profile.overview.process_families,
				translate('research.materialDossier.narrative.unspecifiedProcess')
			),
			papers: paperCount,
			samples: sampleCount,
			properties: joinedList(
				propertyColumns.map((column) => column.shortLabel),
				translate('research.materialDossier.narrative.unspecifiedProperties')
			),
			evidence: evidenceCount
		});
	}

	function narrativeSampleDesign(translate: Translate) {
		const controlled = joinedList(
			processSummary.controlledLabels,
			translate('research.materialDossier.narrative.noControlledVariables')
		);
		const changed = joinedList(
			processSummary.changedLabels,
			translate('research.materialDossier.narrative.noChangedVariables')
		);
		return translate('research.materialDossier.narrative.sampleDesignBody', {
			samples: sampleCount,
			controlled,
			changed
		});
	}

	function narrativeTrendBody(row: ComparisonRow | undefined, translate: Translate) {
		if (!row) return translate('research.materialDossier.narrative.trendEmpty');
		return translate('research.materialDossier.narrative.trendBody', {
			property: row.property,
			first: row.firstLabel,
			firstValue: row.firstValue ?? '--',
			second: row.secondLabel,
			secondValue: row.secondValue ?? '--',
			conclusion: row.conclusion
		});
	}

	function openValueEvidence(
		row: SampleMatrixRow,
		column: PropertyColumn,
		value: EvidenceBackedValue
	) {
		pdfDrawerOpen = false;
		selectedEvidence = drawerDetailForValue(row, column, value, evidenceCodeMap, collectionId, $t);
	}

	function openSupportedValue(value: SupportedValue) {
		openValueEvidence(value.row, value.column, value.value);
	}

	function openEvidenceRow(row: EvidenceLocatorRow) {
		pdfDrawerOpen = false;
		selectedEvidence = row.detail;
	}

	function closeDrawer() {
		selectedEvidence = null;
		pdfDrawerOpen = false;
	}

	function openPdfDrawer() {
		selectedEvidence = null;
		pdfDrawerOpen = true;
		if (!pdfReportLoading) {
			void loadPdfReportStatus();
		}
	}

	async function generatePdfReport(forceRegenerate = false) {
		if (!collectionId || !materialId || pdfReportBusy) return;
		pdfReportLoading = true;
		pdfReportError = '';
		try {
			const report = await createMaterialReviewReport(collectionId, materialId, {
				language: $language,
				report_type: 'review_draft',
				include_appendix: true,
				force_regenerate: forceRegenerate
			});
			pdfReport = report;
			updateReportPolling(report);
		} catch (err) {
			clearReportPoll();
			pdfReportError = errorMessage(err);
		} finally {
			pdfReportLoading = false;
		}
	}

	function pdfStatusBody() {
		if (pdfReportLoading && !pdfReport) {
			return $t('research.materialDossier.pdf.loadingStatus');
		}
		if (pdfReportGenerating) {
			return $t('research.materialDossier.pdf.generatingStatus');
		}
		if (pdfReport?.status === 'failed') {
			return $t('research.materialDossier.pdf.failedStatus');
		}
		return $t('research.materialDossier.pdf.body');
	}

	function pdfGeneratedStatus(report: MaterialReviewReport) {
		if (report.status === 'ready_with_warnings') {
			return $t('research.materialDossier.pdf.generatedWithWarnings', {
				count: report.warnings.length
			});
		}
		return $t('research.materialDossier.pdf.generatedStatus');
	}

	function csvEscape(value: string | number | null | undefined) {
		const text = String(value ?? '');
		return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
	}

	function exportCsv() {
		if (!browser || !materialProfile) return;
		const header = ['record_type', 'sample_id', 'property', 'value', 'evidence', 'source_location'];
		const rows = sampleRows.flatMap((row) =>
			propertyColumns.map((column) => {
				const value = row.values[column.key];
				const ref = value?.evidence_refs[0];
				return [
					'performance',
					sampleDisplayLabel(row, $t),
					column.shortLabel,
					value ? formatEvidenceBackedValue(value) : '',
					evidenceCode(ref, evidenceCodeMap),
					ref?.locator ?? ''
				];
			})
		);
		const csv = [header, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n');
		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = url;
		link.download = `${materialProfile.material_id || materialId}-material-dossier.csv`;
		link.click();
		URL.revokeObjectURL(url);
	}
</script>

<svelte:head>
	<title>{materialProfile?.canonical_name ?? $t('research.materialDossier.title')}</title>
</svelte:head>

<section class="material-dossier-page fade-up">
	<div class="dossier-topline">
		<a href={resolve('/collections/[id]/materials', { id: collectionId })}>
			{$t('research.materialProfile.back')}
		</a>
		<span aria-hidden="true">/</span>
		<span>{materialProfile?.canonical_name ?? materialId}</span>
	</div>

	<header class="dossier-header">
		<div class="dossier-header__copy">
			<div class="dossier-title-row">
				<h2>{materialProfile?.canonical_name ?? materialId}</h2>
				{#each materialTags as tag}
					<span class="dossier-tag">{tag}</span>
				{/each}
			</div>
			<p>{$t('research.materialDossier.subtitle')}</p>
		</div>
		<div class="dossier-header__actions" aria-label={$t('research.materialDossier.actions.label')}>
			<a
				class="btn btn--ghost btn--small"
				href={resolve('/collections/[id]/documents', { id: collectionId })}
			>
				{$t('research.materialDossier.actions.viewPapers')}
			</a>
			<a
				class="btn btn--ghost btn--small"
				href={resolve('/collections/[id]/evidence', { id: collectionId })}
			>
				{$t('research.materialDossier.actions.viewEvidence')}
			</a>
			<a
				class="btn btn--ghost btn--small"
				href={`${resolve('/collections/[id]/assistant', { id: collectionId })}?material_id=${encodeURIComponent(
					materialId
				)}`}
			>
				{$t('research.materialDossier.actions.askCopilot')}
			</a>
			<button class="btn btn--primary-light btn--small" type="button" on:click={openPdfDrawer}>
				{$t('research.materialDossier.actions.generatePdf')}
			</button>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadMaterialPage}>
				{$t('research.materialDossier.actions.refresh')}
			</button>
		</div>
	</header>

	{#if loading}
		<section class="dossier-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.materialProfile.loading')}</div>
		</section>
	{:else if error}
		<section class="dossier-state-card dossier-state-card--error" role="alert">
			<h3>{$t('research.materialProfile.errorTitle')}</h3>
			<p>{error}</p>
		</section>
	{:else if !materialProfile}
		<section class="dossier-state-card">
			<h3>{$t('research.materialProfile.emptyTitle')}</h3>
			<p>{$t('research.materialProfile.emptyBody')}</p>
		</section>
	{:else}
		<div class="dossier-tabs" role="tablist" aria-label={$t('research.materialDossier.tabs.label')}>
			<button
				type="button"
				role="tab"
				aria-selected={activeDossierTab === 'structured'}
				class:active={activeDossierTab === 'structured'}
				on:click={() => (activeDossierTab = 'structured')}
			>
				{$t('research.materialDossier.tabs.structured')}
			</button>
			<button
				type="button"
				role="tab"
				aria-selected={activeDossierTab === 'narrative'}
				class:active={activeDossierTab === 'narrative'}
				on:click={() => (activeDossierTab = 'narrative')}
			>
				{$t('research.materialDossier.tabs.narrative')}
			</button>
		</div>
		<div class="dossier-layout">
			{#if activeDossierTab === 'structured'}
				<main class="dossier-main" aria-label={$t('research.materialDossier.mainLabel')}>
				<section id="key-findings" class="dossier-card dossier-card--findings">
					<div class="dossier-section-heading">
						<span class="section-number">1</span>
						<h3>{$t('research.materialDossier.sections.findings.title')}</h3>
						<p>{$t('research.materialDossier.sections.findings.body')}</p>
					</div>

					<div class="finding-grid">
						{#each keyFindings as finding, index (finding.key)}
							<article class="finding-card">
								<div class="finding-card__header">
									<span>{index + 1}</span>
									<div>
										<h4>{finding.title}</h4>
										<p>{finding.body}</p>
									</div>
								</div>
								<div class="finding-meta">
									<span>{finding.type}</span>
									<span
										>{$t('research.materialDossier.evidence.confidence')}: {finding.confidence}</span
									>
									<span
										>{$t('research.materialDossier.evidence.anchor')}:
										{finding.evidenceCodes.join(', ') || '--'}</span
									>
								</div>
								{#if finding.supportedValues.length}
									<div class="finding-values">
										{#each finding.supportedValues as value (value.key)}
											<button type="button" on:click={() => openSupportedValue(value)}>
												<strong>{value.sample}</strong>
												<span>{value.property} = {value.displayValue}</span>
												<small>{value.evidenceCode}</small>
											</button>
										{/each}
									</div>
								{/if}
							</article>
						{:else}
							<p class="empty-copy">{$t('research.materialDossier.findings.empty')}</p>
						{/each}
					</div>
				</section>

				<section id="material-graph" class="dossier-card material-graph-card">
					<div class="dossier-section-heading">
						<span class="section-number">2</span>
						<h3>{$t('research.materialDossier.sections.graph.title')}</h3>
						<p>{$t('research.materialDossier.sections.graph.body')}</p>
					</div>

					<div
						class="material-graph-map"
						aria-label={$t('research.materialDossier.graph.label')}
					>
						{#each materialGraphColumns as column (column.kind)}
							<div class={`material-graph-column material-graph-column--${column.kind}`}>
								<h4>{column.title}</h4>
								<div class="material-graph-node-list">
									{#each column.nodes as node (node.id)}
										<button
											type="button"
											class={`material-graph-node material-graph-node--${node.kind}`}
											class:active={selectedGraphNodeId === node.id}
											aria-label={$t('research.materialDossier.graph.selectNode', {
												label: node.label
											})}
											on:click={() => selectGraphNode(node)}
										>
											<span>{graphNodeTypeLabel(node.kind, $t)}</span>
											<strong>{node.label}</strong>
											<small>{node.meta}</small>
										</button>
									{:else}
										<p class="empty-copy">{$t('research.materialDossier.graph.emptyColumn')}</p>
									{/each}
								</div>
							</div>
						{/each}
					</div>

					<div class="material-graph-detail" aria-live="polite">
						{#if selectedMaterialGraphNode}
							<div>
								<span>{graphNodeTypeLabel(selectedMaterialGraphNode.kind, $t)}</span>
								<h4>{selectedMaterialGraphNode.label}</h4>
								<p>{selectedMaterialGraphNode.detail}</p>
							</div>
							{#if selectedMaterialGraphNode.evidenceCodes.length}
								<div class="material-graph-evidence">
									<strong>{$t('research.materialDossier.graph.evidenceAnchors')}</strong>
									<div class="evidence-chip-row">
										{#each selectedMaterialGraphNode.evidenceCodes as code}
											<button type="button" class="evidence-chip" on:click={() => openEvidenceCode(code)}>
												{code}
											</button>
										{/each}
									</div>
								</div>
							{:else}
								<p class="empty-copy">{$t('research.materialDossier.graph.noEvidence')}</p>
							{/if}
						{:else}
							<p class="empty-copy">{$t('research.materialDossier.graph.selectPrompt')}</p>
						{/if}
					</div>
				</section>

				<section id="trend-comparison" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">3</span>
						<h3>{$t('research.materialDossier.sections.trends.title')}</h3>
						<p>{$t('research.materialDossier.sections.trends.body')}</p>
					</div>

					<div class="trend-grid">
						<div class="comparison-panel">
							<h4>{$t('research.materialDossier.comparison.topic')}</h4>
							<p>
								{$t('research.materialDossier.comparison.controls', {
									controlled: processSummary.controlledLabels.join(', ') || '--'
								})}
							</p>
							<div class="dossier-table-wrapper">
								<table class="dossier-table dossier-table--compact">
									<thead>
										<tr>
											<th>{$t('research.materialDossier.comparison.variable')}</th>
											<th>{$t('research.materialDossier.comparison.property')}</th>
											<th>{$t('research.materialDossier.comparison.observation')}</th>
											<th>{$t('research.materialDossier.comparison.conclusion')}</th>
										</tr>
									</thead>
									<tbody>
										{#each comparisonRows as row (row.key)}
											<tr>
												<td>{row.variable}</td>
												<td>{row.property}</td>
												<td>
													<div class="comparison-bars">
														<span>{row.firstValue ?? '--'}</span>
														<div class="bar-track">
															<span
																class="bar-fill bar-fill--primary"
																style={`width: ${((row.firstValue ?? 0) / row.maxValue) * 100}%`}
															></span>
															<span
																class="bar-fill bar-fill--secondary"
																style={`width: ${((row.secondValue ?? 0) / row.maxValue) * 100}%`}
															></span>
														</div>
														<span>{row.secondValue ?? '--'}</span>
													</div>
												</td>
												<td>{row.conclusion}</td>
											</tr>
										{:else}
											<tr>
												<td colspan="4" class="empty-cell">
													{$t('research.materialDossier.comparison.empty')}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>

						<div class="chart-panel">
							<h4>{$t('research.materialDossier.chart.title')}</h4>
							{#if trendRows.length}
								{@const trend = trendRows[0]}
								<div class="mini-chart" aria-label={trend.property}>
									<div class="chart-scale">
										<span>{Math.ceil(trend.maxValue)}</span>
										<span>{Math.round(trend.maxValue * 0.75)}</span>
										<span>{Math.round(trend.maxValue * 0.5)}</span>
										<span>0</span>
									</div>
									<div class="chart-bars">
										<div class="chart-bar">
											<span
												class="chart-bar__fill chart-bar__fill--primary"
												style={`height: ${((trend.firstValue ?? 0) / trend.maxValue) * 100}%`}
											></span>
											<strong>{trend.firstValue ?? '--'}</strong>
										</div>
										<div class="chart-bar">
											<span
												class="chart-bar__fill chart-bar__fill--secondary"
												style={`height: ${((trend.secondValue ?? 0) / trend.maxValue) * 100}%`}
											></span>
											<strong>{trend.secondValue ?? '--'}</strong>
										</div>
									</div>
									<div class="chart-labels">
										<span>{trend.firstLabel}</span>
										<span>{trend.secondLabel}</span>
									</div>
								</div>
								<p class="chart-caption">
									{$t('research.materialDossier.chart.caption')}
								</p>
							{:else}
								<p class="empty-copy">{$t('research.materialDossier.chart.empty')}</p>
							{/if}
						</div>
					</div>
				</section>

				<section id="performance-results" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">4</span>
						<h3>{$t('research.materialDossier.sections.performance.title')}</h3>
						<p>{$t('research.materialDossier.sections.performance.body')}</p>
					</div>

					<div class="dossier-table-wrapper">
						<table class="dossier-table dossier-table--wide">
							<thead>
								<tr>
									<th>{$t('research.materialDossier.table.sampleCondition')}</th>
									<th>{$t('research.materialDossier.table.primaryVariable')}</th>
									<th>{$t('research.materialDossier.table.processSummary')}</th>
									{#each propertyColumns as column (column.key)}
										<th>{column.label}</th>
									{/each}
									<th>{$t('research.materialDossier.table.evidenceAnchors')}</th>
								</tr>
							</thead>
							<tbody>
								{#each sampleRows as row, rowIndex (row.row_id)}
									<tr>
										<td>
											<div class="sample-condition">
												<strong>{sampleDisplayLabel(row, $t, rowIndex)}</strong>
												<small>{materialProfile.canonical_name}</small>
											</div>
										</td>
										<td>{variableSummary(row, processSummary, $t)}</td>
										<td>{processBrief(row)}</td>
										{#each propertyColumns as column (column.key)}
											{@const value = row.values[column.key]}
											<td>
												{#if value}
													<button
														type="button"
														class="value-button"
														on:click={() => openValueEvidence(row, column, value)}
													>
														{formatEvidenceBackedValue(value)}
													</button>
												{:else}
													<span class="empty-value">--</span>
												{/if}
											</td>
										{/each}
										<td>{rowEvidenceLabels(row, propertyColumns, evidenceCodeMap)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<p class="dossier-table-note">
						{$t('research.materialDossier.performance.summary', {
							samples: sampleRows.length,
							properties: propertyColumns.length
						})}
					</p>
				</section>

				<section id="evidence-locator" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">5</span>
						<h3>{$t('research.materialDossier.sections.evidence.title')}</h3>
						<p>{$t('research.materialDossier.sections.evidence.body')}</p>
					</div>

					<div class="dossier-table-wrapper">
						<table class="dossier-table">
							<thead>
								<tr>
									<th>{$t('research.materialDossier.evidence.code')}</th>
									<th>{$t('research.materialDossier.evidence.claim')}</th>
									<th>{$t('research.materialDossier.evidence.type')}</th>
									<th>{$t('research.materialDossier.evidence.location')}</th>
									<th>{$t('research.materialDossier.evidence.anchor')}</th>
									<th>{$t('research.materialDossier.evidence.confidence')}</th>
								</tr>
							</thead>
							<tbody>
								{#each evidenceRows as row (row.key)}
									<tr>
										<td>{row.code}</td>
										<td>
											<button
												type="button"
												class="evidence-row-button"
												on:click={() => openEvidenceRow(row)}
											>
												{row.claim}
											</button>
										</td>
										<td>{row.type}</td>
										<td>
											{#if row.href}
												<a class="dossier-link" href={row.href}>{row.location}</a>
											{:else}
												{row.location}
											{/if}
										</td>
										<td>{row.code}</td>
										<td>{row.confidence}</td>
									</tr>
								{:else}
									<tr>
										<td colspan="6" class="empty-cell">
											{$t('research.materialDossier.evidence.empty')}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<a class="footer-link" href={resolve('/collections/[id]/evidence', { id: collectionId })}>
						{$t('research.materialDossier.evidence.viewAll', { count: evidenceCount })}
					</a>
				</section>
			</main>
			{:else}
				<main
					class="dossier-main dossier-main--narrative"
					aria-label={$t('research.materialDossier.narrative.mainLabel')}
				>
					<section id="narrative-overview" class="dossier-card narrative-card">
						<p class="narrative-eyebrow">
							{$t('research.materialDossier.narrative.eyebrow')}
						</p>
						<h3>{$t('research.materialDossier.narrative.overviewTitle')}</h3>
						<p class="narrative-lede">{narrativeLead(materialProfile, $t)}</p>
						<div class="narrative-metrics">
							<div>
								<strong>{paperCount}</strong>
								<span>{$t('research.materialDossier.aside.sourcePapers')}</span>
							</div>
							<div>
								<strong>{sampleCount}</strong>
								<span>{$t('research.overview.samples')}</span>
							</div>
							<div>
								<strong>{measuredPropertyCount}</strong>
								<span>{$t('research.overview.properties')}</span>
							</div>
							<div>
								<strong>{evidenceCount}</strong>
								<span>{$t('research.overview.evidence')}</span>
							</div>
						</div>
					</section>

					<section id="narrative-samples" class="dossier-card narrative-card">
						<div class="narrative-section-heading">
							<span>1</span>
							<div>
								<h3>{$t('research.materialDossier.narrative.sampleDesignTitle')}</h3>
								<p>{narrativeSampleDesign($t)}</p>
							</div>
						</div>
						<div class="dossier-table-wrapper narrative-table-wrapper">
							<table class="dossier-table dossier-table--compact">
								<thead>
									<tr>
										<th>{$t('research.materialDossier.table.sampleCondition')}</th>
										<th>{$t('research.materialDossier.table.primaryVariable')}</th>
										<th>{$t('research.materialDossier.table.processSummary')}</th>
									</tr>
								</thead>
								<tbody>
									{#each sampleRows.slice(0, 5) as row, rowIndex (row.row_id)}
										<tr>
											<td>{sampleDisplayLabel(row, $t, rowIndex)}</td>
											<td>{variableSummary(row, processSummary, $t)}</td>
											<td>{processBrief(row)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</section>

					<section id="narrative-findings" class="dossier-card narrative-card">
						<div class="narrative-section-heading">
							<span>2</span>
							<div>
								<h3>{$t('research.materialDossier.narrative.findingsTitle')}</h3>
								<p>{$t('research.materialDossier.narrative.findingsBody')}</p>
							</div>
						</div>
						<div class="best-value-grid">
							{#each bestPropertyValues as value (value.key)}
								<button
									type="button"
									class="best-value-card"
									on:click={() => openSupportedValue(value)}
								>
									<span>{value.property}</span>
									<strong>{value.displayValue}</strong>
									<small>{value.sample}</small>
									<em>{value.evidenceCode}</em>
								</button>
							{:else}
								<p class="empty-copy">{$t('research.materialDossier.findings.empty')}</p>
							{/each}
						</div>
						<div class="narrative-finding-list">
							{#each keyFindings as finding (finding.key)}
								<article class="narrative-finding">
									<h4>{finding.title}</h4>
									<p>{finding.body}</p>
									<div class="evidence-chip-row">
										{#each finding.evidenceCodes as code}
											<button type="button" class="evidence-chip" on:click={() => openEvidenceCode(code)}>
												{code}
											</button>
										{:else}
											<span class="evidence-chip evidence-chip--muted">--</span>
										{/each}
									</div>
								</article>
							{/each}
						</div>
					</section>

					<section id="narrative-trends" class="dossier-card narrative-card">
						<div class="narrative-section-heading">
							<span>3</span>
							<div>
								<h3>{$t('research.materialDossier.narrative.trendQuestion')}</h3>
								<p>{narrativeTrendBody(trendRows[0], $t)}</p>
							</div>
						</div>
						{#if trendRows.length}
							{@const trend = trendRows[0]}
							<div class="narrative-comparison-card">
								<div>
									<strong>{trend.firstLabel}</strong>
									<span>{trend.property}: {trend.firstValue ?? '--'}</span>
								</div>
								<div>
									<strong>{trend.secondLabel}</strong>
									<span>{trend.property}: {trend.secondValue ?? '--'}</span>
								</div>
							</div>
						{/if}
						<div class="evidence-chip-row">
							{#each evidenceRows.slice(0, 4) as row (row.key)}
								<button type="button" class="evidence-chip" on:click={() => openEvidenceRow(row)}>
									{row.code}
								</button>
							{/each}
						</div>
					</section>

					<section id="narrative-evidence" class="dossier-card narrative-card">
						<div class="narrative-section-heading">
							<span>4</span>
							<div>
								<h3>{$t('research.materialDossier.narrative.evidenceTitle')}</h3>
								<p>{$t('research.materialDossier.narrative.evidenceBody')}</p>
							</div>
						</div>
						<div class="evidence-chip-row">
							{#each evidenceRows as row (row.key)}
								<button type="button" class="evidence-chip" on:click={() => openEvidenceRow(row)}>
									{row.code}
								</button>
							{:else}
								<span class="evidence-chip evidence-chip--muted">
									{$t('research.materialDossier.evidence.empty')}
								</span>
							{/each}
						</div>
						<a class="footer-link" href={resolve('/collections/[id]/evidence', { id: collectionId })}>
							{$t('research.materialDossier.evidence.viewAll', { count: evidenceCount })}
						</a>
					</section>
				</main>
			{/if}

			<aside class="dossier-aside" aria-label={$t('research.materialDossier.aside.label')}>
				<section class="aside-card aside-card--source">
					<h3>{$t('research.materialDossier.aside.sourceInfo')}</h3>
					<p>
						<strong>{$t('research.materialDossier.aside.sourcePapers')}</strong>
						<span>{paperCount}</span>
					</p>
					<p>
						<strong>{$t('research.materialDossier.aside.lastUpdated')}</strong>
						<span>{$t('research.materialDossier.aside.lastUpdatedUnknown')}</span>
					</p>
				</section>

				<nav
					class="aside-card quick-nav"
					aria-label={$t('research.materialDossier.aside.quickNav')}
				>
					<h3>{$t('research.materialDossier.aside.quickNav')}</h3>
					{#if activeDossierTab === 'structured'}
						<a href="#key-findings">1 {$t('research.materialDossier.sections.findings.title')}</a>
						<a href="#material-graph">2 {$t('research.materialDossier.sections.graph.title')}</a>
						<a href="#trend-comparison">3 {$t('research.materialDossier.sections.trends.title')}</a>
						<a href="#performance-results"
							>4 {$t('research.materialDossier.sections.performance.title')}</a
						>
						<a href="#evidence-locator"
							>5 {$t('research.materialDossier.sections.evidence.title')}</a
						>
					{:else}
						<a href="#narrative-overview"
							>1 {$t('research.materialDossier.narrative.overviewTitle')}</a
						>
						<a href="#narrative-samples"
							>2 {$t('research.materialDossier.narrative.sampleDesignTitle')}</a
						>
						<a href="#narrative-findings"
							>3 {$t('research.materialDossier.narrative.findingsTitle')}</a
						>
						<a href="#narrative-evidence"
							>4 {$t('research.materialDossier.narrative.evidenceTitle')}</a
						>
					{/if}
				</nav>

				<section class="aside-card">
					<h3>{$t('research.materialDossier.aside.literatureInfo')}</h3>
					<p>
						{$t('research.materialDossier.aside.sourcePapers')}: {paperCount}
					</p>
					{#each materialPapers().slice(0, 2) as paper (paper.document_id)}
						<a
							class="paper-mini-card"
							href={resolve('/collections/[id]/documents/[document_id]', {
								id: collectionId,
								document_id: paper.document_id
							})}
						>
							<strong>{paper.title}</strong>
							<span>{paper.source_filename ?? formatShortIdentifier(paper.document_id)}</span>
						</a>
					{:else}
						<p class="empty-copy">{$t('research.materialDossier.aside.noLiterature')}</p>
					{/each}
				</section>

				<section class="aside-card action-card">
					<h3>{$t('research.materialDossier.aside.actions')}</h3>
					<a href={resolve('/collections/[id]/documents', { id: collectionId })}>
						{$t('research.materialDossier.actions.viewPapers')}
					</a>
					<a href={resolve('/collections/[id]/evidence', { id: collectionId })}>
						{$t('research.materialDossier.actions.viewEvidence')}
					</a>
					<a
						href={`${resolve('/collections/[id]/assistant', {
							id: collectionId
						})}?material_id=${encodeURIComponent(materialId)}`}
					>
						{$t('research.materialDossier.actions.askCopilot')}
					</a>
					<button type="button" on:click={exportCsv}>
						{$t('research.materialDossier.actions.exportCsv')}
					</button>
				</section>

				<section class="aside-card aside-card--tip">
					<h3>{$t('research.materialDossier.aside.tip')}</h3>
					<p>{$t('research.materialDossier.aside.tipBody')}</p>
				</section>
			</aside>
		</div>
	{/if}

	{#if selectedEvidence}
		<aside class="detail-drawer" aria-label={$t('research.materialDossier.evidence.drawerTitle')}>
			<div class="detail-drawer__header">
				<h3>{$t('research.materialDossier.evidence.drawerTitle')}</h3>
				<button type="button" on:click={closeDrawer}>
					{$t('research.evidence.close')}
				</button>
			</div>
			<dl>
				<div>
					<dt>{$t('research.materialDossier.evidence.value')}</dt>
					<dd>{selectedEvidence.title}</dd>
				</div>
				<div>
					<dt>{$t('research.materialDossier.table.sampleId')}</dt>
					<dd>{selectedEvidence.sample}</dd>
				</div>
				<div>
					<dt>{$t('research.materialDossier.evidence.source')}</dt>
					<dd>{selectedEvidence.source}</dd>
				</div>
				<div>
					<dt>{$t('research.materialDossier.evidence.location')}</dt>
					<dd>
						{#if selectedEvidence.href}
							<a class="dossier-link" href={selectedEvidence.href}>{selectedEvidence.location}</a>
						{:else}
							{selectedEvidence.location}
						{/if}
					</dd>
				</div>
				<div>
					<dt>{$t('research.materialDossier.evidence.anchor')}</dt>
					<dd>{selectedEvidence.anchor}</dd>
				</div>
				<div>
					<dt>{$t('research.materialDossier.evidence.confidence')}</dt>
					<dd>{selectedEvidence.confidence}</dd>
				</div>
				<div class="drawer-wide">
					<dt>{$t('research.materialDossier.evidence.excerpt')}</dt>
					<dd>{selectedEvidence.excerpt}</dd>
				</div>
			</dl>
		</aside>
	{/if}

	{#if pdfDrawerOpen}
		<aside class="detail-drawer" aria-label={$t('research.materialDossier.pdf.title')}>
			<div class="detail-drawer__header">
				<h3>
					{pdfReportReady
						? $t('research.materialDossier.pdf.generatedTitle')
						: $t('research.materialDossier.pdf.title')}
				</h3>
				<button type="button" on:click={closeDrawer}>
					{$t('research.evidence.close')}
				</button>
			</div>
			{#if pdfReportReady && pdfReport}
				<p
					class:pdf-status--warning={pdfReport.status === 'ready_with_warnings'}
					class="pdf-status"
				>
					{pdfGeneratedStatus(pdfReport)}
				</p>
				<dl class="pdf-data">
					<div>
						<dt>{$t('research.materialDossier.pdf.reportTitle')}</dt>
						<dd>{pdfReport.title ?? materialProfile?.canonical_name ?? materialId}</dd>
					</div>
					<div>
						<dt>{$t('research.materialDossier.pdf.readiness')}</dt>
						<dd>{pdfReport.readiness} · {pdfReport.readiness_reason}</dd>
					</div>
				</dl>
				{#if pdfReport.warnings.length}
					<ul class="pdf-warning-list">
						{#each pdfReport.warnings as warning}
							<li>{warning}</li>
						{/each}
					</ul>
				{/if}
				<div class="drawer-actions">
					<a
						class="btn btn--ghost btn--small"
						href={buildMaterialReviewMarkdownUrl(collectionId, materialId)}
						target="_blank"
						rel="noreferrer"
					>
						{$t('research.materialDossier.pdf.previewMarkdown')}
					</a>
					<a
						class="btn btn--ghost btn--small"
						href={buildMaterialReviewPdfUrl(collectionId, materialId)}
						target="_blank"
						rel="noreferrer"
					>
						{$t('research.materialDossier.pdf.view')}
					</a>
					<a
						class="btn btn--ghost btn--small"
						href={buildMaterialReviewPdfUrl(collectionId, materialId)}
						download
					>
						{$t('research.materialDossier.pdf.download')}
					</a>
					<button
						class="btn btn--primary-light btn--small"
						type="button"
						disabled={pdfReportBusy}
						on:click={() => generatePdfReport(true)}
					>
						{$t('research.materialDossier.pdf.regenerate')}
					</button>
				</div>
			{:else}
				<p>{pdfStatusBody()}</p>
				{#if pdfReportError}
					<p class="pdf-error" role="alert">{pdfReportError}</p>
				{/if}
				<ul class="pdf-list">
					<li>{$t('research.materialDossier.sections.findings.title')}</li>
					<li>{$t('research.materialDossier.sections.trends.title')}</li>
					<li>{$t('research.materialDossier.sections.performance.title')}</li>
					<li>{$t('research.materialDossier.sections.evidence.title')}</li>
				</ul>
				<dl class="pdf-data">
					<div>
						<dt>{$t('research.materialDossier.aside.sourcePapers')}</dt>
						<dd>{paperCount}</dd>
					</div>
					<div>
						<dt>{$t('research.overview.samples')}</dt>
						<dd>{sampleCount}</dd>
					</div>
					<div>
						<dt>{$t('research.overview.properties')}</dt>
						<dd>{measuredPropertyCount}</dd>
					</div>
					<div>
						<dt>{$t('research.overview.evidence')}</dt>
						<dd>{evidenceCount}</dd>
					</div>
				</dl>
				<div class="drawer-actions">
					<button class="btn btn--ghost btn--small" type="button" on:click={closeDrawer}>
						{$t('research.materialDossier.pdf.cancel')}
					</button>
					<button
						class="btn btn--primary-light btn--small"
						type="button"
						disabled={pdfReportBusy}
						on:click={() => generatePdfReport(pdfReport?.status === 'failed')}
					>
						{pdfReportBusy
							? $t('research.materialDossier.pdf.generatingStatus')
							: pdfReport?.status === 'failed'
								? $t('research.materialDossier.pdf.regenerate')
								: $t('research.materialDossier.pdf.generate')}
					</button>
				</div>
			{/if}
		</aside>
	{/if}
</section>

<style>
	.material-dossier-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 16px;
	}

	.dossier-topline {
		min-height: 32px;
		display: flex;
		align-items: center;
		gap: 8px;
		color: #64748b;
		font-size: 14px;
		line-height: 22px;
	}

	.dossier-topline a,
	.dossier-link,
	.footer-link {
		color: #2563eb;
		font-weight: 700;
	}

	.dossier-topline span:last-child {
		color: #0f172a;
		font-weight: 700;
	}

	.dossier-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		padding-bottom: 4px;
	}

	.dossier-title-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.dossier-title-row h2 {
		margin: 0;
		color: #0f172a;
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
	}

	.dossier-header p {
		max-width: 760px;
		margin: 8px 0 0;
		color: #64748b;
		font-size: 14px;
		line-height: 22px;
	}

	.dossier-tag {
		display: inline-flex;
		align-items: center;
		height: 24px;
		padding: 0 8px;
		border: 1px solid #bfdbfe;
		border-radius: 6px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.dossier-header__actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 8px;
	}

	.dossier-tabs {
		width: fit-content;
		display: inline-flex;
		gap: 4px;
		padding: 4px;
		border: 1px solid #dbe4f0;
		border-radius: 10px;
		background: #ffffff;
		box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
	}

	.dossier-tabs button {
		min-height: 32px;
		padding: 0 12px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: #475569;
		font-size: 14px;
		font-weight: 700;
		line-height: 20px;
		cursor: pointer;
	}

	.dossier-tabs button.active {
		background: #eff6ff;
		color: #2563eb;
	}

	.btn--primary-light {
		border-color: #bfdbfe;
		background: #eff6ff;
		color: #2563eb;
	}

	.btn--primary-light:not(:disabled):hover {
		background: #dbeafe;
		color: #1d4ed8;
	}

	.dossier-state-card,
	.dossier-card,
	.aside-card,
	.detail-drawer {
		border: 1px solid #e3eaf5;
		border-radius: 12px;
		background: #ffffff;
		box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
	}

	.dossier-state-card {
		display: grid;
		gap: 8px;
		padding: 18px;
	}

	.dossier-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.dossier-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 280px;
		gap: 24px;
		align-items: start;
	}

	.dossier-main {
		display: grid;
		gap: 16px;
		min-width: 0;
	}

	.dossier-main--narrative {
		max-width: 880px;
	}

	.dossier-card {
		display: grid;
		gap: 12px;
		padding: 16px;
		overflow: hidden;
	}

	.dossier-section-heading {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 8px;
	}

	.section-number {
		width: 22px;
		height: 22px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 6px;
		background: #2563eb;
		color: #ffffff;
		font-size: 13px;
		font-weight: 800;
		line-height: 18px;
	}

	.dossier-section-heading h3,
	.aside-card h3,
	.comparison-panel h4,
	.chart-panel h4,
	.detail-drawer h3 {
		margin: 0;
		color: #0f172a;
	}

	.dossier-section-heading h3 {
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.dossier-section-heading p {
		margin: 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.finding-grid {
		display: grid;
		gap: 12px;
	}

	.finding-card {
		display: grid;
		gap: 12px;
		padding: 14px;
		border: 1px solid #dbeafe;
		border-radius: 10px;
		background: #f8fbff;
	}

	.finding-card__header {
		display: grid;
		grid-template-columns: 26px minmax(0, 1fr);
		gap: 10px;
		align-items: start;
	}

	.finding-card__header > span {
		width: 24px;
		height: 24px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 8px;
		background: #2563eb;
		color: #ffffff;
		font-size: 13px;
		font-weight: 800;
		line-height: 18px;
	}

	.finding-card h4 {
		margin: 0;
		color: #0f172a;
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
	}

	.finding-card p {
		margin: 4px 0 0;
		color: #475569;
		font-size: 14px;
		line-height: 22px;
	}

	.finding-meta,
	.finding-values {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.finding-meta span {
		display: inline-flex;
		align-items: center;
		min-height: 24px;
		padding: 3px 8px;
		border: 1px solid #e2e8f0;
		border-radius: 6px;
		background: #ffffff;
		color: #475569;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.finding-values button {
		display: grid;
		gap: 2px;
		min-width: 180px;
		padding: 9px 10px;
		border: 1px solid #bfdbfe;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		text-align: left;
		cursor: pointer;
	}

	.finding-values button:hover {
		border-color: #2563eb;
		background: #eff6ff;
	}

	.finding-values strong,
	.finding-values span,
	.finding-values small {
		overflow-wrap: anywhere;
	}

	.finding-values strong {
		color: #2563eb;
		font-size: 13px;
		line-height: 19px;
	}

	.finding-values span {
		font-size: 13px;
		font-weight: 700;
		line-height: 19px;
	}

	.finding-values small {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.material-graph-card {
		gap: 14px;
	}

	.material-graph-map {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 10px;
		align-items: stretch;
		overflow-x: auto;
		padding-bottom: 2px;
	}

	.material-graph-column {
		position: relative;
		min-width: 170px;
		display: grid;
		align-content: start;
		gap: 8px;
		padding: 10px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #fbfdff;
	}

	.material-graph-column:not(:last-child)::after {
		content: '';
		position: absolute;
		right: -8px;
		top: 42px;
		width: 14px;
		height: 2px;
		background: #cbd5e1;
		z-index: 1;
	}

	.material-graph-column h4 {
		margin: 0;
		color: #0f172a;
		font-size: 13px;
		font-weight: 800;
		line-height: 20px;
	}

	.material-graph-node-list {
		display: grid;
		gap: 8px;
	}

	.material-graph-node {
		display: grid;
		gap: 4px;
		min-height: 82px;
		padding: 10px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		text-align: left;
		cursor: pointer;
	}

	.material-graph-node:hover,
	.material-graph-node.active {
		border-color: #2563eb;
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.material-graph-node--process {
		border-color: #bae6fd;
	}

	.material-graph-node--sample {
		border-color: #bbf7d0;
	}

	.material-graph-node--property {
		border-color: #a5f3fc;
	}

	.material-graph-node--finding {
		border-color: #fed7aa;
	}

	.material-graph-node span {
		width: max-content;
		max-width: 100%;
		padding: 2px 7px;
		border-radius: 999px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 11px;
		font-weight: 800;
		line-height: 16px;
	}

	.material-graph-node strong {
		color: #0f172a;
		font-size: 13px;
		line-height: 18px;
		overflow-wrap: anywhere;
	}

	.material-graph-node small {
		color: #64748b;
		font-size: 12px;
		line-height: 17px;
		overflow-wrap: anywhere;
	}

	.material-graph-detail {
		display: grid;
		gap: 10px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #f8fafc;
	}

	.material-graph-detail > div:first-child {
		display: grid;
		gap: 4px;
	}

	.material-graph-detail span {
		width: max-content;
		padding: 2px 7px;
		border-radius: 999px;
		background: #e0f2fe;
		color: #0369a1;
		font-size: 11px;
		font-weight: 800;
		line-height: 16px;
	}

	.material-graph-detail h4 {
		margin: 0;
		color: #0f172a;
		font-size: 15px;
		font-weight: 800;
		line-height: 22px;
	}

	.material-graph-detail p {
		margin: 0;
		color: #475569;
		font-size: 13px;
		line-height: 20px;
	}

	.material-graph-evidence {
		display: grid;
		gap: 8px;
	}

	.material-graph-evidence strong {
		color: #0f172a;
		font-size: 13px;
		line-height: 20px;
	}

	.dossier-table-wrapper {
		overflow-x: auto;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
	}

	.dossier-table {
		width: 100%;
		min-width: 760px;
		border-collapse: collapse;
	}

	.dossier-table--compact {
		min-width: 620px;
	}

	.dossier-table--wide {
		min-width: 1080px;
	}

	.dossier-table th,
	.dossier-table td {
		padding: 10px 12px;
		border-bottom: 1px solid #e2e8f0;
		border-right: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: middle;
		color: #0f172a;
		font-size: 13px;
		line-height: 20px;
	}

	.dossier-table th:last-child,
	.dossier-table td:last-child {
		border-right: 0;
	}

	.dossier-table tbody tr:last-child td {
		border-bottom: 0;
	}

	.dossier-table th {
		background: #f8fafc;
		color: #0f172a;
		font-weight: 700;
	}

	.sample-condition {
		display: grid;
		gap: 3px;
		min-width: 180px;
	}

	.sample-condition strong {
		color: #2563eb;
		font-weight: 700;
	}

	.sample-condition small {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.value-button,
	.evidence-row-button {
		border: 0;
		background: transparent;
		color: #2563eb;
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		cursor: pointer;
		padding: 0;
		text-align: left;
	}

	.value-button:hover,
	.evidence-row-button:hover,
	.dossier-link:hover,
	.footer-link:hover,
	.action-card a:hover,
	.action-card button:hover,
	.quick-nav a:hover {
		color: #1d4ed8;
	}

	.empty-value,
	.empty-copy,
	.empty-cell {
		color: #64748b;
	}

	.dossier-table-note {
		margin: 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.trend-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
		gap: 16px;
	}

	.comparison-panel,
	.chart-panel {
		display: grid;
		gap: 10px;
		min-width: 0;
	}

	.comparison-panel > p,
	.chart-caption {
		margin: 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.comparison-bars {
		min-width: 180px;
		display: grid;
		grid-template-columns: 42px minmax(80px, 1fr) 42px;
		gap: 8px;
		align-items: center;
	}

	.bar-track {
		display: grid;
		gap: 3px;
	}

	.bar-fill {
		display: block;
		height: 8px;
		border-radius: 999px;
	}

	.bar-fill--primary,
	.chart-bar__fill--primary {
		background: #2563eb;
	}

	.bar-fill--secondary,
	.chart-bar__fill--secondary {
		background: #16a34a;
	}

	.mini-chart {
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr);
		grid-template-rows: 180px auto;
		gap: 8px 10px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
	}

	.chart-scale {
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		align-items: flex-end;
		color: #475569;
		font-size: 12px;
		line-height: 16px;
	}

	.chart-bars {
		display: grid;
		grid-template-columns: repeat(2, minmax(54px, 1fr));
		gap: 28px;
		align-items: end;
		padding: 0 12px;
		border-left: 1px solid #cbd5e1;
		border-bottom: 1px solid #cbd5e1;
		background: linear-gradient(#e2e8f0 1px, transparent 1px) 0 0 / 100% 25%;
	}

	.chart-bar {
		position: relative;
		height: 100%;
		display: flex;
		align-items: flex-end;
		justify-content: center;
	}

	.chart-bar__fill {
		width: 54px;
		min-height: 2px;
		display: block;
		border-radius: 6px 6px 0 0;
	}

	.chart-bar strong {
		position: absolute;
		bottom: calc(100% + 4px);
		color: #0f172a;
		font-size: 12px;
		line-height: 16px;
	}

	.chart-labels {
		grid-column: 2;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		color: #0f172a;
		font-size: 12px;
		line-height: 18px;
		text-align: center;
	}

	.narrative-card {
		gap: 14px;
		padding: 18px;
	}

	.narrative-eyebrow {
		margin: 0;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
		text-transform: uppercase;
	}

	.narrative-card h3,
	.narrative-finding h4 {
		margin: 0;
		color: #0f172a;
	}

	.narrative-card h3 {
		font-size: 20px;
		font-weight: 800;
		line-height: 28px;
	}

	.narrative-lede,
	.narrative-section-heading p,
	.narrative-finding p {
		margin: 0;
		color: #475569;
		font-size: 15px;
		line-height: 25px;
	}

	.narrative-metrics,
	.best-value-grid,
	.narrative-comparison-card {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 10px;
	}

	.narrative-metrics div,
	.best-value-card,
	.narrative-comparison-card div,
	.narrative-finding {
		border: 1px solid #e2e8f0;
		border-radius: 10px;
		background: #f8fbff;
	}

	.narrative-metrics div {
		display: grid;
		gap: 2px;
		padding: 12px;
	}

	.narrative-metrics strong {
		color: #0f172a;
		font-size: 22px;
		line-height: 28px;
	}

	.narrative-metrics span,
	.best-value-card span,
	.best-value-card small,
	.best-value-card em,
	.narrative-comparison-card span {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.narrative-section-heading {
		display: grid;
		grid-template-columns: 28px minmax(0, 1fr);
		gap: 12px;
		align-items: start;
	}

	.narrative-section-heading > span {
		width: 26px;
		height: 26px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 8px;
		background: #2563eb;
		color: #ffffff;
		font-size: 13px;
		font-weight: 800;
		line-height: 18px;
	}

	.narrative-table-wrapper .dossier-table {
		min-width: 620px;
	}

	.best-value-card {
		display: grid;
		gap: 3px;
		padding: 12px;
		text-align: left;
		cursor: pointer;
	}

	.best-value-card:hover {
		border-color: #2563eb;
		background: #eff6ff;
	}

	.best-value-card strong {
		color: #0f172a;
		font-size: 18px;
		line-height: 26px;
	}

	.best-value-card em {
		font-style: normal;
		font-weight: 800;
		color: #2563eb;
	}

	.narrative-finding-list,
	.evidence-chip-row {
		display: grid;
		gap: 10px;
	}

	.narrative-finding {
		display: grid;
		gap: 8px;
		padding: 14px;
	}

	.narrative-finding h4 {
		font-size: 16px;
		font-weight: 800;
		line-height: 24px;
	}

	.evidence-chip-row {
		display: flex;
		flex-wrap: wrap;
	}

	.evidence-chip {
		min-height: 28px;
		padding: 0 9px;
		border: 1px solid #bfdbfe;
		border-radius: 999px;
		background: #ffffff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
		cursor: pointer;
	}

	.evidence-chip:hover {
		border-color: #2563eb;
		background: #eff6ff;
	}

	.evidence-chip--muted {
		border-color: #e2e8f0;
		color: #64748b;
		cursor: default;
	}

	.narrative-comparison-card div {
		display: grid;
		gap: 4px;
		padding: 14px;
	}

	.narrative-comparison-card strong {
		color: #0f172a;
		font-size: 14px;
		line-height: 22px;
	}

	.footer-link {
		width: fit-content;
		font-size: 13px;
		line-height: 20px;
	}

	.dossier-aside {
		position: sticky;
		top: 96px;
		display: grid;
		gap: 14px;
		min-width: 0;
	}

	.aside-card {
		display: grid;
		gap: 10px;
		padding: 14px;
	}

	.aside-card h3 {
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
	}

	.aside-card p {
		margin: 0;
		color: #475569;
		font-size: 13px;
		line-height: 20px;
	}

	.aside-card--source {
		border-color: #bfdbfe;
		background: #eff6ff;
		color: #1e3a8a;
	}

	.aside-card--source p {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		color: #1e3a8a;
	}

	.quick-nav a,
	.action-card a,
	.action-card button {
		display: flex;
		align-items: center;
		min-height: 32px;
		border: 0;
		background: transparent;
		color: #2563eb;
		font-size: 14px;
		font-weight: 700;
		line-height: 20px;
		text-align: left;
		cursor: pointer;
		padding: 0;
	}

	.paper-mini-card {
		display: grid;
		gap: 4px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
	}

	.paper-mini-card strong {
		color: #2563eb;
		font-size: 13px;
		line-height: 20px;
	}

	.paper-mini-card span {
		color: #0f172a;
		font-size: 12px;
		line-height: 18px;
	}

	.aside-card--tip {
		border-color: #fde68a;
		background: #fffbeb;
		color: #92400e;
	}

	.aside-card--tip p {
		color: #92400e;
	}

	.detail-drawer {
		position: fixed;
		top: 88px;
		right: 24px;
		z-index: 30;
		width: min(380px, calc(100vw - 48px));
		max-height: calc(100vh - 112px);
		display: grid;
		gap: 14px;
		padding: 18px;
		overflow-y: auto;
	}

	.detail-drawer__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}

	.detail-drawer__header h3 {
		font-size: 18px;
		line-height: 26px;
	}

	.detail-drawer__header button {
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
		color: #64748b;
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		padding: 5px 9px;
		cursor: pointer;
	}

	.detail-drawer dl,
	.pdf-data {
		display: grid;
		gap: 10px;
		margin: 0;
	}

	.detail-drawer dt,
	.pdf-data dt {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.detail-drawer dd,
	.pdf-data dd {
		margin: 3px 0 0;
		color: #0f172a;
		font-size: 14px;
		line-height: 21px;
	}

	.drawer-wide dd {
		color: #475569;
	}

	.pdf-list {
		margin: 0;
		padding-left: 18px;
		color: #475569;
		font-size: 14px;
		line-height: 22px;
	}

	.pdf-status {
		margin: 0;
		color: #16a34a;
		font-weight: 700;
	}

	.pdf-status--warning {
		color: #f59e0b;
	}

	.pdf-error {
		margin: 0;
		color: #b91c1c;
		font-size: 13px;
		line-height: 20px;
	}

	.pdf-warning-list {
		margin: 0;
		padding-left: 18px;
		color: #92400e;
		font-size: 13px;
		line-height: 20px;
	}

	.drawer-actions {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 8px;
	}

	.drawer-actions .btn:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}

	:root[data-theme='dark'] .dossier-topline span:last-child,
	:root[data-theme='dark'] .dossier-title-row h2,
	:root[data-theme='dark'] .dossier-section-heading h3,
	:root[data-theme='dark'] .aside-card h3,
	:root[data-theme='dark'] .comparison-panel h4,
	:root[data-theme='dark'] .chart-panel h4,
	:root[data-theme='dark'] .material-graph-column h4,
	:root[data-theme='dark'] .material-graph-node strong,
	:root[data-theme='dark'] .material-graph-detail h4,
	:root[data-theme='dark'] .material-graph-evidence strong,
	:root[data-theme='dark'] .detail-drawer h3,
	:root[data-theme='dark'] .dossier-table th,
	:root[data-theme='dark'] .dossier-table td,
	:root[data-theme='dark'] .paper-mini-card span,
	:root[data-theme='dark'] .chart-bar strong,
	:root[data-theme='dark'] .chart-labels,
	:root[data-theme='dark'] .narrative-card h3,
	:root[data-theme='dark'] .narrative-finding h4,
	:root[data-theme='dark'] .narrative-metrics strong,
	:root[data-theme='dark'] .best-value-card strong,
	:root[data-theme='dark'] .narrative-comparison-card strong,
	:root[data-theme='dark'] .detail-drawer dd,
	:root[data-theme='dark'] .pdf-data dd {
		color: var(--text-primary);
	}

	:root[data-theme='dark'] .dossier-tabs,
	:root[data-theme='dark'] .dossier-state-card,
	:root[data-theme='dark'] .dossier-card,
	:root[data-theme='dark'] .aside-card,
	:root[data-theme='dark'] .detail-drawer,
	:root[data-theme='dark'] .paper-mini-card,
	:root[data-theme='dark'] .narrative-metrics div,
	:root[data-theme='dark'] .best-value-card,
	:root[data-theme='dark'] .narrative-comparison-card div,
	:root[data-theme='dark'] .narrative-finding,
	:root[data-theme='dark'] .material-graph-column,
	:root[data-theme='dark'] .material-graph-node,
	:root[data-theme='dark'] .material-graph-detail,
	:root[data-theme='dark'] .mini-chart {
		border-color: var(--border-default);
		background: var(--surface-card);
	}

	:root[data-theme='dark'] .dossier-tabs button.active,
	:root[data-theme='dark'] .dossier-table th,
	:root[data-theme='dark'] .detail-drawer__header button {
		background: rgba(120, 140, 180, 0.16);
	}

	:root[data-theme='dark'] .dossier-table-wrapper,
	:root[data-theme='dark'] .dossier-table th,
	:root[data-theme='dark'] .dossier-table td {
		border-color: var(--border-default);
	}

	:root[data-theme='dark'] .dossier-header p,
	:root[data-theme='dark'] .dossier-section-heading p,
	:root[data-theme='dark'] .dossier-table-note,
	:root[data-theme='dark'] .comparison-panel > p,
	:root[data-theme='dark'] .chart-caption,
	:root[data-theme='dark'] .narrative-lede,
	:root[data-theme='dark'] .narrative-section-heading p,
	:root[data-theme='dark'] .narrative-finding p,
	:root[data-theme='dark'] .material-graph-node small,
	:root[data-theme='dark'] .material-graph-detail p,
	:root[data-theme='dark'] .empty-value,
	:root[data-theme='dark'] .empty-copy,
	:root[data-theme='dark'] .empty-cell {
		color: var(--text-secondary);
	}

	@media (max-width: 1080px) {
		.dossier-layout,
		.trend-grid {
			grid-template-columns: 1fr;
		}

		.material-graph-map {
			grid-template-columns: repeat(5, minmax(170px, 1fr));
		}

		.dossier-aside {
			position: static;
			grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		}
	}

	@media (max-width: 760px) {
		.dossier-header,
		.dossier-header__actions {
			display: grid;
			justify-content: stretch;
		}

		.dossier-header__actions .btn,
		.drawer-actions .btn {
			width: 100%;
		}

		.comparison-bars {
			grid-template-columns: 1fr;
		}
	}
</style>
