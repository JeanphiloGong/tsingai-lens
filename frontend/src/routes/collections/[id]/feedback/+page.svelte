<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import {
		AlertTriangle,
		CheckCircle2,
		ChevronRight,
		Download,
		FileText,
		MessageSquareWarning,
		RefreshCw,
		Search,
		ThumbsDown,
		ThumbsUp,
		Wrench,
		XCircle
	} from '@lucide/svelte';
	import { ApiError, errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchFeedbackCase,
		fetchFeedbackCases,
		downloadFeedbackCaseExport,
		saveFeedbackAnnotation,
		submitFeedbackReview,
		type FeedbackCaseDetail,
		type FeedbackCaseSummary
	} from '../../../_shared/feedbackCases';

	let cases: FeedbackCaseSummary[] = [];
	let selected: FeedbackCaseDetail | null = null;
	let loading = true;
	let detailLoading = false;
	let error = '';
	let filter = '';
	let activeStatus = 'all';
	let annotationSaving = false;
	let annotationError = '';
	let annotationSaved = false;
	let reviewSaving = false;
	let reviewError = '';
	let reviewReason = '';
	let reviewRequestKey = '';
	let candidateExporting = false;
	let candidateExportNotice = '';
	let candidateExportError = '';
	let annotationProblemType = 'source_missing';
	let annotationSeverity = 'medium';
	let annotationTarget = '';
	let annotationReason = '';
	let annotationSupportRefs: string[] = [];
	let annotationDatasetUses: string[] = ['evaluation'];

	$: collectionId = $page.params.id ?? '';
	$: visibleCases = cases.filter((item) => {
		const matchesStatus = activeStatus === 'all' || item.status === activeStatus;
		const haystack = [
			item.problem_type ?? '',
			item.question_preview,
			item.answer_preview,
			...item.document_titles
		]
			.join(' ')
			.toLowerCase();
		return matchesStatus && haystack.includes(filter.trim().toLowerCase());
	});
	$: caseStats = {
		total: cases.length,
		needsReview: cases.filter((item) => item.needs_human_review).length,
		accepted: cases.filter((item) => item.status === 'accepted').length,
		papers: new Set(cases.flatMap((item) => item.document_titles)).size
	};

	onMount(() => {
		void loadCases();
	});

	async function loadCases() {
		if (!collectionId) return;
		loading = true;
		error = '';
		try {
			const response = await fetchFeedbackCases(collectionId);
			cases = response.items;
			if (selected && !cases.some((item) => item.case_id === selected?.case_id)) selected = null;
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function exportCandidateAnalysis() {
		if (!collectionId || candidateExporting) return;
		candidateExporting = true;
		candidateExportNotice = '';
		candidateExportError = '';
		try {
			await downloadFeedbackCaseExport(collectionId);
			candidateExportNotice = $t('feedbackWorkbench.candidateExported');
		} catch (err) {
			candidateExportError = errorMessage(err);
		} finally {
			candidateExporting = false;
		}
	}

	function scrollToAnnotation() {
		if (typeof document === 'undefined') return;
		document.getElementById('annotation-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	function nextActionLabel(status: string) {
		if (status === 'needs_annotation' || status === 'rejected' || status === 'insufficient') {
			return $t('feedbackWorkbench.nextAnnotate');
		}
		if (status === 'ready_for_review') return $t('feedbackWorkbench.nextReview');
		if (status === 'accepted') return $t('feedbackWorkbench.nextAccepted');
		return $t('feedbackWorkbench.nextInspect');
	}

	async function openCase(item: FeedbackCaseSummary) {
		detailLoading = true;
		error = '';
		try {
			selected = await fetchFeedbackCase(collectionId, item.case_id);
			reviewRequestKey = '';
			loadAnnotationForm(selected);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			detailLoading = false;
		}
	}

	function loadAnnotationForm(detail: FeedbackCaseDetail) {
		const annotation = detail.annotation;
		annotationProblemType = String(annotation?.problem_type ?? detail.analysis?.problem_type ?? 'source_missing');
		annotationSeverity = String(annotation?.severity ?? 'medium');
		annotationTarget = String(annotation?.target ?? detail.analysis?.suggested_target ?? '');
		annotationReason = String(annotation?.reason ?? '');
		annotationSupportRefs = Array.isArray(annotation?.support_source_refs)
			? annotation.support_source_refs.map(String)
			: [];
		annotationDatasetUses = Array.isArray(annotation?.dataset_uses)
			? annotation.dataset_uses.map(String)
			: ['evaluation'];
		annotationError = '';
		annotationSaved = false;
		reviewError = '';
		reviewReason = '';
	}

	$: annotationSources = selected
		? [...selected.inspected_sources, ...selected.claim_support]
			.filter((source, index, values) => {
				const ref = String(source.source_ref ?? source.source_id ?? '');
				return ref && values.findIndex((item) => String(item.source_ref ?? item.source_id ?? '') === ref) === index;
			})
		: [];

	async function saveAnnotation() {
		if (!selected || annotationSaving) return;
		annotationSaving = true;
		annotationError = '';
		annotationSaved = false;
		try {
			await saveFeedbackAnnotation(collectionId, selected.case_id, {
				expected_digest: selected.current_annotation_digest,
				problem_type: annotationProblemType,
				severity: annotationSeverity,
				target: annotationTarget.trim() || null,
				support_source_refs: annotationSupportRefs,
				dataset_uses: annotationDatasetUses,
				reason: annotationReason.trim()
			});
			selected = await fetchFeedbackCase(collectionId, selected.case_id);
			loadAnnotationForm(selected);
			reviewRequestKey = '';
			annotationSaved = true;
			await loadCases();
		} catch (err) {
			annotationError = errorMessage(err);
		} finally {
			annotationSaving = false;
		}
	}

	async function submitReview(decision: string) {
		if (!selected || reviewSaving || !selected.current_annotation_digest) return;
		reviewSaving = true;
		reviewError = '';
		if (!reviewRequestKey) reviewRequestKey = newReviewRequestKey();
		try {
			await submitFeedbackReview(collectionId, selected.case_id, {
				expected_annotation_digest: selected.current_annotation_digest,
				decision,
				reason: reviewReason.trim()
			}, reviewRequestKey);
			selected = await fetchFeedbackCase(collectionId, selected.case_id);
			loadAnnotationForm(selected);
			reviewRequestKey = '';
			await loadCases();
		} catch (err) {
			reviewError = errorMessage(err);
			// A validation or stale-digest response describes a new attempt; a
			// transport/server failure should keep the key for a safe retry.
			if (err instanceof ApiError && err.status < 500) reviewRequestKey = '';
		} finally {
			reviewSaving = false;
		}
	}

	function newReviewRequestKey() {
		if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
			return crypto.randomUUID();
		}
		return `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
	}

	function formatDate(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}

	function label(value: string | null | undefined) {
		return value ? value.replaceAll('_', ' ') : $t('feedbackWorkbench.unknown');
	}

	const problemTranslationKeys: Record<string, string> = {
		fact_error: 'problemFactError',
		source_missing: 'problemSourceMissing',
		evidence_mismatch: 'problemEvidenceMismatch',
		retrieval_failure: 'problemRetrievalFailure',
		tool_failure: 'problemToolFailure',
		intent_mismatch: 'problemIntentMismatch',
		incomplete_answer: 'problemIncomplete',
		style_or_format: 'problemStyle',
		undetermined_dissatisfaction: 'problemUndetermined'
	};

	const decisionTranslationKeys: Record<string, string> = {
		accept: 'decisionAccept',
		reject: 'decisionReject',
		insufficient: 'decisionInsufficient',
		withdraw: 'decisionWithdraw'
	};

	const omissionReasonTranslationKeys: Record<string, string> = {
		not_read: 'reasonNotRead',
		not_requested: 'reasonNotRequested',
		unavailable: 'reasonUnavailable'
	};

	function problemLabel(value: string | null | undefined) {
		if (!value) return $t('feedbackWorkbench.unknown');
		const key = problemTranslationKeys[value];
		return key ? $t(`feedbackWorkbench.${key}`) : label(value);
	}

	function decisionLabel(value: string | null | undefined) {
		if (!value) return $t('feedbackWorkbench.unknown');
		const key = decisionTranslationKeys[value];
		return key ? $t(`feedbackWorkbench.${key}`) : label(value);
	}

	function severityLabel(value: string | null | undefined) {
		const key =
			{
				low: 'severityLow',
				medium: 'severityMedium',
				high: 'severityHigh',
				critical: 'severityCritical'
			}[value ?? ''] ?? '';
		return key ? $t(`feedbackWorkbench.${key}`) : label(value);
	}

	function statusLabel(value: string) {
		const key =
			{
				detected: 'statusDetected',
				collecting_context: 'statusCollectingContext',
				needs_annotation: 'statusNeedsAnnotation',
				ready_for_review: 'statusReadyForReview',
				insufficient: 'statusInsufficient',
				accepted: 'statusAccepted',
				rejected: 'statusRejected',
				withdrawn: 'statusWithdrawn'
			}[value] ?? 'unknown';
		return $t(`feedbackWorkbench.${key}`);
	}

	function coverageLabel(value: string) {
		const key =
			{
				complete: 'coverageComplete',
				partial: 'coveragePartial',
				failed: 'coverageFailed',
				unknown: 'coverageUnknown'
			}[value] ?? 'coverageUnknown';
		return $t(`feedbackWorkbench.${key}`);
	}

	function sourceTitle(source: Record<string, unknown>) {
		const title = source.document_title ?? source.title ?? source.document_name;
		return String(title ?? '').trim() || $t('feedbackWorkbench.source');
	}

	function sourceLocator(source: Record<string, unknown>) {
		const locations = [source.heading_path, source.section, source.section_title, source.figure_label, source.table_label]
			.map((value) => String(value ?? '').trim())
			.filter(Boolean);
		if (source.page !== undefined && source.page !== null && String(source.page).trim()) {
			locations.push($t('feedbackWorkbench.page', { page: String(source.page) }));
		}
		return [...new Set(locations)].join(' · ');
	}

	function sourceHref(source: Record<string, unknown>) {
		const documentId = String(source.document_id ?? '').trim();
		if (!documentId || !collectionId) return '';
		const params = new URLSearchParams({ view: 'parsed-paper' });
		const sourceRef = String(source.source_ref ?? source.source_id ?? '').trim();
		if (sourceRef) params.set('source_ref', sourceRef);
		return `/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}?${params.toString()}`;
	}

	function sourceCitation(source: Record<string, unknown>) {
		const doi = String(source.doi ?? '').trim();
		return doi ? `DOI ${doi}` : '';
	}

	function sourceReason(source: Record<string, unknown>) {
		const raw = String(source.reason ?? '').trim().split(':', 1)[0];
		if (!raw) return '';
		const key = omissionReasonTranslationKeys[raw];
		return key ? $t(`feedbackWorkbench.${key}`) : label(raw);
	}

	function claimText(claim: Record<string, unknown>) {
		return String(claim.claim ?? claim.statement ?? claim.text ?? $t('feedbackWorkbench.unknown'));
	}

	function claimSourceLabel(claim: Record<string, unknown>) {
		const ref = String(claim.source_ref ?? claim.source ?? claim.source_id ?? '').trim();
		const source = selected
			? [...selected.inspected_sources, ...selected.omitted_candidates, ...selected.requested_scope].find(
					(item) => String(item.source_ref ?? item.source_id ?? '') === ref
				  )
			: undefined;
		if (source) {
			const location = sourceLocator(source);
			return `${sourceTitle(source)}${location ? ` · ${location}` : ''}`;
		}
		return ref ? $t('feedbackWorkbench.supportRecorded') : $t('feedbackWorkbench.sourceUnknown');
	}

	function annotationText(key: string) {
		const value = selected?.annotation?.[key];
		return typeof value === 'string' ? value.trim() : '';
	}

	function datasetUseLabel(value: string) {
		const key =
			{
				evaluation: 'useEvaluation',
				sft: 'useSft',
				preference: 'usePreference'
			}[value] ?? '';
		return key ? $t(`feedbackWorkbench.${key}`) : label(value);
	}

	function annotationUsesLabel() {
		const values = selected?.annotation?.dataset_uses;
		if (!Array.isArray(values) || !values.length) return $t('feedbackWorkbench.noDatasetUses');
		return values.map((value) => datasetUseLabel(String(value))).join(' · ');
	}
</script>

<svelte:head>
	<title>{$t('feedbackWorkbench.title')} | Lens</title>
</svelte:head>

	<section class="workbench" aria-labelledby="feedback-title">
		<header class="workbench-header">
			<div>
			<p class="eyebrow">{$t('feedbackWorkbench.eyebrow')}</p>
			<h1 id="feedback-title">{$t('feedbackWorkbench.title')}</h1>
			<p class="lede">{$t('feedbackWorkbench.lede')}</p>
			</div>
			<div class="header-actions">
				<button class="export-button" type="button" on:click={exportCandidateAnalysis} disabled={candidateExporting}>
					<Download size={16} />
					{candidateExporting ? $t('feedbackWorkbench.candidateExporting') : $t('feedbackWorkbench.candidateExport')}
				</button>
				<a class="dataset-link" href={`/collections/${collectionId}/feedback/datasets`}>{$t('feedbackWorkbench.datasets')}</a>
				<button
					class="icon-button"
					type="button"
					title={$t('feedbackWorkbench.refresh')}
					aria-label={$t('feedbackWorkbench.refresh')}
					on:click={loadCases}
					disabled={loading}
				>
					<span class:spin={loading}><RefreshCw size={17} /></span>
				</button>
			</div>
		</header>

	{#if error}
		<div class="notice notice--error" role="alert"><AlertTriangle size={17} /><span>{error}</span></div>
	{/if}
	{#if candidateExportNotice}
		<div class="notice notice--success" role="status"><CheckCircle2 size={17} /><span>{candidateExportNotice}</span></div>
	{/if}
	{#if candidateExportError}
		<div class="notice notice--error" role="alert"><AlertTriangle size={17} /><span>{candidateExportError}</span></div>
	{/if}

	<div class="status-strip" aria-label={$t('feedbackWorkbench.queueSummary')}>
		<div><strong>{caseStats.total}</strong><span>{$t('feedbackWorkbench.totalCases')}</span></div>
		<div><strong>{caseStats.needsReview}</strong><span>{$t('feedbackWorkbench.needsReviewCount')}</span></div>
		<div><strong>{caseStats.accepted}</strong><span>{$t('feedbackWorkbench.acceptedCount')}</span></div>
		<div><strong>{caseStats.papers}</strong><span>{$t('feedbackWorkbench.paperCount')}</span></div>
	</div>

	<div class="workbench-grid">
		<aside class="case-list" aria-label={$t('feedbackWorkbench.listLabel')}>
			<div class="list-toolbar">
				<label class="search-box">
					<Search size={16} />
					<span class="sr-only">{$t('feedbackWorkbench.filterLabel')}</span>
					<input bind:value={filter} placeholder={$t('feedbackWorkbench.filterPlaceholder')} />
				</label>
				<select bind:value={activeStatus} aria-label={$t('feedbackWorkbench.statusLabel')}>
					<option value="all">{$t('feedbackWorkbench.allCases')}</option>
					<option value="detected">{statusLabel('detected')}</option>
					<option value="collecting_context">{statusLabel('collecting_context')}</option>
					<option value="needs_annotation">{statusLabel('needs_annotation')}</option>
					<option value="ready_for_review">{statusLabel('ready_for_review')}</option>
					<option value="insufficient">{statusLabel('insufficient')}</option>
					<option value="accepted">{statusLabel('accepted')}</option>
					<option value="rejected">{statusLabel('rejected')}</option>
					<option value="withdrawn">{statusLabel('withdrawn')}</option>
				</select>
			</div>

			{#if loading}
				<div class="empty-state" role="status" aria-live="polite"><span class="loader"></span><p>{$t('feedbackWorkbench.loadingCases')}</p></div>
			{:else if !visibleCases.length}
				<div class="empty-state">
					<CheckCircle2 size={24} />
					<strong>{$t('feedbackWorkbench.noMatching')}</strong>
					<p>{$t('feedbackWorkbench.noMatchingDetail')}</p>
				</div>
			{:else}
				<div class="case-items">
					{#each visibleCases as item (item.case_id)}
						<button
							class:selected={selected?.case_id === item.case_id}
							class="case-item"
							type="button"
							on:click={() => openCase(item)}
						>
							<div class="case-item__topline">
							<span class="case-type">{problemLabel(item.problem_type)}</span>
								<ChevronRight size={16} />
							</div>
							<strong title={item.question_preview || item.answer_preview || $t('feedbackWorkbench.unknown')}>
								{item.question_preview || item.answer_preview || $t('feedbackWorkbench.unknown')}
							</strong>
							{#if item.document_titles.length}
								<span class="case-item__documents" title={item.document_titles.join(' · ')}>{item.document_titles.join(' · ')}</span>
							{/if}
							<div class="case-item__meta">
								<span class="status-dot"></span>
								<span>{statusLabel(item.status)}</span>
								{#if item.confidence !== null}<span>{Math.round(item.confidence * 100)}% {$t('feedbackWorkbench.confidence').toLowerCase()}</span>{/if}
							</div>
						</button>
					{/each}
				</div>
			{/if}
		</aside>

		<main class="case-detail" aria-busy={detailLoading}>
			{#if detailLoading}
				<div class="empty-state" role="status" aria-live="polite"><span class="loader"></span><p>{$t('feedbackWorkbench.loadingDetails')}</p></div>
			{:else if !selected}
				<div class="detail-placeholder">
					<div class="placeholder-icon"><FileText size={26} /></div>
					<h2>{$t('feedbackWorkbench.chooseCase')}</h2>
					<p>{$t('feedbackWorkbench.chooseCaseDetail')}</p>
				</div>
			{:else}
				<div class="detail-header">
					<div>
						<div class="detail-kicker"><span class="status-pill">{statusLabel(selected.status)}</span><span>{formatDate(selected.updated_at)}</span></div>
						<h2>{$t('feedbackWorkbench.caseReview')}</h2>
						<p class="detail-context">{$t('feedbackWorkbench.realScenario')}</p>
					</div>
					<div class="detail-next">
						<span class="section-label">{$t('feedbackWorkbench.nextStep')}</span>
						<strong>{nextActionLabel(selected.status)}</strong>
						{#if selected.status === 'needs_annotation' || selected.status === 'rejected' || selected.status === 'insufficient'}
							<button type="button" class="jump-button" on:click={scrollToAnnotation}>{$t('feedbackWorkbench.jumpToAnnotation')}</button>
						{/if}
					</div>
				</div>

				<section class="prompt-answer">
					<div><span class="section-label">{$t('feedbackWorkbench.question')}</span><p>{selected.question || $t('feedbackWorkbench.noQuestion')}</p></div>
					<div><span class="section-label">{$t('feedbackWorkbench.answer')}</span><p>{selected.answer || $t('feedbackWorkbench.noAnswer')}</p></div>
				</section>

				{#if selected.source_signals.length}
					<section class="detail-section">
						<div class="section-heading">
							<h3>{$t('feedbackWorkbench.feedbackSignal')}</h3>
							<span>{selected.source_signals.length} {selected.source_signals.length === 1 ? $t('feedbackWorkbench.record') : $t('feedbackWorkbench.records')}</span>
						</div>
						<div class="signal-list">
							{#each selected.source_signals as signal (signal.signal_type === 'chat_message_feedback' ? signal.feedback_id : signal.signal_id)}
								<article class="signal" data-signal-type={signal.signal_type}>
									<div class="signal__heading">
										{#if signal.signal_type === 'chat_message_feedback'}
											<span class="signal__badge" class:signal__badge--negative={signal.rating === 'not_helpful'}>
												{#if signal.rating === 'not_helpful'}<ThumbsDown size={14} aria-hidden="true" />{:else}<ThumbsUp size={14} aria-hidden="true" />{/if}
												{signal.rating === 'not_helpful' ? $t('feedbackWorkbench.notHelpful') : $t('feedbackWorkbench.helpful')}
											</span>
											<strong>{problemLabel(signal.reason)}</strong>
										{:else if signal.signal_type === 'natural_language_correction'}
											<span class="signal__badge signal__badge--correction"><MessageSquareWarning size={14} aria-hidden="true" />{$t('feedbackWorkbench.userCorrection')}</span>
											<strong>{problemLabel(signal.problem_type)}</strong>
										{:else}
											<span class="signal__badge signal__badge--negative"><Wrench size={14} aria-hidden="true" />{$t('feedbackWorkbench.toolFailureSignal')}</span>
											<strong>{label(signal.tool_name)}</strong>
										{/if}
									</div>
									{#if signal.signal_type === 'chat_message_feedback' && signal.comment}
										<p class="signal__body">{signal.comment}</p>
									{:else if signal.signal_type === 'natural_language_correction'}
										<blockquote class="signal__body">{signal.content}</blockquote>
									{:else if signal.signal_type === 'tool_failure'}
										<dl class="signal__facts">
											<div><dt>{$t('feedbackWorkbench.tool')}</dt><dd>{label(signal.tool_name)}</dd></div>
											<div><dt>{$t('feedbackWorkbench.recordedFailure')}</dt><dd>{label(signal.error_code)}</dd></div>
										</dl>
									{/if}
								</article>
							{/each}
						</div>
					</section>
				{/if}

					<section class="detail-section">
						<div class="section-heading"><h3>{$t('feedbackWorkbench.requestedScope')}</h3><span>{selected.requested_scope.length}</span></div>
						{#if selected.requested_scope.length}
							<div class="scope-list">{#each selected.requested_scope as source}{#if sourceHref(source)}<a class="scope-chip" href={sourceHref(source)}>{sourceTitle(source)}</a>{:else}<span class="scope-chip">{sourceTitle(source)}</span>{/if}{/each}</div>
						{:else}<p class="muted">{$t('feedbackWorkbench.noRequestedScope')}</p>{/if}
				</section>

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.sourceCoverage')}</h3><span class="coverage-badge coverage-badge--{selected.coverage_status}">{coverageLabel(selected.coverage_status)}</span></div>
					{#if selected.inspected_sources.length}
						<div class="source-list">
							{#each selected.inspected_sources as source}
								<article class="source-row"><div class="source-icon"><FileText size={16} /></div><div><strong>{#if sourceHref(source)}<a class="source-link" href={sourceHref(source)}>{sourceTitle(source)}</a>{:else}{sourceTitle(source)}{/if}</strong>{#if sourceLocator(source)}<span>{sourceLocator(source)}</span>{/if}{#if sourceCitation(source)}<span>{sourceCitation(source)}</span>{/if}{#if source.quote}<p>{String(source.quote)}</p>{:else}<p class="muted">{$t('feedbackWorkbench.noQuote')}</p>{/if}</div></article>
							{/each}
						</div>
					{:else}<p class="muted">{$t('feedbackWorkbench.inspectedNone')}</p>{/if}
				</section>

				{#if selected.omitted_candidates.length}
						<section class="detail-section detail-section--warning"><div class="section-heading"><h3>{$t('feedbackWorkbench.omittedCandidates')}</h3><span>{selected.omitted_candidates.length}</span></div>{#each selected.omitted_candidates as source}<div class="omitted"><XCircle size={16} /><span><strong>{#if sourceHref(source)}<a class="source-link" href={sourceHref(source)}>{sourceTitle(source)}</a>{:else}{sourceTitle(source)}{/if}{sourceLocator(source) ? ` · ${sourceLocator(source)}` : ''}</strong>{#if sourceReason(source)}<small>{$t('feedbackWorkbench.omissionReason', { reason: sourceReason(source) })}</small>{/if}</span></div>{/each}</section>
				{/if}

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.claimSupport')}</h3><span>{selected.claim_support.length}</span></div>
					{#if selected.claim_support.length}{#each selected.claim_support as claim}<div class="support-row"><strong>{claimText(claim)}</strong><span>{claimSourceLabel(claim)}</span></div>{/each}{:else}<p class="muted">{$t('feedbackWorkbench.noClaimSupport')}</p>{/if}
				</section>

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.gaps')}</h3><span>{selected.gaps.length}</span></div>
					{#if selected.gaps.length}<ul class="gap-list">{#each selected.gaps as gap}<li>{gap}</li>{/each}</ul>{:else}<p class="muted">{$t('feedbackWorkbench.noGaps')}</p>{/if}
				</section>

					<section class="detail-section analysis-panel">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.aiSuggestion')}</h3><span>{$t('feedbackWorkbench.candidateOnly')}</span></div>
					{#if selected.analysis}
						<div class="analysis-grid"><div><span class="section-label">{$t('feedbackWorkbench.possibleIssue')}</span><strong>{problemLabel(selected.analysis.problem_type)}</strong></div><div><span class="section-label">{$t('feedbackWorkbench.confidence')}</span><strong>{Math.round(selected.analysis.confidence * 100)}%</strong></div></div>
					{:else}<p class="muted">{$t('feedbackWorkbench.analysisCollecting')}</p>{/if}
					{#if selected.technical_error}<p class="technical-note">{$t('feedbackWorkbench.statusFailed')}: {$t('feedbackWorkbench.statusHelp')}</p>{/if}
					</section>

					{#if selected.annotation && (selected.status === 'accepted' || selected.status === 'withdrawn')}
						<section class="detail-section annotation-record">
							<div class="section-heading"><h3>{$t('feedbackWorkbench.savedAnnotation')}</h3><span>{$t('feedbackWorkbench.readOnly')}</span></div>
							<div class="annotation-summary-grid">
								<div><span class="section-label">{$t('feedbackWorkbench.annotationProblem')}</span><strong>{problemLabel(annotationText('problem_type'))}</strong></div>
								<div><span class="section-label">{$t('feedbackWorkbench.annotationSeverity')}</span><strong>{severityLabel(annotationText('severity'))}</strong></div>
								<div><span class="section-label">{$t('feedbackWorkbench.annotationUses')}</span><strong>{annotationUsesLabel()}</strong></div>
							</div>
							<div class="annotation-summary-field"><span class="section-label">{$t('feedbackWorkbench.annotationTarget')}</span><p>{annotationText('target') || $t('feedbackWorkbench.noTarget')}</p></div>
							<div class="annotation-summary-field"><span class="section-label">{$t('feedbackWorkbench.annotationReason')}</span><p>{annotationText('reason') || $t('feedbackWorkbench.noReason')}</p></div>
						</section>
					{/if}

					{#if selected.status === 'needs_annotation' || selected.status === 'ready_for_review' || selected.status === 'rejected' || selected.status === 'insufficient'}
						<section id="annotation-panel" class="detail-section annotation-panel">
							<div class="section-heading"><h3>{$t('feedbackWorkbench.annotationTitle')}</h3><span>{$t('feedbackWorkbench.annotationHint')}</span></div>
							{#if annotationError}<div class="inline-error" role="alert"><AlertTriangle size={15} />{annotationError}</div>{/if}
							{#if annotationSaved}<div class="inline-success" role="status"><CheckCircle2 size={15} />{$t('feedbackWorkbench.annotationSaved')}</div>{/if}
							<div class="annotation-grid">
								<label><span class="field-label">{$t('feedbackWorkbench.annotationProblem')}</span><select bind:value={annotationProblemType}><option value="fact_error">{$t('feedbackWorkbench.problemFactError')}</option><option value="source_missing">{$t('feedbackWorkbench.problemSourceMissing')}</option><option value="evidence_mismatch">{$t('feedbackWorkbench.problemEvidenceMismatch')}</option><option value="retrieval_failure">{$t('feedbackWorkbench.problemRetrievalFailure')}</option><option value="tool_failure">{$t('feedbackWorkbench.problemToolFailure')}</option><option value="intent_mismatch">{$t('feedbackWorkbench.problemIntentMismatch')}</option><option value="incomplete_answer">{$t('feedbackWorkbench.problemIncomplete')}</option><option value="style_or_format">{$t('feedbackWorkbench.problemStyle')}</option><option value="undetermined_dissatisfaction">{$t('feedbackWorkbench.problemUndetermined')}</option></select></label>
								<label><span class="field-label">{$t('feedbackWorkbench.annotationSeverity')}</span><select bind:value={annotationSeverity}><option value="low">{$t('feedbackWorkbench.severityLow')}</option><option value="medium">{$t('feedbackWorkbench.severityMedium')}</option><option value="high">{$t('feedbackWorkbench.severityHigh')}</option><option value="critical">{$t('feedbackWorkbench.severityCritical')}</option></select></label>
							</div>
							<label class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationTarget')}</span><textarea bind:value={annotationTarget} rows="4" placeholder={$t('feedbackWorkbench.annotationTargetPlaceholder')}></textarea></label>
							{#if annotationSources.length}
								<div class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationSources')}</span><div class="annotation-sources">{#each annotationSources as source}<label class="source-choice"><input type="checkbox" value={String(source.source_ref ?? source.source_id)} bind:group={annotationSupportRefs} /><span><strong>{sourceTitle(source)}</strong>{#if sourceLocator(source)}<small>{sourceLocator(source)}</small>{/if}</span></label>{/each}</div></div>
							{:else}<p class="muted">{$t('feedbackWorkbench.annotationNoSources')}</p>{/if}
							<div class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationUses')}</span><div class="use-choices"><label><input type="checkbox" value="evaluation" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.useEvaluation')}</label><label><input type="checkbox" value="sft" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.useSft')}</label><label><input type="checkbox" value="preference" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.usePreference')}</label></div></div>
							<label class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationReason')}</span><textarea bind:value={annotationReason} rows="3" placeholder={$t('feedbackWorkbench.annotationReasonPlaceholder')}></textarea></label>
							<div class="annotation-actions"><span class="muted">{$t('feedbackWorkbench.annotationNoIds')}</span><button type="button" class="primary-button" on:click={saveAnnotation} disabled={annotationSaving || !annotationReason.trim()}>{annotationSaving ? $t('feedbackWorkbench.annotationSaving') : $t('feedbackWorkbench.annotationSave')}</button></div>
						</section>
					{/if}

					{#if selected.annotation && selected.current_annotation_digest && (selected.status === 'ready_for_review' || selected.status === 'accepted')}
						<section class="detail-section review-panel">
							<div class="section-heading"><h3>{$t('feedbackWorkbench.reviewTitle')}</h3><span>{$t('feedbackWorkbench.reviewHint')}</span></div>
							{#if reviewError}<div class="inline-error" role="alert"><AlertTriangle size={15} />{reviewError}</div>{/if}
							<label class="field-block"><span class="field-label">{$t('feedbackWorkbench.reviewReason')}</span><textarea bind:value={reviewReason} rows="2" placeholder={$t('feedbackWorkbench.reviewReasonPlaceholder')}></textarea></label>
							<div class="review-actions"><button type="button" class="review-button review-button--accept" on:click={() => submitReview('accept')} disabled={reviewSaving || !reviewReason.trim()}><CheckCircle2 size={15} />{$t('feedbackWorkbench.reviewAccept')}</button><button type="button" class="review-button" on:click={() => submitReview('insufficient')} disabled={reviewSaving || !reviewReason.trim()}>{$t('feedbackWorkbench.reviewInsufficient')}</button><button type="button" class="review-button review-button--reject" on:click={() => submitReview('reject')} disabled={reviewSaving || !reviewReason.trim()}><XCircle size={15} />{$t('feedbackWorkbench.reviewReject')}</button>{#if selected.status === 'accepted'}<button type="button" class="review-button" on:click={() => submitReview('withdraw')} disabled={reviewSaving || !reviewReason.trim()}>{$t('feedbackWorkbench.reviewWithdraw')}</button>{/if}</div>
						</section>
					{/if}

					{#if selected.review_decisions?.length}
						<section class="detail-section">
							<div class="section-heading"><h3>{$t('feedbackWorkbench.reviewHistory')}</h3><span>{selected.review_decisions.length}</span></div>
							<div class="review-history">{#each selected.review_decisions as review}<div class="review-history__row"><strong>{decisionLabel(review.decision)}</strong><span>{formatDate(review.created_at)}</span><p>{review.reason}</p></div>{/each}</div>
						</section>
					{/if}
				{/if}
		</main>
	</div>
</section>

<style>
	.workbench { padding: 4px 0 48px; }
	.workbench-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 24px; }
	.header-actions { display: flex; align-items: center; gap: 10px; }
	.export-button { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 0 12px; border: 1px solid var(--brand-border); border-radius: 7px; background: var(--brand-primary); color: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
	.export-button:hover { filter: brightness(.96); }
	.export-button:disabled { opacity: .6; cursor: default; }
	.dataset-link { padding: 8px 11px; border: 1px solid var(--border-subtle); border-radius: 6px; color: var(--text-primary); background: var(--surface-raised); font-size: 12px; font-weight: 700; text-decoration: none; white-space: nowrap; }
	.dataset-link:hover { border-color: var(--accent-primary); }
	.eyebrow { margin: 0 0 4px; color: var(--brand-primary); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
	h1, h2, h3, p { margin-top: 0; }
	h1 { margin-bottom: 6px; font-size: clamp(24px, 3vw, 34px); line-height: 1.15; letter-spacing: 0; }
	.lede { margin-bottom: 0; color: var(--text-secondary); font-size: 14px; }
	.icon-button { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--surface-card); cursor: pointer; }
	.icon-button:hover { border-color: var(--brand-border); color: var(--brand-primary); }
	.icon-button:disabled { opacity: .55; cursor: default; }
	.spin { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	.notice { display: flex; align-items: center; gap: 8px; padding: 12px 14px; margin-bottom: 16px; border: 1px solid var(--danger-border); background: var(--danger-bg); color: var(--danger-text); border-radius: 8px; font-size: 13px; }
	.notice--success { border-color: var(--success-border); background: var(--success-bg); color: var(--success-text); }
	.status-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 18px; border: 1px solid var(--border-default); border-radius: 8px; overflow: hidden; background: var(--border-default); }
	.status-strip div { display: grid; gap: 3px; padding: 12px 14px; background: var(--surface-card); }
	.status-strip strong { font-size: 20px; line-height: 1; }
	.status-strip span { color: var(--text-secondary); font-size: 11px; }
		.workbench-grid { display: grid; grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); gap: 18px; align-items: start; }
	.case-list, .case-detail { min-width: 0; border: 1px solid var(--border-default); border-radius: 8px; background: var(--surface-card); box-shadow: var(--shadow-xs); }
	.case-list { overflow: hidden; }
	.list-toolbar { display: grid; gap: 10px; padding: 14px; border-bottom: 1px solid var(--border-default); background: var(--bg-subtle); }
	.search-box { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); color: var(--text-secondary); }
	.search-box input { width: 100%; min-width: 0; border: 0; outline: 0; background: transparent; font-size: 13px; }
	select { width: 100%; padding: 8px 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); font-size: 13px; }
	.case-items { display: grid; }
	.case-item { display: block; width: 100%; padding: 14px; border: 0; border-bottom: 1px solid var(--border-default); background: transparent; text-align: left; cursor: pointer; color: var(--text-primary); }
	.case-item:last-child { border-bottom: 0; }
	.case-item:hover, .case-item.selected { background: var(--brand-soft); }
	.case-item__topline, .case-item__meta, .detail-kicker, .section-heading, .analysis-grid { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
	.case-type { color: var(--brand-primary); font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; }
		.case-item strong { display: -webkit-box; overflow: hidden; margin: 8px 0 5px; font-size: 13px; line-height: 1.4; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; }
		.case-item__documents { display: -webkit-box; overflow: hidden; color: var(--text-tertiary); font-size: 11px; line-height: 1.4; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; }
	.case-item__meta { justify-content: flex-start; margin-top: 9px; color: var(--text-secondary); font-size: 11px; }
	.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning-text); }
	.empty-state, .detail-placeholder { display: grid; place-items: center; gap: 8px; min-height: 220px; padding: 28px; color: var(--text-secondary); text-align: center; }
	.empty-state strong, .empty-state p, .detail-placeholder h2, .detail-placeholder p { margin: 0; }
	:global(.empty-state svg) { color: var(--success-text); }
	.loader { width: 22px; height: 22px; border: 2px solid var(--border-default); border-top-color: var(--brand-primary); border-radius: 50%; animation: spin .8s linear infinite; }
	.detail-placeholder { min-height: 520px; }
	.placeholder-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 12px; color: var(--brand-primary); background: var(--brand-soft); }
	.detail-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; padding: 22px 24px 18px; border-bottom: 1px solid var(--border-default); }
	.detail-header h2 { margin: 8px 0 0; font-size: 22px; }
	.detail-context { max-width: 620px; margin: 8px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.45; }
	.detail-next { display: grid; gap: 5px; min-width: 170px; padding: 11px 12px; border: 1px solid var(--brand-border); border-radius: 7px; background: var(--brand-soft); }
	.detail-next strong { font-size: 13px; }
	.jump-button { width: fit-content; padding: 0; border: 0; background: transparent; color: var(--brand-primary); font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
	.detail-kicker { justify-content: flex-start; color: var(--text-secondary); font-size: 12px; }
	.status-pill { padding: 4px 8px; border-radius: 999px; color: var(--warning-text); background: var(--warning-bg); font-weight: 700; }
	.prompt-answer { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding: 20px 24px; background: var(--bg-subtle); border-bottom: 1px solid var(--border-default); }
	.prompt-answer p { margin: 6px 0 0; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
	.section-label { display: block; color: var(--text-secondary); font-size: 11px; font-weight: 800; letter-spacing: .05em; text-transform: uppercase; }
	.detail-section { padding: 20px 24px; border-bottom: 1px solid var(--border-default); }
	.detail-section:last-child { border-bottom: 0; }
	.section-heading { margin-bottom: 12px; }
	.section-heading h3 { margin: 0; font-size: 15px; }
	.section-heading > span { color: var(--text-secondary); font-size: 12px; }
	.signal-list { display: grid; }
	.signal { display: grid; gap: 8px; padding: 12px 0; border-top: 1px solid var(--border-default); font-size: 13px; }
	.signal__heading { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; min-width: 0; }
	.signal__heading strong { min-width: 0; overflow-wrap: anywhere; }
	.signal__badge { display: inline-flex; align-items: center; gap: 5px; color: var(--success-text); font-weight: 700; }
	.signal__badge--negative { color: var(--danger-text); }
	.signal__badge--correction { color: var(--warning-text); }
	.signal__body { margin: 0; padding-left: 20px; border-left: 2px solid var(--border-default); color: var(--text-secondary); line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
	.signal__facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 20px; margin: 0; }
	.signal__facts div { min-width: 0; }
	.signal__facts dt { color: var(--text-secondary); font-size: 11px; }
	.signal__facts dd { margin: 2px 0 0; font-weight: 700; overflow-wrap: anywhere; }
	.scope-list { display: flex; flex-wrap: wrap; gap: 8px; }
		.scope-chip { display: inline-flex; max-width: 100%; box-sizing: border-box; padding: 6px 9px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); color: var(--text-primary); font-size: 12px; line-height: 1.4; text-decoration: none; overflow-wrap: anywhere; }
	.scope-chip:hover, .source-link:hover { border-color: var(--brand-border); color: var(--brand-primary); }
	.coverage-badge { color: var(--text-secondary) !important; }
	.coverage-badge--complete { color: var(--success-text) !important; }
	.coverage-badge--partial { color: var(--warning-text) !important; }
	.coverage-badge--failed { color: var(--danger-text) !important; }
	.source-list { display: grid; gap: 10px; }
	.source-row { display: grid; grid-template-columns: 28px 1fr; gap: 10px; padding: 12px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); }
	.source-icon { display: grid; place-items: center; width: 28px; height: 28px; color: var(--brand-primary); }
	.source-row strong, .source-row span { display: block; }
	.source-row strong { font-size: 13px; }
	.source-row span { margin-top: 2px; color: var(--text-secondary); font-size: 11px; overflow-wrap: anywhere; }
	.source-link { color: inherit; text-decoration: underline; text-decoration-color: color-mix(in srgb, currentColor 30%, transparent); text-underline-offset: 2px; }
	.source-row p { margin: 8px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
	.support-row { display: grid; gap: 4px; padding: 10px 0; border-top: 1px solid var(--border-default); font-size: 13px; }
	.support-row span { color: var(--text-secondary); font-size: 11px; overflow-wrap: anywhere; }
	.gap-list { margin: 0; padding-left: 18px; color: var(--warning-text); font-size: 13px; line-height: 1.6; }
	.muted { margin: 0; color: var(--text-secondary); font-size: 13px; }
	.detail-section--warning { background: color-mix(in srgb, var(--warning-bg) 35%, transparent); }
	.omitted { display: flex; align-items: flex-start; gap: 8px; padding: 7px 0; color: var(--warning-text); font-size: 13px; }
	.omitted > span { display: grid; gap: 3px; min-width: 0; overflow-wrap: anywhere; }
	.omitted small { color: var(--text-secondary); font-size: 11px; }
	.analysis-panel { background: var(--brand-soft); }
	.analysis-grid { justify-content: flex-start; gap: 44px; }
	.analysis-grid strong { display: block; margin-top: 5px; font-size: 14px; text-transform: capitalize; }
	.annotation-record { background: var(--bg-subtle); }
	.annotation-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
	.annotation-summary-grid strong { display: block; margin-top: 5px; font-size: 13px; overflow-wrap: anywhere; }
	.annotation-summary-field { display: grid; gap: 6px; margin-top: 14px; }
	.annotation-summary-field p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
		.technical-note { margin: 16px 0 0; color: var(--danger-text); font-size: 12px; line-height: 1.5; }
		.annotation-panel { background: var(--bg-subtle); scroll-margin-top: 16px; }
		.annotation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
		.field-block, .annotation-grid label { display: grid; gap: 6px; margin-top: 12px; }
		.field-label { color: var(--text-secondary); font-size: 11px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
		textarea { width: 100%; box-sizing: border-box; resize: vertical; min-height: 74px; padding: 9px 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); font: inherit; line-height: 1.5; }
		.annotation-sources { display: grid; gap: 8px; }
		.source-choice { display: flex; align-items: flex-start; gap: 9px; padding: 9px 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); cursor: pointer; }
		.source-choice span { display: grid; gap: 2px; min-width: 0; }
		.source-choice small { color: var(--text-secondary); overflow-wrap: anywhere; }
		.use-choices { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; }
		.use-choices label { display: flex; align-items: center; gap: 6px; }
		.annotation-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 18px; }
		.primary-button { padding: 9px 14px; border: 0; border-radius: 6px; background: var(--brand-primary); color: white; font: inherit; font-weight: 700; cursor: pointer; }
		.primary-button:disabled { opacity: .55; cursor: default; }
		.inline-error, .inline-success { display: flex; align-items: center; gap: 7px; padding: 9px 10px; border-radius: 6px; font-size: 12px; }
		.inline-error { color: var(--danger-text); background: var(--danger-bg); }
		.inline-success { color: var(--success-text); background: var(--success-bg); }
		.review-panel { background: color-mix(in srgb, var(--brand-soft) 50%, var(--surface-card)); }
		.review-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
		.review-button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 11px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--surface-card); color: var(--text-primary); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
		.review-button:hover { border-color: var(--brand-border); }
		.review-button:disabled { opacity: .5; cursor: default; }
		.review-button--accept { color: var(--success-text); }
	.review-button--reject { color: var(--danger-text); }
	button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible { outline: 3px solid color-mix(in srgb, var(--brand-primary) 35%, transparent); outline-offset: 2px; }
		.review-history { display: grid; gap: 8px; }
		.review-history__row { display: grid; grid-template-columns: auto auto; gap: 4px 10px; padding: 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); font-size: 12px; }
		.review-history__row span { color: var(--text-secondary); text-align: right; }
		.review-history__row p { grid-column: 1 / -1; margin: 2px 0 0; color: var(--text-secondary); line-height: 1.45; }
	.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
	@media (max-width: 840px) { .workbench-grid { grid-template-columns: 1fr; } .case-list { order: 0; } .case-detail { order: 1; } .detail-placeholder { min-height: 260px; } }
		@media (max-width: 840px) { .detail-next { min-width: 150px; } }
		@media (max-width: 600px) { .workbench-header { gap: 12px; flex-direction: column; } .header-actions { width: 100%; flex-wrap: wrap; } .export-button { flex: 1 1 auto; } .status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } .prompt-answer, .annotation-grid, .annotation-summary-grid, .signal__facts { grid-template-columns: 1fr; } .detail-header, .prompt-answer, .detail-section { padding-left: 16px; padding-right: 16px; } .detail-header { flex-direction: column; } .detail-next { width: 100%; box-sizing: border-box; } .annotation-actions { align-items: stretch; flex-direction: column; } }
</style>
