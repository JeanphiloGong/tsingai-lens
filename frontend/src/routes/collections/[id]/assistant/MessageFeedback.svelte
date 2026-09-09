<script lang="ts">
	import { tick } from 'svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import type {
		ChatFeedbackInput,
		ChatFeedbackReason,
		ChatFeedbackState
	} from '../../../_shared/chatSessions';

	export let messageId: string;
	export let state: ChatFeedbackState | undefined = undefined;
	export let onSave: (input: ChatFeedbackInput) => Promise<boolean>;
	let editing = false;
	let reason: ChatFeedbackReason | '' = '';
	let comment = '';
	let announced = '';
	let toolbar: HTMLDivElement;
	let commentInput: HTMLTextAreaElement;
	const reasons: ChatFeedbackReason[] = ['incorrect', 'incomplete', 'unclear', 'other'];
	$: feedback = state?.feedback ?? null;
	$: saving = state?.saving ?? false;

	async function openEditor() {
		reason = feedback?.reason ?? '';
		comment = feedback?.comment ?? '';
		editing = true;
		await tick();
		commentInput?.focus();
	}

	async function closeEditor() {
		editing = false;
		await tick();
		Array.from(toolbar?.querySelectorAll<HTMLButtonElement>('button') ?? [])
			.at(-1)
			?.focus();
	}

	async function rate(rating: 'helpful' | 'not_helpful') {
		const next = feedback?.rating === rating ? null : rating;
		announced = '';
		if (await onSave({ rating: next })) {
			announced = $t(next ? 'researchAgent.feedback.saved' : 'researchAgent.feedback.removed');
			if (next === 'not_helpful') await openEditor();
			else editing = false;
		}
	}

	async function saveDetails() {
		if (!feedback || saving) return;
		announced = '';
		if (
			await onSave({
				rating: feedback.rating,
				reason: feedback.rating === 'not_helpful' ? reason || null : null,
				comment: comment.trim() || null
			})
		) {
			announced = $t('researchAgent.feedback.saved');
			await closeEditor();
		}
	}
</script>

<div class="message-feedback" data-testid="message-feedback">
	<div class="feedback-actions" bind:this={toolbar}>
		<IconButton
			label={$t('researchAgent.feedback.helpful')}
			pressed={feedback?.rating === 'helpful'}
			disabled={saving}
			tooltipAlign="start"
			onClick={() => rate('helpful')}
		>
			<svg
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill={feedback?.rating === 'helpful' ? 'currentColor' : 'none'}
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path
					d="M7 10v11M15 5.9 14 10h5.8a2 2 0 0 1 1.9 2.6l-2.3 7a2 2 0 0 1-1.9 1.4H3a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h4l5.1-8a3 3 0 0 1 2.9 3.9Z"
				/>
			</svg>
		</IconButton>
		<IconButton
			label={$t('researchAgent.feedback.notHelpful')}
			pressed={feedback?.rating === 'not_helpful'}
			disabled={saving}
			onClick={() => rate('not_helpful')}
		>
			<svg
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill={feedback?.rating === 'not_helpful' ? 'currentColor' : 'none'}
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path
					d="M17 14V3M9 18.1 10 14H4.2a2 2 0 0 1-1.9-2.6l2.3-7A2 2 0 0 1 6.5 3H21a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-4l-5.1 8A3 3 0 0 1 9 18.1Z"
				/>
			</svg>
		</IconButton>
		{#if feedback}
			<IconButton label={$t('researchAgent.feedback.edit')} disabled={saving} onClick={openEditor}>
				<svg
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path
						d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"
					/>
				</svg>
			</IconButton>
		{/if}
		<span class="feedback-status" role="status"
			>{saving ? $t('researchAgent.feedback.saving') : announced}</span
		>
	</div>
	{#if state?.error}<p class="feedback-error" role="alert">{state.error}</p>{/if}
	{#if editing && feedback}
		<form
			class="feedback-editor"
			aria-label={$t('researchAgent.feedback.edit')}
			on:submit|preventDefault={saveDetails}
		>
			{#if feedback.rating === 'not_helpful'}
				<label for="feedback-reason-{messageId}">{$t('researchAgent.feedback.reason')}</label>
				<select id="feedback-reason-{messageId}" bind:value={reason} disabled={saving}>
					<option value="">{$t('researchAgent.feedback.optional')}</option>
					{#each reasons as value}<option {value}
							>{$t(`researchAgent.feedback.reasons.${value}`)}</option
						>{/each}
				</select>
			{/if}
			<label for="feedback-comment-{messageId}">{$t('researchAgent.feedback.comment')}</label>
			<textarea
				id="feedback-comment-{messageId}"
				bind:this={commentInput}
				bind:value={comment}
				maxlength="2000"
				rows="3"
				disabled={saving}
				on:keydown={(event) => {
					if (event.key === 'Escape' && !saving) {
						event.stopPropagation();
						void closeEditor();
					}
				}}
			></textarea>
			<div class="editor-actions">
				<span class="character-count">{comment.length}/2000</span>
				<button type="button" disabled={saving} on:click={closeEditor}
					>{$t('researchAgent.feedback.cancel')}</button
				>
				<button class="save-feedback" type="submit" disabled={saving}
					>{$t('researchAgent.feedback.save')}</button
				>
			</div>
		</form>
	{/if}
</div>

<style>
	.message-feedback {
		margin-top: 8px;
	}
	.feedback-actions {
		display: flex;
		align-items: center;
		gap: 2px;
		min-height: 36px;
	}
	.feedback-status {
		color: var(--text-secondary);
		font-size: 12px;
		margin-left: 8px;
	}
	.feedback-error {
		color: var(--danger-text);
		font-size: 13px;
		margin: 4px 0;
	}
	.feedback-editor {
		display: grid;
		gap: 8px;
		width: min(100%, 440px);
		margin-top: 8px;
		padding-top: 12px;
		border-top: 1px solid var(--border-default);
		animation: reveal 140ms ease;
	}
	label {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-secondary);
	}
	select,
	textarea {
		width: 100%;
		min-width: 0;
		padding: 8px 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		font-size: 13px;
	}
	textarea {
		resize: vertical;
		min-height: 80px;
		max-height: 240px;
	}
	.editor-actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: 8px;
	}
	.character-count {
		margin-right: auto;
		color: var(--text-secondary);
		font-size: 11px;
	}
	button {
		border: 1px solid var(--border-default);
		border-radius: 6px;
		padding: 6px 12px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		cursor: pointer;
	}
	button.save-feedback {
		color: var(--surface-card);
		background: var(--text-primary);
		border-color: var(--text-primary);
	}
	button:disabled {
		opacity: 0.55;
		cursor: wait;
	}
	button:focus-visible,
	select:focus-visible,
	textarea:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	@keyframes reveal {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.feedback-editor {
			animation: none;
		}
	}
</style>
