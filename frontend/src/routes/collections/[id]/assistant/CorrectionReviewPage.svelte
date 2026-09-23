<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, CircleAlert, LoaderCircle, X } from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import {
		createChatCorrectionReview,
		createChatCorrectionSample,
		fetchChatCorrectionReviewStatus,
		fetchChatCorrectionReviews,
		type ChatCorrectionCase,
		type ChatCorrectionReview,
		type ChatCorrectionReviewDecision,
		type ChatCorrectionReviewStatus,
		type ChatCorrectionSample
	} from '../../../_shared/chatSessions';
	import { t } from '../../../_shared/i18n';

	export let sessionId = '';
	export let caseItem: ChatCorrectionCase;
	export let onClose: () => void = () => {};

	let sample: ChatCorrectionSample | null = null;
	let reviews: ChatCorrectionReview[] = [];
	let reviewStatus: ChatCorrectionReviewStatus | null = null;
	let loading = true;
	let submitting = false;
	let error = '';
	let decision: ChatCorrectionReviewDecision = 'accept';
	let reason = '';
	let supportMessageIds: string[] = [];

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		error = '';
		sample = null;
		reviews = [];
		reviewStatus = null;
		try {
			sample = await createChatCorrectionSample(sessionId, caseItem.case_id);
			const [history, status] = await Promise.all([
				fetchChatCorrectionReviews(sessionId, sample.sample_id),
				fetchChatCorrectionReviewStatus(sessionId, sample.sample_id)
			]);
			reviews = history.items;
			reviewStatus = status;
		} catch (value) {
			error = errorMessage(value);
		} finally {
			loading = false;
		}
	}

	function observationId(value: Record<string, unknown>) {
		return typeof value.message_id === 'string' ? value.message_id : '';
	}

	function toggleSupport(id: string) {
		if (!id) return;
		supportMessageIds = supportMessageIds.includes(id)
			? supportMessageIds.filter((item) => item !== id)
			: [...supportMessageIds, id];
	}

	async function submit() {
		if (!sample || submitting) return;
		submitting = true;
		error = '';
		try {
			const saved = await createChatCorrectionReview(sessionId, sample.sample_id, {
				decision,
				reason: reason.trim() || null,
				support_message_ids: supportMessageIds
			});
			reviews = [...reviews, saved];
			reviewStatus = await fetchChatCorrectionReviewStatus(sessionId, sample.sample_id);
			reason = '';
		} catch (value) {
			error = errorMessage(value);
		} finally {
			submitting = false;
		}
	}

	function statusLabel(value: ChatCorrectionReviewStatus | null) {
		if (!value) return '';
		if (value.state === 'accept') return $t('researchAgent.correctionReview.accepted');
		if (value.state === 'reject') return $t('researchAgent.correctionReview.rejected');
		if (value.state === 'withdraw') return $t('researchAgent.correctionReview.withdrawn');
		if (value.state === 'insufficient') return $t('researchAgent.correctionReview.insufficient');
		if (value.state === 'stale') return $t('researchAgent.correctionReview.stale');
		return $t('researchAgent.correctionReview.pending');
	}
</script>

