<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import {
		createResearchUnderstandingCuration,
		createResearchUnderstandingFeedback,
		fetchResearchUnderstandingFeedback,
		fetchResearchUnderstandingCurations,
		formatShortIdentifier,
		type ResearchUnderstanding,
		type ResearchUnderstandingClaim,
		type ResearchUnderstandingCuration,
		type ResearchUnderstandingPresentationEffect,
		type ResearchUnderstandingPresentationEvidence,
		type ResearchUnderstandingPresentationFinding,
		type ResearchUnderstandingPresentationContext,
		type ResearchUnderstandingRelation,
		type ResearchUnderstandingFeedbackIssueType,
		type ResearchUnderstandingFeedback,
		type ResearchUnderstandingFeedbackStatus
	} from '../../../_shared/researchView';

	export let understanding: ResearchUnderstanding | null = null;
	export let collectionId = '';
	export let returnTo = '';
	export let bodyKey = 'research.understanding.objectiveBody';
	export let titleId = 'research-understanding-title';

	const CLAIM_TYPE_ORDER = [
		'all',
		'finding',
		'measurement',
		'comparison',
		'mechanism',
		'limitation',
		'context'
	];
	const CLAIM_STATUS_ORDER = ['all', 'supported', 'limited', 'conflicted', 'unsupported'];
	const SUPPORT_GRADE_ORDER = ['all', 'strong', 'partial', 'weak', 'conflict', 'insufficient'];
	const FINDING_CONTEXT_DISPLAY_LIMIT = 3;
	const FEEDBACK_STATUS_OPTIONS: ResearchUnderstandingFeedbackStatus[] = [
		'correct',
		'partial',
		'incorrect',
		'unclear'
	];
	const FEEDBACK_ISSUE_OPTIONS: ResearchUnderstandingFeedbackIssueType[] = [
		'none',
		'evidence_not_grounded',
		'missing_evidence',
		'wrong_context',
		'wrong_relation',
		'overclaim',
		'unclear_statement',
		'other'
	];
	const CURATION_CLAIM_TYPE_OPTIONS = CLAIM_TYPE_ORDER.filter((type) => type !== 'all');
	const CURATION_STATUS_OPTIONS = CLAIM_STATUS_ORDER.filter((status) => status !== 'all');
	type FindingEvidenceRole = keyof ResearchUnderstandingPresentationFinding['evidence_bundle'];

	let selectedClaimType = 'all';
	let selectedClaimStatus = 'all';
	let selectedEffectId = '';
	let selectedFindingId = '';
	let detailMode = false;
	let activeReviewPanel: 'feedback' | 'curation' | '' = '';
	let curationClaimType = 'finding';
	let curationStatus = 'limited';
	let curationStatement = '';
	let curationEvidenceRefIds: string[] = [];
	let curationContextIds: string[] = [];
	let curationNote = '';
	let curationReviewer = '';
	let curationSubmitting = false;
	let curationMessage = '';
	let curationError = '';
	let curationLoadError = '';
	let curationsByTargetId = new Map<string, ResearchUnderstandingCuration>();
	let loadedCurationScopeKey = '';
	let lastCurationTargetId = '';
	let feedbackByTargetId = new Map<string, ResearchUnderstandingFeedback[]>();
	let loadedFeedbackScopeKey = '';
	let feedbackLoadError = '';
	let reviewQueueOnly = false;
	let feedbackStatus: ResearchUnderstandingFeedbackStatus = 'correct';
	let feedbackIssue: ResearchUnderstandingFeedbackIssueType = 'none';
	let feedbackNote = '';
	let feedbackReviewer = '';
	let feedbackSubmitting = false;
	let feedbackMessage = '';
	let feedbackError = '';
	let lastFeedbackTargetId = '';
	let lastUsesFindings = false;

	$: presentation = understanding?.presentation ?? null;
	$: presentationSummary = presentation?.summary ?? null;
	$: effectRows = presentation?.effects ?? [];
	$: allFindingRows = presentation?.findings ?? [];
	$: primaryFindingRows = presentation?.primary_findings ?? [];
	$: reviewQueueFindingRows = presentation?.review_queue_findings ?? [];
	$: findingRows = reviewQueueOnly ? reviewQueueFindingRows : primaryFindingRows;
	$: usesFindings =
		allFindingRows.length > 0 ||
		primaryFindingRows.length > 0 ||
		reviewQueueFindingRows.length > 0;
	$: if (usesFindings !== lastUsesFindings) {
		lastUsesFindings = usesFindings;
		selectedClaimStatus = 'all';
	}
	$: presentationEvidenceById = new Map(
		(presentation?.evidence_items ?? []).map((item) => [item.evidence_ref_id, item])
	);
	$: presentationContextById = new Map(
		(presentation?.context_summaries ?? []).map((item) => [item.context_id, item])
	);
	$: evidenceById = new Map(
		(understanding?.evidence_refs ?? []).map((ref) => [ref.evidence_ref_id, ref])
	);
	$: claims = understanding?.claims ?? [];
	$: claimById = new Map(claims.map((claim) => [claim.claim_id, claim]));
	$: relationById = new Map(
		(understanding?.relations ?? []).map((relation) => [relation.relation_id, relation])
	);
	$: reviewQueueClaimIds = new Set(
		claims
			.filter((claim) => shouldReviewClaim(claim, feedbackByTargetId))
			.map((claim) => claim.claim_id)
	);
	$: reviewQueueFindingIds = new Set(
		(reviewQueueFindingRows.length ? reviewQueueFindingRows : allFindingRows)
			.filter((finding) => {
				const feedback = [
					...(feedbackByTargetId.get(finding.finding_id) ?? []),
					...(feedbackByTargetId.get(finding.claim_id) ?? [])
				];
				return (
					finding.review_status === 'needs_review' ||
					feedback.some((item) => item.review_status !== 'correct' || item.issue_type !== 'none')
				);
			})
			.map((finding) => finding.finding_id)
	);
	$: filteredEffects = effectRows.filter(
		(effect) =>
			(selectedClaimType === 'all' || effect.claim_type === selectedClaimType) &&
			(selectedClaimStatus === 'all' || effect.support_status === selectedClaimStatus) &&
			(!reviewQueueOnly || effect.needs_review || reviewQueueClaimIds.has(effect.claim_id))
	);
	$: filteredFindings = findingRows.filter(
		(finding) =>
			(selectedClaimStatus === 'all' || finding.support_grade === selectedClaimStatus) &&
			(!reviewQueueOnly ||
				finding.review_status === 'needs_review' ||
				reviewQueueFindingIds.has(finding.finding_id) ||
				reviewQueueClaimIds.has(finding.claim_id))
	);
	$: visibleFindingRows = usesFindings ? filteredFindings : [];
	$: visibleEffectRows = usesFindings ? [] : filteredEffects;
	$: selectableEffects = usesFindings
		? filteredFindings
				.map((finding) => findingEffectFor(finding))
				.filter((effect): effect is ResearchUnderstandingPresentationEffect => Boolean(effect))
		: filteredEffects;
	$: selectedFinding = detailMode && selectedFindingId
		? (allFindingRows.find((finding) => finding.finding_id === selectedFindingId) ?? null)
		: null;
	$: claimTypeCounts = countEffectsBy(effectRows, 'claim_type');
	$: claimStatusCounts = (() => {
		if (!usesFindings) return countEffectsBy(effectRows, 'support_status');
		const counts = new Map<string, number>([['all', findingRows.length]]);
		for (const finding of findingRows) {
			counts.set(finding.support_grade, (counts.get(finding.support_grade) ?? 0) + 1);
		}
		return counts;
	})();
	$: if (understanding && detailMode && selectableEffects.length && !selectableEffects.some((effect) => effect.effect_id === selectedEffectId)) {
		selectedEffectId = selectableEffects[0]?.effect_id ?? '';
	}
	$: if ((!selectableEffects.length || !detailMode || selectedFindingId) && selectedEffectId) {
		selectedEffectId = '';
	}
	$: selectedEffect =
		detailMode ? (selectableEffects.find((effect) => effect.effect_id === selectedEffectId) ?? null) : null;
	$: selectedClaim = selectedFinding
		? (claimById.get(selectedFinding.claim_id) ?? null)
		: selectedEffect
			? (claimById.get(selectedEffect.claim_id) ?? null)
			: null;
	$: selectedRelations = selectedEffect
		? (selectedFinding?.relation_ids.length ? selectedFinding.relation_ids : selectedEffect.relation_ids)
				.map((relationId) => relationById.get(relationId))
				.filter((relation): relation is ResearchUnderstandingRelation => Boolean(relation))
		: selectedFinding
			? selectedFinding.relation_ids
					.map((relationId) => relationById.get(relationId))
					.filter((relation): relation is ResearchUnderstandingRelation => Boolean(relation))
			: [];
	$: selectedReadableRelations = selectedRelations.filter((relation) => isReadableRelation(relation));
	$: selectedHiddenRelationCount = Math.max(
		0,
		selectedRelations.length - selectedReadableRelations.length
	);
	$: selectedScopeId = scopeId(understanding);
	$: selectedReviewTargetId = selectedFinding?.finding_id ?? selectedClaim?.claim_id ?? '';
	$: selectedReviewFallbackId =
		selectedFinding && selectedFinding.claim_id !== selectedReviewTargetId
			? selectedFinding.claim_id
			: '';
	$: selectedCuration = selectedReviewTargetId
		? (curationsByTargetId.get(selectedReviewTargetId) ??
			(selectedReviewFallbackId ? curationsByTargetId.get(selectedReviewFallbackId) : null) ??
			null)
		: null;
	$: selectedFeedback = selectedReviewTargetId
		? [
				...(feedbackByTargetId.get(selectedReviewTargetId) ?? []),
				...(selectedReviewFallbackId ? (feedbackByTargetId.get(selectedReviewFallbackId) ?? []) : [])
			]
		: [];
	$: displayClaim = selectedClaim
		? {
				claim_type: selectedCuration?.curated_claim_type ?? selectedClaim.claim_type,
				status: selectedCuration?.curated_status ?? selectedClaim.status,
				statement: selectedCuration?.curated_statement ?? selectedClaim.statement,
				evidence_ref_ids: selectedCuration?.curated_evidence_ref_ids ?? selectedClaim.evidence_ref_ids,
				context_ids: selectedCuration?.curated_context_ids ?? selectedClaim.context_ids
			}
		: null;
	$: selectedEvidenceRefs = displayClaim
		? presentationEvidenceForIds(displayClaim.evidence_ref_ids)
		: selectedFinding
			? presentationEvidenceForIds(selectedFinding.evidence_ref_ids)
			: [];
	$: selectedContextRefs = displayClaim
		? presentationContextsForIds(displayClaim.context_ids)
		: selectedFinding
			? presentationContextsForIds(selectedFinding.context_ids)
			: [];
	$: selectedFindingContextRefs = selectedFinding
		? presentationContextsForIds(selectedFinding.context_ids)
		: [];
	$: selectedFindingDisplayContextRefs = selectedFinding
		? compactFindingContextDisplay(selectedFindingContextRefs, selectedFinding)
		: [];
	$: selectedHiddenFindingContextCount = selectedFinding
		? Math.max(0, selectedFindingContextRefs.length - selectedFindingDisplayContextRefs.length)
		: 0;
	$: selectedCurationEvidenceOptions = selectedClaim || selectedFinding
		? presentationEvidenceForIds([
				...(selectedFinding?.evidence_ref_ids ?? selectedClaim?.evidence_ref_ids ?? []),
				...(selectedCuration?.curated_evidence_ref_ids ?? [])
			])
		: [];
	$: selectedCurationContextOptions = selectedClaim || selectedFinding
		? presentationContextsForIds([
				...(selectedFinding?.context_ids ?? selectedClaim?.context_ids ?? []),
				...(selectedCuration?.curated_context_ids ?? [])
			])
		: [];
	$: if (selectedReviewTargetId !== lastCurationTargetId) {
		lastCurationTargetId = selectedReviewTargetId;
		activeReviewPanel = '';
		resetCurationForm();
		curationMessage = '';
		curationError = '';
	}
	$: curationScopeKey =
		understanding && selectedScopeId
			? `${collectionId}:${understanding.scope.scope_type}:${selectedScopeId}`
			: '';
	$: if (curationScopeKey && curationScopeKey !== loadedCurationScopeKey) {
		void loadCurationsForScope(curationScopeKey);
	}
	$: if (curationScopeKey && curationScopeKey !== loadedFeedbackScopeKey) {
		void loadFeedbackForScope(curationScopeKey);
	}
	$: if (selectedReviewTargetId !== lastFeedbackTargetId) {
		lastFeedbackTargetId = selectedReviewTargetId;
		feedbackMessage = '';
		feedbackError = '';
	}

	function humanizeCode(value: string) {
		const normalized = value.trim();
		if (!normalized) return '';
		return normalized.replace(/_/g, ' ');
	}

	function translatedCatalogLabel(namespace: string, value: string) {
		const label = $t(`${namespace}.${value}`);
		return label.startsWith('research.') ? humanizeCode(value) : label;
	}

	function stateLabel(state: string) {
		return translatedCatalogLabel('research.understanding.states', state);
	}

	function claimTypeLabel(type: string) {
		if (type === 'all') return $t('research.understanding.allClaimTypes');
		return translatedCatalogLabel('research.understanding.types', type);
	}

	function statusLabel(status: string) {
		if (status === 'all') return $t('research.understanding.allStatuses');
		return translatedCatalogLabel('research.understanding.statuses', status);
	}

	function supportGradeLabel(grade: string) {
		if (grade === 'all') return $t('research.understanding.allSupportGrades');
		return translatedCatalogLabel('research.understanding.supportGrades', grade);
	}

	function findingReviewStatusLabel(status: string) {
		return translatedCatalogLabel('research.understanding.findingReviewStatuses', status);
	}

	function relationLabel(type: string) {
		return translatedCatalogLabel('research.understanding.relations', type);
	}

	function relationStatusLabel(status: string) {
		return statusLabel(status || 'limited');
	}

	function feedbackStatusLabel(status: string) {
		return translatedCatalogLabel('research.understanding.feedbackStatuses', status);
	}

	function feedbackIssueLabel(issue: string) {
		return translatedCatalogLabel('research.understanding.feedbackIssues', issue);
	}

	function hasDisplayValue(value: unknown): boolean {
		if (value === null || value === undefined) return false;
		if (typeof value === 'string') {
			const normalized = value.trim();
			return Boolean(normalized && normalized !== '-' && normalized !== '--');
		}
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
			return value.map(displayValue).filter(Boolean).join(', ');
		}
		if (typeof value === 'object') {
			return Object.entries(value as Record<string, unknown>)
				.filter(([, item]) => hasDisplayValue(item))
				.map(([key, item]) => `${key}: ${displayValue(item)}`)
				.join('; ');
		}
		return String(value);
	}

	function listLabel(values: string[]) {
		const cleaned = [...new Set(values.map((value) => value.trim()).filter(Boolean))];
		return cleaned.length ? cleaned.join(', ') : $t('research.emptyValue');
	}

	function findingListLabel(values: string[]) {
		return listLabel(values);
	}

	function findingChainText(values: string[]) {
		return listLabel(values);
	}

	function findingEvidenceGroupLabel(role: FindingEvidenceRole) {
		return translatedCatalogLabel('research.understanding.findingEvidenceGroups', role);
	}

	function selectedFindingEvidenceGroups() {
		if (!selectedFinding) return [];
		const roles: FindingEvidenceRole[] = [
			'direct_result',
			'mechanism',
			'condition_context',
			'conflict',
			'background',
			'uncategorized'
		];
		return roles
			.map((role) => ({
				role,
				items: presentationEvidenceForIds(selectedFinding.evidence_bundle[role] ?? [])
			}))
			.filter((group) => group.items.length);
	}

	function compactText(value: string, limit = 160) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (normalized.length <= limit) return normalized;
		return `${normalized.slice(0, limit).trim()}...`;
	}

	function stripSourcePrefix(value: string) {
		return value
			.replace(/^[a-f0-9]{24,}[_-]/i, '')
			.replace(/\s*\/\s*p\.\s*\d+\s*$/i, '')
			.replace(/\.(pdf|md|txt)\b/gi, '')
			.replace(/\s+/g, ' ')
			.trim();
	}

	function readableEvidenceTitle(value: string, limit = 120) {
		const cleaned = stripSourcePrefix(value).replace(/^(P\d{3})[-_](?=\S)/i, '$1 · ');
		return compactText(cleaned || value, limit);
	}

	function readableRelationSide(value: string) {
		const normalized = compactText(value);
		if (!normalized) return '';
		if (
			/(sample_context|process_context|test_condition|source_object_ids|evidence_ref_ids)/i.test(
				normalized
			)
			|| /(^|[,;]\s*)(sample_number|condition_number|sample id|condition id|sample number|condition number)\s*:/i.test(
				normalized
			)
		) {
			return '';
		}
		return normalized;
	}

	function relationSummary(relation: ResearchUnderstandingRelation) {
		if (relation.statement) return relation.statement;
		const subject = readableRelationSide(relation.subject);
		const object = readableRelationSide(relation.object);
		const predicate = relationLabel(relation.predicate || relation.relation_type);
		if (subject && object) return `${subject} -> ${predicate} -> ${object}`;
		if (subject) return `${predicate}: ${subject}`;
		if (object) return `${predicate}: ${object}`;
		return $t('research.understanding.relationNeedsNormalization');
	}

	function isReadableRelation(relation: ResearchUnderstandingRelation) {
		const summary = relationSummary(relation);
		return summary !== $t('research.understanding.relationNeedsNormalization');
	}

	function findingEffectFor(finding: ResearchUnderstandingPresentationFinding) {
		return effectRows.find((effect) => effect.claim_id === finding.claim_id) ?? null;
	}

	function openClaimDetail(effectId: string) {
		selectedEffectId = effectId;
		selectedFindingId = '';
		detailMode = true;
	}

	function openFindingDetail(findingId: string) {
		selectedFindingId = findingId;
		selectedEffectId = '';
		detailMode = true;
	}

	function closeClaimDetail() {
		detailMode = false;
		selectedEffectId = '';
		selectedFindingId = '';
		activeReviewPanel = '';
	}

	function toggleReviewPanel(panel: 'feedback' | 'curation') {
		activeReviewPanel = activeReviewPanel === panel ? '' : panel;
	}

	function confidenceLabel(value: number | null) {
		if (value === null) return '';
		const clamped = Math.max(0, Math.min(1, value));
		return `${Math.round(clamped * 100)}%`;
	}

	function queryString(params: [string, string][]) {
		const query = params
			.filter(([, value]) => value)
			.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
			.join('&');
		return query ? `?${query}` : '';
	}

	function evidenceHref(ref: ResearchUnderstandingPresentationEvidence) {
		const rawRef = evidenceById.get(ref.evidence_ref_id);
		if (ref.href) return ref.href;
		if (rawRef?.href) return rawRef.href;
		if (!collectionId || !ref.document_id) return '';
		const params: [string, string][] = [];
		const pageValue = ref.page || displayValue(rawRef?.locator.page);
		const sourceRef = displayValue(rawRef?.locator.source_ref);
		const anchorId = rawRef?.anchor_ids[0] ?? '';
		params.push(['view', 'parsed-paper']);
		if (pageValue) params.push(['page', pageValue]);
		if (sourceRef) params.push(['source_ref', sourceRef]);
		if (ref.evidence_ref_id) params.push(['evidence_id', ref.evidence_ref_id]);
		if (anchorId) params.push(['anchor_id', anchorId]);
		if (returnTo) params.push(['return_to', returnTo]);
		return `${resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: ref.document_id
		})}${queryString(params)}`;
	}

	function evidenceMeta(ref: ResearchUnderstandingPresentationEvidence) {
		return [
			ref.block_type || ref.source_kind,
			ref.page ? `p. ${ref.page}` : '',
			ref.heading_path,
			ref.traceability_status
		]
			.filter(Boolean)
			.join(' · ');
	}

	function evidenceSourceText(ref: ResearchUnderstandingPresentationEvidence) {
		return ref.source_text || ref.quote || '';
	}

	function evidenceLabelsForIds(evidenceIds: string[], limit = 3) {
		return evidenceIds
			.map((id) =>
				readableEvidenceTitle(presentationEvidenceById.get(id)?.title || evidenceById.get(id)?.label || '')
			)
			.filter(Boolean)
			.slice(0, limit);
	}

	function shouldReviewClaim(
		claim: ResearchUnderstandingClaim,
		currentFeedbackByClaimId: Map<string, ResearchUnderstandingFeedback[]>
	) {
		const feedback = currentFeedbackByClaimId.get(claim.claim_id) ?? [];
		return (
			claim.status === 'limited' ||
			claim.status === 'conflicted' ||
			claim.status === 'unsupported' ||
			(claim.confidence !== null && claim.confidence < 0.7) ||
			claim.warnings.length > 0 ||
			claim.evidence_ref_ids.length === 0 ||
			feedback.some((item) => item.review_status !== 'correct' || item.issue_type !== 'none')
		);
	}

	function countEffectsBy(
		currentEffects: ResearchUnderstandingPresentationEffect[],
		field: 'claim_type' | 'support_status'
	) {
		const counts = new Map<string, number>([['all', currentEffects.length]]);
		for (const effect of currentEffects) {
			counts.set(effect[field], (counts.get(effect[field]) ?? 0) + 1);
		}
		return counts;
	}

	function optionLabel(label: string, count: number) {
		return `${label} ${count}`;
	}

	function presentationEvidenceForIds(ids: string[]) {
		return [...new Set(ids)]
			.map((id) => presentationEvidenceById.get(id))
			.filter((ref): ref is ResearchUnderstandingPresentationEvidence => Boolean(ref));
	}

	function presentationContextsForIds(ids: string[]) {
		return [...new Set(ids)]
			.map((id) => presentationContextById.get(id))
			.filter((context): context is ResearchUnderstandingPresentationContext => Boolean(context));
	}

	function isGenericFindingContextLabel(label: string) {
		return /^(claim applicability|context)$/i.test(label.trim());
	}

	function isMostlyNumericContextText(value: string) {
		const parts = value
			.split(/[,;]/)
			.map((part) => part.trim())
			.filter(Boolean);
		if (parts.length < 3) return false;
		const noisyParts = parts.filter(
			(part) =>
				part === '-' ||
				/^oeu_[a-z0-9]+$/i.test(part) ||
				/^[A-Z]$/.test(part) ||
				/^[-+]?\d+(\.\d+)?\s*(%|degc|c|mpa|w|mm\/s|j\/mm3|j\/mm³)?$/i.test(part)
		);
		return noisyParts.length / parts.length >= 0.65;
	}

	function isNoisyFindingContextText(value: string) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (!normalized) return true;
		if (/\boeu_[a-z0-9]+\b/i.test(normalized)) return true;
		if (/\bdensity_porosity_microstructure\b/i.test(normalized)) return true;
		if (/^SEM\s*\/\s*ImageJ$/i.test(normalized)) return true;
		if (isMostlyNumericContextText(normalized)) return true;
		if (
			normalized.length > 220 &&
			/(samples were|characterized|polished|magnification|figure legend|interpretation of the references)/i.test(
				normalized
			)
		) {
			return true;
		}
		return false;
	}

	function readableFindingContextText(value: string, limit = 140) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (!normalized || isNoisyFindingContextText(normalized)) return '';
		return compactText(normalized, limit);
	}

	function readableFindingContextList(values: string[], limit = 4) {
		const cleaned: string[] = [];
		for (const value of values) {
			const text = readableFindingContextText(value, 90);
			if (text && !cleaned.includes(text)) cleaned.push(text);
			if (cleaned.length >= limit) break;
		}
		return cleaned;
	}

	function normalizedFindingContextToken(value: string) {
		return value
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, ' ')
			.replace(/\s+/g, ' ')
			.trim();
	}

	function contextValueMatchesFinding(value: string, finding: ResearchUnderstandingPresentationFinding) {
		const normalized = normalizedFindingContextToken(value);
		if (!normalized) return false;
		const findingTerms = [
			...finding.variables,
			...finding.mediators,
			...finding.outcomes,
			finding.scope_summary
		]
			.map(normalizedFindingContextToken)
			.filter(Boolean);
		return findingTerms.some(
			(term) =>
				term &&
				(normalized.includes(term) || term.includes(normalized))
		);
	}

	function contextMatchesFinding(
		context: ResearchUnderstandingPresentationContext,
		finding: ResearchUnderstandingPresentationFinding
	) {
		if (!isGenericFindingContextLabel(context.label)) return true;
		if (!context.property_scope.length) return true;
		return context.property_scope.some((value) => contextValueMatchesFinding(value, finding));
	}

	function compactFindingContext(
		context: ResearchUnderstandingPresentationContext,
		finding: ResearchUnderstandingPresentationFinding
	): ResearchUnderstandingPresentationContext | null {
		if (!contextMatchesFinding(context, finding)) return null;
		const material_scope = readableFindingContextList(context.material_scope);
		const property_scope = readableFindingContextList(context.property_scope);
		const process_summary = readableFindingContextText(context.process_summary);
		const test_summary = readableFindingContextText(context.test_summary);
		const limitations = readableFindingContextList(context.limitations, 3);
		const hasSpecificContext = Boolean(process_summary || test_summary || limitations.length);
		if (isGenericFindingContextLabel(context.label) && !hasSpecificContext) return null;
		if (
			!material_scope.length &&
			!property_scope.length &&
			!process_summary &&
			!test_summary &&
			!limitations.length
		) {
			return null;
		}
		return {
			...context,
			label: compactText(context.label || 'Context', 80),
			material_scope,
			property_scope,
			process_summary,
			test_summary,
			limitations
		};
	}

	function findingContextScore(
		original: ResearchUnderstandingPresentationContext,
		context: ResearchUnderstandingPresentationContext
	) {
		let score = isGenericFindingContextLabel(original.label) ? -2 : 5;
		if (context.process_summary) score += 3;
		if (context.test_summary) score += 2;
		if (context.material_scope.length) score += 1;
		if (context.property_scope.length) score += 1;
		if (context.limitations.length) score += 1;
		if (isNoisyFindingContextText(original.process_summary)) score -= 1;
		if (isNoisyFindingContextText(original.test_summary)) score -= 1;
		return score;
	}

	function compactFindingContextDisplay(
		contexts: ResearchUnderstandingPresentationContext[],
		finding: ResearchUnderstandingPresentationFinding
	) {
		return contexts
			.map((context, index) => {
				const compacted = compactFindingContext(context, finding);
				if (!compacted) return null;
				return {
					context: compacted,
					index,
					score: findingContextScore(context, compacted)
				};
			})
			.filter(
				(
					item
				): item is {
					context: ResearchUnderstandingPresentationContext;
					index: number;
					score: number;
				} => Boolean(item)
			)
			.sort((left, right) => right.score - left.score || left.index - right.index)
			.slice(0, FINDING_CONTEXT_DISPLAY_LIMIT)
			.sort((left, right) => left.index - right.index)
			.map((item) => item.context);
	}

	function contextCurationMeta(context: ResearchUnderstandingPresentationContext) {
		return [
			listLabel(context.material_scope),
			listLabel(context.property_scope),
			context.process_summary,
			context.test_summary
		]
			.filter((value) => value && value !== $t('research.emptyValue'))
			.join(' · ');
	}

	function scopeId(currentUnderstanding: ResearchUnderstanding | null) {
		const scope = currentUnderstanding?.scope;
		return (
			scope?.goal_id ||
			scope?.objective_id ||
			scope?.material_id ||
			scope?.document_id ||
			scope?.collection_id ||
			''
		);
	}

	function resetCurationForm() {
		const curation = selectedCuration;
		curationClaimType = curation?.curated_claim_type ?? selectedClaim?.claim_type ?? 'finding';
		curationStatus = curation?.curated_status ?? selectedClaim?.status ?? 'supported';
		curationStatement =
			curation?.curated_statement ?? selectedFinding?.statement ?? selectedClaim?.statement ?? '';
		curationEvidenceRefIds = [
			...(curation?.curated_evidence_ref_ids ??
				selectedFinding?.evidence_ref_ids ??
				selectedClaim?.evidence_ref_ids ??
				[])
		];
		curationContextIds = [
			...(curation?.curated_context_ids ??
				selectedFinding?.context_ids ??
				selectedClaim?.context_ids ??
				[])
		];
		curationNote = curation?.note ?? '';
		curationReviewer = curation?.reviewer ?? '';
	}

	function toggleCurationEvidence(evidenceId: string) {
		curationEvidenceRefIds = curationEvidenceRefIds.includes(evidenceId)
			? curationEvidenceRefIds.filter((id) => id !== evidenceId)
			: [...curationEvidenceRefIds, evidenceId];
	}

	function toggleCurationContext(contextId: string) {
		curationContextIds = curationContextIds.includes(contextId)
			? curationContextIds.filter((id) => id !== contextId)
			: [...curationContextIds, contextId];
	}

	function reviewTargetKey(record: ResearchUnderstandingFeedback | ResearchUnderstandingCuration) {
		return record.finding_id || record.claim_id || '';
	}

	async function loadCurationsForScope(scopeKey: string) {
		if (!understanding || !collectionId || !selectedScopeId) return;
		loadedCurationScopeKey = scopeKey;
		curationLoadError = '';
		try {
			const curations = await fetchResearchUnderstandingCurations(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId
			});
			curationsByTargetId = new Map(
				curations
					.map(
						(curation): [string, ResearchUnderstandingCuration] => [
							reviewTargetKey(curation),
							curation
						]
					)
					.filter(([id]) => Boolean(id))
			);
			resetCurationForm();
		} catch (error) {
			curationLoadError = error instanceof Error ? error.message : $t('error.unexpected');
		}
	}

	async function loadFeedbackForScope(scopeKey: string) {
		if (!understanding || !collectionId || !selectedScopeId) return;
		loadedFeedbackScopeKey = scopeKey;
		feedbackLoadError = '';
		try {
			const feedback = await fetchResearchUnderstandingFeedback(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId
			});
			const next = new Map<string, ResearchUnderstandingFeedback[]>();
			for (const item of feedback) {
				const targetId = reviewTargetKey(item);
				if (!targetId) continue;
				next.set(targetId, [...(next.get(targetId) ?? []), item]);
			}
			feedbackByTargetId = next;
		} catch (error) {
			feedbackLoadError = error instanceof Error ? error.message : $t('error.unexpected');
		}
	}

	async function submitClaimFeedback() {
		if (!understanding || !selectedReviewTargetId || !collectionId || !selectedScopeId) return;
		feedbackSubmitting = true;
		feedbackMessage = '';
		feedbackError = '';
		try {
			const feedback = await createResearchUnderstandingFeedback(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId,
				finding_id: selectedReviewTargetId,
				claim_id: selectedClaim?.claim_id ?? selectedFinding?.claim_id ?? null,
				review_status: feedbackStatus,
				issue_type: feedbackIssue,
				note: feedbackNote.trim() || null,
				reviewer: feedbackReviewer.trim() || null
			});
			feedbackMessage = $t('research.understanding.feedbackSaved', {
				id: formatShortIdentifier(feedback.feedback_id)
			});
			const targetId = reviewTargetKey(feedback);
			feedbackByTargetId = new Map(feedbackByTargetId).set(targetId, [
				feedback,
				...(feedbackByTargetId.get(targetId) ?? [])
			]);
			feedbackNote = '';
		} catch (error) {
			feedbackError = error instanceof Error ? error.message : $t('error.unexpected');
		} finally {
			feedbackSubmitting = false;
		}
	}

	async function submitClaimCuration() {
		if (!understanding || !selectedReviewTargetId || !collectionId || !selectedScopeId) return;
		curationSubmitting = true;
		curationMessage = '';
		curationError = '';
		try {
			const curation = await createResearchUnderstandingCuration(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId,
				finding_id: selectedReviewTargetId,
				claim_id: selectedClaim?.claim_id ?? selectedFinding?.claim_id ?? null,
				curated_claim_type: curationClaimType,
				curated_status: curationStatus,
				curated_statement: curationStatement.trim(),
				curated_support_grade: selectedFinding?.support_grade ?? null,
				curated_review_status: selectedFinding?.review_status ?? null,
				curated_variables: selectedFinding?.variables ?? [],
				curated_mediators: selectedFinding?.mediators ?? [],
				curated_outcomes: selectedFinding?.outcomes ?? [],
				curated_direction: selectedFinding?.direction || null,
				curated_scope_summary: selectedFinding?.scope_summary || null,
				curated_evidence_ref_ids: curationEvidenceRefIds,
				curated_context_ids: curationContextIds,
				note: curationNote.trim() || null,
				reviewer: curationReviewer.trim() || null
			});
			curationMessage = $t('research.understanding.curationSaved', {
				id: formatShortIdentifier(curation.curation_id)
			});
			curationsByTargetId = new Map(curationsByTargetId).set(reviewTargetKey(curation), curation);
		} catch (error) {
			curationError = error instanceof Error ? error.message : $t('error.unexpected');
		} finally {
			curationSubmitting = false;
		}
	}
