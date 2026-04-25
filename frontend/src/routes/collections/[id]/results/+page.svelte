<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		buildResultsConclusion,
		buildResultsQualitySummary,
		fetchCollectionResults,
		filterResults,
		formatDocumentTitle,
		formatResultValue,
		getMissingContextChips,
		getResultActions,
		getResultConfidence,
		getResultContext,
		getResultStatusBadges,
		getSourceEvidenceQuote,
		sortResults,
		type ResultAction,
		type ResultAvailabilityStatus,
		type ResultFilters,
		type ResultListItem,
		type ResultListResponse,
		type ResultSortMode,
		type ResultSpecifiedFilter,
		type ResultTraceabilityStatus,
		type ResultValueLabels,
		type ResultsConclusionActionKey
	} from '../../../_shared/results';
	import { createBuildTask } from '../../../_shared/tasks';
	import { buildDocumentViewerHref } from '../../../_shared/traceback';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview,
		type WorkspaceSurfaceState
	} from '../../../_shared/workspace';

	type ViewMode = 'card' | 'table';

	type FilterOption<T extends string> = {
		value: T;
		labelKey: string;
	};

	const AVAILABILITY_FILTERS: FilterOption<'' | ResultAvailabilityStatus>[] = [
		{ value: '', labelKey: 'results.filters.all' },
		{ value: 'comparable', labelKey: 'results.status.comparable' },
		{ value: 'limited', labelKey: 'results.status.limited' },
		{ value: 'insufficient', labelKey: 'results.status.insufficient' },
		{ value: 'unavailable', labelKey: 'results.status.unavailable' }
	];

	const SPECIFIED_FILTERS: FilterOption<ResultSpecifiedFilter>[] = [
		{ value: '', labelKey: 'results.filters.all' },
		{ value: 'specified', labelKey: 'results.filters.specified' },
		{ value: 'unspecified', labelKey: 'results.filters.unspecified' }
	];

	const TRACEABILITY_FILTERS: FilterOption<'' | ResultTraceabilityStatus>[] = [
		{ value: '', labelKey: 'results.filters.all' },
		{ value: 'direct', labelKey: 'results.traceability.direct' },
		{ value: 'indirect', labelKey: 'results.traceability.indirect' },
		{ value: 'none', labelKey: 'results.traceability.none' }
	];

	const SORT_OPTIONS: FilterOption<ResultSortMode>[] = [
		{ value: 'confidence_desc', labelKey: 'results.sort.confidenceDesc' },
		{ value: 'context_completeness', labelKey: 'results.sort.contextCompleteness' },
		{ value: 'traceability', labelKey: 'results.sort.traceability' },
		{ value: 'recent', labelKey: 'results.sort.recent' }
	];

	const MORE_ACTIONS = [
		'results.more.copyResult',
		'results.more.openDetail',
		'results.more.markReviewed',
		'results.more.reanalyze'
	];

	$: collectionId = $page.params.id ?? '';

	let response: ResultListResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let actionStatus = '';
	let actionLoading = false;
	let loadedCollectionId = '';
	let notFound = false;
	let syncedRouteMaterial = '';

	let search = '';
	let availabilityFilter: '' | ResultAvailabilityStatus = '';
	let materialFilter = '';
	let propertyFilter = '';
	let testConditionFilter: ResultSpecifiedFilter = '';
	let traceabilityFilter: '' | ResultTraceabilityStatus = '';
	let sortMode: ResultSortMode = 'confidence_desc';
	let viewMode: ViewMode = 'card';

	function uniqueSorted(values: string[]) {
		return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort((a, b) =>
			a.localeCompare(b)
		);
	}

	$: routeMaterialFilter = $page.url.searchParams.get('material_system_normalized')?.trim() ?? '';
	$: valueLabels = {
		material: $t('results.values.unspecifiedMaterialSystem'),
		process: $t('results.values.unspecifiedProcess'),
		baseline: $t('results.values.unspecifiedBaseline'),
		test_condition: $t('results.values.unspecifiedTestCondition'),
		generic: $t('results.values.unspecified')
	} satisfies ResultValueLabels;
	$: if (routeMaterialFilter !== syncedRouteMaterial) {
		materialFilter = routeMaterialFilter
			? formatResultValue(routeMaterialFilter, 'material', valueLabels)
			: '';
		syncedRouteMaterial = routeMaterialFilter;
	}

	$: resultItems = response?.items ?? [];
	$: resultFilters = {
		search,
		availability: availabilityFilter,
		material: materialFilter,
		property: propertyFilter,
		testCondition: testConditionFilter,
		traceability: traceabilityFilter
	} satisfies ResultFilters;
	$: filteredItems = sortResults(
		filterResults(resultItems, resultFilters, valueLabels),
		sortMode,
		valueLabels
	);
	$: qualitySummary = buildResultsQualitySummary(resultItems);
	$: conclusion = buildResultsConclusion(qualitySummary);
	$: materials = uniqueSorted(
		resultItems.map((item) => getResultContext(item, valueLabels).materialSystem)
	);
	$: properties = uniqueSorted(
		resultItems.map((item) => getResultContext(item, valueLabels).property)
	);
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'results');
	$: updatedAt = workspace?.collection.updated_at || workspace?.artifacts.updated_at || '';
	$: showFallbackState =
		Boolean(workspace) &&
		!loading &&
		resultItems.length < 1 &&
		(surfaceState !== 'ready' || notFound);
	$: hasBlockingError = Boolean(error) && !showFallbackState;
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadResults();
	}

	async function loadResults() {
		loading = true;
		error = '';
		actionStatus = '';
		notFound = false;

		const [resultsResult, workspaceResult] = await Promise.allSettled([
			fetchCollectionResults(collectionId, { limit: 500 }),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		if (resultsResult.status === 'fulfilled') {
			response = resultsResult.value;
			loading = false;
			return;
		}

		response = null;
		notFound = isHttpStatusError(resultsResult.reason, 404);
		error = errorMessage(resultsResult.reason);
		loading = false;
	}

	async function startProcessing() {
		actionLoading = true;
		actionStatus = '';
		try {
			await createBuildTask(collectionId);
			actionStatus = $t('documents.indexing');
			await loadResults();
		} catch (err) {
			actionStatus = safeErrorText(errorMessage(err));
		} finally {
			actionLoading = false;
		}
	}

	async function updateMaterialRoute(value: string) {
		const params = new URLSearchParams($page.url.searchParams);
		if (value) {
			params.set('material_system_normalized', value);
		} else {
			params.delete('material_system_normalized');
		}
		const query = params.toString();
		await goto(query ? `${$page.url.pathname}?${query}` : $page.url.pathname, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
	}

	function clearFilters() {
		search = '';
		availabilityFilter = '';
		materialFilter = '';
		propertyFilter = '';
		testConditionFilter = '';
		traceabilityFilter = '';
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

	function safeErrorText(value: string) {
		const firstLine = value.split('\n')[0]?.trim() ?? '';
		if (!firstLine) return $t('error.unexpected');
		return firstLine.length > 180 ? `${firstLine.slice(0, 180)}...` : firstLine;
	}

	function badgeLabel(
		badge: { key: string; labelKey: string; fallbackLabel: string },
		item: ResultListItem
	) {
		const label =
			badge.key === 'confidence'
				? $t(badge.labelKey, { value: `${getResultConfidence(item)}%` })
				: $t(badge.labelKey);
		return label === badge.labelKey ? badge.fallbackLabel : label;
	}

	function resultTitle(item: ResultListItem) {
		return formatResultValue(item.property, 'property', valueLabels);
	}

	function extractedResult(item: ResultListItem) {
		const summary = item.summary.trim();
		if (!summary || summary === '--' || summary === item.property) {
			return resultTitle(item);
		}
		return formatResultValue(summary, 'result', valueLabels);
	}

	function resultHref(item: ResultListItem) {
		return `/collections/${collectionId}/results/${encodeURIComponent(item.result_id)}`;
	}

	function sourceHref(item: ResultListItem) {
		if (!item.document_id) return null;
		const evidenceId = item.evidence_ids[0] ?? null;
		if (evidenceId) {
			return buildDocumentViewerHref(collectionId, item.document_id, {
				evidenceId,
				returnTo: `${$page.url.pathname}${$page.url.search}`
			});
		}
		const params = new URLSearchParams({
			result_id: item.result_id,
			return_to: `${$page.url.pathname}${$page.url.search}`
		});
		return `/collections/${collectionId}/documents/${encodeURIComponent(item.document_id)}?${params.toString()}`;
	}

	function comparisonHref(item: ResultListItem) {
		const params = new URLSearchParams();
		for (const [key, value] of Object.entries({
			material_system_normalized: item.material_label,
			property_normalized: item.property,
			baseline_normalized: item.baseline ?? '',
			test_condition_normalized: item.test_condition ?? ''
		})) {
			if (value && value.trim() && value !== '--') params.set(key, value);
		}
		const query = params.toString();
		return query
			? `/collections/${collectionId}/comparisons?${query}`
			: `/collections/${collectionId}/comparisons`;
	}

	function actionHref(action: ResultAction, item: ResultListItem) {
		if (action.key === 'view_source') return sourceHref(item);
		if (action.key === 'open_comparison' || action.key === 'open_comparison_review') {
			return comparisonHref(item);
		}
		if (action.key === 'view_missing_context' || action.key === 'view_reason') {
			return resultHref(item);
		}
		return null;
	}

	function actionClass(action: ResultAction) {
		const toneClass =
			action.tone === 'primary'
				? 'btn--primary'
				: action.tone === 'danger'
					? 'btn--danger'
					: 'btn--ghost';
		return `btn ${toneClass} btn--small results-action-button`;
	}

	function handlePendingAction(action: ResultAction, item: ResultListItem) {
		if (action.key === 'mark_issue') {
			actionStatus = $t('results.review.actionTodo', {
				action: $t(action.labelKey),
				result: resultTitle(item)
			});
		}
	}

	function conclusionActionLabel(actionKey: ResultsConclusionActionKey) {
		return $t(`results.conclusionActions.${actionKey}`);
	}

	async function handleConclusionAction(actionKey: ResultsConclusionActionKey) {
		if (actionKey === 'view_insufficient') {
			availabilityFilter = 'insufficient';
			return;
		}
		if (actionKey === 'open_comparison') {
			await goto(`/collections/${collectionId}/comparisons`);
			return;
		}
		clearFilters();
	}
</script>

<svelte:head>
	<title>{$t('results.title')}</title>
</svelte:head>

<section class="results-page fade-up">
	<header class="results-header">
		<div class="results-header__copy">
			<h2>{$t('results.title')}</h2>
			<p>{$t('results.description')}</p>
			<div class="results-meta-row">
				<span class="results-meta">
					<span class="results-meta__icon results-meta__icon--count" aria-hidden="true"></span>
					{$t('results.review.count', { count: response?.total ?? resultItems.length })}
				</span>
				<span class={`status-badge status-badge--${surfaceStatusTone(surfaceState)}`}>
					{$t(`overview.surfaceStates.${surfaceState}`)}
				</span>
				<span class="results-meta">
					<span class="results-meta__icon results-meta__icon--time" aria-hidden="true"></span>
					{$t('results.review.updatedAt', { time: formatDate(updatedAt) })}
				</span>
			</div>
		</div>
		<button class="btn btn--ghost results-refresh-button" type="button" on:click={loadResults}>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('results.actions.refresh')}
		</button>
	</header>

	{#if hasBlockingError}
		<div class="results-alert results-alert--error" role="alert">
			<strong>{$t('results.review.error')}</strong>
			<span>{safeErrorText(error)}</span>
		</div>
	{:else if loading}
		<section class="results-skeleton" aria-busy="true" aria-live="polite">
			<div class="results-skeleton-card results-skeleton-card--summary-grid"></div>
			<div class="results-skeleton-card results-skeleton-card--wide"></div>
			<div class="results-skeleton-card results-skeleton-card--filters"></div>
			<div class="results-skeleton-card results-skeleton-card--result"></div>
			<div class="results-skeleton-card results-skeleton-card--result"></div>
		</section>
	{:else if showFallbackState}
		<article class="results-empty-card">
			<div class="results-empty-card__icon" aria-hidden="true">!</div>
			<h3>{stateCardTitle()}</h3>
			<p>{stateCardBody()}</p>
			<div class="results-empty-card__actions">
				<a class="btn btn--ghost" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
				<button class="btn btn--primary" type="button" on:click={loadResults}>
					{$t('results.actions.refreshStatus')}
				</button>
			</div>
		</article>
	{:else if !resultItems.length}
		<article class="results-empty-card">
			<div class="results-empty-card__icon" aria-hidden="true">R</div>
			<h3>{$t('results.empty.title')}</h3>
			<p>{$t('results.empty.description')}</p>
			<div class="results-empty-card__actions">
				<button
					class="btn btn--primary"
					type="button"
					disabled={actionLoading}
					on:click={startProcessing}
				>
					{actionLoading ? $t('results.review.processing') : $t('results.empty.startProcessing')}
				</button>
				<button class="btn btn--ghost" type="button" on:click={loadResults}>
					{$t('results.empty.refreshStatus')}
				</button>
			</div>
			{#if actionStatus}
				<div class="results-alert" role="status">{actionStatus}</div>
			{/if}
		</article>
	{:else}
		<section class="results-summary-grid" aria-label={$t('results.summary.label')}>
			{#each qualitySummary.items as item (item.key)}
				<article class={`results-summary-card results-summary-card--${item.tone}`}>
					<div class="results-summary-card__icon" aria-hidden="true">{item.icon}</div>
					<div class="results-summary-card__copy">
						<span>{$t(item.labelKey)}</span>
						<strong>{item.value}</strong>
					</div>
				</article>
			{/each}
		</section>

		<section class={`results-conclusion results-conclusion--${conclusion.tone}`}>
			<div class="results-conclusion__icon" aria-hidden="true">
				{conclusion.tone === 'success' ? 'OK' : '!'}
			</div>
			<div class="results-conclusion__copy">
				<h3>{$t(conclusion.titleKey)}</h3>
				<p>{$t(conclusion.bodyKey)}</p>
			</div>
			<div class="results-conclusion__actions">
				{#each conclusion.actionKeys as actionKey (actionKey)}
					<button
						class={actionKey === 'open_comparison'
							? 'btn btn--primary btn--small'
							: 'btn btn--ghost btn--small'}
						type="button"
						on:click={() => void handleConclusionAction(actionKey)}
					>
						{conclusionActionLabel(actionKey)}
					</button>
				{/each}
			</div>
		</section>

		<section class="results-filters-card" aria-label={$t('results.filters.title')}>
			<div class="results-filter-search-row">
				<label class="sr-only" for="results-search">{$t('results.filters.search')}</label>
				<div class="results-search-field">
					<span class="results-search-field__icon" aria-hidden="true"></span>
					<input
						id="results-search"
						type="search"
						bind:value={search}
						placeholder={$t('results.filters.searchPlaceholder')}
					/>
				</div>
				<div class="results-view-switch" aria-label={$t('results.view.label')}>
					<button
						type="button"
						class:active={viewMode === 'card'}
						aria-pressed={viewMode === 'card'}
						on:click={() => (viewMode = 'card')}
					>
						<span class="results-view-grid-icon" aria-hidden="true"></span>
						{$t('results.view.card')}
					</button>
					<button
						type="button"
						class:active={viewMode === 'table'}
						aria-pressed={viewMode === 'table'}
						on:click={() => (viewMode = 'table')}
					>
						<span class="results-view-table-icon" aria-hidden="true"></span>
						{$t('results.view.table')}
					</button>
				</div>
			</div>

			<div class="results-filter-grid">
				<div class="field">
					<label for="results-availability">{$t('results.filters.availability')}</label>
					<select id="results-availability" class="select" bind:value={availabilityFilter}>
						{#each AVAILABILITY_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="results-material">{$t('results.filters.material')}</label>
					<select
						id="results-material"
						class="select"
						bind:value={materialFilter}
						on:change={(event) =>
							void updateMaterialRoute((event.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">{$t('results.filters.all')}</option>
						{#each materials as item (item)}
							<option value={item}>{item}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="results-property">{$t('results.filters.property')}</label>
					<select id="results-property" class="select" bind:value={propertyFilter}>
						<option value="">{$t('results.filters.all')}</option>
						{#each properties as item (item)}
							<option value={item}>{item}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="results-test-condition">{$t('results.filters.testCondition')}</label>
					<select id="results-test-condition" class="select" bind:value={testConditionFilter}>
						{#each SPECIFIED_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="results-traceability">{$t('results.filters.traceability')}</label>
					<select id="results-traceability" class="select" bind:value={traceabilityFilter}>
						{#each TRACEABILITY_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
			</div>

			<div class="results-filter-footer">
				<button class="btn btn--ghost btn--small" type="button" on:click={clearFilters}>
					{$t('results.filters.clear')}
				</button>
			</div>
		</section>

		{#if actionStatus}
			<div class="results-alert" role="status">{actionStatus}</div>
		{/if}

		<section class="results-list-section">
			<div class="results-list-header">
				<h3>{$t('results.list.count', { count: filteredItems.length })}</h3>
				<label class="results-sort-control">
					<span>{$t('results.sort.label')}</span>
					<select class="select" bind:value={sortMode}>
						{#each SORT_OPTIONS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</label>
			</div>

			{#if filteredItems.length}
				{#if viewMode === 'card'}
					<div class="results-card-list">
						{#each filteredItems as item, index (item.result_id)}
							{@const badges = getResultStatusBadges(item)}
							{@const context = getResultContext(item, valueLabels)}
							{@const missingChips = getMissingContextChips(item)}
							{@const quote = getSourceEvidenceQuote(item)}
							{@const actions = getResultActions(item)}
							<article class="results-card">
								<div class="results-card-top">
									<div
										class={`results-type-icon results-type-icon--${badges[0].tone}`}
										aria-hidden="true"
									>
										{index + 1}
									</div>
									<div class="results-card-title-block">
										<h4>{resultTitle(item)}</h4>
										<div class="results-badge-row">
											{#each badges as badge (badge.key)}
												<span class={`results-badge results-badge--${badge.tone}`}>
													{badgeLabel(badge, item)}
												</span>
											{/each}
										</div>
									</div>
									<details class="results-more-menu">
										<summary aria-label={$t('results.more.label')}>...</summary>
										<div class="results-more-menu__panel">
											{#each MORE_ACTIONS as labelKey (labelKey)}
												<button type="button" disabled>{$t(labelKey)}</button>
											{/each}
										</div>
									</details>
								</div>

								<div class="results-card-body">
									<section class="results-evidence-column">
										<div class="results-card-section">
											<h5>{$t('results.card.extractedResult')}</h5>
											<p class="results-result-text">{extractedResult(item)}</p>
											<p class="results-result-note">{$t('results.card.resultNote')}</p>
										</div>

										<div class="results-card-section">
											<h5>{$t('results.card.sourceEvidence')}</h5>
											<blockquote class="results-quote-block">
												<p>{quote.text}</p>
												{#if quote.citation}
													<cite>{$t('results.card.sourcePrefix')}: {quote.citation}</cite>
												{/if}
											</blockquote>
										</div>
									</section>

									<div class="results-context-column">
										<section class="results-card-section">
											<h5>{$t('results.card.context')}</h5>
											<dl class="results-context-grid">
												<div>
													<dt>{$t('results.card.materialSystem')}</dt>
													<dd>{context.materialSystem}</dd>
												</div>
												<div>
													<dt>{$t('results.card.property')}</dt>
													<dd>{context.property}</dd>
												</div>
												<div>
													<dt>{$t('results.card.process')}</dt>
													<dd>{context.process}</dd>
												</div>
												<div>
													<dt>{$t('results.card.baseline')}</dt>
													<dd>{context.baseline}</dd>
												</div>
												<div>
													<dt>{$t('results.card.testCondition')}</dt>
													<dd>{context.testCondition}</dd>
												</div>
											</dl>
										</section>

										<section class="results-card-section">
											<h5>{$t('results.card.missingContext')}</h5>
											{#if missingChips.length}
												<div class="results-chip-row">
													{#each missingChips as chip (chip.key)}
														<span class={`results-chip results-chip--${chip.tone}`}>
															{$t(chip.labelKey)}
														</span>
													{/each}
												</div>
											{:else}
												<p class="results-muted-text">{$t('results.card.noMissingContext')}</p>
											{/if}
										</section>
									</div>

									<div class="results-actions-panel">
										{#each actions as action (action.key)}
											{@const href = actionHref(action, item)}
											{#if href}
												<a class={actionClass(action)} {href}>{$t(action.labelKey)}</a>
											{:else}
												<button
													class={actionClass(action)}
													type="button"
													on:click={() => handlePendingAction(action, item)}
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
					<div class="results-table-wrapper">
						<table class="results-table">
							<thead>
								<tr>
									<th>{$t('results.table.result')}</th>
									<th>{$t('results.table.availability')}</th>
									<th>{$t('results.table.traceability')}</th>
									<th>{$t('results.table.material')}</th>
									<th>{$t('results.table.property')}</th>
									<th>{$t('results.table.testCondition')}</th>
									<th>{$t('results.table.document')}</th>
									<th>{$t('results.table.actions')}</th>
								</tr>
							</thead>
							<tbody>
								{#each filteredItems as item (item.result_id)}
									{@const badges = getResultStatusBadges(item)}
									{@const statusBadge = badges[0]}
									{@const traceabilityBadge = badges[1]}
									{@const context = getResultContext(item, valueLabels)}
									{@const actions = getResultActions(item)}
									<tr>
										<td>
											<div class="results-table-result" title={extractedResult(item)}>
												<strong>{resultTitle(item)}</strong>
												<p>{extractedResult(item)}</p>
											</div>
										</td>
										<td>
											<span class={`results-badge results-badge--${statusBadge.tone}`}>
												{badgeLabel(statusBadge, item)}
											</span>
										</td>
										<td>
											<span class={`results-badge results-badge--${traceabilityBadge.tone}`}>
												{badgeLabel(traceabilityBadge, item)}
											</span>
										</td>
										<td>{context.materialSystem}</td>
										<td>{context.property}</td>
										<td>{context.testCondition}</td>
										<td>
											<span title={formatDocumentTitle(item.document_id, item.document_title)}>
												{formatDocumentTitle(item.document_id, item.document_title)}
											</span>
										</td>
										<td>
											<div class="results-table-actions">
												{#each actions.slice(0, 2) as action (action.key)}
													{@const href = actionHref(action, item)}
													{#if href}
														<a class={actionClass(action)} {href}>{$t(action.labelKey)}</a>
													{:else}
														<button
															class={actionClass(action)}
															type="button"
															on:click={() => handlePendingAction(action, item)}
														>
															{$t(action.labelKey)}
														</button>
													{/if}
												{/each}
											</div>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			{:else}
				<div class="results-empty-filter" role="status">{$t('results.list.emptyFiltered')}</div>
			{/if}
		</section>
	{/if}
</section>

<style>
	.results-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 24px;
	}

	.results-header,
	.results-filters-card,
	.results-card,
	.results-empty-card,
	.results-summary-card {
		border: 1px solid var(--border-default);
		border-radius: 16px;
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.results-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
		padding: 24px;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
	}

	.results-header__copy {
		min-width: 0;
		display: grid;
		gap: 10px;
	}

	.results-header h2 {
		margin: 0;
		color: var(--text-primary);
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
		letter-spacing: 0;
	}

	.results-header p {
		max-width: 820px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 22px;
	}

	.results-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.results-meta {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.results-meta__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		color: var(--text-tertiary);
	}

	.results-meta__icon--count {
		border: 1.5px solid currentColor;
		border-radius: 3px;
	}

	.results-meta__icon--count::before,
	.results-meta__icon--count::after {
		content: '';
		position: absolute;
		left: 3px;
		right: 3px;
		height: 1.5px;
		background: currentColor;
	}

	.results-meta__icon--count::before {
		top: 4px;
	}

	.results-meta__icon--count::after {
		top: 8px;
	}

	.results-meta__icon--time {
		border: 1.5px solid currentColor;
		border-radius: 999px;
	}

	.results-meta__icon--time::before,
	.results-meta__icon--time::after {
		content: '';
		position: absolute;
		left: 6px;
		top: 3px;
		width: 1.5px;
		height: 4px;
		border-radius: 999px;
		background: currentColor;
	}

	.results-meta__icon--time::after {
		top: 6px;
		width: 4px;
		height: 1.5px;
	}

	.results-refresh-button {
		flex: 0 0 auto;
	}

	.results-summary-grid {
		display: grid;
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 16px;
	}

	.results-summary-card {
		min-width: 0;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		align-items: center;
		gap: 14px;
		padding: 18px 20px;
	}

	.results-summary-card__icon {
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 12px;
		font-weight: 800;
		line-height: 1;
	}

	.results-summary-card--success .results-summary-card__icon {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.results-summary-card--warning .results-summary-card__icon {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.results-summary-card--danger .results-summary-card__icon {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.results-summary-card--info .results-summary-card__icon {
		background: #f3e8ff;
		color: #7e22ce;
	}

	.results-summary-card__copy {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.results-summary-card__copy span {
		color: var(--text-primary);
		font-size: 14px;
		font-weight: 600;
		line-height: 22px;
	}

	.results-summary-card__copy strong {
		color: var(--text-primary);
		font-size: 24px;
		font-weight: 700;
		line-height: 30px;
	}

	.results-conclusion {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 18px;
		padding: 20px 24px;
		border: 1px solid #fde68a;
		border-radius: 16px;
		background: #fffbeb;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.results-conclusion--success {
		border-color: #bbf7d0;
		background: #f0fdf4;
	}

	.results-conclusion--info {
		border-color: #bfdbfe;
		background: #eff6ff;
	}

	.results-conclusion__icon {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 12px;
		font-weight: 800;
	}

	.results-conclusion--success .results-conclusion__icon {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.results-conclusion--info .results-conclusion__icon {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.results-conclusion__copy {
		min-width: 0;
		display: grid;
		gap: 6px;
	}

	.results-conclusion h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.results-conclusion p {
		margin: 0;
		color: #5f4b1b;
		font-size: 14px;
		line-height: 22px;
	}

	.results-conclusion--success p,
	.results-conclusion--info p {
		color: var(--text-secondary);
	}

	.results-conclusion__actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 10px;
	}

	.results-filters-card {
		display: grid;
		gap: 14px;
		padding: 18px 20px;
	}

	.results-filter-search-row {
		display: grid;
		grid-template-columns: minmax(260px, 420px) auto;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.results-search-field {
		min-width: 0;
		height: 40px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 12px;
		border: 1px solid var(--border-strong);
		border-radius: 12px;
		background: #fff;
	}

	.results-search-field:focus-within {
		border-color: var(--brand-primary);
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.results-search-field__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		border: 1.8px solid var(--text-secondary);
		border-radius: 999px;
	}

	.results-search-field__icon::after {
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

	.results-search-field input {
		min-width: 0;
		width: 100%;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.results-search-field input::placeholder {
		color: var(--text-secondary);
	}

	.results-view-switch {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px;
		border: 1px solid var(--border-default);
		border-radius: 12px;
		background: #f8fafc;
	}

	.results-view-switch button {
		min-height: 32px;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 0 12px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--text-secondary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		cursor: pointer;
	}

	.results-view-switch button.active {
		background: var(--brand-soft);
		color: var(--brand-primary);
		box-shadow: var(--shadow-xs);
	}

	.results-view-grid-icon,
	.results-view-table-icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
	}

	.results-view-grid-icon {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 2px;
	}

	.results-view-grid-icon::before,
	.results-view-grid-icon::after,
	.results-view-table-icon::before,
	.results-view-table-icon::after {
		content: '';
		display: block;
	}

	.results-view-grid-icon::before,
	.results-view-grid-icon::after {
		width: 6px;
		height: 6px;
		border: 1.5px solid currentColor;
		border-radius: 2px;
		box-shadow: 8px 0 0 -1.5px currentColor;
	}

	.results-view-table-icon::before,
	.results-view-table-icon::after {
		position: absolute;
		left: 0;
		right: 0;
		height: 2px;
		border-radius: 999px;
		background: currentColor;
		box-shadow:
			0 5px 0 currentColor,
			0 10px 0 currentColor;
	}

	.results-view-table-icon::after {
		left: 5px;
	}

	.results-filter-grid {
		display: grid;
		grid-template-columns: repeat(5, minmax(150px, 1fr));
		gap: 16px;
	}

	.results-filter-grid .select,
	.results-sort-control .select {
		min-height: 40px;
		border-radius: 12px;
	}

	.results-filter-footer {
		display: flex;
		justify-content: flex-end;
	}

	.results-alert {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		padding: 10px 12px;
		border: 1px solid var(--info-border);
		border-radius: 12px;
		background: var(--info-bg);
		color: var(--info-text);
		font-size: 14px;
		line-height: 22px;
	}

	.results-alert--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.results-list-section {
		display: grid;
		gap: 14px;
	}

	.results-list-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
	}

	.results-list-header h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 600;
		line-height: 24px;
	}

	.results-sort-control {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.results-sort-control .select {
		width: 210px;
	}

	.results-card-list {
		display: grid;
		gap: 16px;
	}

	.results-card {
		display: grid;
		gap: 16px;
		padding: 16px;
	}

	.results-card-top {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: 12px;
	}

	.results-type-icon {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 13px;
		font-weight: 800;
		line-height: 1;
	}

	.results-type-icon--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.results-type-icon--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.results-type-icon--danger {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.results-card-title-block {
		min-width: 0;
		display: grid;
		gap: 7px;
	}

	.results-card-title-block h4 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
		letter-spacing: 0;
		word-break: break-word;
	}

	.results-badge-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}

	.results-badge,
	.results-chip {
		display: inline-flex;
		align-items: center;
		min-height: 24px;
		padding: 3px 9px;
		border-radius: 999px;
		background: #f1f5f9;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
		white-space: nowrap;
	}

	.results-badge--brand,
	.results-badge--info {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.results-badge--success,
	.results-chip--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.results-badge--warning,
	.results-chip--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.results-badge--danger {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.results-more-menu {
		position: relative;
	}

	.results-more-menu summary {
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

	.results-more-menu summary::-webkit-details-marker {
		display: none;
	}

	.results-more-menu__panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 20;
		width: 178px;
		display: grid;
		gap: 4px;
		padding: 6px;
		border: 1px solid var(--border-default);
		border-radius: 12px;
		background: var(--surface-card);
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
	}

	.results-more-menu__panel button {
		min-height: 34px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-secondary);
		text-align: left;
		font-size: 13px;
		line-height: 20px;
	}

	.results-card-body {
		display: grid;
		grid-template-columns: minmax(280px, 1.3fr) minmax(280px, 1fr) minmax(150px, 180px);
		gap: 16px;
	}

	.results-evidence-column,
	.results-context-column {
		min-width: 0;
		display: grid;
		align-content: start;
		gap: 14px;
	}

	.results-card-section {
		display: grid;
		gap: 8px;
	}

	.results-card-section h5 {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
	}

	.results-result-text,
	.results-muted-text {
		margin: 0;
		font-size: 14px;
		line-height: 22px;
	}

	.results-result-text {
		color: var(--text-primary);
	}

	.results-result-note,
	.results-muted-text {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.results-quote-block {
		display: grid;
		gap: 8px;
		margin: 0;
		padding: 12px 14px;
		border: 1px solid var(--border-default);
		border-left: 3px solid var(--brand-primary);
		border-radius: 10px;
		background: #f8fafc;
	}

	.results-quote-block p {
		margin: 0;
		color: #334155;
		font-size: 14px;
		font-style: italic;
		line-height: 22px;
	}

	.results-quote-block cite {
		color: var(--text-secondary);
		font-size: 12px;
		font-style: normal;
		line-height: 18px;
	}

	.results-context-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		margin: 0;
		padding: 12px;
		border: 1px solid var(--border-default);
		border-radius: 12px;
		background: #f8fafc;
	}

	.results-context-grid div {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.results-context-grid dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.results-context-grid dd {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		word-break: break-word;
	}

	.results-chip-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
	}

	.results-actions-panel {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 10px;
	}

	.results-action-button {
		min-height: 38px;
		width: 100%;
		border-radius: 10px;
		white-space: nowrap;
	}

	.results-table-wrapper {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: 16px;
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.results-table {
		width: 100%;
		min-width: 1120px;
		border-collapse: collapse;
		font-size: 14px;
		line-height: 22px;
	}

	.results-table th,
	.results-table td {
		padding: 12px;
		border-bottom: 1px solid var(--border-default);
		text-align: left;
		vertical-align: top;
	}

	.results-table th {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.results-table-result {
		max-width: 300px;
		display: grid;
		gap: 4px;
	}

	.results-table-result strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.results-table-result p {
		margin: 0;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.results-table-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 220px;
	}

	.results-empty-card {
		display: grid;
		justify-items: center;
		gap: 12px;
		padding: 34px 24px;
		text-align: center;
	}

	.results-empty-card h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.results-empty-card p {
		max-width: 640px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.results-empty-card__icon {
		width: 52px;
		height: 52px;
		display: grid;
		place-items: center;
		border-radius: 16px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.results-empty-card__actions {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.results-empty-filter {
		padding: 24px;
		border: 1px solid var(--border-default);
		border-radius: 16px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		text-align: center;
	}

	.results-skeleton {
		display: grid;
		gap: 16px;
	}

	.results-skeleton-card {
		min-height: 150px;
		border: 1px solid var(--border-default);
		border-radius: 16px;
		background:
			linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.68), transparent), #eef3f8;
		background-size:
			220px 100%,
			100% 100%;
		animation: results-skeleton 1.4s ease-in-out infinite;
	}

	.results-skeleton-card--summary-grid {
		min-height: 92px;
	}

	.results-skeleton-card--wide {
		min-height: 112px;
	}

	.results-skeleton-card--filters {
		min-height: 132px;
	}

	.results-skeleton-card--result {
		min-height: 246px;
	}

	:root[data-theme='dark'] .results-header,
	:root[data-theme='dark'] .results-filters-card,
	:root[data-theme='dark'] .results-card,
	:root[data-theme='dark'] .results-empty-card,
	:root[data-theme='dark'] .results-summary-card,
	:root[data-theme='dark'] .results-table-wrapper,
	:root[data-theme='dark'] .results-empty-filter,
	:root[data-theme='dark'] .results-more-menu__panel {
		background: rgba(16, 26, 44, 0.88);
	}

	:root[data-theme='dark'] .results-search-field,
	:root[data-theme='dark'] .results-more-menu summary,
	:root[data-theme='dark'] .results-view-switch {
		background: rgba(12, 20, 34, 0.8);
	}

	:root[data-theme='dark'] .results-context-grid,
	:root[data-theme='dark'] .results-quote-block {
		background: rgba(120, 140, 180, 0.12);
	}

	:root[data-theme='dark'] .results-quote-block p {
		color: var(--text-secondary);
	}

	@keyframes results-skeleton {
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
		.results-summary-grid {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}

		.results-filter-grid {
			grid-template-columns: repeat(3, minmax(160px, 1fr));
		}

		.results-card-body {
			grid-template-columns: minmax(0, 1fr) minmax(260px, 1fr);
		}

		.results-actions-panel {
			grid-column: 1 / -1;
			flex-direction: row;
			flex-wrap: wrap;
		}

		.results-action-button {
			width: auto;
		}
	}

	@media (max-width: 900px) {
		.results-summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.results-filter-search-row,
		.results-list-header,
		.results-conclusion,
		.results-header {
			display: grid;
			grid-template-columns: 1fr;
		}

		.results-conclusion__actions {
			justify-content: flex-start;
		}

		.results-card-body {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 560px) {
		.results-header,
		.results-filters-card,
		.results-card,
		.results-empty-card,
		.results-conclusion {
			padding: 18px;
		}

		.results-header h2 {
			font-size: 28px;
			line-height: 36px;
		}

		.results-summary-grid,
		.results-filter-grid,
		.results-context-grid {
			grid-template-columns: 1fr;
		}

		.results-card-top {
			grid-template-columns: auto minmax(0, 1fr);
		}

		.results-more-menu {
			grid-column: 1 / -1;
			justify-self: start;
		}

		.results-view-switch,
		.results-view-switch button,
		.results-actions-panel,
		.results-action-button,
		.results-sort-control .select {
			width: 100%;
		}

		.results-actions-panel {
			flex-direction: column;
		}

		.results-sort-control {
			display: grid;
			gap: 6px;
		}
	}
</style>
