<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
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

	type LogicStep = {
		step_id: string;
		titleKey: string;
		count: number;
		ready: boolean;
		items: string[];
		emptyKey: string;
		evidenceKind: string | null;
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

	type ScientificJudgementItem = {
		id: string;
		title: string;
		body: string;
		meta: string[];
		unit?: ObjectiveEvidenceUnit;
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

	const evidenceKindOrder = [
		'measurement',
		'test_condition',
		'characterization',
		'comparison',
		'interpretation'
	];
	const EVIDENCE_GROUP_PREVIEW_LIMIT = 6;
	const SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT = 3;

	let objectiveView: ObjectiveResearchView | null = null;
	let loading = false;
	let error = '';
	let loadedKey = '';
	let selectedEvidenceUnitId = '';
	let selectedEvidenceKind = 'all';
	let selectedEvidenceDocumentId = 'all';
	let evidenceAuditOpen = false;
	let evidenceSection: HTMLElement | null = null;

	$: collectionId = $page.params.id ?? '';
	$: objectiveId = $page.params.objective_id ?? '';
	$: loadKey = `${collectionId}:${objectiveId}`;
	$: frames = objectiveView?.paper_frames ?? [];
	$: evidenceUnits = objectiveView?.evidence_units ?? [];
	$: evidenceRoutes = objectiveView?.evidence_routes ?? [];
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
	$: logicSteps = objectiveView ? buildLogicSteps(objectiveView) : [];
	$: researchFocusGroups = objectiveView ? buildResearchFocusGroups(objectiveView) : [];
	$: evidenceReadinessItems = objectiveView ? buildEvidenceReadinessItems(objectiveView) : [];
	$: comparisonReadiness = objectiveView ? buildComparisonReadiness(objectiveView) : null;
	$: controlledComparisonItems = buildControlledComparisonItems(evidenceUnits);
	$: mechanismInterpretationItems = buildMechanismInterpretationItems(evidenceUnits);
	$: limitationItems = objectiveView ? buildLimitationItems(objectiveView) : [];
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
		} catch (err) {
			objectiveView = null;
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	function listLabel(items: string[]) {
		return items.length ? items.join(', ') : $t('research.emptyValue');
	}

	function frameTitle(frame: ObjectivePaperFrame) {
		return frame.title || frame.source_filename || frame.document_id;
	}

	function collectionConclusionText(view: ObjectiveResearchView) {
		const summary = view.logic_chain?.summary || view.objective.comparison_intent || '';
		const prefix = `${view.objective.question}:`;
		const normalizedSummary = summary.trim();
		if (normalizedSummary.startsWith(prefix)) {
			return normalizedSummary.slice(prefix.length).trim();
		}
		return normalizedSummary || $t('research.objectiveWorkspace.noLogicChain');
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

	function recordEntries(record: Record<string, unknown>, limit = 5) {
		return Object.entries(record)
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
		const [entry] = recordEntries(record, 1);
		return entry ? `baseline: ${entry.value}` : '';
	}

	function evidenceCardEntries(record: Record<string, unknown>, limit = 5) {
		const verboseKeys = new Set(['detail', 'details', 'source_text', 'raw_text', 'statement']);
		return recordEntries(record, limit).filter((entry) => !verboseKeys.has(entry.key.toLowerCase()));
	}

	function evidenceCardFacts(unit: ObjectiveEvidenceUnit) {
		return [
			...evidenceCardEntries(unit.sample_context, 1).map((entry) => `${entry.key}: ${entry.value}`),
			...evidenceCardEntries(unit.process_context, 2).map((entry) => `${entry.key}: ${entry.value}`),
			...evidenceCardEntries(unit.test_condition, 1).map((entry) => `${entry.key}: ${entry.value}`),
			baselineCardFact(unit.baseline_context)
		]
			.filter(Boolean)
			.slice(0, 4);
	}

	function sourceRefLabel(sourceRef: Record<string, unknown>) {
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
			...Object.keys(counts).filter((kind) => !evidenceKindOrder.includes(kind)).sort()
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

	function comparisonDirectionLabel(value: unknown) {
		const direction = displayValue(value).toLowerCase();
		if (direction === 'increase') return $t('research.objectiveWorkspace.directionIncrease');
		if (direction === 'decrease') return $t('research.objectiveWorkspace.directionDecrease');
		if (direction === 'no_change') return $t('research.objectiveWorkspace.directionNoChange');
		return direction || $t('research.objectiveWorkspace.directionObserved');
	}

	function valueWithUnit(value: unknown, unit: string | null) {
		const text = displayValue(value);
		if (!text) return '';
		if (!unit || text.includes(unit)) return text;
		return `${text} ${unit}`;
	}

	function controlledAxesSummary(unit: ObjectiveEvidenceUnit) {
		const axes = displayValue(unit.value_payload.controlled_axes);
		return axes ? $t('research.objectiveWorkspace.controlledAxes', { axes }) : '';
	}

	function comparisonBody(unit: ObjectiveEvidenceUnit) {
		const statement = displayValue(unit.value_payload.statement) || displayValue(unit.interpretation);
		if (statement) return statement;
		const property = unit.property_normalized || $t('research.objectiveWorkspace.measurementResults');
		const current = valueWithUnit(
			unit.value_payload.current_value ?? unit.value_payload.value,
			unit.unit
		);
		const baseline = valueWithUnit(unit.baseline_context.value, unit.unit);
		if (current && baseline) {
			return $t('research.objectiveWorkspace.comparisonGeneratedBody', {
				property,
				current,
				baseline,
				direction: comparisonDirectionLabel(unit.value_payload.direction)
			});
		}
		return evidenceUnitValue(unit);
	}

	function judgementMeta(unit: ObjectiveEvidenceUnit, extra: string[] = []) {
		return [
			...extra,
			...evidenceCardFacts(unit),
			evidenceCardSourceLabel(unit.document_id),
			confidenceLabel(unit.confidence)
		]
			.filter(Boolean)
			.slice(0, 5);
	}

	function buildControlledComparisonItems(units: ObjectiveEvidenceUnit[]): ScientificJudgementItem[] {
		return units
			.filter((unit) => unit.unit_kind === 'comparison')
			.sort((left, right) => right.confidence - left.confidence)
			.slice(0, SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT)
			.map((unit) => ({
				id: unit.evidence_unit_id,
				title: unit.property_normalized || $t('research.objectiveWorkspace.comparisonEvidence'),
				body: comparisonBody(unit),
				meta: judgementMeta(unit, [controlledAxesSummary(unit)]),
				unit
			}));
	}

	function buildMechanismInterpretationItems(
		units: ObjectiveEvidenceUnit[]
	): ScientificJudgementItem[] {
		return units
			.filter((unit) => unit.unit_kind === 'interpretation')
			.sort((left, right) => right.confidence - left.confidence)
			.slice(0, SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT)
			.map((unit) => ({
				id: unit.evidence_unit_id,
				title: unit.property_normalized || $t('research.objectiveWorkspace.authorInterpretations'),
				body: displayValue(unit.interpretation) || evidenceUnitValue(unit),
				meta: judgementMeta(unit),
				unit
			}));
	}

	function humanizeGapCode(value: string) {
		const normalized = value.trim();
		if (!normalized) return '';
		const labelKey = `research.objectiveWorkspace.gapLabels.${normalized}`;
		const translated = $t(labelKey);
		if (translated !== labelKey) return translated;
		return normalized.replace(/_/g, ' ');
	}

	function unresolvedEvidenceItems(units: ObjectiveEvidenceUnit[]): ScientificJudgementItem[] {
		return units
			.filter((unit) => unit.resolution_status && unit.resolution_status !== 'resolved')
			.sort((left, right) => right.confidence - left.confidence)
			.slice(0, SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT)
			.map((unit) => ({
				id: `unresolved-${unit.evidence_unit_id}`,
				title: unit.property_normalized || $t(evidenceKindLabelKey(unit.unit_kind)),
				body: $t('research.objectiveWorkspace.unresolvedEvidenceBody', {
					status: unit.resolution_status,
					value: evidenceUnitValue(unit)
				}),
				meta: judgementMeta(unit),
				unit
			}));
	}

	function buildLimitationItems(view: ObjectiveResearchView): ScientificJudgementItem[] {
		const gapItems = chainGaps(view)
			.slice(0, SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT)
			.map((gap) => ({
				id: `gap-${gap}`,
				title: $t('research.objectiveWorkspace.logicGap'),
				body: humanizeGapCode(gap),
				meta: [$t('research.objectiveWorkspace.logicChainTitle')]
			}));
		return [...gapItems, ...unresolvedEvidenceItems(view.evidence_units)].slice(
			0,
			SCIENTIFIC_JUDGEMENT_PREVIEW_LIMIT
		);
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

	function textList(value: unknown): string[] {
		if (typeof value === 'string' || typeof value === 'number') {
			const text = displayValue(value);
			return text ? [text] : [];
		}
		if (Array.isArray(value)) {
			return value.map((item) => displayValue(item)).filter(Boolean);
		}
		if (value && typeof value === 'object') {
			return Object.values(value as Record<string, unknown>)
				.map((item) => displayValue(item))
				.filter(Boolean);
		}
		return [];
	}

	function chainGaps(view: ObjectiveResearchView) {
		const payload = view.logic_chain?.chain_payload ?? {};
		const crossPaper = payload.cross_paper;
		const crossPaperRecord =
			crossPaper && typeof crossPaper === 'object' && !Array.isArray(crossPaper)
				? (crossPaper as Record<string, unknown>)
				: {};
		return [...textList(payload.gaps), ...textList(crossPaperRecord.gaps)];
	}

	function buildLogicSteps(view: ObjectiveResearchView): LogicStep[] {
		const measurements = unitsByKind(view.evidence_units, 'measurement');
		const conditions = unitsByKind(view.evidence_units, 'test_condition');
		const observations = unitsByKind(view.evidence_units, 'characterization');
		const comparisons = unitsByKind(view.evidence_units, 'comparison');
		const gaps = chainGaps(view);
		const scopeItems = [
			...view.objective.material_scope,
			...view.objective.process_axes,
			...view.objective.property_axes
		];

		return [
			{
				step_id: 'scope',
				titleKey: 'research.objectiveWorkspace.scopeStep',
				count: scopeItems.length,
				ready: view.readiness.objectives_ready,
				items: scopeItems.slice(0, 5),
				emptyKey: 'research.objectiveWorkspace.noScope',
				evidenceKind: null
			},
			{
				step_id: 'coverage',
				titleKey: 'research.objectiveWorkspace.coverageStep',
				count: relevantFrameCount,
				ready: view.readiness.frames_ready,
				items: frames
					.filter((frame) => frame.relevance !== 'irrelevant')
					.slice(0, 4)
					.map((frame) => frameTitle(frame)),
				emptyKey: 'research.objectiveWorkspace.noCoverage',
				evidenceKind: null
			},
			{
				step_id: 'conditions',
				titleKey: 'research.objectiveWorkspace.conditionsStep',
				count: conditions.length,
				ready: view.readiness.evidence_units_ready,
				items: conditions.slice(0, 4).map((unit) => evidenceUnitValue(unit)),
				emptyKey: 'research.objectiveWorkspace.noConditions',
				evidenceKind: 'test_condition'
			},
			{
				step_id: 'measurements',
				titleKey: 'research.objectiveWorkspace.measurementsStep',
				count: measurements.length,
				ready: view.readiness.evidence_units_ready,
				items: measurements.slice(0, 4).map((unit) => evidenceUnitValue(unit)),
				emptyKey: 'research.objectiveWorkspace.noMeasurements',
				evidenceKind: 'measurement'
			},
			{
				step_id: 'observations',
				titleKey: 'research.objectiveWorkspace.observationsStep',
				count: observations.length,
				ready: view.readiness.evidence_units_ready,
				items: observations.slice(0, 4).map((unit) => evidenceUnitValue(unit)),
				emptyKey: 'research.objectiveWorkspace.noObservations',
				evidenceKind: 'characterization'
			},
			{
				step_id: 'gaps',
				titleKey: 'research.objectiveWorkspace.gapsStep',
				count: gaps.length || comparisons.length,
				ready: view.readiness.logic_chain_ready,
				items: (
					gaps.length
						? gaps.map((gap) => humanizeGapCode(gap))
						: comparisons.map((unit) => evidenceUnitValue(unit))
				).slice(0, 4),
				emptyKey: 'research.objectiveWorkspace.noGaps',
				evidenceKind: 'comparison'
			}
		];
	}

	function focusLogicStepEvidence(step: LogicStep) {
		focusEvidenceKind(step.evidenceKind);
	}

	function focusEvidenceKind(kind: string | null) {
		selectedEvidenceKind = kind ?? 'all';
		selectedEvidenceDocumentId = 'all';
		selectedEvidenceUnitId = '';
		evidenceAuditOpen = true;
		evidenceSection?.scrollIntoView({ block: 'start', behavior: 'smooth' });
	}

	function focusEvidenceUnit(unit: ObjectiveEvidenceUnit) {
		selectedEvidenceKind = unit.unit_kind;
		selectedEvidenceDocumentId = unit.document_id || 'all';
		selectedEvidenceUnitId = unit.evidence_unit_id;
		evidenceAuditOpen = true;
		evidenceSection?.scrollIntoView({ block: 'start', behavior: 'smooth' });
	}

	function focusJudgementItem(item: ScientificJudgementItem) {
		if (item.unit) focusEvidenceUnit(item.unit);
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
			</div>
		</header>

		<section class="objective-primary-grid">
			<section class="objective-section objective-section--conclusion">
				<div class="section-heading">
					<div>
						<h3>{$t('research.objectiveWorkspace.conclusionPackageTitle')}</h3>
						<p>{$t('research.objectiveWorkspace.conclusionPackageBody')}</p>
					</div>
					<span>{boolState(objectiveView.readiness.logic_chain_ready)}</span>
				</div>

				<div class="collection-conclusion">
					<span>{$t('research.objectiveWorkspace.collectionConclusion')}</span>
					<strong>{collectionConclusionText(objectiveView)}</strong>
				</div>

				<div
					class="scientific-judgement-grid"
					aria-label={$t('research.objectiveWorkspace.scientificJudgements')}
				>
					<section>
						<div class="scientific-judgement-grid__heading">
							<h4>{$t('research.objectiveWorkspace.controlledComparisons')}</h4>
							<span>{controlledComparisonItems.length}</span>
						</div>
						{#if controlledComparisonItems.length}
							<div class="judgement-list">
								{#each controlledComparisonItems as item (item.id)}
									<button type="button" on:click={() => focusJudgementItem(item)}>
										<strong>{item.title}</strong>
										<p>{item.body}</p>
										{#if item.meta.length}
											<small>{item.meta.join(' · ')}</small>
										{/if}
									</button>
								{/each}
							</div>
						{:else}
							<p class="judgement-empty">
								{$t('research.objectiveWorkspace.noControlledComparisons')}
							</p>
						{/if}
					</section>

					<section>
						<div class="scientific-judgement-grid__heading">
							<h4>{$t('research.objectiveWorkspace.mechanismInterpretations')}</h4>
							<span>{mechanismInterpretationItems.length}</span>
						</div>
						{#if mechanismInterpretationItems.length}
							<div class="judgement-list">
								{#each mechanismInterpretationItems as item (item.id)}
									<button type="button" on:click={() => focusJudgementItem(item)}>
										<strong>{item.title}</strong>
										<p>{item.body}</p>
										{#if item.meta.length}
											<small>{item.meta.join(' · ')}</small>
										{/if}
									</button>
								{/each}
							</div>
						{:else}
							<p class="judgement-empty">
								{$t('research.objectiveWorkspace.noMechanismInterpretations')}
							</p>
						{/if}
					</section>

					<section>
						<div class="scientific-judgement-grid__heading">
							<h4>{$t('research.objectiveWorkspace.limitations')}</h4>
							<span>{limitationItems.length}</span>
						</div>
						{#if limitationItems.length}
							<div class="judgement-list">
								{#each limitationItems as item (item.id)}
									{#if item.unit}
										<button type="button" on:click={() => focusJudgementItem(item)}>
											<strong>{item.title}</strong>
											<p>{item.body}</p>
											{#if item.meta.length}
												<small>{item.meta.join(' · ')}</small>
											{/if}
										</button>
									{:else}
										<article>
											<strong>{item.title}</strong>
											<p>{item.body}</p>
											{#if item.meta.length}
												<small>{item.meta.join(' · ')}</small>
											{/if}
										</article>
									{/if}
								{/each}
							</div>
						{:else}
							<p class="judgement-empty">{$t('research.objectiveWorkspace.noLimitations')}</p>
						{/if}
					</section>
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

				<div class="evidence-readiness" aria-label={$t('research.objectiveWorkspace.evidenceReadiness')}>
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

				{#if representativeEvidenceUnits.length}
					<div class="representative-evidence">
						<div class="representative-evidence__heading">
							<h4>{$t('research.objectiveWorkspace.representativeEvidence')}</h4>
							<span>{confidenceLabel(objectiveView.logic_chain?.confidence ?? 0)}</span>
						</div>
						<div class="representative-evidence__list">
							{#each representativeEvidenceUnits as unit (unit.evidence_unit_id)}
								<button type="button" on:click={() => focusEvidenceUnit(unit)}>
									<span>{$t(evidenceKindLabelKey(unit.unit_kind))}</span>
									<strong>{evidenceUnitValue(unit)}</strong>
									<small>{evidenceUnitTitle(unit)} · {confidenceLabel(unit.confidence)}</small>
								</button>
							{/each}
						</div>
					</div>
				{/if}
			</section>

			<aside class="objective-summary-panel" aria-label={$t('research.objectiveWorkspace.summary')}>
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
			</aside>

			<section class="objective-section objective-section--path">
				<div class="section-heading">
					<div>
						<h3>{$t('research.objectiveWorkspace.logicChainTitle')}</h3>
						<p>{$t('research.objectiveWorkspace.logicChainBody')}</p>
					</div>
				</div>
				<div class="logic-chain" aria-label={$t('research.objectiveWorkspace.logicChainTitle')}>
					{#each logicSteps as step (step.step_id)}
						<button
							class:logic-step--pending={!step.ready}
							class:selected={step.evidenceKind !== null && selectedEvidenceKind === step.evidenceKind}
							class="logic-step"
							type="button"
							on:click={() => focusLogicStepEvidence(step)}
						>
							<div class="logic-step__marker">{step.count}</div>
							<div class="logic-step__body">
								<div class="logic-step__header">
									<h4>{$t(step.titleKey)}</h4>
									<span>{boolState(step.ready)}</span>
								</div>
								{#if step.items.length}
									<ul>
										{#each step.items as item, index (`${item}-${index}`)}
											<li>{item}</li>
										{/each}
									</ul>
								{:else}
									<p>{$t(step.emptyKey)}</p>
								{/if}
							</div>
						</button>
					{/each}
				</div>
			</section>
		</section>

		<section class="objective-workspace-grid">
			<div class="objective-main-column">
				<section
					class="objective-section"
					aria-labelledby="paper-contribution-title"
				>
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
										{evidenceCardSourceLabel(unit.document_id)} · {confidenceLabel(
											unit.confidence
										)}
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
	.objective-summary-panel,
	.objective-section,
	.objective-side-panel {
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
	}

	.objective-hero p,
	.section-heading p,
	.logic-step p,
	.comparison-readiness p,
	.paper-contribution-card p,
	.evidence-detail p,
	.diagnostic-list p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
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

	.objective-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.objective-chip-row span,
	.evidence-detail__header span,
	.logic-step__header span,
	.evidence-group__header span,
	.diagnostics-grid summary span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 5px 10px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--bg-subtle);
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

	.objective-primary-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
		gap: 16px;
		align-items: start;
	}

	.objective-section--path {
		grid-column: 1 / -1;
	}

	.objective-section,
	.objective-summary-panel,
	.objective-side-panel {
		padding: 20px;
	}

	.objective-section,
	.objective-summary-panel,
	.objective-side-panel,
	.objective-main-column,
	.objective-summary-list,
	.collection-conclusion,
	.research-focus,
	.scientific-judgement-grid,
	.representative-evidence,
	.evidence-group-list,
	.evidence-group,
	.paper-contribution-list,
	.evidence-detail,
	.evidence-chain-section,
	.evidence-context-list,
	.evidence-source-list {
		display: grid;
		gap: 14px;
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

	.collection-conclusion {
		border-left: 3px solid var(--color-accent);
		padding: 4px 0 4px 14px;
	}

	.collection-conclusion span,
	.research-focus span,
	.representative-evidence__heading span,
	.representative-evidence button span,
	.representative-evidence button small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.collection-conclusion strong {
		color: var(--text-primary);
		font-size: 18px;
		line-height: 27px;
		font-weight: 650;
	}

	.research-focus h4,
	.scientific-judgement-grid h4,
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

	.research-focus__grid div,
	.scientific-judgement-grid section,
	.comparison-readiness {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.scientific-judgement-grid {
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.scientific-judgement-grid section,
	.judgement-list {
		display: grid;
		gap: 10px;
	}

	.scientific-judgement-grid__heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
	}

	.scientific-judgement-grid__heading span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 3px 8px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 16px;
		background: var(--surface-card);
	}

	.judgement-list button,
	.judgement-list article {
		display: grid;
		gap: 5px;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 11px;
		text-align: left;
		background: var(--surface-card);
		cursor: pointer;
		font: inherit;
	}

	.judgement-list button:hover {
		border-color: var(--color-accent);
	}

	.judgement-list strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.judgement-list p,
	.judgement-list small,
	.judgement-empty {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
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

	.representative-evidence button {
		display: grid;
		gap: 5px;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		text-align: left;
		background: var(--surface-card);
		cursor: pointer;
		font: inherit;
	}

	.representative-evidence button:hover {
		border-color: var(--color-accent);
	}

	.representative-evidence button strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 21px;
		font-weight: 600;
		overflow-wrap: anywhere;
		text-transform: none;
	}

	.logic-chain {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
	}

	.logic-step {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 12px;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 14px;
		text-align: left;
		background: var(--bg-subtle);
		cursor: pointer;
		font: inherit;
	}

	.logic-step:hover,
	.logic-step.selected {
		border-color: var(--color-accent);
		background: var(--surface-card);
	}

	.logic-step--pending {
		opacity: 0.72;
	}

	.logic-step__marker {
		width: 32px;
		height: 32px;
		border-radius: 999px;
		display: grid;
		place-items: center;
		background: var(--surface-card);
		color: var(--text-primary);
		font-weight: 700;
	}

	.logic-step__body {
		display: grid;
		gap: 8px;
		min-width: 0;
	}

	.logic-step__header,
	.evidence-group__header,
	.evidence-detail__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 10px;
	}

	.logic-step h4,
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

	.logic-step ul {
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.logic-step li,
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
	}

	.paper-contribution-card {
		display: grid;
		gap: 13px;
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
	}

	.paper-contribution-card__header div {
		display: grid;
		gap: 4px;
		min-width: 0;
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
		display: grid;
		gap: 5px;
		width: 100%;
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
	}

	.route-table {
		width: 100%;
		border-collapse: collapse;
	}

	.route-table th,
	.route-table td {
		border-bottom: 1px solid var(--border-default);
		padding: 10px 8px;
		text-align: left;
		vertical-align: top;
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
		.logic-chain,
		.objective-primary-grid,
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
		}

		.objective-hero,
		.section-heading,
		.logic-step__header,
		.evidence-group__header,
		.paper-contribution-card__header,
		.representative-evidence__heading,
		.evidence-detail__header {
			flex-direction: column;
		}

		.objective-hero__status {
			justify-items: start;
		}

		.evidence-toolbar,
		.supporting-evidence-list,
		.evidence-unit-list,
		.evidence-readiness,
		.scientific-judgement-grid,
		.research-focus__grid,
		.representative-evidence__list,
		.paper-contribution-card__metrics,
		.paper-contribution-card dl,
		.evidence-detail dl {
			grid-template-columns: 1fr;
		}
	}
</style>
