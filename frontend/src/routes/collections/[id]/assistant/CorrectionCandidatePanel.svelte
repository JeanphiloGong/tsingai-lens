<script lang="ts">
	import { onMount } from 'svelte';
	import { CircleAlert, Check, LoaderCircle, Play, Sparkles, X } from '@lucide/svelte';
	import { errorMessage } from '../../../_shared/api';
	import {
		createChatCorrectionCandidate,
		fetchChatCorrectionCandidates,
		selectChatCorrectionCandidate,
		type ChatCorrectionCandidate,
		type ChatMessage
	} from '../../../_shared/chatSessions';
	import { t } from '../../../_shared/i18n';

	export let sessionId = '';
	export let messages: ChatMessage[] = [];
	export let onClose: () => void = () => {};

	let candidates: ChatCorrectionCandidate[] = [];
	let challengeMessageId = '';
	let loading = true;
	let running = false;
	let selecting = '';
	let error = '';

	$: challenges = messages.filter((message) => message.role === 'user' && message.content.trim());

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		error = '';
		try {
			candidates = (await fetchChatCorrectionCandidates(sessionId)).items;
		} catch (value) {
			error = errorMessage(value);
		} finally {
			loading = false;
		}
	}

	async function run() {
		if (running) return;
		running = true;
		error = '';
		try {
			const candidate = await createChatCorrectionCandidate(sessionId, {
				challenge_message_id: challengeMessageId || null
			});
			candidates = [candidate, ...candidates.filter((item) => item.candidate_id !== candidate.candidate_id)];
		} catch (value) {
			error = errorMessage(value);
		} finally {
			running = false;
		}
	}

	async function select(candidate: ChatCorrectionCandidate) {
		if (selecting || candidate.status !== 'needs_review' || candidate.selected_sample_id) return;
		selecting = candidate.candidate_id;
		error = '';
		try {
			const selected = await selectChatCorrectionCandidate(sessionId, candidate.candidate_id);
			candidates = candidates.map((item) => (item.candidate_id === selected.candidate_id ? selected : item));
		} catch (value) {
			error = errorMessage(value);
		} finally {
			selecting = '';
		}
	}

	function statusLabel(status: ChatCorrectionCandidate['status']) {
		return $t(`researchAgent.correctionCandidate.status.${status}`);
	}

	function messageLabel(message: ChatMessage) {
		const text = message.content.replace(/\s+/g, ' ').trim();
		return `${text.slice(0, 110)}${text.length > 110 ? '...' : ''}`;
	}
</script>

