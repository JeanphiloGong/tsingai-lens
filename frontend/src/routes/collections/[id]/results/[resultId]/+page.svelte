<script lang="ts">
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../../_shared/api';
	import { t } from '../../../../_shared/i18n';
	import { fetchCollectionResult, type ResultDetail } from '../../../../_shared/results';
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
	$: stateCardTitle = $t(`overview.surfaceStateCards.${surfaceState}.title`);
	$: stateCardBody = $t(`overview.surfaceStateCards.${surfaceState}.body`);
	$: resultTitleText = !result
		? resultId
		: `${result.material.label} · ${result.measurement.property}`;
	$: comparisonLinkHref = (() => {
		const actionHref = result?.actions.open_comparisons?.trim();
		if (actionHref) return actionHref;
		if (!result) return `/collections/${collectionId}/comparisons`;

		const params = new URLSearchParams();
		const property = result.measurement.property.trim();
		if (property) {
			params.set('property_normalized', property);
		}

		const query = params.toString();
		return query
			? `/collections/${collectionId}/comparisons?${query}`
			: `/collections/${collectionId}/comparisons`;
	})();
	$: sourceLinkHref = (() => {
		if (!result) return `/collections/${collectionId}/documents`;
		const evidenceId = result.evidence[0]?.evidence_id ?? null;
		return buildDocumentViewerHref(collectionId, result.document.document_id, {
			evidenceId,
			returnTo: $page.url.pathname
		});
	})();
	$: hasEvidenceChain =
		Boolean(result) &&
		Boolean(
			result?.variant_dossier ||
			result?.test_condition_detail ||
			result?.baseline_detail ||
			result?.structure_support.length ||
			result?.value_provenance ||
			result?.series_navigation
		);
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

	function formatOptional(value: unknown, unit?: string | null) {
		if (value === null || value === undefined) return null;
		if (typeof value === 'string' && value.trim() === '') return null;
		const text =
			typeof value === 'boolean' ? (value ? $t('results.yes') : $t('results.no')) : String(value);
		const unitText = unit?.trim();
		return unitText ? `${text} ${unitText}` : text;
	}

	function formatScalar(value: unknown) {
		if (value === null || value === undefined) return '--';
		if (typeof value === 'string') return value.trim() || '--';
		if (typeof value === 'number' || typeof value === 'boolean') return String(value);
		return JSON.stringify(value);
	}

	function formatRecordValue(value: unknown) {
		if (value === null || value === undefined) return null;
		if (typeof value === 'string' && value.trim() === '') return null;
		if (typeof value === 'boolean') return value ? $t('results.yes') : $t('results.no');
		if (typeof value === 'object') return JSON.stringify(value);
		return String(value);
	}

	function formatMeasurementValue(value: number | null, unit: string | null) {
		return formatOptional(value, unit) ?? '--';
	}

	function recordEntries(record: Record<string, unknown> | null | undefined) {
		return Object.entries(record ?? {})
			.map(([key, value]) => ({ key, value: formatRecordValue(value) }))
			.filter((entry): entry is { key: string; value: string } => entry.value !== null);
	}

	function testConditionRows(condition: ResultDetail['test_condition_detail']) {
		if (!condition) return [];
		return [
			{ label: $t('results.fieldTestMethod'), value: formatOptional(condition.test_method) },
			{
				label: $t('results.fieldTestTemperature'),
				value: formatOptional(condition.test_temperature_c, 'C')
			},
			{ label: $t('results.fieldStrainRate'), value: formatOptional(condition.strain_rate_s_1) },
			{
				label: $t('results.fieldLoadingDirection'),
				value: formatOptional(condition.loading_direction)
			},
			{
				label: $t('results.fieldSampleOrientation'),
				value: formatOptional(condition.sample_orientation)
			},
			{ label: $t('results.fieldEnvironment'), value: formatOptional(condition.environment) },
			{ label: $t('results.fieldFrequency'), value: formatOptional(condition.frequency_hz, 'Hz') },
			{
				label: $t('results.fieldSpecimenGeometry'),
				value: formatOptional(condition.specimen_geometry)
			},
			{ label: $t('results.fieldSurfaceState'), value: formatOptional(condition.surface_state) }
		].filter((row): row is { label: string; value: string } => row.value !== null);
	}

	function baselineRows(baseline: ResultDetail['baseline_detail']) {
		if (!baseline) return [];
		return [
			{ label: $t('results.fieldBaseline'), value: formatOptional(baseline.label) },
			{ label: $t('results.fieldBaselineReference'), value: formatOptional(baseline.reference) },
			{ label: $t('results.fieldBaselineType'), value: formatOptional(baseline.baseline_type) },
			{ label: $t('results.fieldResolved'), value: formatOptional(baseline.resolved) },
			{ label: $t('results.fieldBaselineScope'), value: formatOptional(baseline.baseline_scope) }
		].filter((row): row is { label: string; value: string } => row.value !== null);
	}

	function provenanceRows(provenance: ResultDetail['value_provenance']) {
		if (!provenance) return [];
		return [
			{ label: $t('results.fieldValueOrigin'), value: formatOptional(provenance.value_origin) },
			{
				label: $t('results.fieldSourceValue'),
				value: formatOptional(provenance.source_value_text)
			},
			{ label: $t('results.fieldSourceUnit'), value: formatOptional(provenance.source_unit_text) },
			{
				label: $t('results.fieldDerivationFormula'),
				value: formatOptional(provenance.derivation_formula)
			},
			{
				label: $t('results.fieldDerivationInputs'),
				value: formatRecordValue(provenance.derivation_inputs)
			}
		].filter((row): row is { label: string; value: string } => row.value !== null);
	}

	function siblingHref(siblingResultId: string) {
		return `/collections/${collectionId}/results/${encodeURIComponent(siblingResultId)}`;
	}

	function axisValue(value: string | number | null, unit: string | null) {
		return formatOptional(value, unit) ?? '--';
	}
