<script lang="ts">
	import { resolve } from '$app/paths';
	import { tick } from 'svelte';
	import { isHttpStatusError } from '../../../_shared/api';
	import { authState } from '../../../_shared/auth';
	import { t } from '../../../_shared/i18n';
	import {
		createResearchUnderstandingCuration,
		createResearchUnderstandingFeedback,
		fetchResearchUnderstandingCollectionDataset,
		fetchResearchUnderstandingDataset,
		fetchResearchUnderstandingFeedback,
		fetchResearchUnderstandingCurations,
		formatShortIdentifier,
		researchUnderstandingCollectionDatasetUrl,
		researchUnderstandingDatasetUrl,
		type ResearchUnderstanding,
		type ResearchUnderstandingClaim,
		type ResearchUnderstandingCuration,
		type ResearchUnderstandingDataset,
		type ResearchUnderstandingDatasetExportFormat,
		type ResearchUnderstandingDatasetLabelStatus,
		type ResearchUnderstandingDatasetSample,
		type ResearchUnderstandingDatasetUseStatus,
		type ResearchUnderstandingAxisCoverageItem,
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
	export let initialFocus: '' | 'review_queue' | 'training_ready' = '';
	export let initialFindingId = '';

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
		'insufficient_evidence',
		'wrong_variable',
		'wrong_outcome',
		'wrong_direction',
		'wrong_context',
		'wrong_relation',
		'overclaim',
		'unclear_statement',
		'other'
	];
	const CURATION_CLAIM_TYPE_OPTIONS = CLAIM_TYPE_ORDER.filter((type) => type !== 'all');
	const CURATION_STATUS_OPTIONS = CLAIM_STATUS_ORDER.filter((status) => status !== 'all');
	const DATASET_LABEL_STATUS_ORDER: ResearchUnderstandingDatasetLabelStatus[] = [
		'candidate',
		'silver',
		'gold',
		'rejected'
	];
	type FindingDatasetUseFilter = 'all' | ResearchUnderstandingDatasetUseStatus;
	const DATASET_USE_STATUS_FILTER_ORDER: FindingDatasetUseFilter[] = [
		'all',
		'training_ready',
		'review_candidate',
		'rejected'
	];
	const REJECTING_FEEDBACK_ISSUES = new Set<ResearchUnderstandingFeedbackIssueType>([
		'evidence_not_grounded',
		'missing_evidence',
		'insufficient_evidence',
		'wrong_variable',
		'wrong_outcome',
		'wrong_direction',
		'wrong_context',
		'wrong_relation',
		'overclaim',
		'unclear_statement'
	]);
	type FindingDatasetTrust = {
		labelStatus: ResearchUnderstandingDatasetLabelStatus;
		datasetUseStatus: ResearchUnderstandingDatasetUseStatus;
		source: 'human_curation' | 'human_feedback' | 'ai_curation' | 'ai_feedback' | 'rejected' | 'candidate';
	};
	type FindingEvidenceRole = keyof ResearchUnderstandingPresentationFinding['evidence_bundle'];
	const FINDING_MAIN_EVIDENCE_ROLES: FindingEvidenceRole[] = [
		'direct_result',
		'mechanism',
		'conflict'
	];
	const FINDING_SECONDARY_EVIDENCE_ROLES: FindingEvidenceRole[] = [
		'condition_context',
		'background',
		'noise',
		'uncategorized'
	];
	const FINDING_CONTEXT_AXIS_TERMS = [
		'fatigue',
		'hip',
		'hot isostatic pressing',
		'as built',
		'preheating',
		'build platform preheating',
		'microhardness',
		'corrosion',
		'pitting corrosion'
	];
	const FINDING_CONTEXT_GENERIC_FRAGMENTS = [
		'variable',
		'test specimen',
		'source object ids',
		'source_object_ids',
		'evidence ref ids',
		'evidence_ref_ids'
	];

	let selectedClaimType = 'all';
	let selectedClaimStatus = 'all';
	let selectedDatasetUseStatus: FindingDatasetUseFilter = 'all';
	let selectedEffectId = '';
	let selectedFindingId = '';
	let detailMode = false;
	let activeReviewPanel: 'feedback' | 'curation' | '' = '';
	let datasetReviewCandidatesOnly = false;
	let curationClaimType = 'finding';
	let curationStatus = 'limited';
	let curationSupportGrade = 'partial';
	let curationStatement = '';
	let curationVariables = '';
	let curationMediators = '';
	let curationOutcomes = '';
	let curationDirection = '';
	let curationScopeSummary = '';
	let curationEvidenceRefIds: string[] = [];
	let curationContextIds: string[] = [];
	let curationNote = '';
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
	let feedbackSubmitting = false;
	let feedbackMessage = '';
	let feedbackError = '';
	let lastFeedbackTargetId = '';
	let lastUsesFindings = false;
	let datasetSummary: ResearchUnderstandingDataset | null = null;
	let datasetScopeKey = '';
	let datasetLoading = false;
	let datasetError = '';
	let datasetRequestSequence = 0;
	let datasetPanelOpen = false;
	let collectionDatasetSummary: ResearchUnderstandingDataset | null = null;
	let collectionDatasetScopeKey = '';
	let collectionDatasetLoading = false;
	let collectionDatasetError = '';
	let collectionDatasetRequestSequence = 0;
	let appliedInitialFocusKey = '';
	let appliedInitialFindingKey = '';

	$: presentation = understanding?.presentation ?? null;
	$: presentationSummary = presentation?.summary ?? null;
	$: effectRows = presentation?.effects ?? [];
	$: allFindingRows = presentation?.findings ?? [];
	$: primaryFindingRows = presentation?.primary_findings ?? [];
	$: reviewQueueFindingRows = presentation?.review_queue_findings ?? [];
	$: hasReviewQueueFindingProjection = Array.isArray(presentation?.review_queue_findings);
	$: allDisplayFindingRows = allFindingRows.length
		? allFindingRows
		: dedupeFindings([...primaryFindingRows, ...reviewQueueFindingRows]);
	$: reviewableFindingRows = hasReviewQueueFindingProjection
		? reviewQueueFindingRows
		: allDisplayFindingRows.filter((finding) =>
				findingNeedsReview(finding, feedbackByTargetId, reviewQueueClaimIds)
			);
	$: if (!primaryFindingRows.length && reviewableFindingRows.length && !reviewQueueOnly) {
		reviewQueueOnly = true;
	}
	$: findingRows = datasetReviewCandidatesOnly
		? allDisplayFindingRows
		: reviewQueueOnly
			? reviewableFindingRows
			: primaryFindingRows;
	$: usesFindings =
		allFindingRows.length > 0 ||
		primaryFindingRows.length > 0 ||
		reviewQueueFindingRows.length > 0;
	$: hasUnprojectedEffects = !usesFindings && effectRows.length > 0;
	$: if (usesFindings !== lastUsesFindings) {
		lastUsesFindings = usesFindings;
		selectedClaimStatus = 'all';
		selectedDatasetUseStatus = 'all';
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
	$: reviewQueueFindingIds = new Set(reviewableFindingRows.map((finding) => finding.finding_id));
	$: reviewQueueFindingCount = usesFindings
		? (presentationSummary?.review_queue_finding_count ?? reviewableFindingRows.length)
		: 0;
	$: reviewLoopFindingCount = usesFindings ? allDisplayFindingRows.length : 0;
	$: reviewLoopMissingDirectEvidenceCount = usesFindings
		? allDisplayFindingRows.filter((finding) => findingDirectEvidenceCount(finding) === 0).length
		: 0;
	$: reviewQueueCount = usesFindings
		? reviewQueueFindingCount
		: effectRows.filter(
				(effect) => effect.needs_review || reviewQueueClaimIds.has(effect.claim_id)
			).length;
	$: primaryFindingCount = usesFindings ? primaryFindingRows.length : 0;
	$: primaryFindingPaperCount = usesFindings ? countUniqueFindingPapers(primaryFindingRows) : 0;
	$: collectionDocumentCount = presentationSummary?.collection_document_count ?? 0;
	$: primaryFindingPaperCoverage = primaryFindingCoverageLabel(primaryFindingPaperCount);
	$: primaryFindingDirectEvidenceCount = usesFindings
		? primaryFindingRows.reduce((count, finding) => count + findingDirectEvidenceCount(finding), 0)
		: 0;
	$: axisCoverage = presentationSummary?.axis_coverage ?? { variables: [], properties: [] };
	$: hasAxisCoverage = Boolean(axisCoverage.variables.length || axisCoverage.properties.length);
	$: axisCoverageGapGroups = hasAxisCoverage ? buildAxisCoverageGapGroups(axisCoverage) : [];
	$: answerBoundary = hasAxisCoverage
		? buildAnswerBoundary(axisCoverage, primaryFindingRows, feedbackByTargetId, curationsByTargetId)
		: null;
	$: datasetTrainingReadySampleCount =
		datasetSummary?.quality_summary.training_ready_sample_count ?? 0;
	$: datasetTrainingMessageSampleCount =
		datasetSummary?.quality_summary.training_message_sample_count ?? 0;
	$: datasetProtocolReadySampleCount =
		datasetSummary?.quality_summary.protocol_ready_sample_count ?? 0;
	$: datasetReviewCandidateSampleCount =
		datasetSummary?.quality_summary.review_candidate_sample_count ?? 0;
	$: expertReviewCandidateCount = datasetSummary
		? datasetReviewCandidateSampleCount
		: reviewQueueFindingCount;
	$: datasetLabelCounts = datasetSummary?.label_counts ?? {
		candidate: 0,
		silver: 0,
		gold: 0,
		rejected: 0
	};
	$: datasetErrorCategories = datasetSummary
		? Object.entries(datasetSummary.quality_summary.by_error_category)
				.filter(([category, count]) => count > 0 && !['none', 'unreviewed'].includes(category))
				.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
		: [];
	$: datasetReviewReasons = datasetSummary
		? topPositiveCounts(
				preferredReviewRiskCounts(
					datasetSummary.quality_summary.by_review_candidate_reason,
					datasetSummary.quality_summary.by_review_reason,
					datasetReviewCandidateSampleCount
				),
				5
			)
		: [];
	$: datasetSystemWarnings = datasetSummary
		? topPositiveCounts(
				preferredReviewRiskCounts(
					datasetSummary.quality_summary.by_review_candidate_warning,
					datasetSummary.quality_summary.by_system_warning,
					datasetReviewCandidateSampleCount
				),
				5
			)
		: [];
	$: collectionDatasetTrainingReadySampleCount =
		collectionDatasetSummary?.quality_summary.training_ready_sample_count ?? 0;
	$: collectionDatasetTrainingMessageSampleCount =
		collectionDatasetSummary?.quality_summary.training_message_sample_count ?? 0;
	$: collectionDatasetProtocolReadySampleCount =
		collectionDatasetSummary?.quality_summary.protocol_ready_sample_count ?? 0;
	$: collectionDatasetReviewCandidateSampleCount =
		collectionDatasetSummary?.quality_summary.review_candidate_sample_count ?? 0;
	$: collectionDatasetLabelCounts = collectionDatasetSummary?.label_counts ?? {
		candidate: 0,
		silver: 0,
		gold: 0,
		rejected: 0
	};
	$: collectionDatasetErrorCategories = collectionDatasetSummary
		? Object.entries(collectionDatasetSummary.quality_summary.by_error_category)
				.filter(([category, count]) => count > 0 && !['none', 'unreviewed'].includes(category))
				.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
		: [];
	$: collectionDatasetBucketCounts = collectionDatasetSummary
		? Object.entries(collectionDatasetSummary.quality_summary.by_presentation_bucket)
				.filter(([, count]) => count > 0)
				.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
		: [];
	$: collectionDatasetReviewReasons = collectionDatasetSummary
		? topPositiveCounts(
				preferredReviewRiskCounts(
					collectionDatasetSummary.quality_summary.by_review_candidate_reason,
					collectionDatasetSummary.quality_summary.by_review_reason,
					collectionDatasetReviewCandidateSampleCount
				),
				5
			)
		: [];
	$: collectionDatasetSystemWarnings = collectionDatasetSummary
		? topPositiveCounts(
				preferredReviewRiskCounts(
					collectionDatasetSummary.quality_summary.by_review_candidate_warning,
					collectionDatasetSummary.quality_summary.by_system_warning,
					collectionDatasetReviewCandidateSampleCount
				),
				5
			)
		: [];
	$: expertSummary = usesFindings
		? expertReadinessSummary(
				primaryFindingRows,
				expertReviewCandidateCount,
				datasetTrainingReadySampleCount,
				datasetReviewCandidateSampleCount
			)
		: null;
	$: reviewLoopStatus = expertSummary
		? reviewLoopStatusValue(
				expertSummary,
				datasetLoading,
				Boolean(datasetSummary),
				reviewerReady,
				datasetTrainingReadySampleCount,
				datasetTrainingMessageSampleCount,
				datasetProtocolReadySampleCount,
				datasetReviewCandidateSampleCount
			)
		: '';
	$: reviewLoopSteps = expertSummary
		? reviewLoopStepItems(
				expertSummary,
				reviewerReady,
				datasetTrainingReadySampleCount,
				datasetTrainingMessageSampleCount,
				datasetProtocolReadySampleCount,
				datasetReviewCandidateSampleCount
			)
		: [];
	$: reviewLoopChecklist = expertSummary
		? reviewLoopChecklistItems(
				reviewerReady,
				Boolean(datasetSummary),
				datasetTrainingReadySampleCount,
				datasetTrainingMessageSampleCount,
				datasetProtocolReadySampleCount,
				datasetReviewCandidateSampleCount,
				reviewLoopFindingCount,
				reviewLoopMissingDirectEvidenceCount
			)
		: [];
	$: reviewLoopErrorItems = datasetErrorCategories.slice(0, 3);
	$: filteredEffects = effectRows.filter(
		(effect) =>
			(selectedClaimType === 'all' || effect.claim_type === selectedClaimType) &&
			(selectedClaimStatus === 'all' || effect.support_status === selectedClaimStatus) &&
			(!reviewQueueOnly || effect.needs_review || reviewQueueClaimIds.has(effect.claim_id))
	);
	$: filteredFindings = findingRows.filter(
		(finding) =>
			(selectedClaimStatus === 'all' ||
				findingForDisplay(finding).support_grade === selectedClaimStatus) &&
			(selectedDatasetUseStatus === 'all' ||
				findingDatasetTrust(finding).datasetUseStatus === selectedDatasetUseStatus) &&
			(!reviewQueueOnly ||
				finding.review_status === 'needs_review' ||
				reviewQueueFindingIds.has(finding.finding_id) ||
				reviewQueueClaimIds.has(finding.claim_id))
	);
	$: visibleFindingRows = usesFindings ? filteredFindings : [];
	$: reviewCandidateFindingRows = allDisplayFindingRows.filter(
		(finding) => findingDatasetTrust(finding).datasetUseStatus === 'review_candidate'
	);
	$: nextReviewCandidateFinding =
		(datasetSummary?.quality_summary.next_review_finding_id
			? reviewCandidateFindingRows.find(
					(finding) =>
						finding.finding_id === datasetSummary?.quality_summary.next_review_finding_id
				)
			: null) ??
		reviewCandidateFindingRows[0] ??
		null;
	$: nextReviewCandidateSample = nextReviewCandidateFinding
		? findingDatasetSampleFor(nextReviewCandidateFinding)
		: null;
	$: visibleEffectRows = usesFindings ? [] : filteredEffects;
	$: selectableEffects = usesFindings
		? filteredFindings
				.map((finding) => findingEffectFor(finding))
				.filter((effect): effect is ResearchUnderstandingPresentationEffect => Boolean(effect))
		: visibleEffectRows;
	$: selectedFinding = detailMode && selectedFindingId
		? (allDisplayFindingRows.find((finding) => finding.finding_id === selectedFindingId) ?? null)
		: null;
	$: selectedReviewCandidateIndex = selectedFinding
		? reviewCandidateFindingRows.findIndex(
				(finding) => finding.finding_id === selectedFinding.finding_id
			)
		: -1;
	$: selectedReviewQueuePosition =
		selectedReviewCandidateIndex >= 0
			? $t('research.understanding.reviewQueuePosition', {
					current: selectedReviewCandidateIndex + 1,
					total: reviewCandidateFindingRows.length
				})
			: '';
	$: claimTypeCounts = countEffectsBy(effectRows, 'claim_type');
	$: claimStatusCounts = (() => {
		if (!usesFindings) return countEffectsBy(effectRows, 'support_status');
		const counts = new Map<string, number>([['all', findingRows.length]]);
		for (const finding of findingRows) {
			const grade = findingForDisplay(finding).support_grade;
			counts.set(grade, (counts.get(grade) ?? 0) + 1);
		}
		return counts;
	})();
	$: findingDatasetUseCounts = usesFindings ? countFindingsByDatasetUse(findingRows) : new Map();
	$: if (selectedFindingId && selectedEffectId) {
		selectedEffectId = '';
	}
	$: if (understanding && detailMode && !selectedFindingId && selectableEffects.length && !selectableEffects.some((effect) => effect.effect_id === selectedEffectId)) {
		selectedEffectId = selectableEffects[0]?.effect_id ?? '';
	}
	$: if ((!selectableEffects.length || !detailMode || selectedFindingId) && selectedEffectId) {
		selectedEffectId = '';
	}
	$: if (!usesFindings && detailMode) {
		detailMode = false;
		selectedFindingId = '';
		selectedEffectId = '';
		activeReviewPanel = '';
	}
	$: selectedEffect =
		detailMode && !selectedFindingId
			? (selectableEffects.find((effect) => effect.effect_id === selectedEffectId) ?? null)
			: null;
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
	$: selectedDisplayFinding = selectedFinding
		? findingForDisplay(selectedFinding, selectedCuration)
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
		: selectedEffect
			? presentationEvidenceForIds(selectedEffect.evidence_ref_ids)
			: selectedFinding
			? presentationEvidenceForIds(selectedFinding.evidence_ref_ids)
			: [];
	$: selectedContextRefs = displayClaim
		? presentationContextsForIds(displayClaim.context_ids)
		: selectedEffect
			? presentationContextsForIds(selectedEffect.context_ids)
			: selectedFinding
			? presentationContextsForIds(selectedFinding.context_ids)
			: [];
	$: selectedFindingContextRefs = selectedFinding
		? presentationContextsForIds(selectedFinding.context_ids)
		: [];
	$: selectedFindingDisplayContextRefs = selectedDisplayFinding
		? compactFindingContextDisplay(selectedFindingContextRefs, selectedDisplayFinding)
		: [];
	$: selectedFindingDecision = selectedDisplayFinding ? findingDecision(selectedDisplayFinding) : null;
	$: selectedFindingUsagePath = selectedDisplayFinding
		? findingUsagePath(selectedDisplayFinding, selectedFeedback, selectedCuration)
		: null;
	$: selectedFindingTrust = selectedFinding ? findingDatasetTrust(selectedFinding) : null;
	$: selectedFindingDatasetSample = selectedFinding ? findingDatasetSampleFor(selectedFinding) : null;
	$: selectedFindingReviewReasons = selectedDisplayFinding
		? findingReviewReasonValues(selectedDisplayFinding)
		: [];
	$: selectedFindingWarnings =
		selectedFinding && selectedFindingTrust
			? selectedFinding.warnings.filter((warning) =>
					findingReviewReasonIsVisible(selectedFinding, warning, selectedFindingTrust)
				)
			: [];
	$: selectedDetailWarnings = selectedFinding
		? selectedFindingWarnings
		: (selectedClaim?.warnings ?? []);
	$: currentReviewer = currentReviewerLabel($authState.user);
	$: reviewerReady = Boolean(currentReviewer);
	$: selectedRelatedReviewFindings = selectedFinding
		? relatedReviewFindings(selectedFinding, allDisplayFindingRows)
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
	$: currentDatasetScopeKey =
		understanding && collectionId && selectedScopeId
			? `${collectionId}:${understanding.scope.scope_type}:${selectedScopeId}`
			: '';
	$: if (
		initialFocus &&
		!initialFindingId &&
		currentDatasetScopeKey &&
		appliedInitialFocusKey !== `${currentDatasetScopeKey}:${initialFocus}`
	) {
		appliedInitialFocusKey = `${currentDatasetScopeKey}:${initialFocus}`;
		applyInitialFocus(initialFocus);
	}
	$: if (
		initialFindingId &&
		currentDatasetScopeKey &&
		allDisplayFindingRows.length &&
		appliedInitialFindingKey !== `${currentDatasetScopeKey}:${initialFindingId}`
	) {
		appliedInitialFindingKey = `${currentDatasetScopeKey}:${initialFindingId}`;
		void applyInitialFindingFocus(initialFindingId);
	}
	$: currentCollectionDatasetScopeKey =
		understanding?.scope.scope_type === 'goal' && collectionId ? `${collectionId}:goal` : '';
	$: goalCopilotHref =
		understanding?.scope.scope_type === 'goal' && collectionId && selectedScopeId
			? `${resolve('/collections/[id]/assistant', {
					id: collectionId
				})}?goal_id=${encodeURIComponent(selectedScopeId)}`
			: '';
	$: if (currentDatasetScopeKey && currentDatasetScopeKey !== datasetScopeKey) {
		void loadDatasetSummary(currentDatasetScopeKey);
	}
	$: if (
		datasetPanelOpen &&
		currentCollectionDatasetScopeKey &&
		currentCollectionDatasetScopeKey !== collectionDatasetScopeKey
	) {
		void loadCollectionDatasetSummary(currentCollectionDatasetScopeKey);
	}
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

	function findingReviewStatusForDisplay(
		finding: ResearchUnderstandingPresentationFinding,
		trust: FindingDatasetTrust = findingDatasetTrust(finding)
	) {
		if (trust.datasetUseStatus === 'training_ready' && trust.source === 'human_feedback') return 'accepted';
		if (trust.datasetUseStatus === 'training_ready' && trust.source === 'human_curation') return 'curated';
		return finding.review_status;
	}

	function findingIsUnreviewedForDisplay(
		finding: ResearchUnderstandingPresentationFinding,
		trust: FindingDatasetTrust = findingDatasetTrust(finding)
	) {
		const displayStatus = findingReviewStatusForDisplay(finding, trust);
		return displayStatus === 'needs_review' || displayStatus === 'pending_review';
	}

	function findingReviewReasonIsVisible(
		finding: ResearchUnderstandingPresentationFinding,
		reason: string,
		trust: FindingDatasetTrust = findingDatasetTrust(finding)
	) {
		if (reason === 'needs_expert_review' && !findingIsUnreviewedForDisplay(finding, trust)) {
			return false;
		}
		return true;
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

	function feedbackIssueCategory(issue: ResearchUnderstandingFeedbackIssueType) {
		if (issue === 'none') return 'none';
		if (issue === 'wrong_variable') return 'variable_error';
		if (issue === 'wrong_outcome') return 'outcome_error';
		if (issue === 'wrong_direction') return 'direction_error';
		if (issue === 'wrong_context') return 'context_error';
		if (issue === 'wrong_relation') return 'relation_error';
		if (
			issue === 'evidence_not_grounded' ||
			issue === 'missing_evidence' ||
			issue === 'insufficient_evidence'
		) {
			return 'evidence_error';
		}
		if (issue === 'overclaim') return 'claim_scope_error';
		if (issue === 'unclear_statement') return 'statement_error';
		return 'other_error';
	}

	function feedbackIssueGuidance(issue: ResearchUnderstandingFeedbackIssueType) {
		return $t(`research.understanding.feedbackIssueGuidance.${issue}`);
	}

	function datasetLabelStatusLabel(status: ResearchUnderstandingDatasetLabelStatus) {
		return translatedCatalogLabel('research.understanding.datasetLabelStatuses', status);
	}

	function datasetUseStatusLabel(status: ResearchUnderstandingDatasetUseStatus) {
		return translatedCatalogLabel('research.understanding.datasetUseStatuses', status);
	}

	function datasetUseStatusFilterLabel(status: FindingDatasetUseFilter) {
		if (status === 'all') return $t('research.understanding.allDatasetUseStatuses');
		return datasetUseStatusLabel(status);
	}

	function datasetErrorCategoryLabel(category: string) {
		return translatedCatalogLabel('research.understanding.datasetErrorCategories', category);
	}

	function datasetReviewReasonLabel(reason: string) {
		return translatedCatalogLabel('research.understanding.datasetReviewReasons', reason);
	}

	function datasetSystemWarningLabel(warning: string) {
		return translatedCatalogLabel('research.understanding.datasetSystemWarnings', warning);
	}

	function datasetPresentationBucketLabel(bucket: string) {
		return translatedCatalogLabel('research.understanding.datasetPresentationBuckets', bucket);
	}

	function findingTrustSourceLabel(source: FindingDatasetTrust['source']) {
		return translatedCatalogLabel('research.understanding.findingTrustSources', source);
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

	function topPositiveCounts(counts: Record<string, number>, limit: number) {
		return Object.entries(counts)
			.filter(([, count]) => count > 0)
			.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
			.slice(0, limit);
	}

	function preferredReviewRiskCounts(
		candidateCounts: Record<string, number>,
		allCounts: Record<string, number>,
		reviewCandidateCount: number
	) {
		if (reviewCandidateCount <= 0) return {};
		return Object.keys(candidateCounts).length ? candidateCounts : allCounts;
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

	function findingEvidenceRoleCoverageLabel(role: FindingEvidenceRole) {
		return translatedCatalogLabel('research.understanding.findingEvidenceRoleLabels', role);
	}

	function dedupeFindings(findings: ResearchUnderstandingPresentationFinding[]) {
		const seen = new Set<string>();
		const result: ResearchUnderstandingPresentationFinding[] = [];
		for (const finding of findings) {
			if (seen.has(finding.finding_id)) continue;
			seen.add(finding.finding_id);
			result.push(finding);
		}
		return result;
	}

	function findingNeedsReview(
		finding: ResearchUnderstandingPresentationFinding,
		currentFeedbackByTargetId: Map<string, ResearchUnderstandingFeedback[]>,
		currentReviewQueueClaimIds: Set<string>
	) {
		const feedback = [
			...(currentFeedbackByTargetId.get(finding.finding_id) ?? []),
			...(currentFeedbackByTargetId.get(finding.claim_id) ?? [])
		];
		return (
			finding.review_status === 'needs_review' ||
			currentReviewQueueClaimIds.has(finding.claim_id) ||
			feedback.some((item) => item.review_status !== 'correct' || item.issue_type !== 'none')
		);
	}

	function findingDirectEvidenceCount(finding: ResearchUnderstandingPresentationFinding) {
		return uniquePresentationEvidenceForIds(finding.evidence_bundle.direct_result ?? []).length;
	}

	function findingRoleEvidenceCount(
		finding: ResearchUnderstandingPresentationFinding,
		role: FindingEvidenceRole
	) {
		return uniquePresentationEvidenceForIds(finding.evidence_bundle[role] ?? []).length;
	}

	function findingHasMechanismSupport(finding: ResearchUnderstandingPresentationFinding) {
		if (!finding.mediators.length) return false;
		return !finding.review_reasons.includes('missing_mechanism_evidence');
	}

	function findingEvidenceRoleSummary(finding: ResearchUnderstandingPresentationFinding) {
		return FINDING_MAIN_EVIDENCE_ROLES.map((role) => ({
			role,
			count:
				role === 'mechanism' && findingHasMechanismSupport(finding)
					? Math.max(1, findingRoleEvidenceCount(finding, role))
					: findingRoleEvidenceCount(finding, role),
			label: findingEvidenceRoleCoverageLabel(role)
		}));
	}

	function findingEvidenceGapNotes(finding: ResearchUnderstandingPresentationFinding) {
		const notes: string[] = [];
		if (findingRoleEvidenceCount(finding, 'direct_result') === 0) {
			notes.push($t('research.understanding.findingGapDirectResult'));
		}
		if (finding.mediators.length && !findingHasMechanismSupport(finding)) {
			notes.push($t('research.understanding.findingGapMechanism'));
		}
		if (!finding.scope_summary && findingRoleEvidenceCount(finding, 'condition_context') === 0) {
			notes.push($t('research.understanding.findingGapContext'));
		}
		if (finding.paper_count <= 1) {
			notes.push($t('research.understanding.findingGapCrossPaper'));
		}
		if (finding.support_grade === 'strong' && findingRoleEvidenceCount(finding, 'conflict') === 0) {
			notes.push($t('research.understanding.findingGapConflictCheck'));
		}
		if (!notes.length) notes.push($t('research.understanding.findingGapNone'));
		return notes;
	}

	function countUniqueFindingPapers(findings: ResearchUnderstandingPresentationFinding[]) {
		const documentIds = new Set<string>();
		let fallbackPaperCount = 0;
		for (const finding of findings) {
			for (const evidenceId of finding.evidence_ref_ids) {
				const documentId =
					presentationEvidenceById.get(evidenceId)?.document_id ||
					evidenceById.get(evidenceId)?.document_id ||
					'';
				if (documentId) documentIds.add(documentId);
			}
			if (!finding.evidence_ref_ids.length) {
				fallbackPaperCount += finding.paper_count;
			}
		}
		return documentIds.size || fallbackPaperCount;
	}

	function paperCoverageLabel(count: number) {
		const total = collectionDocumentCount;
		if (total > 0) {
			return $t('research.understanding.paperCoverage', {
				count,
				total
			});
		}
		return $t('research.understanding.paperCount', { count });
	}

	function primaryFindingCoverageLabel(count: number) {
		const total = collectionDocumentCount;
		if (total > 0) {
			return $t('research.understanding.primaryFindingPaperCoverage', {
				count,
				total
			});
		}
		return $t('research.understanding.paperCount', { count });
	}

	function findingPaperCoverageLabel(finding: ResearchUnderstandingPresentationFinding) {
		return paperCoverageLabel(finding.paper_count);
	}

	function findingEvidenceBasisLabel(finding: ResearchUnderstandingPresentationFinding) {
		if (finding.paper_count <= 1) return $t('research.understanding.singlePaperFinding');
		return $t('research.understanding.crossPaperFinding', { count: finding.paper_count });
	}

	function findingComparisonTitle(finding: ResearchUnderstandingPresentationFinding) {
		const summary = finding.comparison_summary;
		if (!summary) return '';
		return [summary.variable, summary.outcome].filter(Boolean).join(' -> ');
	}

	function findingComparisonValueLabel(finding: ResearchUnderstandingPresentationFinding) {
		const summary = finding.comparison_summary;
		if (!summary) return '';
		return [summary.baseline.value, summary.observed.value].filter(Boolean).join(' -> ');
	}

	function findingComparisonContextLabel(finding: ResearchUnderstandingPresentationFinding) {
		const summary = finding.comparison_summary;
		if (!summary?.controlled_conditions.length) return '';
		const conditions = summary.controlled_conditions
			.map((condition) => [condition.axis, condition.value].filter(Boolean).join(' '))
			.filter(Boolean)
			.join('; ');
		return conditions ? `Fixed: ${conditions}` : '';
	}

	function findingComparisonGroupLabel(finding: ResearchUnderstandingPresentationFinding) {
		const summary = finding.comparison_summary;
		if (!summary) return '';
		const baseline = [summary.baseline.label, summary.baseline.value].filter(Boolean).join(': ');
		const observed = [summary.observed.label, summary.observed.value].filter(Boolean).join(': ');
		return [baseline, observed].filter(Boolean).join(' vs ');
	}

	function findingScopeTableLabel(finding: ResearchUnderstandingPresentationFinding) {
		if (!finding.scope_summary) return $t('research.emptyValue');
		const terms = finding.scope_summary
			.split(',')
			.map((term) => term.trim())
			.filter(Boolean);
		if (terms.length <= 3) return finding.scope_summary;
		return `${terms.slice(0, 3).join(', ')} +${terms.length - 3} ${$t('research.understanding.moreScopeTerms')}`;
	}

	function findingSummaryId(finding: ResearchUnderstandingPresentationFinding) {
		return `${titleId}-finding-${finding.finding_id.replace(/[^A-Za-z0-9_-]/g, '-')}-summary`;
	}

	function findingDirectEvidenceLabel(finding: ResearchUnderstandingPresentationFinding) {
		return $t('research.understanding.directEvidenceCount', {
			count: findingDirectEvidenceCount(finding)
		});
	}

	function findingReviewReasonLabel(reason: string) {
		return translatedCatalogLabel('research.understanding.reviewReasons', reason);
	}

	function findingReviewReasonValues(finding: ResearchUnderstandingPresentationFinding) {
		const priority = [
			'confounded_table_row_comparison',
			'model_validation_finding',
			'missing_direct_result_evidence',
			'table_row_alignment_uncertain',
			'missing_mechanism_evidence',
			'conflicting_direction',
			'partial_support',
			'weak_support',
			'insufficient_support',
			'needs_cross_paper_confirmation',
			'single_paper_evidence',
			'needs_expert_review'
		];
		const trust = findingDatasetTrust(finding);
		const values = [...(finding.warnings ?? []), ...(finding.review_reasons ?? [])]
			.map((reason) => reason.trim())
			.filter((reason) => reason && findingReviewReasonIsVisible(finding, reason, trust));
		return [...new Set(values)].sort((left, right) => {
			const leftIndex = priority.indexOf(left);
			const rightIndex = priority.indexOf(right);
			return (
				(leftIndex < 0 ? priority.length : leftIndex) -
				(rightIndex < 0 ? priority.length : rightIndex)
			);
		});
	}

	function findingAuditNotes(finding: ResearchUnderstandingPresentationFinding) {
		const reviewReasons = findingReviewReasonValues(finding);
		const notes = [
			findingEvidenceBasisLabel(finding),
			findingPaperCoverageLabel(finding),
			findingDirectEvidenceLabel(finding),
			$t('research.understanding.evidenceCount', { count: finding.evidence_count })
		];
		if (reviewReasons.length) {
			notes.push(...reviewReasons.map(findingReviewReasonLabel));
		}
		if (finding.paper_count <= 1) notes.push($t('research.understanding.singlePaperLimitation'));
		if (findingDirectEvidenceCount(finding) === 0) {
			notes.push($t('research.understanding.noDirectResultEvidence'));
		}
		if (findingIsUnreviewedForDisplay(finding)) {
			notes.push($t('research.understanding.findingNeedsExpertReview'));
		}
		return [...new Set(notes)];
	}

	function findingUseBoundaryNotes(finding: ResearchUnderstandingPresentationFinding) {
		const notes = [];
		if (finding.generalization_note) notes.push(finding.generalization_note);
		const evidenceGapSummary = findingEvidenceGapSummaryForDisplay(finding);
		if (evidenceGapSummary) notes.push(evidenceGapSummary);
		notes.push(
			finding.paper_count <= 1
				? $t('research.understanding.useBoundaryPaperLevel')
				: $t('research.understanding.useBoundaryCrossPaper', { count: finding.paper_count })
		);
		if (finding.support_grade !== 'strong') {
			notes.push($t('research.understanding.useBoundaryNeedsConfirmation'));
		}
		if (findingIsUnreviewedForDisplay(finding)) {
			notes.push($t('research.understanding.useBoundaryBeforeModelUse'));
		}
		return [...new Set(notes)];
	}

	function findingEvidenceGapSummaryForDisplay(finding: ResearchUnderstandingPresentationFinding) {
		if (!finding.evidence_gap_summary || findingIsUnreviewedForDisplay(finding)) {
			return finding.evidence_gap_summary;
		}
		return finding.evidence_gap_summary
			.split(',')
			.map((item) => item.trim())
			.filter((item) => item && !/expert review/i.test(item))
			.join(', ');
	}

	function findingGeneralizationStatusLabel(finding: ResearchUnderstandingPresentationFinding) {
		return translatedCatalogLabel(
			'research.understanding.findingGeneralizationStatus',
			finding.generalization_status || 'cross_paper_candidate'
		);
	}

	function findingReviewReasonSummary(finding: ResearchUnderstandingPresentationFinding) {
		const reviewReasons = findingReviewReasonValues(finding);
		if (!reviewReasons.length) return '';
		return reviewReasons.slice(0, 2).map(findingReviewReasonLabel).join(' · ');
	}

	function findingDatasetSampleFor(
		finding: ResearchUnderstandingPresentationFinding
	): ResearchUnderstandingDatasetSample | null {
		return datasetSummary?.items.find((item) => item.finding_id === finding.finding_id) ?? null;
	}

	function datasetReviewActionLabel(sample: ResearchUnderstandingDatasetSample | null) {
		const label = sample?.review_action.label.trim() ?? '';
		if (label) return label;
		const code = sample?.review_action.code.trim() ?? '';
		if (!code) return '';
		return translatedCatalogLabel('research.objectives.goalReviewRecommendedActions', code);
	}

	function findingAcceptLabel(
		finding: ResearchUnderstandingPresentationFinding,
		andNext = false
	) {
		const actionCode = findingDatasetSampleFor(finding)?.review_action.code.trim() ?? '';
		const reviewReasons = new Set(findingReviewReasonValues(finding));
		const isPaperLevelAccept =
			actionCode === 'accept_as_paper_level' ||
			reviewReasons.has('single_paper_evidence') ||
			reviewReasons.has('needs_cross_paper_confirmation') ||
			finding.paper_count <= 1;
		if (isPaperLevelAccept) {
			return andNext
				? $t('research.understanding.quickAcceptPaperLevelAndNext')
				: $t('research.understanding.quickAcceptPaperLevel');
		}
		return andNext
			? $t('research.understanding.quickAcceptAndNext')
			: $t('research.understanding.quickAccept');
	}

	function findingReviewReasonActionLabel(
		finding: ResearchUnderstandingPresentationFinding,
		datasetSample: ResearchUnderstandingDatasetSample | null = findingDatasetSampleFor(finding)
	) {
		const datasetActionLabel = datasetReviewActionLabel(datasetSample);
		if (datasetActionLabel) return datasetActionLabel;
		const trust = findingDatasetTrust(finding);
		const reasons = new Set(findingReviewReasonValues(finding));
		if (trust.datasetUseStatus === 'training_ready') {
			return $t('research.understanding.findingReviewReasonActionReady');
		}
		if (reasons.has('table_row_alignment_uncertain')) {
			return $t('research.understanding.findingReviewReasonActionVerifyTableRows');
		}
		if (reasons.has('confounded_table_row_comparison')) {
			return $t('research.understanding.findingReviewReasonActionReviewTableVariables');
		}
		if (
			reasons.has('conflicting_direction') ||
			finding.support_grade === 'conflict' ||
			finding.evidence_bundle.conflict.length
		) {
			return $t('research.understanding.findingReviewReasonActionResolve');
		}
		if (reasons.has('missing_direct_result_evidence') || findingDirectEvidenceCount(finding) === 0) {
			return $t('research.understanding.findingReviewReasonActionRepair');
		}
		if (reasons.has('missing_mechanism_evidence')) {
			return $t('research.understanding.findingReviewReasonActionCheckMechanism');
		}
		if (reasons.has('model_validation_finding')) {
			return $t('research.understanding.findingReviewReasonActionValidateModel');
		}
		if (
			reasons.has('needs_cross_paper_confirmation') ||
			reasons.has('single_paper_evidence') ||
			finding.paper_count <= 1
		) {
			return $t('research.understanding.findingReviewReasonActionPaperLevel');
		}
		return $t('research.understanding.findingReviewReasonActionReview');
	}

	function relatedReviewFindings(
		finding: ResearchUnderstandingPresentationFinding,
		findings: ResearchUnderstandingPresentationFinding[]
	) {
		const byId = new Map(findings.map((item) => [item.finding_id, item]));
		return finding.related_review_finding_ids
			.map((findingId) => byId.get(findingId))
			.filter((item): item is ResearchUnderstandingPresentationFinding => Boolean(item));
	}

	function openRelatedReviewFinding(findingId: string) {
		reviewQueueOnly = true;
		openFindingDetail(findingId);
	}

	function findingFeedbackFor(
		finding: ResearchUnderstandingPresentationFinding,
		currentFeedbackByTargetId = feedbackByTargetId
	) {
		return [
			...(currentFeedbackByTargetId.get(finding.finding_id) ?? []),
			...(currentFeedbackByTargetId.get(finding.claim_id) ?? [])
		];
	}

	function findingCurationFor(
		finding: ResearchUnderstandingPresentationFinding,
		currentCurationsByTargetId = curationsByTargetId
	) {
		return (
			currentCurationsByTargetId.get(finding.finding_id) ??
			currentCurationsByTargetId.get(finding.claim_id) ??
			null
		);
	}

	function curatedListOrOriginal(
		curatedValues: string[] | undefined,
		originalValues: string[]
	) {
		const cleaned = [...new Set((curatedValues ?? []).map((value) => value.trim()).filter(Boolean))];
		return cleaned.length ? cleaned : originalValues;
	}

	function curatedTextOrOriginal(
		curatedValue: string | null | undefined,
		originalValue: string
	) {
		const cleaned = curatedValue?.trim() ?? '';
		return cleaned || originalValue;
	}

	function findingForDisplay(
		finding: ResearchUnderstandingPresentationFinding,
		curation: ResearchUnderstandingCuration | null = findingCurationFor(finding)
	): ResearchUnderstandingPresentationFinding {
		if (!curation) return finding;
		return {
			...finding,
			statement: curatedTextOrOriginal(curation.curated_statement, finding.statement),
			variables: curatedListOrOriginal(curation.curated_variables, finding.variables),
			mediators: curatedListOrOriginal(curation.curated_mediators, finding.mediators),
			outcomes: curatedListOrOriginal(curation.curated_outcomes, finding.outcomes),
			direction: curatedTextOrOriginal(curation.curated_direction, finding.direction),
			scope_summary: curatedTextOrOriginal(curation.curated_scope_summary, finding.scope_summary),
			support_grade: curatedTextOrOriginal(curation.curated_support_grade, finding.support_grade)
		};
	}

	function findingHasAcceptedReview(feedback: ResearchUnderstandingFeedback[]) {
		return feedback.some(
			(item) =>
				(item.review_status === 'correct' || item.review_status === 'partial') &&
				item.issue_type === 'none' &&
				isHumanReviewer(item.reviewer)
		);
	}

	function findingHasSilverReview(feedback: ResearchUnderstandingFeedback[]) {
		return feedback.some(
			(item) =>
				(item.review_status === 'correct' || item.review_status === 'partial') &&
				item.issue_type === 'none'
		);
	}

	function findingHasRejectingReview(feedback: ResearchUnderstandingFeedback[]) {
		return feedback.some(
			(item) => item.review_status === 'incorrect' || REJECTING_FEEDBACK_ISSUES.has(item.issue_type)
		);
	}

	function isAiReviewer(reviewer: string | null | undefined) {
		const normalized = reviewer?.trim().toLowerCase() ?? '';
		return normalized.startsWith('ai-reviewer') || normalized.startsWith('agent-');
	}

	function isHumanReviewer(reviewer: string | null | undefined) {
		const normalized = reviewer?.trim() ?? '';
		return Boolean(normalized) && !isAiReviewer(normalized);
	}

	function findingDatasetTrust(
		finding: ResearchUnderstandingPresentationFinding,
		currentFeedbackByTargetId = feedbackByTargetId,
		currentCurationsByTargetId = curationsByTargetId
	): FindingDatasetTrust {
		const curation = findingCurationFor(finding, currentCurationsByTargetId);
		const feedback = findingFeedbackFor(finding, currentFeedbackByTargetId);
		const hasRejected = findingHasRejectingReview(feedback);
		if (curation && isHumanReviewer(curation.reviewer)) {
			return {
				labelStatus: 'gold',
				datasetUseStatus: 'training_ready',
				source: 'human_curation'
			};
		}
		if (curation) {
			return {
				labelStatus: 'silver',
				datasetUseStatus: 'review_candidate',
				source: isAiReviewer(curation.reviewer) ? 'ai_curation' : 'candidate'
			};
		}
		if (hasRejected) {
			return {
				labelStatus: 'rejected',
				datasetUseStatus: 'rejected',
				source: 'rejected'
			};
		}
		if (
			feedback.some(
				(item) =>
					item.review_status === 'correct' &&
					item.issue_type === 'none' &&
					isHumanReviewer(item.reviewer)
			)
		) {
			return {
				labelStatus: 'gold',
				datasetUseStatus: 'training_ready',
				source: 'human_feedback'
			};
		}
		if (
			feedback.some(
				(item) =>
					(item.review_status === 'correct' || item.review_status === 'partial') &&
					item.issue_type === 'none'
			)
		) {
			return {
				labelStatus: 'silver',
				datasetUseStatus: 'review_candidate',
				source: 'ai_feedback'
			};
		}
		return {
			labelStatus: 'candidate',
			datasetUseStatus:
				finding.dataset_use_status === 'rejected' ? 'rejected' : 'review_candidate',
			source: 'candidate'
		};
	}

	function findingDatasetTrustSubtitle(trust: FindingDatasetTrust) {
		return [
			datasetUseStatusLabel(trust.datasetUseStatus),
			findingTrustSourceLabel(trust.source)
		].join(' · ');
	}

	function findingUsagePathForDisplay(finding: ResearchUnderstandingPresentationFinding) {
		return findingUsagePath(finding, findingFeedbackFor(finding), findingCurationFor(finding));
	}

	function findingUsagePreview(finding: ResearchUnderstandingPresentationFinding) {
		const usagePath = findingUsagePathForDisplay(finding);
		return {
			...usagePath,
			nextAction: datasetReviewActionLabel(findingDatasetSampleFor(finding)) || usagePath.checklist[0] || ''
		};
	}

	function findingUsagePath(
		finding: ResearchUnderstandingPresentationFinding,
		feedback: ResearchUnderstandingFeedback[] = [],
		curation: ResearchUnderstandingCuration | null = null
	) {
		const directEvidenceCount = findingDirectEvidenceCount(finding);
		const hasDirectEvidence = directEvidenceCount > 0;
		const hasSinglePaperEvidence = finding.paper_count <= 1;
		const hasAcceptedReview =
			findingHasAcceptedReview(feedback) || Boolean(curation && isHumanReviewer(curation.reviewer));
		const hasSilverReview = findingHasSilverReview(feedback) || Boolean(curation);
		const hasRejectingReview = findingHasRejectingReview(feedback);
		const hasConflict =
			finding.support_grade === 'conflict' || Boolean(finding.evidence_bundle.conflict?.length);
		const needsReview =
			findingIsUnreviewedForDisplay(finding) || finding.support_grade !== 'strong' || hasRejectingReview;
		const status = findingUsageStatus(finding, {
			hasDirectEvidence,
			hasSinglePaperEvidence,
			hasAcceptedReview,
			hasRejectingReview
		});
		const checklist = findingUpgradeChecklist(finding, {
			directEvidenceCount,
			hasAcceptedReview,
			needsReview,
			hasConflict
		});
		return {
			status,
			title: $t(`research.understanding.findingUsageStatus.${status}`),
			body: $t(`research.understanding.findingUsageBody.${status}`),
			datasetNote: $t(
				hasAcceptedReview
					? 'research.understanding.findingUsageDatasetReady'
					: hasSilverReview
						? 'research.understanding.findingUsageDatasetSilver'
					: 'research.understanding.findingUsageDatasetReview'
			),
			checklist
		};
	}

	function findingUsageStatus(
		finding: ResearchUnderstandingPresentationFinding,
		flags: {
			hasDirectEvidence: boolean;
			hasSinglePaperEvidence: boolean;
			hasAcceptedReview: boolean;
			hasRejectingReview: boolean;
		}
	) {
		const mapped = findingUsageStatusFromBackend(finding.expert_use_status);
		if (mapped) return mapped;
		if (!flags.hasDirectEvidence) return 'repair';
		if (flags.hasSinglePaperEvidence) return 'paper';
		if (findingIsExpertReady(finding) || (flags.hasAcceptedReview && !flags.hasRejectingReview)) {
			return 'ready';
		}
		return 'review';
	}

	function findingUsageStatusFromBackend(status: string) {
		if (status === 'scoped_expert_finding') return 'ready';
		if (status === 'paper_level_finding') return 'paper';
		if (status === 'evidence_repair_needed') return 'repair';
		if (status === 'review_candidate') return 'review';
		return '';
	}

	function findingUpgradeChecklist(
		finding: ResearchUnderstandingPresentationFinding,
		flags: {
			directEvidenceCount: number;
			hasAcceptedReview: boolean;
			needsReview: boolean;
			hasConflict: boolean;
		}
	) {
		const backendActions = Array.isArray(finding.upgrade_actions) ? finding.upgrade_actions : [];
		const actions = backendActions.length
			? backendActions
			: inferredFindingUpgradeActions(finding, flags.hasConflict, flags.needsReview);
		const checklist = actions
			.filter((action) => action !== 'record_expert_review' || !flags.hasAcceptedReview)
			.map((action) => findingUpgradeActionLabel(action, flags.directEvidenceCount))
			.filter(Boolean);
		if (
			flags.needsReview &&
			!flags.hasAcceptedReview &&
			!actions.includes('record_expert_review')
		) {
			checklist.push($t('research.understanding.findingUsageRecordReview'));
		}
		return checklist.length ? checklist : [$t('research.understanding.findingUsageKeepScope')];
	}

	function inferredFindingUpgradeActions(
		finding: ResearchUnderstandingPresentationFinding,
		hasConflict: boolean,
		needsReview: boolean
	) {
		const actions: string[] = [];
		if (findingDirectEvidenceCount(finding)) actions.push('verify_direct_evidence');
		else actions.push('repair_direct_evidence');
		if (finding.paper_count <= 1) actions.push('add_cross_paper_evidence');
		if (finding.support_grade !== 'strong') actions.push('curate_support_grade');
		if (hasConflict) actions.push('resolve_conflict');
		if (needsReview) actions.push('record_expert_review');
		if (!actions.length) actions.push('keep_scope_conditions');
		return actions;
	}

	function findingUpgradeActionLabel(action: string, directEvidenceCount: number) {
		if (action === 'verify_direct_evidence') {
			return $t('research.understanding.findingUsageVerifyEvidence', {
				count: directEvidenceCount
			});
		}
		if (action === 'repair_direct_evidence') {
			return $t('research.understanding.findingUsageRepairEvidence');
		}
		if (action === 'add_cross_paper_evidence') {
			return $t('research.understanding.findingUsageAddPaper');
		}
		if (action === 'curate_support_grade') {
			return $t('research.understanding.findingUsageResolveSupport');
		}
		if (action === 'resolve_conflict') {
			return $t('research.understanding.findingUsageResolveConflict');
		}
		if (action === 'record_expert_review') {
			return $t('research.understanding.findingUsageRecordReview');
		}
		if (action === 'keep_scope_conditions') {
			return $t('research.understanding.findingUsageKeepScope');
		}
		return '';
	}

	function selectedFindingEvidenceGroups() {
		if (!selectedFinding) return [];
		const usedEvidenceTargets = new Set<string>();
		return FINDING_MAIN_EVIDENCE_ROLES
			.map((role) => {
				const items = presentationEvidenceForIds(selectedFinding.evidence_bundle[role] ?? []).filter(
					(item) => {
						const key = evidenceStableTargetKey(item);
						if (usedEvidenceTargets.has(key)) return false;
						usedEvidenceTargets.add(key);
						return true;
					}
				);
				return { role, items };
			})
			.filter((group) => group.items.length);
	}

	function selectedSecondaryFindingEvidenceCount() {
		if (!selectedFinding) return 0;
		const usedMainEvidenceTargets = new Set(
			uniquePresentationEvidenceForIds(
				FINDING_MAIN_EVIDENCE_ROLES.flatMap((role) => selectedFinding.evidence_bundle[role] ?? [])
			).map(evidenceStableTargetKey)
		);
		return uniquePresentationEvidenceForIds(
			FINDING_SECONDARY_EVIDENCE_ROLES.flatMap((role) => selectedFinding.evidence_bundle[role] ?? [])
		).filter((item) => !usedMainEvidenceTargets.has(evidenceStableTargetKey(item))).length;
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
		selectedFindingId = '';
		selectedEffectId = effectId;
		detailMode = true;
	}

	function openFindingDetail(findingId: string) {
		selectedEffectId = '';
		selectedFindingId = findingId;
		detailMode = true;
	}

	async function openFindingFeedback(findingId: string) {
		openFindingDetail(findingId);
		await tick();
		activeReviewPanel = 'feedback';
	}

	async function openFindingReject(findingId: string) {
		openFindingDetail(findingId);
		await tick();
		rejectSelectedFinding();
	}

	async function openFindingCorrection(findingId: string) {
		openFindingDetail(findingId);
		await tick();
		correctSelectedFinding();
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

	async function acceptSelectedFinding() {
		if (!selectedFinding) return;
		activeReviewPanel = 'feedback';
		await acceptFinding(selectedFinding);
	}

	async function acceptSelectedFindingAndOpenNext() {
		if (!selectedFinding) return;
		activeReviewPanel = 'feedback';
		await acceptFinding(selectedFinding, { openNext: true });
	}

	async function acceptFinding(
		finding: ResearchUnderstandingPresentationFinding,
		options: { openNext?: boolean } = {}
	) {
		if (!understanding || !collectionId || !selectedScopeId || !reviewerReady) return;
		feedbackSubmitting = true;
		feedbackMessage = '';
		feedbackError = '';
		try {
			const feedback = await createResearchUnderstandingFeedback(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId,
				finding_id: finding.finding_id,
				claim_id: finding.claim_id,
				review_status: 'correct',
				issue_type: 'none',
				note: null
			});
			const targetId = reviewTargetKey(feedback);
			const nextFeedbackByTargetId = new Map(feedbackByTargetId).set(targetId, [
				feedback,
				...(feedbackByTargetId.get(targetId) ?? [])
			]);
			feedbackByTargetId = nextFeedbackByTargetId;
			if (options.openNext) {
				const nextFinding = nextReviewCandidateAfter(finding.finding_id, nextFeedbackByTargetId);
				if (nextFinding) {
					openFindingDetail(nextFinding.finding_id);
				}
			}
			const refreshed = await refreshDatasetSummaryForCurrentScope();
			feedbackMessage = reviewSaveMessage(
				'feedback',
				formatShortIdentifier(feedback.feedback_id),
				refreshed
			);
		} catch (error) {
			feedbackError = error instanceof Error ? error.message : $t('error.unexpected');
		} finally {
			feedbackSubmitting = false;
		}
	}

	function nextReviewCandidateAfter(
		currentFindingId: string,
		currentFeedbackByTargetId: Map<string, ResearchUnderstandingFeedback[]> = feedbackByTargetId,
		currentCurationsByTargetId: Map<string, ResearchUnderstandingCuration> = curationsByTargetId
	) {
		const candidates = allDisplayFindingRows.filter(
			(finding) =>
				finding.finding_id !== currentFindingId &&
				findingDatasetTrust(finding, currentFeedbackByTargetId, currentCurationsByTargetId).datasetUseStatus ===
					'review_candidate'
		);
		return candidates[0] ?? null;
	}

	function rejectSelectedFinding() {
		feedbackStatus = 'incorrect';
		feedbackIssue = 'wrong_variable';
		feedbackNote = '';
		activeReviewPanel = 'feedback';
	}

	function correctSelectedFinding() {
		resetCurationForm();
		activeReviewPanel = 'curation';
	}

	function currentReviewerLabel(user: { email?: string | null; display_name?: string | null } | null) {
		return user?.email?.trim() || user?.display_name?.trim() || '';
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

	function evidenceQuote(ref: ResearchUnderstandingPresentationEvidence) {
		return ref.quote || ref.source_text || '';
	}

	function evidenceHrefWithQuote(href: string, ref: ResearchUnderstandingPresentationEvidence) {
		const quote = evidenceQuote(ref);
		if (!href || !quote) return href;
		const [path, query = ''] = href.split('?');
		const params = new URLSearchParams(query);
		if (!params.get('quote')) {
			params.set('quote', quote);
		}
		const encoded = params.toString();
		return encoded ? `${path}?${encoded}` : path;
	}

	function evidenceHref(ref: ResearchUnderstandingPresentationEvidence) {
		const rawRef = evidenceById.get(ref.evidence_ref_id);
		if (ref.href) return evidenceHrefWithQuote(ref.href, ref);
		if (rawRef?.href) return evidenceHrefWithQuote(rawRef.href, ref);
		if (!collectionId || !ref.document_id) return '';
		const params: [string, string][] = [];
		const pageValue = ref.page || displayValue(rawRef?.locator.page);
		const sourceRef = ref.source_ref || displayValue(rawRef?.locator.source_ref);
		const anchorId = rawRef?.anchor_ids[0] ?? '';
		params.push(['view', 'parsed-paper']);
		if (pageValue) params.push(['page', pageValue]);
		if (sourceRef) params.push(['source_ref', sourceRef]);
		if (ref.evidence_ref_id) params.push(['evidence_id', ref.evidence_ref_id]);
		if (anchorId) params.push(['anchor_id', anchorId]);
		if (evidenceQuote(ref)) params.push(['quote', evidenceQuote(ref)]);
		if (returnTo) params.push(['return_to', returnTo]);
		return `${resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: ref.document_id
		})}${queryString(params)}`;
	}

	function evidenceStableTargetKey(ref: ResearchUnderstandingPresentationEvidence) {
		const rawRef = evidenceById.get(ref.evidence_ref_id);
		const sourceRef = ref.source_ref || displayValue(rawRef?.locator.source_ref);
		const page = ref.page || displayValue(rawRef?.locator.page);
		if (ref.document_id && sourceRef) {
			return [ref.document_id, sourceRef, page].join('|');
		}
		const href = evidenceHref(ref);
		if (href) {
			const url = new URL(href, 'http://localhost');
			url.searchParams.delete('quote');
			url.searchParams.delete('evidence_id');
			return url.pathname + url.search;
		}
		return ref.evidence_ref_id;
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

	function evidenceSourceBlock(ref: ResearchUnderstandingPresentationEvidence) {
		return ref.source_text || '';
	}

	function hasDistinctEvidenceSourceBlock(ref: ResearchUnderstandingPresentationEvidence) {
		const quote = evidenceQuote(ref).replace(/\s+/g, ' ').trim();
		const sourceBlock = evidenceSourceBlock(ref).replace(/\s+/g, ' ').trim();
		return Boolean(sourceBlock && sourceBlock !== quote);
	}

	function tableAuditColumns(ref: ResearchUnderstandingPresentationEvidence) {
		return ref.table_audit?.columns.join(' | ') ?? '';
	}

	function tableAuditRows(ref: ResearchUnderstandingPresentationEvidence) {
		return ref.table_audit?.relevant_rows ?? [];
	}

	function tableAuditHasUnalignedRows(ref: ResearchUnderstandingPresentationEvidence) {
		return tableAuditRows(ref).some((row) => !row.aligned);
	}

	function tableAuditRowText(ref: ResearchUnderstandingPresentationEvidence, row: { cells: string[]; aligned?: boolean }) {
		const columns = ref.table_audit?.columns ?? [];
		if (!columns.length) return row.cells.join(' | ');
		if (row.aligned === false || columns.length !== row.cells.length) {
			return $t('research.understanding.unalignedTableRow', {
				cells: row.cells.join(' | ')
			});
		}
		return row.cells
			.map((cell, index) => (columns[index] ? `${columns[index]}: ${cell}` : cell))
			.join('; ');
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

	function countFindingsByDatasetUse(currentFindings: ResearchUnderstandingPresentationFinding[]) {
		const counts = new Map<FindingDatasetUseFilter, number>([['all', currentFindings.length]]);
		for (const finding of currentFindings) {
			const status = findingDatasetTrust(finding).datasetUseStatus;
			counts.set(status, (counts.get(status) ?? 0) + 1);
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

	function uniquePresentationEvidenceForIds(ids: string[]) {
		const seen = new Set<string>();
		const items: ResearchUnderstandingPresentationEvidence[] = [];
		for (const item of presentationEvidenceForIds(ids)) {
			const key = evidenceStableTargetKey(item);
			if (seen.has(key)) continue;
			seen.add(key);
			items.push(item);
		}
		return items;
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
		const normalized = cleanFindingContextText(value);
		if (!normalized || isNoisyFindingContextText(normalized)) return '';
		return compactText(normalized, limit);
	}

	function cleanFindingContextText(value: string) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (!normalized) return '';
		const fragments = normalized
			.split(/[,;]/)
			.map((fragment) => fragment.trim())
			.filter(Boolean);
		if (fragments.length <= 1) {
			return isGenericFindingContextFragment(normalized) ? '' : normalized;
		}
		return fragments
			.filter((fragment) => !isGenericFindingContextFragment(fragment))
			.join(', ');
	}

	function isGenericFindingContextFragment(value: string) {
		const normalized = normalizedFindingContextToken(value);
		return FINDING_CONTEXT_GENERIC_FRAGMENTS.some(
			(fragment) => normalized === normalizedFindingContextToken(fragment)
		);
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

	function findingContextAxisTerms(finding: ResearchUnderstandingPresentationFinding) {
		return [
			...finding.variables,
			...finding.mediators,
			...finding.outcomes,
			finding.scope_summary
		]
			.map(normalizedFindingContextToken)
			.filter(Boolean);
	}

	function contextValueMatchesFinding(value: string, finding: ResearchUnderstandingPresentationFinding) {
		const normalized = normalizedFindingContextToken(value);
		if (!normalized) return false;
		return findingContextAxisTerms(finding).some(
			(term) =>
				term &&
				(normalized.includes(term) || term.includes(normalized))
		);
	}

	function contextDescriptionMatchesFinding(
		context: ResearchUnderstandingPresentationContext,
		finding: ResearchUnderstandingPresentationFinding
	) {
		return [
			context.process_summary,
			context.test_summary,
			...context.limitations
		].some((value) => contextValueMatchesFinding(value, finding));
	}

	function contextHasOffAxisTerms(
		context: ResearchUnderstandingPresentationContext,
		finding: ResearchUnderstandingPresentationFinding
	) {
		const text = normalizedFindingContextToken(
			[
				context.process_summary,
				context.test_summary,
				...context.property_scope,
				...context.limitations
			].join(' ')
		);
		if (!text) return false;
		const axisTerms = findingContextAxisTerms(finding);
		return FINDING_CONTEXT_AXIS_TERMS.some((term) => {
			const normalizedTerm = normalizedFindingContextToken(term);
			if (!normalizedTerm || !text.includes(normalizedTerm)) return false;
			return !axisTerms.some(
				(axisTerm) =>
					axisTerm &&
					(axisTerm.includes(normalizedTerm) || normalizedTerm.includes(axisTerm))
			);
		});
	}

	function contextMatchesFinding(
		context: ResearchUnderstandingPresentationContext,
		finding: ResearchUnderstandingPresentationFinding
	) {
		if (!isGenericFindingContextLabel(context.label)) return true;
		if (!context.property_scope.length) return true;
		if (contextHasOffAxisTerms(context, finding)) return false;
		if (contextDescriptionMatchesFinding(context, finding)) return true;
		if (context.process_summary || context.test_summary || context.limitations.length) return false;
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

	function datasetFilters() {
		if (!understanding || !selectedScopeId) return null;
		return {
			scope_type: understanding.scope.scope_type,
			scope_id: selectedScopeId
		};
	}

	function datasetDownloadUrl(
		format: ResearchUnderstandingDatasetExportFormat,
		datasetUseStatus: ResearchUnderstandingDatasetUseStatus
	) {
		const filters = datasetFilters();
		if (!collectionId || !filters) return '';
		return researchUnderstandingDatasetUrl(
			collectionId,
			{ ...filters, dataset_use_status: datasetUseStatus },
			format
		);
	}

	function collectionDatasetDownloadUrl(
		format: ResearchUnderstandingDatasetExportFormat,
		datasetUseStatus: ResearchUnderstandingDatasetUseStatus
	) {
		if (!collectionId || understanding?.scope.scope_type !== 'goal') return '';
		return researchUnderstandingCollectionDatasetUrl(
			collectionId,
			{
				scope_type: 'goal',
				dataset_use_status: datasetUseStatus
			},
			format
		);
	}

	function findingIsExpertReady(finding: ResearchUnderstandingPresentationFinding) {
		return (
			finding.support_grade === 'strong' &&
			finding.review_status !== 'needs_review' &&
			finding.review_status !== 'pending_review' &&
			finding.paper_count > 1 &&
			findingDirectEvidenceCount(finding) > 0
		);
	}

	function findingIsReviewCandidate(finding: ResearchUnderstandingPresentationFinding) {
		return finding.expert_use_status === 'review_candidate';
	}

	function expertReadinessSummary(
		findings: ResearchUnderstandingPresentationFinding[],
		reviewQueueCandidates: number,
		trainingReady: number,
		reviewCandidateSamples: number
	) {
		const total = findings.length;
		const strong = findings.filter((finding) => finding.support_grade === 'strong').length;
		const partial = findings.filter((finding) => finding.support_grade === 'partial').length;
		const weakOrConflict = findings.filter((finding) =>
			['weak', 'conflict', 'insufficient'].includes(finding.support_grade)
		).length;
		const singlePaper = findings.filter((finding) => finding.paper_count <= 1).length;
		const missingDirect = findings.filter((finding) => findingDirectEvidenceCount(finding) === 0).length;
		const paperLevelFindings = findings.filter(
			(finding) => finding.expert_use_status === 'paper_level_finding'
		).length;
		const readyFindings = findings.filter(findingIsExpertReady).length;
		const status =
			total === 0 && reviewQueueCandidates > 0
				? 'review'
				: total === 0
					? 'empty'
				: readyFindings === total
					? 'ready'
					: trainingReady > 0
						? 'mixed'
						: 'review';
		return {
			status,
			total,
			strong,
			partial,
			weakOrConflict,
			singlePaper,
			missingDirect,
			paperLevelFindings,
			reviewCandidates: reviewQueueCandidates,
			readyFindings,
			trainingReady,
			reviewCandidateSamples
		};
	}

	function expertSummaryTitle(summary: ReturnType<typeof expertReadinessSummary>) {
		if (summary.status === 'ready') return $t('research.understanding.expertSummaryReady');
		if (summary.status === 'mixed') return $t('research.understanding.expertSummaryMixed');
		if (summary.paperLevelFindings > 0) {
			return $t('research.understanding.expertSummaryPaperLevel');
		}
		if (summary.status === 'review') return $t('research.understanding.expertSummaryReviewOnly');
		return $t('research.understanding.expertSummaryEmpty');
	}

	function headingStatusLabel(
		currentUnderstanding: ResearchUnderstanding,
		summary: ReturnType<typeof expertReadinessSummary> | null
	) {
		if (summary) return expertSummaryTitle(summary);
		return stateLabel(currentUnderstanding.state);
	}

	function expertSummaryBody(summary: ReturnType<typeof expertReadinessSummary>) {
		if (summary.status === 'ready') {
			return $t('research.understanding.expertSummaryReadyBody', {
				count: summary.readyFindings
			});
		}
		if (summary.trainingReady > 0) {
			return $t('research.understanding.expertSummaryMixedBody', {
				training: summary.trainingReady,
				review: summary.reviewCandidateSamples
			});
		}
		if (summary.paperLevelFindings > 0) {
			return $t('research.understanding.expertSummaryPaperLevelBody', {
				count: summary.paperLevelFindings
			});
		}
		return $t('research.understanding.expertSummaryReviewOnlyBody', {
			count: summary.reviewCandidates
		});
	}

	function expertSummaryGaps(summary: ReturnType<typeof expertReadinessSummary>) {
		const gaps: string[] = [];
		if (summary.singlePaper) {
			gaps.push($t('research.understanding.expertGapSinglePaper', { count: summary.singlePaper }));
		}
		if (summary.partial) {
			gaps.push($t('research.understanding.expertGapPartial', { count: summary.partial }));
		}
		if (summary.weakOrConflict) {
			gaps.push($t('research.understanding.expertGapWeakOrConflict', { count: summary.weakOrConflict }));
		}
		if (summary.missingDirect) {
			gaps.push($t('research.understanding.expertGapMissingDirect', { count: summary.missingDirect }));
		}
		if (summary.reviewCandidates) {
			gaps.push(
				$t('research.understanding.expertGapReviewQueue', {
					count: summary.reviewCandidates
				})
			);
		}
		if (!gaps.length) gaps.push($t('research.understanding.expertGapNone'));
		return gaps;
	}

	function reviewLoopStatusValue(
		summary: ReturnType<typeof expertReadinessSummary>,
		isDatasetLoading: boolean,
		hasDatasetSummary: boolean,
		hasReviewer: boolean,
		trainingReady: number,
		trainingMessages: number,
		protocolReady: number,
		reviewCandidates: number
	) {
		if (isDatasetLoading) return 'loading';
		if (!summary.total && !summary.reviewCandidates) return 'empty';
		if (!hasDatasetSummary) return 'dataset_unavailable';
		if (!hasReviewer) return 'needs_reviewer';
		if (reviewCandidates > 0 && trainingReady === 0) return 'needs_review';
		if (reviewCandidates > 0) return 'continue_review';
		if (protocolReady > 0) return 'export_ready';
		if (trainingMessages > 0) return 'protocol_inputs_pending';
		if (trainingReady > 0) return 'messages_pending';
		return 'needs_review';
	}

	function reviewLoopTitle(status: string) {
		return translatedCatalogLabel('research.understanding.reviewLoopStatuses', status);
	}

	function reviewLoopBody(
		status: string,
		trainingReady: number,
		trainingMessages: number,
		protocolReady: number,
		reviewCandidates: number
	) {
		return $t(`research.understanding.reviewLoopBodies.${status}`, {
			training: trainingReady,
			messages: trainingMessages,
			protocol: protocolReady,
			review: reviewCandidates
		});
	}

	function reviewLoopStepItems(
		summary: ReturnType<typeof expertReadinessSummary>,
		hasReviewer: boolean,
		trainingReady: number,
		trainingMessages: number,
		protocolReady: number,
		reviewCandidates: number
	) {
		const steps: string[] = [];
		if (!hasReviewer) {
			steps.push($t('research.understanding.reviewLoopStepLogin'));
		}
		if (summary.missingDirect) {
			steps.push(
				$t('research.understanding.reviewLoopStepEvidence', {
					count: summary.missingDirect
				})
			);
		}
		if (reviewCandidates) {
			steps.push(
				$t('research.understanding.reviewLoopStepReview', {
					count: reviewCandidates
				})
			);
		}
		if (trainingReady && trainingMessages < trainingReady) {
			steps.push(
				$t('research.understanding.reviewLoopStepMessages', {
					training: trainingReady,
					messages: trainingMessages
				})
			);
		}
		if (trainingMessages && protocolReady === 0) {
			steps.push(
				$t('research.understanding.reviewLoopStepProtocolInputs', {
					messages: trainingMessages,
					protocol: protocolReady
				})
			);
		}
		if (protocolReady) {
			steps.push(
				$t('research.understanding.reviewLoopStepExport', {
					count: protocolReady
				})
			);
		}
		if (!steps.length) steps.push($t('research.understanding.reviewLoopStepDone'));
		return steps;
	}

	function reviewLoopChecklistItems(
		hasReviewer: boolean,
		hasDatasetSummary: boolean,
		trainingReady: number,
		trainingMessages: number,
		protocolReady: number,
		reviewCandidates: number,
		findingCount: number,
		missingDirectEvidenceCount: number
	) {
		const hasReadableFindings = findingCount > 0;
		const hasEvidence = missingDirectEvidenceCount === 0 && findingCount > 0;
		const reviewComplete = hasDatasetSummary && reviewCandidates === 0 && trainingReady > 0;
		const messagesReady = trainingMessages > 0 && trainingMessages >= trainingReady;
		const protocolInputsReady = protocolReady > 0;
		return [
			{
				key: 'findings',
				status: hasReadableFindings ? 'done' : 'blocked',
				label: $t('research.understanding.reviewLoopChecklistFindings'),
				detail: hasReadableFindings
					? $t('research.understanding.reviewLoopChecklistFindingsDone', {
							count: findingCount
						})
					: $t('research.understanding.reviewLoopChecklistFindingsBlocked')
			},
			{
				key: 'evidence',
				status: hasEvidence ? 'done' : 'blocked',
				label: $t('research.understanding.reviewLoopChecklistEvidence'),
				detail: hasEvidence
					? $t('research.understanding.reviewLoopChecklistEvidenceDone')
					: $t('research.understanding.reviewLoopChecklistEvidenceBlocked', {
							count: missingDirectEvidenceCount
						})
			},
			{
				key: 'review',
				status: reviewComplete ? 'done' : hasReviewer && hasDatasetSummary ? 'active' : 'blocked',
				label: $t('research.understanding.reviewLoopChecklistReview'),
				detail: reviewComplete
					? $t('research.understanding.reviewLoopChecklistReviewDone', {
							count: trainingReady
						})
					: $t('research.understanding.reviewLoopChecklistReviewBlocked', {
							count: reviewCandidates
						})
			},
			{
				key: 'training',
				status: messagesReady ? 'done' : trainingReady > 0 ? 'active' : 'blocked',
				label: $t('research.understanding.reviewLoopChecklistTraining'),
				detail: messagesReady
					? $t('research.understanding.reviewLoopChecklistTrainingDone', {
							count: trainingMessages
						})
					: $t('research.understanding.reviewLoopChecklistTrainingBlocked', {
							training: trainingReady,
							messages: trainingMessages
						})
			},
			{
				key: 'protocol',
				status: protocolInputsReady ? 'done' : 'blocked',
				label: $t('research.understanding.reviewLoopChecklistProtocol'),
				detail: protocolInputsReady
					? $t('research.understanding.reviewLoopChecklistProtocolDone', {
							count: protocolReady
						})
					: $t('research.understanding.reviewLoopChecklistProtocolBlocked', {
							protocol: protocolReady
						})
			}
		];
	}

	function showReviewQueue() {
		datasetReviewCandidatesOnly = true;
		reviewQueueOnly = false;
		selectedClaimStatus = 'all';
		selectedDatasetUseStatus = 'review_candidate';
		closeClaimDetail();
	}

	function applyInitialFocus(focus: typeof initialFocus) {
		if (focus === 'review_queue') {
			showReviewQueue();
		} else if (focus === 'training_ready') {
			showTrainingReady();
			openDatasetExport();
		}
	}

	async function applyInitialFindingFocus(findingId: string) {
		const finding = allDisplayFindingRows.find((item) => item.finding_id === findingId);
		if (!finding) return;
		selectedClaimStatus = 'all';
		selectedDatasetUseStatus = findingDatasetTrust(finding).datasetUseStatus;
		datasetReviewCandidatesOnly = true;
		reviewQueueOnly = false;
		await tick();
		selectedEffectId = '';
		selectedFindingId = finding.finding_id;
		detailMode = true;
	}

	function showTrainingReady() {
		datasetReviewCandidatesOnly = true;
		reviewQueueOnly = false;
		selectedClaimStatus = 'all';
		selectedDatasetUseStatus = 'training_ready';
		closeClaimDetail();
	}

	function showAllFindings() {
		datasetReviewCandidatesOnly = false;
		reviewQueueOnly = false;
		selectedClaimStatus = 'all';
		selectedDatasetUseStatus = 'all';
		closeClaimDetail();
	}

	function openDatasetExport() {
		datasetPanelOpen = true;
		if (currentCollectionDatasetScopeKey && currentCollectionDatasetScopeKey !== collectionDatasetScopeKey) {
			void loadCollectionDatasetSummary(currentCollectionDatasetScopeKey);
		}
	}

	function axisCoverageStatusLabel(status: ResearchUnderstandingAxisCoverageItem['status']) {
		if (status === 'primary') return $t('research.understanding.axisCoveragePrimary');
		if (status === 'review_queue') return $t('research.understanding.axisCoverageReviewQueue');
		if (status === 'mechanism') return $t('research.understanding.axisCoverageMechanism');
		if (status === 'context') return $t('research.understanding.axisCoverageContext');
		return $t('research.understanding.axisCoverageMissing');
	}

	function axisCoverageStatusClass(status: ResearchUnderstandingAxisCoverageItem['status']) {
		if (status === 'primary') return 'research-understanding-workbench__axis-status--primary';
		if (status === 'review_queue') {
			return 'research-understanding-workbench__axis-status--review';
		}
		if (status === 'mechanism') {
			return 'research-understanding-workbench__axis-status--mechanism';
		}
		if (status === 'context') {
			return 'research-understanding-workbench__axis-status--context';
		}
		return 'research-understanding-workbench__axis-status--missing';
	}

	function axisCoverageStatusCount(
		items: ResearchUnderstandingAxisCoverageItem[],
		status: ResearchUnderstandingAxisCoverageItem['status']
	) {
		return items.filter((item) => item.status === status).length;
	}

	function axisCoverageTerms(
		items: ResearchUnderstandingAxisCoverageItem[],
		statuses: ResearchUnderstandingAxisCoverageItem['status'][]
	) {
		const statusSet = new Set(statuses);
		return items.filter((item) => statusSet.has(item.status)).map((item) => item.axis);
	}

	function buildAxisCoverageGapGroups(currentAxisCoverage: typeof axisCoverage) {
		const items = [
			...currentAxisCoverage.variables.map((item) => ({ ...item, group: 'variables' as const })),
			...currentAxisCoverage.properties.map((item) => ({ ...item, group: 'properties' as const }))
		];
		const missing = axisCoverageTerms(items, ['missing']);
		const review = axisCoverageTerms(items, ['review_queue']);
		const contextOnly = axisCoverageTerms(items, ['context', 'mechanism']);
		return [
			{
				key: 'missing',
				label: $t('research.understanding.coverageMissing'),
				terms: missing
			},
			{
				key: 'review',
				label: $t('research.understanding.coverageReviewCandidates'),
				terms: review
			},
			{
				key: 'context',
				label: $t('research.understanding.coverageContextOnly'),
				terms: contextOnly
			}
		].filter((group) => group.terms.length);
	}

	function findingBoundaryLabel(finding: ResearchUnderstandingPresentationFinding) {
		const variables = finding.variables.map((value) => value.trim()).filter(Boolean);
		const outcomes = finding.outcomes.map((value) => value.trim()).filter(Boolean);
		if (variables.length && outcomes.length) return `${variables.join(', ')} -> ${outcomes.join(', ')}`;
		return finding.title || finding.statement || finding.finding_id;
	}

	function buildAnswerBoundary(
		currentAxisCoverage: typeof axisCoverage,
		currentPrimaryFindings: ResearchUnderstandingPresentationFinding[],
		_currentFeedbackByTargetId: Map<string, ResearchUnderstandingFeedback[]>,
		_currentCurationsByTargetId: Map<string, ResearchUnderstandingCuration>
	) {
		const variableTotal = currentAxisCoverage.variables.length;
		const propertyTotal = currentAxisCoverage.properties.length;
		const variablePrimary = axisCoverageStatusCount(currentAxisCoverage.variables, 'primary');
		const propertyPrimary = axisCoverageStatusCount(currentAxisCoverage.properties, 'primary');
		const primaryFindingById = new Map(
			currentPrimaryFindings.map((finding) => [finding.finding_id, finding])
		);
		const primaryCoverageItems = [
			...currentAxisCoverage.variables,
			...currentAxisCoverage.properties
		].filter((item) => item.status === 'primary' && item.finding_id);
		const coveredPrimaryFindingIds = [
			...new Set(primaryCoverageItems.map((item) => item.finding_id).filter(Boolean))
		];
		const draftFindingLabels: string[] = [];
		for (const findingId of coveredPrimaryFindingIds) {
			const finding = primaryFindingById.get(findingId);
			const trust = finding
				? findingDatasetTrust(finding, _currentFeedbackByTargetId, _currentCurationsByTargetId)
				: null;
			if (
				finding &&
				trust?.datasetUseStatus !== 'training_ready' &&
				!findingIsExpertReady(finding)
			) {
				draftFindingLabels.push(findingBoundaryLabel(finding));
			}
		}
		const blockedTerms = axisCoverageTerms(
			[...currentAxisCoverage.variables, ...currentAxisCoverage.properties],
			['missing', 'review_queue']
		);
		const contextTerms = axisCoverageTerms(
			[...currentAxisCoverage.variables, ...currentAxisCoverage.properties],
			['context', 'mechanism']
		);
		return {
			variablePrimary,
			variableTotal,
			propertyPrimary,
			propertyTotal,
			draftFindingLabels,
			blockedTerms,
			contextTerms,
			status:
				blockedTerms.length === 0 && variableTotal > 0 && propertyTotal > 0
					? draftFindingLabels.length === 0
						? 'expert_ready'
						: 'draft'
					: 'limited'
		};
	}

	function openAxisCoverageFinding(item: ResearchUnderstandingAxisCoverageItem) {
		if (!item.finding_id) return;
		openFindingDetail(item.finding_id);
	}

	function findingDecision(finding: ResearchUnderstandingPresentationFinding) {
		if (findingIsExpertReady(finding)) {
			return {
				title: $t('research.understanding.findingDecisionReady'),
				body: $t('research.understanding.findingDecisionReadyBody')
			};
		}
		if (findingDirectEvidenceCount(finding) === 0) {
			return {
				title: $t('research.understanding.findingDecisionDoNotUse'),
				body: $t('research.understanding.findingDecisionMissingDirectBody')
			};
		}
		if (finding.paper_count <= 1) {
			return {
				title: $t('research.understanding.findingDecisionPaperLevel'),
				body: $t('research.understanding.findingDecisionSinglePaperBody')
			};
		}
		return {
			title: $t('research.understanding.findingDecisionNeedsReview'),
			body: $t('research.understanding.findingDecisionNeedsReviewBody')
		};
	}

	function resetCurationForm() {
		const curation = selectedCuration;
		curationClaimType = curation?.curated_claim_type ?? selectedClaim?.claim_type ?? 'finding';
		curationStatus = curation?.curated_status ?? selectedClaim?.status ?? 'supported';
		curationSupportGrade = curation?.curated_support_grade ?? selectedFinding?.support_grade ?? 'partial';
		curationStatement =
			curation?.curated_statement ?? selectedFinding?.statement ?? selectedClaim?.statement ?? '';
		curationVariables = listEditorValue(curation?.curated_variables ?? selectedFinding?.variables ?? []);
		curationMediators = listEditorValue(curation?.curated_mediators ?? selectedFinding?.mediators ?? []);
		curationOutcomes = listEditorValue(curation?.curated_outcomes ?? selectedFinding?.outcomes ?? []);
		curationDirection = curation?.curated_direction ?? selectedFinding?.direction ?? '';
		curationScopeSummary = curation?.curated_scope_summary ?? selectedFinding?.scope_summary ?? '';
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
	}

	function listEditorValue(values: string[]) {
		return values.map((value) => value.trim()).filter(Boolean).join(', ');
	}

	function listEditorItems(value: string) {
		return [
			...new Set(
				value
					.split(',')
					.map((item) => item.trim())
					.filter(Boolean)
			)
		];
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

	async function loadDatasetSummary(scopeKey: string, force = false) {
		const filters = datasetFilters();
		if (!understanding || !collectionId || !filters) return null;
		if (force) {
			datasetScopeKey = '';
		}
		datasetScopeKey = scopeKey;
		const requestSequence = ++datasetRequestSequence;
		datasetLoading = true;
		datasetError = '';
		try {
			const nextDatasetSummary = await fetchResearchUnderstandingDataset(collectionId, filters);
			if (requestSequence === datasetRequestSequence) {
				datasetSummary = nextDatasetSummary;
			}
			return nextDatasetSummary;
		} catch (error) {
			if (requestSequence === datasetRequestSequence) {
				datasetSummary = null;
				datasetError = isHttpStatusError(error, 404)
					? ''
					: error instanceof Error
						? error.message
						: $t('error.unexpected');
			}
			return null;
		} finally {
			if (requestSequence === datasetRequestSequence) {
				datasetLoading = false;
			}
		}
	}

	async function loadCollectionDatasetSummary(scopeKey: string, force = false) {
		if (!collectionId || understanding?.scope.scope_type !== 'goal') return;
		if (force) {
			collectionDatasetScopeKey = '';
		}
		collectionDatasetScopeKey = scopeKey;
		const requestSequence = ++collectionDatasetRequestSequence;
		collectionDatasetLoading = true;
		collectionDatasetError = '';
		try {
			const nextDatasetSummary = await fetchResearchUnderstandingCollectionDataset(collectionId, {
				scope_type: 'goal'
			});
			if (requestSequence === collectionDatasetRequestSequence) {
				collectionDatasetSummary = nextDatasetSummary;
			}
		} catch (error) {
			if (requestSequence === collectionDatasetRequestSequence) {
				collectionDatasetSummary = null;
				collectionDatasetError = isHttpStatusError(error, 404)
					? ''
					: error instanceof Error
						? error.message
						: $t('error.unexpected');
			}
		} finally {
			if (requestSequence === collectionDatasetRequestSequence) {
				collectionDatasetLoading = false;
			}
		}
	}

	async function refreshDatasetSummaryForCurrentScope() {
		if (!currentDatasetScopeKey) return null;
		const refreshed = await loadDatasetSummary(currentDatasetScopeKey, true);
		if (datasetPanelOpen && currentCollectionDatasetScopeKey) {
			await loadCollectionDatasetSummary(currentCollectionDatasetScopeKey, true);
		}
		return refreshed;
	}

	function reviewSaveMessage(kind: 'feedback' | 'curation', id: string, dataset: ResearchUnderstandingDataset | null) {
		const fallbackKey =
			kind === 'feedback'
				? 'research.understanding.feedbackSaved'
				: 'research.understanding.curationSaved';
		const saved = $t(fallbackKey, { id });
		if (!dataset) {
			return saved;
		}
		return `${saved}. ${$t('research.understanding.reviewSaveDatasetStatus', {
			id,
			training: dataset.quality_summary.training_ready_sample_count,
			messages: dataset.quality_summary.training_message_sample_count,
			protocol: dataset.quality_summary.protocol_ready_sample_count,
			review: dataset.quality_summary.review_candidate_sample_count
		})}`;
	}

	function handleDatasetToggle(event: Event) {
		const details = event.currentTarget as HTMLDetailsElement | null;
		datasetPanelOpen = details?.open ?? false;
		if (
			datasetPanelOpen &&
			currentCollectionDatasetScopeKey &&
			currentCollectionDatasetScopeKey !== collectionDatasetScopeKey
		) {
			void loadCollectionDatasetSummary(currentCollectionDatasetScopeKey);
		}
	}

	async function submitClaimFeedback(options: { openNext?: boolean } = {}) {
		if (!understanding || !selectedReviewTargetId || !collectionId || !selectedScopeId) return;
		if (!reviewerReady) return;
		const currentFindingId = selectedFinding?.finding_id ?? '';
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
				note: feedbackNote.trim() || null
			});
			const targetId = reviewTargetKey(feedback);
			const nextFeedbackByTargetId = new Map(feedbackByTargetId).set(targetId, [
				feedback,
				...(feedbackByTargetId.get(targetId) ?? [])
			]);
			feedbackByTargetId = nextFeedbackByTargetId;
			feedbackNote = '';
			if (options.openNext && currentFindingId) {
				const nextFinding = nextReviewCandidateAfter(currentFindingId, nextFeedbackByTargetId);
				if (nextFinding) {
					openFindingDetail(nextFinding.finding_id);
				}
			}
			const refreshed = await refreshDatasetSummaryForCurrentScope();
			feedbackMessage = reviewSaveMessage(
				'feedback',
				formatShortIdentifier(feedback.feedback_id),
				refreshed
			);
		} catch (error) {
			feedbackError = error instanceof Error ? error.message : $t('error.unexpected');
		} finally {
			feedbackSubmitting = false;
		}
	}

	async function submitClaimCuration(options: { openNext?: boolean } = {}) {
		if (!understanding || !selectedReviewTargetId || !collectionId || !selectedScopeId) return;
		if (!curationStatement.trim() || !reviewerReady) return;
		const currentFindingId = selectedFinding?.finding_id ?? '';
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
				curated_support_grade: curationSupportGrade || null,
				curated_review_status: 'accepted',
				curated_variables: listEditorItems(curationVariables),
				curated_mediators: listEditorItems(curationMediators),
				curated_outcomes: listEditorItems(curationOutcomes),
				curated_direction: curationDirection.trim() || null,
				curated_scope_summary: curationScopeSummary.trim() || null,
				curated_evidence_ref_ids: curationEvidenceRefIds,
				curated_context_ids: curationContextIds,
				note: curationNote.trim() || null
			});
			const nextCurationsByTargetId = new Map(curationsByTargetId).set(
				reviewTargetKey(curation),
				curation
			);
			curationsByTargetId = nextCurationsByTargetId;
			if (options.openNext && currentFindingId) {
				const nextFinding = nextReviewCandidateAfter(
					currentFindingId,
					feedbackByTargetId,
					nextCurationsByTargetId
				);
				if (nextFinding) {
					openFindingDetail(nextFinding.finding_id);
				}
			}
			const refreshed = await refreshDatasetSummaryForCurrentScope();
			curationMessage = reviewSaveMessage(
				'curation',
				formatShortIdentifier(curation.curation_id),
				refreshed
			);
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
			<span>{headingStatusLabel(understanding, expertSummary)}</span>
		{/if}
	</div>

	{#if understanding}
		{#if usesFindings}
			<div
				class="research-understanding-workbench__summary"
				aria-label={$t('research.understanding.summary')}
			>
				<div>
					<strong>{primaryFindingCount}</strong>
					<span>{$t('research.understanding.primaryFindings')}</span>
				</div>
				<div>
					<strong>{primaryFindingPaperCount}</strong>
					<span>{primaryFindingPaperCoverage}</span>
				</div>
				<div>
					<strong>{primaryFindingDirectEvidenceCount}</strong>
					<span>{$t('research.understanding.directEvidence')}</span>
				</div>
				<div>
					<strong>{expertReviewCandidateCount}</strong>
					<span>{$t('research.understanding.candidateQueue')}</span>
				</div>
			</div>
			{#if expertSummary}
				<section
					class="research-understanding-workbench__expert-summary"
					aria-label={$t('research.understanding.expertSummary')}
				>
					<div>
						<strong>{expertSummaryTitle(expertSummary)}</strong>
						<p>{expertSummaryBody(expertSummary)}</p>
					</div>
					<div class="research-understanding-workbench__expert-metrics">
						<span>
							{$t('research.understanding.expertMetricStrong')}
							<strong>{expertSummary.strong}</strong>
						</span>
						<span>
							{$t('research.understanding.expertMetricPartial')}
							<strong>{expertSummary.partial}</strong>
						</span>
						<span>
							{$t('research.understanding.expertMetricSinglePaper')}
							<strong>{expertSummary.singlePaper}</strong>
						</span>
						<span>
							{$t('research.understanding.expertMetricTrainingReady')}
							<strong>{expertSummary.trainingReady}</strong>
						</span>
					</div>
					<ul>
						{#each expertSummaryGaps(expertSummary) as gap}
							<li>{gap}</li>
						{/each}
					</ul>
				</section>
				<section
					class={`research-understanding-workbench__review-loop research-understanding-workbench__review-loop--${reviewLoopStatus}`}
					aria-label={$t('research.understanding.reviewLoop')}
				>
					<div>
						<span>{$t('research.understanding.reviewLoop')}</span>
						<strong>{reviewLoopTitle(reviewLoopStatus)}</strong>
						<p>
							{reviewLoopBody(
								reviewLoopStatus,
								datasetTrainingReadySampleCount,
								datasetTrainingMessageSampleCount,
								datasetProtocolReadySampleCount,
								datasetReviewCandidateSampleCount
							)}
						</p>
					</div>
					<div class="research-understanding-workbench__review-loop-metrics">
						<span>
							{$t('research.understanding.datasetTrainingReady')}
							<strong>{datasetTrainingReadySampleCount}</strong>
						</span>
						<span>
							{$t('research.understanding.datasetTrainingMessages')}
							<strong>{datasetTrainingMessageSampleCount}</strong>
						</span>
						<span>
							{$t('research.understanding.datasetProtocolReady')}
							<strong>{datasetProtocolReadySampleCount}</strong>
						</span>
						<span>
							{$t('research.understanding.datasetReviewCandidate')}
							<strong>{datasetReviewCandidateSampleCount}</strong>
						</span>
					</div>
					<div class="research-understanding-workbench__review-loop-actions">
						<button
							type="button"
							disabled={datasetReviewCandidateSampleCount === 0}
							on:click={showReviewQueue}
						>
							{$t('research.understanding.reviewLoopOpenQueue')}
						</button>
						<button
							type="button"
							disabled={!nextReviewCandidateFinding}
							on:click={() =>
								nextReviewCandidateFinding &&
								openFindingDetail(nextReviewCandidateFinding.finding_id)}
						>
							{$t('research.understanding.reviewLoopOpenNextFinding')}
						</button>
						<button
							type="button"
							disabled={datasetTrainingReadySampleCount === 0}
							on:click={showTrainingReady}
						>
							{$t('research.understanding.reviewLoopOpenTraining')}
						</button>
						<button type="button" on:click={showAllFindings}>
							{$t('research.understanding.reviewLoopOpenAll')}
						</button>
						<button type="button" on:click={openDatasetExport}>
							{$t('research.understanding.reviewLoopOpenDataset')}
						</button>
						{#if goalCopilotHref}
							{#if datasetProtocolReadySampleCount > 0}
								<a class="research-understanding-workbench__review-loop-link" href={goalCopilotHref}>
									{$t('research.understanding.reviewLoopDraftProtocol')}
								</a>
							{:else}
								<span class="research-understanding-workbench__review-loop-link research-understanding-workbench__review-loop-link--disabled">
									{$t(
										datasetTrainingMessageSampleCount > 0
											? 'research.understanding.reviewLoopDraftProtocolInputsBlocked'
										: datasetTrainingReadySampleCount > 0
											? 'research.understanding.reviewLoopDraftProtocolMessagesBlocked'
											: 'research.understanding.reviewLoopDraftProtocolBlocked'
									)}
								</span>
							{/if}
						{/if}
					</div>
					{#if datasetSummary && nextReviewCandidateFinding && !reviewQueueOnly && !datasetReviewCandidatesOnly}
						{@const nextDisplayFinding = findingForDisplay(nextReviewCandidateFinding)}
						{@const nextUsagePreview = findingUsagePreview(nextDisplayFinding)}
						<div
							class="research-understanding-workbench__review-loop-next"
							aria-label={$t('research.understanding.reviewLoopNextCandidate')}
						>
							<div>
								<span>{$t('research.understanding.reviewLoopNextCandidate')}</span>
								<strong>{nextDisplayFinding.statement || nextDisplayFinding.title}</strong>
								<p>{findingReviewReasonActionLabel(nextDisplayFinding, nextReviewCandidateSample)}</p>
							</div>
							<div class="research-understanding-workbench__review-loop-next-fields">
								<span>
									{$t('research.understanding.variablesColumn')}
									<strong>{findingListLabel(nextDisplayFinding.variables)}</strong>
								</span>
								<span>
									{$t('research.understanding.resultColumn')}
									<strong>
										{[
											nextDisplayFinding.direction
												? relationLabel(nextDisplayFinding.direction)
												: '',
											findingListLabel(nextDisplayFinding.outcomes)
										]
											.filter(Boolean)
											.join(' · ')}
									</strong>
								</span>
								<span>
									{$t('research.understanding.evidenceGradeColumn')}
									<strong>{supportGradeLabel(nextDisplayFinding.support_grade)}</strong>
								</span>
								<span>
									{$t('research.understanding.evidenceBasisColumn')}
									<strong>{nextUsagePreview.title}</strong>
								</span>
							</div>
							<div class="research-understanding-workbench__review-loop-next-reasons">
								<span>
									{$t('research.understanding.reviewLoopNextReasonCount', {
										count: findingReviewReasonValues(nextDisplayFinding).length
									})}
								</span>
							</div>
							<div class="research-understanding-workbench__review-loop-next-actions">
								<button
									type="button"
									on:click={() => openFindingDetail(nextReviewCandidateFinding.finding_id)}
								>
									{$t('research.understanding.openFindingDetail')}
								</button>
							</div>
						</div>
					{/if}
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
					<div
						class="research-understanding-workbench__review-loop-checklist"
						aria-label={$t('research.understanding.reviewLoopChecklist')}
					>
						{#each reviewLoopChecklist as item (item.key)}
							<div
								class={`research-understanding-workbench__review-loop-check research-understanding-workbench__review-loop-check--${item.status}`}
							>
								<span>{item.label}</span>
								<strong>{translatedCatalogLabel('research.understanding.reviewLoopChecklistStatuses', item.status)}</strong>
								<p>{item.detail}</p>
							</div>
						{/each}
					</div>
					<ul>
						{#each reviewLoopSteps as step}
							<li>{step}</li>
						{/each}
					</ul>
					{#if reviewLoopErrorItems.length}
						<div class="research-understanding-workbench__review-loop-errors">
							<strong>{$t('research.understanding.datasetErrorCategoriesTitle')}</strong>
							<div>
								{#each reviewLoopErrorItems as [category, count] (category)}
									<span>
										{datasetErrorCategoryLabel(category)}
										<strong>{count}</strong>
									</span>
								{/each}
							</div>
						</div>
					{/if}
				</section>
			{/if}
			{#if hasAxisCoverage}
				<section
					class="research-understanding-workbench__axis-coverage"
					aria-label={$t('research.understanding.goalCoverage')}
				>
					<div class="research-understanding-workbench__axis-coverage-heading">
						<div>
							<h4>{$t('research.understanding.goalCoverage')}</h4>
							<p>{$t('research.understanding.goalCoverageBody')}</p>
						</div>
					</div>
					{#if answerBoundary}
						<div
							class="research-understanding-workbench__answer-boundary"
							aria-label={$t('research.understanding.answerBoundary')}
						>
							<div>
								<strong>
									{answerBoundary.status === 'expert_ready'
										? $t('research.understanding.answerBoundaryExpertReady')
										: answerBoundary.status === 'draft'
											? $t('research.understanding.answerBoundaryDraft')
											: $t('research.understanding.answerBoundaryLimited')}
								</strong>
								<p>
									{$t('research.understanding.answerBoundaryBody', {
										variablePrimary: answerBoundary.variablePrimary,
										variableTotal: answerBoundary.variableTotal,
										propertyPrimary: answerBoundary.propertyPrimary,
										propertyTotal: answerBoundary.propertyTotal
									})}
								</p>
							</div>
							{#if answerBoundary.draftFindingLabels.length}
								<span>
									{$t('research.understanding.answerBoundaryDraftCuration', {
										findings: listLabel(answerBoundary.draftFindingLabels)
									})}
								</span>
							{/if}
							{#if answerBoundary.blockedTerms.length}
								<span>
									{$t('research.understanding.answerBoundaryBlocked', {
										terms: listLabel(answerBoundary.blockedTerms)
									})}
								</span>
							{/if}
							{#if answerBoundary.contextTerms.length}
								<span>
									{$t('research.understanding.answerBoundaryContextOnly', {
										terms: listLabel(answerBoundary.contextTerms)
									})}
								</span>
							{/if}
						</div>
					{/if}
					{#if axisCoverageGapGroups.length}
						<div
							class="research-understanding-workbench__coverage-gaps"
							aria-label={$t('research.understanding.coverageGaps')}
						>
							<div>
								<strong>{$t('research.understanding.coverageGaps')}</strong>
								<p>{$t('research.understanding.coverageGapsBody')}</p>
							</div>
							<ul>
								{#each axisCoverageGapGroups as group (group.key)}
									<li>
										<strong>{group.label}</strong>
										<span>{listLabel(group.terms)}</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
					<div class="research-understanding-workbench__axis-coverage-grid">
						{#if axisCoverage.variables.length}
							<div class="research-understanding-workbench__axis-group">
								<div class="research-understanding-workbench__axis-group-heading">
									<strong>{$t('research.understanding.goalCoverageVariables')}</strong>
									<span>
										{$t('research.understanding.axisCoverageSummary', {
											primary: axisCoverageStatusCount(axisCoverage.variables, 'primary'),
											review: axisCoverageStatusCount(axisCoverage.variables, 'review_queue'),
											mechanism: axisCoverageStatusCount(axisCoverage.variables, 'mechanism'),
											context: axisCoverageStatusCount(axisCoverage.variables, 'context'),
											missing: axisCoverageStatusCount(axisCoverage.variables, 'missing')
										})}
									</span>
								</div>
								<ul>
									{#each axisCoverage.variables as item (`variable-${item.axis}`)}
										<li>
											{#if item.finding_id}
												<button type="button" on:click={() => openAxisCoverageFinding(item)}>
													<span>{item.axis}</span>
													<small class={axisCoverageStatusClass(item.status)}>
														{axisCoverageStatusLabel(item.status)}
													</small>
												</button>
											{:else}
												<span>
													<span>{item.axis}</span>
													<small class={axisCoverageStatusClass(item.status)}>
														{axisCoverageStatusLabel(item.status)}
													</small>
												</span>
											{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
						{#if axisCoverage.properties.length}
							<div class="research-understanding-workbench__axis-group">
								<div class="research-understanding-workbench__axis-group-heading">
									<strong>{$t('research.understanding.goalCoverageProperties')}</strong>
									<span>
										{$t('research.understanding.axisCoverageSummary', {
											primary: axisCoverageStatusCount(axisCoverage.properties, 'primary'),
											review: axisCoverageStatusCount(axisCoverage.properties, 'review_queue'),
											mechanism: axisCoverageStatusCount(axisCoverage.properties, 'mechanism'),
											context: axisCoverageStatusCount(axisCoverage.properties, 'context'),
											missing: axisCoverageStatusCount(axisCoverage.properties, 'missing')
										})}
									</span>
								</div>
								<ul>
									{#each axisCoverage.properties as item (`property-${item.axis}`)}
										<li>
											{#if item.finding_id}
												<button type="button" on:click={() => openAxisCoverageFinding(item)}>
													<span>{item.axis}</span>
													<small class={axisCoverageStatusClass(item.status)}>
														{axisCoverageStatusLabel(item.status)}
													</small>
												</button>
											{:else}
												<span>
													<span>{item.axis}</span>
													<small class={axisCoverageStatusClass(item.status)}>
														{axisCoverageStatusLabel(item.status)}
													</small>
												</span>
											{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					</div>
				</section>
			{/if}
		{/if}

		{#if usesFindings || effectRows.length || understanding.claims.length || understanding.evidence_refs.length}
			{#if usesFindings}
				<div
					class="research-understanding-workbench__filters"
					aria-label={$t('research.understanding.claimFilters')}
				>
					<div class="research-understanding-workbench__filter-group">
						<span>{$t('research.understanding.filterByEvidenceGrade')}</span>
						<div class="research-understanding-workbench__segmented" role="list">
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
						</div>
					</div>
					<div class="research-understanding-workbench__filter-group">
						<span>{$t('research.understanding.reviewQueue')}</span>
						<div class="research-understanding-workbench__segmented" role="list">
							<button
								type="button"
								class:research-understanding-workbench__segment--active={reviewQueueOnly}
								aria-pressed={reviewQueueOnly}
								on:click={() => {
									datasetReviewCandidatesOnly = false;
									reviewQueueOnly = !reviewQueueOnly;
								}}
							>
								{$t('research.understanding.reviewQueueCount', {
									count: reviewQueueCount
								})}
							</button>
						</div>
					</div>
					<div class="research-understanding-workbench__filter-group">
						<span>{$t('research.understanding.filterByDatasetUse')}</span>
						<div class="research-understanding-workbench__segmented" role="list">
							{#each DATASET_USE_STATUS_FILTER_ORDER as status (status)}
								{@const count = findingDatasetUseCounts.get(status) ?? 0}
								{#if count || status === 'all'}
									<button
										type="button"
										class:research-understanding-workbench__segment--active={selectedDatasetUseStatus ===
											status}
										aria-pressed={selectedDatasetUseStatus === status}
										on:click={() => {
											datasetReviewCandidatesOnly = false;
											selectedDatasetUseStatus = status;
										}}
									>
										{optionLabel(datasetUseStatusFilterLabel(status), count)}
									</button>
								{/if}
							{/each}
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
				{#if currentDatasetScopeKey}
					<details
						class="research-understanding-workbench__dataset"
						aria-busy={datasetLoading || collectionDatasetLoading}
						bind:open={datasetPanelOpen}
						on:toggle={handleDatasetToggle}
					>
						<summary>
							<span>{$t('research.understanding.datasetSummary')}</span>
							<small>
								{#if datasetLoading}
									{$t('research.understanding.datasetLoading')}
								{:else if datasetSummary}
									{$t('research.understanding.datasetReady', {
										count: datasetSummary.item_count
									})}
								{:else}
									{$t('research.understanding.datasetUnavailable')}
								{/if}
							</small>
						</summary>
						{#if datasetSummary}
							<div class="research-understanding-workbench__dataset-body">
								<div class="research-understanding-workbench__dataset-counts">
									<span>
										{$t('research.understanding.datasetTrainingReady')}
										<strong>{datasetTrainingReadySampleCount}</strong>
									</span>
									<span>
										{$t('research.understanding.datasetTrainingMessages')}
										<strong>{datasetTrainingMessageSampleCount}</strong>
									</span>
									<span>
										{$t('research.understanding.datasetProtocolReady')}
										<strong>{datasetProtocolReadySampleCount}</strong>
									</span>
									<span>
										{$t('research.understanding.datasetReviewCandidate')}
										<strong>{datasetReviewCandidateSampleCount}</strong>
									</span>
									{#each DATASET_LABEL_STATUS_ORDER as status (status)}
										<span>
											{datasetLabelStatusLabel(status)}
											<strong>{datasetLabelCounts[status]}</strong>
										</span>
									{/each}
								</div>
								<p class="research-understanding-workbench__dataset-note">
									{$t('research.understanding.datasetLabelBoundaryNote')}
								</p>
								<div class="research-understanding-workbench__dataset-actions">
									{#if datasetTrainingReadySampleCount > 0}
										<a href={datasetDownloadUrl('json', 'training_ready')} download>
											{$t('research.understanding.datasetDownloadTrainingJson')}
										</a>
										<a href={datasetDownloadUrl('jsonl', 'training_ready')} download>
											{$t('research.understanding.datasetDownloadTrainingJsonl')}
										</a>
										<a href={datasetDownloadUrl('messages_jsonl', 'training_ready')} download>
											{$t('research.understanding.datasetDownloadTrainingMessagesJsonl')}
										</a>
										{#if understanding.scope.scope_type === 'goal'}
											<a href={collectionDatasetDownloadUrl('json', 'training_ready')} download>
												{$t('research.understanding.datasetDownloadCollectionTrainingJson')}
											</a>
											<a href={collectionDatasetDownloadUrl('jsonl', 'training_ready')} download>
												{$t('research.understanding.datasetDownloadCollectionTrainingJsonl')}
											</a>
											<a href={collectionDatasetDownloadUrl('messages_jsonl', 'training_ready')} download>
												{$t(
													'research.understanding.datasetDownloadCollectionTrainingMessagesJsonl'
												)}
											</a>
										{/if}
									{:else}
										<span
											class="research-understanding-workbench__dataset-action-disabled"
											aria-disabled="true"
										>
											{$t('research.understanding.datasetNoTrainingReady')}
										</span>
									{/if}
									{#if datasetReviewCandidateSampleCount > 0}
										<a href={datasetDownloadUrl('json', 'review_candidate')} download>
											{$t('research.understanding.datasetDownloadReviewJson')}
										</a>
									{/if}
									{#if understanding.scope.scope_type === 'goal'}
										<a href={collectionDatasetDownloadUrl('json', 'review_candidate')} download>
											{$t('research.understanding.datasetDownloadCollectionReviewJson')}
										</a>
									{/if}
								</div>
								{#if datasetTrainingReadySampleCount > 0}
									<p class="research-understanding-workbench__dataset-note">
										{$t('research.understanding.datasetTrainingMessagesNote')}
									</p>
								{/if}
								{#if understanding.scope.scope_type === 'goal'}
									<div class="research-understanding-workbench__dataset-collection">
										<strong>{$t('research.understanding.collectionDatasetSummary')}</strong>
										{#if collectionDatasetLoading}
											<p>{$t('research.understanding.datasetLoading')}</p>
										{:else if collectionDatasetSummary}
											<p>
												{$t('research.understanding.collectionDatasetReady', {
													training: collectionDatasetTrainingReadySampleCount,
													messages: collectionDatasetTrainingMessageSampleCount,
													protocol: collectionDatasetProtocolReadySampleCount,
													review: collectionDatasetReviewCandidateSampleCount
												})}
											</p>
											<div>
												<span>
													{$t('research.understanding.datasetTrainingReady')}
													<strong>{collectionDatasetTrainingReadySampleCount}</strong>
												</span>
												<span>
													{$t('research.understanding.datasetTrainingMessages')}
													<strong>{collectionDatasetTrainingMessageSampleCount}</strong>
												</span>
												<span>
													{$t('research.understanding.datasetProtocolReady')}
													<strong>{collectionDatasetProtocolReadySampleCount}</strong>
												</span>
												<span>
													{$t('research.understanding.datasetReviewCandidate')}
													<strong>{collectionDatasetReviewCandidateSampleCount}</strong>
												</span>
												{#each DATASET_LABEL_STATUS_ORDER as status (status)}
													<span>
														{datasetLabelStatusLabel(status)}
														<strong>{collectionDatasetLabelCounts[status]}</strong>
													</span>
												{/each}
												{#each collectionDatasetErrorCategories as [category, count] (category)}
													<span>
														{datasetErrorCategoryLabel(category)}
														<strong>{count}</strong>
													</span>
												{/each}
												{#each collectionDatasetBucketCounts as [bucket, count] (bucket)}
													<span>
														{datasetPresentationBucketLabel(bucket)}
														<strong>{count}</strong>
													</span>
												{/each}
												{#each collectionDatasetReviewReasons as [reason, count] (reason)}
													<span>
														{datasetReviewReasonLabel(reason)}
														<strong>{count}</strong>
													</span>
												{/each}
												{#each collectionDatasetSystemWarnings as [warning, count] (warning)}
													<span>
														{datasetSystemWarningLabel(warning)}
														<strong>{count}</strong>
													</span>
												{/each}
											</div>
										{:else if collectionDatasetError}
											<p
												class="research-understanding-workbench__feedback-state research-understanding-workbench__feedback-state--error"
												role="alert"
											>
												{$t('research.understanding.datasetError', {
													message: collectionDatasetError
												})}
											</p>
										{:else}
											<p>{$t('research.understanding.datasetUnavailable')}</p>
										{/if}
									</div>
								{/if}
								{#if datasetErrorCategories.length}
									<div class="research-understanding-workbench__dataset-errors">
										<strong>{$t('research.understanding.datasetErrorCategoriesTitle')}</strong>
										<div>
											{#each datasetErrorCategories as [category, count] (category)}
												<span>
													{datasetErrorCategoryLabel(category)}
													<strong>{count}</strong>
												</span>
											{/each}
										</div>
									</div>
								{/if}
								{#if datasetReviewReasons.length}
									<div class="research-understanding-workbench__dataset-errors">
										<strong>{$t('research.understanding.datasetReviewReasonsTitle')}</strong>
										<div>
											{#each datasetReviewReasons as [reason, count] (reason)}
												<span>
													{datasetReviewReasonLabel(reason)}
													<strong>{count}</strong>
												</span>
											{/each}
										</div>
									</div>
								{/if}
								{#if datasetSystemWarnings.length}
									<div class="research-understanding-workbench__dataset-errors">
										<strong>{$t('research.understanding.datasetSystemWarningsTitle')}</strong>
										<div>
											{#each datasetSystemWarnings as [warning, count] (warning)}
												<span>
													{datasetSystemWarningLabel(warning)}
													<strong>{count}</strong>
												</span>
											{/each}
										</div>
									</div>
								{/if}
							</div>
						{/if}
						{#if datasetError}
							<p
								class="research-understanding-workbench__feedback-state research-understanding-workbench__feedback-state--error"
								role="alert"
							>
								{$t('research.understanding.datasetError', { message: datasetError })}
							</p>
						{/if}
					</details>
				{/if}
			{/if}

			{#if !detailMode}
				<section
					class="research-understanding-workbench__column research-understanding-workbench__column--list"
					aria-label={$t('research.understanding.findingsWorkspace')}
				>
					<div class="research-understanding-workbench__column-heading">
						<h4>{$t('research.understanding.findingsWorkspace')}</h4>
						{#if usesFindings}
							<span>
								{$t('research.understanding.filteredClaimCount', {
									shown: visibleFindingRows.length,
									total: findingRows.length
								})}
							</span>
						{/if}
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
											<th scope="col">{$t('research.understanding.evidenceBasisColumn')}</th>
											<th scope="col">{$t('research.understanding.datasetTrustColumn')}</th>
											<th scope="col">{$t('research.understanding.actionsColumn')}</th>
										</tr>
									</thead>
										<tbody>
											{#each visibleFindingRows as finding (finding.finding_id)}
												{@const curation = findingCurationFor(finding)}
												{@const displayFinding = findingForDisplay(finding, curation)}
												{@const findingFeedback = findingFeedbackFor(finding)}
												{@const usagePreview = findingUsagePreview(displayFinding)}
												{@const trust = findingDatasetTrust(finding)}
												<tr>
													<td class="research-understanding-workbench__finding-main">
														<button
															type="button"
															on:click={() => openFindingDetail(finding.finding_id)}
														>
															<strong id={findingSummaryId(displayFinding)}>
																{displayFinding.statement || displayFinding.title}
															</strong>
															{#if displayFinding.title && displayFinding.title !== displayFinding.statement}
																<span>{displayFinding.title}</span>
															{/if}
																{#if curation || findingFeedback.length}
																	<span>
																		{[
																			curation ? findingTrustSourceLabel(trust.source) : '',
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
													<td>{findingListLabel(displayFinding.variables)}</td>
													<td>{findingListLabel(displayFinding.mediators)}</td>
													<td>
														{#if displayFinding.direction}
															<span>{relationLabel(displayFinding.direction)}</span>
														{/if}
														{#if displayFinding.outcomes.length}
															<span>{findingListLabel(displayFinding.outcomes)}</span>
														{:else}
															<span>{findingListLabel([])}</span>
														{/if}
														{#if finding.comparison_summary}
															<div class="research-understanding-workbench__comparison-mini">
																{#if findingComparisonValueLabel(finding)}
																	<strong>{findingComparisonValueLabel(finding)}</strong>
																{/if}
																{#if findingComparisonContextLabel(finding)}
																	<span>{findingComparisonContextLabel(finding)}</span>
																{/if}
															</div>
														{/if}
													</td>
													<td title={displayFinding.scope_summary || ''}>{findingScopeTableLabel(displayFinding)}</td>
													<td>
														<span class="research-understanding-workbench__grade">
															{supportGradeLabel(displayFinding.support_grade)}
														</span>
													</td>
													<td>
														<div class="research-understanding-workbench__basis">
															<strong>{usagePreview.title}</strong>
															<span>{findingDirectEvidenceLabel(displayFinding)}</span>
															<span>{findingPaperCoverageLabel(displayFinding)}</span>
															<span>{usagePreview.datasetNote}</span>
															{#if usagePreview.nextAction}
																<span>{usagePreview.nextAction}</span>
															{/if}
																{#if findingReviewReasonSummary(displayFinding)}
																	<span>{findingReviewReasonSummary(displayFinding)}</span>
																{/if}
															</div>
														</td>
														<td>
															<div class="research-understanding-workbench__trust">
																<span
																	class={`research-understanding-workbench__trust-badge research-understanding-workbench__trust-badge--${trust.labelStatus}`}
																>
																	{datasetLabelStatusLabel(trust.labelStatus)}
																</span>
																<small>{findingDatasetTrustSubtitle(trust)}</small>
																<small>{findingReviewStatusLabel(findingReviewStatusForDisplay(finding, trust))}</small>
															</div>
														</td>
													<td>
														<div class="research-understanding-workbench__finding-actions">
															<button
																type="button"
																aria-describedby={findingSummaryId(displayFinding)}
																on:click={() => openFindingDetail(finding.finding_id)}
															>
																{$t('research.understanding.openFindingDetail')}
															</button>
															<button
																type="button"
																aria-describedby={findingSummaryId(displayFinding)}
																disabled={feedbackSubmitting || !reviewerReady || trust.datasetUseStatus === 'training_ready'}
																on:click={() => acceptFinding(finding)}
															>
																{feedbackSubmitting
																	? $t('research.understanding.quickAcceptSaving')
																	: findingAcceptLabel(finding)}
															</button>
															<button
																type="button"
																aria-describedby={findingSummaryId(displayFinding)}
																on:click={() => openFindingReject(finding.finding_id)}
															>
																{$t('research.understanding.quickReject')}
															</button>
															<button
																type="button"
																aria-describedby={findingSummaryId(displayFinding)}
																on:click={() => openFindingCorrection(finding.finding_id)}
															>
																{$t('research.understanding.quickCorrect')}
															</button>
														</div>
													</td>
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
						<div class="research-understanding-workbench__empty">
							{#if hasUnprojectedEffects}
								{$t('research.understanding.noExpertFindings')}
							{:else}
								{$t('research.understanding.noFindings')}
							{/if}
						</div>
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
											{#if selectedReviewQueuePosition}
												<span>{selectedReviewQueuePosition}</span>
											{/if}
											{#if selectedFindingTrust}
												<span
													class={`research-understanding-workbench__trust-badge research-understanding-workbench__trust-badge--${selectedFindingTrust.labelStatus}`}
												>
													{datasetLabelStatusLabel(selectedFindingTrust.labelStatus)}
												</span>
											{/if}
											<span>{supportGradeLabel(selectedDisplayFinding?.support_grade ?? selectedFinding.support_grade)}</span>
											{#if selectedFindingTrust}
												<span>
													{findingReviewStatusLabel(
														findingReviewStatusForDisplay(selectedFinding, selectedFindingTrust)
													)}
												</span>
												<span>{datasetUseStatusLabel(selectedFindingTrust.datasetUseStatus)}</span>
												<span>{findingTrustSourceLabel(selectedFindingTrust.source)}</span>
											{/if}
											{#if selectedFinding.confidence !== null}
												<span>{confidenceLabel(selectedFinding.confidence)}</span>
											{/if}
											<span>{findingPaperCoverageLabel(selectedFinding)}</span>
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
										{selectedDisplayFinding?.statement ||
											selectedDisplayFinding?.title ||
											displayClaim?.statement ||
											selectedClaim?.statement ||
											''}
									</strong>
									{#if selectedDisplayFinding?.title && selectedDisplayFinding.title !== selectedDisplayFinding.statement}
										<p>{selectedDisplayFinding.title}</p>
									{:else if !selectedFinding && selectedEffect && selectedEffect.title && selectedEffect.title !== (displayClaim?.statement ?? selectedClaim?.statement)}
										<p>{selectedEffect.title}</p>
									{/if}
								<div
									class="research-understanding-workbench__review-actions"
									aria-label={$t('research.understanding.reviewActions')}
								>
									{#if selectedFinding}
										<button
											type="button"
											class="research-understanding-workbench__review-action--accept"
											disabled={feedbackSubmitting || !collectionId || !reviewerReady}
											on:click={acceptSelectedFinding}
										>
											{feedbackSubmitting
												? $t('research.understanding.quickAcceptSaving')
												: findingAcceptLabel(selectedFinding)}
										</button>
										<button
											type="button"
											disabled={feedbackSubmitting || !collectionId || !reviewerReady || !nextReviewCandidateAfter(selectedFinding.finding_id, feedbackByTargetId)}
											on:click={acceptSelectedFindingAndOpenNext}
										>
											{feedbackSubmitting
												? $t('research.understanding.quickAcceptSaving')
												: findingAcceptLabel(selectedFinding, true)}
										</button>
										<button
											type="button"
											class:research-understanding-workbench__review-action--active={activeReviewPanel ===
												'feedback' &&
												feedbackStatus === 'incorrect' &&
												feedbackIssue !== 'none'}
											aria-pressed={activeReviewPanel === 'feedback' &&
												feedbackStatus === 'incorrect' &&
												feedbackIssue !== 'none'}
											on:click={rejectSelectedFinding}
										>
											{$t('research.understanding.quickReject')}
										</button>
										<button
											type="button"
											class:research-understanding-workbench__review-action--active={activeReviewPanel ===
												'curation'}
											aria-pressed={activeReviewPanel === 'curation'}
											on:click={correctSelectedFinding}
										>
											{$t('research.understanding.quickCorrect')}
										</button>
									{/if}
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
								{#if selectedFindingDecision}
									<section
										class="research-understanding-workbench__basis-panel research-understanding-workbench__basis-panel--decision"
										aria-label={$t('research.understanding.findingDecision')}
									>
										<strong>{selectedFindingDecision.title}</strong>
										<p>{selectedFindingDecision.body}</p>
									</section>
								{/if}
								{#if selectedFindingUsagePath}
									<section
										class="research-understanding-workbench__usage-path"
										aria-label={$t('research.understanding.findingUsagePath')}
									>
										<div>
											<span>{$t('research.understanding.findingUsageCurrent')}</span>
											<strong>{selectedFindingUsagePath.title}</strong>
											<p>{selectedFindingUsagePath.body}</p>
										</div>
										<div>
											<span>{$t('research.understanding.findingUsageDataset')}</span>
											{#if selectedFindingTrust}
												<strong>{datasetLabelStatusLabel(selectedFindingTrust.labelStatus)}</strong>
												<p>{findingDatasetTrustSubtitle(selectedFindingTrust)}</p>
											{/if}
											<p>{selectedFindingUsagePath.datasetNote}</p>
										</div>
										<div>
											<span>{$t('research.understanding.findingUsageUpgrade')}</span>
											<ul>
												{#each selectedFindingUsagePath.checklist as item}
													<li>{item}</li>
												{/each}
											</ul>
										</div>
									</section>
								{/if}
								{#if selectedFindingReviewReasons.length}
									<section
										class="research-understanding-workbench__basis-panel research-understanding-workbench__basis-panel--review-reasons"
										aria-label={$t('research.understanding.findingReviewReasonPanel')}
									>
										<div>
											<strong>{$t('research.understanding.findingReviewReasonPanel')}</strong>
											<span>{findingReviewReasonActionLabel(selectedDisplayFinding ?? selectedFinding, selectedFindingDatasetSample)}</span>
										</div>
										<ul>
											{#each selectedFindingReviewReasons as reason (reason)}
												<li>{findingReviewReasonLabel(reason)}</li>
											{/each}
										</ul>
									</section>
								{/if}
								<section
									class="research-understanding-workbench__basis-panel"
									aria-label={$t('research.understanding.evidenceBasis')}
								>
									<strong>{$t('research.understanding.evidenceBasis')}</strong>
									<ul>
										{#each findingAuditNotes(selectedFinding) as note}
											<li>{note}</li>
										{/each}
									</ul>
								</section>
								<section
									class="research-understanding-workbench__basis-panel"
									aria-label={$t('research.understanding.findingEvidenceRoleCoverage')}
								>
									<strong>{$t('research.understanding.findingEvidenceRoleCoverage')}</strong>
									<div class="research-understanding-workbench__role-grid">
										{#each findingEvidenceRoleSummary(selectedFinding) as roleSummary (roleSummary.role)}
											<div
												class:research-understanding-workbench__role-grid-item--empty={roleSummary.count === 0}
											>
												<span>{roleSummary.label}</span>
												<strong>{roleSummary.count}</strong>
											</div>
										{/each}
									</div>
									<ul>
										{#each findingEvidenceGapNotes(selectedFinding) as note}
											<li>{note}</li>
										{/each}
									</ul>
								</section>
								<section
									class="research-understanding-workbench__basis-panel research-understanding-workbench__basis-panel--boundary"
									aria-label={$t('research.understanding.conclusionUseBoundary')}
								>
									<strong>{$t('research.understanding.conclusionUseBoundary')}</strong>
									<p>{findingGeneralizationStatusLabel(selectedFinding)}</p>
									<ul>
										{#each findingUseBoundaryNotes(selectedFinding) as note}
											<li>{note}</li>
										{/each}
									</ul>
								</section>
								{#if selectedRelatedReviewFindings.length}
									<section
										class="research-understanding-workbench__basis-panel research-understanding-workbench__basis-panel--related-review"
										aria-label={$t('research.understanding.relatedReviewFindings')}
									>
										<strong>{$t('research.understanding.relatedReviewFindings')}</strong>
										<p>{$t('research.understanding.relatedReviewFindingsBody')}</p>
										<div class="research-understanding-workbench__related-review-list">
											{#each selectedRelatedReviewFindings as relatedFinding (relatedFinding.finding_id)}
												<button
													type="button"
													on:click={() => openRelatedReviewFinding(relatedFinding.finding_id)}
												>
													<span>{relatedFinding.statement || relatedFinding.title}</span>
													<small>
														{[
															supportGradeLabel(relatedFinding.support_grade),
															findingDirectEvidenceLabel(relatedFinding),
															findingPaperCoverageLabel(relatedFinding)
														].join(' · ')}
													</small>
												</button>
											{/each}
										</div>
									</section>
								{/if}
								<div class="research-understanding-workbench__context research-understanding-workbench__context--finding-chain">
									<div>
										<span>{$t('research.understanding.findingVariables')}</span>
										<p>{findingChainText(selectedDisplayFinding?.variables ?? selectedFinding.variables)}</p>
									</div>
									<div>
										<span>{$t('research.understanding.findingMechanism')}</span>
										<p>{findingChainText(selectedDisplayFinding?.mediators ?? selectedFinding.mediators)}</p>
									</div>
									<div>
										<span>{$t('research.understanding.findingOutcomes')}</span>
										<p>{findingChainText(selectedDisplayFinding?.outcomes ?? selectedFinding.outcomes)}</p>
									</div>
									{#if selectedDisplayFinding?.direction || selectedFinding.direction}
										<div>
											<span>{$t('research.understanding.relationDirection')}</span>
											<p>{relationLabel(selectedDisplayFinding?.direction ?? selectedFinding.direction)}</p>
										</div>
									{/if}
									{#if selectedDisplayFinding?.scope_summary || selectedFinding.scope_summary}
										<div>
											<span>{$t('research.understanding.findingScope')}</span>
											<p>{selectedDisplayFinding?.scope_summary ?? selectedFinding.scope_summary}</p>
										</div>
									{/if}
								</div>
								{#if selectedFinding.comparison_summary}
									<section
										class="research-understanding-workbench__basis-panel research-understanding-workbench__basis-panel--comparison"
										aria-label="Comparison"
									>
										<strong>Comparison</strong>
										{#if findingComparisonTitle(selectedFinding)}
											<p>{findingComparisonTitle(selectedFinding)}</p>
										{/if}
										{#if findingComparisonValueLabel(selectedFinding)}
											<p>{findingComparisonValueLabel(selectedFinding)}</p>
										{/if}
										{#if findingComparisonGroupLabel(selectedFinding)}
											<small>{findingComparisonGroupLabel(selectedFinding)}</small>
										{/if}
										{#if findingComparisonContextLabel(selectedFinding)}
											<small>{findingComparisonContextLabel(selectedFinding)}</small>
										{/if}
									</section>
								{/if}
							{/if}

							{#if activeReviewPanel === 'feedback'}
								<form
									class="research-understanding-workbench__feedback research-understanding-workbench__feedback--primary"
									on:submit|preventDefault={() => submitClaimFeedback()}
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
										<small class="research-understanding-workbench__feedback-guidance">
											{$t('research.understanding.feedbackIssueCategory', {
												category: datasetErrorCategoryLabel(feedbackIssueCategory(feedbackIssue))
											})}
											{feedbackIssueGuidance(feedbackIssue)}
										</small>
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
									<div class="research-understanding-workbench__reviewer-chip">
										<span>{$t('research.understanding.feedbackReviewer')}</span>
										<strong>{currentReviewer || $t('research.understanding.reviewerUnavailable')}</strong>
									</div>
									<button
										type="submit"
										disabled={feedbackSubmitting || !collectionId || !reviewerReady}
									>
										{feedbackSubmitting
											? $t('research.understanding.feedbackSaving')
											: $t('research.understanding.feedbackSubmit')}
									</button>
									<button
										type="button"
										disabled={feedbackSubmitting || !collectionId || !reviewerReady || !selectedFinding || !nextReviewCandidateAfter(selectedFinding.finding_id)}
										on:click={() => submitClaimFeedback({ openNext: true })}
									>
										{feedbackSubmitting
											? $t('research.understanding.feedbackSaving')
											: $t('research.understanding.feedbackSubmitAndNext')}
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
									on:submit|preventDefault={() => submitClaimCuration()}
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
										<span>{$t('research.understanding.curationSupportGrade')}</span>
										<select
											id={`${titleId}-curation-support-grade`}
											name="curation_support_grade"
											bind:value={curationSupportGrade}
											disabled={curationSubmitting}
										>
											{#each SUPPORT_GRADE_ORDER.filter((grade) => grade !== 'all') as grade (grade)}
												<option value={grade}>{supportGradeLabel(grade)}</option>
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
									<label>
										<span>{$t('research.understanding.curationVariables')}</span>
										<input
											id={`${titleId}-curation-variables`}
											name="curation_variables"
											bind:value={curationVariables}
											disabled={curationSubmitting}
										/>
									</label>
									<label>
										<span>{$t('research.understanding.curationMediators')}</span>
										<input
											id={`${titleId}-curation-mediators`}
											name="curation_mediators"
											bind:value={curationMediators}
											disabled={curationSubmitting}
										/>
									</label>
									<label>
										<span>{$t('research.understanding.curationOutcomes')}</span>
										<input
											id={`${titleId}-curation-outcomes`}
											name="curation_outcomes"
											bind:value={curationOutcomes}
											disabled={curationSubmitting}
										/>
									</label>
									<label>
										<span>{$t('research.understanding.curationDirection')}</span>
										<input
											id={`${titleId}-curation-direction`}
											name="curation_direction"
											bind:value={curationDirection}
											disabled={curationSubmitting}
										/>
									</label>
									<label>
										<span>{$t('research.understanding.curationScope')}</span>
										<textarea
											id={`${titleId}-curation-scope`}
											name="curation_scope"
											bind:value={curationScopeSummary}
											disabled={curationSubmitting}
											maxlength="1000"
											rows="2"
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
									<div class="research-understanding-workbench__reviewer-chip">
										<span>{$t('research.understanding.curationReviewer')}</span>
										<strong>{currentReviewer || $t('research.understanding.reviewerUnavailable')}</strong>
									</div>
									<button
										type="submit"
										disabled={curationSubmitting ||
											!collectionId ||
											!curationStatement.trim() ||
											!reviewerReady}
									>
										{curationSubmitting
											? $t('research.understanding.curationSaving')
											: $t('research.understanding.curationSubmit')}
									</button>
									<button
										type="button"
										disabled={curationSubmitting ||
											!collectionId ||
											!curationStatement.trim() ||
											!reviewerReady ||
											!selectedFinding ||
											!nextReviewCandidateAfter(selectedFinding.finding_id)}
										on:click={() => submitClaimCuration({ openNext: true })}
									>
										{curationSubmitting
											? $t('research.understanding.curationSaving')
											: $t('research.understanding.curationSubmitAndNext')}
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
												{@const selectedQuote = evidenceQuote(ref)}
												{@const sourceBlock = evidenceSourceBlock(ref)}
												<article class="research-understanding-workbench__evidence">
													<div class="research-understanding-workbench__evidence-header">
														<div>
															<strong>{readableEvidenceTitle(ref.title)}</strong>
															<span>{evidenceMeta(ref)}</span>
														</div>
														{#if href}
															<a class="research-understanding-workbench__evidence-link" {href}>
																{$t('research.understanding.openEvidenceSource')}
															</a>
														{/if}
													</div>
													{#if selectedQuote}
														<div class="research-understanding-workbench__evidence-quote">
															<span>{$t('research.understanding.selectedEvidenceQuote')}</span>
															<p>{selectedQuote}</p>
														</div>
													{:else}
														<small>{$t('research.understanding.noEvidenceSourceText')}</small>
													{/if}
													{#if ref.table_audit && (tableAuditColumns(ref) || tableAuditRows(ref).length)}
														<div class="research-understanding-workbench__table-audit">
															<span>{$t('research.understanding.relevantTableRows')}</span>
															{#if tableAuditColumns(ref)}
																<p>{tableAuditColumns(ref)}</p>
															{/if}
															{#if tableAuditHasUnalignedRows(ref)}
																<p class="research-understanding-workbench__table-audit-warning">
																	{$t('research.understanding.unalignedTableRowsWarning')}
																</p>
															{/if}
															{#if tableAuditRows(ref).length}
																<ul>
																	{#each tableAuditRows(ref) as row (row.row_index)}
																		<li>
																			<small>
																				{$t('research.understanding.tableRowLabel', {
																					row: row.row_index
																				})}
																			</small>
																			<span>{tableAuditRowText(ref, row)}</span>
																		</li>
																	{/each}
																</ul>
															{/if}
														</div>
													{/if}
													{#if hasDistinctEvidenceSourceBlock(ref)}
														<details class="research-understanding-workbench__evidence-source">
															<summary>{$t('research.understanding.parsedSourceBlock')}</summary>
															<p>{sourceBlock}</p>
														</details>
													{/if}
												</article>
											{/each}
										</section>
									{:else}
										<div class="research-understanding-workbench__empty">
											{$t('research.understanding.noFindingEvidence')}
										</div>
									{/each}
									{#if selectedSecondaryFindingEvidenceCount() > 0}
										<p class="research-understanding-workbench__audit-note">
											{$t('research.understanding.secondaryFindingEvidenceCount', {
												count: selectedSecondaryFindingEvidenceCount()
											})}
										</p>
									{/if}
								</div>
							{:else}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.understanding.evidenceRefs')}</h5>
									{#each selectedEvidenceRefs as ref (ref.evidence_ref_id)}
										{@const href = evidenceHref(ref)}
										{@const selectedQuote = evidenceQuote(ref)}
										{@const sourceBlock = evidenceSourceBlock(ref)}
										<article class="research-understanding-workbench__evidence">
											<div class="research-understanding-workbench__evidence-header">
												<div>
													<strong>{readableEvidenceTitle(ref.title)}</strong>
													<span>{evidenceMeta(ref)}</span>
												</div>
												{#if href}
													<a class="research-understanding-workbench__evidence-link" {href}>
														{$t('research.understanding.openEvidenceSource')}
													</a>
												{/if}
											</div>
											{#if selectedQuote}
												<div class="research-understanding-workbench__evidence-quote">
													<span>{$t('research.understanding.selectedEvidenceQuote')}</span>
													<p>{selectedQuote}</p>
												</div>
											{:else}
												<small>{$t('research.understanding.noEvidenceSourceText')}</small>
											{/if}
											{#if ref.table_audit && (tableAuditColumns(ref) || tableAuditRows(ref).length)}
												<div class="research-understanding-workbench__table-audit">
													<span>{$t('research.understanding.relevantTableRows')}</span>
													{#if tableAuditColumns(ref)}
														<p>{tableAuditColumns(ref)}</p>
													{/if}
													{#if tableAuditHasUnalignedRows(ref)}
														<p class="research-understanding-workbench__table-audit-warning">
															{$t('research.understanding.unalignedTableRowsWarning')}
														</p>
													{/if}
													{#if tableAuditRows(ref).length}
														<ul>
															{#each tableAuditRows(ref) as row (row.row_index)}
																<li>
																	<small>
																		{$t('research.understanding.tableRowLabel', {
																			row: row.row_index
																		})}
																	</small>
																	<span>{tableAuditRowText(ref, row)}</span>
																</li>
															{/each}
														</ul>
													{/if}
												</div>
											{/if}
											{#if hasDistinctEvidenceSourceBlock(ref)}
												<details class="research-understanding-workbench__evidence-source">
													<summary>{$t('research.understanding.parsedSourceBlock')}</summary>
													<p>{sourceBlock}</p>
												</details>
											{/if}
										</article>
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

							{#if selectedClaim && (selectedDetailWarnings.length || (!selectedFinding && selectedClaim.source_object_ids.length))}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.warnings')}</h5>
									{#if selectedDetailWarnings.length}
										<div class="research-understanding-workbench__chips">
											{#each selectedDetailWarnings as warning (`${selectedClaim.claim_id}-${warning}`)}
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
	.research-understanding-workbench__column {
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

	.research-understanding-workbench__expert-summary {
		display: grid;
		grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.9fr);
		gap: 12px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__expert-summary > div:first-child {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.research-understanding-workbench__expert-summary strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__expert-summary p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__expert-summary ul {
		grid-column: 1 / -1;
		display: grid;
		gap: 4px;
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__expert-metrics {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__expert-metrics span {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		min-height: 30px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 5px 8px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__expert-metrics strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__review-loop {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(230px, 0.75fr);
		gap: 12px;
		border: 1px solid var(--accent-border);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--accent-subtle);
	}

	.research-understanding-workbench__review-loop--needs_review,
	.research-understanding-workbench__review-loop--continue_review,
	.research-understanding-workbench__review-loop--needs_reviewer {
		border-color: rgba(217, 119, 6, 0.36);
		background: rgba(217, 119, 6, 0.08);
	}

	.research-understanding-workbench__review-loop--export_ready {
		border-color: rgba(22, 163, 74, 0.34);
		background: rgba(22, 163, 74, 0.08);
	}

	.research-understanding-workbench__review-loop > div:first-child,
	.research-understanding-workbench__review-loop-errors {
		display: grid;
		gap: 4px;
		min-width: 0;
	}

	.research-understanding-workbench__review-loop > div:first-child > span,
	.research-understanding-workbench__review-loop-errors > strong {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		text-transform: uppercase;
	}

	.research-understanding-workbench__review-loop strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__review-loop p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__review-loop-metrics,
	.research-understanding-workbench__review-loop-actions,
	.research-understanding-workbench__review-loop-errors div {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__review-loop-metrics span,
	.research-understanding-workbench__review-loop-errors span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		min-height: 28px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 4px 8px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		white-space: nowrap;
	}

	.research-understanding-workbench__review-loop-actions button,
	.research-understanding-workbench__review-loop-next-actions button,
	.research-understanding-workbench__review-loop-link {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 30px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 5px 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
		text-decoration: none;
	}

	.research-understanding-workbench__review-loop-actions button:hover,
	.research-understanding-workbench__review-loop-actions button:focus-visible,
	.research-understanding-workbench__review-loop-next-actions button:hover,
	.research-understanding-workbench__review-loop-next-actions button:focus-visible,
	.research-understanding-workbench__review-loop-link:hover,
	.research-understanding-workbench__review-loop-link:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.research-understanding-workbench__review-loop-actions button:disabled,
	.research-understanding-workbench__review-loop-next-actions button:disabled,
	.research-understanding-workbench__review-loop-link--disabled {
		color: var(--text-secondary);
		cursor: not-allowed;
		opacity: 0.62;
	}

	.research-understanding-workbench__review-loop-link--disabled {
		pointer-events: none;
	}

	.research-understanding-workbench__review-loop-next {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(220px, 0.65fr);
		gap: 10px;
		min-width: 0;
		border: 1px solid rgba(217, 119, 6, 0.28);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__review-loop-next > div:first-child {
		display: grid;
		gap: 3px;
		min-width: 0;
	}

	.research-understanding-workbench__review-loop-next > div:first-child > span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		text-transform: uppercase;
	}

	.research-understanding-workbench__review-loop-next strong,
	.research-understanding-workbench__review-loop-next p {
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__review-loop-next-fields,
	.research-understanding-workbench__review-loop-next-reasons,
	.research-understanding-workbench__review-loop-next-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__review-loop-next-fields {
		justify-content: flex-end;
	}

	.research-understanding-workbench__review-loop-next-fields span,
	.research-understanding-workbench__review-loop-next-reasons span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		max-width: 100%;
		min-height: 28px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 4px 8px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__review-loop-next-fields strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__review-loop-next-reasons {
		grid-column: 1 / -1;
	}

	.research-understanding-workbench__review-loop-next-actions {
		grid-column: 1 / -1;
	}

	.research-understanding-workbench__review-loop-checklist {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 8px;
		min-width: 0;
	}

	.research-understanding-workbench__review-loop-check {
		display: grid;
		gap: 4px;
		min-width: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 9px 10px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__review-loop-check span,
	.research-understanding-workbench__review-loop-check strong {
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__review-loop-check span {
		color: var(--text-primary);
		font-weight: 750;
	}

	.research-understanding-workbench__review-loop-check strong {
		width: fit-content;
		border-radius: 999px;
		padding: 1px 7px;
		background: var(--bg-subtle);
		color: var(--text-secondary);
	}

	.research-understanding-workbench__review-loop-check p {
		margin: 0;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__review-loop-check--done {
		border-color: rgba(22, 163, 74, 0.28);
	}

	.research-understanding-workbench__review-loop-check--done strong {
		background: rgba(22, 163, 74, 0.12);
		color: #166534;
	}

	.research-understanding-workbench__review-loop-check--active {
		border-color: rgba(217, 119, 6, 0.28);
	}

	.research-understanding-workbench__review-loop-check--active strong {
		background: rgba(217, 119, 6, 0.13);
		color: #92400e;
	}

	.research-understanding-workbench__review-loop-check--blocked {
		border-color: rgba(100, 116, 139, 0.28);
	}

	.research-understanding-workbench__review-loop-check--blocked strong {
		background: rgba(100, 116, 139, 0.14);
		color: var(--text-secondary);
	}

	.research-understanding-workbench__review-loop ul {
		grid-column: 1 / -1;
		display: grid;
		gap: 4px;
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__review-loop-errors {
		grid-column: 1 / -1;
		border-top: 1px solid var(--border-default);
		padding-top: 10px;
	}

	.research-understanding-workbench__axis-coverage {
		display: grid;
		gap: 12px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__axis-coverage-heading h4,
	.research-understanding-workbench__axis-group-heading strong {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__axis-coverage-heading p,
	.research-understanding-workbench__axis-group-heading span {
		margin: 3px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__coverage-gaps {
		display: grid;
		gap: 10px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__coverage-gaps strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__coverage-gaps p {
		margin: 2px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__coverage-gaps ul {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.research-understanding-workbench__coverage-gaps li {
		display: grid;
		grid-template-columns: minmax(110px, 0.28fr) minmax(0, 1fr);
		gap: 8px;
		align-items: start;
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__coverage-gaps li span {
		min-width: 0;
		overflow-wrap: anywhere;
		color: var(--text-secondary);
	}

	.research-understanding-workbench__answer-boundary {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(220px, 0.8fr);
		gap: 10px;
		align-items: start;
		border: 1px solid var(--accent-border);
		border-radius: var(--radius-md);
		padding: 10px;
		background: var(--accent-subtle);
	}

	.research-understanding-workbench__answer-boundary div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}

	.research-understanding-workbench__answer-boundary strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__answer-boundary p,
	.research-understanding-workbench__answer-boundary span {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__answer-boundary span {
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__axis-coverage-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}

	.research-understanding-workbench__axis-group {
		display: grid;
		gap: 8px;
		min-width: 0;
	}

	.research-understanding-workbench__axis-group ul {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.research-understanding-workbench__axis-group li > button,
	.research-understanding-workbench__axis-group li > span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 5px 7px;
		background: var(--bg-subtle);
		color: var(--text-primary);
		font: inherit;
		font-size: 12px;
		line-height: 18px;
		text-align: left;
	}

	.research-understanding-workbench__axis-group li > button {
		cursor: pointer;
	}

	.research-understanding-workbench__axis-group li > button:hover {
		border-color: var(--accent-border);
		background: var(--accent-subtle);
	}

	.research-understanding-workbench__axis-group li > button > span,
	.research-understanding-workbench__axis-group li > span > span {
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__axis-group small {
		flex: 0 0 auto;
		border-radius: var(--radius-sm);
		padding: 1px 5px;
		font-size: 11px;
		font-weight: 700;
		line-height: 15px;
	}

	.research-understanding-workbench__axis-status--primary {
		background: rgba(22, 163, 74, 0.12);
		color: #166534;
	}

	.research-understanding-workbench__axis-status--review {
		background: rgba(217, 119, 6, 0.13);
		color: #92400e;
	}

	.research-understanding-workbench__axis-status--mechanism {
		background: rgba(37, 99, 235, 0.12);
		color: #1d4ed8;
	}

	.research-understanding-workbench__axis-status--context {
		background: rgba(71, 85, 105, 0.12);
		color: #475569;
	}

	.research-understanding-workbench__axis-status--missing {
		background: rgba(100, 116, 139, 0.14);
		color: var(--text-secondary);
	}

	.research-understanding-workbench__dataset {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__dataset summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 12px;
		cursor: pointer;
	}

	.research-understanding-workbench__dataset summary span {
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 750;
		line-height: 19px;
	}

	.research-understanding-workbench__dataset summary small,
	.research-understanding-workbench__dataset p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__dataset-body {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 12px;
		border-top: 1px solid var(--border-default);
		padding: 10px 12px 12px;
	}

	.research-understanding-workbench__dataset-counts,
	.research-understanding-workbench__dataset-actions,
	.research-understanding-workbench__dataset-errors div {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__dataset-errors {
		display: grid;
		flex-basis: 100%;
		gap: 6px;
		min-width: 0;
		border-top: 1px solid var(--border-default);
		padding-top: 10px;
	}

	.research-understanding-workbench__dataset-collection {
		display: grid;
		flex-basis: 100%;
		gap: 6px;
		min-width: 0;
		border-top: 1px solid var(--border-default);
		padding-top: 10px;
	}

	.research-understanding-workbench__dataset-errors > strong,
	.research-understanding-workbench__dataset-collection > strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__dataset-collection > div {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__dataset-counts span,
	.research-understanding-workbench__dataset-collection span,
	.research-understanding-workbench__dataset-errors span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		min-height: 26px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		padding: 3px 8px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		white-space: nowrap;
	}

	.research-understanding-workbench__dataset-counts strong,
	.research-understanding-workbench__dataset-collection span strong,
	.research-understanding-workbench__dataset-errors span strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__dataset-actions a,
	.research-understanding-workbench__dataset-action-disabled {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 30px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 5px 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		text-decoration: none;
		white-space: nowrap;
	}

	.research-understanding-workbench__dataset-action-disabled {
		border-style: dashed;
		color: var(--text-secondary);
		cursor: not-allowed;
	}

	.research-understanding-workbench__dataset-actions a:hover,
	.research-understanding-workbench__dataset-actions a:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.research-understanding-workbench__summary span,
	.research-understanding-workbench__meta span,
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

	.research-understanding-workbench__evidence {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 13px;
		background: var(--bg-subtle);
		text-decoration: none;
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

	.research-understanding-workbench__table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
	}

	.research-understanding-workbench__findings-table {
		width: 100%;
		min-width: 1200px;
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
	.research-understanding-workbench__findings-table td:nth-child(7),
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

	.research-understanding-workbench__finding-actions {
		display: grid;
		gap: 6px;
		min-width: 112px;
	}

	.research-understanding-workbench__finding-actions button {
		min-height: 30px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 5px 9px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__finding-actions button:hover,
	.research-understanding-workbench__finding-actions button:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
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

	.research-understanding-workbench__basis {
		display: grid;
		gap: 3px;
		min-width: 220px;
	}

	.research-understanding-workbench__basis strong {
		color: var(--text-primary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__basis span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 17px;
	}

	.research-understanding-workbench__trust {
		display: grid;
		gap: 3px;
		min-width: 128px;
	}

	.research-understanding-workbench__trust small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 17px;
	}

	.research-understanding-workbench__trust-badge {
		display: inline-flex;
		align-items: center;
		width: fit-content;
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

	.research-understanding-workbench__trust-badge--gold {
		border-color: rgba(150, 110, 20, 0.45);
		background: rgba(246, 198, 82, 0.16);
		color: #7a5400;
	}

	.research-understanding-workbench__trust-badge--silver {
		border-color: rgba(88, 103, 122, 0.38);
		background: rgba(115, 132, 155, 0.12);
		color: #465265;
	}

	.research-understanding-workbench__trust-badge--candidate {
		border-color: rgba(57, 114, 178, 0.36);
		background: rgba(73, 133, 202, 0.1);
		color: #245b95;
	}

	.research-understanding-workbench__trust-badge--rejected {
		border-color: rgba(177, 72, 72, 0.45);
		background: rgba(210, 82, 82, 0.1);
		color: #983737;
	}

	.research-understanding-workbench__related-review-list {
		display: grid;
		gap: 8px;
	}

	.research-understanding-workbench__related-review-list button {
		display: grid;
		gap: 4px;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 9px 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.research-understanding-workbench__related-review-list button:hover,
	.research-understanding-workbench__related-review-list button:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
	}

	.research-understanding-workbench__related-review-list small {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 17px;
	}

	.research-understanding-workbench__role-grid > div {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 11px;
		line-height: 16px;
		white-space: nowrap;
	}

	.research-understanding-workbench__role-grid strong {
		color: var(--text-primary);
		font-size: 11px;
		line-height: 16px;
	}

	.research-understanding-workbench__role-grid-item--empty {
		color: var(--text-muted);
		opacity: 0.7;
	}

	.research-understanding-workbench__role-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 6px;
		min-width: 0;
	}

	.research-understanding-workbench__role-grid > div {
		justify-content: space-between;
		border-radius: var(--radius-md);
		padding: 7px 9px;
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

	.research-understanding-workbench__basis-panel {
		display: grid;
		gap: 7px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px 12px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__basis-panel strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__basis-panel ul {
		display: grid;
		gap: 4px;
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__basis-panel--decision p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__basis-panel--review-reasons {
		border-color: var(--accent-border);
		background: var(--accent-subtle);
	}

	.research-understanding-workbench__basis-panel--review-reasons > div {
		display: grid;
		gap: 3px;
	}

	.research-understanding-workbench__basis-panel--review-reasons span {
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__usage-path {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(180px, 0.8fr) minmax(240px, 1fr);
		gap: 10px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 12px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__usage-path > div {
		display: grid;
		align-content: start;
		gap: 5px;
		min-width: 0;
	}

	.research-understanding-workbench__usage-path span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
		text-transform: uppercase;
	}

	.research-understanding-workbench__usage-path strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__usage-path p {
		margin: 0;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.research-understanding-workbench__usage-path ul {
		display: grid;
		gap: 4px;
		margin: 0;
		padding-left: 18px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
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

	.research-understanding-workbench__review-action--accept {
		border-color: var(--color-accent);
		background: var(--color-accent);
		color: var(--color-on-accent, #fff);
	}

	.research-understanding-workbench__review-action--accept:hover,
	.research-understanding-workbench__review-action--accept:focus-visible {
		color: var(--color-on-accent, #fff);
	}

	.research-understanding-workbench__review-action--accept:disabled {
		cursor: not-allowed;
		opacity: 0.62;
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

	.research-understanding-workbench__feedback-guidance {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
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

	.research-understanding-workbench__reviewer-chip {
		display: grid;
		gap: 4px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 10px 12px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__reviewer-chip span {
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.research-understanding-workbench__reviewer-chip strong {
		overflow-wrap: anywhere;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
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

	.research-understanding-workbench__context strong,
	.research-understanding-workbench__evidence strong {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 19px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__evidence-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
		min-width: 0;
	}

	.research-understanding-workbench__evidence-header > div {
		display: grid;
		gap: 3px;
		min-width: 0;
	}

	.research-understanding-workbench__evidence-link {
		flex: 0 0 auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 4px 9px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		text-decoration: none;
	}

	.research-understanding-workbench__evidence-link:hover,
	.research-understanding-workbench__evidence-link:focus-visible {
		border-color: var(--color-accent);
		color: var(--color-accent);
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

	.research-understanding-workbench__evidence-quote {
		display: grid;
		gap: 5px;
	}

	.research-understanding-workbench__evidence-quote > span {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
	}

	.research-understanding-workbench__table-audit {
		display: grid;
		gap: 6px;
		border-top: 1px solid var(--border-subtle);
		padding-top: 7px;
	}

	.research-understanding-workbench__table-audit > span,
	.research-understanding-workbench__table-audit small {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 750;
		line-height: 18px;
	}

	.research-understanding-workbench__table-audit-warning {
		color: var(--warning-text);
		font-size: 12px;
		font-weight: 650;
		line-height: 18px;
	}

	.research-understanding-workbench__table-audit ul {
		display: grid;
		gap: 5px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.research-understanding-workbench__table-audit li {
		display: grid;
		gap: 2px;
	}

	.research-understanding-workbench__table-audit li > span {
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__evidence p,
	.research-understanding-workbench__evidence-source p {
		margin: 0;
		border-left: 3px solid var(--border-default);
		padding-left: 10px;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 21px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__evidence-source {
		border-top: 1px solid var(--border-default);
		padding-top: 7px;
	}

	.research-understanding-workbench__evidence-source summary {
		width: fit-content;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		cursor: pointer;
	}

	.research-understanding-workbench__evidence-source summary:hover,
	.research-understanding-workbench__evidence-source summary:focus-visible {
		color: var(--color-accent);
	}

	.research-understanding-workbench__evidence-source p {
		margin-top: 8px;
		color: var(--text-secondary);
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

	:global(:root[data-theme='dark'])
		.research-understanding-workbench__axis-status--primary {
		color: #86efac;
	}

	:global(:root[data-theme='dark'])
		.research-understanding-workbench__axis-status--review {
		color: #fbbf24;
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

		.research-understanding-workbench__answer-boundary,
		.research-understanding-workbench__review-loop,
		.research-understanding-workbench__review-loop-next,
		.research-understanding-workbench__axis-coverage-grid {
			grid-template-columns: 1fr;
		}

		.research-understanding-workbench__dataset {
			align-items: stretch;
		}

		.research-understanding-workbench__dataset summary,
		.research-understanding-workbench__dataset-body {
			align-items: flex-start;
			flex-direction: column;
		}

		.research-understanding-workbench__usage-path {
			grid-template-columns: 1fr;
		}

		.research-understanding-workbench__role-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.research-understanding-workbench__dataset-counts,
		.research-understanding-workbench__dataset-actions,
		.research-understanding-workbench__review-loop-metrics,
		.research-understanding-workbench__review-loop-actions,
		.research-understanding-workbench__review-loop-next-fields {
			justify-content: flex-start;
		}
	}
</style>
