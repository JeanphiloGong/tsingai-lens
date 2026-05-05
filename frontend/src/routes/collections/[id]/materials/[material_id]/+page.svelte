<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchMaterialResearchView,
		formatEvidenceBackedValue,
		formatShortIdentifier,
		type EvidenceBackedValue,
		type EvidenceReference,
		type MaterialPaperCoverage,
		type MaterialProfile,
		type SampleMatrixColumn,
		type SampleMatrixRow
	} from '../../../../_shared/researchView';

	type Translate = (key: string, vars?: Record<string, string | number>) => string;

	type PropertyColumn = {
		key: string;
		label: string;
		shortLabel: string;
		unit: string | null;
	};

	type ProcessSummary = {
		controlledLabels: string[];
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

	const PRIMARY_PROCESS_KEYS = [
		'scan_strategy',
		'laser_power_w',
		'scan_speed_mm_s',
		'energy_density_j_mm3',
		'layer_thickness_um',
		'hatch_spacing_um'
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
	let pdfGenerated = false;
	let loading = false;
	let error = '';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: materialId = $page.params.material_id ?? '';
	$: loadKey = `${collectionId}:${materialId}`;
	$: sampleRows = materialProfile?.sample_matrix.rows ?? [];
	$: sampleColumns = sampleMatrixColumns(materialProfile, sampleRows);
	$: propertyColumns = materialPropertyColumns(sampleRows, sampleColumns, $t);
	$: evidenceCodeMap = buildEvidenceCodeMap(sampleRows, propertyColumns);
	$: evidenceRows = buildEvidenceRows(
		sampleRows,
		propertyColumns,
		evidenceCodeMap,
		collectionId,
		$t
	);
	$: processSummary = buildProcessSummary(sampleRows, $t);
	$: comparisonRows = buildComparisonRows(sampleRows, propertyColumns, processSummary, $t);
	$: trendRows = trendComparisonRows(comparisonRows);
	$: materialTags = buildMaterialTags(materialProfile, $t);
	$: paperCount = materialProfile?.overview.paper_count || materialPapers().length;
	$: sampleCount = materialProfile?.overview.sample_count || sampleRows.length;
	$: evidenceCount = materialProfile?.overview.evidence_count || evidenceRows.length;
	$: measuredPropertyCount =
		materialProfile?.overview.measured_properties.length || propertyColumns.length;
	$: if (collectionId && materialId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadMaterialProfile();
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

	function materialPropertyColumns(
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
		return row.process_context[key] || '--';
	}

	function sampleLabel(row: SampleMatrixRow) {
		return row.sample_label || row.sample_id || '--';
	}

	function otherProcessParameters(row: SampleMatrixRow, translate: Translate) {
		return Object.entries(row.process_context)
			.filter(([key, value]) => value && !PRIMARY_PROCESS_KEYS.includes(key))
			.map(([key, value]) => `${processLabel(key, translate)}: ${value}`)
			.join('; ');
	}

	function buildProcessSummary(rows: SampleMatrixRow[], translate: Translate): ProcessSummary {
		const keys = Array.from(
			new Set(rows.flatMap((row) => Object.keys(row.process_context)))
		).filter((key) => rows.some((row) => row.process_context[key]));
		const controlledLabels: string[] = [];
		const changedLabels: string[] = [];

		for (const key of keys) {
			const values = Array.from(
				new Set(rows.map((row) => row.process_context[key]).filter(Boolean))
			);
			if (values.length === 1) controlledLabels.push(processLabel(key, translate));
			if (values.length > 1) changedLabels.push(processLabel(key, translate));
		}

		return {
			controlledLabels,
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

	function buildComparisonRows(
		rows: SampleMatrixRow[],
		columns: PropertyColumn[],
		summary: ProcessSummary,
		translate: Translate
	): ComparisonRow[] {
		if (rows.length < 2) return [];
		const [first, second] = rows;
		const firstLabel = sampleLabel(first);
		const secondLabel = sampleLabel(second);

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
					variable: `${summary.changedVariable}: ${firstLabel} vs ${secondLabel}`,
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

	function buildEvidenceCodeMap(rows: SampleMatrixRow[], columns: PropertyColumn[]) {
		const ids: string[] = [];
		for (const row of rows) {
			for (const column of columns) {
				for (const ref of row.values[column.key]?.evidence_refs ?? []) {
					if (ref.evidence_ref_id && !ids.includes(ref.evidence_ref_id))
						ids.push(ref.evidence_ref_id);
				}
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
			sample: sampleLabel(row),
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
		translate: Translate
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
					claim: `${sampleLabel(row)} ${column.shortLabel} ${formatEvidenceBackedValue(value)}`,
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

	function openValueEvidence(
		row: SampleMatrixRow,
		column: PropertyColumn,
		value: EvidenceBackedValue
	) {
		pdfDrawerOpen = false;
		selectedEvidence = drawerDetailForValue(row, column, value, evidenceCodeMap, collectionId, $t);
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
	}

	function generatePdfReport() {
		pdfGenerated = true;
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
					sampleLabel(row),
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
			<button class="btn btn--primary-light btn--small" type="button" on:click={openPdfDrawer}>
				{$t('research.materialDossier.actions.generatePdf')}
			</button>
			<button class="btn btn--ghost btn--small" type="button" on:click={loadMaterialProfile}>
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
		<div class="dossier-layout">
			<main class="dossier-main" aria-label={$t('research.materialDossier.mainLabel')}>
				<section id="samples-process" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">1</span>
						<h3>{$t('research.materialDossier.sections.samples.title')}</h3>
						<p>{$t('research.materialDossier.sections.samples.body')}</p>
					</div>

					<div class="dossier-table-wrapper">
						<table class="dossier-table">
							<thead>
								<tr>
									<th>{$t('research.materialDossier.table.sampleId')}</th>
									<th>{$t('research.materialDossier.table.scanStrategy')}</th>
									<th>{$t('research.materialDossier.table.laserPower')}</th>
									<th>{$t('research.materialDossier.table.scanSpeed')}</th>
									<th>{$t('research.materialDossier.table.energyDensity')}</th>
									<th>{$t('research.materialDossier.table.layerThickness')}</th>
									<th>{$t('research.materialDossier.table.hatchSpacing')}</th>
									<th>{$t('research.materialDossier.table.otherParameters')}</th>
								</tr>
							</thead>
							<tbody>
								{#each sampleRows as row (row.row_id)}
									<tr>
										<td>
											<a
												class="dossier-link"
												href={resolve('/collections/[id]/materials/[material_id]', {
													id: collectionId,
													material_id: materialId
												})}
											>
												{sampleLabel(row)}
											</a>
										</td>
										<td>{processValue(row, 'scan_strategy')}</td>
										<td>{processValue(row, 'laser_power_w')}</td>
										<td>{processValue(row, 'scan_speed_mm_s')}</td>
										<td>{processValue(row, 'energy_density_j_mm3')}</td>
										<td>{processValue(row, 'layer_thickness_um')}</td>
										<td>{processValue(row, 'hatch_spacing_um')}</td>
										<td>{otherProcessParameters(row, $t) || '--'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					<p class="dossier-table-note">
						{$t('research.materialDossier.samples.summary', {
							count: sampleRows.length,
							controlled: processSummary.controlledLabels.join(', ') || '--',
							changed: processSummary.changedLabels.join(', ') || '--'
						})}
					</p>
				</section>

				<section id="performance-results" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">2</span>
						<h3>{$t('research.materialDossier.sections.performance.title')}</h3>
						<p>{$t('research.materialDossier.sections.performance.body')}</p>
					</div>

					<div class="dossier-table-wrapper">
						<table class="dossier-table">
							<thead>
								<tr>
									<th>{$t('research.materialDossier.table.sampleId')}</th>
									{#each propertyColumns as column (column.key)}
										<th>{column.label}</th>
									{/each}
									<th>{$t('research.materialDossier.table.testCondition')}</th>
									<th>{$t('research.materialDossier.table.evidenceAnchors')}</th>
								</tr>
							</thead>
							<tbody>
								{#each sampleRows as row (row.row_id)}
									<tr>
										<td>
											<span class="sample-id">{sampleLabel(row)}</span>
										</td>
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
										<td>{row.variable_axis ?? '--'}</td>
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

				<section id="evidence-locator" class="dossier-card">
					<div class="dossier-section-heading">
						<span class="section-number">4</span>
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
					<a href="#samples-process">1 {$t('research.materialDossier.sections.samples.title')}</a>
					<a href="#performance-results"
						>2 {$t('research.materialDossier.sections.performance.title')}</a
					>
					<a href="#trend-comparison">3 {$t('research.materialDossier.sections.trends.title')}</a>
					<a href="#evidence-locator">4 {$t('research.materialDossier.sections.evidence.title')}</a>
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
					{pdfGenerated
						? $t('research.materialDossier.pdf.generatedTitle')
						: $t('research.materialDossier.pdf.title')}
				</h3>
				<button type="button" on:click={closeDrawer}>
					{$t('research.evidence.close')}
				</button>
			</div>
			{#if pdfGenerated}
				<p class="pdf-status">{$t('research.materialDossier.pdf.generatedStatus')}</p>
				<div class="drawer-actions">
					<button class="btn btn--ghost btn--small" type="button">
						{$t('research.materialDossier.pdf.view')}
					</button>
					<button class="btn btn--ghost btn--small" type="button">
						{$t('research.materialDossier.pdf.download')}
					</button>
					<button
						class="btn btn--primary-light btn--small"
						type="button"
						on:click={generatePdfReport}
					>
						{$t('research.materialDossier.pdf.regenerate')}
					</button>
				</div>
			{:else}
				<p>{$t('research.materialDossier.pdf.body')}</p>
				<ul class="pdf-list">
					<li>{$t('research.materialDossier.sections.samples.title')}</li>
					<li>{$t('research.materialDossier.sections.performance.title')}</li>
					<li>{$t('research.materialDossier.sections.trends.title')}</li>
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
						on:click={generatePdfReport}
					>
						{$t('research.materialDossier.pdf.generate')}
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

	.sample-id {
		color: #2563eb;
		font-weight: 700;
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

	.drawer-actions {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 8px;
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
	:root[data-theme='dark'] .paper-mini-card span,
	:root[data-theme='dark'] .chart-bar strong,
	:root[data-theme='dark'] .chart-labels,
	:root[data-theme='dark'] .detail-drawer dd,
	:root[data-theme='dark'] .pdf-data dd {
		color: var(--text-primary);
	}

	:root[data-theme='dark'] .dossier-state-card,
	:root[data-theme='dark'] .dossier-card,
	:root[data-theme='dark'] .aside-card,
	:root[data-theme='dark'] .detail-drawer,
	:root[data-theme='dark'] .paper-mini-card,
	:root[data-theme='dark'] .mini-chart {
		border-color: var(--border-default);
		background: var(--surface-card);
	}

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
