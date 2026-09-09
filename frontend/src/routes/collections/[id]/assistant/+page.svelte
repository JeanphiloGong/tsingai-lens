<script lang="ts">
	import { onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import { authState } from '../../../_shared/auth';
	import { collections } from '../../../_shared/collections';
	import {
		createChatSession,
		clearPendingChatSourceContext,
		decideChatToolCall,
		fetchChatSession,
		fetchChatTrajectory,
		appendChatProgress,
		readPendingChatSourceContext,
		storePendingChatSourceContext,
		streamChatMessage,
		setChatMessageFeedback,
		type ChatFeedbackInput,
		type ChatFeedbackState,
		type ChatMessageFeedback,
		type ChatMessage,
		type ChatProgress,
		type ChatSession,
		type ChatSourceContext,
		type ChatToolCall,
		type ChatTurn
	} from '../../../_shared/chatSessions';
	import { t } from '../../../_shared/i18n';
	import MessageTimeline from './MessageTimeline.svelte';
	import ConversationHeader from './ConversationHeader.svelte';
	import MessageComposer from './MessageComposer.svelte';
	import ResearchSidebar from './ResearchSidebar.svelte';

	type StoredChatSession = {
		session_id: string;
		title: string;
		created_at: string;
		updated_at: string;
	};

	let session: ChatSession | null = null;
	let messages: ChatMessage[] = [];
	let feedbackByMessage: Record<string, ChatFeedbackState> = {};
	let pendingApproval: ChatToolCall | null = null;
	let history: StoredChatSession[] = [];
	let loading = false;
	let sending = false;
	let progress: ChatProgress | null = null;
	let progressHistory: ChatProgress[] = [];
	let streamingText = '';

	let deciding = false;
	let error = '';
	let notice = '';
	let input = '';
	let pendingSourceContext: ChatSourceContext | null = null;
	let loadedCollectionId = '';
	let loadedUserId = '';
	let failedSessionId: string | null = null;
	let recoveringCallId: string | null = null;
	let recoveryLoading = false;
	let recoveryError = '';
	let recoveryTimer: ReturnType<typeof setTimeout> | undefined;

	let sessionGeneration = 0;
	let sessionController: AbortController | null = null;

	let destroyed = false;

	onDestroy(() => {
		destroyed = true;
		clearTimeout(recoveryTimer);
		sessionController?.abort();
	});

	function isCurrentSession(generation: number, ownerCollectionId: string) {
		return (
			!destroyed &&
			generation === sessionGeneration &&
			ownerCollectionId === collectionId &&
			$authState.status === 'authenticated' &&
			$authState.user?.user_id === loadedUserId
		);
	}

	$: collectionId = $page.params.id ?? '';
	$: userId = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: collectionName = userId
		? ($collections.find((item) => item.id === collectionId)?.name?.trim() ?? '')
		: '';
	$: conversationTitle = messages.find((message) => message.role === 'user')?.content.trim() ?? '';

	$: queryObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
	$: activeSessionId = session?.session_id ?? '';
	$: if (browser && (collectionId !== loadedCollectionId || userId !== loadedUserId)) {
		loadedCollectionId = collectionId;
		loadedUserId = userId;
		void loadSession();
	}

	function sessionStorageKey() {
		return `lens.chatSession.${encodeURIComponent(userId)}:${encodeURIComponent(collectionId)}`;
	}

	function historyStorageKey() {
		return `lens.chatSessionHistory.${encodeURIComponent(userId)}:${encodeURIComponent(collectionId)}`;
	}

	function readStoredSessionId() {
		if (!browser) return '';
		return window.localStorage.getItem(sessionStorageKey()) ?? '';
	}

	function storeSessionId(sessionId: string) {
		if (!browser) return;
		window.localStorage.setItem(sessionStorageKey(), sessionId);
	}

	function clearStoredSessionId() {
		if (!browser) return;
		window.localStorage.removeItem(sessionStorageKey());
	}

	function readHistory(): StoredChatSession[] {
		if (!browser) return [];
		try {
			const raw = window.localStorage.getItem(historyStorageKey());
			const parsed = raw ? JSON.parse(raw) : [];
			if (!Array.isArray(parsed)) return [];
			return parsed
				.filter((item) => item && typeof item.session_id === 'string')
				.map((item) => ({
					session_id: item.session_id,
					title:
						typeof item.title === 'string' && item.title.trim()
							? item.title
							: $t('researchAgent.untitledSession'),
					created_at:
						typeof item.created_at === 'string' ? item.created_at : new Date().toISOString(),
					updated_at:
						typeof item.updated_at === 'string' ? item.updated_at : new Date().toISOString()
				}))
				.slice(0, 12);
		} catch {
			return [];
		}
	}

	function writeHistory(nextHistory: StoredChatSession[]) {
		history = nextHistory.slice(0, 12);
		if (!browser) return;
		window.localStorage.setItem(historyStorageKey(), JSON.stringify(history));
	}

	function titleFromMessages(nextMessages: ChatMessage[]) {
		const firstUserMessage = nextMessages.find((message) => message.role === 'user');
		const text = firstUserMessage?.content.trim() ?? '';
		if (!text) return $t('researchAgent.untitledSession');
		return text.length > 38 ? `${text.slice(0, 38)}...` : text;
	}

	function upsertHistory(nextSession: ChatSession, title = '') {
		const existing = history.filter((item) => item.session_id !== nextSession.session_id);
		writeHistory([
			{
				session_id: nextSession.session_id,
				title: title || titleFromMessages(messages),
				created_at: nextSession.created_at,
				updated_at: nextSession.updated_at
			},
			...existing
		]);
	}

	async function loadSession(requestedSessionId = '') {
		const activeCollectionId = collectionId;
		const generation = ++sessionGeneration;
		clearTimeout(recoveryTimer);
		recoveringCallId = null;
		recoveryLoading = false;
		recoveryError = '';
		sessionController?.abort();
		sessionController = null;
		session = null;
		messages = [];
		feedbackByMessage = {};
		input = '';
		sending = false;
		streamingText = '';
		deciding = false;
		progressHistory = [];
		failedSessionId = null;

		loading = false;
		error = '';
		notice = '';
		pendingApproval = null;
		progress = null;
		pendingSourceContext = null;
		history = [];
		if (!userId || !activeCollectionId) return;

		const controller = new AbortController();
		sessionController = controller;
		loading = true;
		pendingSourceContext = readPendingChatSourceContext(userId, activeCollectionId);
		history = readHistory();

		try {
			const storedSessionId = requestedSessionId || readStoredSessionId();
			let nextSession: ChatSession | null = null;
			if (storedSessionId) {
				try {
					nextSession = await fetchChatSession(storedSessionId, controller.signal);
					if (!isCurrentSession(generation, activeCollectionId)) return;
					if (nextSession.collection_id !== activeCollectionId) nextSession = null;
				} catch (err) {
					if (!isCurrentSession(generation, activeCollectionId)) return;
					if (!isHttpStatusError(err, 404)) throw err;
					nextSession = null;
					clearStoredSessionId();
					writeHistory(history.filter((item) => item.session_id !== storedSessionId));
				}
			}

			if (!isCurrentSession(generation, activeCollectionId)) return;
			if (nextSession === null) {
				nextSession = await createChatSession(activeCollectionId, controller.signal);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = [];
			} else {
				const trajectory = await fetchChatTrajectory(nextSession.session_id, controller.signal);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = trajectory.items;
				loadFeedback(trajectory.feedback);
				pendingApproval = trajectory.pending_approval;
				pendingSourceContext = readPendingChatSourceContext(userId, activeCollectionId, {
					sessionId: nextSession.session_id,
					messages
				});
			}
			session = nextSession;
			storeSessionId(nextSession.session_id);
			upsertHistory(nextSession);
			scheduleRecovery();
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			failedSessionId = requestedSessionId || readStoredSessionId();
			error = errorMessage(err);
			session = null;
			messages = [];
			pendingApproval = null;
		} finally {
			if (isCurrentSession(generation, activeCollectionId)) loading = false;
		}
	}

	function scheduleRecovery() {
		clearTimeout(recoveryTimer);
		const completed = new Set(messages.map((message) => message.tool_result?.tool_call_id));
		recoveringCallId =
			messages
				.flatMap((message) => message.tool_calls)
				.find(
					(call) =>
						call.tool_call_id !== pendingApproval?.tool_call_id && !completed.has(call.tool_call_id)
				)?.tool_call_id ?? null;
		if (recoveringCallId && !destroyed) {
			recoveryTimer = setTimeout(() => void refreshRecovery(), 3000);
		}
	}

	async function refreshRecovery() {
		if (!session || !recoveringCallId || recoveryLoading) return;
		const generation = sessionGeneration;
		const ownerCollectionId = collectionId;
		const activeSession = session;
		clearTimeout(recoveryTimer);
		recoveryLoading = true;
		try {
			const trajectory = await fetchChatTrajectory(
				activeSession.session_id,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, ownerCollectionId)) return;
			messages = trajectory.items;
			loadFeedback(trajectory.feedback);
			pendingApproval = trajectory.pending_approval;
			recoveryError = '';
			error = '';
			failedSessionId = null;
			session = {
				...activeSession,
				updated_at: messages.at(-1)?.created_at ?? activeSession.updated_at
			};
			upsertHistory(session);
		} catch (err) {
			if (!isCurrentSession(generation, ownerCollectionId)) return;
			recoveryError = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerCollectionId)) {
				recoveryLoading = false;
				scheduleRecovery();
			}
		}
	}

	function loadFeedback(feedback: ChatMessageFeedback[]) {
		// An in-session trajectory recovery may have started before a feedback save.
		feedbackByMessage = {
			...Object.fromEntries(
				feedback.map((item) => [item.message_id, { feedback: item, saving: false, error: '' }])
			),
			...feedbackByMessage
		};
	}

	async function saveFeedback(messageId: string, input: ChatFeedbackInput): Promise<boolean> {
		if (!session || feedbackByMessage[messageId]?.saving) return false;
		const generation = sessionGeneration;
		const ownerCollectionId = collectionId;
		const current = feedbackByMessage[messageId]?.feedback ?? null;
		feedbackByMessage = {
			...feedbackByMessage,
			[messageId]: { feedback: current, saving: true, error: '' }
		};
		try {
			const saved = await setChatMessageFeedback(
				session.session_id,
				messageId,
				input,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, ownerCollectionId)) return false;
			feedbackByMessage = {
				...feedbackByMessage,
				[messageId]: { feedback: saved, saving: false, error: '' }
			};
			return true;
		} catch {
			if (!isCurrentSession(generation, ownerCollectionId)) return false;
			feedbackByMessage = {
				...feedbackByMessage,
				[messageId]: {
					feedback: current,
					saving: false,
					error: $t('researchAgent.feedback.failed')
				}
			};
			return false;
		}
	}

	async function startNewSession() {
		if (loading || sending || deciding) return;
		clearStoredSessionId();
		session = null;
		messages = [];
		pendingApproval = null;
		input = '';
		await loadSession();
	}

	async function switchSession(sessionId: string) {
		if (sessionId === activeSessionId || loading || sending || deciding) return;
		session = null;
		messages = [];
		pendingApproval = null;
		await loadSession(sessionId);
	}

	async function sendMessage(nextText = input.trim()) {
		const text = nextText.trim();
		if (!session || !text || sending || deciding || pendingApproval || recoveringCallId) return;
		const activeSession = session;
		const activeCollectionId = collectionId;
		const generation = sessionGeneration;
		const signal = sessionController?.signal;
		let pendingText = '';
		let textFrame = 0;
		const cancelTextFrame = () => {
			cancelAnimationFrame(textFrame);
			textFrame = 0;
		};
		const flushText = () => {
			textFrame = 0;
			if (!isCurrentSession(generation, activeCollectionId)) return;
			streamingText += pendingText;
			pendingText = '';
		};
		signal?.addEventListener('abort', cancelTextFrame, { once: true });
		const previousMessageCount = messages.length;
		const optimisticId = `local-${Date.now()}`;
		const streamingId = `local-stream-${Date.now()}`;
		const createdAt = new Date().toISOString();
		const sourceContexts = pendingSourceContext ? [pendingSourceContext] : [];
		if (pendingSourceContext) {
			storePendingChatSourceContext(userId, pendingSourceContext, {
				session_id: activeSession.session_id,
				content: text,
				after_message_id: messages.at(-1)?.message_id ?? null
			});
		}
		const optimisticMessage: ChatMessage = {
			message_id: optimisticId,
			session_id: activeSession.session_id,
			role: 'user',
			content: text,
			created_at: createdAt,
			tool_call_id: null,
			tool_calls: [],
			tool_result: null,
			source_contexts: sourceContexts
		};
		const streamingMessage: ChatMessage = {
			...optimisticMessage,
			message_id: streamingId,
			role: 'assistant',
			content: ''
		};
		messages = [...messages, optimisticMessage, streamingMessage];
		streamingText = '';
		input = '';
		sending = true;
		progress = { phase: 'starting', cycle_index: 0, elapsed_ms: 0 };
		progressHistory = [progress];

		error = '';
		notice = '';
		try {
			const turn = await streamChatMessage(
				activeSession.session_id,
				text,
				(content) => {
					if (!isCurrentSession(generation, activeCollectionId)) return;
					pendingText += content;
					if (!textFrame) textFrame = requestAnimationFrame(flushText);
				},
				sourceContexts,
				(nextProgress) => {
					if (!isCurrentSession(generation, activeCollectionId)) return;
					progress = nextProgress;
					progressHistory = appendChatProgress(progressHistory, nextProgress);
				},
				signal
			);
			if (!isCurrentSession(generation, activeCollectionId)) return;
			cancelTextFrame();
			flushText();
			applyTurn(turn, [optimisticId, streamingId]);
			if (sourceContexts.length) {
				clearPendingChatSourceContext(userId, activeCollectionId);
				pendingSourceContext = null;
			}
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			try {
				const trajectory = await fetchChatTrajectory(activeSession.session_id, signal);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = trajectory.items;
				pendingApproval = trajectory.pending_approval;
				const persistedMessage = messages
					.slice(previousMessageCount)
					.find((message) => message.role === 'user' && message.content === text);
				if (!persistedMessage) {
					input = text;
				}
				pendingSourceContext = readPendingChatSourceContext(userId, activeCollectionId, {
					sessionId: activeSession.session_id,
					messages
				});
				scheduleRecovery();
			} catch {
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = messages.filter(
					(message) => ![optimisticId, streamingId].includes(message.message_id)
				);
				input = text;
			}
			error = errorMessage(err);
		} finally {
			cancelTextFrame();
			signal?.removeEventListener('abort', cancelTextFrame);
			if (isCurrentSession(generation, activeCollectionId)) {
				sending = false;
				progress = null;
				progressHistory = [];
			}
		}
	}

	function handleComposerInput(value: string) {
		input = value;
	}

	function removePendingSourceContext() {
		clearPendingChatSourceContext(userId, collectionId);
		pendingSourceContext = null;
	}

	function applyTurn(
		turn: ChatTurn,
		localMessageIds: string[] = [],
		decidedToolName: string | null = null
	) {
		const prior = localMessageIds.length
			? messages.filter((message) => !localMessageIds.includes(message.message_id))
			: messages;
		const knownIds = new Set(prior.map((message) => message.message_id));
		messages = [...prior, ...turn.messages.filter((message) => !knownIds.has(message.message_id))];
		pendingApproval = turn.pending_approval;
		if (turn.status === 'rejected') {
			notice = $t(rejectionNoticeKey(decidedToolName));
		}
		if (turn.status === 'failed') {
			error = $t('researchAgent.turnFailed', { code: turn.error_code ?? turn.status });
		}
		if (turn.status === 'completed' && turn.warnings?.length) {
			notice = $t('researchAgent.turnLimited');
		}
		if (session) {
			const updatedAt = turn.messages.at(-1)?.created_at ?? session.updated_at;
			session = { ...session, updated_at: updatedAt };
			upsertHistory(session, titleFromMessages(messages));
		}
	}

	async function decide(decision: 'approved' | 'rejected') {
		if (!session || !pendingApproval || deciding) return;
		const activeSession = session;
		const generation = sessionGeneration;
		const activeCollectionId = collectionId;
		const call = pendingApproval;
		deciding = true;
		failedSessionId = null;
		error = '';
		notice = '';
		let decisionError: unknown;
		try {
			const turn = await decideChatToolCall(
				activeSession.session_id,
				call,
				decision,
				sessionController?.signal
			).catch((err: unknown) => {
				decisionError = err;
				return null;
			});
			if (!isCurrentSession(generation, activeCollectionId)) return;
			if (!turn || !turn.messages.length) {
				// A lost response or idempotent acknowledgement needs the persisted result.
				const trajectory = await fetchChatTrajectory(
					activeSession.session_id,
					sessionController?.signal
				);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = trajectory.items;
				loadFeedback(trajectory.feedback);
				pendingApproval = trajectory.pending_approval;
				upsertHistory(activeSession);
				if (turn) applyTurn({ ...turn, pending_approval: pendingApproval }, [], call.name);
				else if (
					!messages.some((message) => message.tool_result?.tool_call_id === call.tool_call_id)
				) {
					error = errorMessage(decisionError);
					failedSessionId = activeSession.session_id;
				}
			} else {
				applyTurn(turn, [], call.name);
			}
			scheduleRecovery();
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			error = errorMessage(decisionError ?? err);
		} finally {
			if (isCurrentSession(generation, activeCollectionId)) deciding = false;
		}
	}

	function rejectionNoticeKey(toolName: string | null) {
		if (toolName === 'start_research_process') return 'researchAgent.researchProcessRejected';
		if (toolName === 'confirm_objective') return 'researchAgent.objectiveConfirmationRejected';
		if (toolName === 'start_objective_analysis') return 'researchAgent.objectiveAnalysisRejected';
		if (toolName === 'record_finding_feedback') return 'researchAgent.findingFeedbackRejected';
		if (toolName === 'curate_finding') return 'researchAgent.findingCurationRejected';
		if (toolName === 'create_finding_version') return 'researchAgent.findingAuthoringRejected';
		if (toolName === 'create_evidence_version') return 'researchAgent.evidenceAuthoringRejected';
		if (toolName === 'create_research_plan') return 'researchAgent.researchPlanRejected';
		if (toolName === 'publish_agent_objective_analysis') {
			return 'researchAgent.agentObjectiveAnalysisRejected';
		}
		return 'researchAgent.rejected';
	}

	function formatHistoryTime(value: string) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
	}
