<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import { buildChatPresentation } from './conversationPresentation';
	import type { ChatMessage, ChatToolCall, ChatProgress } from '../../../_shared/chatSessions';
	import UserMessage from './UserMessage.svelte';
	import AssistantMessage from './AssistantMessage.svelte';
	import ResearchActivity from './ResearchActivity.svelte';
	import ResearchArtifact from './ResearchArtifact.svelte';
	import ApprovalPanel from './ApprovalPanel.svelte';
	export let messages: ChatMessage[] = [];
	export let streamingText = '';
	export let pendingApproval: ChatToolCall | null = null;
	export let progress: ChatProgress | null = null;
	export let progressHistory: ChatProgress[] = [];
	export let loading = false;
	export let sending = false;
	export let deciding = false;
	export let ready = false;
	export let onSend: (text: string) => void;
	export let decide: (decision: 'approved' | 'rejected') => void;
	const suggestionKeys = [
		'researchAgent.suggestions.greeting',
		'researchAgent.suggestions.overview',
		'researchAgent.suggestions.findings',
		'researchAgent.suggestions.objectives'
	];
	$: conversationItems = buildChatPresentation(messages, pendingApproval?.tool_call_id ?? null);
	function askSuggestion(key: string) {
		onSend($t(key));
	}
</script>

<div class="timeline">
	<div
		class="message-scroll"
		role="log"
		aria-label={$t('researchAgent.chatLabel')}
		aria-live="polite"
		aria-busy={loading || sending || deciding}
	>
		<div class="message-list">
			{#if loading}
				<div class="empty-state" role="status">
					<h3>{$t('researchAgent.loading')}</h3>
				</div>
			{:else if messages.length === 0}
				<div class="empty-state welcome-state">
					<div class="welcome-avatar" aria-hidden="true">AI</div>
					<p class="welcome-eyebrow">{$t('researchAgent.welcomeEyebrow')}</p>
					<h3>{$t('researchAgent.emptyTitle')}</h3>
					<p>{$t('researchAgent.emptyBody')}</p>
					<div class="suggestions">
						{#each suggestionKeys as key (key)}
							<button
								type="button"
								disabled={!ready || sending}
								on:click={() => askSuggestion(key)}
							>
								{$t(key)}
							</button>
						{/each}
					</div>
				</div>
			{:else}
				{#each conversationItems as item (item.id)}
					{#if item.kind === 'message'}
						{#if item.message.role === 'user'}<UserMessage
								message={item.message}
							/>{:else if item.message.role === 'assistant'}<AssistantMessage
								message={item.message}
								streaming={item.message.message_id.startsWith('local-stream-') && sending}
								{streamingText}
								{progress}
								{progressHistory}
							/>{/if}
					{:else}<ResearchActivity
							{item}
						/>{#each item.artifacts as artifact (artifact.toolCallId)}<ResearchArtifact
								{artifact}
							/>{/each}{/if}{/each}
			{/if}

			{#if pendingApproval}
				<ApprovalPanel call={pendingApproval} {deciding} onDecide={decide} />
			{/if}
		</div>
	</div>
</div>

<style>
	.timeline {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
		min-width: 0;
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.message-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 36px 32px 44px;
		scroll-behavior: auto;
	}

	.message-list {
		width: min(100%, 900px);
		margin: 0 auto;
		padding-bottom: 8px;
	}

	.empty-state {
		max-width: 620px;
		margin: 88px auto 0;
		text-align: center;
	}

	.welcome-state {
		display: flex;
		align-items: center;
		flex-direction: column;
	}

	.welcome-avatar {
		display: grid;
		place-items: center;
		width: 48px;
		height: 48px;
		border: 1px solid var(--brand-border);
		border-radius: 50%;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 12px;
		font-weight: 800;
		letter-spacing: 0;
	}

	.welcome-eyebrow {
		margin: 16px 0 0;
		color: var(--brand-primary);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0;
		text-transform: uppercase;
	}

	.empty-state h3 {
		margin: 0;
		font-size: 20px;
	}

	.empty-state > p {
		margin: 8px 0 0;
		color: var(--text-secondary);
		font-size: 14px;
	}

	.suggestions {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
		margin-top: 22px;
	}

	.suggestions button {
		min-height: 46px;
		padding: 10px 12px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
	}

	.suggestions button:hover:not(:disabled) {
		border-color: var(--brand-border);
		background: var(--brand-soft);
	}

	@media (max-width: 820px) {
		.message-scroll {
			padding-left: 18px;
			padding-right: 18px;
		}
	}

	@media (max-width: 560px) {
		.suggestions {
			grid-template-columns: 1fr;
		}
	}
</style>
