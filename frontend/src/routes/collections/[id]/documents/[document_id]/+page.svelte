<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { tick } from 'svelte';
	import { errorMessage } from '../../../../_shared/api';
	import {
		fetchDocumentComparisonSemantics,
		type DocumentChainTestCondition,
		type DocumentComparisonSemanticsResponse,
		type DocumentResultChain,
		type DocumentResultSeries,
		type DocumentVariantDossier
	} from '../../../../_shared/documents';
	import { t } from '../../../../_shared/i18n';
	import { fetchCollectionResults, type ResultListItem } from '../../../../_shared/results';
	import {
		buildDocumentViewerHref,
		fetchDocumentContent,
		fetchEvidenceTraceback,
		type DocumentContentBlock,
		type DocumentContentResponse,
		type EvidenceTracebackResponse,
		type TracebackAnchor
	} from '../../../../_shared/traceback';

	type ChainContext = {
		dossier: DocumentVariantDossier;
		series: DocumentResultSeries;
		chain: DocumentResultChain;
	};

	type SourceTextSegment = {
		key: string;
		blockId: string | null;
		start: number;
		end: number;
		text: string;
	};

	type SourceTextHighlight = {
		start: number;
		end: number;
	};

	type SourceSectionNavItem = {
		blockId: string;
		label: string;
	};

	type Translate = (key: string, vars?: Record<string, string | number>) => string;

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
	let selectedChainId = '';
	let selectedEvidenceId = '';
	let sourceLocationStatus: 'idle' | 'loading' | 'located' | 'unavailable' | 'error' = 'idle';
	let sourceLocationMessage = '';

	$: collectionId = $page.params.id ?? '';
	$: routeDocumentId = $page.params.document_id ?? '';
	$: requestedResultId = $page.url.searchParams.get('result_id')?.trim() ?? '';
	$: evidenceId = $page.url.searchParams.get('evidence_id')?.trim() ?? '';
	$: requestedAnchorId = $page.url.searchParams.get('anchor_id')?.trim() ?? '';
	$: loadKey = [
		collectionId,
		routeDocumentId,
		requestedResultId,
		evidenceId,
		requestedAnchorId
	].join(':');
	$: selectedAnchor =
		traceback?.anchors.find((anchor) => anchor.anchor_id === selectedAnchorId) ??
		traceback?.anchors[0] ??
		null;
	$: variantDossiers = comparisonSemantics?.variant_dossiers ?? [];
	$: selectedChainContext = findChainContext(variantDossiers, selectedChainId);
	$: selectedChain = selectedChainContext?.chain ?? null;
	$: localGraphContext = selectedChainContext ?? firstChainContext(variantDossiers);
	$: localGraphChain = localGraphContext?.chain ?? null;
	$: sourceText = sourceTextForContent(content);
	$: sourceTextSegments = sourceSegmentsForContent(content, sourceText);
	$: sourceSectionNavItems = sectionNavItemsForContent(content?.blocks ?? [], $t);
	$: selectedSourceHighlight = sourceHighlightForAnchor(selectedAnchor, sourceText);
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
		selectedChainId = requestedResultId;
		selectedEvidenceId = evidenceId;
		sourceLocationStatus = evidenceId ? 'loading' : 'idle';
		sourceLocationMessage = '';
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
				sourceLocationStatus = initialAnchor ? 'located' : 'unavailable';
			} catch (err) {
				tracebackError = errorMessage(err);
				sourceLocationStatus = 'error';
				sourceLocationMessage = tracebackError;
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
				if (!selectedChainId && evidenceId) {
					selectedChainId = findChainIdByEvidence(comparisonSemantics.variant_dossiers, evidenceId);
				}
			} else {
				evidenceChainsError = errorMessage(semanticsResponse.reason);
			}

			relatedResultsLoading = false;
			evidenceChainsLoading = false;
		}

		if (initialAnchor) {
			await scrollToSourceAnchor(initialAnchor);
		}
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

	function sourceBlockIdForAnchor(anchor: TracebackAnchor | null) {
		return anchor?.block_id || anchor?.section_id || '';
	}

	function sourceTextForContent(response: DocumentContentResponse | null) {
		const text = response?.content_text.trim();
		if (text) return text;
		return [...(response?.blocks ?? [])]
			.sort((left, right) => left.order - right.order)
			.map((block) => block.text.trim())
			.filter((blockText) => blockText.length > 0)
			.join('\n\n');
	}

	function sortedBlocks(blocks: DocumentContentBlock[]) {
		return [...blocks].sort((left, right) => left.order - right.order);
	}

	function hasValidSourceRange(block: DocumentContentBlock, sourceTextLength: number) {
		return (
			block.start_offset !== null &&
			block.end_offset !== null &&
			block.start_offset >= 0 &&
			block.end_offset > block.start_offset &&
			block.end_offset <= sourceTextLength
		);
	}

	function sourceSegmentsForContent(
		response: DocumentContentResponse | null,
		text: string
	): SourceTextSegment[] {
		if (!response || !text) return [];

		const rangedBlocks = sortedBlocks(response.blocks).filter((block) =>
			hasValidSourceRange(block, text.length)
		);

		if (rangedBlocks.length) {
			const segments: SourceTextSegment[] = [];
			let cursor = 0;

			for (const block of rangedBlocks) {
				const rangeStart = Math.max(block.start_offset ?? 0, cursor);
				const rangeEnd = block.end_offset ?? rangeStart;
				if (rangeEnd <= cursor) continue;

				if (cursor < rangeStart) {
					segments.push({
						key: `gap-${cursor}-${rangeStart}`,
						blockId: null,
						start: cursor,
						end: rangeStart,
						text: text.slice(cursor, rangeStart)
					});
				}

				segments.push({
					key: `block-${block.block_id}`,
					blockId: block.block_id,
					start: rangeStart,
					end: rangeEnd,
					text: text.slice(rangeStart, rangeEnd)
				});
				cursor = rangeEnd;
			}

			if (cursor < text.length) {
				segments.push({
					key: `gap-${cursor}-${text.length}`,
					blockId: null,
					start: cursor,
					end: text.length,
					text: text.slice(cursor)
				});
			}

			return segments;
		}

		const blockSegments = sortedBlocks(response.blocks)
			.map((block) => block.text.trim())
			.filter((blockText) => blockText.length > 0);

		if (!blockSegments.length) {
			return [{ key: 'source-text', blockId: null, start: 0, end: text.length, text }];
		}

		const segments: SourceTextSegment[] = [];
		let cursor = 0;
		for (const block of sortedBlocks(response.blocks)) {
			const blockText = block.text.trim();
			if (!blockText) continue;

			if (segments.length) {
				segments.push({
					key: `gap-${cursor}-${cursor + 2}`,
					blockId: null,
					start: cursor,
					end: cursor + 2,
					text: '\n\n'
				});
				cursor += 2;
			}

			segments.push({
				key: `block-${block.block_id}`,
				blockId: block.block_id,
				start: cursor,
				end: cursor + blockText.length,
				text: blockText
			});
			cursor += blockText.length;
		}

		return segments.length
			? segments
			: [{ key: 'source-text', blockId: null, start: 0, end: text.length, text }];
	}

	function sectionLabel(block: DocumentContentBlock, translate: Translate) {
		return (
			block.heading_path?.trim() ||
			block.block_type?.trim() ||
			translate('traceback.sectionFallbackLabel', { index: block.order || 1 })
		);
	}

	function sectionNavItemsForContent(
		blocks: DocumentContentBlock[],
		translate: Translate
	): SourceSectionNavItem[] {
		const seen = new Set<string>();
		const items: SourceSectionNavItem[] = [];

		for (const block of sortedBlocks(blocks)) {
			const label = sectionLabel(block, translate);
			const normalizedLabel = label.toLowerCase().replace(/\s+/g, ' ').trim();
			if (!normalizedLabel || seen.has(normalizedLabel)) continue;
			seen.add(normalizedLabel);
			items.push({ blockId: block.block_id, label });
		}

		return items;
	}

	function sourceHighlightForAnchor(
		anchor: TracebackAnchor | null,
		text: string
	): SourceTextHighlight | null {
		if (!anchor || !text) return null;

		const range = anchor.char_range;
		if (range && range.start >= 0 && range.end > range.start && range.end <= text.length) {
			return {
				start: range.start,
				end: range.end
			};
		}

		const quoteParts = highlightParts(text, anchor.quote);
		if (!quoteParts) return null;

		return {
			start: quoteParts.before.length,
			end: quoteParts.before.length + quoteParts.match.length
		};
	}

	function segmentHighlightParts(
		segment: SourceTextSegment,
		highlight: SourceTextHighlight | null
	) {
		if (!highlight) return null;
		const start = Math.max(segment.start, highlight.start);
		const end = Math.min(segment.end, highlight.end);
		if (start >= end) return null;

		const localStart = start - segment.start;
		const localEnd = end - segment.start;

		return {
			before: segment.text.slice(0, localStart),
			match: segment.text.slice(localStart, localEnd),
			after: segment.text.slice(localEnd)
		};
	}

	async function scrollToBlock(blockId: string) {
		if (!browser || !blockId) return;
		await tick();
		const target = document.getElementById(`block-${blockId}`);
		if (target && typeof target.scrollIntoView === 'function') {
			target.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}

	async function scrollToSourceAnchor(anchor: TracebackAnchor | null) {
		if (!browser || !anchor) return;
		await tick();

		const highlightTarget = document.querySelector('.source-highlight');
		if (
			highlightTarget instanceof HTMLElement &&
			typeof highlightTarget.scrollIntoView === 'function'
		) {
			highlightTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
			return;
		}

		const blockId = sourceBlockIdForAnchor(anchor);
		if (blockId) {
			await scrollToBlock(blockId);
			return;
		}

		const reader = document.getElementById('source-document-text');
		if (reader && typeof reader.scrollIntoView === 'function') {
			reader.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}

	async function selectAnchor(anchor: TracebackAnchor) {
		selectedAnchorId = anchor.anchor_id;
		sourceLocationStatus = 'located';
		sourceLocationMessage = '';
		await scrollToSourceAnchor(anchor);
	}

	function documentTitle() {
		return content?.title || routeDocumentId;
	}

	function documentSubtitle() {
		return content?.source_filename || null;
	}

	function blockCount() {
		return content?.blocks.length ?? 0;
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

	function findChainContext(
		dossiers: DocumentVariantDossier[],
		chainId: string
	): ChainContext | null {
		if (!chainId) return null;
		for (const dossier of dossiers) {
			for (const series of dossier.series) {
				const chain = series.chains.find((item) => item.result_id === chainId);
				if (chain) return { dossier, series, chain };
			}
		}
		return null;
	}

	function firstChainContext(dossiers: DocumentVariantDossier[]): ChainContext | null {
		for (const dossier of dossiers) {
			for (const series of dossier.series) {
				const chain = series.chains[0];
				if (chain) return { dossier, series, chain };
			}
		}
		return null;
	}

	function findChainIdByEvidence(dossiers: DocumentVariantDossier[], targetEvidenceId: string) {
		if (!targetEvidenceId) return '';
		for (const dossier of dossiers) {
			for (const series of dossier.series) {
				const chain = series.chains.find((item) =>
					item.evidence.evidence_ids.includes(targetEvidenceId)
				);
				if (chain) return chain.result_id;
			}
		}
		return '';
	}

	function firstUsableEvidenceId(chain: DocumentResultChain) {
		return chain.evidence.evidence_ids[0] ?? '';
	}

	function bestAnchorForChain(chain: DocumentResultChain, response: EvidenceTracebackResponse) {
		const directAnchorIds = new Set(chain.evidence.direct_anchor_ids);
		return (
			response.anchors.find((anchor) => directAnchorIds.has(anchor.anchor_id)) ??
			response.anchors[0] ??
			null
		);
	}

	async function locateChainSource(chain: DocumentResultChain) {
		selectedChainId = chain.result_id;
		selectedAnchorId = '';
		sourceLocationMessage = '';

		const nextEvidenceId = firstUsableEvidenceId(chain);
		if (!nextEvidenceId) {
			selectedEvidenceId = '';
			traceback = null;
			sourceLocationStatus = 'unavailable';
			sourceLocationMessage = $t('traceback.sourceUnavailableBody');
			return;
		}

		selectedEvidenceId = nextEvidenceId;
		sourceLocationStatus = 'loading';

		try {
			const response = await fetchEvidenceTraceback(collectionId, nextEvidenceId);
			traceback = response;
			const anchor = bestAnchorForChain(chain, response);

			if (!anchor) {
				sourceLocationStatus = 'unavailable';
				sourceLocationMessage = $t('traceback.sourceUnavailableBody');
				return;
			}

			if (anchor.document_id && anchor.document_id !== resolvedDocumentId) {
				sourceLocationStatus = 'unavailable';
				sourceLocationMessage = $t('traceback.sourceDifferentDocument');
				return;
			}

			selectedAnchorId = anchor.anchor_id;
			sourceLocationStatus = 'located';
			await scrollToSourceAnchor(anchor);
		} catch (err) {
			sourceLocationStatus = 'error';
			sourceLocationMessage = errorMessage(err);
		}
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

	function sourceLocationTitle(status: typeof sourceLocationStatus, hasSelectedChain: boolean) {
		if (status === 'loading') return $t('traceback.sourceLocating');
		if (status === 'located') return $t('traceback.sourceLocated');
		if (status === 'unavailable') return $t('traceback.sourceUnavailable');
		if (status === 'error') return $t('traceback.sourceError');
		if (hasSelectedChain) return $t('traceback.sourceReadyToLocate');
		return $t('traceback.sourceSelectPrompt');
	}

	function sourceLocationBody(
		status: typeof sourceLocationStatus,
		message: string,
		hasSelectedChain: boolean
	) {
		if (status === 'loading') return $t('traceback.sourceLocatingBody');
		if (status === 'located') return $t('traceback.sourceLocatedBody');
		if (status === 'unavailable') {
			return message || $t('traceback.sourceUnavailableBody');
		}
		if (status === 'error') {
			return message || $t('traceback.sourceErrorBody');
		}
		if (hasSelectedChain) return $t('traceback.sourceReadyToLocateBody');
		return $t('traceback.sourceSelectPromptBody');
	}

	function selectedVariantLabel(context: ChainContext | null) {
		if (!context) return '--';
		return context.dossier.variant_label || context.dossier.material.label;
	}

	function selectedSeriesLabel(context: ChainContext | null) {
		if (!context) return '--';
		return `${context.series.property_family} · ${context.series.test_family}`;
	}

	function localGraphResultLabel(chain: DocumentResultChain | null) {
		if (!chain) return '--';
		return `${chain.measurement.property} · ${formatMeasurementValue(
			chain.measurement.value,
			chain.measurement.unit
		)}`;
	}

	function localGraphSourceLabel(
		anchor: TracebackAnchor | null,
		chain: DocumentResultChain | null
	) {
		if (anchor) return sourceBlockIdForAnchor(anchor) || locatorLabel(anchor);
		return chain?.evidence.traceability_status ?? '--';
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

		<div class="document-review-layout">
			<section class="source-reader" aria-labelledby="source-reader-title">
				<article class="result-card">
					<div class="table-main">
						<h3 id="source-reader-title">{$t('traceback.sourceReaderTitle')}</h3>
						<p class="note">{$t('traceback.sourceReaderLead')}</p>
					</div>
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
							<dd>{blockCount()}</dd>
						</div>
					</dl>
				</article>

				{#if sourceTextSegments.length}
					{#if sourceSectionNavItems.length}
						<section class="result-card detail-section">
							<div class="detail-section__title">{$t('traceback.sectionsTitle')}</div>
							<div class="section-nav">
								{#each sourceSectionNavItems as item}
									<button
										class="btn btn--ghost btn--small"
										type="button"
										on:click={() => void scrollToBlock(item.blockId)}
									>
										{item.label}
									</button>
								{/each}
							</div>
						</section>
					{/if}

					<article class="result-card document-source-reader" id="source-document-text">
						<div class="document-source-text">
							{#each sourceTextSegments as segment}
								{#if segment.blockId}
									<span
										class:source-block-anchor--active={sourceBlockIdForAnchor(selectedAnchor) ===
											segment.blockId}
										class="source-block-anchor"
										id={`block-${segment.blockId}`}
										aria-hidden="true"
									></span>
								{/if}
								{@const parts = segmentHighlightParts(segment, selectedSourceHighlight)}
								{#if parts}
									{parts.before}<mark class="source-highlight">{parts.match}</mark>{parts.after}
								{:else}
									{segment.text}
								{/if}
							{/each}
						</div>

						{#if selectedAnchor?.quote && !selectedSourceHighlight}
							<section class="source-location-note">
								<div class="detail-section__title">{$t('traceback.quoteTitle')}</div>
								<p class="result-text">{selectedAnchor.quote}</p>
							</section>
						{/if}
					</article>
				{:else if !contentError}
					<article class="result-card">
						<p class="note">{$t('traceback.empty')}</p>
					</article>
				{/if}
			</section>

			<aside class="evidence-review-panel" aria-labelledby="evidence-review-title">
				<article class="result-card">
					<div class="table-main">
						<h3 id="evidence-review-title">{$t('traceback.evidenceReviewTitle')}</h3>
						<p class="note">{$t('traceback.evidenceReviewLead')}</p>
					</div>
					<dl class="detail-list">
						<div class="detail-row">
							<dt>{$t('traceback.documentLabel')}</dt>
							<dd>{documentTitle()}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('results.totalLabel')}</dt>
							<dd>{comparisonSemantics?.count ?? relatedResults.length}</dd>
						</div>
						<div class="detail-row">
							<dt>{$t('results.variantDossierTitle')}</dt>
							<dd>{variantDossiers.length}</dd>
						</div>
					</dl>
				</article>

				{#if !contentError}
					<article class="result-card source-location-card">
						<h3>{$t('traceback.traceCardTitle')}</h3>
						<p class="result-text">
							{sourceLocationTitle(sourceLocationStatus, Boolean(selectedChain))}
						</p>
						<p class="note">
							{sourceLocationBody(
								sourceLocationStatus,
								sourceLocationMessage,
								Boolean(selectedChain)
							)}
						</p>
						{#if selectedAnchor}
							<dl class="detail-list">
								{#if selectedEvidenceId}
									<div class="detail-row">
										<dt>{$t('traceback.evidenceIdsTitle')}</dt>
										<dd>{selectedEvidenceId}</dd>
									</div>
								{/if}
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

					{#if showTracebackPanel() && traceback?.anchors.length}
						<section class="result-card detail-section">
							<div class="detail-section__title">{$t('traceback.anchorsTitle')}</div>
							<div class="traceback-anchor-list">
								{#each traceback.anchors as anchor}
									<button
										class:selected-anchor={selectedAnchor?.anchor_id === anchor.anchor_id}
										class="traceback-anchor"
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
											{#if sourceBlockIdForAnchor(anchor)}
												{anchor.page !== null ? ' · ' : ''}{$t('traceback.blockLabel', {
													block: sourceBlockIdForAnchor(anchor)
												})}
											{/if}
										</div>
									</button>
								{/each}
							</div>
						</section>
					{/if}

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
											<div class="table-title">
												{dossier.variant_label || dossier.material.label}
											</div>
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
													{series.varying_axis.axis_unit
														? ` (${series.varying_axis.axis_unit})`
														: ''}
												</p>
												{#if series.chains.length}
													<div class="document-chain-list">
														{#each series.chains as chain}
															<article
																class:selected-chain={selectedChainId === chain.result_id}
																class="document-chain-item"
															>
																<div class="table-main">
																	<a class="table-title" href={chainHref(chain)}>
																		{chain.measurement.property} · {formatMeasurementValue(
																			chain.measurement.value,
																			chain.measurement.unit
																		)}
																	</a>
																	<div class="table-sub">
																		{chain.assessment.comparability_status}
																	</div>
																</div>
																{#if chainConditionSummary(chain)}
																	<div class="note">{chainConditionSummary(chain)}</div>
																{/if}
																{#if chain.baseline.label}
																	<div class="note">
																		{$t('results.fieldBaseline')}: {chain.baseline.label}
																	</div>
																{/if}
																<div class="table-actions">
																	<button
																		class="btn btn--ghost btn--small"
																		type="button"
																		on:click={() => void locateChainSource(chain)}
																	>
																		{$t('traceback.locateSource')}
																	</button>
																	<a class="btn btn--ghost btn--small" href={chainHref(chain)}>
																		{$t('results.openResult')}
																	</a>
																</div>
															</article>
														{/each}
													</div>
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

					{#if selectedChain}
						<article class="result-card selected-chain-detail">
							<h3>{$t('traceback.selectedChainTitle')}</h3>
							<p class="note">
								{sourceLocationBody(
									sourceLocationStatus,
									sourceLocationMessage,
									Boolean(selectedChain)
								)}
							</p>
							<dl class="detail-list">
								<div class="detail-row">
									<dt>{$t('results.fieldVariant')}</dt>
									<dd>{selectedVariantLabel(selectedChainContext)}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldSeries')}</dt>
									<dd>{selectedSeriesLabel(selectedChainContext)}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldValue')}</dt>
									<dd>
										{selectedChain.measurement.property} · {formatMeasurementValue(
											selectedChain.measurement.value,
											selectedChain.measurement.unit
										)}
									</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldTest')}</dt>
									<dd>{chainConditionSummary(selectedChain) || '--'}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldBaseline')}</dt>
									<dd>{selectedChain.baseline.label || '--'}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldComparability')}</dt>
									<dd>{selectedChain.assessment.comparability_status}</dd>
								</div>
								<div class="detail-row">
									<dt>{$t('results.fieldTraceability')}</dt>
									<dd>{selectedChain.evidence.traceability_status}</dd>
								</div>
							</dl>

							{#if selectedChain.evidence.evidence_ids.length}
								<div class="detail-section">
									<div class="detail-section__title">{$t('traceback.evidenceIdsTitle')}</div>
									<div class="detail-chips">
										{#each selectedChain.evidence.evidence_ids as chainEvidenceId}
											<span class="detail-chip">{chainEvidenceId}</span>
										{/each}
									</div>
								</div>
							{/if}

							<div class="table-actions">
								<button
									class="btn btn--ghost btn--small"
									type="button"
									on:click={() => void locateChainSource(selectedChain)}
								>
									{$t('traceback.locateSource')}
								</button>
								<a class="btn btn--ghost btn--small" href={chainHref(selectedChain)}>
									{$t('results.openResult')}
								</a>
							</div>
						</article>
					{/if}
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
			</aside>

			<aside class="local-graph-panel" aria-labelledby="local-graph-title">
				<article class="result-card local-graph-card">
					<div class="table-main">
						<h3 id="local-graph-title">{$t('traceback.localGraphTitle')}</h3>
						<p class="note">{$t('traceback.localGraphLead')}</p>
					</div>

					{#if localGraphContext && localGraphChain}
						{@const graphContext = localGraphContext}
						{@const graphChain = localGraphChain}
						<div class="local-graph-canvas" aria-labelledby="local-graph-title">
							<svg class="local-graph-edges" viewBox="0 0 100 100" aria-hidden="true">
								<line x1="50" y1="48" x2="50" y2="13" />
								<line x1="50" y1="48" x2="18" y2="40" />
								<line x1="50" y1="48" x2="82" y2="40" />
								<line x1="50" y1="54" x2="25" y2="82" />
								<line x1="50" y1="54" x2="76" y2="82" />
							</svg>

							<div class="graph-node graph-node--top">
								<div class="graph-node__label">{$t('results.fieldMaterial')}</div>
								<div class="graph-node__value">{graphContext.dossier.material.label}</div>
							</div>

							<div class="graph-node graph-node--left">
								<div class="graph-node__label">{$t('results.fieldVariant')}</div>
								<div class="graph-node__value">{selectedVariantLabel(graphContext)}</div>
							</div>

							<div class="graph-node graph-node--center graph-node--primary">
								<div class="graph-node__label">{$t('results.fieldValue')}</div>
								<div class="graph-node__value">{localGraphResultLabel(graphChain)}</div>
							</div>

							<div class="graph-node graph-node--right">
								<div class="graph-node__label">{$t('results.fieldSeries')}</div>
								<div class="graph-node__value">{selectedSeriesLabel(graphContext)}</div>
							</div>

							<div class="graph-node graph-node--bottom-left">
								<div class="graph-node__label">{$t('results.fieldBaseline')}</div>
								<div class="graph-node__value">{graphChain.baseline.label || '--'}</div>
							</div>

							<div class="graph-node graph-node--bottom-right">
								<div class="graph-node__label">{$t('traceback.graphSourceNode')}</div>
								<div class="graph-node__value">
									{localGraphSourceLabel(selectedAnchor, graphChain)}
								</div>
							</div>
						</div>

						<dl class="detail-list local-graph-detail">
							<div class="detail-row">
								<dt>{$t('results.fieldComparability')}</dt>
								<dd>{graphChain.assessment.comparability_status}</dd>
							</div>
							<div class="detail-row">
								<dt>{$t('results.fieldTraceability')}</dt>
								<dd>{graphChain.evidence.traceability_status}</dd>
							</div>
						</dl>
					{:else}
						<p class="note">{$t('traceback.localGraphEmpty')}</p>
					{/if}
				</article>
			</aside>
		</div>
	{/if}
</section>

<style>
	.traceback-anchor {
		width: 100%;
		text-align: left;
		padding: 12px;
		border: 1px solid var(--color-line);
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.72);
		cursor: pointer;
	}

	.selected-anchor {
		border-color: var(--accent, #2f5bd2);
		box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent, #2f5bd2) 40%, transparent);
	}

	.document-review-layout {
		display: grid;
		grid-template-columns: minmax(420px, 1.35fr) minmax(360px, 0.95fr) minmax(260px, 0.55fr);
		gap: 16px;
		align-items: start;
		margin-top: 16px;
	}

	.source-reader,
	.evidence-review-panel,
	.local-graph-panel {
		display: grid;
		gap: 12px;
		align-content: start;
	}

	.evidence-review-panel,
	.local-graph-panel {
		position: sticky;
		top: 1rem;
	}

	.traceback-anchor-list {
		display: grid;
		gap: 12px;
	}

	.section-nav {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.document-source-reader {
		display: grid;
		gap: 1rem;
		scroll-margin-top: 5rem;
	}

	.document-source-text {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.72;
	}

	.source-block-anchor {
		display: inline-block;
		width: 0;
		height: 0;
		scroll-margin-top: 5rem;
	}

	.source-block-anchor--active {
		outline: 0;
	}

	.source-highlight {
		padding: 0.04em 0.08em;
		border-radius: 4px;
		background: color-mix(in srgb, var(--accent, #2f5bd2) 22%, #fff4a3);
		color: inherit;
	}

	.source-location-note {
		display: grid;
		gap: 0.5rem;
		padding-top: 1rem;
		border-top: 1px solid var(--color-line);
	}

	.document-chain-card {
		grid-column: 1 / -1;
	}

	.document-chain-stack,
	.document-chain-list {
		display: grid;
		gap: 0.75rem;
	}

	.document-chain-item {
		display: grid;
		gap: 0.5rem;
		padding: 12px;
		border: 1px solid var(--color-line);
		border-radius: 12px;
		background: rgba(255, 255, 255, 0.56);
	}

	.selected-chain {
		border-color: var(--accent, #2f5bd2);
		background: color-mix(in srgb, var(--accent, #2f5bd2) 10%, rgba(255, 255, 255, 0.72));
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

	.selected-chain-detail {
		display: grid;
		gap: 0.75rem;
	}

	.local-graph-card {
		display: grid;
		gap: 1rem;
		overflow: hidden;
	}

	.local-graph-canvas {
		position: relative;
		min-height: 330px;
		border: 1px solid var(--color-line);
		border-radius: 18px;
		background:
			radial-gradient(circle at 50% 48%, rgba(47, 91, 210, 0.14), transparent 24%),
			linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(245, 248, 255, 0.68));
	}

	.local-graph-edges {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}

	.local-graph-edges line {
		stroke: color-mix(in srgb, var(--accent, #2f5bd2) 34%, var(--color-muted));
		stroke-width: 0.75;
		stroke-linecap: round;
	}

	.graph-node {
		position: absolute;
		display: grid;
		gap: 0.2rem;
		width: 104px;
		min-height: 76px;
		padding: 0.65rem;
		border: 1px solid color-mix(in srgb, var(--accent, #2f5bd2) 26%, var(--color-line));
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.92);
		box-shadow: 0 14px 36px rgba(27, 42, 79, 0.08);
		place-content: center;
		text-align: center;
		transform: translate(-50%, -50%);
	}

	.graph-node--primary {
		width: 120px;
		min-height: 88px;
		border-color: var(--accent, #2f5bd2);
		background: color-mix(in srgb, var(--accent, #2f5bd2) 12%, white);
	}

	.graph-node--top {
		left: 50%;
		top: 13%;
	}

	.graph-node--left {
		left: 18%;
		top: 40%;
	}

	.graph-node--center {
		left: 50%;
		top: 50%;
	}

	.graph-node--right {
		left: 82%;
		top: 40%;
	}

	.graph-node--bottom-left {
		left: 25%;
		top: 82%;
	}

	.graph-node--bottom-right {
		left: 76%;
		top: 82%;
	}

	.graph-node__label {
		color: var(--color-muted);
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.graph-node__value {
		display: -webkit-box;
		overflow: hidden;
		font-size: 0.78rem;
		font-weight: 800;
		line-height: 1.25;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
	}

	.local-graph-detail {
		margin-top: 0;
	}

	@media (max-width: 1280px) {
		.document-review-layout {
			grid-template-columns: minmax(0, 1.3fr) minmax(340px, 0.8fr);
		}

		.local-graph-panel {
			grid-column: 1 / -1;
			position: static;
		}
	}

	@media (max-width: 980px) {
		.document-review-layout {
			grid-template-columns: 1fr;
		}

		.evidence-review-panel,
		.local-graph-panel {
			position: static;
		}
	}

	@media (max-width: 640px) {
		.local-graph-canvas {
			min-height: 520px;
		}

		.graph-node--top,
		.graph-node--left,
		.graph-node--center,
		.graph-node--right,
		.graph-node--bottom-left,
		.graph-node--bottom-right {
			left: 50%;
		}

		.graph-node--top {
			top: 10%;
		}

		.graph-node--left {
			top: 26%;
		}

		.graph-node--center {
			top: 43%;
		}

		.graph-node--right {
			top: 60%;
		}

		.graph-node--bottom-left {
			top: 77%;
		}

		.graph-node--bottom-right {
			top: 92%;
		}

		.local-graph-edges {
			display: none;
		}
	}
</style>
