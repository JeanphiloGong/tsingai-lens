<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import {
		buildComparisonConclusion,
		buildComparisonQualitySummary,
		fetchComparisons,
		filterComparisonItems,
		formatComparisonConfidence,
		formatComparisonValue,
		getComparisonActions,
		getComparisonContext,
		getComparisonNote,
		getComparisonStatus,
		getComparisonStatusBadge,
		getMissingContextChips,
		getResultTypeBadge,
		sortComparisonItems,
		type ComparisonAction,
		type ComparisonConclusionActionKey,
		type ComparisonFilters,
		type ComparisonMissingContextFilter,
		type ComparisonResultTypeFilter,
		type ComparisonReviewStatus,
		type ComparisonRow,
		type ComparisonSortMode,
		type ComparisonSpecifiedFilter,
		type ComparisonValueLabels,
		type ComparisonsResponse
	} from '../../../_shared/comparisons';
	import { t } from '../../../_shared/i18n';
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

	const STATUS_FILTERS: FilterOption<'' | ComparisonReviewStatus>[] = [
		{ value: '', labelKey: 'comparison.filters.all' },
		{ value: 'comparable', labelKey: 'comparison.status.comparable' },
		{ value: 'limited', labelKey: 'comparison.status.limited' },
		{ value: 'not_comparable', labelKey: 'comparison.status.notComparable' },
		{ value: 'insufficient', labelKey: 'comparison.status.insufficient' }
	];

	const RESULT_TYPE_FILTERS: FilterOption<ComparisonResultTypeFilter>[] = [
		{ value: '', labelKey: 'comparison.filters.all' },
		{ value: 'property', labelKey: 'comparison.resultTypes.property' },
		{ value: 'process', labelKey: 'comparison.resultTypes.process' },
		{ value: 'result', labelKey: 'comparison.resultTypes.result' },
		{ value: 'structure', labelKey: 'comparison.resultTypes.structure' },
		{ value: 'performance', labelKey: 'comparison.resultTypes.performance' },
		{ value: 'other', labelKey: 'comparison.resultTypes.other' }
	];

	const SPECIFIED_FILTERS: FilterOption<ComparisonSpecifiedFilter>[] = [
		{ value: '', labelKey: 'comparison.filters.all' },
		{ value: 'specified', labelKey: 'comparison.filters.specified' },
		{ value: 'unspecified', labelKey: 'comparison.filters.unspecified' }
	];

	const MISSING_CONTEXT_FILTERS: FilterOption<ComparisonMissingContextFilter>[] = [
		{ value: '', labelKey: 'comparison.filters.all' },
		{ value: 'baseline', labelKey: 'comparison.missing.baseline' },
		{ value: 'variant_link', labelKey: 'comparison.missing.variantLink' },
		{ value: 'test_condition', labelKey: 'comparison.missing.testCondition' },
		{ value: 'unit_context', labelKey: 'comparison.missing.unitContext' },
		{ value: 'expert_interpretation', labelKey: 'comparison.missing.expertInterpretation' }
	];

	const SORT_OPTIONS: FilterOption<ComparisonSortMode>[] = [
		{ value: 'completeness', labelKey: 'comparison.sort.completeness' },
		{ value: 'confidence_desc', labelKey: 'comparison.sort.confidenceDesc' },
		{ value: 'status', labelKey: 'comparison.sort.status' },
		{ value: 'material', labelKey: 'comparison.sort.material' },
		{ value: 'recent', labelKey: 'comparison.sort.recent' }
	];

	const MORE_ACTIONS = [
		'comparison.more.copyResult',
		'comparison.more.remove',
		'comparison.more.markReviewed',
		'comparison.more.reanalyze',
		'comparison.more.exportItem'
	];

	$: collectionId = $page.params.id ?? '';

	let response: ComparisonsResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let actionStatus = '';
	let actionLoading = false;
	let loadedCollectionId = '';
	let notFound = false;
	let syncedRouteMaterial = '';

	let search = '';
	let statusFilter: '' | ComparisonReviewStatus = '';
	let materialFilter = '';
	let resultTypeFilter: ComparisonResultTypeFilter = '';
	let testConditionFilter: ComparisonSpecifiedFilter = '';
	let baselineFilter: ComparisonSpecifiedFilter = '';
	let missingContextFilter: ComparisonMissingContextFilter = '';
	let sortMode: ComparisonSortMode = 'completeness';
	let viewMode: ViewMode = 'card';

	function uniqueSorted(values: string[]) {
		return Array.from(
			new Set(values.map((value) => value.trim()).filter((value) => value !== ''))
		).sort((a, b) => a.localeCompare(b));
	}

	$: routeMaterialFilter = $page.url.searchParams.get('material_system_normalized')?.trim() ?? '';
	$: valueLabels = {
		material: $t('comparison.values.unspecifiedMaterialSystem'),
		process: $t('comparison.values.unspecifiedProcess'),
		baseline: $t('comparison.values.unspecifiedBaseline'),
		test_condition: $t('comparison.values.unspecifiedTestCondition'),
		generic: $t('comparison.values.unspecified')
	} satisfies ComparisonValueLabels;
	$: if (routeMaterialFilter !== syncedRouteMaterial) {
		materialFilter = routeMaterialFilter
			? formatComparisonValue(routeMaterialFilter, 'material', valueLabels)
			: '';
		syncedRouteMaterial = routeMaterialFilter;
	}

	$: comparisonItems = response?.items ?? [];
	$: comparisonFilters = {
		search,
		status: statusFilter,
		material: materialFilter,
		resultType: resultTypeFilter,
		testCondition: testConditionFilter,
		baseline: baselineFilter,
		missingContext: missingContextFilter
	} satisfies ComparisonFilters;
	$: filteredItems = sortComparisonItems(
		filterComparisonItems(comparisonItems, comparisonFilters, valueLabels),
		sortMode,
		valueLabels
	);
	$: qualitySummary = buildComparisonQualitySummary(comparisonItems);
	$: conclusion = buildComparisonConclusion(qualitySummary);
	$: materials = uniqueSorted(
		comparisonItems.map((item) => getComparisonContext(item, valueLabels).materialSystem)
	);
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'comparisons');
	$: updatedAt = workspace?.collection.updated_at || workspace?.artifacts.updated_at || '';
	$: showFallbackState =
		Boolean(workspace) &&
		!loading &&
		comparisonItems.length < 1 &&
		(surfaceState !== 'ready' || notFound);
	$: hasBlockingError = Boolean(error) && !showFallbackState;
	$: if (collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadComparisons();
	}

	async function loadComparisons() {
		loading = true;
		error = '';
		actionStatus = '';
		notFound = false;

		const [comparisonsResult, workspaceResult] = await Promise.allSettled([
			fetchComparisons(collectionId),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResult.status === 'fulfilled' ? workspaceResult.value : null;

		if (comparisonsResult.status === 'fulfilled') {
			response = comparisonsResult.value;
			loading = false;
			return;
		}

		response = null;
		notFound = isHttpStatusError(comparisonsResult.reason, 404);
		error = errorMessage(comparisonsResult.reason);
		loading = false;
	}

	async function startComparisonGeneration() {
		actionLoading = true;
		actionStatus = '';
		try {
			await createBuildTask(collectionId);
			actionStatus = $t('comparison.review.processingStarted');
			await loadComparisons();
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
		statusFilter = '';
		materialFilter = '';
		resultTypeFilter = '';
		testConditionFilter = '';
		baselineFilter = '';
		missingContextFilter = '';
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

	function badgeLabel(badge: { labelKey: string; fallbackLabel: string }) {
		const label = $t(badge.labelKey);
		return label === badge.labelKey ? badge.fallbackLabel : label;
	}

	function resultTitle(item: ComparisonRow) {
		return formatComparisonValue(item.display.property_normalized, 'result', valueLabels);
	}

	function extractedResult(item: ComparisonRow) {
		const summary = item.display.result_summary.trim();
		if (!summary || summary === '--' || summary === item.display.property_normalized) {
			return resultTitle(item);
		}
		return formatComparisonValue(summary, 'result', valueLabels);
	}

	function canViewSource(row: ComparisonRow) {
		return Boolean(row.source_document_id && row.evidence_bundle.supporting_evidence_ids.length);
	}

	function viewSourceHref(row: ComparisonRow) {
		return buildDocumentViewerHref(collectionId, row.source_document_id, {
			evidenceId: row.evidence_bundle.supporting_evidence_ids[0] ?? null,
			returnTo: `${$page.url.pathname}${$page.url.search}`
		});
	}

	function viewResultHref(row: ComparisonRow) {
		return `/collections/${collectionId}/results/${encodeURIComponent(row.result_id)}`;
	}

	function actionHref(action: ComparisonAction, row: ComparisonRow) {
		if (action.key === 'view_evidence') {
			return canViewSource(row) ? viewSourceHref(row) : `/collections/${collectionId}/evidence`;
		}
		if (['view_comparison', 'view_conditions', 'view_reason'].includes(action.key)) {
			return row.result_id ? viewResultHref(row) : null;
		}
		return null;
	}

	function actionClass(action: ComparisonAction) {
		const toneClass =
			action.tone === 'primary'
				? 'btn--primary'
				: action.tone === 'danger'
					? 'btn--danger'
					: 'btn--ghost';
		return `btn ${toneClass} btn--small comparison-action-button`;
	}

	function handlePendingAction(action: ComparisonAction, row: ComparisonRow) {
		if (action.key === 'view_missing') {
			const firstFilterableChip = getMissingContextChips(row).find((chip) =>
				[
					'baseline',
					'variant_link',
					'test_condition',
					'unit_context',
					'expert_interpretation'
				].includes(chip.key)
			);
			if (firstFilterableChip) {
				missingContextFilter = firstFilterableChip.key as ComparisonMissingContextFilter;
			}
		}
		actionStatus = $t('comparison.review.actionTodo', { action: $t(action.labelKey) });
	}

	function conclusionActionLabel(actionKey: ComparisonConclusionActionKey) {
		return $t(`comparison.conclusionActions.${actionKey}`);
	}

	async function handleConclusionAction(actionKey: ComparisonConclusionActionKey) {
		if (actionKey === 'view_direct') {
			statusFilter = 'comparable';
			return;
		}
		if (actionKey === 'view_limited') {
			statusFilter = 'limited';
			return;
		}
		if (actionKey === 'view_insufficient') {
			statusFilter = 'insufficient';
			return;
		}
		if (actionKey === 'view_evidence') {
			await goto(`/collections/${collectionId}/evidence`);
			return;
		}
		actionStatus = $t('comparison.review.actionTodo', { action: conclusionActionLabel(actionKey) });
	}
</script>

<svelte:head>
	<title>{$t('comparison.review.title')}</title>
</svelte:head>

<section class="comparison-review-page fade-up">
	<header class="comparison-review-header">
		<div class="comparison-review-header__copy">
			<h2>{$t('comparison.review.title')}</h2>
			<p>{$t('comparison.review.description')}</p>
			<div class="comparison-meta-row">
				<span class="comparison-meta">
					<span class="comparison-meta__icon comparison-meta__icon--count" aria-hidden="true"
					></span>
					{$t('comparison.review.count', { count: response?.total ?? comparisonItems.length })}
				</span>
				<span class={`status-badge status-badge--${surfaceStatusTone(surfaceState)}`}>
					{$t(`overview.surfaceStates.${surfaceState}`)}
				</span>
				<span class="comparison-meta">
					<span class="comparison-meta__icon comparison-meta__icon--time" aria-hidden="true"></span>
					{$t('comparison.review.updatedAt', { time: formatDate(updatedAt) })}
				</span>
			</div>
		</div>
		<button
			class="btn btn--ghost comparison-refresh-button"
			type="button"
			on:click={loadComparisons}
		>
			<span class="refresh-icon" aria-hidden="true"></span>
			{$t('comparison.actions.refresh')}
		</button>
	</header>

	{#if hasBlockingError}
		<div class="comparison-alert comparison-alert--error" role="alert">
			<strong>{$t('comparison.review.error')}</strong>
			<span>{safeErrorText(error)}</span>
		</div>
	{:else if loading}
		<section class="comparison-skeleton" aria-busy="true" aria-live="polite">
			<div class="skeleton-card skeleton-card--summary-grid"></div>
			<div class="skeleton-card skeleton-card--wide"></div>
			<div class="skeleton-card skeleton-card--filters"></div>
			<div class="skeleton-card skeleton-card--comparison"></div>
			<div class="skeleton-card skeleton-card--comparison"></div>
		</section>
	{:else if showFallbackState}
		<article class="comparison-empty-card">
			<div class="comparison-empty-card__icon" aria-hidden="true">!</div>
			<h3>{stateCardTitle()}</h3>
			<p>{stateCardBody()}</p>
			<div class="comparison-empty-card__actions">
				<a class="btn btn--ghost" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
				<button class="btn btn--primary" type="button" on:click={loadComparisons}>
					{$t('comparison.actions.refresh')}
				</button>
			</div>
		</article>
	{:else if !comparisonItems.length}
		<article class="comparison-empty-card">
			<div class="comparison-empty-card__icon" aria-hidden="true">C</div>
			<h3>{$t('comparison.empty.title')}</h3>
			<p>{$t('comparison.empty.description')}</p>
			<div class="comparison-empty-card__actions">
				<button
					class="btn btn--primary"
					type="button"
					disabled={actionLoading}
					on:click={startComparisonGeneration}
				>
					{actionLoading ? $t('comparison.review.processing') : $t('comparison.empty.generate')}
				</button>
				<button class="btn btn--ghost" type="button" on:click={loadComparisons}>
					{$t('comparison.actions.refreshStatus')}
				</button>
			</div>
			{#if actionStatus}
				<div class="comparison-alert" role="status">{actionStatus}</div>
			{/if}
		</article>
	{:else}
		<section class="comparison-summary-grid" aria-label={$t('comparison.review.summaryLabel')}>
			{#each qualitySummary as item (item.key)}
				<article class={`comparison-summary-card comparison-summary-card--${item.tone}`}>
					<div class="comparison-summary-card__icon" aria-hidden="true">{item.icon}</div>
					<div class="comparison-summary-card__copy">
						<span>{$t(item.labelKey)}</span>
						<strong>{item.value}</strong>
					</div>
					{#if item.percent !== null}
						<span class="comparison-summary-card__percent">{item.percent}%</span>
					{/if}
				</article>
			{/each}
		</section>

		<section class={`comparison-conclusion comparison-conclusion--${conclusion.tone}`}>
			<div class="comparison-conclusion__icon" aria-hidden="true">
				{conclusion.tone === 'success' ? 'OK' : '!'}
			</div>
			<div class="comparison-conclusion__copy">
				<h3>{$t(conclusion.titleKey)}</h3>
				<p>{$t(conclusion.bodyKey)}</p>
			</div>
			<div class="comparison-conclusion__actions">
				{#each conclusion.actionKeys as actionKey (actionKey)}
					<button
						class={actionKey === 'add_to_final'
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

		<section class="comparison-filters-card" aria-label={$t('comparison.filters.title')}>
			<div class="comparison-filter-search-row">
				<label class="sr-only" for="comparison-search">{$t('comparison.filters.search')}</label>
				<div class="comparison-search-field">
					<span class="comparison-search-field__icon" aria-hidden="true"></span>
					<input
						id="comparison-search"
						type="search"
						bind:value={search}
						placeholder={$t('comparison.filters.searchPlaceholder')}
					/>
				</div>
				<div class="comparison-view-switch" aria-label={$t('comparison.view.label')}>
					<button
						type="button"
						class:active={viewMode === 'card'}
						aria-pressed={viewMode === 'card'}
						on:click={() => (viewMode = 'card')}
					>
						<span class="view-grid-icon" aria-hidden="true"></span>
						{$t('comparison.view.card')}
					</button>
					<button
						type="button"
						class:active={viewMode === 'table'}
						aria-pressed={viewMode === 'table'}
						on:click={() => (viewMode = 'table')}
					>
						<span class="view-table-icon" aria-hidden="true"></span>
						{$t('comparison.view.table')}
					</button>
				</div>
			</div>

			<div class="comparison-filter-grid">
				<div class="field">
					<label for="comparison-status">{$t('comparison.filters.status')}</label>
					<select id="comparison-status" class="select" bind:value={statusFilter}>
						{#each STATUS_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="comparison-material">{$t('comparison.filters.material')}</label>
					<select
						id="comparison-material"
						class="select"
						bind:value={materialFilter}
						on:change={(event) =>
							void updateMaterialRoute((event.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">{$t('comparison.filters.all')}</option>
						{#each materials as item (item)}
							<option value={item}>{item}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="comparison-result-type">{$t('comparison.filters.resultType')}</label>
					<select id="comparison-result-type" class="select" bind:value={resultTypeFilter}>
						{#each RESULT_TYPE_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="comparison-test-condition">{$t('comparison.filters.testCondition')}</label>
					<select id="comparison-test-condition" class="select" bind:value={testConditionFilter}>
						{#each SPECIFIED_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="comparison-baseline">{$t('comparison.filters.baseline')}</label>
					<select id="comparison-baseline" class="select" bind:value={baselineFilter}>
						{#each SPECIFIED_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
				<div class="field">
					<label for="comparison-missing-context">{$t('comparison.filters.missingContext')}</label>
					<select id="comparison-missing-context" class="select" bind:value={missingContextFilter}>
						{#each MISSING_CONTEXT_FILTERS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</div>
			</div>

			<div class="comparison-filter-footer">
				<button class="btn btn--ghost btn--small" type="button" on:click={clearFilters}>
					{$t('comparison.filters.clear')}
				</button>
			</div>
		</section>

		{#if actionStatus}
			<div class="comparison-alert" role="status">{actionStatus}</div>
		{/if}

		<section class="comparison-list-section">
			<div class="comparison-list-header">
				<h3>{$t('comparison.list.count', { count: filteredItems.length })}</h3>
				<label class="comparison-sort-control">
					<span>{$t('comparison.sort.label')}</span>
					<select class="select" bind:value={sortMode}>
						{#each SORT_OPTIONS as option (option.value)}
							<option value={option.value}>{$t(option.labelKey)}</option>
						{/each}
					</select>
				</label>
			</div>

			{#if filteredItems.length}
				{#if viewMode === 'card'}
					<div class="comparison-card-list">
						{#each filteredItems as item (item.row_id)}
							{@const status = getComparisonStatus(item)}
							{@const statusBadge = getComparisonStatusBadge(status)}
							{@const typeBadge = getResultTypeBadge(item.display.result_type)}
							{@const context = getComparisonContext(item, valueLabels)}
							{@const missingChips = getMissingContextChips(item)}
							{@const actions = getComparisonActions(item)}
							<article class="comparison-card">
								<div class="comparison-card-top">
									<div
										class={`comparison-type-icon comparison-type-icon--${typeBadge.tone}`}
										aria-hidden="true"
									>
										{typeBadge.icon}
									</div>
									<div class="comparison-card-title-block">
										<h4>{resultTitle(item)}</h4>
										<div class="comparison-badge-row">
											<span class={`comparison-badge comparison-badge--${statusBadge.tone}`}>
												{badgeLabel(statusBadge)}
											</span>
											<span class={`comparison-badge comparison-badge--${typeBadge.tone}`}>
												{badgeLabel(typeBadge)}
											</span>
											<span class="comparison-badge comparison-badge--confidence">
												{$t('comparison.card.confidenceValue', {
													value: formatComparisonConfidence(item)
												})}
											</span>
										</div>
									</div>
									<details class="comparison-more-menu">
										<summary aria-label={$t('comparison.more.label')}>...</summary>
										<div class="comparison-more-menu__panel">
											{#each MORE_ACTIONS as labelKey (labelKey)}
												<button type="button" disabled>{$t(labelKey)}</button>
											{/each}
										</div>
									</details>
								</div>

								<div class="comparison-card-body">
									<section class="comparison-result-column">
										<div class="comparison-card-section">
											<h5>{$t('comparison.card.extractedResult')}</h5>
											<p class="comparison-result-text">{extractedResult(item)}</p>
											<p class="comparison-result-note">{$t('comparison.card.resultNote')}</p>
										</div>
									</section>

									<div class="comparison-context-column">
										<section class="comparison-card-section">
											<h5>{$t('comparison.card.context')}</h5>
											<dl class="comparison-context-grid">
												<div>
													<dt>{$t('comparison.card.materialSystem')}</dt>
													<dd>{context.materialSystem}</dd>
												</div>
												<div>
													<dt>{$t('comparison.card.process')}</dt>
													<dd>{context.process}</dd>
												</div>
												<div>
													<dt>{$t('comparison.card.baseline')}</dt>
													<dd>{context.baseline}</dd>
												</div>
												<div>
													<dt>{$t('comparison.card.testCondition')}</dt>
													<dd>{context.testCondition}</dd>
												</div>
											</dl>
											{#if context.variant || context.variable}
												<p class="comparison-context-note">
													{[context.variant, context.variable].filter(Boolean).join(' / ')}
												</p>
											{/if}
										</section>

										<section class="comparison-card-section">
											<h5>{$t('comparison.card.missingContext')}</h5>
											{#if missingChips.length}
												<div class="comparison-chip-row">
													{#each missingChips as chip (chip.key)}
														<span class={`comparison-chip comparison-chip--${chip.tone}`}>
															{badgeLabel(chip)}
														</span>
													{/each}
												</div>
											{:else}
												<p class="comparison-muted-text">
													{$t('comparison.card.noMissingContext')}
												</p>
											{/if}
										</section>

										<section class="comparison-card-section">
											<h5>{$t('comparison.card.note')}</h5>
											<p class="comparison-note-text">{getComparisonNote(item)}</p>
										</section>
									</div>

									<div class="comparison-actions-panel">
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
					<div class="comparison-table-wrapper">
						<table class="comparison-table">
							<thead>
								<tr>
									<th>{$t('comparison.table.result')}</th>
									<th>{$t('comparison.table.status')}</th>
									<th>{$t('comparison.table.material')}</th>
									<th>{$t('comparison.table.process')}</th>
									<th>{$t('comparison.table.baseline')}</th>
									<th>{$t('comparison.table.testCondition')}</th>
									<th>{$t('comparison.table.missingContext')}</th>
									<th>{$t('comparison.table.actions')}</th>
								</tr>
							</thead>
							<tbody>
								{#each filteredItems as item (item.row_id)}
									{@const statusBadge = getComparisonStatusBadge(getComparisonStatus(item))}
									{@const context = getComparisonContext(item, valueLabels)}
									{@const missingChips = getMissingContextChips(item)}
									{@const actions = getComparisonActions(item)}
									<tr>
										<td>
											<div class="comparison-table-result" title={extractedResult(item)}>
												<strong>{resultTitle(item)}</strong>
												<p>{extractedResult(item)}</p>
											</div>
										</td>
										<td>
											<span class={`comparison-badge comparison-badge--${statusBadge.tone}`}>
												{badgeLabel(statusBadge)}
											</span>
										</td>
										<td>{context.materialSystem}</td>
										<td>{context.process}</td>
										<td>{context.baseline}</td>
										<td>{context.testCondition}</td>
										<td>
											<div class="comparison-table-chips">
												{#if missingChips.length}
													{#each missingChips as chip (chip.key)}
														<span class={`comparison-chip comparison-chip--${chip.tone}`}>
															{badgeLabel(chip)}
														</span>
													{/each}
												{:else}
													<span class="comparison-muted-text"
														>{$t('comparison.card.noMissingContext')}</span
													>
												{/if}
											</div>
										</td>
										<td>
											<div class="comparison-table-actions">
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
				<div class="comparison-empty-filter" role="status">
					{$t('comparison.list.emptyFiltered')}
				</div>
			{/if}
		</section>
	{/if}
</section>

<style>
	.comparison-review-page {
		width: 100%;
		max-width: 1280px;
		margin: 0 auto;
		display: grid;
		gap: 24px;
	}

	.comparison-review-header,
	.comparison-filters-card,
	.comparison-card,
	.comparison-empty-card,
	.comparison-summary-card {
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.comparison-review-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 20px;
		padding: 24px;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
	}

	.comparison-review-header__copy {
		min-width: 0;
		display: grid;
		gap: 10px;
	}

	.comparison-review-header h2 {
		margin: 0;
		color: var(--text-primary);
		font-size: 30px;
		font-weight: 700;
		line-height: 38px;
		letter-spacing: 0;
	}

	.comparison-review-header p {
		max-width: 780px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 15px;
		line-height: 22px;
	}

	.comparison-meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.comparison-meta {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.comparison-meta__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		color: var(--text-tertiary);
	}

	.comparison-meta__icon--count {
		border: 1.5px solid currentColor;
		border-radius: 3px;
	}

	.comparison-meta__icon--count::before,
	.comparison-meta__icon--count::after {
		content: '';
		position: absolute;
		left: 3px;
		right: 3px;
		height: 1.5px;
		background: currentColor;
	}

	.comparison-meta__icon--count::before {
		top: 4px;
	}

	.comparison-meta__icon--count::after {
		top: 8px;
	}

	.comparison-meta__icon--time {
		border: 1.5px solid currentColor;
		border-radius: 999px;
	}

	.comparison-meta__icon--time::before,
	.comparison-meta__icon--time::after {
		content: '';
		position: absolute;
		left: 6px;
		top: 3px;
		width: 1.5px;
		height: 4px;
		border-radius: 999px;
		background: currentColor;
	}

	.comparison-meta__icon--time::after {
		top: 6px;
		width: 4px;
		height: 1.5px;
	}

	.comparison-refresh-button {
		flex: 0 0 auto;
	}

	.comparison-summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 16px;
	}

	.comparison-summary-card {
		min-width: 0;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 14px;
		padding: 18px 20px;
	}

	.comparison-summary-card__icon {
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

	.comparison-summary-card--success .comparison-summary-card__icon {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.comparison-summary-card--warning .comparison-summary-card__icon {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.comparison-summary-card--danger .comparison-summary-card__icon {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-summary-card--neutral .comparison-summary-card__icon {
		background: #f1f5f9;
		color: var(--text-secondary);
	}

	.comparison-summary-card__copy {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.comparison-summary-card__copy span {
		color: var(--text-primary);
		font-size: 14px;
		font-weight: 600;
		line-height: 22px;
	}

	.comparison-summary-card__copy strong {
		color: var(--text-primary);
		font-size: 24px;
		font-weight: 700;
		line-height: 30px;
	}

	.comparison-summary-card__percent {
		color: #50658a;
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-conclusion {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 18px;
		padding: 20px 24px;
		border: 1px solid var(--warning-border);
		border-radius: var(--radius-lg);
		background: #fffbeb;
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.comparison-conclusion--success {
		border-color: var(--success-border);
		background: #f0fdf4;
	}

	.comparison-conclusion--info {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	.comparison-conclusion__icon {
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

	.comparison-conclusion--success .comparison-conclusion__icon {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.comparison-conclusion__copy {
		display: grid;
		gap: 6px;
		min-width: 0;
	}

	.comparison-conclusion h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.comparison-conclusion p {
		margin: 0;
		color: #5f4b1b;
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-conclusion--success p,
	.comparison-conclusion--info p {
		color: var(--text-secondary);
	}

	.comparison-conclusion__actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: 10px;
	}

	.comparison-filters-card {
		display: grid;
		gap: 14px;
		padding: 18px 20px;
	}

	.comparison-filter-search-row {
		display: grid;
		grid-template-columns: minmax(260px, 420px) auto;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.comparison-search-field {
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

	.comparison-search-field:focus-within {
		border-color: var(--brand-primary);
		box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
	}

	.comparison-search-field__icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
		border: 1.8px solid var(--text-secondary);
		border-radius: 999px;
	}

	.comparison-search-field__icon::after {
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

	.comparison-search-field input {
		min-width: 0;
		width: 100%;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--text-primary);
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-search-field input::placeholder {
		color: var(--text-secondary);
	}

	.comparison-view-switch {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: #f8fafc;
	}

	.comparison-view-switch button {
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

	.comparison-view-switch button.active {
		background: var(--brand-soft);
		color: var(--brand-primary);
		box-shadow: var(--shadow-xs);
	}

	.view-grid-icon,
	.view-table-icon {
		position: relative;
		width: 14px;
		height: 14px;
		flex: 0 0 auto;
	}

	.view-grid-icon {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 2px;
	}

	.view-grid-icon::before,
	.view-grid-icon::after,
	.view-table-icon::before,
	.view-table-icon::after {
		content: '';
		display: block;
	}

	.view-grid-icon::before,
	.view-grid-icon::after {
		width: 6px;
		height: 6px;
		border: 1.5px solid currentColor;
		border-radius: 2px;
		box-shadow: 8px 0 0 -1.5px currentColor;
	}

	.view-table-icon::before,
	.view-table-icon::after {
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

	.view-table-icon::after {
		left: 5px;
	}

	.comparison-filter-grid {
		display: grid;
		grid-template-columns: repeat(6, minmax(140px, 1fr));
		gap: 16px;
	}

	.comparison-filter-grid .select,
	.comparison-sort-control .select {
		min-height: 40px;
		border-radius: var(--radius-md);
	}

	.comparison-filter-footer {
		display: flex;
		justify-content: flex-end;
	}

	.comparison-alert {
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

	.comparison-alert--error {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-list-section {
		display: grid;
		gap: 14px;
	}

	.comparison-list-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
	}

	.comparison-list-header h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 600;
		line-height: 24px;
	}

	.comparison-sort-control {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--text-secondary);
		font-size: 13px;
		line-height: 20px;
	}

	.comparison-sort-control .select {
		width: 190px;
	}

	.comparison-card-list {
		display: grid;
		gap: 16px;
	}

	.comparison-card {
		display: grid;
		gap: 16px;
		padding: 16px;
		border-radius: 16px;
	}

	.comparison-card-top {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: 12px;
	}

	.comparison-type-icon {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 9px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 13px;
		font-weight: 800;
		line-height: 1;
	}

	.comparison-type-icon--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.comparison-type-icon--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.comparison-type-icon--danger {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-type-icon--neutral,
	.comparison-type-icon--info {
		background: #f1f5f9;
		color: var(--text-secondary);
	}

	.comparison-card-title-block {
		min-width: 0;
		display: grid;
		gap: 7px;
	}

	.comparison-card-title-block h4 {
		margin: 0;
		color: var(--text-primary);
		font-size: 16px;
		font-weight: 700;
		line-height: 24px;
		letter-spacing: 0;
		word-break: break-word;
	}

	.comparison-badge-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
	}

	.comparison-badge,
	.comparison-chip {
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

	.comparison-badge--brand {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.comparison-badge--success,
	.comparison-chip--success {
		background: var(--success-bg);
		color: var(--success-text);
	}

	.comparison-badge--warning,
	.comparison-chip--warning {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.comparison-badge--danger {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.comparison-badge--info {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}

	.comparison-badge--confidence {
		background: #eef6ef;
		color: #1f7a3f;
	}

	.comparison-more-menu {
		position: relative;
	}

	.comparison-more-menu summary {
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

	.comparison-more-menu summary::-webkit-details-marker {
		display: none;
	}

	.comparison-more-menu__panel {
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

	.comparison-more-menu__panel button {
		min-height: 34px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-secondary);
		text-align: left;
		font-size: 13px;
		line-height: 20px;
	}

	.comparison-card-body {
		display: grid;
		grid-template-columns: minmax(260px, 1.2fr) minmax(320px, 1.5fr) minmax(150px, 180px);
		gap: 16px;
	}

	.comparison-result-column,
	.comparison-context-column {
		min-width: 0;
		display: grid;
		align-content: start;
		gap: 14px;
	}

	.comparison-card-section {
		display: grid;
		gap: 8px;
	}

	.comparison-card-section h5 {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
	}

	.comparison-result-text,
	.comparison-note-text,
	.comparison-muted-text,
	.comparison-context-note {
		margin: 0;
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-result-text {
		color: var(--text-primary);
	}

	.comparison-result-note,
	.comparison-context-note,
	.comparison-muted-text {
		margin: 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	.comparison-note-text {
		color: #334155;
	}

	.comparison-context-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 12px;
		margin: 0;
		padding: 12px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: #f8fafc;
	}

	.comparison-context-grid div {
		min-width: 0;
		display: grid;
		gap: 2px;
	}

	.comparison-context-grid dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.comparison-context-grid dd {
		margin: 0;
		color: var(--text-primary);
		font-size: 13px;
		font-weight: 700;
		line-height: 20px;
		word-break: break-word;
	}

	.comparison-chip-row,
	.comparison-table-chips {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
	}

	.comparison-actions-panel {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 10px;
	}

	.comparison-action-button {
		min-height: 38px;
		width: 100%;
		border-radius: 10px;
		white-space: nowrap;
	}

	.comparison-table-wrapper {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
	}

	.comparison-table {
		width: 100%;
		min-width: 1080px;
		border-collapse: collapse;
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-table th,
	.comparison-table td {
		padding: 12px;
		border-bottom: 1px solid var(--border-default);
		text-align: left;
		vertical-align: top;
	}

	.comparison-table th {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		line-height: 18px;
	}

	.comparison-table-result {
		max-width: 280px;
		display: grid;
		gap: 4px;
	}

	.comparison-table-result strong {
		color: var(--text-primary);
		font-size: 14px;
		line-height: 20px;
	}

	.comparison-table-result p {
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

	.comparison-table-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		min-width: 220px;
	}

	.comparison-empty-card {
		display: grid;
		justify-items: center;
		gap: 12px;
		padding: 34px 24px;
		text-align: center;
	}

	.comparison-empty-card h3 {
		margin: 0;
		color: var(--text-primary);
		font-size: 18px;
		font-weight: 700;
		line-height: 26px;
	}

	.comparison-empty-card p {
		max-width: 640px;
		margin: 0;
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
	}

	.comparison-empty-card__icon {
		width: 52px;
		height: 52px;
		display: grid;
		place-items: center;
		border-radius: 16px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.comparison-empty-card__actions {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 10px;
	}

	.comparison-empty-filter {
		padding: 24px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 14px;
		line-height: 22px;
		text-align: center;
	}

	.comparison-skeleton {
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
		animation: comparison-skeleton 1.4s ease-in-out infinite;
	}

	.skeleton-card--summary-grid {
		min-height: 92px;
	}

	.skeleton-card--wide {
		min-height: 112px;
	}

	.skeleton-card--filters {
		min-height: 132px;
	}

	.skeleton-card--comparison {
		min-height: 226px;
	}

	:root[data-theme='dark'] .comparison-review-header,
	:root[data-theme='dark'] .comparison-filters-card,
	:root[data-theme='dark'] .comparison-card,
	:root[data-theme='dark'] .comparison-empty-card,
	:root[data-theme='dark'] .comparison-summary-card,
	:root[data-theme='dark'] .comparison-table-wrapper,
	:root[data-theme='dark'] .comparison-empty-filter,
	:root[data-theme='dark'] .comparison-more-menu__panel {
		background: rgba(16, 26, 44, 0.88);
	}

	:root[data-theme='dark'] .comparison-search-field,
	:root[data-theme='dark'] .comparison-more-menu summary,
	:root[data-theme='dark'] .comparison-view-switch {
		background: rgba(12, 20, 34, 0.8);
	}

	:root[data-theme='dark'] .comparison-context-grid {
		background: rgba(120, 140, 180, 0.12);
	}

	:root[data-theme='dark'] .comparison-note-text {
		color: var(--text-secondary);
	}

	@keyframes comparison-skeleton {
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
		.comparison-filter-grid {
			grid-template-columns: repeat(3, minmax(160px, 1fr));
		}

		.comparison-card-body {
			grid-template-columns: minmax(0, 1fr) minmax(260px, 1fr);
		}

		.comparison-actions-panel {
			grid-column: 1 / -1;
			flex-direction: row;
			flex-wrap: wrap;
		}

		.comparison-action-button {
			width: auto;
		}
	}

	@media (max-width: 900px) {
		.comparison-summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.comparison-filter-search-row,
		.comparison-list-header,
		.comparison-conclusion,
		.comparison-review-header {
			display: grid;
			grid-template-columns: 1fr;
		}

		.comparison-conclusion__actions {
			justify-content: flex-start;
		}

		.comparison-card-body {
			grid-template-columns: 1fr;
		}

		.comparison-context-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	@media (max-width: 560px) {
		.comparison-review-header,
		.comparison-filters-card,
		.comparison-card,
		.comparison-empty-card,
		.comparison-conclusion {
			padding: 18px;
		}

		.comparison-review-header h2 {
			font-size: 28px;
			line-height: 36px;
		}

		.comparison-summary-grid,
		.comparison-filter-grid,
		.comparison-context-grid {
			grid-template-columns: 1fr;
		}

		.comparison-card-top {
			grid-template-columns: auto minmax(0, 1fr);
		}

		.comparison-more-menu {
			grid-column: 1 / -1;
			justify-self: start;
		}

		.comparison-view-switch,
		.comparison-view-switch button,
		.comparison-actions-panel,
		.comparison-action-button,
		.comparison-sort-control .select {
			width: 100%;
		}

		.comparison-actions-panel {
			flex-direction: column;
		}

		.comparison-sort-control {
			display: grid;
			gap: 6px;
		}
	}
</style>
