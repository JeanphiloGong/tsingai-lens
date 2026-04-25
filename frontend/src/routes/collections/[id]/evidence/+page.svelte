<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import {
		buildEvidenceQualitySummary,
		fetchEvidenceCards,
		filterEvidenceItems,
		formatConfidence,
		getComparabilityStatus,
		getConfidenceLevel,
		getEvidenceActions,
		getEvidenceQuote,
		getEvidenceSourceLocation,
		getEvidenceTypeBadge,
		getTraceabilityBadge,
		sortEvidenceItems,
		type EvidenceAction,
		type EvidenceActionKey,
		type EvidenceCard,
		type EvidenceCardsResponse,
		type EvidenceComparabilityFilter,
		type EvidenceComparabilityStatus,
		type EvidenceConfidenceFilter,
		type EvidenceFilters,
		type EvidenceSortMode,
		type EvidenceSourceFilter,
		type EvidenceSourceType,
		type EvidenceTraceabilityFilter,
		type EvidenceTypeFilter
	} from '../../../_shared/evidence';
	import { t } from '../../../_shared/i18n';
	import { createBuildTask } from '../../../_shared/tasks';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview,
		type WorkspaceSurfaceState
	} from '../../../_shared/workspace';

	type FilterOption<T extends string> = {
		value: T;
		labelKey: string;
	};

	const TYPE_FILTERS: FilterOption<EvidenceTypeFilter>[] = [
		{ value: '', labelKey: 'evidence.filters.all' },
		{ value: 'process', labelKey: 'evidence.types.process' },
		{ value: 'method', labelKey: 'evidence.types.method' },
		{ value: 'material', labelKey: 'evidence.types.material' },
		{ value: 'property', labelKey: 'evidence.types.property' },
		{ value: 'result', labelKey: 'evidence.types.result' },
		{ value: 'condition', labelKey: 'evidence.types.condition' },
		{ value: 'other', labelKey: 'evidence.types.other' }
	];

	const TRACEABILITY_FILTERS: FilterOption<EvidenceTraceabilityFilter>[] = [
		{ value: '', labelKey: 'evidence.filters.all' },
		{ value: 'direct', labelKey: 'evidence.traceability.direct' },
		{ value: 'indirect', labelKey: 'evidence.traceability.indirect' },
		{ value: 'none', labelKey: 'evidence.traceability.none' }
	];

	const SOURCE_FILTERS: FilterOption<EvidenceSourceFilter>[] = [
		{ value: '', labelKey: 'evidence.filters.all' },
		{ value: 'text', labelKey: 'evidence.sources.text' },
		{ value: 'table', labelKey: 'evidence.sources.table' },
		{ value: 'figure', labelKey: 'evidence.sources.figure' },
		{ value: 'abstract', labelKey: 'evidence.sources.abstract' }
	];

	const CONFIDENCE_FILTERS: FilterOption<EvidenceConfidenceFilter>[] = [
		{ value: '', labelKey: 'evidence.filters.all' },
		{ value: 'high', labelKey: 'evidence.confidence.high' },
		{ value: 'medium', labelKey: 'evidence.confidence.medium' },
		{ value: 'low', labelKey: 'evidence.confidence.low' }
	];

	const COMPARABILITY_FILTERS: FilterOption<EvidenceComparabilityFilter>[] = [
		{ value: '', labelKey: 'evidence.filters.all' },
		{ value: 'joinable', labelKey: 'evidence.comparability.joinable' },
		{ value: 'needs_context', labelKey: 'evidence.comparability.needs_context' },
		{ value: 'not_recommended', labelKey: 'evidence.comparability.not_recommended' },
		{ value: 'added', labelKey: 'evidence.comparability.added' }
	];

	const SORT_OPTIONS: FilterOption<EvidenceSortMode>[] = [
		{ value: 'confidence_desc', labelKey: 'evidence.sort.confidenceDesc' },
		{ value: 'confidence_asc', labelKey: 'evidence.sort.confidenceAsc' },
		{ value: 'recent', labelKey: 'evidence.sort.recent' },
		{ value: 'document', labelKey: 'evidence.sort.document' }
	];

	const MORE_ACTIONS = [
		'evidence.more.copyEvidence',
		'evidence.more.removeFromComparison',
		'evidence.more.markUnusable',
		'evidence.more.reanalyze'
	];

	$: collectionId = $page.params.id ?? '';

	let response: EvidenceCardsResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let actionStatus = '';
	let actionLoading = false;
	let loadedCollectionId = '';
	let notFound = false;

	let search = '';
	let typeFilter: EvidenceTypeFilter = '';
	let traceabilityFilter: EvidenceTraceabilityFilter = '';
	let sourceFilter: EvidenceSourceFilter = '';
	let confidenceFilter: EvidenceConfidenceFilter = '';
	let comparabilityFilter: EvidenceComparabilityFilter = '';
	let sortMode: EvidenceSortMode = 'confidence_desc';

	$: evidenceItems = response?.items ?? [];
	$: evidenceFilters = {
		search,
		type: typeFilter,
		traceability: traceabilityFilter,
		source: sourceFilter,
		confidence: confidenceFilter,
		comparability: comparabilityFilter
	} satisfies EvidenceFilters;
	$: filteredItems = sortEvidenceItems(
		filterEvidenceItems(evidenceItems, evidenceFilters),
		sortMode
	);
	$: qualitySummary = buildEvidenceQualitySummary(evidenceItems);
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'evidence');
	$: updatedAt = latestUpdatedAt(evidenceItems, workspace);
	$: showFallbackState =
		Boolean(workspace) &&
		!loading &&
		evidenceItems.length < 1 &&
		(surfaceState !== 'ready' || notFound);
	$: hasBlockingError = Boolean(error) && !showFallbackState;
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadEvidence();
	}

	async function loadEvidence(clearActionStatus = true) {
		loading = true;
		error = '';
		if (clearActionStatus) actionStatus = '';
		notFound = false;

		const [evidenceResult, workspaceResult] = await Promise.allSettled([
			fetchEvidenceCards(collectionId),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		if (evidenceResult.status === 'fulfilled') {
			response = evidenceResult.value;
			loading = false;
			return;
		}

		response = null;
		notFound = isHttpStatusError(evidenceResult.reason, 404);
		error = errorMessage(evidenceResult.reason);
		loading = false;
	}

	function refreshEvidence() {
		void loadEvidence();
	}

	async function startProcessing() {
		actionLoading = true;
		actionStatus = '';
		try {
			await createBuildTask(collectionId);
			await loadEvidence(false);
			actionStatus = $t('evidence.review.processingStarted');
		} catch (err) {
			actionStatus = safeErrorText(errorMessage(err));
		} finally {
			actionLoading = false;
		}
	}

	function clearFilters() {
		search = '';
		typeFilter = '';
		traceabilityFilter = '';
		sourceFilter = '';
		confidenceFilter = '';
		comparabilityFilter = '';
	}

	function formatDate(value?: string | null) {
		if (!value) return '--';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString(undefined, {
			year: 'numeric',
			month: 'numeric',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function latestUpdatedAt(items: EvidenceCard[], currentWorkspace: WorkspaceOverview | null) {
		const newestEvidenceDate = items
			.flatMap((item) => [item.updated_at, item.extracted_at])
			.filter((value): value is string => Boolean(value))
			.map((value) => new Date(value).getTime())
			.filter((value) => Number.isFinite(value))
			.sort((a, b) => b - a)[0];
		if (typeof newestEvidenceDate === 'number') return new Date(newestEvidenceDate).toISOString();
		return currentWorkspace?.collection.updated_at ?? currentWorkspace?.artifacts.updated_at ?? '';
	}

	function surfaceStatusTone(state: WorkspaceSurfaceState) {
		if (state === 'ready' || state === 'limited') return 'ready';
		if (state === 'processing' || state === 'ready_to_process') return 'processing';
		if (state === 'failed') return 'failed';
		if (state === 'empty') return 'empty';
		return 'pending';
	}

	function stateCardTitle() {
		return $t(`overview.surfaceStateCards.${surfaceState}.title`);
	}

	function stateCardBody() {
		return $t(`overview.surfaceStateCards.${surfaceState}.body`);
	}

	function badgeLabel(badge: { label: string; labelKey?: string }) {
		return badge.labelKey ? $t(badge.labelKey) : badge.label;
	}

	function sourceTypeLabel(sourceType: EvidenceSourceType) {
		return $t(`evidence.sources.${sourceType}`);
	}

	function confidenceLevelLabel(confidence?: number | null) {
		return $t(`evidence.confidence.${getConfidenceLevel(confidence)}`);
	}

	function comparabilityLabel(status: EvidenceComparabilityStatus) {
		return $t(`evidence.comparability.${status}`);
	}

	function safeErrorText(value: string) {
		const firstLine = value.split('\n')[0]?.trim() ?? '';
		if (!firstLine) return $t('error.unexpected');
		return firstLine.length > 180 ? `${firstLine.slice(0, 180)}...` : firstLine;
	}

	function cardTitle(item: EvidenceCard) {
		const text = item.claim_text.trim() || item.evidence_id;
		if (text.length <= 82) return text;
		const firstSentence = text.split(/[.!?]/)[0]?.trim();
		if (firstSentence && firstSentence.length <= 82) return firstSentence;
		return `${text.slice(0, 79)}...`;
	}

	function formatList(values: string[]) {
		return values.length ? values.join(', ') : '--';
	}

	function documentHref(card: EvidenceCard) {
		const anchor = card.evidence_anchors[0] ?? null;
		if (anchor?.deep_link) return anchor.deep_link;
		if (!card.document_id) {
			return resolve('/collections/[id]/documents', { id: collectionId });
		}

		const href = resolve('/collections/[id]/documents/[document_id]', {
			id: collectionId,
			document_id: card.document_id
		});
		const params = new URLSearchParams();
		params.set('evidence_id', card.evidence_id);
		if (anchor?.anchor_id) params.set('anchor_id', anchor.anchor_id);
		return `${href}?${params.toString()}`;
	}

	function comparisonHref(card: EvidenceCard) {
		const href = resolve('/collections/[id]/comparisons', { id: collectionId });
		const location = getEvidenceSourceLocation(card);
		const params = new URLSearchParams();
		if (location.materials[0]) params.set('material_system_normalized', location.materials[0]);
		return params.toString() ? `${href}?${params.toString()}` : href;
	}

	function actionHref(action: EvidenceActionKey, card: EvidenceCard) {
		if (action === 'view_source') return documentHref(card);
		if (action === 'add_to_comparison' || action === 'view_comparison') return comparisonHref(card);
		return null;
	}

	function actionClass(action: EvidenceAction) {
		return `btn ${action.tone === 'primary' ? 'btn--primary' : 'btn--ghost'} btn--small evidence-action-button`;
	}

	function handlePendingAction(action: EvidenceAction) {
		actionStatus = $t('evidence.review.actionTodo', { action: $t(action.labelKey) });
	}

	function evidenceMetaRows(item: EvidenceCard) {
		const location = getEvidenceSourceLocation(item);
		const status = getComparabilityStatus(item);
		return [
			{
				icon: 'D',
				labelKey: 'evidence.card.sourceDocument',
				value: location.documentLabel,
				tone: 'neutral'
			},
			{
				icon: 'S',
				labelKey: 'evidence.card.sourceType',
				value: sourceTypeLabel(location.sourceType),
				tone: 'neutral'
			},
			{
				icon: 'L',
				labelKey: 'evidence.card.location',
				value: location.location,
				tone: 'neutral'
			},
			{
				icon: 'C',
				labelKey: 'evidence.card.comparability',
				value: comparabilityLabel(status),
				tone: status === 'joinable' || status === 'added' ? 'success' : 'warning'
			},
			{
				icon: 'M',
				labelKey: 'evidence.card.materials',
				value: formatList(location.materials),
				tone: 'neutral'
			},
			{
				icon: 'P',
				labelKey: 'evidence.card.parameters',
				value: formatList(location.parameters),
				tone: 'neutral'
			},
			{
				icon: 'T',
				labelKey: 'evidence.card.tags',
				value: formatList(location.tags),
				tone: 'neutral'
			}
		];
	}
</script>

<svelte:head>
	<title>{$t('evidence.review.title')}</title>
</svelte:head>

<section class="evidence-review-page fade-up">
	<header class="evidence-review-header">
		<div class="evidence-review-header__copy">
			<div class="evidence-title-row">
				<h2>{$t('evidence.review.title')}</h2>
				<span class="evidence-info-dot" aria-hidden="true">i</span>
			</div>
			<p>{$t('evidence.review.description')}</p>
			<div class="evidence-meta-row">
				<span class="evidence-meta">
					<span class="evidence-meta__icon evidence-meta__icon--count" aria-hidden="true"></span>
					{$t('evidence.review.count', { count: response?.total ?? evidenceItems.length })}
				</span>
				<span class={`status-badge status-badge--${surfaceStatusTone(surfaceState)}`}>
					{$t(`overview.surfaceStates.${surfaceState}`)}
				</span>
				<span class="evidence-meta">
					<span class="evidence-meta__icon evidence-meta__icon--time" aria-hidden="true"></span>
					{$t('evidence.review.updatedAt', { time: formatDate(updatedAt) })}
				</span>
			</div>
		</div>
		<button class="btn btn--ghost evidence-refresh-button" type="button" on:click={refreshEvidence}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('evidence.actions.refresh')}
		</button>
	</header>

	{#if hasBlockingError}
		<div class="evidence-alert evidence-alert--error" role="alert">
			<strong>{$t('evidence.review.error')}</strong>
			<span>{safeErrorText(error)}</span>
		</div>
	{:else if loading}
		<section class="evidence-skeleton" aria-busy="true" aria-live="polite">
			<div class="skeleton-card skeleton-card--wide"></div>
			<div class="evidence-summary-grid">
				{#each Array(5) as _, index (index)}
					<div class="skeleton-card skeleton-card--summary"></div>
				{/each}
			</div>
			<div class="skeleton-card skeleton-card--wide"></div>
			<div class="skeleton-card skeleton-card--evidence"></div>
			<div class="skeleton-card skeleton-card--evidence"></div>
		</section>
	{:else if showFallbackState}
		<article class="evidence-empty-card">
			<div class="evidence-empty-card__icon" aria-hidden="true">!</div>
			<h3>{stateCardTitle()}</h3>
			<p>{stateCardBody()}</p>
			<div class="evidence-empty-card__actions">
				<a class="btn btn--ghost" href={resolve('/collections/[id]', { id: collectionId })}>
					{$t('overview.goToWorkspace')}
				</a>
				<button class="btn btn--primary" type="button" on:click={refreshEvidence}>
					{$t('evidence.actions.refresh')}
				</button>
			</div>
		</article>
	{:else if !evidenceItems.length}
		<article class="evidence-empty-card">
			<div class="evidence-empty-card__icon" aria-hidden="true">E</div>
			<h3>{$t('evidence.empty.title')}</h3>
			<p>{$t('evidence.empty.description')}</p>
			<div class="evidence-empty-card__actions">
				<button
					class="btn btn--primary"
					type="button"
					disabled={actionLoading}
					on:click={startProcessing}
				>
					{actionLoading ? $t('evidence.review.processing') : $t('overview.startIndex')}
				</button>
				<button class="btn btn--ghost" type="button" on:click={refreshEvidence}>
					{$t('evidence.actions.refresh')}
				</button>
			</div>
			{#if actionStatus}
				<div class="evidence-alert" role="status">{actionStatus}</div>
			{/if}
		</article>
	{:else}
		<section class="evidence-summary-grid" aria-label={$t('evidence.review.summaryLabel')}>
			{#each qualitySummary as item (item.key)}
				<article class={`evidence-summary-card evidence-summary-card--${item.tone}`}>
					<div class="evidence-summary-card__icon" aria-hidden="true">{item.icon}</div>
					<div class="evidence-summary-card__copy">
						<span>{$t(item.labelKey)}</span>
						<strong>{item.value}</strong>
					</div>
					{#if item.percent !== null}
						<span class="evidence-summary-card__percent">{item.percent}%</span>
					{/if}
				</article>
			{/each}
		</section>

		<section class="evidence-filters-card" aria-label={$t('evidence.filters.title')}>
			<div class="evidence-filter-search-row">
				<label class="sr-only" for="evidence-search">{$t('evidence.filters.searchLabel')}</label>
				<div class="evidence-search-field">
					<span class="evidence-search-field__icon" aria-hidden="true"></span>
					<input
						id="evidence-search"
						type="search"
						bind:value={search}
						placeholder={$t('evidence.filters.searchPlaceholder')}
					/>
				</div>
				<button class="btn btn--ghost btn--small" type="button" on:click={clearFilters}>
					{$t('evidence.filters.clear')}
				</button>
			</div>

			<div class="evidence-filter-grid">
				<div class="field">
					<label for="evidence-type">{$t('evidence.filters.type')}</label>
					<select id="evidence-type" class="select" bind:value={typeFilter}>
						{#each TYPE_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="evidence-traceability">{$t('evidence.filters.traceability')}</label>
					<select id="evidence-traceability" class="select" bind:value={traceabilityFilter}>
						{#each TRACEABILITY_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="evidence-source">{$t('evidence.filters.source')}</label>
					<select id="evidence-source" class="select" bind:value={sourceFilter}>
						{#each SOURCE_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="evidence-confidence">{$t('evidence.filters.confidence')}</label>
					<select id="evidence-confidence" class="select" bind:value={confidenceFilter}>
						{#each CONFIDENCE_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="evidence-comparability">{$t('evidence.filters.comparability')}</label>
					<select id="evidence-comparability" class="select" bind:value={comparabilityFilter}>
						{#each COMPARABILITY_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
			</div>
		</section>

		{#if actionStatus}
			<div class="evidence-alert" role="status">{actionStatus}</div>
		{/if}

		<section class="evidence-list-section">
			<div class="evidence-list-header">
				<h3>{$t('evidence.list.count', { count: filteredItems.length })}</h3>
				<label class="evidence-sort-control">
					<span>{$t('evidence.sort.label')}</span>
					<select class="select" bind:value={sortMode}>
						{#each SORT_OPTIONS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</label>
			</div>

			{#if filteredItems.length}
				<div class="evidence-card-list">
					{#each filteredItems as item (item.evidence_id)}
						{@const typeBadge = getEvidenceTypeBadge(item.claim_type)}
						{@const traceabilityBadge = getTraceabilityBadge(item.traceability_status)}
						{@const quote = getEvidenceQuote(item)}
						{@const actions = getEvidenceActions(item)}
						<article class="evidence-review-card">
							<div class="evidence-card-top">
								<div
									class={`evidence-type-icon evidence-type-icon--${typeBadge.tone}`}
									aria-hidden="true"
								>
									{typeBadge.icon}
								</div>
								<div class="evidence-card-title-block">
									<h4>{cardTitle(item)}</h4>
									<div class="evidence-badge-row">
										<span class={`evidence-badge evidence-badge--${typeBadge.tone}`}>
											{typeBadge.label}
										</span>
										<span class={`evidence-badge evidence-badge--${traceabilityBadge.tone}`}>
											{badgeLabel(traceabilityBadge)}
										</span>
										<span
											class={`evidence-badge evidence-badge--confidence evidence-badge--${getConfidenceLevel(item.confidence)}`}
										>
											{$t('evidence.card.confidenceValue', {
												value: formatConfidence(item.confidence)
											})}
										</span>
									</div>
								</div>
								<details class="evidence-more-menu">
									<summary aria-label={$t('evidence.more.label')}>...</summary>
									<div class="evidence-more-menu__panel">
										{#each MORE_ACTIONS as labelKey (labelKey)}
											<button type="button" disabled>{$t(labelKey)}</button>
										{/each}
									</div>
								</details>
							</div>

							<div class="evidence-card-body">
								<div class="evidence-claim-column">
									<section class="evidence-card-section">
										<h5>{$t('evidence.card.extractedClaim')}</h5>
										<p class="evidence-claim-text">{item.claim_text || item.evidence_id}</p>
										<p class="evidence-claim-note">{$t('evidence.card.claimNote')}</p>
									</section>

									<section class="evidence-card-section">
										<h5>{$t('evidence.card.sourceEvidence')}</h5>
										<blockquote class="evidence-quote-block">
											<p>{quote.text}</p>
											{#if quote.citation}
												<cite>{quote.citation}</cite>
											{/if}
										</blockquote>
									</section>
								</div>

								<dl class="evidence-meta-list">
									{#each evidenceMetaRows(item) as row (row.labelKey)}
										<div class="evidence-meta-item">
											<dt>
												<span
													class={`evidence-meta-item__icon evidence-meta-item__icon--${row.tone}`}
													aria-hidden="true"
												>
													{row.icon}
												</span>
												{$t(row.labelKey)}
											</dt>
											<dd class:success-value={row.tone === 'success'}>{row.value}</dd>
										</div>
									{/each}
									<div class="evidence-meta-item">
										<dt>
											<span class="evidence-meta-item__icon" aria-hidden="true">Q</span>
											{$t('evidence.card.confidenceLevel')}
										</dt>
										<dd>{confidenceLevelLabel(item.confidence)}</dd>
									</div>
								</dl>

								<div class="evidence-actions-panel">
									{#each actions as action (action.key)}
										{@const href = actionHref(action.key, item)}
										{#if href}
											<a class={actionClass(action)} {href}>{$t(action.labelKey)}</a>
										{:else}
											<button
												class={actionClass(action)}
												type="button"
												on:click={() => handlePendingAction(action)}
											>
												{$t(action.labelKey)}
											</button>
										{/if}
									{/each}
								</div>
							</div>
						</article>
					{/each}
				</div>
			{:else}
				<div class="evidence-empty-filter" role="status">{$t('evidence.list.emptyFiltered')}</div>
			{/if}
		</section>
	{/if}
</section>

<style>
	.evidence-review-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 24px;
	}

	.evidence-review-header,
	.evidence-filters-card,
	.evidence-review-card,
	.evidence-list-section,
	.evidence-empty-card {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.evidence-review-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
		padding: 24px;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
	}

	.evidence-review-header__copy {
		min-width: 0;
		display: grid;
		gap: 10px;
	}

	.evidence-title-row {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.evidence-title-row h2 {
		margin: 0;
		color: var(--text-primary);
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
		letter-spacing: 0;
	}

	.evidence-info-dot {
		width: 22px;
		height: 22px;
		display: inline-grid;
		place-items: center;
		border: 1px solid var(--border-strong);
		border-radius: 999px;
		color: var(--text-secondary);
		font-size: 13px;
		font-weight: 700;
		line-height: 1;
	}

	.evidence-review-header p {
		max-width: 760px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 22px;
	}

	.evidence-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.evidence-meta {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.evidence-meta__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		color: var(--text-tertiary);
	}

	.evidence-meta__icon--count {
		border: 1.5px solid currentColor;
		border-radius: 3px;
	}

	.evidence-meta__icon--count::before,
	.evidence-meta__icon--count::after {
		content: '';
		position: absolute;
		left: 3px;
		right: 3px;
		height: 1.5px;
		background: currentColor;
	}

	.evidence-meta__icon--count::before {
		top: 4px;
	}

	.evidence-meta__icon--count::after {
		top: 8px;
	}

	.evidence-meta__icon--time {
		border: 1.5px solid currentColor;
		border-radius: 999px;
	}

	.evidence-meta__icon--time::before,
	.evidence-meta__icon--time::after {
		content: '';
		position: absolute;
		left: 6px;
		top: 3px;
		width: 1.5px;
		height: 4px;
		border-radius: 999px;
		background: currentColor;
	}

	.evidence-meta__icon--time::after {
		top: 6px;
		width: 4px;
		height: 1.5px;
	}

	.evidence-refresh-button {
		flex: 0 0 auto;
	}

	.evidence-summary-grid {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 16px;
	}

	.evidence-summary-card {
		min-width: 0;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 14px;
		padding: 18px 20px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.evidence-summary-card__icon {
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 13px;
		font-weight: 800;
	}

	.evidence-summary-card--success .evidence-summary-card__icon {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.evidence-summary-card--warning .evidence-summary-card__icon {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.evidence-summary-card--purple .evidence-summary-card__icon {
		background: #f3e8ff;
		color: #7c3aed;
	}

	.evidence-summary-card--danger .evidence-summary-card__icon {
		background: #ccfbf1;
		color: #0f766e;
	}

	.evidence-summary-card__copy {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.evidence-summary-card__copy span {
		color: var(--text-primary);
		font-size: 14px;
		font-weight: 600;
		line-height: 22px;
	}

	.evidence-summary-card__copy strong {
		color: var(--text-primary);
		font-size: 24px;
		font-weight: 700;
		line-height: 30px;
	}

	.evidence-summary-card__percent {
		color: #50658a;
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-filters-card {
		display: grid;
		gap: 14px;
		padding: 18px 20px;
	}

	.evidence-filter-search-row {
		display: grid;
		grid-template-columns: minmax(260px, 428px) auto;
		justify-content: space-between;
		gap: 12px;
	}

	.evidence-search-field {
		min-width: 0;
		height: 40px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 12px;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		background: #fff;
	}

	.evidence-search-field:focus-within {
		border-color: var(--brand-primary);
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.evidence-search-field__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		border: 1.8px solid var(--text-secondary);
		border-radius: 999px;
	}

	.evidence-search-field__icon::after {
		content: '';
		position: absolute;
		right: -5px;
		bottom: -3px;
		width: 6px;
		height: 2px;
		border-radius: 999px;
		background: var(--text-secondary);
		transform: rotate(45deg);
	}

	.evidence-search-field input {
		min-width: 0;
		width: 100%;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-search-field input::placeholder {
		color: var(--text-secondary);
	}

	.evidence-filter-grid {
		display: grid;
		grid-template-columns: repeat(5, minmax(150px, 1fr));
		gap: 16px;
	}

	.evidence-filter-grid .select,
	.evidence-sort-control .select {
		min-height: 40px;
		border-radius: var(--radius-md);
	}

	.evidence-alert {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		padding: 10px 12px;
		border: 1px solid var(--info-border);
		border-radius: var(--radius-md);
		background: var(--info-bg);
		color: var(--info-text);
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-alert--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.evidence-list-section {
		display: grid;
		gap: 14px;
		padding: 0;
		background: transparent;
		border: 0;
		box-shadow: none;
	}

	.evidence-list-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
	}

	.evidence-list-header h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 600;
		line-height: 24px;
	}

	.evidence-sort-control {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.evidence-sort-control .select {
		width: 190px;
	}

	.evidence-card-list {
		display: grid;
		gap: 16px;
	}

	.evidence-review-card {
		display: grid;
		gap: 16px;
		padding: 16px;
		border-radius: 16px;
	}

	.evidence-card-top {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: 12px;
	}

	.evidence-type-icon {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 9px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 14px;
		font-weight: 800;
		line-height: 1;
	}

	.evidence-type-icon--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.evidence-type-icon--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.evidence-type-icon--purple {
		background: #f3e8ff;
		color: #7c3aed;
	}

	.evidence-type-icon--neutral {
		background: var(--neutral-bg, #f1f5f9);
		color: var(--neutral-text, var(--text-secondary));
	}

	.evidence-card-title-block {
		min-width: 0;
		display: grid;
		gap: 7px;
	}

	.evidence-card-title-block h4 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
		letter-spacing: 0;
		word-break: break-word;
	}

	.evidence-badge-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}

	.evidence-badge {
		display: inline-flex;
		align-items: center;
		min-height: 24px;
		padding: 3px 9px;
		border-radius: 999px;
		background: var(--neutral-bg, #f1f5f9);
		color: var(--neutral-text, var(--text-secondary));
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		white-space: nowrap;
	}

	.evidence-badge--brand {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.evidence-badge--success,
	.evidence-badge--high {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.evidence-badge--warning,
	.evidence-badge--medium {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.evidence-badge--danger,
	.evidence-badge--low {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.evidence-badge--purple {
		background: #f3e8ff;
		color: #7c3aed;
	}

	.evidence-badge--unknown {
		background: var(--neutral-bg, #f1f5f9);
		color: var(--text-secondary);
	}

	.evidence-more-menu {
		position: relative;
	}

	.evidence-more-menu summary {
		width: 34px;
		height: 34px;
		display: inline-grid;
		place-items: center;
		border: 1px solid var(--border-strong);
		border-radius: 10px;
		background: #fff;
		color: var(--text-secondary);
		font-weight: 800;
		cursor: pointer;
		list-style: none;
	}

	.evidence-more-menu summary::-webkit-details-marker {
		display: none;
	}

	.evidence-more-menu__panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 20;
		width: 178px;
		display: grid;
		gap: 4px;
		padding: 6px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--surface-card);
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
	}

	.evidence-more-menu__panel button {
		min-height: 34px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-secondary);
		text-align: left;
		font-size: 13px;
		line-height: 20px;
	}

	.evidence-card-body {
		display: grid;
		grid-template-columns: minmax(320px, 1.2fr) minmax(260px, 0.8fr) minmax(140px, 170px);
		gap: 16px;
	}

	.evidence-claim-column {
		min-width: 0;
		display: grid;
		align-content: start;
		gap: 14px;
	}

	.evidence-card-section {
		display: grid;
		gap: 8px;
	}

	.evidence-card-section h5 {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
	}

	.evidence-claim-text {
		margin: 0;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-claim-note {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.evidence-quote-block {
		margin: 0;
		display: grid;
		gap: 6px;
		padding: 12px 14px;
		border-left: 3px solid var(--brand-primary);
		border-radius: 10px;
		background: #f8fafc;
	}

	.evidence-quote-block p {
		margin: 0;
		color: #334155;
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-quote-block cite {
		color: #475569;
		font-size: 13px;
		font-style: normal;
		line-height: 20px;
	}

	.evidence-meta-list {
		min-width: 0;
		display: grid;
		align-content: start;
		gap: 8px;
		margin: 0;
	}

	.evidence-meta-item {
		display: grid;
		grid-template-columns: 100px minmax(0, 1fr);
		align-items: start;
		gap: 10px;
		color: var(--text-primary);
		font-size: 13px;
		line-height: 20px;
	}

	.evidence-meta-item dt {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: var(--text-secondary);
		font-weight: 600;
	}

	.evidence-meta-item dd {
		margin: 0;
		word-break: break-word;
	}

	.evidence-meta-item dd.success-value {
		color: var(--success-text);
		font-weight: 700;
	}

	.evidence-meta-item__icon {
		width: 16px;
		height: 16px;
		display: inline-grid;
		place-items: center;
		flex: 0 0 auto;
		border-radius: 6px;
		background: var(--neutral-bg, #f1f5f9);
		color: var(--text-secondary);
		font-size: 10px;
		font-weight: 800;
		line-height: 1;
	}

	.evidence-meta-item__icon--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.evidence-meta-item__icon--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.evidence-actions-panel {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 10px;
	}

	.evidence-action-button {
		min-height: 38px;
		width: 100%;
		border-radius: 10px;
	}

	.evidence-empty-card {
		display: grid;
		justify-items: center;
		gap: 12px;
		padding: 34px 24px;
		text-align: center;
	}

	.evidence-empty-card h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.evidence-empty-card p {
		max-width: 620px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.evidence-empty-card__icon {
		width: 52px;
		height: 52px;
		display: grid;
		place-items: center;
		border-radius: 16px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.evidence-empty-card__actions {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.evidence-empty-filter {
		padding: 24px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		text-align: center;
	}

	.evidence-skeleton {
		display: grid;
		gap: 16px;
	}

	.skeleton-card {
		min-height: 150px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background:
			linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.68), transparent), #eef3f8;
		background-size:
			220px 100%,
			100% 100%;
		animation: evidence-skeleton 1.4s ease-in-out infinite;
	}

	.skeleton-card--wide {
		min-height: 104px;
	}

	.skeleton-card--summary {
		min-height: 82px;
	}

	.skeleton-card--evidence {
		min-height: 238px;
	}

	:root[data-theme='dark'] .evidence-review-header,
	:root[data-theme='dark'] .evidence-filters-card,
	:root[data-theme='dark'] .evidence-review-card,
	:root[data-theme='dark'] .evidence-empty-card,
	:root[data-theme='dark'] .evidence-summary-card,
	:root[data-theme='dark'] .evidence-empty-filter,
	:root[data-theme='dark'] .evidence-more-menu__panel {
		background: rgba(16, 26, 44, 0.88);
	}

	:root[data-theme='dark'] .evidence-search-field,
	:root[data-theme='dark'] .evidence-more-menu summary {
		background: rgba(12, 20, 34, 0.8);
	}

	:root[data-theme='dark'] .evidence-quote-block {
		background: rgba(120, 140, 180, 0.12);
	}

	:root[data-theme='dark'] .evidence-quote-block p,
	:root[data-theme='dark'] .evidence-quote-block cite {
		color: var(--text-secondary);
	}

	@keyframes evidence-skeleton {
		from {
			background-position:
				-220px 0,
				0 0;
		}
		to {
			background-position:
				calc(100% + 220px) 0,
				0 0;
		}
	}

	@media (max-width: 1180px) {
		.evidence-summary-grid {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}

		.evidence-filter-grid {
			grid-template-columns: repeat(3, minmax(160px, 1fr));
		}

		.evidence-card-body {
			grid-template-columns: minmax(0, 1fr) minmax(240px, 0.85fr);
		}

		.evidence-actions-panel {
			grid-column: 1 / -1;
			flex-direction: row;
			flex-wrap: wrap;
		}

		.evidence-action-button {
			width: auto;
		}
	}

	@media (max-width: 820px) {
		.evidence-review-header,
		.evidence-filter-search-row,
		.evidence-list-header {
			display: grid;
			grid-template-columns: 1fr;
		}

		.evidence-summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.evidence-filter-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.evidence-card-body {
			grid-template-columns: 1fr;
		}

		.evidence-sort-control {
			justify-content: space-between;
		}

		.evidence-sort-control .select {
			width: min(100%, 220px);
		}
	}

	@media (max-width: 560px) {
		.evidence-review-header,
		.evidence-filters-card,
		.evidence-review-card,
		.evidence-empty-card {
			padding: 18px;
		}

		.evidence-title-row h2 {
			font-size: 28px;
			line-height: 36px;
		}

		.evidence-summary-grid,
		.evidence-filter-grid {
			grid-template-columns: 1fr;
		}

		.evidence-summary-card {
			padding: 16px;
		}

		.evidence-card-top {
			grid-template-columns: auto minmax(0, 1fr);
		}

		.evidence-more-menu {
			grid-column: 1 / -1;
			justify-self: start;
		}

		.evidence-meta-item {
			grid-template-columns: 1fr;
			gap: 4px;
		}

		.evidence-actions-panel {
			flex-direction: column;
		}

		.evidence-action-button {
			width: 100%;
		}
	}
</style>
