<script lang="ts">
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import {
		fetchCollectionResult,
		type ResultDetail
	} from '../../../../_shared/results';
	import { buildDocumentViewerHref } from '../../../../_shared/traceback';
	import {
		fetchWorkspaceOverview,
		getWorkspaceSurfaceState,
		type WorkspaceOverview
	} from '../../../../_shared/workspace';

	$: collectionId = $page.params.id ?? '';
	$: resultId = $page.params.resultId ?? '';

	let result: ResultDetail | null = null;
	let workspace: WorkspaceOverview | null = null;
	let loading = false;
	let error = '';
	let loadedKey = '';
	let notFound = false;

	$: surfaceState = getWorkspaceSurfaceState(workspace, 'results');
	$: showFallbackState =
		Boolean(workspace) && !loading && !result && (surfaceState !== 'ready' || notFound);
	$: requestKey = collectionId && resultId ? `${collectionId}:${resultId}` : '';
	$: if (requestKey && requestKey !== loadedKey) {
		loadedKey = requestKey;
		void loadResult();
	}

	async function loadResult() {
		loading = true;
		error = '';
		notFound = false;

		const [resultResponse, workspaceResponse] = await Promise.allSettled([
			fetchCollectionResult(collectionId, resultId),
			fetchWorkspaceOverview(collectionId)
		]);

		workspace = workspaceResponse.status === 'fulfilled' ? workspaceResponse.value : null;

		if (resultResponse.status === 'fulfilled') {
			result = resultResponse.value;
			loading = false;
			return;
		}

		result = null;
		notFound = isHttpStatusError(resultResponse.reason, 404);
		error = errorMessage(resultResponse.reason);
		loading = false;
	}

	function stateCardTitle() {
		return $t(`overview.surfaceStateCards.${surfaceState}.title`);
	}

	function stateCardBody() {
		return $t(`overview.surfaceStateCards.${surfaceState}.body`);
	}

	function titleText() {
		if (!result) return resultId;
		return `${result.material.label} · ${result.measurement.property}`;
	}

	function comparisonHref() {
		return result?.actions.open_comparisons || `/collections/${collectionId}/comparisons`;
	}

	function sourceHref() {
		if (!result) return `/collections/${collectionId}/documents`;
		const evidenceId = result.evidence[0]?.evidence_id ?? null;
		return buildDocumentViewerHref(collectionId, result.document.document_id, {
			evidenceId,
			returnTo: $page.url.pathname
		});
	}
</script>

<svelte:head>
	<title>{$t('results.detailTitle')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="card-header-inline">
		<div>
			<h2>{$t('results.detailTitle')}</h2>
			<p class="lead">{titleText()}</p>
		</div>
		<div class="table-actions">
			<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/results`}>
				{$t('results.backToList')}
			</a>
			<a class="btn btn--ghost btn--small" href={comparisonHref()}>
				{$t('results.openComparisons')}
			</a>
			<a class="btn btn--ghost btn--small" href={sourceHref()}>
				{$t('traceback.viewSource')}
			</a>
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
	{:else if result}
		<div class="result-grid result-grid--tasks">
			<article class="result-card">
				<h3>{$t('results.measurementTitle')}</h3>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('results.fieldProperty')}</dt>
						<dd>{result.measurement.property}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldValue')}</dt>
						<dd>{result.measurement.value ?? '--'} {result.measurement.unit ?? ''}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldSummary')}</dt>
						<dd>{result.measurement.summary}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldMaterial')}</dt>
						<dd>{result.material.label}</dd>
					</div>
					{#if result.material.variant_label}
						<div class="detail-row">
							<dt>{$t('results.fieldVariant')}</dt>
							<dd>{result.material.variant_label}</dd>
						</div>
					{/if}
				</dl>
			</article>

			<article class="result-card">
				<h3>{$t('results.contextTitle')}</h3>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('results.fieldBaseline')}</dt>
						<dd>{result.context.baseline || '--'}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldTest')}</dt>
						<dd>{result.context.test_condition || '--'}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldProcess')}</dt>
						<dd>{result.context.process || '--'}</dd>
					</div>
					{#if result.context.axis_name}
						<div class="detail-row">
							<dt>{$t('results.fieldAxis')}</dt>
							<dd>{result.context.axis_name}: {result.context.axis_value ?? '--'}</dd>
						</div>
					{/if}
				</dl>
			</article>

			<article class="result-card">
				<h3>{$t('results.assessmentTitle')}</h3>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('results.fieldComparability')}</dt>
						<dd>{result.assessment.comparability_status}</dd>
					</div>
					<div class="detail-row">
						<dt>{$t('results.fieldReview')}</dt>
						<dd>{result.assessment.requires_expert_review ? $t('results.reviewYes') : $t('results.reviewNo')}</dd>
					</div>
				</dl>
				{#if result.assessment.warnings.length}
					<div class="detail-section">
						<div class="detail-section__title">{$t('results.warningsTitle')}</div>
						<ul class="result-list">
							{#each result.assessment.warnings as item}
								<li>{item}</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if result.assessment.missing_context.length}
					<div class="detail-section">
						<div class="detail-section__title">{$t('results.missingContextTitle')}</div>
						<ul class="result-list">
							{#each result.assessment.missing_context as item}
								<li>{item}</li>
							{/each}
						</ul>
					</div>
				{/if}
			</article>
		</div>

		<div class="result-grid result-grid--tasks">
			<article class="result-card">
				<h3>{$t('results.documentTitle')}</h3>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('results.fieldDocument')}</dt>
						<dd>{result.document.title}</dd>
					</div>
					{#if result.document.source_filename}
						<div class="detail-row">
							<dt>{$t('results.fieldSourceFile')}</dt>
							<dd>{result.document.source_filename}</dd>
						</div>
					{/if}
				</dl>
			</article>

			<article class="result-card">
				<h3>{$t('results.evidenceTitle')}</h3>
				{#if result.evidence.length}
					<ul class="result-list">
						{#each result.evidence as item}
							<li>
								<div>{item.evidence_id}</div>
								<div class="note">{item.traceability_status}</div>
							</li>
						{/each}
					</ul>
				{:else}
					<p class="note">{$t('results.noEvidence')}</p>
				{/if}
			</article>
		</div>
	{/if}
</section>