</script>

<section class="research-understanding-workbench" aria-labelledby={titleId}>
	<div class="research-understanding-workbench__heading">
		<div>
			<h3 id={titleId}>{$t('research.understanding.title')}</h3>
			<p>{$t(bodyKey)}</p>
		</div>
		{#if understanding}
			<span>{stateLabel(understanding.state)}</span>
		{/if}
	</div>

	{#if understanding}
		<div
			class="research-understanding-workbench__summary"
			aria-label={$t('research.understanding.summary')}
		>
			<div>
				<strong>{presentationSummary?.claim_count ?? understanding.summary.claim_count}</strong>
				<span>{$t('research.understanding.claims')}</span>
			</div>
			<div>
				<strong>{presentationSummary?.relation_count ?? understanding.summary.relation_count}</strong>
				<span>{$t('research.understanding.relationsLabel')}</span>
			</div>
			<div>
				<strong>{presentationSummary?.evidence_count ?? understanding.summary.evidence_ref_count}</strong>
				<span>{$t('research.understanding.evidenceRefs')}</span>
			</div>
			<div>
				<strong>
					{presentationSummary?.review_queue_finding_count ??
						presentationSummary?.review_queue_count ??
						reviewQueueFindingIds.size}
				</strong>
				<span>{$t('research.understanding.reviewQueue')}</span>
			</div>
		</div>

		{#if usesFindings || effectRows.length || understanding.claims.length || understanding.evidence_refs.length}
			{#if usesFindings || effectRows.length}
				<div
					class="research-understanding-workbench__filters"
					aria-label={$t('research.understanding.claimFilters')}
				>
					{#if !usesFindings}
						<div class="research-understanding-workbench__filter-group">
							<span>{$t('research.understanding.filterByType')}</span>
							<div class="research-understanding-workbench__segmented" role="list">
								{#each CLAIM_TYPE_ORDER as type (type)}
									{@const count = claimTypeCounts.get(type) ?? 0}
									{#if count || type === 'all'}
										<button
											type="button"
											class:research-understanding-workbench__segment--active={selectedClaimType ===
												type}
											aria-pressed={selectedClaimType === type}
											on:click={() => (selectedClaimType = type)}
										>
											{optionLabel(claimTypeLabel(type), count)}
										</button>
									{/if}
								{/each}
							</div>
						</div>
					{/if}
					<div class="research-understanding-workbench__filter-group">
						<span>
							{usesFindings
								? $t('research.understanding.filterByEvidenceGrade')
								: $t('research.understanding.filterByStatus')}
						</span>
						<div class="research-understanding-workbench__segmented" role="list">
							{#if usesFindings}
								{#each SUPPORT_GRADE_ORDER as grade (grade)}
									{@const count = claimStatusCounts.get(grade) ?? 0}
									{#if count || grade === 'all'}
										<button
											type="button"
											class:research-understanding-workbench__segment--active={selectedClaimStatus ===
												grade}
											aria-pressed={selectedClaimStatus === grade}
											on:click={() => (selectedClaimStatus = grade)}
										>
											{optionLabel(supportGradeLabel(grade), count)}
										</button>
									{/if}
								{/each}
							{:else}
								{#each CLAIM_STATUS_ORDER as status (status)}
									{@const count = claimStatusCounts.get(status) ?? 0}
									{#if count || status === 'all'}
										<button
											type="button"
											class:research-understanding-workbench__segment--active={selectedClaimStatus ===
												status}
											aria-pressed={selectedClaimStatus === status}
											on:click={() => (selectedClaimStatus = status)}
										>
											{optionLabel(statusLabel(status), count)}
										</button>
									{/if}
								{/each}
							{/if}
						</div>
					</div>
					<div class="research-understanding-workbench__filter-group">
						<span>{$t('research.understanding.reviewQueue')}</span>
						<div class="research-understanding-workbench__segmented" role="list">
							<button
								type="button"
								class:research-understanding-workbench__segment--active={reviewQueueOnly}
								aria-pressed={reviewQueueOnly}
								on:click={() => (reviewQueueOnly = !reviewQueueOnly)}
							>
								{$t('research.understanding.reviewQueueCount', {
									count:
										presentationSummary?.review_queue_finding_count ??
										presentationSummary?.review_queue_count ??
										reviewQueueFindingIds.size
								})}
							</button>
						</div>
					</div>
					{#if curationLoadError || feedbackLoadError}
						<p
							class="research-understanding-workbench__feedback-state research-understanding-workbench__feedback-state--error"
							role="alert"
						>
							{curationLoadError || feedbackLoadError}
						</p>
					{/if}
				</div>
			{/if}

			{#if !detailMode}
				<section
					class="research-understanding-workbench__column research-understanding-workbench__column--list"
					aria-label={usesFindings
						? $t('research.understanding.findingsWorkspace')
						: $t('research.understanding.claimWorkspace')}
				>
					<div class="research-understanding-workbench__column-heading">
						<h4>
							{usesFindings
								? $t('research.understanding.findingsWorkspace')
								: $t('research.understanding.claimWorkspace')}
						</h4>
						<span>
							{$t('research.understanding.filteredClaimCount', {
								shown: usesFindings ? visibleFindingRows.length : visibleEffectRows.length,
								total: usesFindings ? findingRows.length : effectRows.length
							})}
						</span>
					</div>
					{#if usesFindings}
						{#if visibleFindingRows.length}
							<div
								class="research-understanding-workbench__table-wrap"
								aria-label={$t('research.understanding.findingsTable')}
							>
								<table class="research-understanding-workbench__findings-table">
									<thead>
										<tr>
											<th scope="col">{$t('research.understanding.findingColumn')}</th>
											<th scope="col">{$t('research.understanding.variablesColumn')}</th>
											<th scope="col">{$t('research.understanding.mechanismColumn')}</th>
											<th scope="col">{$t('research.understanding.resultColumn')}</th>
											<th scope="col">{$t('research.understanding.scopeColumn')}</th>
											<th scope="col">{$t('research.understanding.evidenceGradeColumn')}</th>
											<th scope="col">{$t('research.understanding.paperCountColumn')}</th>
											<th scope="col">{$t('research.understanding.reviewStatusColumn')}</th>
										</tr>
									</thead>
										<tbody>
											{#each visibleFindingRows as finding (finding.finding_id)}
												{@const curation = curationsByTargetId.get(finding.finding_id)}
												{@const findingFeedback = feedbackByTargetId.get(finding.finding_id) ?? []}
												<tr>
													<td class="research-understanding-workbench__finding-main">
														<button
														type="button"
														on:click={() => openFindingDetail(finding.finding_id)}
													>
														<strong>{finding.statement || finding.title}</strong>
															{#if finding.title && finding.title !== finding.statement}
																<span>{finding.title}</span>
															{/if}
															{#if curation || findingFeedback.length}
																<span>
																	{[
																		curation ? $t('research.understanding.curatedBadge') : '',
																		findingFeedback.length
																			? $t('research.understanding.feedbackCount', {
																					count: findingFeedback.length
																				})
																			: ''
																	]
																		.filter(Boolean)
																		.join(' · ')}
																</span>
															{/if}
														</button>
													</td>
												<td>{findingListLabel(finding.variables)}</td>
												<td>{findingListLabel(finding.mediators)}</td>
												<td>
													{#if finding.direction}
														<span>{relationLabel(finding.direction)}</span>
													{/if}
													{#if finding.outcomes.length}
														<span>{findingListLabel(finding.outcomes)}</span>
													{:else}
														<span>{findingListLabel([])}</span>
													{/if}
												</td>
												<td>{finding.scope_summary || $t('research.emptyValue')}</td>
												<td>
													<span class="research-understanding-workbench__grade">
														{supportGradeLabel(finding.support_grade)}
													</span>
												</td>
												<td>{finding.paper_count}</td>
												<td>{findingReviewStatusLabel(finding.review_status)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{:else}
							<div class="research-understanding-workbench__empty">
								{$t('research.understanding.noFindings')}
							</div>
						{/if}
					{:else}
						{#each visibleEffectRows as effect (effect.effect_id)}
							{@const claim = claimById.get(effect.claim_id)}
							{@const curation = claim ? curationsByTargetId.get(claim.claim_id) : null}
							{@const claimFeedback = claim ? (feedbackByTargetId.get(claim.claim_id) ?? []) : []}
							{@const displayType = curation?.curated_claim_type ?? effect.claim_type}
							{@const displayStatus = curation?.curated_status ?? effect.support_status}
							{@const displayStatement = curation?.curated_statement ?? effect.statement}
							{@const displayEvidenceIds = curation?.curated_evidence_ref_ids ?? effect.evidence_ref_ids}
							{@const labels = evidenceLabelsForIds(displayEvidenceIds)}
							<button
								type="button"
								class="research-understanding-workbench__card research-understanding-workbench__card--claim"
								on:click={() => openClaimDetail(effect.effect_id)}
							>
								<div class="research-understanding-workbench__meta">
									<span>{claimTypeLabel(displayType)}</span>
									<span>{statusLabel(displayStatus)}</span>
									{#if effect.confidence !== null}
										<span>{confidenceLabel(effect.confidence)}</span>
									{/if}
									{#if curation}
										<span>{$t('research.understanding.curatedBadge')}</span>
									{/if}
									{#if claimFeedback.length}
										<span>
											{$t('research.understanding.feedbackCount', {
												count: claimFeedback.length
											})}
										</span>
									{/if}
								</div>
								<strong>{displayStatement}</strong>
								{#if effect.title && effect.title !== displayStatement}
									<p>{effect.title}</p>
								{/if}
								<div class="research-understanding-workbench__claim-stats">
									<span>
										{$t('research.understanding.paperCount', {
											count: effect.paper_count
										})}
									</span>
									<span>
										{$t('research.understanding.evidenceCount', {
											count: effect.evidence_count
										})}
									</span>
								</div>
								{#if curation && claim && curation.curated_statement !== claim.statement}
									<small>
										{$t('research.understanding.originalClaimPrefix')}
										{claim.statement}
									</small>
								{/if}
								{#if labels.length}
									<div class="research-understanding-workbench__source-list">
										<span>{$t('research.understanding.keyEvidence')}</span>
										<ul>
											{#each labels as label, index (`${effect.effect_id}-${index}-${label}`)}
												<li>{label}</li>
											{/each}
										</ul>
									</div>
								{/if}
								{#if effect.context_summary}
									<small>
										{$t('research.understanding.contextPrefix')}
										{effect.context_summary}
									</small>
								{/if}
							</button>
						{:else}
							<div class="research-understanding-workbench__empty">
								{$t('research.understanding.noEffects')}
							</div>
						{/each}
					{/if}
				</section>
			{:else}
				<section
					class="research-understanding-workbench__detail-view"
					aria-label={selectedFinding
						? $t('research.understanding.findingDetail')
						: $t('research.understanding.claimDetail')}
				>
					<div class="research-understanding-workbench__column-heading">
						<button
							type="button"
							class="research-understanding-workbench__back"
							on:click={closeClaimDetail}
						>
							{selectedFinding
								? $t('research.understanding.backToFindings')
								: $t('research.understanding.backToClaims')}
						</button>
						<h4>
							{selectedFinding
								? $t('research.understanding.findingDetail')
								: $t('research.understanding.claimDetail')}
						</h4>
					</div>
					{#if selectedFinding || (selectedEffect && selectedClaim)}
							<article class="research-understanding-workbench__detail">
								<header class="research-understanding-workbench__claim-header">
									<div class="research-understanding-workbench__meta">
										{#if selectedFinding}
											<span>{supportGradeLabel(selectedFinding.support_grade)}</span>
											<span>{findingReviewStatusLabel(selectedFinding.review_status)}</span>
											{#if selectedFinding.confidence !== null}
												<span>{confidenceLabel(selectedFinding.confidence)}</span>
											{/if}
											<span>
												{$t('research.understanding.paperCount', {
													count: selectedFinding.paper_count
												})}
											</span>
											<span>
												{$t('research.understanding.evidenceCount', {
													count: selectedFinding.evidence_count
												})}
											</span>
										{:else if selectedClaim}
											<span>{claimTypeLabel(displayClaim?.claim_type ?? selectedClaim.claim_type)}</span>
											<span>{statusLabel(displayClaim?.status ?? selectedClaim.status)}</span>
											{#if selectedClaim.confidence !== null}
												<span>{confidenceLabel(selectedClaim.confidence)}</span>
											{/if}
											{#if selectedClaim.strength}
												<span>{selectedClaim.strength}</span>
											{/if}
										{/if}
										{#if selectedCuration}
											<span>{$t('research.understanding.curatedBadge')}</span>
										{/if}
									{#if selectedFeedback.length}
										<span>
											{$t('research.understanding.feedbackCount', {
												count: selectedFeedback.length
											})}
											</span>
										{/if}
									</div>
									<strong>
										{selectedFinding?.statement ||
											selectedFinding?.title ||
											displayClaim?.statement ||
											selectedClaim?.statement ||
											''}
									</strong>
									{#if selectedFinding?.title && selectedFinding.title !== selectedFinding.statement}
										<p>{selectedFinding.title}</p>
									{:else if !selectedFinding && selectedEffect && selectedEffect.title && selectedEffect.title !== (displayClaim?.statement ?? selectedClaim?.statement)}
										<p>{selectedEffect.title}</p>
									{/if}
								<div
									class="research-understanding-workbench__review-actions"
									aria-label={$t('research.understanding.reviewActions')}
								>
									<button
										type="button"
										class:research-understanding-workbench__review-action--active={activeReviewPanel ===
											'feedback'}
										aria-pressed={activeReviewPanel === 'feedback'}
										on:click={() => toggleReviewPanel('feedback')}
									>
										{$t('research.understanding.feedbackTitle')}
									</button>
									<button
										type="button"
										class:research-understanding-workbench__review-action--active={activeReviewPanel ===
											'curation'}
										aria-pressed={activeReviewPanel === 'curation'}
										on:click={() => toggleReviewPanel('curation')}
									>
										{$t('research.understanding.curationTitle')}
									</button>
								</div>
							</header>

							{#if selectedFinding}
								<div class="research-understanding-workbench__context research-understanding-workbench__context--finding-chain">
									<div>
										<span>{$t('research.understanding.findingVariables')}</span>
										<p>{findingChainText(selectedFinding.variables)}</p>
									</div>
									<div>
										<span>{$t('research.understanding.findingMechanism')}</span>
										<p>{findingChainText(selectedFinding.mediators)}</p>
									</div>
									<div>
										<span>{$t('research.understanding.findingOutcomes')}</span>
										<p>{findingChainText(selectedFinding.outcomes)}</p>
									</div>
									{#if selectedFinding.direction}
										<div>
											<span>{$t('research.understanding.relationDirection')}</span>
											<p>{relationLabel(selectedFinding.direction)}</p>
										</div>
									{/if}
									{#if selectedFinding.scope_summary}
										<div>
											<span>{$t('research.understanding.findingScope')}</span>
											<p>{selectedFinding.scope_summary}</p>
										</div>
									{/if}
								</div>
							{/if}

							{#if activeReviewPanel === 'feedback'}
								<form
									class="research-understanding-workbench__feedback research-understanding-workbench__feedback--primary"
									on:submit|preventDefault={submitClaimFeedback}
								>
									<h5>{$t('research.understanding.feedbackTitle')}</h5>
									<label>
										<span>{$t('research.understanding.feedbackStatus')}</span>
										<select
											id={`${titleId}-feedback-status`}
											name="feedback_status"
											bind:value={feedbackStatus}
											disabled={feedbackSubmitting}
										>
											{#each FEEDBACK_STATUS_OPTIONS as status (status)}
												<option value={status}>{feedbackStatusLabel(status)}</option>
											{/each}
										</select>
									</label>
									<label>
										<span>{$t('research.understanding.feedbackIssue')}</span>
										<select
											id={`${titleId}-feedback-issue`}
											name="feedback_issue"
											bind:value={feedbackIssue}
											disabled={feedbackSubmitting}
										>
											{#each FEEDBACK_ISSUE_OPTIONS as issue (issue)}
												<option value={issue}>{feedbackIssueLabel(issue)}</option>
											{/each}
										</select>
									</label>
									<label>
										<span>{$t('research.understanding.feedbackNote')}</span>
										<textarea
											id={`${titleId}-feedback-note`}
											name="feedback_note"
											bind:value={feedbackNote}
											disabled={feedbackSubmitting}
											maxlength="2000"
											rows="3"
										></textarea>
									</label>
									<label>
										<span>{$t('research.understanding.feedbackReviewer')}</span>
										<input
											id={`${titleId}-feedback-reviewer`}
											name="feedback_reviewer"
											bind:value={feedbackReviewer}
											disabled={feedbackSubmitting}
											maxlength="120"
										/>
									</label>
									<button type="submit" disabled={feedbackSubmitting || !collectionId}>
										{feedbackSubmitting
											? $t('research.understanding.feedbackSaving')
											: $t('research.understanding.feedbackSubmit')}
									</button>
									{#if feedbackMessage}
										<p class="research-understanding-workbench__feedback-state" role="status">
											{feedbackMessage}
										</p>
									{/if}
									{#if feedbackError}
										<p
											class="research-understanding-workbench__feedback-state research-understanding-workbench__feedback-state--error"
											role="alert"
										>
											{feedbackError}
										</p>
									{/if}
								</form>
							{:else if activeReviewPanel === 'curation'}
								<form
									class="research-understanding-workbench__feedback research-understanding-workbench__feedback--primary"
									on:submit|preventDefault={submitClaimCuration}
								>
									<h5>{$t('research.understanding.curationTitle')}</h5>
									<label>
										<span>{$t('research.understanding.curationClaimType')}</span>
										<select
											id={`${titleId}-curation-type`}
											name="curation_claim_type"
											bind:value={curationClaimType}
											disabled={curationSubmitting}
										>
											{#each CURATION_CLAIM_TYPE_OPTIONS as type (type)}
												<option value={type}>{claimTypeLabel(type)}</option>
											{/each}
										</select>
									</label>
									<label>
										<span>{$t('research.understanding.curationStatus')}</span>
										<select
											id={`${titleId}-curation-status`}
											name="curation_status"
											bind:value={curationStatus}
											disabled={curationSubmitting}
										>
											{#each CURATION_STATUS_OPTIONS as status (status)}
												<option value={status}>{statusLabel(status)}</option>
											{/each}
										</select>
									</label>
									<label>
										<span>{$t('research.understanding.curationStatement')}</span>
										<textarea
											id={`${titleId}-curation-statement`}
											name="curation_statement"
											bind:value={curationStatement}
											disabled={curationSubmitting}
											maxlength="4000"
											rows="4"
											required
										></textarea>
									</label>
									<fieldset class="research-understanding-workbench__curation-picker">
										<legend>{$t('research.understanding.curationEvidenceRefs')}</legend>
										{#if selectedCurationEvidenceOptions.length}
											<div class="research-understanding-workbench__check-list">
												{#each selectedCurationEvidenceOptions as ref (ref.evidence_ref_id)}
													{@const sourceText = evidenceSourceText(ref)}
													<label class="research-understanding-workbench__check-item">
														<input
															type="checkbox"
															checked={curationEvidenceRefIds.includes(ref.evidence_ref_id)}
															disabled={curationSubmitting}
															on:change={() => toggleCurationEvidence(ref.evidence_ref_id)}
														/>
														<span>
															<strong>{readableEvidenceTitle(ref.title)}</strong>
															<small>{evidenceMeta(ref)}</small>
															{#if sourceText}
																<em>{compactText(sourceText, 220)}</em>
															{:else}
																<em>{$t('research.understanding.noEvidenceSourceText')}</em>
															{/if}
														</span>
													</label>
												{/each}
											</div>
										{:else}
											<p class="research-understanding-workbench__picker-empty">
												{$t('research.understanding.curationNoEvidenceRefs')}
											</p>
										{/if}
									</fieldset>
									<fieldset class="research-understanding-workbench__curation-picker">
										<legend>{$t('research.understanding.curationContextRefs')}</legend>
										{#if selectedCurationContextOptions.length}
											<div class="research-understanding-workbench__check-list">
												{#each selectedCurationContextOptions as context (context.context_id)}
													<label class="research-understanding-workbench__check-item">
														<input
															type="checkbox"
															checked={curationContextIds.includes(context.context_id)}
															disabled={curationSubmitting}
															on:change={() => toggleCurationContext(context.context_id)}
														/>
														<span>
															<strong>{context.label}</strong>
															<small>{contextCurationMeta(context)}</small>
															{#if context.limitations.length}
																<em>{listLabel(context.limitations)}</em>
															{/if}
														</span>
													</label>
												{/each}
											</div>
										{:else}
											<p class="research-understanding-workbench__picker-empty">
												{$t('research.understanding.curationNoContextRefs')}
											</p>
										{/if}
									</fieldset>
									<label>
										<span>{$t('research.understanding.curationNote')}</span>
										<textarea
											id={`${titleId}-curation-note`}
											name="curation_note"
											bind:value={curationNote}
											disabled={curationSubmitting}
											maxlength="2000"
											rows="3"
										></textarea>
									</label>
									<label>
										<span>{$t('research.understanding.curationReviewer')}</span>
										<input
											id={`${titleId}-curation-reviewer`}
											name="curation_reviewer"
											bind:value={curationReviewer}
											disabled={curationSubmitting}
											maxlength="120"
										/>
									</label>
									<button
										type="submit"
										disabled={curationSubmitting || !collectionId || !curationStatement.trim()}
									>
										{curationSubmitting
											? $t('research.understanding.curationSaving')
											: $t('research.understanding.curationSubmit')}
									</button>
									{#if curationMessage}
										<p class="research-understanding-workbench__feedback-state" role="status">
											{curationMessage}
										</p>
									{/if}
									{#if curationError}
										<p
											class="research-understanding-workbench__feedback-state research-understanding-workbench__feedback-state--error"
											role="alert"
										>
											{curationError}
										</p>
									{/if}
								</form>
							{/if}

							{#if !selectedFinding && selectedEffect && (selectedEffect.variable_axis || selectedEffect.target_property || selectedEffect.effect_direction)}
								<div class="research-understanding-workbench__context research-understanding-workbench__context--compact">
									{#if selectedEffect.variable_axis}
										<div>
											<span>{$t('research.understanding.variableAxis')}</span>
											<p>{selectedEffect.variable_axis}</p>
										</div>
									{/if}
									{#if selectedEffect.target_property}
										<div>
											<span>{$t('research.understanding.targetProperty')}</span>
											<p>{selectedEffect.target_property}</p>
										</div>
									{/if}
									{#if selectedEffect.effect_direction}
										<div>
											<span>{$t('research.understanding.relationDirection')}</span>
											<p>{relationLabel(selectedEffect.effect_direction)}</p>
										</div>
									{/if}
								</div>
							{/if}

							{#if selectedFinding}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.understanding.findingEvidence')}</h5>
									{#each selectedFindingEvidenceGroups() as group (group.role)}
										<section class="research-understanding-workbench__evidence-group">
											<h6>{findingEvidenceGroupLabel(group.role)}</h6>
											{#each group.items as ref (ref.evidence_ref_id)}
												{@const href = evidenceHref(ref)}
												{@const sourceText = evidenceSourceText(ref)}
												{#if href}
													<a class="research-understanding-workbench__evidence" {href}>
														<strong>{readableEvidenceTitle(ref.title)}</strong>
														<span>{evidenceMeta(ref)}</span>
														{#if sourceText}
															<p>{sourceText}</p>
														{:else}
															<small>{$t('research.understanding.noEvidenceSourceText')}</small>
														{/if}
													</a>
												{:else}
													<div class="research-understanding-workbench__evidence">
														<strong>{readableEvidenceTitle(ref.title)}</strong>
														<span>{evidenceMeta(ref)}</span>
														{#if sourceText}
															<p>{sourceText}</p>
														{:else}
															<small>{$t('research.understanding.noEvidenceSourceText')}</small>
														{/if}
													</div>
												{/if}
											{/each}
										</section>
									{:else}
										<div class="research-understanding-workbench__empty">
											{$t('research.understanding.noFindingEvidence')}
										</div>
									{/each}
								</div>
							{:else}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.understanding.evidenceRefs')}</h5>
									{#each selectedEvidenceRefs as ref (ref.evidence_ref_id)}
										{@const href = evidenceHref(ref)}
										{@const sourceText = evidenceSourceText(ref)}
										{#if href}
											<a class="research-understanding-workbench__evidence" {href}>
												<strong>{readableEvidenceTitle(ref.title)}</strong>
												<span>{evidenceMeta(ref)}</span>
												{#if sourceText}
													<p>{sourceText}</p>
												{:else}
													<small>{$t('research.understanding.noEvidenceSourceText')}</small>
												{/if}
											</a>
										{:else}
											<div class="research-understanding-workbench__evidence">
												<strong>{readableEvidenceTitle(ref.title)}</strong>
												<span>{evidenceMeta(ref)}</span>
												{#if sourceText}
													<p>{sourceText}</p>
												{:else}
													<small>{$t('research.understanding.noEvidenceSourceText')}</small>
												{/if}
											</div>
										{/if}
									{:else}
										<div class="research-understanding-workbench__empty">
											{$t('research.understanding.noEvidence')}
										</div>
									{/each}
								</div>
							{/if}

							<div class="research-understanding-workbench__detail-section">
								<h5>{$t('research.understanding.contexts')}</h5>
								{#each (selectedFinding ? selectedFindingDisplayContextRefs : selectedContextRefs) as context (context.context_id)}
									<div class="research-understanding-workbench__context">
										<strong>{context.label}</strong>
										{#if context.material_scope.length}
											<div>
												<span>{$t('research.understanding.contextMaterial')}</span>
												<p>{listLabel(context.material_scope)}</p>
											</div>
										{/if}
										{#if context.property_scope.length}
											<div>
												<span>{$t('research.understanding.contextProperty')}</span>
												<p>{listLabel(context.property_scope)}</p>
											</div>
										{/if}
										{#if context.process_summary}
											<div>
												<span>{$t('research.understanding.contextProcess')}</span>
												<p>{context.process_summary}</p>
											</div>
										{/if}
										{#if context.test_summary}
											<div>
												<span>{$t('research.understanding.contextTest')}</span>
												<p>{context.test_summary}</p>
											</div>
										{/if}
										{#if context.limitations.length}
											<div>
												<span>{$t('research.understanding.limitations')}</span>
												<p>{listLabel(context.limitations)}</p>
											</div>
										{/if}
									</div>
								{:else}
									<div class="research-understanding-workbench__empty">
										{$t('research.understanding.noContexts')}
									</div>
								{/each}
								{#if selectedFinding && selectedHiddenFindingContextCount > 0}
									<p class="research-understanding-workbench__context-note">
										{$t('research.understanding.hiddenFindingContextCount', {
											count: selectedHiddenFindingContextCount
										})}
									</p>
								{/if}
							</div>

							<div class="research-understanding-workbench__detail-section">
								<h5>{$t('research.understanding.relatedRelations')}</h5>
								{#each selectedReadableRelations.slice(0, 5) as relation (relation.relation_id)}
									<div class="research-understanding-workbench__context">
										<div class="research-understanding-workbench__meta">
											<span>{relationLabel(relation.relation_type)}</span>
											<span>{relationStatusLabel(relation.status)}</span>
											{#if relation.confidence !== null}
												<span>{confidenceLabel(relation.confidence)}</span>
											{/if}
										</div>
										<p>{relationSummary(relation)}</p>
										{#if relation.conditions.length}
											<small>
												{$t('research.understanding.contextPrefix')}
												{listLabel(relation.conditions)}
											</small>
										{/if}
										{#if relation.warnings.length}
											<div class="research-understanding-workbench__chips">
												{#each relation.warnings as warning (`${relation.relation_id}-${warning}`)}
													<span>{humanizeCode(warning)}</span>
												{/each}
											</div>
										{/if}
									</div>
								{:else}
									<div class="research-understanding-workbench__empty">
										{$t('research.understanding.noRelations')}
									</div>
								{/each}
								{#if selectedHiddenRelationCount || selectedReadableRelations.length > 5}
									<small>
										{$t('research.understanding.hiddenRelationCount', {
											count:
												selectedHiddenRelationCount +
												Math.max(0, selectedReadableRelations.length - 5)
										})}
									</small>
								{/if}
							</div>

							{#if selectedCuration}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.understanding.curationApplied')}</h5>
									<div class="research-understanding-workbench__context">
										{#if selectedClaim}
											<div>
												<span>{$t('research.understanding.originalClaim')}</span>
												<p>{selectedClaim.statement}</p>
											</div>
											<div>
												<span>{$t('research.understanding.originalClassification')}</span>
												<p>
													{claimTypeLabel(selectedClaim.claim_type)}
													·
													{statusLabel(selectedClaim.status)}
												</p>
											</div>
										{/if}
										<div>
											<span>{$t('research.understanding.curationStatement')}</span>
											<p>{selectedCuration.curated_statement}</p>
										</div>
										{#if selectedCuration.note}
											<div>
												<span>{$t('research.understanding.curationNote')}</span>
												<p>{selectedCuration.note}</p>
											</div>
										{/if}
										{#if selectedCuration.reviewer || selectedCuration.updated_at}
											<small>
												{[selectedCuration.reviewer, selectedCuration.updated_at]
													.filter(Boolean)
													.join(' · ')}
											</small>
										{/if}
									</div>
								</div>
							{/if}

							<div class="research-understanding-workbench__detail-section">
								<h5>{$t('research.understanding.feedbackHistory')}</h5>
								{#each selectedFeedback as item (item.feedback_id)}
									<div class="research-understanding-workbench__context">
										<div>
											<span>
												{feedbackStatusLabel(item.review_status)}
												·
												{feedbackIssueLabel(item.issue_type)}
											</span>
											{#if item.note}
												<p>{item.note}</p>
											{:else}
												<p>{$t('research.understanding.noFeedbackNote')}</p>
											{/if}
										</div>
										{#if item.reviewer || item.created_at}
											<small>{[item.reviewer, item.created_at].filter(Boolean).join(' · ')}</small>
										{/if}
									</div>
								{:else}
									<div class="research-understanding-workbench__empty">
										{$t('research.understanding.noFeedback')}
									</div>
								{/each}
							</div>

							{#if selectedClaim && (selectedClaim.warnings.length || selectedClaim.source_object_ids.length)}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.warnings')}</h5>
									{#if selectedClaim.warnings.length}
										<div class="research-understanding-workbench__chips">
											{#each selectedClaim.warnings as warning (`${selectedClaim.claim_id}-${warning}`)}
												<span>{humanizeCode(warning)}</span>
											{/each}
										</div>
									{/if}
									{#if selectedClaim.source_object_ids.length}
										<details class="research-understanding-workbench__debug">
											<summary>{$t('research.understanding.auditBinding')}</summary>
											<small>{listLabel(selectedClaim.source_object_ids)}</small>
										</details>
									{/if}
								</div>
							{/if}
						</article>
					{:else}
						<div class="research-understanding-workbench__empty">
							{$t('research.understanding.noSelectedClaim')}
						</div>
					{/if}
				</section>
			{/if}
		{:else}
			<div class="research-understanding-workbench__empty">
				{$t('research.understanding.empty')}
			</div>
		{/if}
	{:else}
		<div class="research-understanding-workbench__empty">
			{$t('research.understanding.unavailable')}
		</div>
	{/if}
</section>

<style>
	.research-understanding-workbench {
		display: grid;
		gap: 14px;
		min-width: 0;
		max-width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: 20px;
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.research-understanding-workbench__heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
		min-width: 0;
	}

	.research-understanding-workbench__heading div,
	.research-understanding-workbench__column,
	.research-understanding-workbench__card {
		display: grid;
		gap: 12px;
		min-width: 0;
	}

	.research-understanding-workbench__heading div {
		gap: 5px;
	}

	.research-understanding-workbench__heading h3,
	.research-understanding-workbench__column h4 {
		margin: 0;
		color: var(--text-primary);
	}

	.research-understanding-workbench__heading h3 {
		font-size: 16px;
		line-height: 22px;
	}

	.research-understanding-workbench__heading p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__heading > span,
	.research-understanding-workbench__meta span,
	.research-understanding-workbench__chips span {
		border: 1px solid var(--border-default);
		border-radius: 999px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__heading > span {
		padding: 4px 9px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 16px;
		text-transform: uppercase;
	}

	.research-understanding-workbench__summary {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 10px;
	}

	.research-understanding-workbench__summary div {
		display: grid;
		gap: 3px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__summary strong {
		color: var(--text-primary);
		font-size: 24px;
		line-height: 30px;
	}

	.research-understanding-workbench__summary span,
	.research-understanding-workbench__meta span,
	.research-understanding-workbench__card small,
	.research-understanding-workbench__evidence span,
	.research-understanding-workbench__evidence small,
	.research-understanding-workbench__column-heading span,
	.research-understanding-workbench__filter-group > span,
	.research-understanding-workbench__detail small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__filters {
		display: grid;
		gap: 10px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__filter-group {
		display: grid;
		gap: 7px;
		min-width: 0;
	}

	.research-understanding-workbench__segmented {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__segmented button {
		min-height: 30px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 10px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font: inherit;
		font-size: 12px;
		font-weight: 650;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__segmented button:hover,
	.research-understanding-workbench__segmented button:focus-visible,
	.research-understanding-workbench__segment--active {
		border-color: var(--color-accent);
		color: var(--text-primary);
		background: var(--surface-card);
	}

	.research-understanding-workbench__column-heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
		min-width: 0;
	}

	.research-understanding-workbench__column--list,
	.research-understanding-workbench__detail-view {
		max-width: 1180px;
	}

	.research-understanding-workbench__column h4 {
		font-size: 15px;
		line-height: 21px;
	}

	.research-understanding-workbench__column-heading h4,
	.research-understanding-workbench__detail-section h5,
	.research-understanding-workbench__evidence-group h6 {
		margin: 0;
		color: var(--text-primary);
	}

	.research-understanding-workbench__card,
	.research-understanding-workbench__evidence {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 13px;
		background: var(--bg-subtle);
		text-decoration: none;
	}

	.research-understanding-workbench__card--claim {
		width: 100%;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.research-understanding-workbench__card--claim:hover,
	.research-understanding-workbench__card--claim:focus-visible {
		border-color: var(--color-accent);
		background: var(--surface-card);
	}

	.research-understanding-workbench__meta,
	.research-understanding-workbench__chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__meta span,
	.research-understanding-workbench__chips span {
		padding: 3px 8px;
	}

	.research-understanding-workbench__card p {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__card > strong,
	.research-understanding-workbench__claim-header > strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__detail,
	.research-understanding-workbench__claim-header,
	.research-understanding-workbench__detail-section,
	.research-understanding-workbench__context,
	.research-understanding-workbench__feedback {
		display: grid;
		gap: 10px;
		min-width: 0;
	}

	.research-understanding-workbench__claim-stats {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__source-list {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.research-understanding-workbench__source-list > span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
	}

	.research-understanding-workbench__source-list ul {
		display: grid;
		gap: 3px;
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__source-list li {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.research-understanding-workbench__table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
	}

	.research-understanding-workbench__findings-table {
		width: 100%;
		min-width: 980px;
		border-collapse: collapse;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__findings-table th,
	.research-understanding-workbench__findings-table td {
		border-bottom: 1px solid var(--border-default);
		padding: 10px;
		text-align: left;
		vertical-align: top;
	}

	.research-understanding-workbench__findings-table th {
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		white-space: nowrap;
	}

	.research-understanding-workbench__findings-table tr:last-child td {
		border-bottom: 0;
	}

	.research-understanding-workbench__findings-table td {
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__findings-table td:nth-child(2),
	.research-understanding-workbench__findings-table td:nth-child(3),
	.research-understanding-workbench__findings-table td:nth-child(4),
	.research-understanding-workbench__findings-table td:nth-child(5),
	.research-understanding-workbench__findings-table td:nth-child(8) {
		color: var(--text-secondary);
	}

	.research-understanding-workbench__finding-main {
		width: 28%;
		min-width: 260px;
	}

	.research-understanding-workbench__finding-main button {
		display: grid;
		gap: 4px;
		width: 100%;
		border: 0;
		padding: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.research-understanding-workbench__finding-main button:hover strong,
	.research-understanding-workbench__finding-main button:focus-visible strong {
		color: var(--color-accent);
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.research-understanding-workbench__finding-main button:disabled {
		cursor: not-allowed;
		opacity: 0.65;
	}

	.research-understanding-workbench__finding-main strong {
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__finding-main span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__grade {
		display: inline-flex;
		align-items: center;
		min-height: 24px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 2px 8px;
		background: var(--bg-subtle);
		color: var(--text-primary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		white-space: nowrap;
	}

	.research-understanding-workbench__detail {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 14px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__claim-header > p,
	.research-understanding-workbench__context p {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__review-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 0;
	}

	.research-understanding-workbench__review-actions button {
		min-height: 34px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 7px 12px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 13px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__review-actions button:hover,
	.research-understanding-workbench__review-actions button:focus-visible,
	.research-understanding-workbench__review-action--active {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.research-understanding-workbench__detail-section {
		padding-top: 10px;
		border-top: 1px solid var(--border-default);
	}

	.research-understanding-workbench__detail-section h5 {
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__evidence-group {
		display: grid;
		gap: 8px;
		min-width: 0;
	}

	.research-understanding-workbench__evidence-group h6 {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
	}

	.research-understanding-workbench__feedback {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__feedback--primary {
		border-color: rgba(37, 99, 235, 0.36);
		box-shadow: inset 3px 0 0 var(--color-accent);
	}

	.research-understanding-workbench__feedback h5 {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__feedback label {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.research-understanding-workbench__feedback label span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.research-understanding-workbench__feedback select,
	.research-understanding-workbench__feedback textarea,
	.research-understanding-workbench__feedback input {
		width: 100%;
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 8px 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__feedback textarea {
		resize: vertical;
	}

	.research-understanding-workbench__curation-picker {
		display: grid;
		gap: 8px;
		margin: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__curation-picker legend {
		padding: 0 4px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.research-understanding-workbench__check-list {
		display: grid;
		gap: 7px;
		min-width: 0;
	}

	.research-understanding-workbench__check-item {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		align-items: start;
		gap: 9px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__feedback .research-understanding-workbench__check-item input {
		width: 16px;
		min-width: 16px;
		height: 16px;
		margin-top: 2px;
		padding: 0;
		cursor: pointer;
	}

	.research-understanding-workbench__check-item > span {
		display: grid;
		gap: 3px;
		min-width: 0;
	}

	.research-understanding-workbench__check-item strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__check-item small,
	.research-understanding-workbench__check-item em,
	.research-understanding-workbench__picker-empty {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__check-item em {
		display: block;
		font-style: normal;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__picker-empty {
		margin: 0;
	}

	.research-understanding-workbench__feedback button {
		justify-self: start;
		min-height: 34px;
		border: 1px solid var(--color-accent);
		border-radius: var(--radius-md);
		padding: 7px 12px;
		background: var(--color-accent);
		color: var(--color-on-accent, #fff);
		font: inherit;
		font-size: 13px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__feedback button:disabled {
		cursor: not-allowed;
		opacity: 0.62;
	}

	.research-understanding-workbench__back {
		min-height: 34px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 6px 11px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 13px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__back:hover,
	.research-understanding-workbench__back:focus-visible {
		border-color: var(--color-accent);
	}

	.research-understanding-workbench__feedback-state {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__context-note {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__feedback-state--error {
		color: var(--color-danger);
	}

	.research-understanding-workbench__context {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 11px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__context--compact {
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	}

	.research-understanding-workbench__context--finding-chain {
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	}

	.research-understanding-workbench__evidence {
		display: grid;
		gap: 7px;
		color: inherit;
	}

	.research-understanding-workbench__evidence[href]:hover {
		border-color: var(--color-accent);
		background: var(--surface-card);
	}

	.research-understanding-workbench__context strong,
	.research-understanding-workbench__evidence strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__context div {
		display: grid;
		gap: 2px;
	}

	.research-understanding-workbench__context div span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.research-understanding-workbench__evidence p {
		margin: 0;
		border-left: 3px solid var(--border-default);
		padding-left: 10px;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 21px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__empty {
		border: 1px dashed var(--border-default);
		border-radius: var(--radius-md);
		padding: 16px;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		background: var(--bg-subtle);
	}

	:global(:root[data-theme='dark']) .research-understanding-workbench__heading > span,
	:global(:root[data-theme='dark']) .research-understanding-workbench__meta span,
	:global(:root[data-theme='dark']) .research-understanding-workbench__chips span,
	:global(:root[data-theme='dark']) .research-understanding-workbench__segmented button {
		background: rgba(120, 140, 180, 0.16);
	}

	@media (max-width: 760px) {
		.research-understanding-workbench {
			padding: 16px;
		}

		.research-understanding-workbench__heading {
			flex-direction: column;
		}

		.research-understanding-workbench__summary {
			grid-template-columns: 1fr;
		}

	}
</style>
