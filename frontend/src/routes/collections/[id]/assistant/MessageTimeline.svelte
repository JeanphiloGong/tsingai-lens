<script lang="ts">
	import { onMount, tick } from 'svelte';
	import IconButton from '../../../_shared/IconButton.svelte';
	import { t } from '../../../_shared/i18n';
	import {
		buildChatPresentation,
		getRecoveredChatProgress,
		getCurrentReadings
	} from './conversationPresentation';
	import { RotateCw } from '@lucide/svelte';
	import type {
		ChatMessage,
		ChatToolCall,
		ChatProgress,
		ChatResponseSnapshot
	} from '../../../_shared/chatSessions';
	import type {
		ChatFeedbackInput,
		ChatFeedbackState,
		ChatBranchOptions
	} from '../../../_shared/chatSessions';
	import UserMessage from './UserMessage.svelte';
	import AssistantMessage from './AssistantMessage.svelte';
	import ResearchActivity from './ResearchActivity.svelte';
	import ResearchArtifact from './ResearchArtifact.svelte';
	import ApprovalPanel from './ApprovalPanel.svelte';
	export let messages: ChatMessage[] = [];
	$: readings = getCurrentReadings(messages);
	export let branches: ChatBranchOptions[] = [];
	export let revisionDisabled = false;
	export let onRevise: (message: ChatMessage, content?: string) => Promise<boolean> = async () =>
		false;
	export let onSwitchVersion: (sessionId: string) => void = () => {};
	export let running = false;
	$: actionsDisabled =
		revisionDisabled ||
		loading ||
		sending ||
		deciding ||
		running ||
		Boolean(pendingApproval) ||
		Boolean(recoveringCallId);
	$: questionsByAnswer = (() => {
		let question: ChatMessage | undefined;
		const questions = new Map<string, ChatMessage>();
		for (const message of messages) {
			if (message.role === 'user') question = message;
			else if (message.role === 'assistant' && question)
				questions.set(message.message_id, question);
		}
		return questions;
	})();
	$: unansweredQuestions = (() => {
		const ids = new Set<string>();
		let questionId = '';
		for (const message of messages) {
			if (message.role === 'user') {
				questionId = message.message_id;
				ids.add(questionId);
			} else if (
				message.role === 'assistant' &&
				message.content.trim() &&
				!message.tool_calls.length
			) {
				ids.delete(questionId);
			}
		}
		return ids;
	})();
	export let feedbackByMessage: Record<string, ChatFeedbackState> = {};
	export let onFeedback: (messageId: string, input: ChatFeedbackInput) => Promise<boolean>;
	export let sessionId = '';
	export let streamingText = '';
	export let responseSnapshot: ChatResponseSnapshot | null = null;
	export let pendingApproval: ChatToolCall | null = null;
	export let progress: ChatProgress | null = null;
	export let progressHistory: ChatProgress[] = [];
	export let loading = false;
	export let sending = false;
	export let deciding = false;
	export let recoveringCallId: string | null = null;
	export let recoveryLoading = false;
	export let recoveryError = '';
	export let onRefreshRecovery: () => void = () => {};
	let now = Date.now();
	$: recovering =
		!loading && !sending && !pendingApproval && (running || Boolean(recoveringCallId));
	$: recoveredProgress = {
		...getRecoveredChatProgress(messages, now),
		...(responseSnapshot?.status === 'running'
			? {
					...responseSnapshot.progress,
					elapsed_ms: Math.max(
						responseSnapshot.progress.elapsed_ms ?? 0,
						now - Date.parse(responseSnapshot.started_at)
					)
				}
			: {}),
		...(recoveryError ? { phase: 'reconnecting' } : {})
	};
	$: responseMessage =
		responseSnapshot?.message_id &&
		!messages.some((message) => message.message_id === responseSnapshot?.message_id)
			? {
					message_id: responseSnapshot.message_id,
					session_id: sessionId,
					role: 'assistant' as const,
					content: responseSnapshot.content,
					created_at: responseSnapshot.message_created_at ?? responseSnapshot.started_at,
					tool_call_id: null,
					tool_calls: [],
					tool_result: null,
					source_contexts: []
				}
			: null;
	$: showRecoveryRow =
		recovering && !responseMessage && (!responseSnapshot || responseSnapshot.status === 'running');
	$: showReadingRow =
		sending &&
		!responseMessage &&
		!messages.some((message) => message.message_id.startsWith('local-stream-'));
	$: recoveryMessage = {
		message_id: `local-recovery-${sessionId}`,
		session_id: sessionId,
		role: 'assistant' as const,
		content: '',
		created_at: '',
		tool_call_id: null,
		tool_calls: [],
		tool_result: null,
		source_contexts: []
	};
	export let ready = false;
	export let onSend: (text: string) => void;
	export let decide: (decision: 'approved' | 'rejected') => void;
	const suggestionKeys = [
		'researchAgent.suggestions.greeting',
		'researchAgent.suggestions.overview',
		'researchAgent.suggestions.findings',
		'researchAgent.suggestions.objectives'
	];
	$: conversationItems = buildChatPresentation(
		responseMessage ? [...messages, responseMessage] : messages,
		pendingApproval?.tool_call_id ?? null
	);
	let scrollElement: HTMLDivElement;
	let contentElement: HTMLDivElement;
	let following = true;
	let visibleCount = 20;
	let loadingEarlier = false;
	let scrollFrame = 0;
	let observedSessionId = '';
	let wasSending = false;
	let previousItemCount = 0;
	let mounted = false;
	let visibleItems: ReturnType<typeof buildChatPresentation> = [];
	$: followNewTurn(sending);
	$: {
		resetSession(sessionId);
		preserveReadingWindow(conversationItems.length);
		visibleItems = conversationItems.slice(-visibleCount);
	}

	function preserveReadingWindow(count: number) {
		if (!following) visibleCount = Math.max(20, visibleCount + count - previousItemCount);
		previousItemCount = count;
	}

	function resetSession(id: string) {
		if (id === observedSessionId) return;
		observedSessionId = id;
		previousItemCount = 0;
		visibleCount = 20;
		following = true;
		scheduleScroll();
	}

	function followNewTurn(active: boolean) {
		if (active && !wasSending) {
			following = true;
			scheduleScroll();
		}
		wasSending = active;
	}

	function scheduleScroll() {
		if (!mounted || scrollFrame) return;
		scrollFrame = requestAnimationFrame(() => {
			scrollFrame = 0;
			if (following && scrollElement) scrollElement.scrollTop = scrollElement.scrollHeight;
		});
	}

	async function loadEarlier() {
		if (loadingEarlier) return;
		const owner = sessionId;
		const previousHeight = scrollElement.scrollHeight;
		const previousTop = scrollElement.scrollTop;
		following = false;
		loadingEarlier = true;
		visibleCount += 20;
		await tick();
		if (owner === sessionId)
			scrollElement.scrollTop = previousTop + scrollElement.scrollHeight - previousHeight;
		loadingEarlier = false;
	}

	function scrollToLatest() {
		following = true;
		scheduleScroll();
	}

	onMount(() => {
		mounted = true;
		const clock = setInterval(() => {
			if (recovering) now = Date.now();
		}, 1000);
		const observer = new ResizeObserver(scheduleScroll);
		observer.observe(contentElement);
		observer.observe(scrollElement);
		return () => {
			clearInterval(clock);
			mounted = false;
			observer.disconnect();
			cancelAnimationFrame(scrollFrame);
		};
	});
	function askSuggestion(key: string) {
		onSend($t(key));
	}
