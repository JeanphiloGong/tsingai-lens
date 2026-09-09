<script lang="ts">
	import { onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		createChatSession,
		clearPendingChatSourceContext,
		decideChatToolCall,
		fetchChatSession,
		fetchChatTrajectory,
		appendChatProgress,
		readPendingChatSourceContext,
		streamChatMessage,
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

	let sessionGeneration = 0;
	let sessionController: AbortController | null = null;

	let destroyed = false;

	onDestroy(() => {
		destroyed = true;
		sessionController?.abort();
	});

	function isCurrentSession(generation: number, ownerCollectionId: string) {
		return !destroyed && generation === sessionGeneration && ownerCollectionId === collectionId;
	}

	$: collectionId = $page.params.id ?? '';

	$: queryObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
	$: activeSessionId = session?.session_id ?? '';
	$: if (browser && collectionId && collectionId !== loadedCollectionId) {
		loadedCollectionId = collectionId;
		void loadSession();
	}

	function sessionStorageKey() {
		return `lens.chatSession.${collectionId}`;
	}

	function historyStorageKey() {
		return `lens.chatSessionHistory.${collectionId}`;
	}

	function clearLegacySessionStorage() {
		if (!browser) return;
		window.localStorage.removeItem(`lens.goalSession.${collectionId}`);
		window.localStorage.removeItem(`lens.goalSessionHistory.${collectionId}`);
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
		sessionController?.abort();
		const controller = new AbortController();
		sessionController = controller;
		session = null;
		messages = [];
		input = '';
		sending = false;
		streamingText = '';
		deciding = false;
		progressHistory = [];

		loading = true;
		error = '';
		notice = '';
		pendingApproval = null;
		progress = null;
		pendingSourceContext = readPendingChatSourceContext(activeCollectionId);
		if (!requestedSessionId) clearLegacySessionStorage();
		history = readHistory();

		try {
			const storedSessionId = requestedSessionId || readStoredSessionId();
			let nextSession: ChatSession | null = null;
			if (storedSessionId) {
				try {
					nextSession = await fetchChatSession(storedSessionId, controller.signal);
					if (!isCurrentSession(generation, activeCollectionId)) return;
					if (nextSession.collection_id !== activeCollectionId) nextSession = null;
				} catch {
					if (!isCurrentSession(generation, activeCollectionId)) return;
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
				pendingApproval = trajectory.pending_approval;
			}
			session = nextSession;
			storeSessionId(nextSession.session_id);
			upsertHistory(nextSession);
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			error = errorMessage(err);
			session = null;
			messages = [];
			pendingApproval = null;
		} finally {
			if (isCurrentSession(generation, activeCollectionId)) loading = false;
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
		if (!session || !text || sending || deciding || pendingApproval) return;
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
				clearPendingChatSourceContext(activeCollectionId);
				pendingSourceContext = null;
			}
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			try {
				const trajectory = await fetchChatTrajectory(activeSession.session_id, signal);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = trajectory.items;
				pendingApproval = trajectory.pending_approval;
				if (
					!messages
						.slice(previousMessageCount)
						.some((message) => message.role === 'user' && message.content === text)
				) {
					input = text;
				}
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
		clearPendingChatSourceContext(collectionId);
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
		const generation = sessionGeneration;
		const activeCollectionId = collectionId;
		const call = pendingApproval;
		deciding = true;
		error = '';
		notice = '';
		try {
			const turn = await decideChatToolCall(
				session.session_id,
				call,
				decision,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, activeCollectionId)) return;
			applyTurn(turn, [], call.name);
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			error = errorMessage(err);
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
		<ConversationHeader {collectionId} objectiveId={queryObjectiveId} />

		{#if error}
			<div class="status status-error" role="alert">{error}</div>
		{/if}
		{#if notice}
			<div class="status status-notice" role="status">{notice}</div>
		{/if}
		<MessageTimeline
			sessionId={activeSessionId}
			{messages}
			{streamingText}
			{pendingApproval}
			{progress}
			{progressHistory}
			{loading}
			{sending}
			{deciding}
			ready={Boolean(session)}
			onSend={sendMessage}
			{decide}
		/>

		<MessageComposer
			{collectionId}
			{input}
			{sending}
			disabled={!session || loading || sending || deciding || Boolean(pendingApproval)}
			{pendingSourceContext}
			onInput={handleComposerInput}
			onSend={sendMessage}
			onRemovePendingSourceContext={removePendingSourceContext}
		/>
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
		border: 1px solid var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
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