</script>

<svelte:head>
	<title>{$t('researchAgent.title')}</title>
</svelte:head>

<section class="research-agent" aria-label={$t('researchAgent.chatLabel')}>
	<ResearchSidebar
		{collectionId}
		{collectionName}
		{history}
		{activeSessionId}
		{loading}
		{sending}
		{deciding}
		onNewSession={startNewSession}
		onSwitchSession={switchSession}
		{formatHistoryTime}
	/>

	<main class="conversation">
		{#if conversationTitle || queryObjectiveId}
			<ConversationHeader title={conversationTitle} {collectionId} objectiveId={queryObjectiveId} />
		{/if}

		{#if error}
			<div class="status status-error" role="alert">
				<span>{error}</span>
				{#if failedSessionId !== null}
					<button type="button" on:click={() => loadSession(failedSessionId ?? '')}>
						{$t('researchAgent.retrySession')}
					</button>
				{/if}
			</div>
		{/if}
		{#if notice}
			<div class="status status-notice" role="status">{notice}</div>
		{/if}
		<MessageTimeline
			sessionId={activeSessionId}
			{messages}
			{feedbackByMessage}
			onFeedback={saveFeedback}
			{streamingText}
			{pendingApproval}
			{progress}
			{progressHistory}
			{recoveringCallId}
			{recoveryLoading}
			{recoveryError}
			onRefreshRecovery={refreshRecovery}
			{loading}
			{sending}
			{deciding}
			ready={Boolean(session)}
			onSend={sendMessage}
			{decide}
		/>

		{#key userId}
			<MessageComposer
				{collectionId}
				{input}
				{sending}
				disabled={!session ||
					loading ||
					sending ||
					deciding ||
					Boolean(pendingApproval) ||
					Boolean(recoveringCallId)}
				{pendingSourceContext}
				onInput={handleComposerInput}
				onSend={sendMessage}
				onRemovePendingSourceContext={removePendingSourceContext}
			/>
		{/key}
	</main>
</section>

<style>
	:global(.app-shell:has(.research-agent)) {
		padding: 0;
		overflow: hidden;
		background: var(--bg-page);
	}

	:global(.app-shell:has(.research-agent) .site-header),
	:global(.app-shell:has(.research-agent) .site-footer),
	:global(.app-shell:has(.research-agent) .bg-grid),
	:global(.collection-header:has(+ .collection-tabs + .collection-panel .research-agent)),
	:global(.collection-tabs:has(+ .collection-panel .research-agent)) {
		display: none;
	}

	:global(.app-shell:has(.research-agent) .page) {
		width: 100vw;
		max-width: none;
		margin: 0;
	}

	:global(.collection-panel:has(.research-agent)) {
		gap: 0;
	}

	.research-agent {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: grid;
		grid-template-columns: 256px minmax(0, 1fr);
		width: 100vw;
		height: 100vh;
		height: 100dvh;
		background: var(--bg-page);
		color: var(--text-primary);
		letter-spacing: 0;
		overflow: hidden;
	}

	.conversation {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		background: var(--bg-page);
	}

	.status {
		width: min(calc(100% - 64px), 900px);
		margin: 12px auto 0;
		padding: 10px 12px;
		border-radius: 6px;
		font-size: 13px;
	}

	.status-error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		border: 1px solid var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.status-error button {
		flex: 0 0 auto;
		padding: 6px 10px;
		border: 1px solid var(--danger-border);
		border-radius: 4px;
		background: var(--surface-card);
		color: var(--danger-text);
		cursor: pointer;
	}

	.status-notice {
		border: 1px solid var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	@media (prefers-reduced-motion: reduce) {
		:global(.research-agent *),
		:global(.research-agent *::before),
		:global(.research-agent *::after) {
			animation-duration: 0.01ms !important;
			animation-iteration-count: 1 !important;
			scroll-behavior: auto !important;
			transition-duration: 0.01ms !important;
		}
	}

	@media (max-width: 820px) {
		.research-agent {
			grid-template-columns: 1fr;
			grid-template-rows: auto minmax(0, 1fr);
		}

		.status {
			width: calc(100% - 36px);
		}
	}
</style>