<div class="backdrop" role="presentation" on:click={(event) => event.target === event.currentTarget && onClose()}>
	<div class="panel" role="dialog" aria-modal="true" aria-labelledby="correction-candidate-title" tabindex="-1">
		<header>
			<div>
				<p class="eyebrow">{$t('researchAgent.correctionCandidate.eyebrow')}</p>
				<h2 id="correction-candidate-title">{$t('researchAgent.correctionCandidate.title')}</h2>
				<p class="hint">{$t('researchAgent.correctionCandidate.hint')}</p>
			</div>
			<button class="icon-button" type="button" aria-label={$t('researchAgent.correctionCandidate.close')} on:click={onClose}>
				<X size={18} />
			</button>
		</header>

		<section class="run-section">
			<label>
				<span>{$t('researchAgent.correctionCandidate.challenge')}</span>
				<select bind:value={challengeMessageId} disabled={running || loading}>
					<option value="">{$t('researchAgent.correctionCandidate.latest')}</option>
					{#each challenges as message (message.message_id)}
						<option value={message.message_id}>{messageLabel(message)}</option>
					{/each}
				</select>
			</label>
			<button class="primary" type="button" disabled={running || loading} on:click={run}>
				{#if running}<LoaderCircle size={15} class="spin" />{:else}<Play size={15} />{/if}
				<span>{$t(running ? 'researchAgent.correctionCandidate.running' : 'researchAgent.correctionCandidate.run')}</span>
			</button>
		</section>

		{#if loading}
			<div class="state" role="status"><LoaderCircle size={16} class="spin" />{$t('researchAgent.correctionCandidate.loading')}</div>
		{:else if !candidates.length}
			<div class="state muted" role="status"><Sparkles size={16} />{$t('researchAgent.correctionCandidate.empty')}</div>
		{:else}
			<section class="candidate-list" aria-label={$t('researchAgent.correctionCandidate.title')}>
				{#each candidates as candidate (candidate.candidate_id)}
					<article class="candidate" data-status={candidate.status}>
						<div class="candidate-heading">
							<div class="status-label"><span class="status-dot"></span>{statusLabel(candidate.status)}</div>
							<code>{candidate.candidate_id.slice(-10)}</code>
						</div>
						<div class="candidate-meta">
							<span>{candidate.answer_message_id ?? $t('researchAgent.correctionCandidate.noAnswer')}</span>
							<span>{candidate.model_call_ids.length} {$t('researchAgent.correctionCandidate.calls')}</span>
						</div>
						{#if candidate.proposal?.rationale}
							<p>{String(candidate.proposal.rationale)}</p>
						{/if}
						{#if candidate.error_code}
							<p class="error-detail"><CircleAlert size={14} />{candidate.error_code}</p>
						{/if}
						<div class="candidate-actions">
							{#if candidate.selected_sample_id}
								<span class="selected"><Check size={14} />{$t('researchAgent.correctionCandidate.selected')}</span>
							{:else if candidate.status === 'needs_review'}
								<button type="button" class="select-button" disabled={Boolean(selecting)} on:click={() => select(candidate)}>
									{#if selecting === candidate.candidate_id}<LoaderCircle size={14} class="spin" />{:else}<Check size={14} />{/if}
									<span>{$t('researchAgent.correctionCandidate.select')}</span>
								</button>
							{/if}
							<details>
								<summary>{$t('researchAgent.correctionCandidate.audit')}</summary>
								<dl>
									<div><dt>{$t('researchAgent.correctionCandidate.events')}</dt><dd>{candidate.event_ids.join(', ') || '-'}</dd></div>
									<div><dt>{$t('researchAgent.correctionCandidate.finish')}</dt><dd>{candidate.finish_reason ?? '-'}</dd></div>
									<div><dt>{$t('researchAgent.correctionCandidate.digest')}</dt><dd>{candidate.digest.slice(0, 16)}</dd></div>
								</dl>
							</details>
						</div>
					</article>
				{/each}
			</section>
		{/if}

		{#if error}<div class="state error" role="alert"><CircleAlert size={16} />{error}</div>{/if}
	</div>
</div>

<style>
	.backdrop { position: fixed; inset: 0; z-index: 57; display: grid; place-items: center; padding: 20px; background: color-mix(in srgb, var(--surface-page) 72%, transparent); }
	.panel { width: min(760px, 100%); max-height: min(820px, 92vh); overflow: auto; padding: 20px; background: var(--surface-card); border: 1px solid var(--border-default); box-shadow: 0 18px 48px rgb(0 0 0 / 18%); }
	header { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
	.eyebrow { margin: 0 0 4px; color: var(--text-tertiary); font-size: 11px; text-transform: uppercase; }
	h2 { margin: 0; font-size: 20px; }
	.hint { max-width: 620px; margin: 6px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.45; }
	.icon-button { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--border-default); background: transparent; color: var(--text-secondary); cursor: pointer; }
	.run-section { display: flex; align-items: end; gap: 12px; padding: 14px 0; border-top: 1px solid var(--border-default); }
	.run-section label { display: grid; gap: 6px; min-width: 0; flex: 1; }
	.run-section label span { color: var(--text-secondary); font-size: 12px; font-weight: 600; }
	select { width: 100%; min-height: 36px; padding: 6px 8px; border: 1px solid var(--border-default); background: var(--surface-page); color: var(--text-primary); }
	.primary, .select-button { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 11px; border: 1px solid var(--brand-primary); background: var(--brand-primary); color: white; cursor: pointer; white-space: nowrap; }
	.primary:disabled, .select-button:disabled { cursor: wait; opacity: .55; }
	.candidate-list { display: grid; gap: 9px; padding-top: 14px; border-top: 1px solid var(--border-default); }
	.candidate { padding: 11px 12px; border: 1px solid var(--border-default); }
	.candidate[data-status='needs_review'] { border-color: color-mix(in srgb, var(--status-success, #18794e) 45%, var(--border-default)); }
	.candidate-heading, .candidate-meta, .candidate-actions { display: flex; align-items: center; gap: 9px; min-width: 0; }
	.candidate-heading { justify-content: space-between; }
	.status-label { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 650; }
	.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-tertiary); }
	.candidate[data-status='needs_review'] .status-dot { background: var(--status-success, #18794e); }
	.candidate[data-status='provider_failed'] .status-dot, .candidate[data-status='invalid_proposal'] .status-dot { background: var(--status-error, #b42318); }
	code { color: var(--text-tertiary); font-size: 10px; }
	.candidate-meta { margin-top: 7px; color: var(--text-tertiary); font-size: 11px; flex-wrap: wrap; }
	.candidate p { margin: 8px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.45; }
	.error-detail { display: flex; align-items: center; gap: 5px; color: var(--status-error, #b42318) !important; }
	.candidate-actions { margin-top: 10px; flex-wrap: wrap; }
	.select-button { min-height: 30px; padding: 0 8px; font-size: 11px; }
	.selected { display: inline-flex; align-items: center; gap: 5px; color: var(--status-success, #18794e); font-size: 11px; }
	details { margin-left: auto; min-width: 180px; color: var(--text-tertiary); font-size: 11px; }
	summary { cursor: pointer; text-align: right; }
	dl { display: grid; gap: 5px; margin: 8px 0 0; padding: 8px; border: 1px solid var(--border-default); background: var(--surface-page); }
	dl div { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; }
	dt { color: var(--text-tertiary); }
	dd { margin: 0; overflow-wrap: anywhere; color: var(--text-secondary); }
	.state { display: flex; align-items: center; gap: 8px; padding: 11px 12px; border: 1px solid var(--border-default); font-size: 13px; }
	.state.error { color: var(--status-error, #b42318); }
	.state.muted { color: var(--text-tertiary); }
	:global(.spin) { animation: spin 1s linear infinite; }
	@keyframes spin { to { transform: rotate(360deg); } }
	@media (max-width: 640px) { .backdrop { padding: 0; place-items: end center; } .panel { max-height: 94vh; } .run-section { align-items: stretch; flex-direction: column; } .primary { justify-content: center; } details { width: 100%; margin-left: 0; } summary { text-align: left; } }
</style>
