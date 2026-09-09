<script lang="ts">
	import { onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage, isHttpStatusError } from '../../../_shared/api';
	import { authState } from '../../../_shared/auth';
	import { collections } from '../../../_shared/collections';
	import {
		createChatSession,
		branchChatMessage,
		clearPendingChatSourceContexts,
		decideChatToolCall,
		fetchChatSession,
		fetchChatTrajectory,
		appendChatProgress,
		readPendingChatSourceContexts,
		storePendingChatSourceContexts,
		streamChatMessage,
		setChatMessageFeedback,
		type ChatFeedbackInput,
		type ChatBranchOptions,
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
	import { getChatSessionActivity, type ChatSessionActivity } from './conversationPresentation';
	import IconButton from '../../../_shared/IconButton.svelte';
	import type { DocumentProfile } from '../../../_shared/documents';
	import { Plus, History, X, LoaderCircle, Clock3, CircleAlert } from '@lucide/svelte';

	export let embedded = false;
	export let selectedPapers: Pick<DocumentProfile, 'document_id' | 'title'>[] = [];
	export let onRemovePaper: (id: string) => void = () => {};
	export let sourceContextVersion = 0;
	export let onSourcesChanged: () => void = () => {};
	export let onBusyChange: (busy: boolean) => void = () => {};
	$: onBusyChange(
		loading || sending || deciding || revising || running || Boolean(recoveringCallId)
	);
	let showHistory = false;

	type StoredChatSession = {
		session_id: string;
		title: string;
		created_at: string;
		updated_at: string;
	};

	let session: ChatSession | null = null;
	let messages: ChatMessage[] = [];
	let branches: ChatBranchOptions[] = [];
	let branchDraft: ChatMessage | null = null;
	let running = false;
	let revising = false;
	let revisionRequest: { key: string; id: string } | null = null;
	let feedbackByMessage: Record<string, ChatFeedbackState> = {};
	let pendingApproval: ChatToolCall | null = null;
	let history: StoredChatSession[] = [];
	let sessionActivities: Record<string, ChatSessionActivity> = {};
	let historyTimer: ReturnType<typeof setTimeout> | undefined;
	let historyLoading = false;
	let loading = false;
	let sending = false;
	let submitting = false;
	$: sessionNavigationDisabled = loading || submitting || deciding || revising;
	let progress: ChatProgress | null = null;
	let progressHistory: ChatProgress[] = [];
	let streamingText = '';

	let deciding = false;
	let error = '';
	let notice = '';
	let input = '';
	let pendingSourceContexts: ChatSourceContext[] = [];
	let inspectRelated = embedded;
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
		clearTimeout(historyTimer);
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
	$: if (sourceContextVersion && userId && collectionId) {
		refreshPendingSources();
	}
	$: collectionName = userId
		? ($collections.find((item) => item.id === collectionId)?.name?.trim() ?? '')
		: '';
	$: conversationTitle =
		messages
			.find((message) => message.role === 'user')
			?.content.trim()
			.split('\n')[0] ?? '';

	$: queryObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
	$: activeSessionId = session?.session_id ?? '';
	$: if (browser && (collectionId !== loadedCollectionId || userId !== loadedUserId)) {
		sessionActivities = {};
		loadedCollectionId = collectionId;
		loadedUserId = userId;
		void loadSession();
	}
	$: if (session && !loading) {
		sessionActivities = {
			...sessionActivities,
			[session.session_id]: recoveryError
				? 'unavailable'
				: getChatSessionActivity(
						messages,
						sending || running,
						pendingApproval?.tool_call_id ?? null
					)
		};
	}

	function sessionStorageKey() {
		return `lens.chatSession.${encodeURIComponent(userId)}:${encodeURIComponent(collectionId)}${embedded ? ':documents' : ''}`;
	}

	function refreshPendingSources() {
		pendingSourceContexts = readPendingChatSourceContexts(
			userId,
			collectionId,
			session ? { sessionId: session.session_id, messages } : undefined
		);
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
		const stored = readHistory();
		const previous = stored.find((item) => item.session_id === nextSession.session_id);
		const existing = stored.filter((item) => item.session_id !== nextSession.session_id);
		writeHistory([
			{
				session_id: nextSession.session_id,
				title:
					title ||
					(messages.some((message) => message.role === 'user')
						? titleFromMessages(messages)
						: previous?.title || $t('researchAgent.untitledSession')),
				created_at: nextSession.created_at,
				updated_at: nextSession.updated_at
			},
			...existing
		]);
	}

	async function refreshHistoryActivities(all = false) {
		if (!session || loading || historyLoading || destroyed) return;
		const generation = sessionGeneration;
		const ownerCollectionId = collectionId;
		clearTimeout(historyTimer);
		historyLoading = true;
		history = readHistory();
		const candidates = history.filter(
			(item) =>
				item.session_id !== session?.session_id &&
				(all ||
					['running', 'approval', 'recovering', 'unavailable'].includes(
						sessionActivities[item.session_id]
					))
		);
		await Promise.all(
			candidates.map(async (item) => {
				let activity: ChatSessionActivity;
				try {
					const trajectory = await fetchChatTrajectory(item.session_id, sessionController?.signal);
					activity = getChatSessionActivity(
						trajectory.items,
						trajectory.running ?? false,
						trajectory.pending_approval?.tool_call_id ?? null
					);
				} catch {
					activity = 'unavailable';
				}
				if (
					!isCurrentSession(generation, ownerCollectionId) ||
					item.session_id === session?.session_id
				)
					return;
				sessionActivities = { ...sessionActivities, [item.session_id]: activity };
			})
		);
		if (!isCurrentSession(generation, ownerCollectionId)) return;
		historyLoading = false;
		if (
			history.some(
				(item) =>
					item.session_id !== session?.session_id &&
					['running', 'approval', 'recovering', 'unavailable'].includes(
						sessionActivities[item.session_id]
					)
			)
		) {
			historyTimer = setTimeout(() => void refreshHistoryActivities(), 5000);
		}
	}

	async function loadSession(requestedSessionId = '') {
		const activeCollectionId = collectionId;
		const generation = ++sessionGeneration;
		clearTimeout(recoveryTimer);
		clearTimeout(historyTimer);
		historyLoading = false;
		recoveringCallId = null;
		recoveryLoading = false;
		recoveryError = '';
		sessionController?.abort();
		sessionController = null;
		session = null;
		messages = [];
		feedbackByMessage = {};
		branches = [];
		branchDraft = null;
		running = false;
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
		pendingApproval = null;
		progress = null;
		pendingSourceContexts = [];
		history = [];
		if (!userId || !activeCollectionId) return;

		const controller = new AbortController();
		sessionController = controller;
		loading = true;
		pendingSourceContexts = readPendingChatSourceContexts(userId, activeCollectionId);
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
					writeHistory(readHistory().filter((item) => item.session_id !== storedSessionId));
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
				branches = trajectory.branches ?? [];
				branchDraft = trajectory.branch_draft ?? null;
				running = trajectory.running ?? false;
				loadFeedback(trajectory.feedback);
				pendingApproval = trajectory.pending_approval;
			}
			session = nextSession;
			refreshPendingSources();
			onSourcesChanged();
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
			if (isCurrentSession(generation, activeCollectionId)) {
				loading = false;
				void refreshHistoryActivities(true);
			}
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
		if ((recoveringCallId || running) && !destroyed) {
			recoveryTimer = setTimeout(() => void refreshRecovery(), 3000);
		}
	}

	async function refreshRecovery() {
		if (!session || (!recoveringCallId && !running) || recoveryLoading) return;
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
			branches = trajectory.branches ?? [];
			branchDraft = trajectory.branch_draft ?? null;
			running = trajectory.running ?? false;
			loadFeedback(trajectory.feedback);
			pendingApproval = trajectory.pending_approval;
			recoveryError = '';
			error = '';
			failedSessionId = null;
			session = {
				...activeSession,
				updated_at: messages.at(-1)?.created_at ?? activeSession.updated_at
			};
			refreshPendingSources();
			onSourcesChanged();
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
		if (sessionNavigationDisabled) return;
		clearStoredSessionId();
		session = null;
		messages = [];
		pendingApproval = null;
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
		await loadSession(sessionId);
		if (preserveDraft && userId === owner && activeSessionId === sessionId) input = draft;
	}

	async function reviseMessage(message: ChatMessage, content?: string): Promise<boolean> {
		if (
			!session ||
			loading ||
			sending ||
			deciding ||
			revising ||
			running ||
			pendingApproval ||
			recoveringCallId
		)
			return false;
		const ownerCollectionId = collectionId;
		let generation = sessionGeneration;
		const key = JSON.stringify([session.session_id, message.message_id, content]);
		if (revisionRequest?.key !== key) {
			const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
				byte.toString(16).padStart(2, '0')
			).join('');
			revisionRequest = { key, id };
		}
		revising = true;
		error = '';
		try {
			const branch = await branchChatMessage(
				session.session_id,
				message.message_id,
				revisionRequest.id,
				content,
				sessionController?.signal
			);
			if (!isCurrentSession(generation, ownerCollectionId)) return false;
			const trajectory = await fetchChatTrajectory(branch.session_id, sessionController?.signal);
			if (!isCurrentSession(generation, ownerCollectionId)) return false;
			clearTimeout(recoveryTimer);
			sessionController?.abort();
			sessionController = new AbortController();
			generation = ++sessionGeneration;
			session = branch;
			messages = trajectory.items;
			feedbackByMessage = {};
			loadFeedback(trajectory.feedback);
			branches = trajectory.branches ?? [];
			branchDraft = trajectory.branch_draft ?? null;
			running = trajectory.running ?? false;
			pendingApproval = trajectory.pending_approval;
			storeSessionId(branch.session_id);
			upsertHistory(branch, content ?? message.content);
			revising = false;
			revisionRequest = null;
			scheduleRecovery();
			// A repeated create request may find a branch whose question already ran.
			if (branchDraft && !running)
				await sendMessage(branchDraft.content, branchDraft.source_contexts);
			return true;
		} catch (err) {
			if (isCurrentSession(generation, ownerCollectionId)) error = errorMessage(err);
			return false;
		} finally {
			if (isCurrentSession(generation, ownerCollectionId)) revising = false;
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
			recoveringCallId
		)
			return;
		const isRevision = revisionSources !== undefined;
		const paperLinks = (isRevision ? [] : selectedPapers).map((paper) => {
			const title = (paper.title || $t('collection.unknownName')).replace(/[\\[\]`*_\n\r]/g, ' ');
			return `- [${title}](/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(paper.document_id)})`;
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
		const sourceContexts = revisionSources ?? [...pendingSourceContexts];
		if (!isRevision && sourceContexts.length) {
			storePendingChatSourceContexts(userId, activeCollectionId, sourceContexts, {
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
		if (!isRevision) input = '';
		sending = true;
		submitting = true;
		progress = { phase: 'starting', cycle_index: 0, elapsed_ms: 0 };
		progressHistory = [progress];

		error = '';
		notice = '';
		const acknowledgeSubmission = () => {
			if (!submitting) return;
			submitting = false;
			upsertHistory(activeSession);
		};
		try {
			const turn = await streamChatMessage(
				activeSession.session_id,
				text,
				(content) => {
					if (!isCurrentSession(generation, activeCollectionId)) return;
					acknowledgeSubmission();
					pendingText += content;
					if (!textFrame) textFrame = requestAnimationFrame(flushText);
				},
				sourceContexts,
				(nextProgress) => {
					if (!isCurrentSession(generation, activeCollectionId)) return;
					acknowledgeSubmission();
					progress = nextProgress;
					progressHistory = appendChatProgress(progressHistory, nextProgress);
				},
				signal,
				isRevision
			);
			if (!isCurrentSession(generation, activeCollectionId)) return;
			cancelTextFrame();
			flushText();
			applyTurn(turn, [optimisticId, streamingId]);
			branchDraft = null;
			if (!isRevision && sourceContexts.length) {
				clearPendingChatSourceContexts(userId, activeCollectionId);
				pendingSourceContexts = [];
				onSourcesChanged();
			}
		} catch (err) {
			if (!isCurrentSession(generation, activeCollectionId)) return;
			try {
				const trajectory = await fetchChatTrajectory(activeSession.session_id, signal);
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = trajectory.items;
				branches = trajectory.branches ?? [];
				branchDraft = trajectory.branch_draft ?? null;
				running = trajectory.running ?? false;
				pendingApproval = trajectory.pending_approval;
				const persistedMessage = messages
					.slice(previousMessageCount)
					.find((message) => message.role === 'user' && message.content === text);
				if (!persistedMessage && !isRevision) {
					input = draft;
				}
				pendingSourceContexts = readPendingChatSourceContexts(userId, activeCollectionId, {
					sessionId: activeSession.session_id,
					messages
				});
				onSourcesChanged();
				scheduleRecovery();
			} catch {
				if (!isCurrentSession(generation, activeCollectionId)) return;
				messages = messages.filter(
					(message) => ![optimisticId, streamingId].includes(message.message_id)
				);
				if (!isRevision) input = draft;
			}
			error = errorMessage(err);
		} finally {
			cancelTextFrame();
			signal?.removeEventListener('abort', cancelTextFrame);
			if (isCurrentSession(generation, activeCollectionId)) {
				sending = false;
				submitting = false;
				progress = null;
				progressHistory = [];
				if (isRevision) {
					try {
						const trajectory = await fetchChatTrajectory(activeSession.session_id, signal);
						if (!isCurrentSession(generation, activeCollectionId)) return;
						branches = trajectory.branches ?? [];
						branchDraft = trajectory.branch_draft ?? null;
						running = trajectory.running ?? false;
						scheduleRecovery();
					} catch (err) {
						if (isCurrentSession(generation, activeCollectionId)) error = errorMessage(err);
					}
				}
			}
		}
	}

	function handleComposerInput(value: string) {
		input = value;
	}

	function removePendingSourceContexts(index: number) {
		pendingSourceContexts = pendingSourceContexts.filter((_, candidate) => candidate !== index);
		storePendingChatSourceContexts(userId, collectionId, pendingSourceContexts);
		onSourcesChanged();
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

<svelte:window
	on:focus={() => void refreshHistoryActivities(true)}
	on:storage={(event) => {
		if (event.key === historyStorageKey()) void refreshHistoryActivities(true);
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
			{collectionId}
			{collectionName}
			{history}
			{sessionActivities}
			{activeSessionId}
			disabled={sessionNavigationDisabled}
			onNewSession={startNewSession}
			onSwitchSession={switchSession}
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
						if (showHistory) void refreshHistoryActivities(true);
					}}><History size={16} /></IconButton
				>
				<span title={conversationTitle}
					>{conversationTitle || $t('researchAgent.untitledSession')}</span
				>
			</div>
			{#if showHistory}
				<nav class="embedded-history" aria-label={$t('researchAgent.historyTitle')}>
					{#each history as item (item.session_id)}
						{@const activity = sessionActivities[item.session_id]}
						<button
							type="button"
							class:active={item.session_id === activeSessionId}
							disabled={sessionNavigationDisabled}
							on:click={() => {
								void switchSession(item.session_id);
								showHistory = false;
							}}
							><span class="embedded-history-title">{item.title}</span>
							{#if activity && activity !== 'idle'}
								<span class="session-state" data-state={activity}>
									{#if activity === 'running'}<LoaderCircle
											size={12}
										/>{:else if activity === 'unavailable'}<CircleAlert size={12} />{:else}<Clock3
											size={12}
										/>{/if}
									<span>{$t(`researchAgent.sessionState.${activity}`)}</span>
								</span>
							{/if}
						</button>
					{/each}
				</nav>
			{/if}
		{:else if conversationTitle || queryObjectiveId}
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
			{branches}
			{running}
			revisionDisabled={revising}
			onRevise={reviseMessage}
			onSwitchVersion={(id) => switchSession(id, true)}
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
			ready={Boolean(session) && !branchDraft}
			onSend={sendMessage}
			{decide}
		/>
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
						Boolean(recoveringCallId)}
					on:click={() =>
						branchDraft && sendMessage(branchDraft.content, branchDraft.source_contexts)}
					>{$t('researchAgent.revision.resume')}</button
				>
			</div>
		{/if}

		{#key userId}
			<MessageComposer
				{collectionId}
				{input}
				{sending}
				disabled={!session ||
					loading ||
					revising ||
					running ||
					Boolean(branchDraft) ||
					sending ||
					deciding ||
					Boolean(pendingApproval) ||
					Boolean(recoveringCallId)}
				{pendingSourceContexts}
				hasExtraContext={selectedPapers.length > 0}
				onInput={handleComposerInput}
				onSend={sendMessage}
				onRemovePendingSourceContexts={removePendingSourceContexts}
			>
				{#if pendingSourceContexts.length}
					<label class="related-sources"
						><input
							type="checkbox"
							bind:checked={inspectRelated}
							disabled={sending || deciding}
						/>{$t('researchAgent.paperScope.related')}</label
					>
				{/if}
				{#if selectedPapers.length}
					<details class="paper-scope" open data-testid="selected-paper-context">
						<summary
							>{$t('researchAgent.paperScope.selected', { count: selectedPapers.length })}</summary
						>
						<ul>
							{#each selectedPapers as paper (paper.document_id)}
								<li>
									<a
										href={`/collections/${collectionId}/documents/${paper.document_id}`}
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

<style>
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
	:global(.app-shell:has(.research-agent.standalone) .bg-grid),
	:global(
		.collection-header:has(+ .collection-tabs + .collection-panel .research-agent.standalone)
	),
	:global(.collection-tabs:has(+ .collection-panel .research-agent.standalone)) {
		display: none;
	}

	:global(.app-shell:has(.research-agent.standalone) .page) {
		width: 100vw;
		max-width: none;
		margin: 0;
	}

	:global(.collection-panel:has(.research-agent.standalone)) {
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
