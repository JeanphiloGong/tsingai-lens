<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { tick } from 'svelte';
	import { errorMessage } from '../../../../_shared/api';
	import {
		fetchDocumentComparisonSemantics,
		type DocumentChainTestCondition,
		type DocumentComparisonSemanticsResponse,
		type DocumentResultChain
	} from '../../../../_shared/documents';
	import { t } from '../../../../_shared/i18n';
	import { fetchCollectionResults, type ResultListItem } from '../../../../_shared/results';
	import {
		buildDocumentViewerHref,
		fetchDocumentContent,
		fetchEvidenceTraceback,
		type DocumentContentResponse,
		type DocumentContentSection,
		type EvidenceTracebackResponse,
		type TracebackAnchor
	} from '../../../../_shared/traceback';

	let content: DocumentContentResponse | null = null;
	let traceback: EvidenceTracebackResponse | null = null;
	let loading = false;
	let contentError = '';
	let tracebackError = '';
	let loadedKey = '';
	let selectedAnchorId = '';
	let resolvedDocumentId = '';
	let relatedResults: ResultListItem[] = [];
	let relatedResultsLoading = false;
	let relatedResultsError = '';
	let comparisonSemantics: DocumentComparisonSemanticsResponse | null = null;
	let evidenceChainsLoading = false;
	let evidenceChainsError = '';

	$: collectionId = $page.params.id ?? '';
	$: routeDocumentId = $page.params.document_id ?? '';
	$: evidenceId = $page.url.searchParams.get('evidence_id')?.trim() ?? '';
	$: requestedAnchorId = $page.url.searchParams.get('anchor_id')?.trim() ?? '';
	$: loadKey = [collectionId, routeDocumentId, evidenceId, requestedAnchorId].join(':');
	$: selectedAnchor =
		traceback?.anchors.find((anchor) => anchor.anchor_id === selectedAnchorId) ??
		traceback?.anchors[0] ??
		null;
	$: variantDossiers = comparisonSemantics?.variant_dossiers ?? [];
	$: if (collectionId && routeDocumentId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadDocumentViewer();
	}

	function defaultReturnTo() {
		return `/collections/${collectionId}/documents`;
	}

	function backHref() {
		const target = $page.url.searchParams.get('return_to')?.trim();
		if (target && target.startsWith(`/collections/${collectionId}`)) {
			return target;
		}
		return defaultReturnTo();
	}

	async function loadDocumentViewer() {
		loading = true;
		contentError = '';
		tracebackError = '';
		content = null;
		traceback = null;
		selectedAnchorId = '';
		resolvedDocumentId = routeDocumentId;
		relatedResults = [];
		relatedResultsError = '';
		relatedResultsLoading = false;
		comparisonSemantics = null;
		evidenceChainsError = '';
		evidenceChainsLoading = false;
		let initialAnchor: TracebackAnchor | null = null;

		if (evidenceId) {
			try {
				traceback = await fetchEvidenceTraceback(collectionId, evidenceId);
				initialAnchor =
					traceback.anchors.find((anchor) => anchor.anchor_id === requestedAnchorId) ??
					traceback.anchors[0] ??
					null;
				selectedAnchorId = initialAnchor?.anchor_id ?? '';
				if (initialAnchor?.document_id) {
					resolvedDocumentId = initialAnchor.document_id;
				}
			} catch (err) {
				tracebackError = errorMessage(err);
			}
		}

		try {
			content = await fetchDocumentContent(collectionId, resolvedDocumentId);
			resolvedDocumentId = content.document_id;
			if (browser && resolvedDocumentId !== routeDocumentId) {
				history.replaceState(
					history.state,
					'',
					buildDocumentViewerHref(collectionId, resolvedDocumentId, {
						evidenceId,
						anchorId: selectedAnchorId || requestedAnchorId || null,
						returnTo: backHref()
					})
				);
			}
		} catch (err) {
			contentError = errorMessage(err);
		} finally {
			loading = false;
		}

		if (!contentError && resolvedDocumentId) {
			relatedResultsLoading = true;
			evidenceChainsLoading = true;

			const [resultResponse, semanticsResponse] = await Promise.allSettled([
				fetchCollectionResults(collectionId, {
					source_document_id: resolvedDocumentId,
					limit: 20
				}),
				fetchDocumentComparisonSemantics(collectionId, resolvedDocumentId, {
					includeGroupedProjections: true
				})
			]);

			if (resultResponse.status === 'fulfilled') {
				relatedResults = resultResponse.value.items;
			} else {
				relatedResultsError = errorMessage(resultResponse.reason);
			}

			if (semanticsResponse.status === 'fulfilled') {
				comparisonSemantics = semanticsResponse.value;
			} else {
				evidenceChainsError = errorMessage(semanticsResponse.reason);
			}

			relatedResultsLoading = false;
			evidenceChainsLoading = false;
		}

		if (initialAnchor?.section_id) {
			await scrollToSection(initialAnchor.section_id);
		}
	}

	function traceStatusLabel(status?: EvidenceTracebackResponse['traceback_status'] | null) {
		if (status === 'ready') return $t('traceback.statusReady');
		if (status === 'partial') return $t('traceback.statusPartial');
		return $t('traceback.statusUnavailable');
	}

	function traceStatusBody(status?: EvidenceTracebackResponse['traceback_status'] | null) {
		if (status === 'ready') return $t('traceback.statusReadyBody');
		if (status === 'partial') return $t('traceback.statusPartialBody');
		return $t('traceback.statusUnavailableBody');
	}

	function locatorLabel(anchor: TracebackAnchor) {
		if (anchor.locator_type === 'char_range') return $t('traceback.locatorCharRange');
		if (anchor.locator_type === 'bbox') return $t('traceback.locatorBBox');
		return $t('traceback.locatorSection');
	}

	function confidenceLabel(anchor: TracebackAnchor) {
		if (anchor.locator_confidence === 'high') return $t('traceback.confidenceHigh');
		if (anchor.locator_confidence === 'medium') return $t('traceback.confidenceMedium');
		return $t('traceback.confidenceLow');
	}

	function highlightParts(text: string, quote: string | null) {
		const normalizedQuote = quote?.trim();
		if (!normalizedQuote) return null;

		const index = text.indexOf(normalizedQuote);
		if (index < 0) return null;

		return {
			before: text.slice(0, index),
			match: text.slice(index, index + normalizedQuote.length),
			after: text.slice(index + normalizedQuote.length)
		};
	}

	function highlightFor(section: DocumentContentSection) {
		if (!selectedAnchor || selectedAnchor.section_id !== section.section_id) return null;
		return highlightParts(section.text, selectedAnchor.quote);
	}

	function sectionTitle(section: DocumentContentSection) {
		return section.title || section.section_type || section.section_id;
	}

	function pageLabel(section: DocumentContentSection) {
		if (section.page === null) return null;
		return $t('traceback.pageLabel', { page: section.page });
	}

	async function scrollToSection(sectionId: string) {
		if (!browser) return;
		await tick();
		const target = document.getElementById(`section-${sectionId}`);
		target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	async function selectAnchor(anchor: TracebackAnchor) {
		selectedAnchorId = anchor.anchor_id;
		if (anchor.section_id) {
			await scrollToSection(anchor.section_id);
		}
	}

	function documentTitle() {
		return content?.title || routeDocumentId;
	}

	function documentSubtitle() {
		return content?.source_filename || null;
	}

	function sectionCount() {
		return content?.sections.length ?? 0;
	}

	function showTracebackPanel() {
		return Boolean(evidenceId || traceback || tracebackError);
	}

	function resultHref(result: ResultListItem) {
		return `/collections/${collectionId}/results/${encodeURIComponent(result.result_id)}`;
	}

	function chainHref(chain: DocumentResultChain) {
		return `/collections/${collectionId}/results/${encodeURIComponent(chain.result_id)}`;
	}

	function formatOptional(value: unknown, unit?: string | null) {
		if (value === null || value === undefined) return null;
		if (typeof value === 'string' && value.trim() === '') return null;
		const text =
			typeof value === 'boolean' ? (value ? $t('results.yes') : $t('results.no')) : String(value);
		const unitText = unit?.trim();
		return unitText ? `${text} ${unitText}` : text;
	}

	function formatMeasurementValue(value: number | null, unit: string | null) {
		return formatOptional(value, unit) ?? '--';
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

	function recordEntries(record: Record<string, unknown> | null | undefined) {
		return Object.entries(record ?? {})
			.map(([key, value]) => ({ key, value: formatRecordValue(value) }))
			.filter((entry): entry is { key: string; value: string } => entry.value !== null);
	}

	function testConditionRows(condition: DocumentChainTestCondition) {
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

	function chainConditionSummary(chain: DocumentResultChain) {
		const rows = testConditionRows(chain.test_condition);
		return rows.map((row) => `${row.label}: ${row.value}`).join(' · ');
	}
</script>

<svelte:head>
	<title>{$t('traceback.title')}</title>
</svelte:head>

<section class="card fade-up">
	<div class="card-header-inline">
		<div>
			<h2>{$t('traceback.title')}</h2>
			<p class="lead">{$t('traceback.lead')}</p>
		</div>
		<a class="btn btn--ghost btn--small" href={backHref()}>
			{$t('traceback.back')}
		</a>
	</div>

	{#if loading}
		<div class="status" role="status">{$t('traceback.loading')}</div>
	{:else}
		{#if contentError}
			<div class="status status--error" role="alert">{contentError}</div>
		{/if}

		{#if tracebackError}
			<div class="status status--error" role="alert">{tracebackError}</div>
		{/if}

		<div class="result-grid result-grid--tasks">
			<article class="result-card">
				<h3>{$t('traceback.documentCardTitle')}</h3>
				<dl class="detail-list">
					<div class="detail-row">
						<dt>{$t('traceback.documentLabel')}</dt>
						<dd>{documentTitle()}</dd>
					</div>
					{#if documentSubtitle()}
						<div class="detail-row">
							<dt>{$t('traceback.sourceFileLabel')}</dt>
							<dd>{documentSubtitle()}</dd>
						</div>
					{/if}
					<div class="detail-row">
						<dt>{$t('traceback.sectionCountLabel')}</dt>
						<dd>{sectionCount()}</dd>
					</div>
					{#if content?.page_count !== null}
						<div class="detail-row">
							<dt>{$t('traceback.pageCountLabel')}</dt>
							<dd>{content?.page_count}</dd>
						</div>
					{/if}
				</dl>
			</article>

			{#if showTracebackPanel()}
				<article class="result-card">
					<h3>{$t('traceback.traceCardTitle')}</h3>
					<p class="result-text">{traceStatusLabel(traceback?.traceback_status)}</p>
					<p class="note">{traceStatusBody(traceback?.traceback_status)}</p>
					{#if selectedAnchor}
						<dl class="detail-list">
							<div class="detail-row">
								<dt>{$t('traceback.locatorLabel')}</dt>
								<dd>{locatorLabel(selectedAnchor)}</dd>
							</div>
							<div class="detail-row">
								<dt>{$t('traceback.precisionLabel')}</dt>
								<dd>{confidenceLabel(selectedAnchor)}</dd>
							</div>
							{#if selectedAnchor.page !== null}
								<div class="detail-row">
									<dt>{$t('traceback.pageNumberLabel')}</dt>
									<dd>{selectedAnchor.page}</dd>
								</div>
							{/if}
						</dl>
					{/if}
				</article>
			{/if}

			{#if !contentError}
				<article class="result-card document-chain-card">
					<h3>{$t('results.documentChainsTitle')}</h3>
					<p class="note">{$t('results.documentChainsLead')}</p>
					{#if evidenceChainsLoading}
						<div class="status" role="status">{$t('results.loading')}</div>
					{:else if evidenceChainsError}
						<div class="status status--error" role="alert">{evidenceChainsError}</div>
					{:else if variantDossiers.length}
						<div class="document-chain-stack">
							{#each variantDossiers as dossier}
								{@const processEntries = recordEntries(dossier.shared_process_state)}
								<section class="document-chain-dossier">
									<div class="table-main">
										<div class="table-title">{dossier.variant_label || dossier.material.label}</div>
										<div class="table-sub">{dossier.material.label}</div>
									</div>

									<dl class="detail-list">
										{#if dossier.material.composition}
											<div class="detail-row">
												<dt>{$t('results.fieldComposition')}</dt>
												<dd>{dossier.material.composition}</dd>
											</div>
										{/if}
										{#if processEntries.length}
											<div class="detail-row detail-row--wide">
												<dt>{$t('results.fieldProcessState')}</dt>
												<dd>
													{#each processEntries as entry, index}
														{index ? ', ' : ''}{entry.key}={entry.value}
													{/each}
												</dd>
											</div>
										{/if}
									</dl>

									{#if dossier.shared_missingness.length}
										<div class="detail-section">
											<div class="detail-section__title">{$t('results.fieldMissingness')}</div>
											<ul class="result-list">
												{#each dossier.shared_missingness as item}
													<li>{item}</li>
												{/each}
											</ul>
										</div>
									{/if}

									{#each dossier.series as series}
										<section class="detail-section document-chain-series">
											<div class="detail-section__title">
												{series.property_family} · {series.test_family}
											</div>
											<p class="note">
												{$t('results.fieldVaryingAxis')}: {series.varying_axis.axis_name || '--'}
												{series.varying_axis.axis_unit ? ` (${series.varying_axis.axis_unit})` : ''}
											</p>
											{#if series.chains.length}
												<ul class="result-list document-chain-list">
													{#each series.chains as chain}
														<li>
															<a href={chainHref(chain)}>
																{chain.measurement.property} · {formatMeasurementValue(
																	chain.measurement.value,
																	chain.measurement.unit
																)}
															</a>
															<div class="note">{chain.assessment.comparability_status}</div>
															{#if chainConditionSummary(chain)}
																<div class="note">{chainConditionSummary(chain)}</div>
															{/if}
															{#if chain.baseline.label}
																<div class="note">
																	{$t('results.fieldBaseline')}: {chain.baseline.label}
																</div>
															{/if}
														</li>
													{/each}
												</ul>
											{:else}
												<p class="note">{$t('results.documentChainsEmpty')}</p>
											{/if}
										</section>
									{/each}
								</section>
							{/each}
						</div>
					{:else}
						<p class="note">{$t('results.documentChainsEmpty')}</p>
					{/if}
				</article>
			{/if}

			{#if relatedResultsLoading || relatedResults.length || relatedResultsError}
				<article class="result-card">
					<h3>{$t('results.relatedTitle')}</h3>
					<p class="note">{$t('results.relatedLead')}</p>
					{#if relatedResultsLoading}
						<div class="status" role="status">{$t('results.loading')}</div>
					{:else if relatedResultsError}
						<div class="status status--error" role="alert">{relatedResultsError}</div>
					{:else}
						<ul class="result-list">
							{#each relatedResults as result}
								<li>
									<a href={resultHref(result)}>
										{result.material_label} · {result.property}
									</a>
									<span class="note"> ({result.comparability_status})</span>
								</li>
							{/each}
						</ul>
					{/if}
				</article>
			{/if}
		</div>

		{#if showTracebackPanel() && traceback?.anchors.length}
			<section class="detail-section">
				<div class="detail-section__title">{$t('traceback.anchorsTitle')}</div>
				<div class="result-grid">
					{#each traceback.anchors as anchor}
						<button
							class:selected-anchor={selectedAnchor?.anchor_id === anchor.anchor_id}
							class="result-card traceback-anchor"
							type="button"
							on:click={() => void selectAnchor(anchor)}
						>
							<div class="table-main">
								<div class="table-title">{locatorLabel(anchor)}</div>
								<div class="table-sub">{confidenceLabel(anchor)}</div>
							</div>
							{#if anchor.quote}
								<p class="result-text">{anchor.quote}</p>
							{/if}
							<div class="note">
								{#if anchor.page !== null}
									{$t('traceback.pageLabel', { page: anchor.page })}
								{/if}
								{#if anchor.section_id}
									{anchor.page !== null ? ' · ' : ''}{$t('traceback.sectionLabel', {
										section: anchor.section_id
									})}
								{/if}
							</div>
						</button>
					{/each}
				</div>
			</section>
		{/if}

		{#if content?.sections.length}
			<section class="detail-section">
				<div class="detail-section__title">{$t('traceback.sectionsTitle')}</div>
				<div class="section-nav">
					{#each content.sections as section}
						<button
							class="btn btn--ghost btn--small"
							type="button"
							on:click={() => void scrollToSection(section.section_id)}
						>
							{sectionTitle(section)}
						</button>
					{/each}
				</div>
			</section>

			<section class="result-grid">
				{#each content.sections as section}
					<article
						class:document-section--active={selectedAnchor?.section_id === section.section_id}
						class="result-card document-section"
						id={`section-${section.section_id}`}
					>
						<div class="table-main">
							<div class="table-title">{sectionTitle(section)}</div>
							{#if pageLabel(section)}
								<div class="table-sub">{pageLabel(section)}</div>
							{/if}
						</div>

						{#if highlightFor(section)}
							{@const parts = highlightFor(section)}
							{#if parts}
								<p class="document-text">{parts.before}<mark>{parts.match}</mark>{parts.after}</p>
							{:else}
								<p class="document-text">{section.text}</p>
							{/if}
						{:else}
							<p class="document-text">{section.text}</p>
						{/if}

						{#if selectedAnchor?.section_id === section.section_id && selectedAnchor.quote && !highlightFor(section)}
							<section class="detail-section">
								<div class="detail-section__title">{$t('traceback.quoteTitle')}</div>
								<p class="result-text">{selectedAnchor.quote}</p>
							</section>
						{/if}
					</article>
				{/each}
			</section>
		{:else if !contentError}
			<p class="note">{$t('traceback.empty')}</p>
		{/if}
	{/if}
</section>

<style>
	.traceback-anchor {
		width: 100%;
		text-align: left;
	}

	.selected-anchor {
		border-color: var(--accent, #2f5bd2);
		box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent, #2f5bd2) 40%, transparent);
	}

	.section-nav {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.document-section {
		scroll-margin-top: 5rem;
	}

	.document-section--active {
		border-color: var(--accent, #2f5bd2);
	}

	.document-text {
		white-space: pre-wrap;
		line-height: 1.7;
	}

	.document-chain-card {
		grid-column: 1 / -1;
	}

	.document-chain-stack,
	.document-chain-list {
		display: grid;
		gap: 0.75rem;
	}

	.document-chain-dossier {
		display: grid;
		gap: 0.75rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--color-line);
	}

	.document-chain-dossier:first-child {
		padding-top: 0;
		border-top: 0;
	}

	.document-chain-series {
		margin-top: 0;
	}
</style>