</script>

<svelte:head>
	<title>{$t('results.detailTitle')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="card-header-inline">
		<div>
			<h2>{$t('results.detailTitle')}</h2>
			<p class="lead">{resultTitleText}</p>
		</div>
		<div class="table-actions">
			<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}/results`}>
				{$t('results.backToList')}
			</a>
			<a class="btn btn--ghost btn--small" href={comparisonLinkHref}>
				{$t('results.openComparisons')}
			</a>
			<a class="btn btn--ghost btn--small" href={sourceLinkHref}>
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
			<h3>{stateCardTitle}</h3>
			<p class="result-text">{stateCardBody}</p>
			<div class="table-actions">
				<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
					{$t('overview.goToWorkspace')}
				</a>
			</div>
		</article>
	{:else if result}
		{#if hasEvidenceChain}
			<section class="detail-section">
				<div class="detail-section__title">{$t('results.chainTitle')}</div>
				<div class="result-grid result-grid--tasks">
					{#if result.variant_dossier}
						{@const processEntries = recordEntries(result.variant_dossier.shared_process_state)}
						<article class="result-card">
							<h3>{$t('results.variantDossierTitle')}</h3>
							<dl class="detail-list">
								<div class="detail-row">
									<dt>{$t('results.fieldMaterial')}</dt>
									<dd>{result.variant_dossier.material.label}</dd>
								</div>
								{#if result.variant_dossier.variant_label}
									<div class="detail-row">
										<dt>{$t('results.fieldVariant')}</dt>
										<dd>{result.variant_dossier.variant_label}</dd>
									</div>
								{/if}
								{#if result.variant_dossier.material.composition}
									<div class="detail-row">
										<dt>{$t('results.fieldComposition')}</dt>
										<dd>{result.variant_dossier.material.composition}</dd>
									</div>
								{/if}
							</dl>

							{#if processEntries.length}
								<div class="detail-section">
									<div class="detail-section__title">{$t('results.fieldProcessState')}</div>
									<dl class="detail-list">
										{#each processEntries as entry}
											<div class="detail-row">
												<dt>{entry.key}</dt>
												<dd>{entry.value}</dd>
											</div>
										{/each}
									</dl>
								</div>
							{/if}

							{#if result.variant_dossier.shared_missingness.length}
								<div class="detail-section">
									<div class="detail-section__title">{$t('results.fieldMissingness')}</div>
									<ul class="result-list">
										{#each result.variant_dossier.shared_missingness as item}
											<li>{item}</li>
										{/each}
									</ul>
								</div>
							{/if}
						</article>
					{/if}

					{#if result.test_condition_detail}
						{@const rows = testConditionRows(result.test_condition_detail)}
						<article class="result-card">
							<h3>{$t('results.testConditionDetailTitle')}</h3>
							{#if rows.length}
								<dl class="detail-list">
									{#each rows as row}
										<div class="detail-row">
											<dt>{row.label}</dt>
											<dd>{row.value}</dd>
										</div>
									{/each}
								</dl>
							{:else}
								<p class="note">{$t('results.noEvidence')}</p>
							{/if}
						</article>
					{/if}

					{#if result.baseline_detail}
						{@const rows = baselineRows(result.baseline_detail)}
						<article class="result-card">
							<h3>{$t('results.baselineDetailTitle')}</h3>
							<dl class="detail-list">
								{#each rows as row}
									<div class="detail-row">
										<dt>{row.label}</dt>
										<dd>{row.value}</dd>
									</div>
								{/each}
							</dl>
						</article>
					{/if}

					{#if result.value_provenance}
						{@const rows = provenanceRows(result.value_provenance)}
						<article class="result-card">
							<h3>{$t('results.valueProvenanceTitle')}</h3>
							<dl class="detail-list">
								{#each rows as row}
									<div class="detail-row">
										<dt>{row.label}</dt>
										<dd>{row.value}</dd>
									</div>
								{/each}
							</dl>
						</article>
					{/if}

					{#if result.structure_support.length}
						<article class="result-card">
							<h3>{$t('results.structureSupportTitle')}</h3>
							<ul class="result-list chain-list">
								{#each result.structure_support as support}
									{@const supportEntries = recordEntries(support.condition)}
									<li>
										<div>{support.summary}</div>
										<div class="note">
											{$t('results.fieldSupportType')}: {support.support_type}
										</div>
										{#if supportEntries.length}
											<div class="note">
												{$t('results.fieldCondition')}:
												{#each supportEntries as entry, index}
													{index ? ', ' : ''}{entry.key}={entry.value}
												{/each}
											</div>
										{/if}
									</li>
								{/each}
							</ul>
						</article>
					{/if}

					{#if result.series_navigation}
						<article class="result-card">
							<h3>{$t('results.seriesNavigationTitle')}</h3>
							<dl class="detail-list">
								<div class="detail-row">
									<dt>{$t('results.fieldSeries')}</dt>
									<dd>{result.series_navigation.series_key || '--'}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldVaryingAxis')}</dt>
									<dd>
										{result.series_navigation.varying_axis.axis_name || '--'}
										{result.series_navigation.varying_axis.axis_unit
											? ` (${result.series_navigation.varying_axis.axis_unit})`
											: ''}
									</dd>
								</div>
							</dl>
							{#if result.series_navigation.siblings.length}
								<ul class="result-list chain-list">
									{#each result.series_navigation.siblings as sibling}
										<li>
											<a href={siblingHref(sibling.result_id)}>
												{axisValue(sibling.axis_value, sibling.axis_unit)} · {formatMeasurementValue(
													sibling.measurement.value,
													sibling.measurement.unit
												)}
											</a>
											<div class="note">{sibling.measurement.property}</div>
										</li>
									{/each}
								</ul>
							{:else}
								<p class="note">{$t('results.noSeriesSiblings')}</p>
							{/if}
						</article>
					{/if}
				</div>
			</section>
		{/if}

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
						<dd>
							{result.assessment.requires_expert_review
								? $t('results.reviewYes')
								: $t('results.reviewNo')}
						</dd>
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

<style>
	.chain-list {
		display: grid;
		gap: 0.75rem;
	}
</style>
