<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import {
		AlertTriangle,
		CheckCircle2,
		ChevronRight,
		FileText,
		RefreshCw,
		Search,
		XCircle
	} from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import { t } from '../../../_shared/i18n';
	import {
		fetchFeedbackCase,
		fetchFeedbackCases,
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

	async function openCase(item: FeedbackCaseSummary) {
		detailLoading = true;
		error = '';
		try {
			selected = await fetchFeedbackCase(collectionId, item.case_id);
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
		try {
			await submitFeedbackReview(collectionId, selected.case_id, {
				expected_annotation_digest: selected.current_annotation_digest,
				decision,
				reason: reviewReason.trim()
			});
			selected = await fetchFeedbackCase(collectionId, selected.case_id);
			loadAnnotationForm(selected);
			await loadCases();
		} catch (err) {
			reviewError = errorMessage(err);
		} finally {
			reviewSaving = false;
		}
	}

	function formatDate(value: string) {
		const date = new Date(value);
		return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
	}

	function label(value: string | null | undefined) {
		return value ? value.replaceAll('_', ' ') : $t('feedbackWorkbench.unknown');
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
		return String(source.document_title ?? source.title ?? $t('feedbackWorkbench.source'));
	}

	function sourceLocator(source: Record<string, unknown>) {
		return [source.source_ref, source.heading_path, source.page ? `p. ${source.page}` : '']
			.filter(Boolean)
			.join(' · ');
	}

	function claimText(claim: Record<string, unknown>) {
		return String(claim.claim ?? claim.statement ?? claim.text ?? $t('feedbackWorkbench.unknown'));
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
				<div class="empty-state"><span class="loader"></span><p>{$t('feedbackWorkbench.loadingCases')}</p></div>
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
								<span class="case-type">{label(item.problem_type)}</span>
								<ChevronRight size={16} />
							</div>
							<strong>{item.question_preview || item.answer_preview || $t('feedbackWorkbench.unknown')}</strong>
							{#if item.document_titles.length}
								<span class="case-item__documents">{item.document_titles.join(' · ')}</span>
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

		<main class="case-detail" aria-live="polite">
			{#if detailLoading}
				<div class="empty-state"><span class="loader"></span><p>{$t('feedbackWorkbench.loadingDetails')}</p></div>
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
					</div>
				</div>

				<section class="prompt-answer">
					<div><span class="section-label">{$t('feedbackWorkbench.question')}</span><p>{selected.question || $t('feedbackWorkbench.noQuestion')}</p></div>
					<div><span class="section-label">{$t('feedbackWorkbench.answer')}</span><p>{selected.answer || $t('feedbackWorkbench.noAnswer')}</p></div>
				</section>

				{#if selected.source_signals.length}
					<section class="detail-section">
						<div class="section-heading"><h3>{$t('feedbackWorkbench.feedbackSignal')}</h3><span>{selected.source_signals.length} {selected.source_signals.length === 1 ? $t('feedbackWorkbench.record') : $t('feedbackWorkbench.records')}</span></div>
						{#each selected.source_signals as signal}
							<div class="signal"><span class:signal--negative={signal.rating === 'not_helpful'}>{signal.rating === 'not_helpful' ? $t('feedbackWorkbench.notHelpful') : $t('feedbackWorkbench.helpful')}</span><strong>{label(signal.reason)}</strong>{#if signal.comment}<p>{signal.comment}</p>{/if}</div>
						{/each}
					</section>
				{/if}

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.requestedScope')}</h3><span>{selected.requested_scope.length}</span></div>
					{#if selected.requested_scope.length}
						<div class="scope-list">{#each selected.requested_scope as source}<span class="scope-chip">{sourceTitle(source)}</span>{/each}</div>
					{:else}<p class="muted">{$t('feedbackWorkbench.noRequestedScope')}</p>{/if}
				</section>

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.sourceCoverage')}</h3><span class="coverage-badge coverage-badge--{selected.coverage_status}">{coverageLabel(selected.coverage_status)}</span></div>
					{#if selected.inspected_sources.length}
						<div class="source-list">
							{#each selected.inspected_sources as source}
								<article class="source-row"><div class="source-icon"><FileText size={16} /></div><div><strong>{sourceTitle(source)}</strong><span>{sourceLocator(source)}</span>{#if source.quote}<p>{String(source.quote)}</p>{:else}<p class="muted">{$t('feedbackWorkbench.noQuote')}</p>{/if}</div></article>
							{/each}
						</div>
					{:else}<p class="muted">{$t('feedbackWorkbench.inspectedNone')}</p>{/if}
				</section>

				{#if selected.omitted_candidates.length}
					<section class="detail-section detail-section--warning"><div class="section-heading"><h3>{$t('feedbackWorkbench.omittedCandidates')}</h3><span>{selected.omitted_candidates.length}</span></div>{#each selected.omitted_candidates as source}<div class="omitted"><XCircle size={16} /><span>{sourceTitle(source)}{sourceLocator(source) ? ` · ${sourceLocator(source)}` : ''}</span></div>{/each}</section>
				{/if}

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.claimSupport')}</h3><span>{selected.claim_support.length}</span></div>
					{#if selected.claim_support.length}{#each selected.claim_support as claim}<div class="support-row"><strong>{claimText(claim)}</strong><span>{String(claim.source_ref ?? claim.source ?? '')}</span></div>{/each}{:else}<p class="muted">{$t('feedbackWorkbench.noClaimSupport')}</p>{/if}
				</section>

				<section class="detail-section">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.gaps')}</h3><span>{selected.gaps.length}</span></div>
					{#if selected.gaps.length}<ul class="gap-list">{#each selected.gaps as gap}<li>{gap}</li>{/each}</ul>{:else}<p class="muted">{$t('feedbackWorkbench.noGaps')}</p>{/if}
				</section>

					<section class="detail-section analysis-panel">
					<div class="section-heading"><h3>{$t('feedbackWorkbench.aiSuggestion')}</h3><span>{$t('feedbackWorkbench.candidateOnly')}</span></div>
					{#if selected.analysis}
						<div class="analysis-grid"><div><span class="section-label">{$t('feedbackWorkbench.possibleIssue')}</span><strong>{label(selected.analysis.problem_type)}</strong></div><div><span class="section-label">{$t('feedbackWorkbench.confidence')}</span><strong>{Math.round(selected.analysis.confidence * 100)}%</strong></div></div>
					{:else}<p class="muted">{$t('feedbackWorkbench.analysisCollecting')}</p>{/if}
					{#if selected.technical_error}<p class="technical-note">{$t('feedbackWorkbench.statusFailed')}: {$t('feedbackWorkbench.statusHelp')}</p>{/if}
					</section>

					{#if selected.status === 'needs_annotation' || selected.status === 'ready_for_review' || selected.status === 'rejected' || selected.status === 'insufficient'}
						<section class="detail-section annotation-panel">
							<div class="section-heading"><h3>{$t('feedbackWorkbench.annotationTitle')}</h3><span>{$t('feedbackWorkbench.annotationHint')}</span></div>
							{#if annotationError}<div class="inline-error" role="alert"><AlertTriangle size={15} />{annotationError}</div>{/if}
							{#if annotationSaved}<div class="inline-success" role="status"><CheckCircle2 size={15} />{$t('feedbackWorkbench.annotationSaved')}</div>{/if}
							<div class="annotation-grid">
								<label><span class="field-label">{$t('feedbackWorkbench.annotationProblem')}</span><select bind:value={annotationProblemType}><option value="fact_error">{$t('feedbackWorkbench.problemFactError')}</option><option value="source_missing">{$t('feedbackWorkbench.problemSourceMissing')}</option><option value="evidence_mismatch">{$t('feedbackWorkbench.problemEvidenceMismatch')}</option><option value="retrieval_failure">{$t('feedbackWorkbench.problemRetrievalFailure')}</option><option value="tool_failure">{$t('feedbackWorkbench.problemToolFailure')}</option><option value="intent_mismatch">{$t('feedbackWorkbench.problemIntentMismatch')}</option><option value="incomplete_answer">{$t('feedbackWorkbench.problemIncomplete')}</option><option value="style_or_format">{$t('feedbackWorkbench.problemStyle')}</option><option value="undetermined_dissatisfaction">{$t('feedbackWorkbench.problemUndetermined')}</option></select></label>
								<label><span class="field-label">{$t('feedbackWorkbench.annotationSeverity')}</span><select bind:value={annotationSeverity}><option value="low">{$t('feedbackWorkbench.severityLow')}</option><option value="medium">{$t('feedbackWorkbench.severityMedium')}</option><option value="high">{$t('feedbackWorkbench.severityHigh')}</option><option value="critical">{$t('feedbackWorkbench.severityCritical')}</option></select></label>
							</div>
							<label class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationTarget')}</span><textarea bind:value={annotationTarget} rows="4" placeholder={$t('feedbackWorkbench.annotationTargetPlaceholder')}></textarea></label>
							{#if annotationSources.length}
								<div class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationSources')}</span><div class="annotation-sources">{#each annotationSources as source}<label class="source-choice"><input type="checkbox" value={String(source.source_ref ?? source.source_id)} bind:group={annotationSupportRefs} /><span><strong>{sourceTitle(source)}</strong><small>{sourceLocator(source)}</small></span></label>{/each}</div></div>
							{:else}<p class="muted">{$t('feedbackWorkbench.annotationNoSources')}</p>{/if}
							<div class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationUses')}</span><div class="use-choices"><label><input type="checkbox" value="evaluation" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.useEvaluation')}</label><label><input type="checkbox" value="sft" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.useSft')}</label><label><input type="checkbox" value="preference" bind:group={annotationDatasetUses} />{$t('feedbackWorkbench.usePreference')}</label></div></div>
							<label class="field-block"><span class="field-label">{$t('feedbackWorkbench.annotationReason')}</span><textarea bind:value={annotationReason} rows="3" placeholder={$t('feedbackWorkbench.annotationReasonPlaceholder')}></textarea></label>
							<div class="annotation-actions"><span class="muted">{$t('feedbackWorkbench.annotationNoIds')}</span><button type="button" class="primary-button" on:click={saveAnnotation} disabled={annotationSaving || !annotationReason.trim()}>{annotationSaving ? $t('feedbackWorkbench.annotationSaving') : $t('feedbackWorkbench.annotationSave')}</button></div>
						</section>
					{/if}

					{#if selected.annotation && selected.current_annotation_digest}
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
							<div class="review-history">{#each selected.review_decisions as review}<div class="review-history__row"><strong>{label(review.decision)}</strong><span>{formatDate(review.created_at)}</span><p>{review.reason}</p></div>{/each}</div>
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
	.workbench-grid { display: grid; grid-template-columns: minmax(260px, 330px) minmax(0, 1fr); gap: 18px; align-items: start; }
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
	.case-item strong { display: block; overflow: hidden; margin: 8px 0 5px; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
	.case-item__documents { display: block; overflow: hidden; color: var(--text-tertiary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
	.case-item__meta { justify-content: flex-start; margin-top: 9px; color: var(--text-secondary); font-size: 11px; }
	.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--warning-text); }
	.empty-state, .detail-placeholder { display: grid; place-items: center; gap: 8px; min-height: 220px; padding: 28px; color: var(--text-secondary); text-align: center; }
	.empty-state strong, .empty-state p, .detail-placeholder h2, .detail-placeholder p { margin: 0; }
	:global(.empty-state svg) { color: var(--success-text); }
	.loader { width: 22px; height: 22px; border: 2px solid var(--border-default); border-top-color: var(--brand-primary); border-radius: 50%; animation: spin .8s linear infinite; }
	.detail-placeholder { min-height: 520px; }
	.placeholder-icon { display: grid; place-items: center; width: 52px; height: 52px; border-radius: 12px; color: var(--brand-primary); background: var(--brand-soft); }
	.detail-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; padding: 22px 24px 18px; border-bottom: 1px solid var(--border-default); }
	.detail-header h2 { margin: 8px 0 0; font-size: 22px; }
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
	.signal { display: flex; align-items: baseline; flex-wrap: wrap; gap: 9px; padding: 10px 0; border-top: 1px solid var(--border-default); font-size: 13px; }
	.signal > span { color: var(--success-text); font-weight: 700; }
	.signal > span.signal--negative { color: var(--danger-text); }
	.signal p { flex-basis: 100%; margin: 2px 0 0; color: var(--text-secondary); }
	.scope-list { display: flex; flex-wrap: wrap; gap: 8px; }
	.scope-chip { padding: 6px 9px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); font-size: 12px; }
	.coverage-badge { color: var(--text-secondary) !important; }
	.coverage-badge--complete { color: var(--success-text) !important; }
	.coverage-badge--partial { color: var(--warning-text) !important; }
	.coverage-badge--failed { color: var(--danger-text) !important; }
	.source-list { display: grid; gap: 10px; }
	.source-row { display: grid; grid-template-columns: 28px 1fr; gap: 10px; padding: 12px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); }
	.source-icon { display: grid; place-items: center; width: 28px; height: 28px; color: var(--brand-primary); }
	.source-row strong, .source-row span { display: block; }
	.source-row strong { font-size: 13px; }
	.source-row span { margin-top: 2px; color: var(--text-secondary); font-size: 11px; }
	.source-row p { margin: 8px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.5; }
	.support-row { display: grid; gap: 4px; padding: 10px 0; border-top: 1px solid var(--border-default); font-size: 13px; }
	.support-row span { color: var(--text-secondary); font-size: 11px; }
	.gap-list { margin: 0; padding-left: 18px; color: var(--warning-text); font-size: 13px; line-height: 1.6; }
	.muted { margin: 0; color: var(--text-secondary); font-size: 13px; }
	.detail-section--warning { background: color-mix(in srgb, var(--warning-bg) 35%, transparent); }
	.omitted { display: flex; align-items: center; gap: 8px; padding: 7px 0; color: var(--warning-text); font-size: 13px; }
	.analysis-panel { background: var(--brand-soft); }
	.analysis-grid { justify-content: flex-start; gap: 44px; }
	.analysis-grid strong { display: block; margin-top: 5px; font-size: 14px; text-transform: capitalize; }
		.technical-note { margin: 16px 0 0; color: var(--danger-text); font-size: 12px; line-height: 1.5; }
		.annotation-panel { background: var(--bg-subtle); }
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
		.review-history { display: grid; gap: 8px; }
		.review-history__row { display: grid; grid-template-columns: auto auto; gap: 4px 10px; padding: 10px; border: 1px solid var(--border-default); border-radius: 6px; background: var(--bg-subtle); font-size: 12px; }
		.review-history__row span { color: var(--text-secondary); text-align: right; }
		.review-history__row p { grid-column: 1 / -1; margin: 2px 0 0; color: var(--text-secondary); line-height: 1.45; }
	.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
	@media (max-width: 840px) { .workbench-grid { grid-template-columns: 1fr; } .case-list { order: 0; } .case-detail { order: 1; } .detail-placeholder { min-height: 260px; } }
		@media (max-width: 600px) { .workbench-header { gap: 12px; } .prompt-answer, .annotation-grid { grid-template-columns: 1fr; } .detail-header, .prompt-answer, .detail-section { padding-left: 16px; padding-right: 16px; } .annotation-actions { align-items: stretch; flex-direction: column; } }
</style>
