<script lang="ts">
	import { onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage, getApiErrorReason, isApiErrorCode } from '../../../_shared/api';
	import { authState } from '../../../_shared/authState';

	import { workspaces } from '$lib/workspace/workspaces';
	import {
		createConversation,
		deleteConversation,
		setConversationPin,
		setConversationTitle,
		listConversations,
		branchChatMessage,
		selectConversationPath,
		forkConversation,
		sendConversationMessage,
		fetchConversation,
		fetchConversationTree,
		setChatMessageFeedback,
		type ChatFeedbackInput,
		type ChatBranchOptions,
		type ChatFeedbackState,
		type ChatMessageFeedback,
		type ConversationMessage,
		type Conversation,
		type ConversationTreeData,
		type ConversationTreeNode
	} from '$lib/conversation/api';
	import { fetchModelConnections, type ModelConnectionChoice } from '$lib/agent/model-connections';
	import {
		clearPendingChatSourceContexts,
		readPendingChatSourceContexts,
		storePendingChatSourceContexts,
		type ChatSourceContext
	} from '$lib/document/source-context';
	import {
		decideOperation,
		fetchTaskState,
		appendChatProgress,
		resumeTask,
		readTaskUpdates,
		stopTask,
		type ChatProgress,
		type TaskSnapshot,
		type TaskState,
		type TaskExecutionEvent,
		type Operation,
		type AgentTurn
	} from '$lib/agent/api';
	import { t } from '../../../_shared/i18n';
	import MessageTimeline from './MessageTimeline.svelte';
	import ConversationHeader from './ConversationHeader.svelte';
	import ConversationTree from './ConversationTree.svelte';
	import MessageComposer from './MessageComposer.svelte';
	import ResearchSidebar from './ResearchSidebar.svelte';
	import {
		getChatSessionActivity,
		getModelServiceErrorKey,
		type ChatSessionActivity
	} from '$lib/research/conversationPresentation';
	import IconButton from '../../../_shared/IconButton.svelte';
	import type { DocumentProfile } from '../../../_shared/documents';
	import type { ResearchAgentSlashCommandName } from '../../../_shared/researchAgentSlashCommands';
	import {
		Plus,
		History,
		X,
		LoaderCircle,
		Clock3,
		CircleAlert,
		GitBranch,
		ArrowRight,
		Pin,
		PinOff,
		ChevronDown,
		Check
	} from '@lucide/svelte';

	export let embedded = false;
	export let selectedPapers: Pick<DocumentProfile, 'document_id' | 'title'>[] = [];
	export let onRemovePaper: (id: string) => void = () => {};
	export let sourceContextVersion = 0;
	export let onSourcesChanged: () => void = () => {};
	export let onBusyChange: (busy: boolean) => void = () => {};
	$: onBusyChange(
		loading ||
			sending ||
			deciding ||
			revising ||
			running ||
			Boolean(recoveringCallId || recoveryError)
	);
	let showHistory = false;
	let showTree = false;
	let tree: ConversationTreeData | null = null;
	let treeLoading = false;
	let treeError = '';
	let treeController: AbortController | null = null;
	let treeTimer: ReturnType<typeof setTimeout> | undefined;
	let checkpointId = '';
	$: checkpointIndex = messages.findIndex((message) => message.message_id === checkpointId);
	$: checkpointEnd =
		checkpointIndex < 0
			? -1
			: messages.findIndex((message, index) => index > checkpointIndex && message.role === 'user');
	$: visibleMessages =
		checkpointId && checkpointIndex >= 0
			? messages.slice(0, checkpointEnd < 0 ? messages.length : checkpointEnd)
			: messages;
	$: checkpointQuestion = checkpointIndex < 0 ? '' : messages[checkpointIndex].content;

	type StoredChatSession = {
		conversation_id: string;
		title: string;
		created_at: string;
		updated_at: string;
		status: ChatSessionActivity;
		is_pinned: boolean;
	};

	let session: Conversation | null = null;
	let messages: ConversationMessage[] = [];
	let branches: ChatBranchOptions[] = [];
	let branchDraft: ConversationMessage | null = null;
	let running = false;
	let revising = false;
	let revisionRequest: { key: string; id: string } | null = null;
	let feedbackByMessage: Record<string, ChatFeedbackState> = {};
	let pendingApproval: Operation | null = null;
	let retryableDecision: Operation | null = null;
	let history: StoredChatSession[] = [];
	let sessionActivities: Record<string, ChatSessionActivity> = {};
	let historyTimer: ReturnType<typeof setTimeout> | undefined;
	let historyLoading = false;
	let historyGeneration = 0;
	const historyPageSize = 10;
	let historyPageOffset = 0;
	let historyHasMore = false;
	let historyPageLoading = false;
	let historyPageError = false;
	let historyNeedsRefresh = false;
	let pinningSessionId = '';
	let renamingSessionId = '';
	let renameDraft = '';
	let renameSaving = false;
	let renameError = '';
	let renameDialog: HTMLDialogElement;
	$: renameInvalid =
		!renameDraft.trim() ||
		Array.from(renameDraft.trim()).length > 160 ||
		/[\r\n]/.test(renameDraft) ||
		renameDraft.includes(String.fromCharCode(0));
	let loading = false;
	let sending = false;
	let stopping = false;
	let submitting = false;
	let deletingSessionId = '';
	$: sessionNavigationDisabled =
		loading ||
		submitting ||
		deciding ||
		revising ||
		Boolean(deletingSessionId || pinningSessionId) ||
		renameSaving;
	let progress: ChatProgress | null = null;
	let settledTurn: AgentTurn | null = null;
	let progressHistory: ChatProgress[] = [];
	let streamingText = '';
	let responseSnapshot: TaskSnapshot | null = null;
	let modelConnections: ModelConnectionChoice[] = [];
	let selectedModelConnectionId = '';
	let modelPicker: HTMLDetailsElement | null = null;
	$: selectedModelConnectionName =
		modelConnections.find((item) => item.connection_id === selectedModelConnectionId)
			?.display_name ?? '';
	let modelConnectionsOwner = '';
	let modelConnectionsLoading = false;
	let modelConnectionsError = '';
	let modelConnectionsController: AbortController | null = null;
	let updatesController: AbortController | null = null;

	let deciding = false;
	let error = '';
	let notice = '';
	let turnRequestError = '';
	let input = '';
	let appliedReviewKey = '';
	let pendingSourceContexts: ChatSourceContext[] = [];
	let inspectRelated = embedded;
	let loadedWorkspaceId = '';
	let loadedUserId = '';
	let failedSessionId: string | null = null;
	let recoveringCallId: string | null = null;
	let recoveryLoading = false;
	let recoveryError = '';
	let recoveryTimer: ReturnType<typeof setTimeout> | undefined;
	let titleTimer: ReturnType<typeof setTimeout> | undefined;

	let sessionGeneration = 0;
	let sessionController: AbortController | null = null;

	let destroyed = false;

	onDestroy(() => {
		destroyed = true;
		modelConnectionsController?.abort();
		clearTimeout(recoveryTimer);
		clearTimeout(historyTimer);
		clearTimeout(titleTimer);
		sessionController?.abort();
		updatesController?.abort();
		treeController?.abort();
		clearTimeout(treeTimer);
	});

	function isCurrentSession(generation: number, ownerWorkspaceId: string) {
		return (
			!destroyed &&
			generation === sessionGeneration &&
			ownerWorkspaceId === workspaceId &&
			$authState.status === 'authenticated' &&
			$authState.user?.user_id === loadedUserId
		);
	}

	$: workspaceId = $page.params.id ?? '';
	$: userId = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: if (browser && userId !== modelConnectionsOwner) {
		modelConnectionsOwner = userId;
		modelConnectionsController?.abort();
		modelConnections = [];
		selectedModelConnectionId = '';
		modelConnectionsLoading = false;
		modelConnectionsError = '';
		// eslint-disable-next-line svelte/infinite-reactive-loop -- The owner/request guard controls this effect; async result assignments are not its dependencies.
		if (userId) void loadModelConnections();
	}
	$: if (sourceContextVersion && userId && workspaceId) {
		refreshPendingSources();
	}
	$: workspaceName = userId
		? ($workspaces.find((item) => item.workspace_id === workspaceId)?.name?.trim() ?? '')
		: '';
	$: conversationTitle =
		session?.title?.trim() ??
		messages
			.find((message) => message.role === 'user')
			?.content.trim()
			.split('\n')[0] ??
		'';

	$: queryObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
	$: queryReviewFindingId = $page.url.searchParams.get('review_finding_id') ?? '';
	$: reviewKey = `${workspaceId}:${queryObjectiveId}:${queryReviewFindingId}`;
	$: if (
		!embedded &&
		session &&
		!loading &&
		queryObjectiveId &&
		queryReviewFindingId &&
		appliedReviewKey !== reviewKey
	) {
		if (!input.trim()) {
			input = $t('research.findingReview.reviewDraft', {
				objective: queryObjectiveId,
				finding: queryReviewFindingId
			});
			appliedReviewKey = reviewKey;
		}
	}
	$: activeSessionId = session?.conversation_id ?? '';
	$: if (browser && (workspaceId !== loadedWorkspaceId || userId !== loadedUserId)) {
		loadedWorkspaceId = workspaceId;
		loadedUserId = userId;
		loadWorkspaceSession();
	}
	$: if (session && !loading) {
		sessionActivities = {
			...sessionActivities,
			[session.conversation_id]: recoveryError
				? 'unavailable'
				: getChatSessionActivity(
						messages,
						sending || running,
						pendingApproval?.tool_call_id ?? null
					)
		};
	}

	function loadWorkspaceSession() {
		sessionActivities = {};
		void loadSession();
	}

	function sessionStorageKey() {
		return `lens.chatSession.${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}${embedded ? ':documents' : ''}`;
	}

	function refreshPendingSources() {
		const contexts = readPendingChatSourceContexts(
			userId,
			workspaceId,
			session
				? {
						sessionId: session.conversation_id,
						messages: messages.filter((message) => !message.message_id.startsWith('local-'))
					}
				: undefined
		);
		pendingSourceContexts = running || (sending && !submitting) ? [] : contexts;
		if (session && !sending && !running && contexts.length) {
			storePendingChatSourceContexts(userId, workspaceId, contexts);
		}
	}

	function historyStorageKey() {
		return `lens.chatSessionHistory.${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}`;
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
				.filter((item) => item && typeof item.conversation_id === 'string')
				.map((item) => ({
					conversation_id: item.conversation_id,
					title:
						typeof item.title === 'string' && item.title.trim()
							? item.title
							: $t('researchAgent.untitledSession'),
					created_at:
						typeof item.created_at === 'string' ? item.created_at : new Date().toISOString(),
					updated_at:
						typeof item.updated_at === 'string' ? item.updated_at : new Date().toISOString(),
					status: item.status === 'running' || item.status === 'approval' ? item.status : 'idle',
					is_pinned: item.is_pinned === true
				}));
		} catch {
			return [];
		}
	}

	function writeHistory(nextHistory: StoredChatSession[]) {
		history = nextHistory.sort(
			(a, b) =>
				Number(b.is_pinned) - Number(a.is_pinned) ||
				Date.parse(b.updated_at) - Date.parse(a.updated_at) ||
				(a.conversation_id < b.conversation_id ? 1 : a.conversation_id > b.conversation_id ? -1 : 0)
		);
		if (!browser) return;
		window.localStorage.setItem(historyStorageKey(), JSON.stringify(history));
	}

	function titleFromText(text: string) {
		const firstLine = text.trim().split('\n')[0]?.trim() ?? '';
		if (!firstLine) return $t('researchAgent.untitledSession');
		return firstLine.length > 160 ? `${firstLine.slice(0, 160)}...` : firstLine;
	}

	function titleFromMessages(nextMessages: ConversationMessage[]) {
		const firstUserMessage = nextMessages.find((message) => message.role === 'user');
		const text = firstUserMessage?.content ?? '';
		return titleFromText(text);
	}

	function upsertHistory(nextSession: Conversation, title = '') {
		const stored = readHistory();
		const previous = stored.find((item) => item.conversation_id === nextSession.conversation_id);
		const existing = stored.filter((item) => item.conversation_id !== nextSession.conversation_id);
		writeHistory([
			{
				conversation_id: nextSession.conversation_id,
				title:
					nextSession.title ||
					title ||
					(messages.some((message) => message.role === 'user')
						? titleFromMessages(messages)
						: previous?.title || $t('researchAgent.untitledSession')),
				created_at: nextSession.created_at,
				updated_at: nextSession.updated_at,
				status: nextSession.status,
				is_pinned: previous?.is_pinned ?? nextSession.is_pinned === true
			},
			...existing
		]);
	}

	async function refreshSessionTitle(attempt = 0) {
		clearTimeout(titleTimer);
		if (!session || session.title) return;
		const sessionId = session.conversation_id;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		const historyRequest = historyGeneration;
		try {
			const saved = await fetchConversation(sessionId, sessionController?.signal);
			if (
				!isCurrentSession(generation, ownerWorkspaceId) ||
				session?.conversation_id !== sessionId ||
				historyRequest !== historyGeneration ||
				session.title
			)
				return;
			if (!saved.title) {
				if (attempt < 24)
					titleTimer = setTimeout(() => void refreshSessionTitle(attempt + 1), 2000);
				return;
			}
			session = { ...session, title: saved.title };
			upsertHistory(session);
		} catch {
			// Optional title metadata must not hide an answer or prevent the next turn.
		}
	}

	async function fetchServerHistory(
		generation: number,
		ownerWorkspaceId: string,
		count = historyPageSize
	) {
		const historyRequest = ++historyGeneration;
		try {
			const items: Conversation[] = [];
			let hasMore = false;
			// Refresh only pages already opened; initial recovery requests one page.
			do {
				const response = await listConversations(ownerWorkspaceId, {
					limit: historyPageSize,
					offset: items.length,
					signal: sessionController?.signal
				});
				if (
					!isCurrentSession(generation, ownerWorkspaceId) ||
					historyRequest !== historyGeneration
				)
					return null;
				items.push(...response.items);
				hasMore = response.items.length === historyPageSize;
			} while (hasMore && items.length < count);
			return { items, hasMore };
		} catch {
			// The existing local history remains usable when the list request is unavailable.
			return null;
		}
	}

	function applyServerHistory(
		items: Conversation[],
		generation: number,
		ownerWorkspaceId: string,
		append = false,
		hasMore = items.length === historyPageSize
	) {
		if (!isCurrentSession(generation, ownerWorkspaceId)) return;
		const stored = readHistory();
		// The list is a navigation index. Do not download every trajectory just
		// to derive sidebar titles; a trajectory is loaded when selected.
		const serverHistory = items.map((item) => {
			const previous = stored.find((entry) => entry.conversation_id === item.conversation_id);
			const status: ChatSessionActivity =
				item.status === 'running' || item.status === 'approval' ? item.status : 'idle';
			const title =
				item.title?.trim() ||
				(item.conversation_id === session?.conversation_id && messages.length
					? titleFromMessages(messages)
					: previous?.title || $t('researchAgent.untitledSession'));
			return {
				conversation_id: item.conversation_id,
				title,
				created_at: item.created_at,
				updated_at: item.updated_at,
				status,
				is_pinned: item.is_pinned === true
			};
		});
		sessionActivities = {
			...sessionActivities,
			...Object.fromEntries(serverHistory.map((item) => [item.conversation_id, item.status]))
		};
		const receivedIds = new Set(items.map((item) => item.conversation_id));
		const retained = append ? stored.filter((item) => !receivedIds.has(item.conversation_id)) : [];
		writeHistory([...retained, ...serverHistory]);
		historyPageOffset = append ? historyPageOffset + items.length : items.length;
		historyHasMore = hasMore;
		historyPageError = false;
		if (!append) historyNeedsRefresh = false;
		if (session) {
			const current = items.find((item) => item.conversation_id === session?.conversation_id);
			if (current) session = { ...session, is_pinned: current.is_pinned === true };
		}
	}

	async function refreshServerHistory(generation: number, ownerWorkspaceId: string) {
		const result = await fetchServerHistory(
			generation,
			ownerWorkspaceId,
			Math.max(historyPageSize, historyPageOffset)
		);
		if (result)
			applyServerHistory(result.items, generation, ownerWorkspaceId, false, result.hasMore);
		return result !== null;
	}

	async function loadMoreHistory(): Promise<void> {
		if (
			(!historyHasMore && !historyNeedsRefresh) ||
			historyPageLoading ||
			historyLoading ||
			sessionNavigationDisabled ||
			destroyed
		)
			return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		historyPageLoading = true;
		historyPageError = false;
		error = '';
		if (historyNeedsRefresh) {
			const refreshed = await refreshServerHistory(generation, ownerWorkspaceId);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			historyPageLoading = false;
			if (!refreshed) {
				historyPageError = true;
				error = $t('error.requestFailed');
				return;
			}
			return loadMoreHistory();
		}
		const historyRequest = ++historyGeneration;
		try {
			const response = await listConversations(ownerWorkspaceId, {
				limit: historyPageSize,
				offset: historyPageOffset,
				signal: sessionController?.signal
			});
			if (!isCurrentSession(generation, ownerWorkspaceId) || historyRequest !== historyGeneration)
				return;
			applyServerHistory(response.items, generation, ownerWorkspaceId, true);
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId) && historyRequest === historyGeneration) {
				historyPageError = true;
				error = errorMessage(err);
			}
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId) && historyRequest === historyGeneration)
				historyPageLoading = false;
		}
	}

	function loadMoreOnScroll(event: Event) {
		const list = event.currentTarget as HTMLElement;
		if (!historyPageError && list.scrollHeight - list.scrollTop - list.clientHeight < 80)
			void loadMoreHistory();
	}

	async function refreshHistoryActivities(refreshIndex = true) {
		if (
			!session ||
			loading ||
			historyLoading ||
			historyPageLoading ||
			destroyed ||
			deletingSessionId ||
			pinningSessionId
		)
			return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		clearTimeout(historyTimer);
		historyLoading = true;
		history = readHistory();
		if (refreshIndex) await refreshServerHistory(generation, ownerWorkspaceId);
		if (!isCurrentSession(generation, ownerWorkspaceId)) return;
		const candidates = history.filter(
			(item) =>
				item.conversation_id !== session?.conversation_id &&
				['running', 'approval', 'recovering', 'unavailable'].includes(
					sessionActivities[item.conversation_id]
				)
		);
		await Promise.all(
			candidates.map(async (item) => {
				let activity: ChatSessionActivity;
				try {
					const trajectory = await fetchTaskState(item.conversation_id, sessionController?.signal);
					activity = getChatSessionActivity(
						trajectory.items,
						Boolean(trajectory.running || trajectory.response?.status === 'running'),
						trajectory.pending_approval?.tool_call_id ?? null
					);
				} catch {
					activity = 'unavailable';
				}
				if (
					!isCurrentSession(generation, ownerWorkspaceId) ||
					item.conversation_id === session?.conversation_id
				)
					return;
				sessionActivities = { ...sessionActivities, [item.conversation_id]: activity };
			})
		);
		if (!isCurrentSession(generation, ownerWorkspaceId)) return;
		historyLoading = false;
		if (
			history.some(
				(item) =>
					item.conversation_id !== session?.conversation_id &&
					['running', 'approval', 'recovering', 'unavailable'].includes(
						sessionActivities[item.conversation_id]
					)
			)
		) {
			historyTimer = setTimeout(() => void refreshHistoryActivities(), 5000);
		}
	}

	function selectModelConnection(connectionId: string) {
		selectedModelConnectionId = connectionId;
		if (modelPicker) {
			modelPicker.open = false;
			modelPicker.querySelector('summary')?.focus();
		}
	}

	async function loadModelConnections() {
		modelConnectionsController?.abort();
		const controller = new AbortController();
		modelConnectionsController = controller;
		const owner = userId;
		modelConnectionsLoading = true;
		modelConnectionsError = '';
		try {
			const result = await fetchModelConnections(controller.signal);
			if (destroyed || owner !== userId || controller.signal.aborted) return;
			// eslint-disable-next-line svelte/infinite-reactive-loop -- The owner/request guard controls this effect; async result assignments are not its dependencies.
			modelConnections = result.items;
			// eslint-disable-next-line svelte/infinite-reactive-loop -- The owner/request guard controls this effect; async result assignments are not its dependencies.
			selectedModelConnectionId = result.items[0]?.connection_id ?? '';
		} catch (err) {
			if (!controller.signal.aborted && owner === userId && !destroyed) {
				// eslint-disable-next-line svelte/infinite-reactive-loop -- The owner/request guard controls this effect; async result assignments are not its dependencies.
				modelConnectionsError = errorMessage(err);
			}
		} finally {
			// eslint-disable-next-line svelte/infinite-reactive-loop -- The owner/request guard controls this effect; async result assignments are not its dependencies.
			if (modelConnectionsController === controller) modelConnectionsLoading = false;
		}
	}

	async function loadSession(requestedSessionId = '') {
		closeTree();
		tree = null;
		checkpointId = '';
		const activeWorkspaceId = workspaceId;
		const generation = ++sessionGeneration;
		clearTimeout(titleTimer);
		clearTimeout(recoveryTimer);
		clearTimeout(historyTimer);
		historyLoading = false;
		recoveringCallId = null;
		historyPageLoading = false;
		historyPageOffset = 0;
		historyPageError = false;
		historyHasMore = false;
		historyNeedsRefresh = false;
		pinningSessionId = '';
		deletingSessionId = '';
		recoveryLoading = false;
		recoveryError = '';
		sessionController?.abort();
		updatesController?.abort();
		updatesController = null;
		responseSnapshot = null;
		sessionController = null;
		session = null;
		messages = [];
		feedbackByMessage = {};
		branches = [];
		branchDraft = null;
		running = false;
		stopping = false;
		revising = false;
		revisionRequest = null;
		input = '';
		sending = false;
		submitting = false;
		streamingText = '';
		deciding = false;
		progressHistory = [];
		failedSessionId = null;

		loading = false;
		error = '';
		notice = '';
		turnRequestError = '';
		pendingApproval = null;
		retryableDecision = null;
		progress = null;
		settledTurn = null;
		pendingSourceContexts = [];
		history = [];
		if (!userId || !activeWorkspaceId) return;

		const controller = new AbortController();
		sessionController = controller;
		loading = true;
		pendingSourceContexts = readPendingChatSourceContexts(userId, activeWorkspaceId);
		history = readHistory();
		// The history endpoint is an independent navigation index. Start it with
		// session recovery so the page does not wait for a serial request waterfall.
		const initialHistoryPromise = fetchServerHistory(generation, activeWorkspaceId);

		try {
			const storedSessionId = requestedSessionId || readStoredSessionId();
			let nextSession: Conversation | null = null;
			let createdSession = false;
			if (storedSessionId) {
				try {
					nextSession = await fetchConversation(storedSessionId, controller.signal);
					if (!isCurrentSession(generation, activeWorkspaceId)) return;
					if (nextSession.workspace_id !== activeWorkspaceId) nextSession = null;
				} catch (err) {
					if (!isCurrentSession(generation, activeWorkspaceId)) return;
					if (!isApiErrorCode(err, 200201)) throw err;
					nextSession = null;
					clearStoredSessionId();
					writeHistory(readHistory().filter((item) => item.conversation_id !== storedSessionId));
				}
			}

			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			if (nextSession === null) {
				nextSession = await createConversation(activeWorkspaceId, controller.signal);
				if (!isCurrentSession(generation, activeWorkspaceId)) return;
				createdSession = true;
			} else {
				const trajectory = await fetchTaskState(nextSession.conversation_id, controller.signal);
				if (!isCurrentSession(generation, activeWorkspaceId)) return;
				acceptTrajectory(trajectory);
			}
			session = nextSession;
			const savedCheckpoint = window.localStorage.getItem(
				`${sessionStorageKey()}:checkpoint:${session.conversation_id}`
			);
			if (
				savedCheckpoint &&
				messages.some(
					(message) => message.message_id === savedCheckpoint && message.role === 'user'
				)
			)
				checkpointId = savedCheckpoint;
			refreshPendingSources();
			onSourcesChanged();
			storeSessionId(nextSession.conversation_id);
			upsertHistory(nextSession);
			const initialHistory = await initialHistoryPromise;
			if (initialHistory) {
				applyServerHistory(
					initialHistory.items,
					generation,
					activeWorkspaceId,
					false,
					initialHistory.hasMore
				);
			}
			if (createdSession && isCurrentSession(generation, activeWorkspaceId))
				upsertHistory(nextSession);
			scheduleRecovery();
		} catch (err) {
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			failedSessionId = requestedSessionId || readStoredSessionId();
			error = errorMessage(err);
			session = null;
			messages = [];
			pendingApproval = null;
			retryableDecision = null;
		} finally {
			if (isCurrentSession(generation, activeWorkspaceId)) {
				loading = false;
				void refreshHistoryActivities(false);
			}
		}
	}

	function scheduleRecovery() {
		clearTimeout(recoveryTimer);
		if ((responseSnapshot && responseSnapshot.status !== 'running') || settledTurn) {
			recoveringCallId = null;
			return;
		}
		const completed = new Set(messages.map((message) => message.tool_result?.tool_call_id));
		recoveringCallId =
			messages
				.flatMap((message) => message.tool_calls)
				.find(
					(call) =>
						call.tool_call_id !== pendingApproval?.tool_call_id &&
						call.tool_call_id !== retryableDecision?.tool_call_id &&
						!completed.has(call.tool_call_id)
				)?.tool_call_id ?? null;
		if (
			running &&
			responseSnapshot?.status === 'running' &&
			!pendingApproval &&
			!sending &&
			!recoveryError
		) {
			void resumeResponse();
			return;
		}
		if ((recoveringCallId || running) && !destroyed) {
			recoveryTimer = setTimeout(() => void refreshRecovery(), 3000);
		}
	}

	function acceptSnapshot(snapshot: TaskSnapshot) {
		if (
			responseSnapshot?.task_id === snapshot.task_id &&
			(responseSnapshot.checkpoint_revision > snapshot.checkpoint_revision ||
				(responseSnapshot.checkpoint_revision === snapshot.checkpoint_revision &&
					responseSnapshot.status === snapshot.status))
		)
			return;
		responseSnapshot = snapshot;
		settledTurn = null;
		running = snapshot.status === 'running' || snapshot.status === 'accepted';
		recoveryError = '';
		streamingText = snapshot.content;
		progress = snapshot.progress;
		progressHistory = appendChatProgress(progressHistory, snapshot.progress);
	}

	function acceptTrajectory(trajectory: TaskState) {
		messages = trajectory.items;
		branches = trajectory.branches ?? [];
		branchDraft = trajectory.branch_draft ?? null;
		// A persisted running response is authoritative when the trajectory flag
		// was written by an earlier polling pass.
		running = Boolean(trajectory.running || trajectory.response?.status === 'running');
		loadFeedback(trajectory.feedback);
		pendingApproval = trajectory.pending_approval;
		recoveryError = '';
		turnRequestError = '';
		retryableDecision = trajectory.retryable_decision ?? null;
		if (trajectory.response) {
			acceptSnapshot(trajectory.response);
			running = responseSnapshot?.status === 'running' || responseSnapshot?.status === 'accepted';
		} else {
			responseSnapshot = null;
			settledTurn = null;
		}
		if (!running) void refreshSessionTitle();
	}

	function acceptTaskEvent(event: TaskExecutionEvent) {
		if (event.event === 'message.delta' && typeof event.text === 'string') {
			streamingText += event.text;
		}
	}

	async function resumeResponse() {
		if (!session || !responseSnapshot || updatesController || destroyed) return;
		const controller = new AbortController();
		updatesController = controller;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		const current = () =>
			isCurrentSession(generation, ownerWorkspaceId) &&
			updatesController === controller &&
			!controller.signal.aborted;
		try {
			const trajectory = await readTaskUpdates(
				session.conversation_id, responseSnapshot.task_id,
				responseSnapshot.checkpoint_revision, controller.signal, acceptTaskEvent
			);
			if (!current()) return;
			acceptTrajectory(trajectory);
			refreshPendingSources();
			onSourcesChanged();
		} catch (err) {
			if (current() && running) recoveryError = errorMessage(err);
		} finally {
			if (current()) {
				updatesController = null;
				if (running) recoveryTimer = setTimeout(() => void resumeResponse(), 1000);
			}
		}
	}

	async function refreshRecovery() {
		if (!session || (!recoveringCallId && !running && !recoveryError) || recoveryLoading) return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		const activeSession = session;
		updatesController?.abort();
		updatesController = null;
		clearTimeout(recoveryTimer);
		recoveryLoading = true;
		try {
			const trajectory = await fetchTaskState(
				activeSession.conversation_id,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			recoveryError = '';
			error = '';
			acceptTrajectory(trajectory);
			failedSessionId = null;
			session = {
				...activeSession,
				updated_at: messages.at(-1)?.created_at ?? activeSession.updated_at
			};
			refreshPendingSources();
			onSourcesChanged();
			upsertHistory(session);
		} catch (err) {
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			recoveryError = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId)) {
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
		const ownerWorkspaceId = workspaceId;
		const current = feedbackByMessage[messageId]?.feedback ?? null;
		feedbackByMessage = {
			...feedbackByMessage,
			[messageId]: { feedback: current, saving: true, error: '' }
		};
		try {
			const saved = await setChatMessageFeedback(
				session.conversation_id,
				messageId,
				input,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return false;
			feedbackByMessage = {
				...feedbackByMessage,
				[messageId]: { feedback: saved, saving: false, error: '' }
			};
			return true;
		} catch {
			if (!isCurrentSession(generation, ownerWorkspaceId)) return false;
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
		if (sessionNavigationDisabled) return;
		clearStoredSessionId();
		session = null;
		messages = [];
		pendingApproval = null;
		retryableDecision = null;
		input = '';
		await loadSession();
	}

	async function switchSession(sessionId: string, preserveDraft = false) {
		if (sessionId === activeSessionId || sessionNavigationDisabled) return;
		const draft = input;
		const owner = userId;
		session = null;
		messages = [];
		pendingApproval = null;
		retryableDecision = null;
		await loadSession(sessionId);
		if (preserveDraft && userId === owner && activeSessionId === sessionId) input = draft;
	}

	async function toggleSessionPin(sessionId: string) {
		if (sessionNavigationDisabled) return;
		const item = history.find((entry) => entry.conversation_id === sessionId);
		if (!item) return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		pinningSessionId = sessionId;
		historyGeneration += 1;
		historyPageLoading = false;
		error = '';
		try {
			const saved = await setConversationPin(sessionId, !item.is_pinned, sessionController?.signal);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			historyGeneration += 1;
			historyNeedsRefresh = true;
			writeHistory(
				history.map((entry) =>
					entry.conversation_id === sessionId ? { ...entry, is_pinned: saved.is_pinned } : entry
				)
			);
			if (session?.conversation_id === sessionId) session = { ...session, is_pinned: saved.is_pinned };
			await refreshServerHistory(generation, ownerWorkspaceId);
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId)) error = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId)) pinningSessionId = '';
		}
	}

	function beginRename(item: StoredChatSession) {
		if (sessionNavigationDisabled) return;
		renamingSessionId = item.conversation_id;
		renameDraft = item.title;
		renameError = '';
		renameDialog.showModal();
	}

	function cancelRename() {
		if (renameSaving) return;
		renameDialog?.close();
		renamingSessionId = '';
		renameDraft = '';
	}

	async function saveRename() {
		if (renameInvalid || renameSaving || !renamingSessionId) return;
		const title = renameDraft.trim();
		const targetId = renamingSessionId;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		renameSaving = true;
		renameError = '';
		historyGeneration += 1;
		historyPageLoading = false;
		try {
			const saved = await setConversationTitle(targetId, title, sessionController?.signal);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			historyGeneration += 1;
			writeHistory(
				history.map((entry) =>
					entry.conversation_id === targetId ? { ...entry, title: saved.title || title } : entry
				)
			);
			if (session?.conversation_id === targetId) session = { ...session, title: saved.title };
			renameSaving = false;
			cancelRename();
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId)) renameError = errorMessage(err);
		} finally {
			renameSaving = false;
		}
	}

	async function removeSession(sessionId: string) {
		if (sessionNavigationDisabled || !browser) return;
		const item = history.find((entry) => entry.conversation_id === sessionId);
		if (!item || !window.confirm($t('researchAgent.deleteSessionConfirm', { title: item.title })))
			return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		deletingSessionId = sessionId;
		error = '';
		try {
			await deleteConversation(sessionId, sessionController?.signal);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return;
			historyGeneration += 1;
			historyPageLoading = false;
			historyNeedsRefresh = true;
			const remaining = history.filter((entry) => entry.conversation_id !== sessionId);
			writeHistory(remaining);
			if (sessionId !== activeSessionId) {
				await refreshServerHistory(generation, ownerWorkspaceId);
				return;
			}
			clearStoredSessionId();
			session = null;
			messages = [];
			pendingApproval = null;
			retryableDecision = null;
			await loadSession(remaining[0]?.conversation_id ?? '');
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId)) error = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId)) deletingSessionId = '';
		}
	}

	function closeTree() {
		showTree = false;
		treeController?.abort();
		treeController = null;
		clearTimeout(treeTimer);
	}

	async function openTree() {
		if (!session || sessionNavigationDisabled) return;
		showTree = true;
		clearTimeout(treeTimer);
		treeController?.abort();
		const controller = new AbortController();
		treeController = controller;
		treeLoading = true;
		treeError = '';
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		try {
			const result = await fetchConversationTree(session.conversation_id, controller.signal);
			if (!isCurrentSession(generation, ownerWorkspaceId) || treeController !== controller) return;
			const checkpoint = result.active_path.indexOf(checkpointId);
			tree =
				checkpoint < 0
					? result
					: { ...result, active_path: result.active_path.slice(0, checkpoint + 1) };
		} catch (err) {
			if (!controller.signal.aborted && isCurrentSession(generation, ownerWorkspaceId))
				treeError = errorMessage(err);
		} finally {
			if (treeController === controller) {
				treeLoading = false;
				if (showTree && tree?.nodes.some((node) => node.status === 'running'))
					treeTimer = setTimeout(() => void openTree(), 5000);
			}
		}
	}

	function returnToLatest() {
		checkpointId = '';
		if (session)
			window.localStorage.removeItem(`${sessionStorageKey()}:checkpoint:${session.conversation_id}`);
	}

	async function selectTreeNode(node: ConversationTreeNode) {
		if (sessionNavigationDisabled) return;
		closeTree();
		const conversationId = node.message.conversation_id;
		try {
			if (node.kind !== 'conversation') {
				const saved = await fetchConversation(conversationId);
				await selectConversationPath(
					conversationId, saved.path_revision ?? 0,
					node.task_id ? { task_id: node.task_id } : { tip_message_id: node.message.message_id }
				);
			}
			await switchSession(conversationId, true);
			returnToLatest();
		} catch (err) {
			error = errorMessage(err);
		}
	}

	async function forkFromMessage(message: ConversationMessage) {
		try {
			const fork = await forkConversation(message.conversation_id, message.message_id);
			await switchSession(fork.conversation_id, true);
		} catch (err) {
			error = errorMessage(err);
		}
	}

	async function reviseMessage(
		message: ConversationMessage,
		content?: string,
		mode: 'revise' | 'continue' = content === undefined ? 'continue' : 'revise'
	): Promise<boolean> {
		if (
			!session ||
			loading ||
			sending ||
			deciding ||
			revising ||
			running ||
			pendingApproval ||
			retryableDecision ||
			recoveringCallId ||
			recoveryError
		)
			return false;
		const ownerWorkspaceId = workspaceId;
		let generation = sessionGeneration;
		const key = JSON.stringify([message.conversation_id, message.message_id, content, mode]);
		if (revisionRequest?.key !== key) {
			const id = crypto.randomUUID();
			revisionRequest = { key, id };
		}
		revising = true;
		error = '';
		try {
			const accepted = await branchChatMessage(
				message.conversation_id,
				message.message_id,
				revisionRequest.id,
				content,
				sessionController?.signal,
				mode
			);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return false;
			const branch = await fetchConversation(message.conversation_id, sessionController?.signal);
			const trajectory = await readTaskUpdates(
				branch.conversation_id, accepted.task_id, 0, sessionController?.signal,
				acceptTaskEvent
			);
			if (!isCurrentSession(generation, ownerWorkspaceId)) return false;
			clearTimeout(recoveryTimer);
			closeTree();
			returnToLatest();
			tree = null;
			if (mode === 'continue') input = '';
			sessionController?.abort();
			sessionController = new AbortController();
			generation = ++sessionGeneration;
			session = branch;
			feedbackByMessage = {};
			responseSnapshot = null;
			streamingText = '';
			acceptTrajectory(trajectory);
			storeSessionId(branch.conversation_id);
			upsertHistory(branch, content ?? message.content);
			revising = false;
			revisionRequest = null;
			scheduleRecovery();
			// A repeated create request may find a branch whose question already ran.
			if (branchDraft && !running)
				await sendMessage(branchDraft.content, branchDraft.source_contexts);
			return true;
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId)) error = errorMessage(err);
			return false;
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId)) revising = false;
		}
	}

	async function sendMessage(nextText = input.trim(), revisionSources?: ChatSourceContext[]) {
		const draft = nextText.trim();
		if (branchDraft && revisionSources === undefined) return;
		if (
			!session ||
			!draft ||
			loading ||
			revising ||
			sending ||
			deciding ||
			running ||
			pendingApproval ||
			retryableDecision ||
			recoveringCallId ||
			recoveryError
		)
			return;
		const isRevision = revisionSources !== undefined;
		const paperLinks = (isRevision ? [] : selectedPapers).map((paper) => {
			const title = (paper.title || $t('workspace.unknownName')).replace(/[\\[\]`*_\n\r]/g, ' ');
			return `- [${title}](/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(paper.document_id)})`;
		});
		let text = paperLinks.length
			? `${draft}\n\n${$t('researchAgent.paperScope.messageLabel')}\n${paperLinks.join('\n')}`
			: draft;
		if (!isRevision && pendingSourceContexts.length && inspectRelated)
			text += `\n\n${$t('researchAgent.paperScope.relatedRequest')}`;
		if (text.length > 12000) {
			error = $t('researchAgent.paperScope.tooLong');
			return;
		}
		const modelConnectionId = selectedModelConnectionId;
		if (!modelConnectionId) return;
		const activeSession = session;
		const activeWorkspaceId = workspaceId;
		const generation = sessionGeneration;
		const signal = sessionController?.signal;
		const parentMessageId = checkpointId || messages.filter((message) => message.role !== 'tool' && message.content).at(-1)?.message_id || null;
		const previousMessageCount = messages.length;
		const optimisticId = `local-${Date.now()}`;
		const streamingId = `local-stream-${Date.now()}`;
		const createdAt = new Date().toISOString();
		const sourceContexts = revisionSources ?? [...pendingSourceContexts];
		if (!isRevision && sourceContexts.length) {
			storePendingChatSourceContexts(userId, activeWorkspaceId, sourceContexts, {
				conversation_id: activeSession.conversation_id,
				content: text,
				after_message_id: messages.at(-1)?.message_id ?? null
			});
		}
		const optimisticMessage: ConversationMessage = {
			message_id: optimisticId,
			conversation_id: activeSession.conversation_id,
			role: 'user',
			content: text,
			created_at: createdAt,
			tool_call_id: null,
			tool_calls: [],
			tool_result: null,
			source_contexts: sourceContexts
		};
		const streamingMessage: ConversationMessage = {
			...optimisticMessage,
			message_id: streamingId,
			role: 'assistant',
			content: ''
		};
		messages = [...messages, optimisticMessage, streamingMessage];
		responseSnapshot = null;
		settledTurn = null;
		streamingText = '';
		if (!isRevision) input = '';
		sending = true;
		submitting = true;
		progress = { phase: 'starting', cycle_index: 0, elapsed_ms: 0 };
		progressHistory = [progress];

		error = '';
		notice = '';
		turnRequestError = '';
		recoveryError = '';
		const acknowledgeSubmission = () => {
			if (!submitting) return;
			submitting = false;
			upsertHistory(activeSession);
			if (!isRevision && sourceContexts.length) {
				// Keep the recovery record until a saved user message confirms the handoff.
				pendingSourceContexts = [];
				onSourcesChanged();
			}
		};
		try {
			const accepted = await sendConversationMessage(
				activeSession.conversation_id, text, parentMessageId, sourceContexts,
				modelConnectionId, signal
			);
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			acknowledgeSubmission();
			const trajectory = await readTaskUpdates(
				activeSession.conversation_id,
				accepted.task_id,
				0,
				signal,
				acceptTaskEvent
			);
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			returnToLatest();
			acceptTrajectory(trajectory);
			branchDraft = null;
			if (!isRevision && sourceContexts.length) {
				clearPendingChatSourceContexts(userId, activeWorkspaceId);
				pendingSourceContexts = [];
				onSourcesChanged();
			}
		} catch (err) {
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			let reconciled = false;
			try {
				const trajectory = await fetchTaskState(activeSession.conversation_id, signal);
				if (!isCurrentSession(generation, activeWorkspaceId)) return;
				acceptTrajectory(trajectory);
				reconciled = true;
				const persistedMessage = messages
					.slice(previousMessageCount)
					.find((message) => message.role === 'user' && message.content === text);
				if (!persistedMessage && !isRevision) {
					input = draft;
				}
				pendingSourceContexts = readPendingChatSourceContexts(userId, activeWorkspaceId, {
					sessionId: activeSession.conversation_id,
					messages
				});
				onSourcesChanged();
				scheduleRecovery();
			} catch {
				if (!isCurrentSession(generation, activeWorkspaceId)) return;
				messages = messages.filter((message) => message.message_id !== streamingId);
				if (!responseSnapshot && streamingText.trim())
					messages = [...messages, { ...streamingMessage, content: streamingText }];
				if (!isRevision) input = draft;
			}
			const key = getModelServiceErrorKey(getApiErrorReason(err));
			if (key) turnRequestError = $t(key);
			if (!reconciled || running)
				recoveryError = errorMessage(err);
			else if (!responseSnapshot && !pendingApproval && !key) turnRequestError = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, activeWorkspaceId)) {
				sending = false;
				submitting = false;
				if (!isRevision) {
					refreshPendingSources();
					onSourcesChanged();
				}
				progress = null;
				progressHistory = [];
				scheduleRecovery();
				if (isRevision) {
					try {
						const trajectory = await fetchTaskState(activeSession.conversation_id, signal);
						if (isCurrentSession(generation, activeWorkspaceId)) {
							branches = trajectory.branches ?? [];
							branchDraft = trajectory.branch_draft ?? null;
							running = Boolean(trajectory.running || trajectory.response?.status === 'running');
							scheduleRecovery();
						}
					} catch (err) {
						if (isCurrentSession(generation, activeWorkspaceId)) error = errorMessage(err);
					}
				}
			}
		}
	}

	async function stopResponse() {
		if (!session || !responseSnapshot || responseSnapshot.status !== 'running' || stopping) return;
		const generation = sessionGeneration;
		const ownerWorkspaceId = workspaceId;
		stopping = true;
		try {
			const snapshot = await stopTask(session.conversation_id, responseSnapshot.task_id);
			if (
				isCurrentSession(generation, ownerWorkspaceId) &&
				responseSnapshot?.task_id === snapshot.task_id &&
				responseSnapshot.status === 'running'
			) {
				if (snapshot.status === 'running')
					responseSnapshot = { ...responseSnapshot, stop_requested: snapshot.stop_requested };
				else acceptSnapshot(snapshot);
			}
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspaceId)) error = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerWorkspaceId)) stopping = false;
		}
	}

	function handleComposerInput(value: string) {
		input = value;
	}

	function handleSlashCommand(command: ResearchAgentSlashCommandName) {
		switch (command) {
			case 'new':
				void startNewSession();
				return;
			case 'history':
				if (embedded) {
					showHistory = !showHistory;
					if (showHistory) void refreshHistoryActivities();
				} else {
					notice = $t('researchAgent.commands.historySidebar');
				}
				return;
			case 'tree':
				void openTree();
				return;
			case 'status': {
				const status = pendingApproval
					? $t('researchAgent.sessionState.approval')
					: running || sending || recoveringCallId
						? $t('researchAgent.sessionState.running')
						: $t('researchAgent.commands.idleStatus');
				notice = $t('researchAgent.commands.statusNotice', { status });
				return;
			}
			case 'help':
				notice = $t('researchAgent.commands.helpNotice');
				return;
		}
	}

	function handleUnknownSlashCommand(command: string) {
		error = $t('researchAgent.commands.unknown', { command: `/${command}` });
		notice = '';
	}

	function removePendingSourceContexts(index: number) {
		pendingSourceContexts = pendingSourceContexts.filter((_, candidate) => candidate !== index);
		storePendingChatSourceContexts(userId, workspaceId, pendingSourceContexts);
		onSourcesChanged();
	}

	function clearPendingSources() {
		pendingSourceContexts = [];
		clearPendingChatSourceContexts(userId, workspaceId);
		onSourcesChanged();
	}

	async function decide(
		decision: 'approved' | 'rejected',
		call: Operation | null = pendingApproval
	) {
		if (!session || !call || deciding) return;
		const activeSession = session;
		const generation = sessionGeneration;
		const activeWorkspaceId = workspaceId;
		deciding = true;
		error = '';
		notice = '';
		try {
			const trajectory = await decideOperation(
				activeSession.conversation_id, call, decision, sessionController?.signal
			);
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			acceptTrajectory(trajectory);
			upsertHistory(activeSession);
			if (decision === 'rejected') notice = $t(rejectionNoticeKey(call.name));
			scheduleRecovery();
		} catch (err) {
			if (!isCurrentSession(generation, activeWorkspaceId)) return;
			error = errorMessage(err);
			refreshRecovery();
		} finally {
			if (isCurrentSession(generation, activeWorkspaceId)) deciding = false;
		}
	}

	async function resumeInterruptedTask() {
		if (!session || responseSnapshot?.status !== 'interrupted' || recoveryLoading) return;
		const generation = sessionGeneration;
		const ownerWorkspace = workspaceId;
		recoveryLoading = true;
		error = '';
		try {
			const trajectory = await resumeTask(
				session.conversation_id, responseSnapshot.task_id,
				responseSnapshot.checkpoint_revision, sessionController?.signal
			);
			if (isCurrentSession(generation, ownerWorkspace)) acceptTrajectory(trajectory);
		} catch (err) {
			if (isCurrentSession(generation, ownerWorkspace)) error = errorMessage(err);
		} finally {
			if (isCurrentSession(generation, ownerWorkspace)) recoveryLoading = false;
		}
	}

	async function retryDecision() {
		const call = retryableDecision;
		if (!call || (call.status !== 'approved' && call.status !== 'rejected')) return;
		await decide(call.status, call);
	}

	function rejectionNoticeKey(toolName: string | null) {
		if (toolName === 'start_research_process') return 'researchAgent.researchProcessRejected';
		if (toolName === 'confirm_objective') return 'researchAgent.objectiveConfirmationRejected';
		if (toolName === 'start_objective_analysis') return 'researchAgent.objectiveAnalysisRejected';
		if (toolName === 'record_finding_feedback') return 'researchAgent.findingFeedbackRejected';
		if (toolName === 'curate_finding') return 'researchAgent.findingCurationRejected';
		if (toolName === 'create_finding_version') return 'researchAgent.findingAuthoringRejected';
		if (toolName === 'create_paper_experiment_revision')
			return 'researchAgent.paperExperimentRevisionRejected';
		if (toolName === 'create_research_plan') return 'researchAgent.researchPlanRejected';
		return 'researchAgent.rejected';
	}

	function formatHistoryTime(value: string) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
	}
</script>

<svelte:window
	on:keydown={(event) => {
		if (event.key === 'Escape' && modelPicker?.open && modelPicker.contains(event.target as Node)) {
			event.preventDefault();
			modelPicker.open = false;
			modelPicker.querySelector('summary')?.focus();
		}
	}}
	on:pointerdown={(event) => {
		if (modelPicker?.open && !modelPicker.contains(event.target as Node)) modelPicker.open = false;
	}}
	on:focus={() => void refreshHistoryActivities()}
	on:storage={(event) => {
		if (event.key === historyStorageKey()) void refreshHistoryActivities();
	}}
/>

<section
	class="research-agent"
	class:embedded
	class:standalone={!embedded}
	aria-label={$t('researchAgent.chatLabel')}
>
	{#if !embedded}
		<ResearchSidebar
			{workspaceId}
			{workspaceName}
			{history}
			{sessionActivities}
			{activeSessionId}
			disabled={sessionNavigationDisabled}
			onNewSession={startNewSession}
			onSwitchSession={switchSession}
			onDeleteSession={removeSession}
			onTogglePin={toggleSessionPin}
			onRenameSession={(id) => {
				const item = history.find((entry) => entry.conversation_id === id);
				if (item) beginRename(item);
			}}
			{pinningSessionId}
			{historyHasMore}
			{historyPageLoading}
			{historyPageError}
			onLoadMoreHistory={loadMoreHistory}
			{formatHistoryTime}
		/>
	{/if}

	<main class="conversation">
		{#if embedded}
			<div class="embedded-toolbar">
				<IconButton
					label={$t('researchAgent.newSession')}
					disabled={sessionNavigationDisabled}
					onClick={startNewSession}><Plus size={16} /></IconButton
				>
				<IconButton
					label={$t('researchAgent.historyTitle')}
					pressed={showHistory}
					onClick={() => {
						showHistory = !showHistory;
						if (showHistory) void refreshHistoryActivities();
					}}><History size={16} /></IconButton
				>
				<span title={conversationTitle}
					>{conversationTitle || $t('researchAgent.untitledSession')}</span
				>
				<IconButton
					label={$t('researchAgent.tree.title')}
					disabled={!session || sessionNavigationDisabled}
					onClick={openTree}><GitBranch size={17} /></IconButton
				>
			</div>
			{#if showHistory}
				<nav
					class="embedded-history"
					aria-label={$t('researchAgent.historyTitle')}
					on:scroll={loadMoreOnScroll}
				>
					{#each history as item (item.conversation_id)}
						{@const activity = sessionActivities[item.conversation_id]}
						<div class="embedded-history-item">
							<button
								class="embedded-history-select"
								type="button"
								title={item.title}
								class:active={item.conversation_id === activeSessionId}
								disabled={sessionNavigationDisabled}
								on:click={() => {
									void switchSession(item.conversation_id);
									showHistory = false;
								}}
							>
								<span class="embedded-history-title">{item.title}</span>
								{#if activity && activity !== 'idle'}
									<span class="session-state" data-state={activity}>
										{#if activity === 'running'}<LoaderCircle size={12} />
										{:else if activity === 'unavailable'}<CircleAlert size={12} />
										{:else}<Clock3 size={12} />{/if}
										<span>{$t(`researchAgent.sessionState.${activity}`)}</span>
									</span>
								{/if}
							</button>
							<button
								class="embedded-rename"
								type="button"
								disabled={sessionNavigationDisabled}
								aria-label={$t('researchAgent.renameSession')}
								title={$t('researchAgent.renameSession')}
								on:click={() => beginRename(item)}>{$t('researchAgent.renameSession')}</button
							>
							<button
								class="embedded-pin"
								class:pinned={item.is_pinned}
								type="button"
								disabled={sessionNavigationDisabled}
								aria-label={$t(
									item.is_pinned ? 'researchAgent.unpinSession' : 'researchAgent.pinSession'
								)}
								title={$t(
									item.is_pinned ? 'researchAgent.unpinSession' : 'researchAgent.pinSession'
								)}
								aria-pressed={item.is_pinned}
								aria-busy={pinningSessionId === item.conversation_id}
								on:click={() => toggleSessionPin(item.conversation_id)}
							>
								{#if pinningSessionId === item.conversation_id}<LoaderCircle size={14} />
								{:else if item.is_pinned}<PinOff size={14} aria-hidden="true" />
								{:else}<Pin size={14} aria-hidden="true" />{/if}
							</button>
						</div>
					{/each}
					{#if historyHasMore}
						<button
							class="embedded-load-more"
							type="button"
							disabled={sessionNavigationDisabled || historyPageLoading}
							aria-label={$t('researchAgent.loadMoreSessions')}
							on:click={loadMoreHistory}
						>
							{#if historyPageLoading}<LoaderCircle size={14} />{:else}<ChevronDown
									size={14}
								/>{/if}
							{$t('researchAgent.loadMoreSessions')}
						</button>
					{/if}
				</nav>
			{/if}
		{:else if conversationTitle || queryObjectiveId || branchDraft}
			<ConversationHeader
				title={conversationTitle || branchDraft?.content || ''}
				{workspaceId}
				objectiveId={queryObjectiveId}
				disabled={!session || sessionNavigationDisabled}
				onOpenTree={openTree}
			/>
		{/if}

		{#if retryableDecision && !checkpointId}
			<div
				class="status status-notice decision-recovery"
				role="status"
				data-testid="decision-recovery"
			>
				<span
					>{$t(
						retryableDecision.status === 'approved'
							? 'researchAgent.savedApprovalWaiting'
							: 'researchAgent.savedRejectionWaiting'
					)}</span
				>
				<button type="button" disabled={deciding || loading || running} on:click={retryDecision}>
					{$t(
						retryableDecision.status === 'approved'
							? 'researchAgent.retryApprovedDecision'
							: 'researchAgent.retryRejectedDecision'
					)}
				</button>
			</div>
		{/if}
		{#if (error && session && !pendingApproval) || modelConnectionsError}
			<div class="status status-error" role="alert">
				<span>{error || modelConnectionsError}</span>
				{#if failedSessionId !== null}
					<button type="button" on:click={() => loadSession(failedSessionId ?? '')}>
						{$t('researchAgent.retrySession')}
					</button>
				{/if}
			</div>
		{/if}
		{#if notice}
			<div class="status status-notice" role="status">
				<span>{notice}</span>
			</div>
		{/if}
		{#if responseSnapshot?.status === 'interrupted'}
			<div class="status" role="status">
				<button type="button" disabled={recoveryLoading} on:click={resumeInterruptedTask}>
					{$t('researchAgent.revision.resume')}
				</button>
			</div>
		{/if}
		<MessageTimeline
			{workspaceId}
			sessionId={activeSessionId}
			messages={visibleMessages}
			{branches}
			running={!checkpointId && running}
			revisionDisabled={revising ||
				Boolean(
					checkpointId &&
					(running || sending || pendingApproval || retryableDecision || recoveringCallId)
				)}
			onRevise={reviseMessage}
			onFork={forkFromMessage}
			onSwitchVersion={(id) => switchSession(id, true)}
			{feedbackByMessage}
			onFeedback={saveFeedback}
			streamingText={checkpointId ? '' : streamingText}
			responseSnapshot={checkpointId ? null : responseSnapshot}
			pendingApproval={checkpointId ? null : pendingApproval}
			progress={checkpointId ? null : progress}
			progressHistory={checkpointId ? [] : progressHistory}
			settledTurn={checkpointId ? null : settledTurn}
			requestError={checkpointId ? '' : turnRequestError}
			approvalError={checkpointId ? '' : error}
			loadError={!session && failedSessionId !== null ? error : ''}
			onRetrySession={() => loadSession(failedSessionId ?? '')}
			onContinue={session &&
			!checkpointId &&
			!branchDraft &&
			!running &&
			!pendingApproval &&
			!retryableDecision
				? () => sendMessage($t('researchAgent.continueRequest'))
				: undefined}
			recoveringCallId={checkpointId ? null : recoveringCallId}
			recoveryLoading={!checkpointId && recoveryLoading}
			recoveryError={checkpointId ? '' : recoveryError}
			onRefreshRecovery={refreshRecovery}
			{loading}
			sending={!checkpointId && sending}
			{deciding}
			ready={Boolean(session) && !branchDraft}
			onSend={sendMessage}
			{decide}
		/>
		{#if checkpointId}
			<div class="checkpoint-bar" role="status">
				<GitBranch size={15} />
				<div>
					<strong>{$t('researchAgent.tree.checkpoint')}</strong><span>{checkpointQuestion}</span>
				</div>
				<button type="button" on:click={returnToLatest}
					>{$t('researchAgent.tree.latest')}<ArrowRight size={14} /></button
				>
			</div>
		{/if}
		{#if branchDraft && !sending}
			<div class="revision-draft" role="status">
				<div>
					<strong>{$t('researchAgent.revision.draft')}</strong>
					<p>{branchDraft.content}</p>
				</div>
				<button
					type="button"
					disabled={loading ||
						revising ||
						running ||
						deciding ||
						Boolean(pendingApproval) ||
						Boolean(retryableDecision) ||
						Boolean(recoveringCallId)}
					on:click={() =>
						branchDraft && sendMessage(branchDraft.content, branchDraft.source_contexts)}
					>{$t('researchAgent.revision.resume')}</button
				>
			</div>
		{/if}

		{#key userId}
			<MessageComposer
				{workspaceId}
				{input}
				{sending}
				canStop={!checkpointId && responseSnapshot?.status === 'running'}
				stopping={stopping || Boolean(responseSnapshot?.stop_requested)}
				onStop={stopResponse}
				disabled={!session ||
					!selectedModelConnectionId ||
					modelConnectionsLoading ||
					loading ||
					revising ||
					running ||
					Boolean(branchDraft) ||
					sending ||
					deciding ||
					Boolean(pendingApproval) ||
					Boolean(retryableDecision) ||
					Boolean(recoveringCallId || recoveryError)}
				pendingSourceContexts={checkpointId ? [] : pendingSourceContexts}
				hasExtraContext={!checkpointId && selectedPapers.length > 0}
				onInput={handleComposerInput}
				onSend={sendMessage}
				onCommand={handleSlashCommand}
				onUnknownCommand={handleUnknownSlashCommand}
				onRemovePendingSourceContexts={removePendingSourceContexts}
				onClearPendingSourceContexts={clearPendingSources}
			>
				<details
					slot="model-picker"
					class="model-picker"
					bind:this={modelPicker}
					data-testid="model-connection-picker"
					on:focusout={(event) => {
						if (
							modelPicker &&
							event.relatedTarget instanceof Node &&
							!modelPicker.contains(event.relatedTarget)
						)
							modelPicker.open = false;
					}}
				>
					<summary title={$t('researchAgent.modelConnectionLabel')}>
						<span class="sr-only">{$t('researchAgent.modelConnectionLabel')}: </span>
						<span class="model-picker-name"
							>{selectedModelConnectionName || $t('researchAgent.modelConnectionLabel')}</span
						>
						<ChevronDown size={14} aria-hidden="true" />
					</summary>
					<div
						class="model-picker-menu"
						role="group"
						aria-label={$t('researchAgent.modelConnectionLabel')}
					>
						{#if !modelConnectionsLoading && !modelConnections.length}<p>
								{$t('researchAgent.modelConnectionEmpty')}
							</p>{/if}
						<div class="model-picker-options">
							{#each modelConnections as item (item.connection_id)}
								<button
									type="button"
									disabled={modelConnectionsLoading}
									aria-pressed={item.connection_id === selectedModelConnectionId}
									on:click={() => selectModelConnection(item.connection_id)}
								>
									<span>{item.display_name}</span>
									{#if item.connection_id === selectedModelConnectionId}<Check
											size={15}
											aria-hidden="true"
										/>{/if}
								</button>
							{/each}
						</div>
					</div>
				</details>
				{#if !checkpointId && pendingSourceContexts.length}
					<label class="related-sources"
						><input
							type="checkbox"
							bind:checked={inspectRelated}
							disabled={sending || deciding}
						/>{$t('researchAgent.paperScope.related')}</label
					>
				{/if}
				{#if !checkpointId && selectedPapers.length}
					<details class="paper-scope" open data-testid="selected-paper-context">
						<summary
							>{$t('researchAgent.paperScope.selected', { count: selectedPapers.length })}</summary
						>
						<ul>
							{#each selectedPapers as paper (paper.document_id)}
								<li>
									<a
										href={resolve('/workspaces/[id]/documents/[document_id]', {
											id: workspaceId,
											document_id: paper.document_id
										})}
										title={paper.title ?? ''}>{paper.title}</a
									>
									<IconButton
										label={$t('researchAgent.paperScope.remove', { title: paper.title ?? '' })}
										disabled={sending || deciding}
										onClick={() => onRemovePaper(paper.document_id)}><X size={14} /></IconButton
									>
								</li>
							{/each}
						</ul>
					</details>
				{/if}
			</MessageComposer>
		{/key}
	</main>
</section>

{#if showTree}
	<ConversationTree
		{tree}
		loading={treeLoading}
		error={treeError}
		disabled={sessionNavigationDisabled || treeLoading || Boolean(treeError)}
		onClose={closeTree}
		onRefresh={openTree}
		onSelect={selectTreeNode}
		onRevise={(node, content) => reviseMessage(node.message, content)}
	/>
{/if}

<dialog
	bind:this={renameDialog}
	aria-labelledby="rename-title"
	on:cancel={(event) => {
		event.preventDefault();
		cancelRename();
	}}
>
	<form on:submit|preventDefault={saveRename}>
		<h2 id="rename-title">{$t('researchAgent.renameSession')}</h2>
		<label for="rename-input">{$t('researchAgent.renameInput')}</label>
		<input
			id="rename-input"
			bind:value={renameDraft}
			disabled={renameSaving}
			aria-describedby="rename-help"
			aria-invalid={renameInvalid}
		/>
		<p id="rename-help">{$t('researchAgent.renameHelp')}</p>
		{#if renameError}<p role="alert">{renameError}</p>{/if}
		<button type="button" disabled={renameSaving} on:click={cancelRename}
			>{$t('researchAgent.cancelRename')}</button
		>
		<button type="submit" disabled={renameInvalid || renameSaving}
			>{$t(renameSaving ? 'researchAgent.savingRename' : 'researchAgent.saveRename')}</button
		>
	</form>
</dialog>

<style>
	dialog {
		width: min(420px, calc(100vw - 32px));
		box-sizing: border-box;
		border: 1px solid var(--border-default);
		border-radius: 12px;
		padding: 24px;
		color: var(--text-primary);
		background: var(--surface-card);
	}
	dialog::backdrop {
		background: rgb(0 0 0 / 35%);
	}
	dialog input {
		display: block;
		width: 100%;
		box-sizing: border-box;
		padding: 10px;
		margin-top: 8px;
	}
	dialog p {
		font-size: 13px;
	}
	dialog button {
		padding: 8px 16px;
		margin-right: 8px;
	}

	.checkpoint-bar {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 0 auto;
		padding: 10px 18px;
		width: min(100%, 936px);
		box-sizing: border-box;
		border-top: 1px solid var(--border-default);
		color: var(--text-secondary);
		font-size: 12px;
	}
	.checkpoint-bar > div {
		display: grid;
		gap: 2px;
		flex: 1;
		min-width: 0;
	}
	.checkpoint-bar strong {
		font-size: 11px;
		font-weight: 600;
		color: var(--brand-primary);
	}
	.checkpoint-bar span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.checkpoint-bar button {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		flex-shrink: 0;
		padding: 8px 0;
		border: 0;
		background: transparent;
		color: var(--brand-primary);
		font-size: 12px;
		cursor: pointer;
	}
	.research-agent :global(.session-state) {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 110px;
		font-size: 11px;
		line-height: 16px;
		color: var(--text-secondary);
	}
	.research-agent :global(.session-state svg) {
		flex-shrink: 0;
	}
	.research-agent :global(.session-state[data-state='running']) {
		color: var(--brand-primary);
	}
	.research-agent :global(.session-state[data-state='running'] svg) {
		animation: session-working 1.4s linear infinite;
	}
	.research-agent :global(.session-state[data-state='unavailable']) {
		color: var(--danger-text);
	}
	@keyframes session-working {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.research-agent :global(.session-state[data-state='running'] svg) {
			animation: none;
		}
	}
	.embedded-history-title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.revision-draft {
		display: flex;
		align-items: center;
		gap: 12px;
		width: min(900px, calc(100% - 32px));
		margin: 8px auto;
	}
	.revision-draft > div {
		min-width: 0;
		flex: 1;
	}
	.revision-draft strong {
		font-size: 12px;
		color: var(--text-secondary);
	}
	.revision-draft p {
		margin: 4px 0;
		font-size: 13px;
		max-height: 90px;
		overflow: auto;
		overflow-wrap: anywhere;
		white-space: pre-wrap;
	}
	.revision-draft button {
		flex-shrink: 0;
		border: 1px solid var(--border-default);
		background: var(--surface-card);
		color: var(--text-primary);
		border-radius: 6px;
		padding: 8px 12px;
		cursor: pointer;
	}
	:global(.app-shell:has(.research-agent.standalone)) {
		padding: 0;
		overflow: hidden;
		background: var(--bg-page);
	}

	:global(.app-shell:has(.research-agent.standalone) .site-header),
	:global(.app-shell:has(.research-agent.standalone) .site-footer),
	:global(
		.workspace-header:has(+ .workspace-tabs + .workspace-panel .research-agent.standalone)
	),
	:global(.workspace-tabs:has(+ .workspace-panel .research-agent.standalone)) {
		display: none;
	}

	:global(.app-shell:has(.research-agent.standalone) .page) {
		width: 100vw;
		max-width: none;
		margin: 0;
	}

	:global(.workspace-panel:has(.research-agent.standalone)) {
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

	.model-picker {
		min-width: 0;
		max-width: 100%;
	}
	.model-picker summary {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		padding: 7px 8px;
		border-radius: 8px;
		color: var(--text-secondary);
		cursor: pointer;
		list-style: none;
		font-size: 13px;
	}
	.model-picker summary::-webkit-details-marker {
		display: none;
	}
	.model-picker summary:hover,
	.model-picker[open] summary {
		background: var(--bg-subtle);
		color: var(--text-primary);
	}
	.model-picker-name {
		min-width: 0;
		max-width: 180px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.model-picker summary :global(svg) {
		flex: 0 0 auto;
	}
	.model-picker .sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
		border: 0;
	}
	.model-picker-menu {
		position: absolute;
		z-index: 30;
		right: 10px;
		bottom: calc(100% + 8px);
		width: min(280px, calc(100% - 20px));
		box-sizing: border-box;
		padding: 8px;
		border: 1px solid var(--border-strong);
		border-radius: 12px;
		background: var(--surface-card);
		color: var(--text-primary);
	}
	.model-picker-options {
		display: grid;
		gap: 2px;
		max-height: 224px;
		overflow-y: auto;
	}
	.model-picker-menu button {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		padding: 9px 10px;
		border: 0;
		border-radius: 6px;
		background: transparent;
		color: inherit;
		font: inherit;
		font-size: 13px;
		text-align: left;
		cursor: pointer;
	}
	.model-picker-menu button span {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.model-picker-menu button :global(svg) {
		flex: 0 0 auto;
	}
	.model-picker-menu button:hover {
		background: var(--bg-subtle);
	}
	.model-picker-menu button[aria-pressed='true'] {
		background: var(--brand-soft);
		color: var(--brand-primary);
	}
	.model-picker-menu p {
		margin: 4px 8px 10px;
		font-size: 13px;
		line-height: 1.5;
	}
	.model-picker summary:focus-visible,
	.model-picker-menu button:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	.model-picker-menu button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}
	.status {
		width: min(calc(100% - 64px), 900px);
		margin: 12px auto 0;
		padding: 10px 12px;
		border-radius: 6px;
		font-size: 13px;
		overflow-wrap: anywhere;
	}
	.status-error {
		display: flex;
		flex-wrap: wrap;
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
	.decision-recovery {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.decision-recovery span {
		flex: 1 1 16rem;
	}
	.decision-recovery button {
		flex: 0 0 auto;
		padding: 6px 10px;
		border: 1px solid currentColor;
		border-radius: 4px;
		background: var(--surface-card);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.decision-recovery button:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}
	.decision-recovery button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
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

	.research-agent.embedded {
		position: relative;
		inset: auto;
		z-index: auto;
		grid-template-columns: minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr);
		width: 100%;
		height: 100%;
		min-height: 0;
	}
	.embedded-toolbar {
		display: flex;
		align-items: center;
		gap: 4px;
		min-height: 44px;
		padding: 0 12px;
		border-bottom: 1px solid var(--border-default);
	}
	.embedded-toolbar > span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
		color: var(--text-secondary);
	}
	.embedded-history {
		position: absolute;
		top: 44px;
		inset-inline: 12px;
		z-index: 5;
		max-height: 45%;
		overflow: auto;
		padding: 8px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		box-shadow: var(--shadow-sm);
	}
	.embedded-history button {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 8px;
		width: 100%;
		border: 0;
		padding: 10px;
		text-align: left;
		overflow-wrap: anywhere;
		color: var(--text-primary);
		background: transparent;
		cursor: pointer;
	}
	.embedded-history button.active,
	.embedded-history button:hover {
		background: var(--bg-subtle);
	}
	.embedded-history-item {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 32px;
		align-items: center;
	}
	.embedded-history .embedded-pin {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		padding: 0;
		border-radius: 6px;
		color: var(--text-tertiary);
	}
	.embedded-history .embedded-pin.pinned {
		color: var(--brand-primary);
	}
	.embedded-history .embedded-load-more {
		display: flex;
		justify-content: center;
		font-size: 12px;
		color: var(--text-secondary);
	}
	.embedded :global(.message-scroll) {
		padding-inline: 16px;
	}
	.embedded :global(.message-list) {
		padding-top: 20px;
		padding-bottom: 24px;
	}
	.embedded :global(.empty-state) {
		margin-top: 24px;
	}
	.embedded :global(.welcome-eyebrow),
	.embedded :global(.welcome-state > p:not(.welcome-eyebrow)) {
		display: none;
	}
	.embedded :global(.empty-state h3) {
		font-size: 16px;
		margin-top: 12px;
	}
	.embedded :global(.suggestions) {
		grid-template-columns: 1fr;
	}
	.embedded :global(.composer) {
		width: calc(100% - 24px);
		margin-inline: auto;
	}
	.embedded :global(.user-message > div) {
		max-width: 94%;
	}
	.paper-scope {
		padding: 8px 0;
		font-size: 12px;
	}
	.related-sources {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 0;
		font-size: 12px;
		color: var(--text-secondary);
	}
	.paper-scope summary {
		cursor: pointer;
		font-weight: 600;
		color: var(--text-secondary);
	}
	.paper-scope ul {
		list-style: none;
		padding: 0;
		margin: 4px 0 0;
		max-height: 108px;
		overflow: auto;
	}
	.paper-scope li {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.paper-scope a {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-primary);
	}
</style>
