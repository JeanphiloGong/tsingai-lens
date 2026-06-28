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

	let selectedClaimType = 'all';
	let selectedClaimStatus = 'all';
	let selectedEffectId = '';
	let detailMode = false;
	let curationClaimType = 'finding';
	let curationStatus = 'limited';
	let curationStatement = '';
	let curationNote = '';
	let curationReviewer = '';
	let curationSubmitting = false;
	let curationMessage = '';
	let curationError = '';
	let curationLoadError = '';
	let curationsByClaimId = new Map<string, ResearchUnderstandingCuration>();
	let loadedCurationScopeKey = '';
	let lastCurationClaimId = '';
	let feedbackByClaimId = new Map<string, ResearchUnderstandingFeedback[]>();
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
	let lastFeedbackClaimId = '';

	$: presentation = understanding?.presentation ?? null;
	$: presentationSummary = presentation?.summary ?? null;
	$: effectRows = presentation?.effects ?? [];
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
			.filter((claim) => shouldReviewClaim(claim, feedbackByClaimId))
			.map((claim) => claim.claim_id)
	);
	$: filteredEffects = effectRows.filter(
		(effect) =>
			(selectedClaimType === 'all' || effect.claim_type === selectedClaimType) &&
			(selectedClaimStatus === 'all' || effect.support_status === selectedClaimStatus) &&
			(!reviewQueueOnly || effect.needs_review || reviewQueueClaimIds.has(effect.claim_id))
	);
	$: claimTypeCounts = countEffectsBy(effectRows, 'claim_type');
	$: claimStatusCounts = countEffectsBy(effectRows, 'support_status');
	$: if (
		understanding &&
		detailMode &&
		filteredEffects.length &&
		!filteredEffects.some((effect) => effect.effect_id === selectedEffectId)
	) {
		selectedEffectId = filteredEffects[0].effect_id;
	}
	$: if ((!filteredEffects.length || !detailMode) && selectedEffectId) {
		selectedEffectId = '';
	}
	$: selectedEffect =
		detailMode ? (filteredEffects.find((effect) => effect.effect_id === selectedEffectId) ?? null) : null;
	$: selectedClaim = selectedEffect ? (claimById.get(selectedEffect.claim_id) ?? null) : null;
	$: selectedRelations = selectedEffect
		? selectedEffect.relation_ids
				.map((relationId) => relationById.get(relationId))
				.filter((relation): relation is ResearchUnderstandingRelation => Boolean(relation))
		: [];
	$: selectedReadableRelations = selectedRelations.filter((relation) => isReadableRelation(relation));
	$: selectedHiddenRelationCount = Math.max(
		0,
		selectedRelations.length - selectedReadableRelations.length
	);
	$: selectedScopeId = scopeId(understanding);
	$: selectedCuration = selectedClaim ? curationsByClaimId.get(selectedClaim.claim_id) : null;
	$: selectedFeedback = selectedClaim ? (feedbackByClaimId.get(selectedClaim.claim_id) ?? []) : [];
	$: displayClaim = selectedClaim
		? {
				claim_type: selectedCuration?.curated_claim_type ?? selectedClaim.claim_type,
				status: selectedCuration?.curated_status ?? selectedClaim.status,
				statement: selectedCuration?.curated_statement ?? selectedClaim.statement,
				evidence_ref_ids: selectedCuration?.curated_evidence_ref_ids ?? selectedClaim.evidence_ref_ids,
				context_ids: selectedCuration?.curated_context_ids ?? selectedClaim.context_ids
			}
		: null;
	$: selectedEvidenceRefs = displayClaim ? presentationEvidenceForIds(displayClaim.evidence_ref_ids) : [];
	$: selectedContextRefs = displayClaim ? presentationContextsForIds(displayClaim.context_ids) : [];
	$: if ((selectedClaim?.claim_id ?? '') !== lastCurationClaimId) {
		lastCurationClaimId = selectedClaim?.claim_id ?? '';
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
	$: if ((selectedClaim?.claim_id ?? '') !== lastFeedbackClaimId) {
		lastFeedbackClaimId = selectedClaim?.claim_id ?? '';
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

	function compactText(value: string, limit = 160) {
		const normalized = value.replace(/\s+/g, ' ').trim();
		if (normalized.length <= limit) return normalized;
		return `${normalized.slice(0, limit).trim()}...`;
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

	function openClaimDetail(effectId: string) {
		selectedEffectId = effectId;
		detailMode = true;
	}

	function closeClaimDetail() {
		detailMode = false;
		selectedEffectId = '';
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
			ref.source_kind,
			ref.traceability_status,
			ref.page ? `p. ${ref.page}` : ''
		]
			.filter(Boolean)
			.join(' · ');
	}

	function evidenceLabelsForIds(evidenceIds: string[], limit = 3) {
		return evidenceIds
			.map((id) => presentationEvidenceById.get(id)?.title || evidenceById.get(id)?.label || '')
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
		return ids
			.map((id) => presentationEvidenceById.get(id))
			.filter((ref): ref is ResearchUnderstandingPresentationEvidence => Boolean(ref));
	}

	function presentationContextsForIds(ids: string[]) {
		return ids
			.map((id) => presentationContextById.get(id))
			.filter((context): context is ResearchUnderstandingPresentationContext => Boolean(context));
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
		curationStatus = curation?.curated_status ?? selectedClaim?.status ?? 'limited';
		curationStatement = curation?.curated_statement ?? selectedClaim?.statement ?? '';
		curationNote = curation?.note ?? '';
		curationReviewer = curation?.reviewer ?? '';
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
			curationsByClaimId = new Map(curations.map((curation) => [curation.claim_id, curation]));
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
				next.set(item.claim_id, [...(next.get(item.claim_id) ?? []), item]);
			}
			feedbackByClaimId = next;
		} catch (error) {
			feedbackLoadError = error instanceof Error ? error.message : $t('error.unexpected');
		}
	}

	async function submitClaimFeedback() {
		if (!understanding || !selectedClaim || !collectionId || !selectedScopeId) return;
		feedbackSubmitting = true;
		feedbackMessage = '';
		feedbackError = '';
		try {
			const feedback = await createResearchUnderstandingFeedback(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId,
				claim_id: selectedClaim.claim_id,
				review_status: feedbackStatus,
				issue_type: feedbackIssue,
				note: feedbackNote.trim() || null,
				reviewer: feedbackReviewer.trim() || null
			});
			feedbackMessage = $t('research.understanding.feedbackSaved', {
				id: formatShortIdentifier(feedback.feedback_id)
			});
			feedbackByClaimId = new Map(feedbackByClaimId).set(feedback.claim_id, [
				feedback,
				...(feedbackByClaimId.get(feedback.claim_id) ?? [])
			]);
			feedbackNote = '';
		} catch (error) {
			feedbackError = error instanceof Error ? error.message : $t('error.unexpected');
		} finally {
			feedbackSubmitting = false;
		}
	}

	async function submitClaimCuration() {
		if (!understanding || !selectedClaim || !collectionId || !selectedScopeId) return;
		curationSubmitting = true;
		curationMessage = '';
		curationError = '';
		try {
			const curation = await createResearchUnderstandingCuration(collectionId, {
				scope_type: understanding.scope.scope_type,
				scope_id: selectedScopeId,
				claim_id: selectedClaim.claim_id,
				curated_claim_type: curationClaimType,
				curated_status: curationStatus,
				curated_statement: curationStatement.trim(),
				curated_evidence_ref_ids: selectedClaim.evidence_ref_ids,
				curated_context_ids: selectedClaim.context_ids,
				note: curationNote.trim() || null,
				reviewer: curationReviewer.trim() || null
			});
			curationMessage = $t('research.understanding.curationSaved', {
				id: formatShortIdentifier(curation.curation_id)
			});
			curationsByClaimId = new Map(curationsByClaimId).set(curation.claim_id, curation);
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
				<strong>{presentationSummary?.review_queue_count ?? reviewQueueClaimIds.size}</strong>
				<span>{$t('research.understanding.reviewQueue')}</span>
			</div>
		</div>

		{#if effectRows.length || understanding.claims.length || understanding.evidence_refs.length}
			{#if effectRows.length}
				<div
					class="research-understanding-workbench__filters"
					aria-label={$t('research.understanding.claimFilters')}
				>
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
					<div class="research-understanding-workbench__filter-group">
						<span>{$t('research.understanding.filterByStatus')}</span>
						<div class="research-understanding-workbench__segmented" role="list">
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
									count: presentationSummary?.review_queue_count ?? reviewQueueClaimIds.size
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
					aria-label={$t('research.understanding.claimWorkspace')}
				>
					<div class="research-understanding-workbench__column-heading">
						<h4>{$t('research.understanding.claimWorkspace')}</h4>
						<span>
							{$t('research.understanding.filteredClaimCount', {
								shown: filteredEffects.length,
								total: effectRows.length
							})}
						</span>
					</div>
					{#each filteredEffects as effect (effect.effect_id)}
						{@const claim = claimById.get(effect.claim_id)}
						{@const curation = claim ? curationsByClaimId.get(claim.claim_id) : null}
						{@const claimFeedback = claim ? (feedbackByClaimId.get(claim.claim_id) ?? []) : []}
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
								<div class="research-understanding-workbench__chips">
									{#each labels as label, index (`${effect.effect_id}-${index}-${label}`)}
										<span>{label}</span>
									{/each}
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
				</section>
			{:else}
				<section
					class="research-understanding-workbench__detail-view"
					aria-label={$t('research.understanding.claimDetail')}
				>
					<div class="research-understanding-workbench__column-heading">
						<button
							type="button"
							class="research-understanding-workbench__back"
							on:click={closeClaimDetail}
						>
							{$t('research.understanding.backToClaims')}
						</button>
						<h4>{$t('research.understanding.claimDetail')}</h4>
					</div>
					{#if selectedEffect && selectedClaim}
						<article class="research-understanding-workbench__detail">
							<div class="research-understanding-workbench__meta">
								<span>{claimTypeLabel(displayClaim?.claim_type ?? selectedClaim.claim_type)}</span>
								<span>{statusLabel(displayClaim?.status ?? selectedClaim.status)}</span>
								{#if selectedClaim.confidence !== null}
									<span>{confidenceLabel(selectedClaim.confidence)}</span>
								{/if}
								{#if selectedClaim.strength}
									<span>{selectedClaim.strength}</span>
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
							<strong>{displayClaim?.statement ?? selectedClaim.statement}</strong>
							{#if selectedEffect.title && selectedEffect.title !== (displayClaim?.statement ?? selectedClaim.statement)}
								<p>{selectedEffect.title}</p>
							{/if}
							{#if selectedEffect.variable_axis || selectedEffect.target_property || selectedEffect.effect_direction}
								<div class="research-understanding-workbench__context">
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

							{#if selectedCuration}
								<div class="research-understanding-workbench__detail-section">
									<h5>{$t('research.understanding.curationApplied')}</h5>
									<div class="research-understanding-workbench__context">
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
								<h5>{$t('research.understanding.evidenceRefs')}</h5>
								{#each selectedEvidenceRefs as ref (ref.evidence_ref_id)}
									{@const href = evidenceHref(ref)}
									{#if href}
										<a class="research-understanding-workbench__evidence" {href}>
											<strong>{ref.title}</strong>
											<span>{evidenceMeta(ref)}</span>
											{#if ref.quote}
												<small>{ref.quote}</small>
											{/if}
										</a>
									{:else}
										<div class="research-understanding-workbench__evidence">
											<strong>{ref.title}</strong>
											<span>{evidenceMeta(ref)}</span>
											{#if ref.quote}
												<small>{ref.quote}</small>
											{/if}
										</div>
									{/if}
								{:else}
									<div class="research-understanding-workbench__empty">
										{$t('research.understanding.noEvidence')}
									</div>
								{/each}
							</div>

							<div class="research-understanding-workbench__detail-section">
								<h5>{$t('research.understanding.contexts')}</h5>
								{#each selectedContextRefs as context (context.context_id)}
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

							{#if selectedClaim.warnings.length || selectedClaim.source_object_ids.length}
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

							<form
								class="research-understanding-workbench__feedback"
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

							<form
								class="research-understanding-workbench__feedback"
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
		max-width: 980px;
	}

	.research-understanding-workbench__column h4 {
		font-size: 15px;
		line-height: 21px;
	}

	.research-understanding-workbench__column-heading h4,
	.research-understanding-workbench__detail-section h5 {
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
	.research-understanding-workbench__detail > strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__detail,
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

	.research-understanding-workbench__detail {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 13px;
		background: var(--bg-subtle);
	}

	.research-understanding-workbench__detail > p,
	.research-understanding-workbench__context p {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
		overflow-wrap: anywhere;
	}

	.research-understanding-workbench__detail-section {
		padding-top: 10px;
		border-top: 1px solid var(--border-default);
	}

	.research-understanding-workbench__detail-section h5 {
		font-size: 13px;
		line-height: 19px;
	}

	.research-understanding-workbench__feedback {
		padding-top: 10px;
		border-top: 1px solid var(--border-default);
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

	.research-understanding-workbench__feedback-state--error {
		color: var(--color-danger);
	}

	.research-understanding-workbench__context {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: 11px;
		background: var(--surface-card);
	}

	.research-understanding-workbench__evidence {
		display: grid;
		gap: 4px;
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
