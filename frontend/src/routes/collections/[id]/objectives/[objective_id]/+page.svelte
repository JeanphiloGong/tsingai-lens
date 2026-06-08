<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		createObjectiveReport,
		fetchObjectiveReport,
		fetchObjectiveResearchView,
		formatShortIdentifier,
		getResearchViewStateTone,
		type ObjectiveEvidenceRoute,
		type ObjectiveEvidenceUnit,
		type ObjectivePaperFrame,
		type ObjectiveResearchView
	} from '../../../../_shared/researchView';

	type EvidenceGroup = {
		kind: string;
		labelKey: string;
		units: ObjectiveEvidenceUnit[];
	};

	type PaperCoverage = {
		frame: ObjectivePaperFrame;
		units: ObjectiveEvidenceUnit[];
		routeCount: number;
	};

	type EvidenceReadinessItem = {
		id: string;
		labelKey: string;
		count: number;
		ready: boolean;
		evidenceKind: string | null;
	};

	type ComparisonReadiness = {
		tone: 'ready' | 'limited' | 'pending';
		titleKey: string;
		bodyKey: string;
	};

	type ResearchFocusGroup = {
		labelKey: string;
		items: string[];
	};

	type SourceEntry = {
		label: string;
		documentId: string | null;
		query: string;
	};

	type FilterOption = {
		value: string;
		label: string;
		count: number;
	};

	type MarkdownReportBlock =
		| { kind: 'h1' | 'h2' | 'h3' | 'p'; text: string }
		| { kind: 'ul' | 'ol'; items: string[] }
		| { kind: 'table'; headers: string[]; rows: string[][] };

	const evidenceKindOrder = [
		'measurement',
		'test_condition',
		'characterization',
		'comparison',
		'interpretation'
	];
	const compactHiddenRecordKeys = new Set([
		'evidence_unit_id',
		'objective_id',
		'document_id',
		'route_id',
		'frame_id',
		'logic_chain_id',
		'evidence_id',
		'anchor_id'
	]);
	const EVIDENCE_GROUP_PREVIEW_LIMIT = 6;

	let objectiveView: ObjectiveResearchView | null = null;
	let loading = false;
	let reportGenerating = false;
	let error = '';
	let reportError = '';
	let loadedKey = '';
	let selectedEvidenceUnitId = '';
	let selectedEvidenceKind = 'all';
	let selectedEvidenceDocumentId = 'all';
	let auditShellOpen = false;
	let evidenceAuditOpen = false;
	let evidenceSection: HTMLElement | null = null;

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: loadKey = `${collectionId}:${objectiveId}`;
	$: frames = objectiveView?.paper_frames ?? [];
	$: evidenceUnits = objectiveView?.evidence_units ?? [];
	$: evidenceRoutes = objectiveView?.evidence_routes ?? [];
	$: objectiveReport = objectiveView?.objective_report ?? null;
	$: objectiveReportBlocks = parseMarkdownReport(objectiveReport?.markdown ?? '');
	$: relevantFrameCount = frames.filter((frame) => frame.relevance !== 'irrelevant').length;
	$: evidenceKindOptions = buildEvidenceKindOptions(evidenceUnits);
	$: evidenceDocumentOptions = buildEvidenceDocumentOptions(frames, evidenceUnits);
	$: if (
		selectedEvidenceKind !== 'all' &&
		!evidenceKindOptions.some((option) => option.value === selectedEvidenceKind)
	) {
		selectedEvidenceKind = 'all';
	}
	$: if (
		selectedEvidenceDocumentId !== 'all' &&
		!evidenceDocumentOptions.some((option) => option.value === selectedEvidenceDocumentId)
	) {
		selectedEvidenceDocumentId = 'all';
	}
	$: filteredEvidenceUnits = filterEvidenceUnits(
		evidenceUnits,
		selectedEvidenceKind,
		selectedEvidenceDocumentId
	);
	$: evidenceGroups = buildEvidenceGroups(filteredEvidenceUnits);
	$: paperCoverage = buildPaperCoverage(frames, evidenceUnits, evidenceRoutes);
	$: researchFocusGroups = objectiveView ? buildResearchFocusGroups(objectiveView) : [];
	$: evidenceReadinessItems = objectiveView ? buildEvidenceReadinessItems(objectiveView) : [];
	$: comparisonReadiness = objectiveView ? buildComparisonReadiness(objectiveView) : null;
	$: representativeEvidenceUnits = buildRepresentativeEvidenceUnits(evidenceUnits);
	$: selectedEvidenceUnit =
		(selectedEvidenceUnitId
			? filteredEvidenceUnits.find((unit) => unit.evidence_unit_id === selectedEvidenceUnitId)
			: null) ??
		filteredEvidenceUnits[0] ??
		null;
	$: if (browser && collectionId && objectiveId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadObjectiveView();
	}

	async function loadObjectiveView() {
		loading = true;
		error = '';
		try {
			objectiveView = await fetchObjectiveResearchView(collectionId, objectiveId);
			reportError = '';
		} catch (err) {
			objectiveView = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function generateObjectiveReport(forceRegenerate = false) {
		if (!collectionId || !objectiveId || reportGenerating) return;
		reportGenerating = true;
		reportError = '';
		try {
			const report = await createObjectiveReport(collectionId, objectiveId, {
				language: 'zh',
				force_regenerate: forceRegenerate
			});
			if (objectiveView) {
				objectiveView = {
					...objectiveView,
					objective_report: report
				};
			}
		} catch (err) {
			reportError = errorMessage(err);
		} finally {
			reportGenerating = false;
		}
	}

	async function refreshObjectiveReport() {
		if (!collectionId || !objectiveId || reportGenerating) return;
		reportGenerating = true;
		reportError = '';
		try {
			const report = await fetchObjectiveReport(collectionId, objectiveId);
			if (objectiveView) {
				objectiveView = {
					...objectiveView,
					objective_report: report
				};
			}
		} catch (err) {
			reportError = errorMessage(err);
		} finally {
			reportGenerating = false;
		}
	}

	function listLabel(items: string[]) {
		return items.length ? items.join(', ') : $t('research.emptyValue');
	}

	function parseMarkdownReport(markdown: string): MarkdownReportBlock[] {
		const blocks: MarkdownReportBlock[] = [];
		let paragraph: string[] = [];
		let listKind: 'ul' | 'ol' | null = null;
		let listItems: string[] = [];
		let tableLines: string[] = [];
		const flushParagraph = () => {
			const text = paragraph.join(' ').trim();
			if (text) blocks.push({ kind: 'p', text });
			paragraph = [];
		};
		const flushList = () => {
			if (listKind && listItems.length) {
				blocks.push({ kind: listKind, items: listItems });
			}
			listKind = null;
			listItems = [];
		};
		const flushTable = () => {
			const table = parseMarkdownTable(tableLines);
			if (table) {
				blocks.push(table);
			} else if (tableLines.length) {
				paragraph.push(...tableLines);
				flushParagraph();
			}
			tableLines = [];
		};
		const flushOpenBlocks = () => {
			flushTable();
			flushList();
			flushParagraph();
		};
		for (const rawLine of markdown.split(/\r?\n/)) {
			const line = rawLine.trim();
			if (!line) {
				flushOpenBlocks();
				continue;
			}
			const heading = /^(#{1,3})\s+(.+)$/.exec(line);
			if (heading) {
				flushOpenBlocks();
				blocks.push({
					kind: heading[1].length === 1 ? 'h1' : heading[1].length === 2 ? 'h2' : 'h3',
					text: heading[2].trim()
				});
				continue;
			}
			if (line.startsWith('|') && line.endsWith('|')) {
				flushParagraph();
				flushList();
				tableLines.push(line);
				continue;
			}
			const listItem = /^[-*]\s+(.+)$/.exec(line);
			if (listItem) {
				flushParagraph();
				flushTable();
				if (listKind && listKind !== 'ul') flushList();
				listKind = 'ul';
				listItems.push(listItem[1].trim());
				continue;
			}
			const orderedListItem = /^\d+[.)]\s+(.+)$/.exec(line);
			if (orderedListItem) {
				flushParagraph();
				flushTable();
				if (listKind && listKind !== 'ol') flushList();
				listKind = 'ol';
				listItems.push(orderedListItem[1].trim());
				continue;
			}
			flushTable();
			flushList();
			paragraph.push(line);
		}
		flushOpenBlocks();
		return blocks;
	}

	function parseMarkdownTable(lines: string[]): MarkdownReportBlock | null {
		if (lines.length < 2 || !isMarkdownSeparatorRow(lines[1])) return null;
		const headers = splitMarkdownTableRow(lines[0]);
		const rows = lines.slice(2).map(splitMarkdownTableRow).filter((row) => row.length);
		if (!headers.length || !rows.length) return null;
		return { kind: 'table', headers, rows };
	}

	function isMarkdownSeparatorRow(line: string) {
		const cells = splitMarkdownTableRow(line);
		return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
	}

	function splitMarkdownTableRow(line: string) {
		return line
			.replace(/^\|/, '')
			.replace(/\|$/, '')
			.split('|')
			.map((cell) => cell.trim());
	}

	function frameTitle(frame: ObjectivePaperFrame) {
		return frame.title || frame.source_filename || frame.document_id;
	}

	function paperContributionSummary(paper: PaperCoverage) {
		if (paper.frame.background) return paper.frame.background;
		if (paper.frame.changed_variables.length && paper.frame.measured_property_scope.length) {
			return $t('research.objectiveWorkspace.paperContributionFallback', {
				variables: listLabel(paper.frame.changed_variables),
				properties: listLabel(paper.frame.measured_property_scope)
			});
		}
		return $t('research.objectiveWorkspace.noBackground');
	}

	function confidenceLabel(value: number) {
		return value > 0 ? `${Math.round(value * 100)}%` : $t('research.emptyValue');
	}

	function evidenceCardSourceLabel(documentId: string | null) {
		return formatShortIdentifier(documentId || null);
	}

	function boolState(value: boolean) {
		return value
			? $t('research.objectiveWorkspace.ready')
			: $t('research.objectiveWorkspace.pending');
	}

	function routeSchemaLabel(value: Record<string, unknown>) {
		const headers = value.column_headers;
		if (Array.isArray(headers) && headers.length) {
			return headers.map((item) => String(item)).join(', ');
		}
		return Object.keys(value).length ? JSON.stringify(value) : $t('research.emptyValue');
	}

	function hasDisplayValue(value: unknown): boolean {
		if (value === null || value === undefined || value === '') return false;
		if (Array.isArray(value)) return value.some((item) => hasDisplayValue(item));
		if (typeof value === 'object') {
			return Object.values(value as Record<string, unknown>).some((item) => hasDisplayValue(item));
		}
		return true;
	}

	function displayValue(value: unknown): string {
		if (!hasDisplayValue(value)) return '';
		if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
			return String(value);
		}
		if (Array.isArray(value)) {
			return value
				.map((item) => displayValue(item))
				.filter(Boolean)
				.join(', ');
		}
		return Object.entries(value as Record<string, unknown>)
			.filter(([, item]) => hasDisplayValue(item))
			.map(([key, item]) => `${key}: ${displayValue(item)}`)
			.join('; ');
	}

	function shouldDisplayRecordKey(key: string) {
		return !compactHiddenRecordKeys.has(key.toLowerCase());
	}

	function recordEntries(record: Record<string, unknown>, limit = 5) {
		return Object.entries(record)
			.filter(([key]) => shouldDisplayRecordKey(key))
			.filter(([, value]) => hasDisplayValue(value))
			.slice(0, limit)
			.map(([key, value]) => ({ key, value: displayValue(value) }));
	}

	function evidenceUnitTitle(unit: ObjectiveEvidenceUnit) {
		return unit.property_normalized || unit.unit_kind;
	}

	function evidenceUnitValue(unit: ObjectiveEvidenceUnit) {
		const payload = unit.value_payload;
		return (
			displayValue(payload.source_value_text) ||
			displayValue(payload.statement) ||
			displayValue(payload.observation_text) ||
			displayValue(payload.observed_value) ||
			displayValue(payload.value) ||
			displayValue(unit.interpretation) ||
			$t('research.objectiveWorkspace.noValue')
		);
	}

	function baselineCardFact(record: Record<string, unknown>) {
		const nestedSampleContext = record.sample_context;
		if (nestedSampleContext && typeof nestedSampleContext === 'object') {
			const [entry] = recordEntries(nestedSampleContext as Record<string, unknown>, 1);
			return entry ? `baseline: ${entry.value}` : '';
		}
		const [entry] = recordEntries(record, 1);
		return entry ? `baseline: ${entry.value}` : '';
	}

	function evidenceCardEntries(record: Record<string, unknown>, limit = 5) {
		const verboseKeys = new Set(['detail', 'details', 'source_text', 'raw_text', 'statement']);
		return recordEntries(record, limit).filter(
			(entry) => !verboseKeys.has(entry.key.toLowerCase())
		);
	}

	function evidenceCardFacts(unit: ObjectiveEvidenceUnit) {
		return [
			...evidenceCardEntries(unit.sample_context, 1).map((entry) => `${entry.key}: ${entry.value}`),
			...evidenceCardEntries(unit.process_context, 2).map(
				(entry) => `${entry.key}: ${entry.value}`
			),
			...evidenceCardEntries(unit.test_condition, 1).map((entry) => `${entry.key}: ${entry.value}`),
			baselineCardFact(unit.baseline_context)
		]
			.filter(Boolean)
			.slice(0, 4);
	}

	function sourceRefLabel(sourceRef: Record<string, unknown>) {
		const displayLabel = displayValue(sourceRef.display_label);
		if (displayLabel) return displayLabel;
		const sourceKind =
			displayValue(sourceRef.source_kind) || $t('research.objectiveWorkspace.source');
		const sourceRefId =
			displayValue(sourceRef.source_ref) ||
			displayValue(sourceRef.table_id) ||
			displayValue(sourceRef.anchor_id) ||
			displayValue(sourceRef.block_id);
		const page = displayValue(sourceRef.page);
		return [sourceKind, sourceRefId, page ? $t('research.objectiveWorkspace.page', { page }) : '']
			.filter(Boolean)
			.join(' · ');
	}

	function evidenceKindLabelKey(kind: string) {
		if (kind === 'measurement') return 'research.objectiveWorkspace.measurementResults';
		if (kind === 'test_condition') return 'research.objectiveWorkspace.testConditions';
		if (kind === 'characterization')
			return 'research.objectiveWorkspace.characterizationObservations';
		if (kind === 'comparison') return 'research.objectiveWorkspace.comparisonEvidence';
		if (kind === 'interpretation') return 'research.objectiveWorkspace.authorInterpretations';
		return 'research.objectiveWorkspace.otherEvidence';
	}

	function buildEvidenceGroups(units: ObjectiveEvidenceUnit[]): EvidenceGroup[] {
		const grouped: Record<string, ObjectiveEvidenceUnit[]> = {};
		for (const unit of units) {
			grouped[unit.unit_kind] = [...(grouped[unit.unit_kind] ?? []), unit];
		}

		const kinds = [
			...evidenceKindOrder.filter((kind) => kind in grouped),
			...Object.keys(grouped).filter((kind) => !evidenceKindOrder.includes(kind))
		];

		return kinds.map((kind) => ({
			kind,
			labelKey: evidenceKindLabelKey(kind),
			units: grouped[kind] ?? []
		}));
	}

	function evidenceGroupPreview(units: ObjectiveEvidenceUnit[]) {
		return units.slice(0, EVIDENCE_GROUP_PREVIEW_LIMIT);
	}

	function evidenceGroupHiddenCount(units: ObjectiveEvidenceUnit[]) {
		return Math.max(0, units.length - EVIDENCE_GROUP_PREVIEW_LIMIT);
	}

	function buildEvidenceKindOptions(units: ObjectiveEvidenceUnit[]): FilterOption[] {
		const counts: Record<string, number> = {};
		for (const unit of units) {
			counts[unit.unit_kind] = (counts[unit.unit_kind] ?? 0) + 1;
		}
		const kinds = [
			...evidenceKindOrder.filter((kind) => kind in counts),
			...Object.keys(counts)
				.filter((kind) => !evidenceKindOrder.includes(kind))
				.sort()
		];
		return [
			{
				value: 'all',
				label: $t('research.objectiveWorkspace.allEvidenceKinds'),
				count: units.length
			},
			...kinds.map((kind) => ({
				value: kind,
				label: $t(evidenceKindLabelKey(kind)),
				count: counts[kind] ?? 0
			}))
		];
	}

	function buildEvidenceDocumentOptions(
		paperFrames: ObjectivePaperFrame[],
		units: ObjectiveEvidenceUnit[]
	): FilterOption[] {
		const counts: Record<string, number> = {};
		for (const unit of units) {
			if (unit.document_id) counts[unit.document_id] = (counts[unit.document_id] ?? 0) + 1;
		}
		const frameByDocumentId = new Map(paperFrames.map((frame) => [frame.document_id, frame]));
		return [
			{
				value: 'all',
				label: $t('research.objectiveWorkspace.allPapers'),
				count: units.length
			},
			...Object.keys(counts)
				.sort()
				.map((documentId) => {
					const frame = frameByDocumentId.get(documentId);
					return {
						value: documentId,
						label: frame ? frameTitle(frame) : documentId,
						count: counts[documentId] ?? 0
					};
				})
		];
	}

	function filterEvidenceUnits(
		units: ObjectiveEvidenceUnit[],
		kind: string,
		documentId: string
	): ObjectiveEvidenceUnit[] {
		return units.filter((unit) => {
			if (kind !== 'all' && unit.unit_kind !== kind) return false;
			if (documentId !== 'all' && unit.document_id !== documentId) return false;
			return true;
		});
	}

	function objectiveHref() {
		return resolve('/collections/[id]/objectives/[objective_id]', {
			id: collectionId,
			objective_id: objectiveId
		});
	}

	function buildPaperCoverage(
		paperFrames: ObjectivePaperFrame[],
		units: ObjectiveEvidenceUnit[],
		routes: ObjectiveEvidenceRoute[]
	): PaperCoverage[] {
		return paperFrames
			.map((frame) => ({
				frame,
				units: units.filter((unit) => unit.document_id === frame.document_id),
				routeCount: routes.filter((route) => route.document_id === frame.document_id).length
			}))
			.sort((left, right) => relevanceRank(left.frame) - relevanceRank(right.frame));
	}

	function relevanceRank(frame: ObjectivePaperFrame) {
		if (frame.relevance === 'high') return 0;
		if (frame.relevance === 'medium') return 1;
		if (frame.relevance === 'low') return 2;
		if (frame.relevance === 'irrelevant') return 4;
		return 3;
	}

	function unitsByKind(units: ObjectiveEvidenceUnit[], kind: string) {
		return units.filter((unit) => unit.unit_kind === kind);
	}

	function buildResearchFocusGroups(view: ObjectiveResearchView): ResearchFocusGroup[] {
		return [
			{
				labelKey: 'research.objectives.materialScope',
				items: view.objective.material_scope
			},
			{
				labelKey: 'research.objectives.processAxes',
				items: view.objective.process_axes
			},
			{
				labelKey: 'research.objectives.propertyAxes',
				items: view.objective.property_axes
			}
		].filter((group) => group.items.length);
	}

	function buildEvidenceReadinessItems(view: ObjectiveResearchView): EvidenceReadinessItem[] {
		const measurements = unitsByKind(view.evidence_units, 'measurement');
		const conditions = unitsByKind(view.evidence_units, 'test_condition');
		const observations = unitsByKind(view.evidence_units, 'characterization');
		const comparisons = unitsByKind(view.evidence_units, 'comparison');
		const relevantPapers = view.paper_frames.filter((frame) => frame.relevance !== 'irrelevant');

		return [
			{
				id: 'papers',
				labelKey: 'research.objectiveWorkspace.relevantPapers',
				count: relevantPapers.length,
				ready: view.readiness.frames_ready && relevantPapers.length > 0,
				evidenceKind: null
			},
			{
				id: 'measurements',
				labelKey: 'research.objectiveWorkspace.measurementResults',
				count: measurements.length,
				ready: measurements.length > 0,
				evidenceKind: 'measurement'
			},
			{
				id: 'comparisons',
				labelKey: 'research.objectiveWorkspace.comparisonEvidence',
				count: comparisons.length,
				ready: comparisons.length > 0,
				evidenceKind: 'comparison'
			},
			{
				id: 'conditions',
				labelKey: 'research.objectiveWorkspace.testConditions',
				count: conditions.length,
				ready: conditions.length > 0,
				evidenceKind: 'test_condition'
			},
			{
				id: 'observations',
				labelKey: 'research.objectiveWorkspace.characterizationObservations',
				count: observations.length,
				ready: observations.length > 0,
				evidenceKind: 'characterization'
			}
		];
	}

	function buildComparisonReadiness(view: ObjectiveResearchView): ComparisonReadiness {
		const measurements = unitsByKind(view.evidence_units, 'measurement');
		const conditions = unitsByKind(view.evidence_units, 'test_condition');
		const comparisons = unitsByKind(view.evidence_units, 'comparison');

		if (comparisons.length && conditions.length) {
			return {
				tone: 'ready',
				titleKey: 'research.objectiveWorkspace.comparisonReadyTitle',
				bodyKey: 'research.objectiveWorkspace.comparisonReadyBody'
			};
		}
		if (measurements.length && (comparisons.length || conditions.length)) {
			return {
				tone: 'limited',
				titleKey: 'research.objectiveWorkspace.comparisonLimitedTitle',
				bodyKey: 'research.objectiveWorkspace.comparisonLimitedBody'
			};
		}
		return {
			tone: 'pending',
			titleKey: 'research.objectiveWorkspace.comparisonPendingTitle',
			bodyKey: 'research.objectiveWorkspace.comparisonPendingBody'
		};
	}

	function humanizeCode(value: string) {
		const normalized = value.trim();
		if (!normalized) return '';
		return normalized.replace(/_/g, ' ');
	}

	function buildRepresentativeEvidenceUnits(units: ObjectiveEvidenceUnit[]) {
		const selected: ObjectiveEvidenceUnit[] = [];
		const selectedIds = new Set<string>();
		const byConfidence = (left: ObjectiveEvidenceUnit, right: ObjectiveEvidenceUnit) =>
			right.confidence - left.confidence;

		for (const kind of ['comparison', 'measurement', 'characterization', 'test_condition']) {
			const [unit] = units.filter((item) => item.unit_kind === kind).sort(byConfidence);
			if (unit) {
				selected.push(unit);
				selectedIds.add(unit.evidence_unit_id);
			}
		}

		for (const unit of [...units].sort(byConfidence)) {
			if (selected.length >= 4) break;
			if (!selectedIds.has(unit.evidence_unit_id)) selected.push(unit);
		}

		return selected;
	}

	function focusEvidenceKind(kind: string | null) {
		selectedEvidenceKind = kind ?? 'all';
		selectedEvidenceDocumentId = 'all';
		selectedEvidenceUnitId = '';
		auditShellOpen = true;
		evidenceAuditOpen = true;
		evidenceSection?.scrollIntoView({ block: 'start', behavior: 'smooth' });
	}

	function focusEvidenceUnit(unit: ObjectiveEvidenceUnit) {
		selectedEvidenceKind = unit.unit_kind;
		selectedEvidenceDocumentId = unit.document_id || 'all';
		selectedEvidenceUnitId = unit.evidence_unit_id;
		auditShellOpen = true;
		evidenceAuditOpen = true;
		evidenceSection?.scrollIntoView({ block: 'start', behavior: 'smooth' });
	}

	function queryString(params: [string, string][]) {
		const query = params
			.filter(([, value]) => value)
			.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
			.join('&');
		return query ? `?${query}` : '';
	}

	function sourceEntry(
		unit: ObjectiveEvidenceUnit,
		sourceRef: Record<string, unknown>
	): SourceEntry {
		const documentId = displayValue(sourceRef.document_id) || unit.document_id;
		const pageNumber = displayValue(sourceRef.page);
		const evidenceId =
			displayValue(sourceRef.evidence_id) || displayValue(sourceRef.evidence_ref_id);
		const anchorId = displayValue(sourceRef.anchor_id) || unit.evidence_anchor_ids[0] || '';
		const params: [string, string][] = [];
		if (pageNumber) params.push(['page', pageNumber]);
		if (evidenceId) params.push(['evidence_id', evidenceId]);
		if (anchorId) params.push(['anchor_id', anchorId]);
		params.push(['return_to', objectiveHref()]);

		return {
			label: sourceRefLabel(sourceRef),
			documentId: documentId || null,
			query: queryString(params)
		};
	}

	function sourceEntries(unit: ObjectiveEvidenceUnit): SourceEntry[] {
		const refs = unit.source_refs.length
			? unit.source_refs
			: [{ document_id: unit.document_id, source_kind: 'document', source_ref: unit.document_id }];

		return refs.map((sourceRef) => sourceEntry(unit, sourceRef));
	}

	function sourceEntryFromRef(sourceRef: Record<string, unknown>): SourceEntry | null {
		const documentId = displayValue(sourceRef.document_id);
		if (!documentId) return null;
		const pageNumber = displayValue(sourceRef.page);
		const evidenceId =
			displayValue(sourceRef.evidence_id) || displayValue(sourceRef.evidence_ref_id);
		const anchorId = displayValue(sourceRef.anchor_id);
		const params: [string, string][] = [];
		if (pageNumber) params.push(['page', pageNumber]);
		if (evidenceId) params.push(['evidence_id', evidenceId]);
		if (anchorId) params.push(['anchor_id', anchorId]);
		params.push(['return_to', objectiveHref()]);
		return {
			label: sourceRefLabel(sourceRef),
			documentId,
			query: queryString(params)
		};
	}


</script>

<svelte:head>
	<title>{objectiveView?.objective.question || $t('research.objectiveWorkspace.title')}</title>
</svelte:head>

<section class="objective-workspace fade-up">
	<a
		class="back-link"
		href={resolve('/collections/[id]/objectives', {
			id: collectionId
		})}
	>
		{$t('research.objectiveWorkspace.back')}
	</a>

	{#if loading}
		<section class="objective-state-card" aria-busy="true" aria-live="polite">
			<div class="status" role="status">{$t('research.objectiveWorkspace.loading')}</div>
		</section>
	{:else if error}
		<section class="objective-state-card objective-state-card--error" role="alert">
			<h2>{$t('research.objectiveWorkspace.errorTitle')}</h2>
			<p>{error}</p>
		</section>
	{:else if !objectiveView}
		<section class="objective-state-card">
			<h2>{$t('research.objectiveWorkspace.emptyTitle')}</h2>
			<p>{$t('research.objectiveWorkspace.emptyBody')}</p>
		</section>
	{:else}
		<header class="objective-hero">
			<div class="objective-hero__main">
				<p class="objective-eyebrow">{$t('research.objectiveWorkspace.eyebrow')}</p>
				<h2>{objectiveView.objective.question}</h2>
				<p>
					{objectiveView.objective.comparison_intent || $t('research.objectiveWorkspace.noIntent')}
				</p>
				<div class="objective-chip-row">
					{#each objectiveView.objective.material_scope as material (material)}
						<span>{material}</span>
					{/each}
					{#each objectiveView.objective.process_axes as axis (axis)}
						<span>{axis}</span>
					{/each}
					{#each objectiveView.objective.property_axes as axis (axis)}
						<span>{axis}</span>
					{/each}
				</div>
			</div>
			<div class="objective-hero__status">
				<span class={`status-badge status-badge--${getResearchViewStateTone(objectiveView.state)}`}>
					{$t(`research.state.${objectiveView.state}`)}
				</span>
				<strong>{confidenceLabel(objectiveView.objective.confidence)}</strong>
				<span>{$t('research.objectives.confidence')}</span>
				<a
					class="objective-hero__assistant-link"
					href={`${resolve('/collections/[id]/assistant', {
						id: collectionId
					})}?objective_id=${encodeURIComponent(objectiveId)}`}
				>
					{$t('research.objectiveWorkspace.askCopilot')}
				</a>
			</div>
		</header>

		<section class="objective-report-layout">
			<section class="objective-section objective-section--report">
				{#if objectiveReport?.markdown && (objectiveReport.status === 'ready' || objectiveReport.status === 'ready_with_warnings')}
					<div class="objective-report-reader-header">
						<div>
							<h3>{$t('research.objectiveWorkspace.objectiveReportTitle')}</h3>
							<p>{$t('research.objectiveWorkspace.objectiveReportBody')}</p>
						</div>
						<div class="objective-report-actions objective-report-actions--compact">
							<button type="button" on:click={refreshObjectiveReport} disabled={reportGenerating}>
								{$t('research.objectiveWorkspace.refreshObjectiveReport')}
							</button>
							<button type="button" on:click={() => generateObjectiveReport(true)} disabled={reportGenerating}>
								{$t('research.objectiveWorkspace.regenerateObjectiveReport')}
							</button>
						</div>
					</div>
					<article class="objective-report-document" aria-label={$t('research.objectiveWorkspace.objectiveReportTitle')}>
						<div class="objective-report-document__meta">
							<span>{humanizeCode(objectiveReport.status)}</span>
							{#if objectiveReport.model}
								<span>{objectiveReport.model}</span>
							{/if}
							{#if objectiveReport.generated_at}
								<span>{objectiveReport.generated_at}</span>
							{/if}
						</div>
						{#each objectiveReportBlocks as block, index (`report-${block.kind}-${index}`)}
							{#if block.kind === 'h1'}
								<h1>{block.text}</h1>
							{:else if block.kind === 'h2'}
								<h2>{block.text}</h2>
							{:else if block.kind === 'h3'}
								<h3>{block.text}</h3>
							{:else if block.kind === 'ul'}
								<ul class="objective-report-document__list">
									{#each block.items as item, itemIndex (`report-ul-${index}-${itemIndex}`)}
										<li>{item}</li>
									{/each}
								</ul>
							{:else if block.kind === 'ol'}
								<ol class="objective-report-document__list">
									{#each block.items as item, itemIndex (`report-ol-${index}-${itemIndex}`)}
										<li>{item}</li>
									{/each}
								</ol>
							{:else if block.kind === 'table'}
								<div class="objective-report-table-wrap">
									<table class="objective-report-table">
										<thead>
											<tr>
												{#each block.headers as header, headerIndex (`report-table-${index}-header-${headerIndex}`)}
													<th>{header}</th>
												{/each}
											</tr>
										</thead>
										<tbody>
											{#each block.rows as row, rowIndex (`report-table-${index}-row-${rowIndex}`)}
												<tr>
													{#each block.headers as _header, cellIndex (`report-table-${index}-cell-${rowIndex}-${cellIndex}`)}
														<td>{row[cellIndex] ?? ''}</td>
													{/each}
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{:else if block.kind === 'p'}
								<p>{block.text}</p>
							{/if}
						{/each}
					</article>
				{:else}
					<div class="section-heading">
						<div>
							<h3>{$t('research.objectiveWorkspace.objectiveReportTitle')}</h3>
							<p>{$t('research.objectiveWorkspace.objectiveReportBody')}</p>
						</div>
						<span>{objectiveReport ? humanizeCode(objectiveReport.status) : boolState(false)}</span>
					</div>
					<article class="objective-report-empty">
						<h4>{$t('research.objectiveWorkspace.objectiveReportNotReadyTitle')}</h4>
						<p>
							{objectiveReport?.message || $t('research.objectiveWorkspace.objectiveReportNotReadyBody')}
						</p>
						<div class="objective-report-actions">
							<button type="button" on:click={() => generateObjectiveReport(false)} disabled={reportGenerating}>
								{$t('research.objectiveWorkspace.generateObjectiveReport')}
							</button>
							{#if objectiveReport}
								<button type="button" on:click={refreshObjectiveReport} disabled={reportGenerating}>
									{$t('research.objectiveWorkspace.refreshObjectiveReport')}
								</button>
								<button type="button" on:click={() => generateObjectiveReport(true)} disabled={reportGenerating}>
									{$t('research.objectiveWorkspace.regenerateObjectiveReport')}
								</button>
							{/if}
						</div>
						{#if reportError}
							<p class="objective-report-error" role="alert">{reportError}</p>
						{/if}
					</article>
				{/if}
			</section>

			<aside class="objective-report-aside" aria-label={$t('research.objectiveWorkspace.summary')}>
				<div class="objective-summary-panel__heading">
					<span>{$t('research.objectiveWorkspace.summary')}</span>
					<strong>{boolState(objectiveView.readiness.evidence_units_ready)}</strong>
				</div>
				<div class="objective-summary-list">
					<article>
						<span>{$t('research.objectiveWorkspace.relevantPapers')}</span>
						<strong>{relevantFrameCount}</strong>
					</article>
					<article>
						<span>{$t('research.objectiveWorkspace.measurementResults')}</span>
						<strong>{unitsByKind(evidenceUnits, 'measurement').length}</strong>
					</article>
					<article>
						<span>{$t('research.objectiveWorkspace.testConditions')}</span>
						<strong>{unitsByKind(evidenceUnits, 'test_condition').length}</strong>
					</article>
					<article>
						<span>{$t('research.objectiveWorkspace.characterizationObservations')}</span>
						<strong>{unitsByKind(evidenceUnits, 'characterization').length}</strong>
					</article>
				</div>

				{#if researchFocusGroups.length}
					<div class="research-focus">
						<h4>{$t('research.objectiveWorkspace.researchFocus')}</h4>
						<div class="research-focus__grid">
							{#each researchFocusGroups as group (group.labelKey)}
								<div>
									<span>{$t(group.labelKey)}</span>
									<p>{listLabel(group.items)}</p>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<div
					class="evidence-readiness"
					aria-label={$t('research.objectiveWorkspace.evidenceReadiness')}
				>
					{#each evidenceReadinessItems as item (item.id)}
						<button
							class:ready={item.ready}
							type="button"
							on:click={() => focusEvidenceKind(item.evidenceKind)}
						>
							<strong>{item.count}</strong>
							<span>{$t(item.labelKey)}</span>
						</button>
					{/each}
				</div>

				{#if comparisonReadiness}
					<div class={`comparison-readiness comparison-readiness--${comparisonReadiness.tone}`}>
						<h4>{$t(comparisonReadiness.titleKey)}</h4>
						<p>{$t(comparisonReadiness.bodyKey)}</p>
					</div>
				{/if}
			</aside>
		</section>

		<details class="objective-audit-shell" bind:open={auditShellOpen}>
			<summary>
				{$t('research.objectiveWorkspace.evidenceAuditTitle')}
				<span>{evidenceUnits.length}</span>
			</summary>
			<section class="objective-workspace-grid">
			<div class="objective-main-column">
				<section class="objective-section" aria-labelledby="paper-contribution-title">
					<div class="section-heading">
						<div>
							<h3 id="paper-contribution-title">
								{$t('research.objectiveWorkspace.paperContributionTitle')}
							</h3>
							<p>{$t('research.objectiveWorkspace.paperContributionBody')}</p>
						</div>
						<span>{boolState(objectiveView.readiness.frames_ready)}</span>
					</div>
					{#if paperCoverage.length}
						<div class="paper-contribution-list">
							{#each paperCoverage as paper (paper.frame.frame_id)}
								<article class="paper-contribution-card">
									<div class="paper-contribution-card__header">
										<div>
											<span>{paper.frame.paper_role}</span>
											<h4>{frameTitle(paper.frame)}</h4>
										</div>
										<strong>{paper.frame.relevance}</strong>
									</div>
									<p>{paperContributionSummary(paper)}</p>
									<div class="paper-contribution-card__metrics">
										<div>
											<strong>{paper.units.length}</strong>
											<span>{$t('research.objectives.evidenceUnits')}</span>
										</div>
										<div>
											<strong>{paper.routeCount}</strong>
											<span>{$t('research.objectives.routes')}</span>
										</div>
										<div>
											<strong>{paper.frame.relevant_tables.length}</strong>
											<span>{$t('research.objectiveWorkspace.relevantTables')}</span>
										</div>
									</div>
									<dl>
										<div>
											<dt>{$t('research.objectiveWorkspace.changedVariables')}</dt>
											<dd>{listLabel(paper.frame.changed_variables)}</dd>
										</div>
										<div>
											<dt>{$t('research.objectiveWorkspace.measuredScope')}</dt>
											<dd>{listLabel(paper.frame.measured_property_scope)}</dd>
										</div>
										<div>
											<dt>{$t('research.objectiveWorkspace.relevantSections')}</dt>
											<dd>{listLabel(paper.frame.relevant_sections)}</dd>
										</div>
									</dl>
									<a
										class="source-action"
										href={resolve('/collections/[id]/documents/[document_id]', {
											id: collectionId,
											document_id: paper.frame.document_id
										})}
									>
										{$t('research.objectiveWorkspace.openPaper')}
									</a>
								</article>
							{/each}
						</div>
					{:else}
						<div class="empty-panel">{$t('research.objectiveWorkspace.noFrames')}</div>
					{/if}
				</section>

				<section class="objective-section" bind:this={evidenceSection}>
					<div class="section-heading">
						<div>
							<h3>{$t('research.objectiveWorkspace.evidenceUnitsTitle')}</h3>
							<p>{$t('research.objectiveWorkspace.evidenceUnitsBody')}</p>
						</div>
						<span>{boolState(objectiveView.readiness.evidence_units_ready)}</span>
					</div>

					{#if representativeEvidenceUnits.length}
						<div class="supporting-evidence-list">
							{#each representativeEvidenceUnits as unit (unit.evidence_unit_id)}
								<button
									class:selected={selectedEvidenceUnit?.evidence_unit_id === unit.evidence_unit_id}
									type="button"
									on:click={() => focusEvidenceUnit(unit)}
								>
									<span>{$t(evidenceKindLabelKey(unit.unit_kind))}</span>
									<strong>{evidenceUnitValue(unit)}</strong>
									{#if evidenceCardFacts(unit).length}
										<div class="evidence-unit-card__facts">
											{#each evidenceCardFacts(unit) as fact, index (`supporting-${unit.evidence_unit_id}-${fact}-${index}`)}
												<span>{fact}</span>
											{/each}
										</div>
									{/if}
									<small>
										{evidenceCardSourceLabel(unit.document_id)} · {confidenceLabel(unit.confidence)}
									</small>
								</button>
							{/each}
						</div>
					{/if}

					{#if evidenceUnits.length}
						<details class="evidence-audit" bind:open={evidenceAuditOpen}>
							<summary>
								{$t('research.objectiveWorkspace.allEvidenceReview')}
								<span>{filteredEvidenceUnits.length}</span>
							</summary>
							<div class="evidence-audit__body">
								<div
									class="evidence-toolbar"
									aria-label={$t('research.objectiveWorkspace.evidenceFilters')}
								>
									<label>
										<span>{$t('research.objectiveWorkspace.evidenceKindFilter')}</span>
										<select bind:value={selectedEvidenceKind}>
											{#each evidenceKindOptions as option (option.value)}
												<option value={option.value}>
													{option.label} ({option.count})
												</option>
											{/each}
										</select>
									</label>
									<label>
										<span>{$t('research.objectiveWorkspace.paperFilter')}</span>
										<select bind:value={selectedEvidenceDocumentId}>
											{#each evidenceDocumentOptions as option (option.value)}
												<option value={option.value}>
													{option.label} ({option.count})
												</option>
											{/each}
										</select>
									</label>
								</div>
								{#if evidenceGroups.length}
									<div class="evidence-group-list">
										{#each evidenceGroups as group (group.kind)}
											<section class="evidence-group" aria-label={$t(group.labelKey)}>
												<div class="evidence-group__header">
													<h4>{$t(group.labelKey)}</h4>
													<span
														>{$t('research.objectiveWorkspace.unitCount', {
															count: group.units.length
														})}</span
													>
												</div>
												<div class="evidence-unit-list">
													{#each evidenceGroupPreview(group.units) as unit (unit.evidence_unit_id)}
														<button
															class:selected={selectedEvidenceUnit?.evidence_unit_id ===
																unit.evidence_unit_id}
															class="evidence-unit-card"
															type="button"
															on:click={() => (selectedEvidenceUnitId = unit.evidence_unit_id)}
														>
															<span>{evidenceUnitTitle(unit)}</span>
															<strong>{evidenceUnitValue(unit)}</strong>
															{#if evidenceCardFacts(unit).length}
																<div class="evidence-unit-card__facts">
																	{#each evidenceCardFacts(unit) as fact, index (`${fact}-${index}`)}
																		<span>{fact}</span>
																	{/each}
																</div>
															{/if}
															<small>
																{evidenceCardSourceLabel(unit.document_id)} · {confidenceLabel(
																	unit.confidence
																)}
															</small>
														</button>
													{/each}
												</div>
												{#if evidenceGroupHiddenCount(group.units)}
													<p class="evidence-group__limit-note">
														{$t('research.objectiveWorkspace.evidencePreviewLimit', {
															shown: EVIDENCE_GROUP_PREVIEW_LIMIT,
															total: group.units.length
														})}
													</p>
												{/if}
											</section>
										{/each}
									</div>
								{:else}
									<div class="empty-panel">{$t('research.objectiveWorkspace.noEvidenceUnits')}</div>
								{/if}
							</div>
						</details>
					{:else}
						<div class="empty-panel">{$t('research.objectiveWorkspace.noEvidenceUnits')}</div>
					{/if}
				</section>
			</div>

			<aside
				class="objective-side-panel"
				aria-label={$t('research.objectiveWorkspace.evidenceDetail')}
			>
				<div class="section-heading">
					<div>
						<h3>{$t('research.objectiveWorkspace.evidenceDetail')}</h3>
						<p>{$t('research.objectiveWorkspace.evidenceDetailBody')}</p>
					</div>
				</div>
				{#if selectedEvidenceUnit}
					<article class="evidence-detail">
						<div class="evidence-detail__header">
							<h4>{evidenceUnitTitle(selectedEvidenceUnit)}</h4>
							<span>{selectedEvidenceUnit.resolution_status}</span>
						</div>
						<section class="evidence-chain-section">
							<h5>{$t('research.objectiveWorkspace.finding')}</h5>
							<p>{evidenceUnitValue(selectedEvidenceUnit)}</p>
							<dl>
								<div>
									<dt>{$t('research.objectiveWorkspace.kind')}</dt>
									<dd>{selectedEvidenceUnit.unit_kind}</dd>
								</div>
								{#if selectedEvidenceUnit.property_normalized}
									<div>
										<dt>{$t('research.objectiveWorkspace.property')}</dt>
										<dd>{selectedEvidenceUnit.property_normalized}</dd>
									</div>
								{/if}
								{#if selectedEvidenceUnit.unit}
									<div>
										<dt>{$t('research.objectiveWorkspace.value')}</dt>
										<dd>{selectedEvidenceUnit.unit}</dd>
									</div>
								{/if}
								<div>
									<dt>{$t('research.objectiveWorkspace.confidence')}</dt>
									<dd>{confidenceLabel(selectedEvidenceUnit.confidence)}</dd>
								</div>
							</dl>
						</section>

						{#if recordEntries(selectedEvidenceUnit.sample_context).length || recordEntries(selectedEvidenceUnit.process_context).length}
							<section class="evidence-chain-section">
								<h5>{$t('research.objectiveWorkspace.sampleAndProcess')}</h5>
								<div class="evidence-context-list">
									{#each recordEntries(selectedEvidenceUnit.sample_context) as entry, index (`sample-${entry.key}-${index}`)}
										<span>{entry.key}: {entry.value}</span>
									{/each}
									{#each recordEntries(selectedEvidenceUnit.process_context) as entry, index (`process-${entry.key}-${index}`)}
										<span>{entry.key}: {entry.value}</span>
									{/each}
								</div>
							</section>
						{/if}

						{#if recordEntries(selectedEvidenceUnit.test_condition).length}
							<section class="evidence-chain-section">
								<h5>{$t('research.objectiveWorkspace.testCondition')}</h5>
								<div class="evidence-context-list">
									{#each recordEntries(selectedEvidenceUnit.test_condition) as entry, index (`test-${entry.key}-${index}`)}
										<span>{entry.key}: {entry.value}</span>
									{/each}
								</div>
							</section>
						{/if}

						{#if recordEntries(selectedEvidenceUnit.baseline_context).length}
							<section class="evidence-chain-section">
								<h5>{$t('research.objectiveWorkspace.comparisonBaseline')}</h5>
								<div class="evidence-context-list">
									{#each recordEntries(selectedEvidenceUnit.baseline_context) as entry, index (`baseline-${entry.key}-${index}`)}
										<span>{entry.key}: {entry.value}</span>
									{/each}
								</div>
							</section>
						{/if}

						{#if recordEntries(selectedEvidenceUnit.resolved_condition).length}
							<section class="evidence-chain-section">
								<h5>{$t('research.objectiveWorkspace.resolvedCondition')}</h5>
								<div class="evidence-context-list">
									{#each recordEntries(selectedEvidenceUnit.resolved_condition) as entry, index (`resolved-${entry.key}-${index}`)}
										<span>{entry.key}: {entry.value}</span>
									{/each}
								</div>
							</section>
						{/if}

						<section class="evidence-chain-section evidence-source-list">
							<h5>{$t('research.objectiveWorkspace.sourceTraceback')}</h5>
							{#each sourceEntries(selectedEvidenceUnit) as source, index (`${source.label}-${index}`)}
								{#if source.documentId}
									<!-- eslint-disable svelte/no-navigation-without-resolve -->
									<a
										href={`${resolve('/collections/[id]/documents/[document_id]', {
											id: collectionId,
											document_id: source.documentId
										})}${source.query}`}>{source.label}</a
									>
									<!-- eslint-enable svelte/no-navigation-without-resolve -->
								{:else}
									<span>{source.label}</span>
								{/if}
							{/each}
						</section>
					</article>
				{:else}
					<div class="empty-panel">{$t('research.objectiveWorkspace.noEvidenceUnits')}</div>
				{/if}
			</aside>
			</section>
		</details>

		<section class="objective-section objective-diagnostics">
			<div class="section-heading">
				<div>
					<h3>{$t('research.objectiveWorkspace.diagnosticsTitle')}</h3>
					<p>{$t('research.objectiveWorkspace.diagnosticsBody')}</p>
				</div>
			</div>
			<div class="diagnostics-grid">
				<details>
					<summary>
						{$t('research.objectiveWorkspace.framesTitle')}
						<span>{frames.length}</span>
					</summary>
					{#if frames.length}
						<div class="diagnostic-list">
							{#each frames as frame (frame.frame_id)}
								<article>
									<strong>{frameTitle(frame)}</strong>
									<span>{frame.relevance} · {frame.paper_role}</span>
									<p>
										{$t('research.objectiveWorkspace.relevantSections')}:
										{listLabel(frame.relevant_sections)}
									</p>
								</article>
							{/each}
						</div>
					{:else}
						<div class="empty-panel">{$t('research.objectiveWorkspace.noFrames')}</div>
					{/if}
				</details>
				<details>
					<summary>
						{$t('research.objectiveWorkspace.routesTitle')}
						<span>{evidenceRoutes.length}</span>
					</summary>
					{#if evidenceRoutes.length}
						<div class="route-table-wrap">
							<table class="route-table">
								<thead>
									<tr>
										<th>{$t('research.objectiveWorkspace.source')}</th>
										<th>{$t('research.objectiveWorkspace.role')}</th>
										<th>{$t('research.objectiveWorkspace.extractable')}</th>
										<th>{$t('research.objectiveWorkspace.schema')}</th>
									</tr>
								</thead>
								<tbody>
									{#each evidenceRoutes as route (route.route_id)}
										<tr>
											<td>{route.source_kind}: {route.source_ref}</td>
											<td>{route.role}</td>
											<td>{boolState(route.extractable)}</td>
											<td>{routeSchemaLabel(route.table_schema)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{:else}
						<div class="empty-panel">{$t('research.objectiveWorkspace.noRoutes')}</div>
					{/if}
				</details>
			</div>
		</section>
	{/if}
</section>

<style>
	.objective-workspace {
		width: 100%;
		max-width: 1320px;
		margin: 0 auto;
		display: grid;
		gap: 18px;
		min-width: 0;
	}

	.objective-workspace > * {
		min-width: 0;
		max-width: 100%;
	}

	.back-link,
	.source-action,
	.evidence-source-list a {
		width: fit-content;
		color: var(--color-accent);
		font-size: 14px;
		text-decoration: none;
	}

	.objective-hero,
	.objective-state-card,
	.objective-report-aside,
	.objective-section,
	.objective-side-panel,
	.objective-audit-shell {
		box-sizing: border-box;
		min-width: 0;
		max-width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.objective-hero {
		display: flex;
		justify-content: space-between;
		gap: 24px;
		padding: 26px;
		min-width: 0;
	}

	.objective-hero__main {
		display: grid;
		gap: 10px;
		min-width: 0;
	}

	.objective-eyebrow {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objective-hero h2,
	.objective-state-card h2,
	.objective-section h3,
	.objective-section h4,
	.objective-side-panel h3,
	.objective-side-panel h4,
	.objective-side-panel h5 {
		margin: 0;
		color: var(--text-primary);
	}

	.objective-hero h2 {
		max-width: 900px;
		font-size: 30px;
		line-height: 38px;
		overflow-wrap: anywhere;
	}

	.objective-hero p,
	.section-heading p,
	.comparison-readiness p,
	.paper-contribution-card p,
	.evidence-detail p,
	.diagnostic-list p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		overflow-wrap: anywhere;
	}

	.objective-hero__status {
		min-width: 150px;
		display: grid;
		justify-items: end;
		align-content: start;
		gap: 8px;
		color: var(--text-secondary);
	}

	.objective-hero__status strong {
		color: var(--text-primary);
		font-size: 28px;
		line-height: 34px;
	}

	.objective-hero__assistant-link {
		margin-top: 6px;
		padding: 8px 12px;
		border: 1px solid var(--border-subtle);
		border-radius: 8px;
		color: var(--accent-strong);
		font-size: 13px;
		font-weight: 700;
		text-decoration: none;
	}

	.objective-hero__assistant-link:hover {
		background: var(--bg-subtle);
	}

	.objective-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 0;
	}

	.objective-chip-row span,
	.evidence-detail__header span,
	.evidence-group__header span,
	.objective-audit-shell summary span,
	.diagnostics-grid summary span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 5px 10px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--bg-subtle);
		max-width: 100%;
		overflow-wrap: anywhere;
	}

	.objective-state-card {
		display: grid;
		gap: 8px;
		padding: 24px;
	}

	.objective-state-card--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.objective-report-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
		gap: 18px;
		align-items: start;
	}

	.objective-section,
	.objective-report-aside,
	.objective-side-panel {
		padding: 20px;
	}

	.objective-section,
	.objective-report-aside,
	.objective-side-panel,
	.objective-audit-shell,
		.objective-main-column,
		.objective-summary-list,
		.research-focus,
		.representative-evidence,
		.evidence-group-list,
		.evidence-group,
		.paper-contribution-list,
		.evidence-detail,
		.evidence-chain-section,
		.evidence-context-list,
		.evidence-source-list,
		.evidence-audit,
		.evidence-audit__body,
		.supporting-evidence-list,
		.evidence-unit-list,
		.evidence-toolbar {
		display: grid;
		gap: 14px;
		min-width: 0;
		max-width: 100%;
	}

	.objective-summary-list span,
	.objective-summary-panel__heading span,
	.section-heading > span,
	.paper-contribution-card dt,
	.evidence-detail dt,
	.route-table th {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objective-summary-panel__heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
	}

	.objective-summary-panel__heading strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 18px;
	}

	.objective-summary-list {
		gap: 0;
	}

	.objective-summary-list article {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: baseline;
		gap: 12px;
		border-top: 1px solid var(--border-default);
		padding: 13px 0;
	}

	.objective-summary-list article:first-child {
		border-top: 0;
		padding-top: 0;
	}

	.objective-summary-list article:last-child {
		padding-bottom: 0;
	}

	.objective-summary-list strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.section-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
	}

	.section-heading > div {
		display: grid;
		gap: 5px;
		min-width: 0;
	}

	.research-focus span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objective-report-document,
	.objective-report-empty {
		display: grid;
		gap: 18px;
		min-width: 0;
	}

	.objective-report-document {
		max-width: 920px;
		padding: 4px 0 16px;
	}

	.objective-report-reader-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		border-bottom: 1px solid var(--border-default);
		padding-bottom: 16px;
		min-width: 0;
	}

	.objective-report-reader-header div:first-child {
		display: grid;
		gap: 5px;
		min-width: 0;
	}

	.objective-report-reader-header h3 {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.objective-report-reader-header p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.objective-report-document__meta,
	.objective-report-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 0;
	}

	.objective-report-document__meta span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 9px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--bg-subtle);
	}

	.objective-report-document h1,
	.objective-report-document h2,
	.objective-report-document h3,
	.objective-report-empty h4 {
		margin: 0;
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.objective-report-document h1 {
		font-size: 28px;
		line-height: 36px;
	}

	.objective-report-document h2 {
		margin-top: 12px;
		border-top: 1px solid var(--border-default);
		padding-top: 22px;
		font-size: 21px;
		line-height: 30px;
	}

	.objective-report-document h3,
	.objective-report-empty h4 {
		font-size: 17px;
		line-height: 24px;
	}

	.objective-report-document p,
	.objective-report-document li,
	.objective-report-empty p {
		margin: 0;
		color: var(--text-primary);
		font-size: 15px;
		line-height: 26px;
		overflow-wrap: anywhere;
	}

	.objective-report-document__list {
		display: grid;
		gap: 7px;
		margin: 0;
		padding-left: 22px;
	}

	.objective-report-table-wrap {
		overflow-x: auto;
		max-width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.objective-report-table {
		width: 100%;
		min-width: 640px;
		border-collapse: collapse;
		background: var(--surface-card);
	}

	.objective-report-table th,
	.objective-report-table td {
		border-bottom: 1px solid var(--border-default);
		padding: 10px 12px;
		text-align: left;
		vertical-align: top;
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.objective-report-table th {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
		background: var(--bg-subtle);
	}

	.objective-report-table td {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.objective-report-table tr:last-child td {
		border-bottom: 0;
	}

	.objective-report-actions button {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 9px 12px;
		color: var(--text-primary);
		background: var(--surface-card);
		cursor: pointer;
		font: inherit;
		font-weight: 650;
	}

	.objective-report-actions--compact {
		justify-content: flex-end;
		flex: 0 0 auto;
	}

	.objective-report-actions--compact button {
		padding: 7px 10px;
		font-size: 13px;
	}

	.objective-report-actions button:hover:not(:disabled) {
		border-color: var(--color-accent);
	}

	.objective-report-actions button:disabled {
		cursor: wait;
		opacity: 0.65;
	}

	.objective-report-error {
		color: var(--danger-text);
	}

	.research-focus h4,
	.representative-evidence h4,
	.comparison-readiness h4 {
		margin: 0;
		color: var(--text-primary);
		font-size: 15px;
		line-height: 21px;
	}

	.research-focus__grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 10px;
	}

	.objective-report-aside .research-focus__grid {
		grid-template-columns: 1fr;
	}

		.research-focus__grid div,
		.comparison-readiness {
			border: 1px solid var(--border-default);
			border-radius: var(--radius-md);
			padding: 12px;
			background: var(--bg-subtle);
		}

	.research-focus__grid p {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
		overflow-wrap: anywhere;
	}

	.evidence-readiness {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 8px;
	}

	.objective-report-aside .evidence-readiness {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.evidence-readiness button {
		display: grid;
		gap: 4px;
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		text-align: left;
		background: var(--bg-subtle);
		cursor: pointer;
		font: inherit;
	}

	.evidence-readiness button:hover,
	.evidence-readiness button.ready {
		border-color: var(--color-accent);
		background: var(--surface-card);
	}

	.evidence-readiness strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 28px;
	}

	.evidence-readiness span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 17px;
	}

	.comparison-readiness {
		display: grid;
		gap: 4px;
	}

	.comparison-readiness--ready {
		border-color: var(--success-border);
		background: var(--success-bg);
	}

	.comparison-readiness--limited {
		border-color: var(--warning-border);
		background: var(--warning-bg);
	}

	.representative-evidence__heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
	}

	.representative-evidence__list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.evidence-group__header,
	.evidence-detail__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 10px;
	}

	.evidence-group h4,
	.evidence-detail h4 {
		font-size: 15px;
		line-height: 21px;
	}

	.evidence-chain-section h5 {
		font-size: 13px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.paper-contribution-card dd,
	.evidence-detail dd,
	.evidence-context-list span,
	.evidence-source-list span,
	.evidence-source-list a,
	.route-table td {
		overflow-wrap: anywhere;
	}

	.objective-workspace-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
		gap: 16px;
		align-items: start;
		min-width: 0;
		max-width: 100%;
	}

	.paper-contribution-card {
		display: grid;
		gap: 13px;
		min-width: 0;
		max-width: 100%;
		box-sizing: border-box;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 16px;
		background: var(--bg-subtle);
	}

	.paper-contribution-card__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
		min-width: 0;
	}

	.paper-contribution-card__header div {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.paper-contribution-card__header h4 {
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.paper-contribution-card__header span,
	.paper-contribution-card__header strong,
	.paper-contribution-card__metrics span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.paper-contribution-card__header strong {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 9px;
		background: var(--surface-card);
	}

	.paper-contribution-card__metrics {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}

	.paper-contribution-card__metrics div {
		display: grid;
		gap: 2px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--surface-card);
	}

	.paper-contribution-card__metrics strong {
		color: var(--text-primary);
		font-size: 20px;
		line-height: 24px;
	}

	.paper-contribution-card dl,
	.evidence-detail dl {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
		margin: 0;
	}

	.paper-contribution-card dd,
	.evidence-detail dd {
		margin: 4px 0 0;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
	}

	.supporting-evidence-list,
	.evidence-unit-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.evidence-toolbar {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}

	.evidence-toolbar label {
		display: grid;
		gap: 6px;
		min-width: 0;
	}

	.evidence-toolbar span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.evidence-toolbar select {
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 9px 11px;
		color: var(--text-primary);
		background: var(--surface-card);
		font: inherit;
	}

	.supporting-evidence-list button,
	.evidence-unit-card {
		overflow: hidden;
		display: grid;
		gap: 5px;
		width: 100%;
		min-width: 0;
		max-width: 100%;
		box-sizing: border-box;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		text-align: left;
		background: var(--bg-subtle);
		cursor: pointer;
	}

	.supporting-evidence-list button:hover,
	.supporting-evidence-list button.selected,
	.evidence-unit-card:hover,
	.evidence-unit-card.selected {
		border-color: var(--color-accent);
		background: var(--surface-card);
	}

	.supporting-evidence-list button > span,
	.supporting-evidence-list button small,
	.evidence-unit-card span,
	.evidence-unit-card small {
		min-width: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.supporting-evidence-list button > strong,
	.evidence-unit-card strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
		font-weight: 600;
		overflow-wrap: anywhere;
	}

	.evidence-unit-card__facts {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		min-width: 0;
		max-width: 100%;
		overflow: hidden;
	}

	.evidence-unit-card__facts span {
		max-width: 100%;
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 3px 7px;
		background: var(--surface-card);
		overflow: hidden;
		overflow-wrap: anywhere;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.evidence-unit-card span,
	.evidence-unit-card small {
		max-width: 100%;
	}

	.evidence-group__limit-note {
		margin: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 9px 11px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		background: var(--surface-card);
	}

	.evidence-audit {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-subtle);
		min-width: 0;
		max-width: 100%;
		box-sizing: border-box;
	}

	.evidence-audit summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 13px 14px;
		color: var(--text-primary);
		cursor: pointer;
	}

	.evidence-audit summary span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 9px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--surface-card);
	}

	.evidence-audit__body {
		display: grid;
		gap: 14px;
		border-top: 1px solid var(--border-default);
		padding: 14px;
		min-width: 0;
		max-width: 100%;
		box-sizing: border-box;
	}

	.objective-side-panel {
		position: sticky;
		top: 18px;
	}

	.evidence-chain-section {
		border-top: 1px solid var(--border-default);
		padding-top: 12px;
	}

	.evidence-detail .evidence-chain-section:first-of-type {
		border-top: 0;
		padding-top: 0;
	}

	.evidence-context-list,
	.evidence-source-list {
		gap: 6px;
	}

	.evidence-context-list span,
	.evidence-source-list span {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.objective-audit-shell {
		padding: 0;
		overflow: hidden;
	}

	.objective-audit-shell > summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 16px 20px;
		color: var(--text-primary);
		cursor: pointer;
	}

	.objective-audit-shell > .objective-workspace-grid {
		border-top: 1px solid var(--border-default);
		padding: 16px;
	}

	.diagnostics-grid {
		display: grid;
		gap: 12px;
	}

	.diagnostics-grid details {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-subtle);
	}

	.diagnostics-grid summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 14px;
		color: var(--text-primary);
		cursor: pointer;
	}

	.diagnostic-list {
		display: grid;
		gap: 10px;
		padding: 0 14px 14px;
	}

	.diagnostic-list article {
		display: grid;
		gap: 4px;
		border-top: 1px solid var(--border-default);
		padding-top: 10px;
	}

	.diagnostic-list strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.diagnostic-list span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.route-table-wrap {
		overflow-x: auto;
		padding: 0 14px 14px;
		max-width: 100%;
		box-sizing: border-box;
	}

	.route-table {
		width: 100%;
		min-width: 0;
		border-collapse: collapse;
		table-layout: fixed;
	}

	.route-table th,
	.route-table td {
		border-bottom: 1px solid var(--border-default);
		padding: 10px 8px;
		text-align: left;
		vertical-align: top;
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.route-table td {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.empty-panel {
		border: 1px dashed var(--border-default);
		border-radius: var(--radius-md);
		padding: 16px;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		background: var(--bg-subtle);
	}

	@media (max-width: 1040px) {
		.objective-report-layout,
		.objective-workspace-grid {
			grid-template-columns: 1fr;
		}

		.objective-side-panel {
			position: static;
		}
	}

	@media (max-width: 760px) {
		.objective-workspace {
			gap: 12px;
			max-width: 100%;
			overflow: hidden;
		}

		.objective-hero,
		.objective-report-reader-header,
		.section-heading,
		.evidence-group__header,
		.paper-contribution-card__header,
		.representative-evidence__heading,
		.evidence-detail__header {
			flex-direction: column;
		}

		.objective-hero {
			display: grid;
			padding: 20px 16px;
		}

		.objective-hero__main,
		.objective-hero__status {
			width: 100%;
			min-width: 0;
		}

		.objective-hero h2 {
			font-size: 26px;
			line-height: 34px;
		}

		.objective-hero__status {
			justify-items: start;
		}

			.evidence-toolbar,
			.supporting-evidence-list,
			.evidence-unit-list,
			.evidence-readiness,
			.research-focus__grid,
			.representative-evidence__list,
		.paper-contribution-card__metrics,
		.paper-contribution-card dl,
		.evidence-detail dl {
			grid-template-columns: 1fr;
		}

		.evidence-unit-card__facts {
			display: grid;
			grid-template-columns: 1fr;
		}

		.evidence-unit-card__facts span {
			white-space: normal;
			text-overflow: clip;
		}
	}
</style>