<div class="review-backdrop" role="presentation" on:click={(event) => event.target === event.currentTarget && onClose()}>
	<div class="review-panel" role="dialog" aria-modal="true" aria-labelledby="correction-review-title" tabindex="-1">
		<header>
			<div>
				<p class="eyebrow">{$t('researchAgent.correctionReview.title')}</p>
				<h2 id="correction-review-title">{caseItem.case_id.slice(-12)}</h2>
			</div>
			<button class="icon-button" type="button" aria-label={$t('researchAgent.correctionReview.close')} on:click={onClose}>
				<X size={18} />
			</button>
		</header>

		{#if loading}
			<div class="loading" role="status"><LoaderCircle size={17} class="spin" />{$t('researchAgent.correctionReview.freezing')}</div>
		{:else if error}
			<div class="error" role="alert"><CircleAlert size={17} />{error}</div>
		{:else if sample}
			<div class="status-line" data-state={reviewStatus?.state ?? 'pending'}>
				<strong>{$t('researchAgent.correctionReview.status')}</strong><span>{statusLabel(reviewStatus)}</span>
			</div>
			<section class="evidence-grid">
				<article>
					<h3>{$t('researchAgent.correctionReview.input')}</h3>
					<pre>{JSON.stringify(sample.input, null, 2)}</pre>
				</article>
				<article>
					<h3>{$t('researchAgent.correctionReview.target')}</h3>
					<p class="target">{sample.target}</p>
				</article>
				<article>
					<h3>{$t('researchAgent.correctionReview.observations')}</h3>
					<div class="observations">
						{#each sample.observations as observation}
							<label class="observation">
								<input
									type="checkbox"
									checked={supportMessageIds.includes(observationId(observation))}
									on:change={() => toggleSupport(observationId(observation))}
								/>
								<span><code>{observationId(observation) || 'event'}</code> {String(observation.kind ?? '')}</span>
							</label>
						{/each}
					</div>
				</article>
				<article>
					<h3>{$t('researchAgent.correctionReview.sources')}</h3>
					<pre>{JSON.stringify(sample.source_refs, null, 2)}</pre>
				</article>
			</section>

			<section class="decision-form">
				<label>
					<span>{$t('researchAgent.correctionReview.decision')}</span>
					<select bind:value={decision} disabled={submitting}>
						<option value="accept">{$t('researchAgent.correctionReview.accept')}</option>
						<option value="reject">{$t('researchAgent.correctionReview.reject')}</option>
						<option value="insufficient">{$t('researchAgent.correctionReview.insufficient')}</option>
						<option value="withdraw">{$t('researchAgent.correctionReview.withdraw')}</option>
					</select>
				</label>
				<label>
					<span>{$t('researchAgent.correctionReview.reason')}</span>
					<textarea bind:value={reason} rows="3" maxlength="4000" placeholder={$t('researchAgent.correctionReview.reasonPlaceholder')} disabled={submitting}></textarea>
				</label>
				<button class="submit" type="button" disabled={submitting || reviewStatus?.state === 'stale'} on:click={submit}>
					{#if submitting}<LoaderCircle size={16} class="spin" />{:else}<Check size={16} />{/if}
					<span>{submitting ? $t('researchAgent.correctionReview.submitting') : $t('researchAgent.correctionReview.submit')}</span>
				</button>
			</section>

			{#if reviews.length}
				<section class="history">
					<h3>{$t('researchAgent.correctionReview.status')}</h3>
					{#each reviews as review (review.review_id)}
						<div class="history-row"><span>#{review.seq} {review.decision}</span><time>{new Date(review.created_at).toLocaleString()}</time></div>
					{/each}
				</section>
			{/if}
		{/if}
	</div>
</div>

<style>
	.review-backdrop { position: fixed; inset: 0; z-index: 55; display: grid; place-items: center; padding: 20px; background: color-mix(in srgb, var(--surface-page) 72%, transparent); }
	.review-panel { width: min(920px, 100%); max-height: min(840px, 92vh); overflow: auto; padding: 20px; background: var(--surface-card); border: 1px solid var(--border-default); box-shadow: 0 18px 48px rgb(0 0 0 / 18%); }
	header { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
	.eyebrow { margin: 0 0 4px; color: var(--text-tertiary); font-size: 11px; text-transform: uppercase; }
	h2 { margin: 0; font-size: 20px; }
	.icon-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--border-default); background: transparent; color: var(--text-secondary); cursor: pointer; }
	.loading, .error, .status-line { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border: 1px solid var(--border-default); font-size: 13px; }
	.error { color: var(--status-error, #b42318); }
	.status-line { justify-content: space-between; margin-bottom: 14px; }
	.status-line[data-state='accept'] { color: var(--status-success, #18794e); }
	.status-line[data-state='stale'] { color: var(--status-error, #b42318); }
	.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
	article { min-width: 0; padding: 12px; border: 1px solid var(--border-default); }
	h3 { margin: 0 0 8px; font-size: 13px; color: var(--text-secondary); }
	pre { max-height: 180px; overflow: auto; margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 11px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text-primary); }
	.target { margin: 0; line-height: 1.55; }
	.observations { display: grid; gap: 7px; max-height: 180px; overflow: auto; }
	.observation { display: flex; align-items: flex-start; gap: 7px; font-size: 12px; }
	.observation code { color: var(--text-tertiary); }
	.decision-form { display: grid; gap: 12px; margin-top: 14px; }
	.decision-form label { display: grid; gap: 6px; }
	.decision-form label > span { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
	select, textarea { width: 100%; box-sizing: border-box; padding: 8px 9px; border: 1px solid var(--border-default); background: var(--surface-page); color: var(--text-primary); font: inherit; }
	.submit { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 38px; padding: 0 13px; border: 1px solid var(--brand-primary); background: var(--brand-primary); color: white; cursor: pointer; }
	.submit:disabled { cursor: wait; opacity: .55; }
	.history { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border-default); }
	.history-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; font-size: 12px; }
	.history-row time { color: var(--text-tertiary); }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 700px) { .review-backdrop { padding: 0; place-items: end center; } .review-panel { max-height: 94vh; } .evidence-grid { grid-template-columns: 1fr; } }
</style>
