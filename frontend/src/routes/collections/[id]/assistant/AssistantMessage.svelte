<script lang="ts">
	import { RotateCcw } from '@lucide/svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import type { ChatMessage, ChatProgress } from '../../../_shared/chatSessions';
	import type { ChatFeedbackInput, ChatFeedbackState } from '../../../_shared/chatSessions';
	import MessageFeedback from './MessageFeedback.svelte';
	import ResearchProgress from './ResearchProgress.svelte';
	import MessageContent from './MessageContent.svelte';
	import { formatTime } from './conversationPresentation';
	export let message: ChatMessage;
	export let disabled = false;
	export let onRegenerate: (() => void) | undefined = undefined;
	export let feedbackState: ChatFeedbackState | undefined = undefined;
	export let onFeedback: (messageId: string, input: ChatFeedbackInput) => Promise<boolean>;
	export let streaming = false;
	export let recovering = false;
	export let streamingText = '';
	export let progress: ChatProgress | null = null;
	export let progressHistory: ChatProgress[] = [];
</script>

<article
	class="assistant-message"
	class:streaming={streaming || recovering}
	data-testid="assistant-message"
>
	<div class="assistant-mark" aria-hidden="true">AI</div>
	<div class="assistant-content">
		{#if (streaming || recovering) && progress}
			<ResearchProgress {progress} {progressHistory} />
		{/if}
		{#if !recovering}
			<time>{formatTime(message.created_at)}</time>
			<MessageContent content={streaming ? streamingText : message.content} {streaming} />
		{/if}
		<slot />
		{#if !streaming && !message.message_id.startsWith('local-') && message.content.trim() && !message.tool_calls.length}
			<div class="answer-actions">
				{#if onRegenerate}
					<IconButton
						label={$t('researchAgent.revision.regenerate')}
						{disabled}
						onClick={onRegenerate}><RotateCcw size={16} /></IconButton
					>
				{/if}
				<MessageFeedback
					messageId={message.message_id}
					state={feedbackState}
					onSave={(input) => onFeedback(message.message_id, input)}
				/>
			</div>
		{/if}
	</div>
</article>

<style>
	.answer-actions {
		display: flex;
		align-items: flex-start;
		gap: 4px;
		margin-top: 6px;
	}
	.answer-actions :global(.message-feedback) {
		margin-top: 0;
		min-width: 0;
	}
	.assistant-mark {
		display: grid;
		place-items: center;
		background: var(--surface-card);
		border: 1px solid var(--brand-border);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.assistant-content > time {
		display: block;
		margin-bottom: 5px;
		color: var(--text-tertiary);
		font-size: 11px;
	}

	.assistant-message {
		display: grid;
		grid-template-columns: 36px minmax(0, 1fr);
		gap: 12px;
		margin-bottom: 18px;
		animation: message-enter 180ms ease both;
	}

	.assistant-message.streaming .assistant-mark {
		border-color: var(--brand-primary);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand-primary) 12%, transparent);
		transition: box-shadow 180ms ease;
	}

	.assistant-mark {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		font-size: 10px;
	}

	.assistant-content {
		max-width: 760px;
		min-width: 0;
	}

	@keyframes message-enter {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
