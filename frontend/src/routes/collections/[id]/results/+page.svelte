<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchCollectionResults,
		type ResultListItem,
		type ResultListResponse
	} from '../../../_shared/results';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../../_shared/workspace';

	type ResultRouteFilterName =
		| 'material_system_normalized'
		| 'property_normalized'
		| 'test_condition_normalized'
		| 'baseline_normalized'
		| 'comparability_status';

	$: collectionId = $page.params.id ?? '';

	let response: ResultListResponse | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let loadedRequestKey = '';
	let syncedRouteFilterKey = '';
	let notFound = false;
	let materialFilter = '';
	let propertyFilter = '';
	let testConditionFilter = '';
	let baselineFilter = '';
	let comparabilityFilter = '';

	function uniqueSorted(values: string[]) {
		return Array.from(new Set(values.map((value) => value.trim()).filter((value) => value !== ''))).sort();
	}

	function routeFilterValue(name: ResultRouteFilterName) {
		return $page.url.searchParams.get(name)?.trim() ?? '';
	}

	$: routeMaterialFilter = routeFilterValue('material_system_normalized');
	$: routePropertyFilter = routeFilterValue('property_normalized');
	$: routeTestConditionFilter = routeFilterValue('test_condition_normalized');
	$: routeBaselineFilter = routeFilterValue('baseline_normalized');
	$: routeComparabilityFilter = routeFilterValue('comparability_status');
	$: routeFilterKey = [
		routeMaterialFilter,
		routePropertyFilter,
		routeTestConditionFilter,
		routeBaselineFilter,
		routeComparabilityFilter
	].join('|');
	$: if (routeFilterKey !== syncedRouteFilterKey) {
		materialFilter = routeMaterialFilter;
		propertyFilter = routePropertyFilter;
		testConditionFilter = routeTestConditionFilter;
		baselineFilter = routeBaselineFilter;
		comparabilityFilter = routeComparabilityFilter;
		syncedRouteFilterKey = routeFilterKey;
	}

	$: materials = uniqueSorted([
		materialFilter,
		...(response?.items ?? []).map((item) => item.material_label)
	]);
	$: properties = uniqueSorted([
		propertyFilter,
		...(response?.items ?? []).map((item) => item.property)
	]);
	$: testConditions = uniqueSorted([
		testConditionFilter,
		...(response?.items ?? []).map((item) => item.test_condition ?? '')
	]);
	$: baselines = uniqueSorted([
		baselineFilter,
		...(response?.items ?? []).map((item) => item.baseline ?? '')
	]);
	$: items = response?.items ?? [];
	$: comparableCount = items.filter((item) => item.comparability_status === 'comparable').length;
	$: limitedCount = items.filter((item) => item.comparability_status === 'limited').length;
	$: traceableCount = items.filter((item) => item.traceability_status === 'direct').length;
	$: surfaceState = getWorkspaceSurfaceState(workspace, 'results');
	$: showFallbackState =
		Boolean(workspace) && !loading && !items.length && (surfaceState !== 'ready' || notFound);
	$: requestKey = collectionId
		? `${collectionId}|${routeFilterKey}`
		: '';
	$: if (requestKey && requestKey !== loadedRequestKey) {
		loadedRequestKey = requestKey;
		void loadResults();
	}

	async function loadResults() {
		loading = true;
		error = '';
		notFound = false;

		const [resultsResult, workspaceResult] = await Promise.allSettled([
			fetchCollectionResults(collectionId, {
				material_system_normalized: routeMaterialFilter || undefined,
				property_normalized: routePropertyFilter || undefined,
				test_condition_normalized: routeTestConditionFilter || undefined,
				baseline_normalized: routeBaselineFilter || undefined,
				comparability_status: routeComparabilityFilter || undefined
			}),
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

	async function updateRouteFilter(name: ResultRouteFilterName, value: string) {
		const params = new URLSearchParams($page.url.searchParams);
		const normalized = value.trim();
		if (normalized) {
			params.set(name, normalized);
		} else {
			params.delete(name);
		}

		const query = params.toString();
		await goto(query ? `${$page.url.pathname}?${query}` : $page.url.pathname, {
			keepFocus: true,
			noScroll: true,
			replaceState: true
		});
	}

	function resultHref(item: ResultListItem) {
		return `/collections/${collectionId}/results/${encodeURIComponent(item.result_id)}`;
	}

	function documentHref(item: ResultListItem) {
		return `/collections/${collectionId}/documents/${encodeURIComponent(item.document_id)}`;
	}

	function stateCardTitle() {
		return $t(`overview.surfaceStateCards.${surfaceState}.title`);
	}

	function stateCardBody() {
		return $t(`overview.surfaceStateCards.${surfaceState}.body`);
	}
</script>

<svelte:head>
	<title>{$t('results.title')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="card-header-inline">
		<div>
			<h2>{$t('results.title')}</h2>
			<p class="lead">{$t('results.lead')}</p>
		</div>
		<button class="btn btn--ghost btn--small" type="button" on:click={loadResults}>
			{$t('overview.refresh')}
		</button>
	</div>

	<div class="result-grid result-grid--tasks">
		<article class="result-card">
			<h3>{$t('results.summaryTitle')}</h3>
			<dl class="detail-list">
				<div class="detail-row">
					<dt>{$t('results.totalLabel')}</dt>
					<dd>{items.length}</dd>
				</div>
				<div class="detail-row">
					<dt>{$t('comparisons.comparable')}</dt>
					<dd>{comparableCount}</dd>
				</div>
				<div class="detail-row">
					<dt>{$t('comparisons.limited')}</dt>
					<dd>{limitedCount}</dd>
				</div>
				<div class="detail-row">
					<dt>{$t('results.traceableLabel')}</dt>
					<dd>{traceableCount}</dd>
				</div>
			</dl>
		</article>
	</div>

	<div class="form-grid">
		<div class="field">
			<label for="comparabilityFilter">{$t('results.filterStatus')}</label>
			<select
				id="comparabilityFilter"
				class="select"
				bind:value={comparabilityFilter}
				on:change={(event) =>
					void updateRouteFilter(
						'comparability_status',
						(event.currentTarget as HTMLSelectElement).value
					)}
			>
				<option value="">{$t('results.allOption')}</option>
				<option value="comparable">{$t('comparisons.comparable')}</option>
				<option value="limited">{$t('comparisons.limited')}</option>
				<option value="not_comparable">{$t('comparisons.notComparable')}</option>
				<option value="insufficient">{$t('comparisons.insufficient')}</option>
			</select>
		</div>
		<div class="field">
			<label for="materialFilter">{$t('results.filterMaterial')}</label>
			<select
				id="materialFilter"
				class="select"
				bind:value={materialFilter}
				on:change={(event) =>
					void updateRouteFilter(
						'material_system_normalized',
						(event.currentTarget as HTMLSelectElement).value
					)}
			>
				<option value="">{$t('results.allOption')}</option>
				{#each materials as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
		<div class="field">
			<label for="propertyFilter">{$t('results.filterProperty')}</label>
			<select
				id="propertyFilter"
				class="select"
				bind:value={propertyFilter}
				on:change={(event) =>
					void updateRouteFilter(
						'property_normalized',
						(event.currentTarget as HTMLSelectElement).value
					)}
			>
				<option value="">{$t('results.allOption')}</option>
				{#each properties as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
		<div class="field">
			<label for="baselineFilter">{$t('results.filterBaseline')}</label>
			<select
				id="baselineFilter"
				class="select"
				bind:value={baselineFilter}
				on:change={(event) =>
					void updateRouteFilter(
						'baseline_normalized',
						(event.currentTarget as HTMLSelectElement).value
					)}
			>
				<option value="">{$t('results.allOption')}</option>
				{#each baselines as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
		<div class="field">
			<label for="testConditionFilter">{$t('results.filterTest')}</label>
			<select
				id="testConditionFilter"
				class="select"
				bind:value={testConditionFilter}
				on:change={(event) =>
					void updateRouteFilter(
						'test_condition_normalized',
						(event.currentTarget as HTMLSelectElement).value
					)}
			>
				<option value="">{$t('results.allOption')}</option>
				{#each testConditions as item}
					<option value={item}>{item}</option>
				{/each}
			</select>
		</div>
	</div>

	{#if error && !showFallbackState}
		<div class="status status--error" role="alert">{error}</div>
	{:else if loading}
		<div class="status" role="status">{$t('results.loading')}</div>
	{:else if showFallbackState}
		<article class="result-card">
			<h3>{stateCardTitle()}</h3>
			<p class="result-text">{stateCardBody()}</p>
			<div class="table-actions">
				<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
			</div>
		</article>
	{:else if items.length}
		<div class="table-wrapper">
			<table class="data-table">
				<thead>
					<tr>
						<th>{$t('results.tableMaterial')}</th>
						<th>{$t('results.tableMeasurement')}</th>
						<th>{$t('results.tableContext')}</th>
						<th>{$t('results.tableStatus')}</th>
						<th>{$t('results.tableDocument')}</th>
						<th>{$t('results.tableActions')}</th>
					</tr>
				</thead>
				<tbody>
					{#each items as item}
						<tr>
							<td>
								<div>{item.material_label}</div>
								{#if item.variant_label}
									<div class="note">{item.variant_label}</div>
								{/if}
							</td>
							<td>
								<div>{item.property}</div>
								<div class="note">{item.summary}</div>
							</td>
							<td>
								<div>{item.baseline || '--'}</div>
								<div class="note">{item.test_condition || '--'}</div>
								{#if item.process}
									<div class="note">{item.process}</div>
								{/if}
							</td>
							<td>
								<div>{item.comparability_status}</div>
								<div class="note">{item.traceability_status}</div>
							</td>
							<td>{item.document_title}</td>
							<td>
								<div class="table-actions">
									<a class="btn btn--ghost btn--small" href={resultHref(item)}>
										{$t('results.openResult')}
									</a>
									<a class="btn btn--ghost btn--small" href={documentHref(item)}>
										{$t('traceback.viewSource')}
									</a>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<p class="note">{$t('results.empty')}</p>
	{/if}
</section>
