<script lang="ts">
	import type { ChatMessage, ChatProgress } from '../../../_shared/chatSessions';
	import ResearchProgress from './ResearchProgress.svelte';
	import MessageContent from './MessageContent.svelte';
	import { formatTime } from './conversationPresentation';
	export let message: ChatMessage;
	export let streaming = false;
	export let streamingText = '';
	export let progress: ChatProgress | null = null;
	export let progressHistory: ChatProgress[] = [];
</script>

<article class="assistant-message" class:streaming data-testid="assistant-message">
	<div class="assistant-mark" aria-hidden="true">AI</div>
	<div class="assistant-content">
		{#if streaming && progress}
			<ResearchProgress {progress} {progressHistory} />
		{/if}
		<time>{formatTime(message.created_at)}</time>
		<MessageContent content={streaming ? streamingText : message.content} {streaming} />
	</div>
</article>

<style>
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
