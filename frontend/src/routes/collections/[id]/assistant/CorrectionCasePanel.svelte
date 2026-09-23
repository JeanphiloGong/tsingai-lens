<script lang="ts">
	import { Link2, Save, X } from '@lucide/svelte';
	import type { ChatCorrectionCase, ChatMessage } from '../../../_shared/chatSessions';
import { t } from '../../../_shared/i18n';

	export let messages: ChatMessage[] = [];
	export let cases: ChatCorrectionCase[] = [];
	export let saving = false;
	export let error = '';
	export let onSave: (input: {
		original_message_id: string;
		feedback_message_id: string;
		corrected_message_id?: string | null;
	}) => Promise<boolean> = async () => false;
	export let onClose: () => void = () => {};

	$: answers = messages.filter(
		(message) => message.role === 'assistant' && message.content.trim() && !message.tool_calls.length
	);
	$: questions = messages.filter((message) => message.role === 'user' && message.content.trim());
	let originalMessageId = '';
	let feedbackMessageId = '';
	let correctedMessageId = '';

	function label(message: ChatMessage) {
		const text = message.content.replace(/\s+/g, ' ').trim();
		return `${message.role === 'assistant' ? 'AI' : 'You'} · ${text.slice(0, 96)}${text.length > 96 ? '...' : ''}`;
	}

	async function save() {
		if (!originalMessageId || !feedbackMessageId || saving) return;
		await onSave({
			original_message_id: originalMessageId,
			feedback_message_id: feedbackMessageId,
			corrected_message_id: correctedMessageId || null
		});
	}
</script>

<div class="case-backdrop" role="presentation" on:click={(event) => event.target === event.currentTarget && onClose()}>
	<div class="case-panel" role="dialog" aria-modal="true" aria-labelledby="correction-case-title" tabindex="-1">
		<header>
			<div>
				<p class="eyebrow">{$t('researchAgent.correctionCase.title')}</p>
				<h2 id="correction-case-title">{$t('researchAgent.correctionCase.open')}</h2>
			</div>
			<button class="icon-button" type="button" aria-label={$t('researchAgent.correctionCase.close')} on:click={onClose}>
				<X size={18} />
			</button>
		</header>

		<div class="fields">
			<label>
				<span>{$t('researchAgent.correctionCase.original')}</span>
				<select bind:value={originalMessageId} disabled={saving}>
					<option value="">{$t('researchAgent.correctionCase.selectOriginal')}</option>
					{#each answers as message (message.message_id)}
						<option value={message.message_id}>{label(message)}</option>
					{/each}
				</select>
			</label>
			<label>
				<span>{$t('researchAgent.correctionCase.feedback')}</span>
				<select bind:value={feedbackMessageId} disabled={saving}>
					<option value="">{$t('researchAgent.correctionCase.selectFeedback')}</option>
					{#each questions as message (message.message_id)}
						<option value={message.message_id}>{label(message)}</option>
					{/each}
				</select>
			</label>
			<label>
				<span>{$t('researchAgent.correctionCase.corrected')}</span>
				<select bind:value={correctedMessageId} disabled={saving}>
					<option value="">{$t('researchAgent.correctionCase.unresolved')}</option>
					{#each answers as message (message.message_id)}
						<option value={message.message_id}>{label(message)}</option>
					{/each}
				</select>
			</label>
		</div>

		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="save-button" type="button" disabled={saving || !originalMessageId || !feedbackMessageId} on:click={save}>
			<Save size={16} />
			<span>{saving ? $t('researchAgent.correctionCase.saving') : $t('researchAgent.correctionCase.save')}</span>
		</button>

		<section class="saved-cases" aria-label={$t('researchAgent.correctionCase.title')}>
			{#if cases.length === 0}
				<p class="muted">{$t('researchAgent.correctionCase.none')}</p>
			{:else}
				{#each cases as item (item.case_id)}
					<div class="saved-case" data-status={item.status}>
						<Link2 size={14} />
						<span>{item.status === 'linked' ? $t('researchAgent.correctionCase.statusLinked') : $t('researchAgent.correctionCase.statusUnresolved')}</span>
						<code>{item.case_id.slice(-8)}</code>
					</div>
				{/each}
			{/if}
		</section>
	</div>
</div>

<style>
	.case-backdrop {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: grid;
		place-items: center;
		padding: 20px;
		background: color-mix(in srgb, var(--surface-page) 72%, transparent);
	}
	.case-panel {
		width: min(620px, 100%);
		max-height: min(720px, 90vh);
		overflow: auto;
		padding: 20px;
		background: var(--surface-card);
		border: 1px solid var(--border-default);
		box-shadow: 0 18px 48px rgb(0 0 0 / 18%);
	}
	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		margin-bottom: 18px;
	}
	.eyebrow {
		margin: 0 0 4px;
		color: var(--text-tertiary);
		font-size: 11px;
		text-transform: uppercase;
	}
	h2 {
		margin: 0;
		font-size: 20px;
	}
	.icon-button {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border: 1px solid var(--border-default);
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
	}
	.fields {
		display: grid;
		gap: 14px;
	}
	label {
		display: grid;
		gap: 6px;
		min-width: 0;
	}
	label span {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-secondary);
	}
	select {
		width: 100%;
		min-height: 38px;
		padding: 7px 9px;
		border: 1px solid var(--border-default);
		background: var(--surface-page);
		color: var(--text-primary);
	}
	.save-button {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		margin-top: 18px;
		min-height: 38px;
		padding: 0 13px;
		border: 1px solid var(--brand-primary);
		background: var(--brand-primary);
		color: white;
		cursor: pointer;
	}
	.save-button:disabled {
		cursor: wait;
		opacity: 0.55;
	}
	.error {
		margin: 14px 0 0;
		color: var(--status-error, #b42318);
		font-size: 13px;
	}
	.saved-cases {
		margin-top: 22px;
		padding-top: 14px;
		border-top: 1px solid var(--border-default);
	}
	.saved-case {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 0;
		font-size: 13px;
	}
	.saved-case[data-status='linked'] {
		color: var(--status-success, #18794e);
	}
	.saved-case code {
		margin-left: auto;
		color: var(--text-tertiary);
		font-size: 11px;
	}
	.muted {
		margin: 0;
		color: var(--text-tertiary);
		font-size: 13px;
	}
	@media (max-width: 640px) {
		.case-backdrop {
			padding: 0;
			place-items: end center;
		}
		.case-panel {
			max-height: 92vh;
		}
	}
</style>
