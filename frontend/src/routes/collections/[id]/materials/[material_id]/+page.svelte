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
		createMaterialReport,
		fetchMaterialReport,
		fetchMaterialResearchView,
		formatEvidenceBackedValue,
		formatShortIdentifier,
		type EvidenceBackedValue,
		type EvidenceReference,
		type MaterialReportArtifact,
		type MaterialReportDocument,
		type MaterialReportPerformanceResult,
		type MaterialReportStateChain,
		type MaterialPaperCoverage,
		type MaterialProfile,
		type PropertySummary,
		type SampleMatrixColumn,
		type SampleMatrixRow
	} from '../../../../_shared/researchView';

	type Translate = (key: string, vars?: Record<string, string | number>) => string;

	type MaterialDossierTab = 'structured' | 'narrative';

	type MaterialReportMarkdownInline =
		| { type: 'text'; text: string }
		| { type: 'citation'; id: string };

	type MaterialReportMarkdownTable = {
		headers: MaterialReportMarkdownInline[][];
		rows: MaterialReportMarkdownInline[][][];
	};

	type MaterialReportMarkdownBlock =
		| { type: 'heading'; level: number; key: string; text: string; anchor: string }
		| { type: 'paragraph'; key: string; parts: MaterialReportMarkdownInline[] }
		| { type: 'list'; key: string; ordered: boolean; items: MaterialReportMarkdownInline[][] }
		| { type: 'table'; key: string; table: MaterialReportMarkdownTable }
		| { type: 'code'; key: string; text: string }
		| { type: 'quote'; key: string; parts: MaterialReportMarkdownInline[] }
		| { type: 'rule'; key: string };

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

	type ChainEntry = {
		key: string;
		label: string;
		value: string;
	};

	type ParameterChainMetric = {
		key: string;
		supportedValue: SupportedValue;
		isBest: boolean;
	};

	type EvidenceCodeSummary = {
		visibleLabels: string[];
		hiddenCount: number;
		title: string;
	};

	type BestParameterChain = {
		key: string;
		row: SampleMatrixRow;
		sampleLabel: string;
		scoreLabel: string;
		background: string;
		processEntries: ChainEntry[];
		testConditionEntries: ChainEntry[];
		metrics: ParameterChainMetric[];
		comparisonSummary: string;
		notLeadingProperties: string[];
		evidenceCodes: string[];
		sourceLocation: string;
	};

	type MaterialProblemCard = {
		key: string;
		title: string;
		body: string;
		values: SupportedValue[];
		status: string;
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
	const MAX_PERFORMANCE_ROWS = 10;
	const MAX_MATRIX_EVIDENCE_LABELS = 3;
	const PROCESS_SUMMARY_KEYS = [
		'energy density',
		'volumetric energy density',
		'laser energy density (j/ mm 3 )',
		'scan speed (mm/s)',
		'laser power',
		'build platform conditions',
		'type of heat treatment',
		'post treatment summary',
		'scan strategy'
	].map(processAlias);
	const TEST_CONDITION_HINTS = [
		'test',
		'condition',
		'environment',
		'electrolyte',
		'solution',
		'strain',
		'loading',
		'frequency',
		'specimen',
		'surface',
		'temperature',
		'corrosion',
		'medium',
		'ph'
	];
	const RESULT_CONTEXT_HINTS = [
		'density',
		'hardness',
		'strength',
		'elongation',
		'potential',
		'current',
		'resistance',
		'defect',
		'grain',
		'melt pool'
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
	let materialReport: MaterialReportArtifact | null = null;
	let materialReportLoading = false;
	let materialReportError = '';
	let loading = false;
	let error = '';
	let loadedKey = '';
	let activeDossierTab: MaterialDossierTab = 'structured';

	$: collectionId = $page.params.id ?? '';
	$: materialId = $page.params.material_id ?? '';
	$: loadKey = `${collectionId}:${materialId}`;
	$: sampleRows = materialProfile?.sample_matrix.rows ?? [];
	$: reportPackage = materialProfile?.report_package ?? null;
	$: materialReportReady =
		materialReport?.markdown &&
		(materialReport.status === 'ready' || materialReport.status === 'ready_with_warnings');
	$: reportDocument =
		materialReportReady && materialReport
			? materialReportDocumentFromArtifact(materialReport)
			: (reportPackage?.document ?? null);
	$: reportDocumentBlocks = reportDocument ? parseMaterialReportMarkdown(reportDocument) : [];
	$: reportChains = reportPackage?.representative_states?.length
		? reportPackage.representative_states
		: (reportPackage?.material_state_chains ?? []);
	$: sampleColumns = sampleMatrixColumns(materialProfile, sampleRows);
	$: propertySummaries = materialProfile?.measured_properties ?? [];
	$: propertyColumns = materialPropertyColumns(materialProfile, sampleRows, sampleColumns, $t);
	$: focusedSampleRows = focusedRowsForColumns(sampleRows, propertyColumns);
	$: performanceRows = materialPerformanceRows(
		focusedSampleRows,
		propertyColumns,
		bestParameterChains,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId,
		$t
	);
	$: evidenceCodeMap = buildEvidenceCodeMap(focusedSampleRows, propertyColumns, propertySummaries);
	$: evidenceRows = buildEvidenceRows(
		focusedSampleRows,
		propertyColumns,
		evidenceCodeMap,
		collectionId,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId,
		reportPackage
	);
	$: processSummary = buildProcessSummary(focusedSampleRows, $t);
	$: comparisonRows = buildComparisonRows(focusedSampleRows, propertyColumns, processSummary, $t);
	$: trendRows = trendComparisonRows(comparisonRows);
	$: summaryTrendValues = summarySupportedValues(
		propertySummaries,
		propertyColumns,
		evidenceCodeMap,
		materialProfile?.canonical_name ?? materialId,
		$t
	).slice(0, 4);
	$: keyFindings = buildKeyFindings(
		focusedSampleRows,
		propertyColumns,
		processSummary,
		evidenceCodeMap,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId
	);
	$: bestParameterChains = buildBestParameterChains(
		materialProfile,
		focusedSampleRows,
		propertyColumns,
		evidenceCodeMap,
		$t
	);
	$: bestPropertyValues = buildBestPropertyValues(
		focusedSampleRows,
		propertyColumns,
		evidenceCodeMap,
		$t,
		propertySummaries,
		materialProfile?.canonical_name ?? materialId
	);
	$: materialProblemCards = buildMaterialProblemCards(bestPropertyValues, summaryTrendValues, $t);
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
		resetMaterialReportState();
		void loadMaterialPage();
	}
	$: pdfReportReady = pdfReport?.status === 'ready' || pdfReport?.status === 'ready_with_warnings';
	$: pdfReportGenerating = pdfReport?.status === 'generating';
	$: pdfReportBusy = pdfReportLoading || pdfReportGenerating;

	onDestroy(clearReportPoll);

	async function loadMaterialPage() {
		await loadMaterialProfile();
		await loadMaterialReportStatus();
	}

	async function loadMaterialProfile() {
		loading = true;
		error = '';
		selectedEvidence = null;
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

	async function loadMaterialReportStatus() {
		if (!collectionId || !materialId) return;
		const requestedCollection = collectionId;
		const requestedMaterial = materialId;
		materialReportLoading = true;
		materialReportError = '';
		try {
			const report = await fetchMaterialReport(requestedCollection, requestedMaterial);
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			materialReport = report;
		} catch (err) {
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			if (isHttpStatusError(err, 404)) {
				materialReport = null;
			} else {
				materialReportError = errorMessage(err);
			}
		} finally {
			if (requestedCollection === collectionId && requestedMaterial === materialId) {
				materialReportLoading = false;
			}
		}
	}

	async function generateMaterialReport(forceRegenerate = false) {
		if (!collectionId || !materialId || materialReportLoading) return;
		const requestedCollection = collectionId;
		const requestedMaterial = materialId;
		materialReportLoading = true;
		materialReportError = '';
		try {
			const report = await createMaterialReport(requestedCollection, requestedMaterial, {
				language: 'zh',
				force_regenerate: forceRegenerate
			});
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			materialReport = report;
		} catch (err) {
			if (requestedCollection !== collectionId || requestedMaterial !== materialId) return;
			materialReportError = errorMessage(err);
		} finally {
			if (requestedCollection === collectionId && requestedMaterial === materialId) {
				materialReportLoading = false;
			}
		}
	}

	function resetMaterialReportState() {
		materialReport = null;
		materialReportLoading = false;
		materialReportError = '';
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

	function cleanDisplayLabel(value: string) {
		return value
			.replace(/\bTable\s+\d+\s*(?:\([^)]*\))?\s*>\s*/gi, '')
			.replace(/\s+/g, ' ')
			.trim();
	}

	function cleanSampleLabel(value: string) {
		return value
			.replace(/\(\s+/g, '(')
			.replace(/\s+\)/g, ')')
			.replace(/\s*\/\s*/g, '/')
			.replace(/\s+/g, ' ')
			.trim();
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
		if (selected.length >= 5) return selected.slice(0, 5);

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
			if (selected.length >= 5) return selected.slice(0, 5);
		}
		if (selected.length) return selected.slice(0, 5);

		for (const key of valueKeys) {
			if (used.has(key)) continue;
			selected.push({
				key,
				label: labelFromColumn(key, columns, translate),
				shortLabel: labelFromColumn(key, columns, translate),
				unit: columns.find((item) => item.key === key)?.unit ?? null
			});
			if (selected.length >= 5) return selected.slice(0, 5);
		}

		return selected.slice(0, 5);
	}

	function rowHasAnyColumnValue(row: SampleMatrixRow, columns: PropertyColumn[]) {
		return columns.some((column) => Boolean(row.values[column.key]));
	}

	function focusedRowsForColumns(rows: SampleMatrixRow[], columns: PropertyColumn[]) {
		if (!columns.length) return rows;
		const focused = rows.filter((row) => rowHasAnyColumnValue(row, columns));
		return focused.length ? focused : rows;
	}

	function processLabel(key: string, translate: Translate) {
		const cleanedKey = cleanDisplayLabel(key);
		const alias = processAlias(cleanedKey);
		if (alias === 'energy_density')
			return translate('research.materialDossier.process.energy_density_j_mm3');
		if (alias === 'scan_speed')
			return translate('research.materialDossier.process.scan_speed_mm_s');
		if (alias === 'laser_power') return translate('research.materialDossier.process.laser_power_w');
		if (alias === 'heat_treatment')
			return translate('research.materialDossier.process.post_treatment_summary');
		if (alias === 'preheat')
			return translate('research.materialDossier.process.preheat_temperature_c');
		if (alias === 'scan_strategy')
			return translate('research.materialDossier.process.scan_strategy');
		const label = translate(`research.materialDossier.process.${key}`);
		return label.startsWith('research.') ? cleanedKey.replace(/_/g, ' ') : label;
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
		const unit = processUnitForKey(key);
		return unit ? `${value} ${unit}` : value;
	}

	function processUnitForKey(key: string) {
		if (PROCESS_UNITS[key]) return PROCESS_UNITS[key];
		const alias = processAlias(cleanDisplayLabel(key));
		if (alias === 'energy_density') return 'J/mm3';
		if (alias === 'laser_power') return 'W';
		if (alias === 'scan_speed') return 'mm/s';
		if (alias === 'preheat') return 'C';
		return null;
	}

	function isMainProcessKey(key: string) {
		return PROCESS_SUMMARY_KEYS.includes(processAlias(key));
	}

	function mainProcessKeys(rows: SampleMatrixRow[]) {
		const selected: string[] = [];
		const aliases = new Set<string>();
		const keys = Array.from(
			new Set(rows.flatMap((row) => Object.keys(row.process_context)))
		).filter((key) => isMainProcessKey(key) && rows.some((row) => processValue(row, key) !== '--'));
		for (const key of keys) {
			const alias = processAlias(key);
			if (aliases.has(alias)) continue;
			aliases.add(alias);
			selected.push(key);
		}
		return selected.slice(0, 3);
	}

	function processAlias(key: string) {
		const normalized = key.toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
		if (normalized.includes('energy density')) return 'energy_density';
		if (normalized.includes('scan speed')) return 'scan_speed';
		if (normalized.includes('laser power')) return 'laser_power';
		if (normalized.includes('heat treatment') || normalized.includes('post treatment')) {
			return 'heat_treatment';
		}
		if (normalized.includes('preheat') || normalized.includes('build platform')) return 'preheat';
		if (normalized.includes('scan strategy')) return 'scan_strategy';
		return normalized;
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
		const rawLabel = cleanSampleLabel(row.sample_label || row.sample_id || '');
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
			const parts = summary.changedKeys
				.map((key) => {
					const value = processValueWithUnit(row, key);
					if (value === '--') return '';
					return `${processLabel(key, translate)} = ${value}`;
				})
				.filter(Boolean);
			if (parts.length) return parts.join('; ');
		}
		if (row.variable_axis && row.variable_value !== null) {
			return `${row.variable_axis} = ${row.variable_value}`;
		}
		return sampleConditionLabel(row, translate) || '--';
	}

	function processBrief(row: SampleMatrixRow) {
		const keys = mainProcessKeys([row]);
		const parts = (keys.length ? keys : PROCESS_BRIEF_KEYS)
			.slice(0, 3)
			.map((key) => processValueWithUnit(row, key))
			.filter((value) => value !== '--');
		return parts.join(' · ') || '--';
	}

	function buildProcessSummary(rows: SampleMatrixRow[], translate: Translate): ProcessSummary {
		const keys = mainProcessKeys(rows);
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
		const visibleChangedKeys = changedKeys.slice(0, 3);
		const visibleChangedLabels = changedLabels.slice(0, 3);

		return {
			controlledKeys,
			controlledLabels,
			changedKeys: visibleChangedKeys,
			changedLabels: visibleChangedLabels,
			changedVariable:
				visibleChangedLabels[0] || translate('research.materialDossier.comparison.defaultVariable')
		};
	}

	function numericValue(value: EvidenceBackedValue | undefined) {
		if (!value) return null;
		const raw = value.normalized_value ?? value.value;
		if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
		if (typeof raw === 'string' && raw.trim()) {
			const text = raw.trim();
			if (!/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(text)) return null;
			const parsed = Number(text);
			if (Number.isFinite(parsed)) return parsed;
		}
		const display = formatEvidenceBackedValue(value).trim();
		if (
			!/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?\s*(?:%|mpa|gpa|hv|j\/mm3|j\/mm³|mm\/s|°c|c|ppm|um|µm)?$/i.test(
				display
			)
		) {
			return null;
		}
		const match = display.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/i);
		if (!match) return null;
		const parsed = Number(match[0]);
		return Number.isFinite(parsed) ? parsed : null;
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

	function summaryTrendText(values: SupportedValue[]) {
		return values
			.map((value) => `${value.property}: ${value.displayValue} (${value.evidenceCode})`)
			.join('; ');
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

	function bestValueMap(rows: SampleMatrixRow[], columns: PropertyColumn[]) {
		return new Map(
			columns
				.map((column) => {
					const best = bestValueForColumn(rows, column);
					return best ? [column.key, best] : null;
				})
				.filter((item): item is [string, NonNullable<ReturnType<typeof bestValueForColumn>>] =>
					Boolean(item)
				)
		);
	}

	function comparableValueCount(row: SampleMatrixRow, columns: PropertyColumn[]) {
		return columns.filter((column) => numericValue(row.values[column.key]) !== null).length;
	}

	function rowLeaderCount(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		bestByColumn: Map<string, NonNullable<ReturnType<typeof bestValueForColumn>>>
	) {
		return columns.filter((column) => {
			const best = bestByColumn.get(column.key);
			return Boolean(best && best.row.row_id === row.row_id);
		}).length;
	}

	function rowPerformanceScore(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		bestByColumn: Map<string, NonNullable<ReturnType<typeof bestValueForColumn>>>
	) {
		return (
			rowLeaderCount(row, columns, bestByColumn) * 100 +
			comparableValueCount(row, columns) * 10 +
			(row.evidence_refs.length ? 1 : 0)
		);
	}

	function bestRowsByCompositeScore(rows: SampleMatrixRow[], columns: PropertyColumn[]) {
		const bestByColumn = bestValueMap(rows, columns);
		return rows
			.map((row, index) => ({
				row,
				index,
				score: rowPerformanceScore(row, columns, bestByColumn)
			}))
			.filter((item) => rowLeaderCount(item.row, columns, bestByColumn) > 0)
			.sort((first, second) => second.score - first.score || first.index - second.index)
			.slice(0, 3);
	}

	function processEntryLabel(key: string, translate: Translate) {
		return processLabel(key, translate);
	}

	function hasDisplayValue(value: unknown) {
		if (value === null || value === undefined) return false;
		const text = String(value).trim();
		return Boolean(text && text !== '-' && text !== '--');
	}

	function chainEntryAlias(entry: ChainEntry) {
		return `${processAlias(entry.label)}:${normalizeForMatch(entry.value)}`;
	}

	function processChainEntries(row: SampleMatrixRow, translate: Translate): ChainEntry[] {
		const entries = Object.entries(row.process_context)
			.filter(([, value]) => hasDisplayValue(value))
			.filter(([key]) => !isLikelyTestConditionKey(key))
			.map(([key]) => ({
				key,
				label: processEntryLabel(key, translate),
				value: processValueWithUnit(row, key)
			}))
			.filter((entry) => entry.value !== '--');

		const preferred = entries.filter((entry) =>
			[...PROCESS_SUMMARY_KEYS, ...PROCESS_BRIEF_KEYS.map(processAlias)].includes(
				processAlias(entry.key)
			)
		);
		const selected = preferred.length ? preferred : entries;
		return uniqueChainEntries(selected).slice(0, 6);
	}

	function isLikelyTestConditionKey(key: string) {
		const normalized = key.toLowerCase().replace(/_/g, ' ');
		if (normalized.includes('build platform')) return false;
		return TEST_CONDITION_HINTS.some((hint) => normalized.includes(hint));
	}

	function isLikelyResultContextKey(key: string) {
		const normalized = key.toLowerCase().replace(/_/g, ' ');
		if (normalized.includes('energy density')) return false;
		return RESULT_CONTEXT_HINTS.some((hint) => normalized.includes(hint));
	}

	function testConditionEntries(row: SampleMatrixRow, translate: Translate): ChainEntry[] {
		const processAliases = new Set(processChainEntries(row, translate).map(chainEntryAlias));
		const fromTestConditions = Object.entries(row.test_condition ?? {})
			.filter(([, value]) => hasDisplayValue(value))
			.filter(([key, value]) => isDisplayableConditionEntry(key, value))
			.map(([key, value]) => ({
				key: `test:${key}`,
				label: processEntryLabel(key, translate),
				value: String(value)
			}))
			.filter((entry) => !processAliases.has(chainEntryAlias(entry)));
		const fromProcessContext = Object.entries(row.process_context)
			.filter(([, value]) => hasDisplayValue(value))
			.filter(([key]) => isLikelyTestConditionKey(key))
			.map(([key]) => ({
				key: `process:${key}`,
				label: processEntryLabel(key, translate),
				value: processValueWithUnit(row, key)
			}))
			.filter((entry) => entry.value !== '--');
		return uniqueChainEntries([...fromTestConditions, ...fromProcessContext]).slice(0, 4);
	}

	function isDisplayableConditionEntry(key: string, value: unknown) {
		const normalized = key.toLowerCase().replace(/_/g, ' ').trim();
		if (normalized === 'details' || normalized === 'detail' || normalized === 'description') {
			return false;
		}
		if (Array.isArray(value)) return value.length > 0 && value.join(', ').length <= 120;
		return String(value).length <= 120;
	}

	function uniqueChainEntries(entries: ChainEntry[]) {
		const seen = new Set<string>();
		return entries.filter((entry) => {
			const key = chainEntryAlias(entry);
			if (seen.has(key)) return false;
			seen.add(key);
			return true;
		});
	}

	function chainBackgroundProcessText(row: SampleMatrixRow, translate: Translate) {
		const entries = processChainEntries(row, translate).filter(
			(entry) => !isLikelyResultContextKey(entry.label)
		);
		if (entries.length) {
			return joinedList(
				entries.slice(0, 3).map((entry) => `${entry.label} ${entry.value}`),
				translate('research.materialDossier.narrative.unspecifiedProcess')
			);
		}
		return translate('research.materialDossier.narrative.unspecifiedProcess');
	}

	function sourceLocationForValue(value: SupportedValue) {
		const ref = value.value.evidence_refs[0];
		return ref?.locator || value.evidenceCode || '--';
	}

	function sourceLocationForValues(values: SupportedValue[]) {
		const locations = uniqueList(
			values.map(sourceLocationForValue).filter((value) => value !== '--')
		);
		return locations.slice(0, 3).join(', ') || '--';
	}

	function reportContextEntries(
		context: Record<string, string>,
		translate: Translate
	): ChainEntry[] {
		return Object.entries(context)
			.filter(([, value]) => hasDisplayValue(value))
			.map(([key, value]) => ({
				key,
				label: processEntryLabel(key, translate),
				value: String(value)
			}))
			.slice(0, 8);
	}

	function reportResultLabel(result: MaterialReportPerformanceResult) {
		if (result.display_value) return result.display_value;
		if (result.value !== null && result.value !== undefined) {
			return result.unit ? `${result.value} ${result.unit}` : String(result.value);
		}
		return '--';
	}

	function reportEvidenceCodes(refs: EvidenceReference[], codeMap: Map<string, string>): string[] {
		return uniqueList(
			refs.map((ref) => evidenceCode(ref, codeMap)).filter((code) => code !== '--')
		);
	}

	function reportChainEvidenceCodes(
		chain: MaterialReportStateChain,
		codeMap: Map<string, string>
	): string[] {
		return reportEvidenceCodes(
			[
				...chain.source_evidence,
				...chain.performance_results.flatMap((result) => result.evidence_refs)
			],
			codeMap
		);
	}

	function reportChainSourceLocation(chain: MaterialReportStateChain) {
		const locations = uniqueList(
			[
				...chain.source_evidence,
				...chain.performance_results.flatMap((result) => result.evidence_refs)
			]
				.map((ref) => ref.locator || '')
				.filter(Boolean)
		);
		return locations.slice(0, 3).join(', ') || '--';
	}

	function materialReportDocumentFromArtifact(
		report: MaterialReportArtifact
	): MaterialReportDocument {
		return {
			schema_version: 'material_report_document.v1',
			status: report.status === 'ready_with_warnings' ? 'partial' : 'ready',
			title: report.title,
			markdown: report.markdown ?? '',
			citations: reportPackage?.document?.citations ?? {},
			outline: materialReportOutline(report.markdown ?? ''),
			warnings: [],
			evidence_appendix: reportPackage?.document?.evidence_appendix ??
				reportPackage?.evidence_appendix ?? {
					sample_matrix_row_count: 0,
					property_count: 0,
					evidence_count: 0,
					source_table_count: 0
				}
		};
	}

	function materialReportOutline(markdown: string) {
		return markdown
			.split(/\r?\n/)
			.map((line) => /^(#{1,3})\s+(.+)$/.exec(line.trim()))
			.filter((match): match is RegExpExecArray => Boolean(match))
			.map((match) => ({
				level: match[1].length,
				title: match[2].trim(),
				anchor: match[2]
					.trim()
					.toLowerCase()
					.replace(/[^a-z0-9\u4e00-\u9fff]+/g, '-')
					.replace(/^-|-$/g, '')
			}));
	}

	function humanizeStatus(value: string) {
		return value.replace(/_/g, ' ');
	}

	function reportReferenceCodes(
		refs: EvidenceReference[],
		codeMap: Map<string, string>,
		limit = 5
	) {
		return reportEvidenceCodes(refs, codeMap).slice(0, limit);
	}

	function parseMaterialReportMarkdown(
		document: MaterialReportDocument
	): MaterialReportMarkdownBlock[] {
		const blocks: MaterialReportMarkdownBlock[] = [];
		let listItems: MaterialReportMarkdownInline[][] = [];
		let listOrdered = false;
		let tableLines: string[] = [];
		let codeLines: string[] = [];
		let inCodeBlock = false;
		const flushList = () => {
			if (!listItems.length) return;
			blocks.push({
				type: 'list',
				key: `list:${blocks.length}`,
				ordered: listOrdered,
				items: listItems
			});
			listItems = [];
			listOrdered = false;
		};
		const flushTable = () => {
			if (tableLines.length >= 2) {
				blocks.push({
					type: 'table',
					key: `table:${blocks.length}`,
					table: parseMaterialReportTable(tableLines, document)
				});
			}
			tableLines = [];
		};
		const flushCode = () => {
			if (!codeLines.length) return;
			blocks.push({
				type: 'code',
				key: `code:${blocks.length}`,
				text: codeLines.join('\n')
			});
			codeLines = [];
		};

		for (const line of document.markdown.split('\n')) {
			const text = line.trim();
			if (/^```/.test(text)) {
				if (inCodeBlock) {
					flushCode();
					inCodeBlock = false;
				} else {
					flushList();
					flushTable();
					inCodeBlock = true;
				}
				continue;
			}
			if (inCodeBlock) {
				codeLines.push(line.replace(/\s+$/g, ''));
				continue;
			}
			if (!text) {
				flushList();
				flushTable();
				continue;
			}
			if (/^-{3,}$/.test(text)) {
				flushList();
				flushTable();
				blocks.push({ type: 'rule', key: `rule:${blocks.length}` });
				continue;
			}
			if (isMaterialReportTableLine(text)) {
				flushList();
				tableLines.push(text);
				continue;
			}
			flushTable();
			const heading = /^(#{1,3})\s+(.+)$/.exec(text);
			if (heading) {
				flushList();
				blocks.push({
					type: 'heading',
					level: heading[1].length,
					key: `heading:${blocks.length}`,
					text: heading[2],
					anchor: reportHeadingAnchor(document, heading[2])
				});
				continue;
			}
			const listItem = /^(-|\d+\.)\s+(.+)$/.exec(text);
			if (listItem) {
				const ordered = listItem[1].endsWith('.');
				if (listItems.length && listOrdered !== ordered) {
					flushList();
				}
				listOrdered = ordered;
				listItems.push(parseMaterialReportInline(listItem[2], document));
				continue;
			}
			const quote = /^>\s+(.+)$/.exec(text);
			if (quote) {
				flushList();
				blocks.push({
					type: 'quote',
					key: `quote:${blocks.length}`,
					parts: parseMaterialReportInline(quote[1], document)
				});
				continue;
			}
			flushList();
			blocks.push({
				type: 'paragraph',
				key: `paragraph:${blocks.length}`,
				parts: parseMaterialReportInline(text, document)
			});
		}
		if (inCodeBlock) flushCode();
		flushTable();
		flushList();
		return blocks;
	}

	function isMaterialReportTableLine(text: string) {
		return text.startsWith('|') && text.endsWith('|') && text.includes('|');
	}

	function isMaterialReportTableSeparator(text: string) {
		return /^\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|$/.test(text);
	}

	function parseMaterialReportTableLine(text: string) {
		return text
			.slice(1, -1)
			.split('|')
			.map((cell) => cell.trim());
	}

	function parseMaterialReportTable(
		lines: string[],
		document: MaterialReportDocument
	): MaterialReportMarkdownTable {
		const headerLine = lines[0] ?? '';
		const bodyLines = isMaterialReportTableSeparator(lines[1] ?? '')
			? lines.slice(2)
			: lines.slice(1);
		return {
			headers: parseMaterialReportTableLine(headerLine).map((cell) =>
				parseMaterialReportInline(cell, document)
			),
			rows: bodyLines.map((row) =>
				parseMaterialReportTableLine(row).map((cell) => parseMaterialReportInline(cell, document))
			)
		};
	}

	function parseMaterialReportInline(text: string, document: MaterialReportDocument) {
		const parts: MaterialReportMarkdownInline[] = [];
		const citationPattern = /\[(E\d{3,})\]/g;
		let cursor = 0;
		for (const match of text.matchAll(citationPattern)) {
			const index = match.index ?? 0;
			if (index > cursor) {
				parts.push({ type: 'text', text: text.slice(cursor, index) });
			}
			const citationId = match[1];
			if (document.citations[citationId]) {
				parts.push({ type: 'citation', id: citationId });
			} else {
				parts.push({ type: 'text', text: match[0] });
			}
			cursor = index + match[0].length;
		}
		if (cursor < text.length) {
			parts.push({ type: 'text', text: text.slice(cursor) });
		}
		return parts;
	}

	function reportHeadingAnchor(document: MaterialReportDocument, title: string) {
		return (
			document.outline.find((item) => item.title === title)?.anchor ||
			title
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, '-')
				.replace(/^-|-$/g, '')
		);
	}

	function reportDocumentNavItems(document: MaterialReportDocument) {
		return document.outline.filter((item) => item.level === 2).slice(0, 12);
	}

	function openReportCitation(document: MaterialReportDocument, citationId: string) {
		const ref = document.citations[citationId];
		if (!ref) return;
		const code = evidenceCode(ref, evidenceCodeMap);
		const row = evidenceRows.find((item) => item.code === code);
		if (row) {
			openEvidenceRow({
				...row,
				code: citationId,
				detail: {
					...row.detail,
					anchor: citationId
				}
			});
			return;
		}
		openEvidenceRow({
			key: `material-report:${citationId}`,
			code: citationId,
			claim: `${document.title} ${citationId}`,
			type: sourceTypeLabel(ref, $t),
			location: ref.locator || '--',
			confidence: confidenceScore(ref.confidence),
			href: evidenceHref(ref, collectionId),
			detail: {
				title: `${document.title} ${citationId}`,
				sample: document.title,
				source: paperTitle(ref),
				location: ref.locator || '--',
				anchor: citationId,
				confidence: confidenceLabel(ref.confidence, $t),
				excerpt: $t('research.materialDossier.evidence.contextUnavailable'),
				href: evidenceHref(ref, collectionId)
			}
		});
	}

	function tableHeaderLabel(parts: MaterialReportMarkdownInline[]) {
		const text = parts
			.map((part) => (part.type === 'text' ? part.text : part.id))
			.join('')
			.trim();
		return text || 'column';
	}

	function renderedTableHeaderLabel(table: MaterialReportMarkdownTable, index: number) {
		return tableHeaderLabel(table.headers[index] ?? []);
	}

	function chainMetricRows(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		codeMap: Map<string, string>,
		bestByColumn: Map<string, NonNullable<ReturnType<typeof bestValueForColumn>>>,
		translate: Translate
	): ParameterChainMetric[] {
		return columns
			.map((column) => {
				const value = row.values[column.key];
				if (!value || numericValue(value) === null) return null;
				return {
					key: `${row.row_id}:${column.key}`,
					supportedValue: supportedValue(row, column, value, codeMap, translate),
					isBest: bestByColumn.get(column.key)?.row.row_id === row.row_id
				};
			})
			.filter((item): item is ParameterChainMetric => item !== null);
	}

	function chainComparisonSummary(
		metrics: ParameterChainMetric[],
		translate: Translate,
		totalProperties: number
	) {
		const bestMetrics = metrics.filter((metric) => metric.isBest);
		if (bestMetrics.length) {
			return translate('research.materialDossier.chain.comparisonSummary', {
				best: bestMetrics
					.map(
						(metric) => `${metric.supportedValue.property} ${metric.supportedValue.displayValue}`
					)
					.join(', '),
				count: bestMetrics.length,
				total: totalProperties
			});
		}
		return translate('research.materialDossier.chain.comparisonNoLeader', {
			count: metrics.length,
			total: totalProperties
		});
	}

	function chainScoreLabel(
		metrics: ParameterChainMetric[],
		translate: Translate,
		totalProperties: number
	) {
		const bestCount = metrics.filter((metric) => metric.isBest).length;
		return translate('research.materialDossier.chain.scoreLabel', {
			best: bestCount,
			total: totalProperties
		});
	}

	function chainBackground(
		profile: MaterialProfile | null,
		row: SampleMatrixRow,
		translate: Translate
	) {
		const material = profile?.canonical_name || row.material || '--';
		const paper = row.document_id
			? materialPapers().find((item) => item.document_id === row.document_id)?.title
			: null;
		return translate('research.materialDossier.chain.backgroundText', {
			material,
			processes: chainBackgroundProcessText(row, translate),
			paper: paper || translate('research.materialDossier.chain.collectionScope')
		});
	}

	function buildBestParameterChains(
		profile: MaterialProfile | null,
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		codeMap: Map<string, string>,
		translate: Translate
	): BestParameterChain[] {
		if (!rows.length || !columns.length) return [];
		const bestByColumn = bestValueMap(rows, columns);
		return bestRowsByCompositeScore(rows, columns).map(({ row }, index) => {
			const metrics = chainMetricRows(row, columns, codeMap, bestByColumn, translate);
			const leadingProperties = metrics
				.filter((metric) => metric.isBest)
				.map((metric) => metric.supportedValue.property);
			const allProperties = metrics.map((metric) => metric.supportedValue.property);
			return {
				key: row.row_id,
				row,
				sampleLabel: sampleDisplayLabel(row, translate, index),
				scoreLabel: chainScoreLabel(metrics, translate, columns.length),
				background: chainBackground(profile, row, translate),
				processEntries: processChainEntries(row, translate),
				testConditionEntries: testConditionEntries(row, translate),
				metrics,
				comparisonSummary: chainComparisonSummary(metrics, translate, columns.length),
				notLeadingProperties: allProperties.filter(
					(property) => !leadingProperties.includes(property)
				),
				evidenceCodes: evidenceCodesForValues(metrics.map((metric) => metric.supportedValue)),
				sourceLocation: sourceLocationForValues(metrics.map((metric) => metric.supportedValue))
			};
		});
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
			test_condition: {},
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

	function materialPerformanceRows(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		chains: BestParameterChain[],
		summaries: PropertySummary[],
		materialName: string,
		translate: Translate
	): SampleMatrixRow[] {
		const selectedRows = highSignalPerformanceRows(rows, columns, chains);
		const summaryValues = summaries
			.map((summary) => {
				const column = summaryColumnForProperty(summary, columns);
				if (!column) return null;
				const value = propertySummaryValue(summary);
				if (!value.display_value || value.display_value === '--') return null;
				return { column, summary, value };
			})
			.filter((item): item is NonNullable<typeof item> => item !== null);
		if (!summaryValues.length || selectedRows.length) return selectedRows;
		const values = Object.fromEntries(summaryValues.map((item) => [item.column.key, item.value]));
		const evidenceRefs = summaryValues.flatMap((item) => item.value.evidence_refs);
		const warnings = summaryValues.flatMap((item) => item.summary.warnings);
		return [
			...selectedRows,
			{
				row_id: 'collection-summary',
				document_id: evidenceRefs[0]?.document_id ?? null,
				sample_id: 'collection-summary',
				sample_label: translate('research.materialDossier.table.collectionSummary'),
				material: materialName,
				process_context: {},
				test_condition: {},
				variable_axis: null,
				variable_value: null,
				values,
				evidence_refs: evidenceRefs,
				warnings
			}
		];
	}

	function highSignalPerformanceRows(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		chains: BestParameterChain[]
	) {
		if (rows.length <= MAX_PERFORMANCE_ROWS) {
			if (!columns.length) return rows;
			return rows.filter((row) => rowHasAnyColumnValue(row, columns));
		}
		const selected = new Map<string, SampleMatrixRow>();
		for (const chain of chains.slice(0, 3)) selected.set(chain.row.row_id, chain.row);
		for (const column of columns) {
			const best = bestValueForColumn(rows, column);
			if (best) selected.set(best.row.row_id, best.row);
		}
		for (const row of rows) {
			if (selected.size >= MAX_PERFORMANCE_ROWS) break;
			if (comparableValueCount(row, columns) >= 2) selected.set(row.row_id, row);
		}
		return rows.filter((row) => selected.has(row.row_id));
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
		for (const ref of Object.values(materialProfile?.report_package?.document?.citations ?? {})) {
			if (ref.evidence_ref_id && !ids.includes(ref.evidence_ref_id)) {
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
			paperDisplayName(materialPapers().find((paper) => paper.document_id === ref.document_id)) ||
			formatShortIdentifier(ref.document_id)
		);
	}

	function paperDisplayName(paper: MaterialPaperCoverage | undefined) {
		return (paper?.title || paper?.source_filename || '').replace(/\.pdf$/i, '');
	}

	function reportPaperTitle(paper: {
		title?: string | null;
		source_filename?: string | null;
		document_id: string;
	}) {
		return (
			paper.title ||
			paper.source_filename ||
			formatShortIdentifier(paper.document_id)
		).replace(/\.pdf$/i, '');
	}

	function paperForRow(row: SampleMatrixRow) {
		if (!row.document_id) return undefined;
		return materialPapers().find((paper) => paper.document_id === row.document_id);
	}

	function paperLabelForRow(row: SampleMatrixRow) {
		const name = paperDisplayName(paperForRow(row));
		if (!name) return formatShortIdentifier(row.document_id ?? '');
		return name.match(/\bP\d{3}\b/i)?.[0] ?? name;
	}

	function materialStateRole(chain: BestParameterChain, translate: Translate) {
		const text = normalizeForMatch(
			[
				chain.sampleLabel,
				...chain.metrics.map((metric) => metric.supportedValue.property),
				...chain.processEntries.map((entry) => `${entry.label} ${entry.value}`)
			].join(' ')
		);
		if (text.includes('odf') || text.includes('jeffrey') || text.includes('texture')) {
			return translate('research.materialDossier.state.roles.texture');
		}
		if (text.includes('hardness'))
			return translate('research.materialDossier.state.roles.hardness');
		if (text.includes('density') || text.includes('porosity')) {
			return translate('research.materialDossier.state.roles.densification');
		}
		if (text.includes('yield') || text.includes('tensile') || text.includes('elongation')) {
			return translate('research.materialDossier.state.roles.tensile');
		}
		return translate('research.materialDossier.state.roles.representative');
	}

	function materialStateTitle(chain: BestParameterChain, translate: Translate) {
		return `${paperLabelForRow(chain.row)} ${chain.sampleLabel}: ${materialStateRole(chain, translate)}`;
	}

	function materialStateSource(chain: BestParameterChain, translate: Translate) {
		const paper = paperDisplayName(paperForRow(chain.row));
		return paper || translate('research.materialDossier.chain.collectionScope');
	}

	function materialStateInterpretation(chain: BestParameterChain, translate: Translate) {
		const leading = chain.metrics.filter((metric) => metric.isBest);
		const observed = (leading.length ? leading : chain.metrics).slice(0, 3);
		const values = observed
			.map((metric) => `${metric.supportedValue.property} ${metric.supportedValue.displayValue}`)
			.join(', ');
		const boundary = chain.notLeadingProperties.length
			? translate('research.materialDossier.state.notGlobalBest', {
					properties: chain.notLeadingProperties.slice(0, 3).join(', ')
				})
			: translate('research.materialDossier.state.sourceBounded');
		return translate('research.materialDossier.state.interpretation', {
			values: values || translate('research.materialDossier.state.noValues'),
			boundary
		});
	}

	function valuesForProblem(values: SupportedValue[], role: string) {
		return values.filter((value) => {
			const text = normalizeForMatch(`${value.property} ${value.column.key}`);
			if (role === 'density') return text.includes('density') || text.includes('porosity');
			if (role === 'mechanical') {
				return (
					text.includes('hardness') ||
					text.includes('yield') ||
					text.includes('tensile') ||
					text.includes('elongation')
				);
			}
			if (role === 'texture') {
				return (
					text.includes('odf') ||
					text.includes('jeffrey') ||
					text.includes('predicted') ||
					text.includes('texture')
				);
			}
			return false;
		});
	}

	function problemBody(
		key: string,
		values: SupportedValue[],
		translate: Translate,
		fallbackKey: string
	) {
		if (!values.length) return translate(fallbackKey);
		return translate(`research.materialDossier.problems.${key}.body`, {
			values: values
				.slice(0, 3)
				.map((value) => `${value.sample}: ${value.property} ${value.displayValue}`)
				.join('; ')
		});
	}

	function buildMaterialProblemCards(
		bestValues: SupportedValue[],
		summaryValues: SupportedValue[],
		translate: Translate
	): MaterialProblemCard[] {
		const values = uniqueSupportedValues([...bestValues, ...summaryValues]);
		const densityValues = valuesForProblem(values, 'density');
		const mechanicalValues = valuesForProblem(values, 'mechanical');
		const textureValues = valuesForProblem(values, 'texture');
		return [
			{
				key: 'densification',
				title: translate('research.materialDossier.problems.densification.title'),
				body: problemBody(
					'densification',
					densityValues,
					translate,
					'research.materialDossier.problems.densification.empty'
				),
				values: densityValues.slice(0, 3),
				status: translate('research.materialDossier.problems.status.traceable')
			},
			{
				key: 'mechanical',
				title: translate('research.materialDossier.problems.mechanical.title'),
				body: problemBody(
					'mechanical',
					mechanicalValues,
					translate,
					'research.materialDossier.problems.mechanical.empty'
				),
				values: mechanicalValues.slice(0, 4),
				status: translate('research.materialDossier.problems.status.traceable')
			},
			{
				key: 'texture',
				title: translate('research.materialDossier.problems.texture.title'),
				body: problemBody(
					'texture',
					textureValues,
					translate,
					'research.materialDossier.problems.texture.empty'
				),
				values: textureValues.slice(0, 3),
				status: textureValues.length
					? translate('research.materialDossier.problems.status.traceable')
					: translate('research.materialDossier.problems.status.partial')
			},
			{
				key: 'unclosed',
				title: translate('research.materialDossier.problems.unclosed.title'),
				body: translate('research.materialDossier.problems.unclosed.body'),
				values: [],
				status: translate('research.materialDossier.problems.status.partial')
			}
		];
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
		materialName: string,
		reportPackage: MaterialProfile['report_package']
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
		for (const chain of reportPackage?.material_state_chains ?? []) {
			for (const ref of [
				...chain.source_evidence,
				...chain.performance_results.flatMap((result) => result.evidence_refs)
			]) {
				const code = evidenceCode(ref, codeMap);
				if (items.some((item) => item.code === code)) continue;
				const detail = {
					title: chain.material_state || chain.sample_label || chain.sample_id,
					sample: chain.sample_label || chain.sample_id,
					source: paperTitle(ref),
					location: ref.locator || '--',
					anchor: code,
					confidence: confidenceLabel(ref.confidence, translate),
					excerpt: translate('research.materialDossier.evidence.contextUnavailable'),
					href: evidenceHref(ref, collection)
				};
				items.push({
					key: `${chain.chain_id}:${ref.evidence_ref_id}`,
					code,
					claim: `${detail.sample} report-chain evidence`,
					type: sourceTypeLabel(ref, translate),
					location: detail.location,
					confidence: confidenceScore(ref.confidence),
					href: detail.href,
					detail
				});
			}
		}
		return items.slice(0, 8);
	}

	function rowEvidenceSummary(
		row: SampleMatrixRow,
		columns: PropertyColumn[],
		codeMap: Map<string, string>
	): EvidenceCodeSummary {
		const labels: string[] = [];
		for (const column of columns) {
			for (const ref of row.values[column.key]?.evidence_refs ?? []) {
				const label = evidenceCode(ref, codeMap);
				if (!labels.includes(label)) labels.push(label);
			}
		}
		const visibleLabels = labels.slice(0, MAX_MATRIX_EVIDENCE_LABELS);
		return {
			visibleLabels,
			hiddenCount: Math.max(0, labels.length - visibleLabels.length),
			title: labels.join(', ')
		};
	}

	function openEvidenceCode(code: string) {
		const row = evidenceRows.find((item) => item.code === code);
		if (row) openEvidenceRow(row);
	}

	function uniqueList(values: string[]) {
		return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
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
		const rows = focusedSampleRows.flatMap((row) =>
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
			<button
				class="btn btn--primary-light btn--small"
				type="button"
				disabled={materialReportLoading}
				on:click={() => generateMaterialReport(Boolean(materialReport))}
			>
				{materialReport
					? $t('research.materialDossier.report.regenerate')
					: $t('research.materialDossier.report.generate')}
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
					{#if reportDocument}
						<section
							id="material-report-document"
							class="dossier-card material-report-document-card"
						>
							<div class="material-report-reader-header">
								<div>
									<h3>{$t('research.materialDossier.report.documentTitle')}</h3>
									<p>
										{materialReportReady
											? $t('research.materialDossier.report.llmBody')
											: $t('research.materialDossier.report.draftBody')}
									</p>
								</div>
								<div class="material-report-actions">
									{#if materialReport}
										<span class="material-report-status"
											>{humanizeStatus(materialReport.status)}</span
										>
										{#if materialReport.model}
											<span class="material-report-status">{materialReport.model}</span>
										{/if}
									{:else}
										<span class="material-report-status">
											{$t('research.materialDossier.report.draftStatus')}
										</span>
									{/if}
									<button
										type="button"
										on:click={loadMaterialReportStatus}
										disabled={materialReportLoading}
									>
										{$t('research.materialDossier.report.refresh')}
									</button>
									<button
										type="button"
										on:click={() => generateMaterialReport(Boolean(materialReport))}
										disabled={materialReportLoading}
									>
										{materialReport
											? $t('research.materialDossier.report.regenerate')
											: $t('research.materialDossier.report.generate')}
									</button>
								</div>
							</div>
							{#if materialReport?.message}
								<p class="material-report-message">{materialReport.message}</p>
							{/if}
							{#if materialReportError}
								<p class="material-report-error" role="alert">{materialReportError}</p>
							{/if}
							<article class="material-report-markdown" aria-label={reportDocument.title}>
								{#each reportDocumentBlocks as block (block.key)}
									{#if block.type === 'heading'}
										{#if block.level === 1}
											<h3 id={block.anchor}>{block.text}</h3>
										{:else if block.level === 2}
											<h4 id={block.anchor}>{block.text}</h4>
										{:else}
											<h5 id={block.anchor}>{block.text}</h5>
										{/if}
									{:else if block.type === 'paragraph'}
										<p>
											{#each block.parts as part}
												{#if part.type === 'citation'}
													<button
														type="button"
														class="report-citation"
														on:click={() => openReportCitation(reportDocument, part.id)}
													>
														[{part.id}]
													</button>
												{:else}
													{part.text}
												{/if}
											{/each}
										</p>
									{:else if block.type === 'list'}
										<svelte:element this={block.ordered ? 'ol' : 'ul'}>
											{#each block.items as item}
												<li>
													{#each item as part}
														{#if part.type === 'citation'}
															<button
																type="button"
																class="report-citation"
																on:click={() => openReportCitation(reportDocument, part.id)}
															>
																[{part.id}]
															</button>
														{:else}
															{part.text}
														{/if}
													{/each}
												</li>
											{/each}
										</svelte:element>
									{:else if block.type === 'table'}
										<div class="report-table-scroll">
											<table>
												<thead>
													<tr>
														{#each block.table.headers as header}
															<th>
																{#each header as part}
																	{#if part.type === 'citation'}
																		<button
																			type="button"
																			class="report-citation"
																			on:click={() => openReportCitation(reportDocument, part.id)}
																		>
																			[{part.id}]
																		</button>
																	{:else}
																		{part.text}
																	{/if}
																{/each}
															</th>
														{/each}
													</tr>
												</thead>
												<tbody>
													{#each block.table.rows as row}
														<tr>
															{#each row as cell, index}
																<td data-label={renderedTableHeaderLabel(block.table, index)}>
																	{#each cell as part}
																		{#if part.type === 'citation'}
																			<button
																				type="button"
																				class="report-citation"
																				on:click={() => openReportCitation(reportDocument, part.id)}
																			>
																				[{part.id}]
																			</button>
																		{:else}
																			{part.text}
																		{/if}
																	{/each}
																</td>
															{/each}
														</tr>
													{/each}
												</tbody>
											</table>
										</div>
									{:else if block.type === 'code'}
										<pre><code>{block.text}</code></pre>
									{:else if block.type === 'quote'}
										<blockquote>
											{#each block.parts as part}
												{#if part.type === 'citation'}
													<button
														type="button"
														class="report-citation"
														on:click={() => openReportCitation(reportDocument, part.id)}
													>
														[{part.id}]
													</button>
												{:else}
													{part.text}
												{/if}
											{/each}
										</blockquote>
									{:else if block.type === 'rule'}
										<hr />
									{/if}
								{/each}
							</article>
						</section>
					{:else}
						<section id="material-report-overview" class="dossier-card report-overview-card">
							<div class="dossier-section-heading">
								<span class="section-number">1</span>
								<h3>{$t('research.materialDossier.sections.overview.title')}</h3>
								<p>
									{reportPackage?.executive_summary ||
										$t('research.materialDossier.sections.overview.body', {
											material: materialProfile.canonical_name,
											processes: joinedList(
												materialProfile.overview.process_families,
												$t('research.materialDossier.narrative.unspecifiedProcess')
											)
										})}
								</p>
							</div>
							<div class="report-stat-grid">
								<div>
									<strong>{reportPackage?.material_scope.source_paper_count || paperCount}</strong>
									<span>{$t('research.materialDossier.aside.sourcePapers')}</span>
								</div>
								<div>
									<strong>{reportPackage?.material_scope.sample_row_count || sampleCount}</strong>
									<span>{$t('research.overview.samples')}</span>
								</div>
								<div>
									<strong
										>{reportPackage?.evidence_appendix.property_count ||
											measuredPropertyCount}</strong
									>
									<span>{$t('research.overview.properties')}</span>
								</div>
								<div>
									<strong>{reportPackage?.material_scope.evidence_count || evidenceCount}</strong>
									<span>{$t('research.overview.evidence')}</span>
								</div>
							</div>
							{#if reportPackage?.key_findings.length}
								<div class="report-finding-list">
									{#each reportPackage.key_findings as finding (finding.finding_id)}
										<article class="report-finding">
											<h4>{finding.title}</h4>
											<p>{finding.body}</p>
											<div class="evidence-chip-row">
												{#each reportReferenceCodes(finding.evidence_refs, evidenceCodeMap) as code}
													<button
														type="button"
														class="evidence-chip"
														on:click={() => openEvidenceCode(code)}
													>
														{code}
													</button>
												{/each}
											</div>
										</article>
									{/each}
								</div>
							{/if}
							<div class="paper-contribution-grid">
								{#each (reportPackage?.paper_contributions?.length ? reportPackage.paper_contributions : materialPapers()).slice(0, 6) as paper (paper.document_id)}
									<a
										class="paper-contribution-card"
										href={resolve('/collections/[id]/documents/[document_id]', {
											id: collectionId,
											document_id: paper.document_id
										})}
									>
										<strong>{reportPaperTitle(paper)}</strong>
										<span>
											{paper.sample_count}
											{$t('research.overview.samples')} ·
											{joinedList(
												paper.measured_properties.slice(0, 3),
												$t('research.materialDossier.narrative.unspecifiedProperties')
											)}
										</span>
									</a>
								{:else}
									<p class="empty-copy">{$t('research.materialDossier.aside.noLiterature')}</p>
								{/each}
							</div>
						</section>

						{#if reportPackage?.thematic_sections.length}
							<section id="material-report-sections" class="dossier-card report-section-card">
								<div class="dossier-section-heading">
									<span class="section-number">2</span>
									<h3>{$t('research.materialDossier.report.sectionsTitle')}</h3>
									<p>{$t('research.materialDossier.report.sectionsBody')}</p>
								</div>
								<div class="report-section-list">
									{#each reportPackage.thematic_sections as section (section.section_id)}
										<article class="report-section">
											<strong class="report-section__title">
												{$t('research.materialDossier.report.sectionLabel', {
													title: section.title
												})}
											</strong>
											<p>{section.body}</p>
											{#if section.key_points.length}
												<ul>
													{#each section.key_points as point}
														<li>{point}</li>
													{/each}
												</ul>
											{/if}
											<div class="evidence-chip-row">
												{#each reportReferenceCodes(section.evidence_refs, evidenceCodeMap) as code}
													<button
														type="button"
														class="evidence-chip"
														on:click={() => openEvidenceCode(code)}
													>
														{code}
													</button>
												{/each}
											</div>
										</article>
									{/each}
								</div>
							</section>
						{/if}

						<section id="representative-material-states" class="dossier-card chain-card">
							<div class="dossier-section-heading">
								<span class="section-number">{reportPackage?.thematic_sections.length ? 3 : 2}</span
								>
								<h3>{$t('research.materialDossier.sections.chain.title')}</h3>
								<p>{$t('research.materialDossier.sections.chain.body')}</p>
							</div>

							<div class="chain-list">
								{#each reportChains as chain, index (chain.chain_id)}
									<article class="parameter-chain">
										<div class="parameter-chain__header">
											<div>
												<span class="chain-rank"
													>{$t('research.materialDossier.state.cardLabel', {
														index: index + 1
													})}</span
												>
												<h4>{chain.material_state || chain.sample_label || chain.sample_id}</h4>
												<p>{chain.material || materialProfile.canonical_name}</p>
											</div>
											<span class="chain-score">{confidenceLabel(chain.confidence, $t)}</span>
										</div>

										<div
											class="chain-steps"
											aria-label={$t('research.materialDossier.chain.stepsLabel')}
										>
											<div class="chain-step">
												<span>1</span>
												<strong>{$t('research.materialDossier.chain.processContext')}</strong>
												{#if reportContextEntries(chain.preparation_context, $t).length}
													<dl>
														{#each reportContextEntries(chain.preparation_context, $t) as entry (entry.key)}
															<div>
																<dt>{entry.label}</dt>
																<dd>{entry.value}</dd>
															</div>
														{/each}
													</dl>
												{:else}
													<p>{$t('research.materialDossier.chain.noProcessContext')}</p>
												{/if}
											</div>

											<div class="chain-step">
												<span>2</span>
												<strong>{$t('research.materialDossier.chain.testConditions')}</strong>
												{#if reportContextEntries(chain.test_conditions, $t).length}
													<dl>
														{#each reportContextEntries(chain.test_conditions, $t) as entry (entry.key)}
															<div>
																<dt>{entry.label}</dt>
																<dd>{entry.value}</dd>
															</div>
														{/each}
													</dl>
												{:else}
													<p>{$t('research.materialDossier.chain.noTestConditions')}</p>
												{/if}
											</div>

											<div class="chain-step chain-step--wide">
												<span>3</span>
												<strong>{$t('research.materialDossier.chain.results')}</strong>
												<div class="chain-metrics">
													{#each chain.performance_results as result (result.property)}
														<div class="chain-metric">
															<span>{result.property}</span>
															<strong>{reportResultLabel(result)}</strong>
															<small>
																{$t('research.materialDossier.chain.observed')}
																{#if result.condition}
																	· {result.condition}
																{/if}
															</small>
														</div>
													{/each}
												</div>
											</div>
										</div>

										<div class="chain-judgement">
											<div>
												<strong>{$t('research.materialDossier.chain.boundary')}</strong>
												{#if chain.comparability_boundary.length || chain.unresolved_fields.length}
													<p>
														{[
															...chain.comparability_boundary,
															...chain.unresolved_fields.map((field) => `${field} unresolved`)
														].join(' ')}
													</p>
												{:else}
													<p>{$t('research.materialDossier.chain.boundaryReady')}</p>
												{/if}
											</div>
											<div>
												<strong>{$t('research.materialDossier.chain.traceback')}</strong>
												<p>{reportChainSourceLocation(chain)}</p>
												<div class="evidence-chip-row">
													{#each reportChainEvidenceCodes(chain, evidenceCodeMap) as code}
														<button
															type="button"
															class="evidence-chip"
															on:click={() => openEvidenceCode(code)}
														>
															{code}
														</button>
													{:else}
														<span class="evidence-chip evidence-chip--muted">--</span>
													{/each}
												</div>
											</div>
										</div>
									</article>
								{:else}
									<p class="empty-copy">
										{reportPackage
											? $t('research.materialDossier.chain.empty')
											: $t('research.materialDossier.chain.packageUnavailable')}
									</p>
								{/each}
							</div>
						</section>
					{/if}

					{#if !reportDocument}
						<section id="material-problems" class="dossier-card material-problems-card">
							<div class="dossier-section-heading">
								<span class="section-number">3</span>
								<h3>{$t('research.materialDossier.sections.materialProblems.title')}</h3>
								<p>{$t('research.materialDossier.sections.materialProblems.body')}</p>
							</div>

							<div class="problem-grid">
								{#each materialProblemCards as problem (problem.key)}
									<article class="problem-card">
										<div class="problem-card__header">
											<h4>{problem.title}</h4>
											<span>{problem.status}</span>
										</div>
										<p>{problem.body}</p>
										{#if problem.values.length}
											<div class="finding-values">
												{#each problem.values as value (value.key)}
													<button type="button" on:click={() => openSupportedValue(value)}>
														<strong>{value.sample}</strong>
														<span>{value.property} = {value.displayValue}</span>
														<small>{value.evidenceCode}</small>
													</button>
												{/each}
											</div>
										{/if}
									</article>
								{/each}
							</div>
						</section>
					{/if}

					{#if !reportDocument}
						<section id="trend-comparison" class="dossier-card">
							<div class="dossier-section-heading">
								<span class="section-number">4</span>
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
															{#if summaryTrendValues.length}
																{$t('research.materialDossier.comparison.summaryOnly', {
																	values: summaryTrendText(summaryTrendValues)
																})}
															{:else}
																{$t('research.materialDossier.comparison.empty')}
															{/if}
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
										<p class="empty-copy">
											{#if summaryTrendValues.length}
												{$t('research.materialDossier.chart.summaryOnly', {
													values: summaryTrendText(summaryTrendValues)
												})}
											{:else}
												{$t('research.materialDossier.chart.empty')}
											{/if}
										</p>
									{/if}
								</div>
							</div>
						</section>
					{/if}

					{#if !reportDocument}
						<section id="performance-results" class="dossier-card">
							<div class="dossier-section-heading">
								<span class="section-number">5</span>
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
										{#each performanceRows as row, rowIndex (row.row_id)}
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
												<td>
													{#each [rowEvidenceSummary(row, propertyColumns, evidenceCodeMap)] as evidenceSummary}
														{#if evidenceSummary.visibleLabels.length}
															<div class="matrix-evidence-chips" title={evidenceSummary.title}>
																{#each evidenceSummary.visibleLabels as code}
																	<button
																		type="button"
																		class="evidence-chip"
																		on:click={() => openEvidenceCode(code)}
																	>
																		{code}
																	</button>
																{/each}
																{#if evidenceSummary.hiddenCount}
																	<span class="evidence-chip evidence-chip--muted">
																		+{evidenceSummary.hiddenCount} more
																	</span>
																{/if}
															</div>
														{:else}
															<span class="empty-value">--</span>
														{/if}
													{/each}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
							<p class="dossier-table-note">
								{$t('research.materialDossier.performance.summary', {
									samples: performanceRows.length,
									properties: propertyColumns.length
								})}
							</p>
						</section>
					{/if}

					{#if !reportDocument}
						<section id="evidence-locator" class="dossier-card">
							<div class="dossier-section-heading">
								<span class="section-number">6</span>
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
							<a
								class="footer-link"
								href={resolve('/collections/[id]/evidence', { id: collectionId })}
							>
								{$t('research.materialDossier.evidence.viewAll', { count: evidenceCount })}
							</a>
						</section>
					{/if}
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
									{#each focusedSampleRows.slice(0, 5) as row, rowIndex (row.row_id)}
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
											<button
												type="button"
												class="evidence-chip"
												on:click={() => openEvidenceCode(code)}
											>
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
						<a
							class="footer-link"
							href={resolve('/collections/[id]/evidence', { id: collectionId })}
						>
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
						{#if reportDocument}
							{#each reportDocumentNavItems(reportDocument) as item (item.anchor)}
								<a href={`#${item.anchor}`}>{item.title}</a>
							{/each}
						{:else}
							<a href="#material-report-overview"
								>1 {$t('research.materialDossier.sections.overview.title')}</a
							>
							<a href="#representative-material-states"
								>2 {$t('research.materialDossier.sections.chain.title')}</a
							>
							<a href="#material-problems"
								>3 {$t('research.materialDossier.sections.materialProblems.title')}</a
							>
							<a href="#trend-comparison"
								>4 {$t('research.materialDossier.sections.trends.title')}</a
							>
							<a href="#performance-results"
								>5 {$t('research.materialDossier.sections.performance.title')}</a
							>
							<a href="#evidence-locator"
								>6 {$t('research.materialDossier.sections.evidence.title')}</a
							>
						{/if}
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
					<li>{$t('research.materialDossier.sections.overview.title')}</li>
					<li>{$t('research.materialDossier.sections.chain.title')}</li>
					<li>{$t('research.materialDossier.sections.materialProblems.title')}</li>
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

	.btn:disabled {
		cursor: wait;
		opacity: 0.65;
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

	.finding-values {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
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

	.report-overview-card,
	.material-report-document-card,
	.material-problems-card {
		gap: 14px;
	}

	.material-report-document-card {
		padding: 0;
	}

	.material-report-reader-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		padding: 18px 24px;
		border-bottom: 1px solid #e2e8f0;
	}

	.material-report-reader-header > div:first-child {
		display: grid;
		gap: 5px;
		min-width: 0;
	}

	.material-report-reader-header h3 {
		margin: 0;
		color: #64748b;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
		text-transform: uppercase;
	}

	.material-report-reader-header p {
		margin: 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.material-report-actions {
		display: flex;
		flex: 0 0 auto;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
	}

	.material-report-actions button {
		min-height: 32px;
		border: 1px solid #dbe3ef;
		border-radius: 8px;
		padding: 6px 10px;
		background: #ffffff;
		color: #0f172a;
		cursor: pointer;
		font: inherit;
		font-size: 13px;
		font-weight: 750;
	}

	.material-report-actions button:disabled {
		cursor: wait;
		opacity: 0.65;
	}

	.material-report-status {
		display: inline-flex;
		align-items: center;
		min-height: 32px;
		border: 1px solid #dbe3ef;
		border-radius: 999px;
		padding: 0 9px;
		background: #f8fafc;
		color: #64748b;
		font-size: 12px;
		line-height: 16px;
	}

	.material-report-error {
		margin: 14px 24px 0;
		color: #b42318;
		font-size: 13px;
		line-height: 20px;
	}

	.material-report-message {
		margin: 14px 24px 0;
		color: #64748b;
		font-size: 13px;
		line-height: 20px;
	}

	.material-report-markdown {
		display: grid;
		gap: 12px;
		padding: 24px;
		color: #1e293b;
	}

	.material-report-markdown h3,
	.material-report-markdown h4,
	.material-report-markdown h5 {
		margin: 0;
		color: #0f172a;
		letter-spacing: 0;
	}

	.material-report-markdown h3 {
		font-size: 28px;
		font-weight: 850;
		line-height: 36px;
	}

	.material-report-markdown h4 {
		margin-top: 10px;
		padding-top: 14px;
		border-top: 1px solid #e2e8f0;
		font-size: 18px;
		font-weight: 800;
		line-height: 26px;
	}

	.material-report-markdown h5 {
		font-size: 15px;
		font-weight: 800;
		line-height: 22px;
	}

	.material-report-markdown p,
	.material-report-markdown li {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 23px;
		overflow-wrap: anywhere;
	}

	.material-report-markdown ul {
		display: grid;
		gap: 7px;
		margin: 0;
		padding-left: 20px;
	}

	.material-report-markdown ol {
		display: grid;
		gap: 7px;
		margin: 0;
		padding-left: 22px;
	}

	.material-report-markdown hr {
		width: 100%;
		margin: 6px 0;
		border: 0;
		border-top: 1px solid #e2e8f0;
	}

	.material-report-markdown blockquote {
		margin: 0;
		padding: 10px 12px;
		border-left: 3px solid #2563eb;
		background: #f8fbff;
		color: #334155;
		font-size: 14px;
		line-height: 23px;
	}

	.material-report-markdown pre {
		margin: 0;
		padding: 12px;
		overflow-x: auto;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #f8fafc;
		color: #0f172a;
		font-size: 13px;
		line-height: 21px;
	}

	.report-table-scroll {
		overflow-x: auto;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #ffffff;
	}

	.material-report-markdown table {
		width: 100%;
		border-collapse: collapse;
		min-width: 560px;
	}

	.material-report-markdown th,
	.material-report-markdown td {
		padding: 9px 11px;
		border-bottom: 1px solid #e2e8f0;
		text-align: left;
		vertical-align: top;
		color: #334155;
		font-size: 13px;
		line-height: 20px;
	}

	.material-report-markdown th {
		background: #f8fafc;
		color: #0f172a;
		font-weight: 800;
	}

	.material-report-markdown tr:last-child td {
		border-bottom: 0;
	}

	.report-citation {
		display: inline-flex;
		align-items: center;
		min-height: 22px;
		margin-left: 3px;
		padding: 0 6px;
		border: 1px solid #bfdbfe;
		border-radius: 6px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 850;
		line-height: 18px;
		cursor: pointer;
	}

	.report-citation:hover {
		border-color: #2563eb;
		background: #dbeafe;
	}

	.report-stat-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
	}

	.report-stat-grid div {
		display: grid;
		gap: 3px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #fbfdff;
	}

	.report-stat-grid strong {
		color: #0f172a;
		font-size: 20px;
		font-weight: 800;
		line-height: 28px;
	}

	.report-stat-grid span {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.paper-contribution-grid,
	.problem-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: 10px;
	}

	.paper-contribution-card,
	.problem-card {
		display: grid;
		gap: 8px;
		padding: 12px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		text-decoration: none;
	}

	.paper-contribution-card:hover {
		border-color: #2563eb;
		background: #eff6ff;
	}

	.paper-contribution-card strong,
	.report-finding h4,
	.report-section__title,
	.problem-card h4 {
		margin: 0;
		color: #0f172a;
		font-size: 14px;
		font-weight: 800;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.paper-contribution-card span,
	.problem-card p {
		margin: 0;
		color: #475569;
		font-size: 13px;
		line-height: 20px;
	}

	.problem-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 10px;
	}

	.problem-card__header span {
		flex: 0 0 auto;
		padding: 2px 7px;
		border: 1px solid #bfdbfe;
		border-radius: 999px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 11px;
		font-weight: 800;
		line-height: 16px;
	}

	.chain-card {
		border-color: #bae6fd;
		background: #f8fbff;
	}

	.chain-list,
	.parameter-chain {
		display: grid;
		gap: 12px;
	}

	.parameter-chain {
		padding: 14px;
		border: 1px solid #dbeafe;
		border-radius: 10px;
		background: #ffffff;
	}

	.parameter-chain__header,
	.chain-judgement {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 12px;
		align-items: start;
	}

	.parameter-chain__header h4 {
		margin: 4px 0 0;
		color: #0f172a;
		font-size: 18px;
		font-weight: 800;
		line-height: 26px;
	}

	.parameter-chain__header p,
	.chain-step p,
	.chain-judgement p {
		margin: 0;
		color: #475569;
		font-size: 13px;
		line-height: 20px;
	}

	.chain-rank,
	.chain-score {
		display: inline-flex;
		align-items: center;
		min-height: 24px;
		padding: 3px 8px;
		border-radius: 6px;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
	}

	.chain-rank {
		background: #dbeafe;
		color: #1d4ed8;
	}

	.chain-score {
		border: 1px solid #bbf7d0;
		background: #f0fdf4;
		color: #15803d;
		white-space: nowrap;
	}

	.chain-steps {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.chain-step {
		display: grid;
		align-content: start;
		gap: 8px;
		padding: 12px;
		border: 1px solid #e2e8f0;
		border-radius: 8px;
		background: #fbfdff;
	}

	.chain-step--wide {
		grid-column: 1 / -1;
	}

	.chain-step > span {
		width: 24px;
		height: 24px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 999px;
		background: #0f172a;
		color: #ffffff;
		font-size: 12px;
		font-weight: 800;
		line-height: 18px;
	}

	.chain-step > strong,
	.chain-judgement strong {
		color: #0f172a;
		font-size: 13px;
		font-weight: 800;
		line-height: 20px;
	}

	.chain-step dl {
		display: grid;
		gap: 6px;
		margin: 0;
	}

	.chain-step dl div {
		display: grid;
		grid-template-columns: minmax(110px, 0.5fr) minmax(0, 1fr);
		gap: 8px;
	}

	.chain-step dt {
		color: #64748b;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.chain-step dd {
		margin: 0;
		color: #0f172a;
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.chain-metrics {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 8px;
	}

	.chain-metric {
		display: grid;
		gap: 2px;
		min-height: 86px;
		padding: 10px;
		border: 1px solid #dbeafe;
		border-radius: 8px;
		background: #ffffff;
		color: #0f172a;
		text-align: left;
		cursor: pointer;
	}

	.chain-metric:hover {
		border-color: #2563eb;
		background: #eff6ff;
	}

	.chain-metric span,
	.chain-metric small {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
	}

	.chain-metric strong {
		color: #0f172a;
		font-size: 17px;
		font-weight: 800;
		line-height: 24px;
	}

	.chain-judgement {
		grid-template-columns: minmax(0, 1fr) minmax(220px, 0.45fr);
		padding-top: 2px;
	}

	.chain-judgement > div {
		display: grid;
		gap: 6px;
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

	.matrix-evidence-chips {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 160px;
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
	:root[data-theme='dark'] .detail-drawer h3,
	:root[data-theme='dark'] .dossier-table th,
	:root[data-theme='dark'] .dossier-table td,
	:root[data-theme='dark'] .report-stat-grid strong,
	:root[data-theme='dark'] .paper-contribution-card strong,
	:root[data-theme='dark'] .problem-card h4,
	:root[data-theme='dark'] .paper-mini-card span,
	:root[data-theme='dark'] .chart-bar strong,
	:root[data-theme='dark'] .chart-labels,
	:root[data-theme='dark'] .narrative-card h3,
	:root[data-theme='dark'] .narrative-finding h4,
	:root[data-theme='dark'] .narrative-metrics strong,
	:root[data-theme='dark'] .best-value-card strong,
	:root[data-theme='dark'] .parameter-chain__header h4,
	:root[data-theme='dark'] .chain-step > strong,
	:root[data-theme='dark'] .chain-judgement strong,
	:root[data-theme='dark'] .chain-step dd,
	:root[data-theme='dark'] .chain-metric strong,
	:root[data-theme='dark'] .narrative-comparison-card strong,
	:root[data-theme='dark'] .detail-drawer dd,
	:root[data-theme='dark'] .pdf-data dd {
		color: var(--text-primary);
	}

	:root[data-theme='dark'] .dossier-tabs,
	:root[data-theme='dark'] .dossier-state-card,
	:root[data-theme='dark'] .dossier-card,
	:root[data-theme='dark'] .parameter-chain,
	:root[data-theme='dark'] .chain-step,
	:root[data-theme='dark'] .chain-metric,
	:root[data-theme='dark'] .aside-card,
	:root[data-theme='dark'] .detail-drawer,
	:root[data-theme='dark'] .paper-mini-card,
	:root[data-theme='dark'] .narrative-metrics div,
	:root[data-theme='dark'] .best-value-card,
	:root[data-theme='dark'] .narrative-comparison-card div,
	:root[data-theme='dark'] .narrative-finding,
	:root[data-theme='dark'] .report-stat-grid div,
	:root[data-theme='dark'] .paper-contribution-card,
	:root[data-theme='dark'] .problem-card,
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
	:root[data-theme='dark'] .parameter-chain__header p,
	:root[data-theme='dark'] .chain-step p,
	:root[data-theme='dark'] .chain-judgement p,
	:root[data-theme='dark'] .chain-step dt,
	:root[data-theme='dark'] .chain-metric span,
	:root[data-theme='dark'] .chain-metric small,
	:root[data-theme='dark'] .report-stat-grid span,
	:root[data-theme='dark'] .paper-contribution-card span,
	:root[data-theme='dark'] .problem-card p,
	:root[data-theme='dark'] .comparison-panel > p,
	:root[data-theme='dark'] .chart-caption,
	:root[data-theme='dark'] .narrative-lede,
	:root[data-theme='dark'] .narrative-section-heading p,
	:root[data-theme='dark'] .narrative-finding p,
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

		.parameter-chain__header,
		.chain-judgement,
		.chain-steps,
		.report-stat-grid {
			grid-template-columns: 1fr;
			grid-column: auto;
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

		.report-table-scroll {
			overflow-x: visible;
			border: 0;
			background: transparent;
		}

		.material-report-markdown table,
		.material-report-markdown thead,
		.material-report-markdown tbody,
		.material-report-markdown tr,
		.material-report-markdown th,
		.material-report-markdown td {
			display: block;
			width: 100%;
			min-width: 0;
		}

		.material-report-markdown thead {
			display: none;
		}

		.material-report-markdown tr {
			margin-bottom: 10px;
			border: 1px solid #e2e8f0;
			border-radius: 8px;
			background: #ffffff;
			overflow: hidden;
		}

		.material-report-markdown td {
			display: grid;
			grid-template-columns: minmax(96px, 34%) minmax(0, 1fr);
			gap: 10px;
			border-bottom: 1px solid #e2e8f0;
		}

		.material-report-markdown td::before {
			content: attr(data-label);
			color: #64748b;
			font-weight: 800;
		}
	}
</style>