</script>

<div class="timeline">
	<div
		class="message-scroll"
		bind:this={scrollElement}
		role="log"
		aria-label={$t('researchAgent.chatLabel')}
		aria-live="polite"
		aria-busy={loading || sending || deciding || recovering}
		on:scroll={(event) => {
			const node = event.currentTarget;
			following = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
		}}
	>
		<div class="message-list" bind:this={contentElement}>
			{#if loading}
				<div class="empty-state" role="status">
					<h3>{$t('researchAgent.loading')}</h3>
				</div>
			{:else if messages.length === 0 && !recovering && !responseMessage}
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
				{#if conversationItems.length > visibleCount}
					<button
						class="earlier-messages"
						type="button"
						disabled={loadingEarlier}
						on:click={loadEarlier}>{$t('researchAgent.earlierMessages')}</button
					>
				{/if}
				{#each visibleItems as item (item.id)}
					{#if item.kind === 'message'}
						{#if item.message.role === 'user'}<UserMessage
								message={item.message}
								disabled={actionsDisabled}
								versions={branches.find((branch) => branch.message_id === item.message.message_id)}
								retryAvailable={unansweredQuestions.has(item.message.message_id)}
								{onRevise}
								{onSwitchVersion}
							/>{:else if item.message.role === 'assistant'}<AssistantMessage
								message={item.message}
								disabled={actionsDisabled}
								onRegenerate={questionsByAnswer.has(item.message.message_id)
									? () => void onRevise(questionsByAnswer.get(item.message.message_id)!)
									: undefined}
								streaming={(item.message.message_id.startsWith('local-stream-') && sending) ||
									(item.message.message_id === responseMessage?.message_id &&
										responseSnapshot?.status === 'running')}
								incomplete={item.message.message_id === responseMessage?.message_id}
								feedbackState={feedbackByMessage[item.message.message_id]}
								{onFeedback}
								streamingText={sending ? streamingText : (responseSnapshot?.content ?? '')}
								progress={sending
									? progress
									: responseMessage && responseSnapshot?.status === 'running'
										? recoveredProgress
										: null}
								{progressHistory}
								{readings}
							>
								{#if item.message.message_id === responseMessage?.message_id && recovering}
									<div class="recovery-controls" data-testid="research-recovery">
										{#if recoveryError}<p class="recovery-error" role="alert">
												{recoveryError}
											</p>{/if}
										<IconButton
											label={$t('researchAgent.checkResult')}
											disabled={recoveryLoading}
											onClick={onRefreshRecovery}><RotateCw size={14} /></IconButton
										>
									</div>
								{/if}
							</AssistantMessage>{/if}
					{:else}<ResearchActivity
							{item}
						/>{#each item.artifacts as artifact (artifact.toolCallId)}<ResearchArtifact
								{artifact}
							/>{/each}
					{/if}{/each}
			{/if}

			{#if pendingApproval}
				<ApprovalPanel call={pendingApproval} {deciding} onDecide={decide} />
			{/if}
			{#if showRecoveryRow || showReadingRow}
				<AssistantMessage
					message={recoveryMessage}
					recovering={showRecoveryRow}
					streaming={showReadingRow}
					progress={showReadingRow ? progress : recoveredProgress}
					{readings}
					{onFeedback}
				>
					{#if showRecoveryRow}<div class="recovery-controls" data-testid="research-recovery">
							{#if recoveryError}<p class="recovery-error" role="alert">{recoveryError}</p>{/if}
							<IconButton
								label={$t('researchAgent.checkResult')}
								disabled={recoveryLoading}
								onClick={onRefreshRecovery}><RotateCw size={14} /></IconButton
							>
						</div>{/if}
				</AssistantMessage>
			{/if}
		</div>
	</div>
	{#if !following && messages.length}
		<div class="jump-to-latest">
			<IconButton label={$t('researchAgent.latestMessage')} onClick={scrollToLatest}
				>&darr;</IconButton
			>
		</div>
	{/if}
</div>

<style>
	.recovery-controls {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 12px;
		color: var(--text-secondary);
		font-size: 13px;
		overflow-wrap: anywhere;
	}
	.recovery-error {
		margin: 4px 0 0;
		flex: 1;
		color: var(--danger-text);
	}
	.timeline {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
		min-width: 0;
	}
	.jump-to-latest {
		position: absolute;
		bottom: 12px;
		left: 50%;
		transform: translateX(-50%);
		border: 1px solid var(--border-default);
		border-radius: 50%;
		background: var(--surface-card);
		box-shadow: var(--shadow-sm);
	}
	.earlier-messages {
		display: block;
		margin: 0 auto 24px;
		padding: 8px 12px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-secondary);
		font-size: 12px;
		cursor: pointer;
	}
	.earlier-messages:hover:not(:disabled) {
		color: var(--brand-primary);
		border-color: var(--brand-border);
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.message-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 0 32px;
		scroll-behavior: auto;
		overflow-anchor: none;
	}

	.message-list {
		width: min(100%, 900px);
		margin: 0 auto;
		padding: 36px 0 52px;
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
