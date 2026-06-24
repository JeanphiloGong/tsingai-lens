<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import {
		createResearchUnderstandingCuration,
		createResearchUnderstandingFeedback,
		fetchResearchUnderstandingCurations,
		formatShortIdentifier,
		type ResearchUnderstanding,
		type ResearchUnderstandingClaim,
		type ResearchUnderstandingContext,
		type ResearchUnderstandingCuration,
		type ResearchUnderstandingEvidenceRef,
		type ResearchUnderstandingFeedbackIssueType,
		type ResearchUnderstandingFeedbackStatus,
		type ResearchUnderstandingRelation
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
	let selectedClaimId = '';
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
	let feedbackStatus: ResearchUnderstandingFeedbackStatus = 'correct';
	let feedbackIssue: ResearchUnderstandingFeedbackIssueType = 'none';
	let feedbackNote = '';
	let feedbackReviewer = '';
	let feedbackSubmitting = false;
	let feedbackMessage = '';
	let feedbackError = '';
	let lastFeedbackClaimId = '';

	$: evidenceById = new Map(
		(understanding?.evidence_refs ?? []).map((ref) => [ref.evidence_ref_id, ref])
	);
	$: contextById = new Map(
		(understanding?.contexts ?? []).map((context) => [context.context_id, context])
	);
	$: claims = understanding?.claims ?? [];
	$: filteredClaims = claims.filter(
		(claim) =>
			(selectedClaimType === 'all' || claim.claim_type === selectedClaimType) &&
			(selectedClaimStatus === 'all' || claim.status === selectedClaimStatus)
	);
	$: claimTypeCounts = countClaimsBy(claims, 'claim_type');
	$: claimStatusCounts = countClaimsBy(claims, 'status');
	$: if (
		understanding &&
		filteredClaims.length &&
		!filteredClaims.some((claim) => claim.claim_id === selectedClaimId)
	) {
		selectedClaimId = filteredClaims[0].claim_id;
	}
	$: if (!filteredClaims.length && selectedClaimId) {
		selectedClaimId = '';
	}
	$: selectedClaim =
		filteredClaims.find((claim) => claim.claim_id === selectedClaimId) ?? filteredClaims[0] ?? null;
	$: selectedEvidenceRefs = selectedClaim ? evidenceRefsForIds(selectedClaim.evidence_ref_ids) : [];
	$: selectedContextRefs = selectedClaim ? contextRefsForIds(selectedClaim.context_ids) : [];
	$: selectedRelations = selectedClaim
		? relatedRelationsForClaim(selectedClaim, understanding?.relations ?? [])
		: [];
	$: selectedEvidenceIdSet = new Set(selectedClaim?.evidence_ref_ids ?? []);
	$: selectedScopeId = scopeId(understanding);
	$: selectedCuration = selectedClaim ? curationsByClaimId.get(selectedClaim.claim_id) : null;
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

	function flattenDisplayValues(value: unknown): string[] {
		if (!hasDisplayValue(value)) return [];
		if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
			return [String(value)];
		}
		if (Array.isArray(value)) {
			return value.flatMap((item) => flattenDisplayValues(item));
		}
		if (typeof value === 'object') {
			return Object.values(value as Record<string, unknown>).flatMap((item) =>
				flattenDisplayValues(item)
			);
		}
		return [String(value)];
	}

	function listLabel(values: string[]) {
		const cleaned = [...new Set(values.map((value) => value.trim()).filter(Boolean))];
		return cleaned.length ? cleaned.join(', ') : $t('research.emptyValue');
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

	function evidenceHref(ref: ResearchUnderstandingEvidenceRef) {
		if (ref.href) return ref.href;
		if (!collectionId || !ref.document_id) return '';
		const params: [string, string][] = [];
		const pageValue = displayValue(ref.locator.page);
		const sourceRef = displayValue(ref.locator.source_ref);
		const anchorId = ref.anchor_ids[0] ?? '';
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

	function evidenceMeta(ref: ResearchUnderstandingEvidenceRef) {
		return [
			ref.source_kind,
			ref.traceability_status,
			ref.document_id ? formatShortIdentifier(ref.document_id) : ''
		]
			.filter(Boolean)
			.join(' · ');
	}

	function evidenceLabelsForIds(evidenceIds: string[], limit = 3) {
		return evidenceIds
			.map((id) => evidenceById.get(id)?.label || formatShortIdentifier(id))
			.filter(Boolean)
			.slice(0, limit);
	}

	function contextLabelForIds(contextIds: string[]) {
		const labels = contextIds
			.map((id) => contextById.get(id))
			.filter((context): context is ResearchUnderstandingContext => Boolean(context))
			.flatMap((context) => [
				...context.material_scope,
				...context.property_scope,
				...flattenDisplayValues(context.process_context),
				...flattenDisplayValues(context.test_condition)
			]);
		return listLabel(labels.slice(0, 4));
	}

	function visibleClaims(currentUnderstanding: ResearchUnderstanding) {
		return currentUnderstanding.claims.slice(0, 6);
	}

	function visibleRelations(currentUnderstanding: ResearchUnderstanding) {
		return currentUnderstanding.relations.slice(0, 4);
	}

	function visibleEvidenceRefs(currentUnderstanding: ResearchUnderstanding) {
		return currentUnderstanding.evidence_refs.slice(0, 5);
	}

	function claimEvidenceLabels(claim: ResearchUnderstandingClaim) {
		return evidenceLabelsForIds(claim.evidence_ref_ids);
	}

	function relationEvidenceLabels(relation: ResearchUnderstandingRelation) {
		return evidenceLabelsForIds(relation.evidence_ref_ids, 2);
	}

	function countClaimsBy(
		currentClaims: ResearchUnderstandingClaim[],
		field: 'claim_type' | 'status'
	) {
		const counts = new Map<string, number>([['all', currentClaims.length]]);
		for (const claim of currentClaims) {
			counts.set(claim[field], (counts.get(claim[field]) ?? 0) + 1);
		}
		return counts;
	}

	function optionLabel(label: string, count: number) {
		return `${label} ${count}`;
	}

	function evidenceRefsForIds(ids: string[]) {
		return ids
			.map((id) => evidenceById.get(id))
			.filter((ref): ref is ResearchUnderstandingEvidenceRef => Boolean(ref));
	}

	function contextRefsForIds(ids: string[]) {
		return ids
			.map((id) => contextById.get(id))
			.filter((context): context is ResearchUnderstandingContext => Boolean(context));
	}

	function intersects(left: string[], right: string[]) {
		const rightSet = new Set(right);
		return left.some((item) => rightSet.has(item));
	}

	function relatedRelationsForClaim(
		claim: ResearchUnderstandingClaim,
		relations: ResearchUnderstandingRelation[]
	) {
		return relations.filter(
			(relation) =>
				intersects(claim.evidence_ref_ids, relation.evidence_ref_ids) ||
				intersects(claim.context_ids, relation.context_ids) ||
				intersects(claim.source_object_ids, relation.source_object_ids)
		);
	}

	function contextRows(context: ResearchUnderstandingContext) {
		return [
			[$t('research.understanding.contextMaterial'), listLabel(context.material_scope)],
			[$t('research.understanding.contextProperty'), listLabel(context.property_scope)],
			[$t('research.understanding.contextProcess'), displayValue(context.process_context)],
			[$t('research.understanding.contextTest'), displayValue(context.test_condition)],
			[$t('research.understanding.limitations'), listLabel(context.limitations)]
		].filter(([, value]) => hasDisplayValue(value));
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
				<strong>{understanding.summary.claim_count}</strong>
				<span>{$t('research.understanding.claims')}</span>
			</div>
			<div>
				<strong>{understanding.summary.relation_count}</strong>
				<span>{$t('research.understanding.relationsLabel')}</span>
			</div>
			<div>
				<strong>{understanding.summary.evidence_ref_count}</strong>
				<span>{$t('research.understanding.evidenceRefs')}</span>
			</div>
			<div>
				<strong>{understanding.summary.context_count}</strong>
				<span>{$t('research.understanding.contexts')}</span>
			</div>
		</div>

		{#if understanding.claims.length || understanding.relations.length || understanding.evidence_refs.length}
			{#if understanding.claims.length}
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
				</div>
			{/if}

			<div class="research-understanding-workbench__grid">
				<section
					class="research-understanding-workbench__column"
					aria-label={$t('research.understanding.claims')}
				>
					<div class="research-understanding-workbench__column-heading">
						<h4>{$t('research.understanding.claims')}</h4>
						<span>
							{$t('research.understanding.filteredClaimCount', {
								shown: filteredClaims.length,
								total: understanding.claims.length
							})}
						</span>
					</div>
					{#each filteredClaims as claim (claim.claim_id)}
						{@const labels = claimEvidenceLabels(claim)}
						<button
							type="button"
							class="research-understanding-workbench__card research-understanding-workbench__card--claim"
							class:research-understanding-workbench__card--selected={selectedClaim?.claim_id ===
								claim.claim_id}
							aria-pressed={selectedClaim?.claim_id === claim.claim_id}
							on:click={() => (selectedClaimId = claim.claim_id)}
						>
							<div class="research-understanding-workbench__meta">
								<span>{claimTypeLabel(claim.claim_type)}</span>
								<span>{statusLabel(claim.status)}</span>
								{#if claim.confidence !== null}
									<span>{confidenceLabel(claim.confidence)}</span>
								{/if}
							</div>
							<p>{claim.statement}</p>
							{#if labels.length}
								<div class="research-understanding-workbench__chips">
									{#each labels as label (`${claim.claim_id}-${label}`)}
										<span>{label}</span>
									{/each}
								</div>
							{/if}
							{#if claim.context_ids.length}
								<small>
									{$t('research.understanding.contextPrefix')}
									{contextLabelForIds(claim.context_ids)}
								</small>
							{/if}
						</button>
					{:else}
						<div class="research-understanding-workbench__empty">
							{$t('research.understanding.noClaims')}
						</div>
					{/each}
				</section>

				<section
					class="research-understanding-workbench__column"
					aria-label={$t('research.understanding.relationsLabel')}
				>
					<div class="research-understanding-workbench__column-heading">
						<h4>{$t('research.understanding.relationsLabel')}</h4>
						<span>{$t('research.understanding.relatedToSelectedClaim')}</span>
					</div>
					{#each selectedClaim ? selectedRelations : visibleRelations(understanding) as relation (relation.relation_id)}
						{@const labels = relationEvidenceLabels(relation)}
						<article
							class="research-understanding-workbench__card research-understanding-workbench__card--relation"
						>
							<div class="research-understanding-workbench__meta">
								<span>{relationLabel(relation.relation_type)}</span>
								<span>{statusLabel(relation.status)}</span>
							</div>
							<p>
								<strong>{relation.subject}</strong>
								<span>{relation.predicate}</span>
								<strong>{relation.object}</strong>
							</p>
							{#if labels.length}
								<div class="research-understanding-workbench__chips">
									{#each labels as label (`${relation.relation_id}-${label}`)}
										<span>{label}</span>
									{/each}
								</div>
							{/if}
						</article>
					{:else}
						<div class="research-understanding-workbench__empty">
							{$t('research.understanding.noRelations')}
						</div>
					{/each}
				</section>

				<section
					class="research-understanding-workbench__column"
					aria-label={$t('research.understanding.claimDetail')}
				>
					<h4>{$t('research.understanding.claimDetail')}</h4>
					{#if selectedClaim}
						<article class="research-understanding-workbench__detail">
							<div class="research-understanding-workbench__meta">
								<span>{claimTypeLabel(selectedClaim.claim_type)}</span>
								<span>{statusLabel(selectedClaim.status)}</span>
								{#if selectedClaim.confidence !== null}
									<span>{confidenceLabel(selectedClaim.confidence)}</span>
								{/if}
								{#if selectedClaim.strength}
									<span>{selectedClaim.strength}</span>
								{/if}
							</div>
							<p>{selectedClaim.statement}</p>

							<div class="research-understanding-workbench__detail-section">
								<h5>{$t('research.understanding.evidenceRefs')}</h5>
								{#each selectedEvidenceRefs as ref (ref.evidence_ref_id)}
									{@const href = evidenceHref(ref)}
									{#if href}
										<a class="research-understanding-workbench__evidence" {href}>
											<strong>{ref.label}</strong>
											<span>{evidenceMeta(ref)}</span>
											{#if ref.quote}
												<small>{ref.quote}</small>
											{/if}
										</a>
									{:else}
										<div class="research-understanding-workbench__evidence">
											<strong>{ref.label}</strong>
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
										{#each contextRows(context) as [label, value] (`${context.context_id}-${label}`)}
											<div>
												<span>{label}</span>
												<p>{value}</p>
											</div>
										{/each}
									</div>
								{:else}
									<div class="research-understanding-workbench__empty">
										{$t('research.understanding.noContexts')}
									</div>
								{/each}
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
										<small>
											{$t('research.understanding.sourceObjects')}
											{listLabel(selectedClaim.source_object_ids)}
										</small>
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
									<select bind:value={curationClaimType} disabled={curationSubmitting}>
										{#each CURATION_CLAIM_TYPE_OPTIONS as type (type)}
											<option value={type}>{claimTypeLabel(type)}</option>
										{/each}
									</select>
								</label>
								<label>
									<span>{$t('research.understanding.curationStatus')}</span>
									<select bind:value={curationStatus} disabled={curationSubmitting}>
										{#each CURATION_STATUS_OPTIONS as status (status)}
											<option value={status}>{statusLabel(status)}</option>
										{/each}
									</select>
								</label>
								<label>
									<span>{$t('research.understanding.curationStatement')}</span>
									<textarea
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
										bind:value={curationNote}
										disabled={curationSubmitting}
										maxlength="2000"
										rows="3"
									></textarea>
								</label>
								<label>
									<span>{$t('research.understanding.curationReviewer')}</span>
									<input
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

							<form
								class="research-understanding-workbench__feedback"
								on:submit|preventDefault={submitClaimFeedback}
							>
								<h5>{$t('research.understanding.feedbackTitle')}</h5>
								<label>
									<span>{$t('research.understanding.feedbackStatus')}</span>
									<select bind:value={feedbackStatus} disabled={feedbackSubmitting}>
										{#each FEEDBACK_STATUS_OPTIONS as status (status)}
											<option value={status}>{feedbackStatusLabel(status)}</option>
										{/each}
									</select>
								</label>
								<label>
									<span>{$t('research.understanding.feedbackIssue')}</span>
									<select bind:value={feedbackIssue} disabled={feedbackSubmitting}>
										{#each FEEDBACK_ISSUE_OPTIONS as issue (issue)}
											<option value={issue}>{feedbackIssueLabel(issue)}</option>
										{/each}
									</select>
								</label>
								<label>
									<span>{$t('research.understanding.feedbackNote')}</span>
									<textarea
										bind:value={feedbackNote}
										disabled={feedbackSubmitting}
										maxlength="2000"
										rows="3"
									></textarea>
								</label>
								<label>
									<span>{$t('research.understanding.feedbackReviewer')}</span>
									<input
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
			</div>

			<section
				class="research-understanding-workbench__evidence-strip"
				aria-label={$t('research.understanding.evidenceRefs')}
			>
				<div class="research-understanding-workbench__column-heading">
					<h4>{$t('research.understanding.evidenceRefs')}</h4>
					<span>{$t('research.understanding.evidenceStripHint')}</span>
				</div>
				<div>
					{#each visibleEvidenceRefs(understanding) as ref (ref.evidence_ref_id)}
						{@const href = evidenceHref(ref)}
						{#if href}
							<a
								class="research-understanding-workbench__evidence"
								class:research-understanding-workbench__evidence--selected={selectedEvidenceIdSet.has(
									ref.evidence_ref_id
								)}
								{href}
							>
								<strong>{ref.label}</strong>
								<span>{evidenceMeta(ref)}</span>
							</a>
						{:else}
							<div
								class="research-understanding-workbench__evidence"
								class:research-understanding-workbench__evidence--selected={selectedEvidenceIdSet.has(
									ref.evidence_ref_id
								)}
							>
								<strong>{ref.label}</strong>
								<span>{evidenceMeta(ref)}</span>
							</div>
						{/if}
					{:else}
						<div class="research-understanding-workbench__empty">
							{$t('research.understanding.noEvidence')}
						</div>
					{/each}
				</div>
			</section>
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

	.research-understanding-workbench__grid {
		display: grid;
		grid-template-columns: minmax(260px, 1.05fr) minmax(220px, 0.85fr) minmax(280px, 1.1fr);
		gap: 14px;
		align-items: start;
		min-width: 0;
	}

	.research-understanding-workbench__column-heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
		min-width: 0;
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
	.research-understanding-workbench__card--claim:focus-visible,
	.research-understanding-workbench__card--selected {
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

	.research-understanding-workbench__card--relation p {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: baseline;
	}

	.research-understanding-workbench__card--relation p span {
		color: var(--text-secondary);
	}

	.research-understanding-workbench__detail,
	.research-understanding-workbench__detail-section,
	.research-understanding-workbench__context,
	.research-understanding-workbench__feedback,
	.research-understanding-workbench__evidence-strip {
		display: grid;
		gap: 10px;
		min-width: 0;
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

	.research-understanding-workbench__evidence-strip {
		border-top: 1px solid var(--border-default);
		padding-top: 14px;
	}

	.research-understanding-workbench__evidence-strip > div:last-child {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
		gap: 10px;
	}

	.research-understanding-workbench__evidence--selected {
		border-color: var(--color-accent);
		background: var(--surface-card);
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

	@media (max-width: 1080px) {
		.research-understanding-workbench__grid {
			grid-template-columns: 1fr;
		}
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
