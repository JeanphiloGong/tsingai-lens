<script lang="ts">
	import { browser } from '$app/environment';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		createChatSession,
		decideChatToolCall,
		fetchChatSession,
		fetchChatTrajectory,
		postChatMessage,
		type ChatMessage,
		type ChatResourceRef,
		type ChatSession,
		type ChatToolCall,
		type ChatTurn
	} from '../../../_shared/chatSessions';
	import { t } from '../../../_shared/i18n';

	type StoredChatSession = {
		session_id: string;
		title: string;
		created_at: string;
		updated_at: string;
	};

	type InlineSegment = {
		text: string;
		strong: boolean;
	};

	type RenderBlock =
		| { kind: 'paragraph'; segments: InlineSegment[] }
		| { kind: 'list'; items: InlineSegment[][] };

	const suggestionKeys = [
		'researchAgent.suggestions.greeting',
		'researchAgent.suggestions.overview',
		'researchAgent.suggestions.findings',
		'researchAgent.suggestions.objectives'
	];

	let session: ChatSession | null = null;
	let messages: ChatMessage[] = [];
	let pendingApproval: ChatToolCall | null = null;
	let history: StoredChatSession[] = [];
	let loading = false;
	let sending = false;
	let deciding = false;
	let error = '';
	let notice = '';
	let input = '';
	let loadedCollectionId = '';

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
		loading = true;
		error = '';
		notice = '';
		pendingApproval = null;
		if (!requestedSessionId) clearLegacySessionStorage();
		history = readHistory();

		try {
			const storedSessionId = requestedSessionId || readStoredSessionId();
			let nextSession: ChatSession | null = null;
			if (storedSessionId) {
				try {
					nextSession = await fetchChatSession(storedSessionId);
					if (nextSession.collection_id !== activeCollectionId) nextSession = null;
				} catch {
					nextSession = null;
					clearStoredSessionId();
					writeHistory(history.filter((item) => item.session_id !== storedSessionId));
				}
			}

			if (activeCollectionId !== collectionId) return;
			if (nextSession === null) {
				nextSession = await createChatSession(activeCollectionId);
				messages = [];
			} else {
				const trajectory = await fetchChatTrajectory(nextSession.session_id);
				messages = trajectory.items;
				pendingApproval = trajectory.pending_approval;
			}
			session = nextSession;
			storeSessionId(nextSession.session_id);
			upsertHistory(nextSession);
		} catch (err) {
			error = errorMessage(err);
			session = null;
			messages = [];
			pendingApproval = null;
		} finally {
			loading = false;
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
		const optimisticId = `local-${Date.now()}`;
		const optimisticMessage: ChatMessage = {
			message_id: optimisticId,
			session_id: activeSession.session_id,
			role: 'user',
			content: text,
			created_at: new Date().toISOString(),
			tool_call_id: null,
			tool_name: null,
			tool_arguments: null,
			tool_result: null
		};
		messages = [...messages, optimisticMessage];
		input = '';
		sending = true;
		error = '';
		notice = '';
		try {
			const turn = await postChatMessage(activeSession.session_id, text);
			applyTurn(turn, optimisticId);
		} catch (err) {
			messages = messages.filter((message) => message.message_id !== optimisticId);
			input = text;
			error = errorMessage(err);
		} finally {
			sending = false;
		}
	}

	function applyTurn(turn: ChatTurn, optimisticId = '') {
		const prior = optimisticId
			? messages.filter((message) => message.message_id !== optimisticId)
			: messages;
		const knownIds = new Set(prior.map((message) => message.message_id));
		messages = [...prior, ...turn.messages.filter((message) => !knownIds.has(message.message_id))];
		pendingApproval = turn.pending_approval;
		if (turn.status === 'rejected') notice = $t('researchAgent.rejected');
		if (turn.status === 'failed' || turn.status === 'step_limit_reached') {
			error = $t('researchAgent.turnFailed', { code: turn.error_code ?? turn.status });
		}
		if (session) {
			const updatedAt = turn.messages.at(-1)?.created_at ?? session.updated_at;
			session = { ...session, updated_at: updatedAt };
			upsertHistory(session, titleFromMessages(messages));
		}
	}

	async function decide(decision: 'approved' | 'rejected') {
		if (!session || !pendingApproval || deciding) return;
		const call = pendingApproval;
		deciding = true;
		error = '';
		notice = '';
		try {
			const turn = await decideChatToolCall(session.session_id, call, decision);
			applyTurn(turn);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			deciding = false;
		}
	}

	function askSuggestion(key: string) {
		void sendMessage($t(key));
	}

	function renderInlineMarkdown(text: string): InlineSegment[] {
		const segments: InlineSegment[] = [];
		const pattern = /\*\*([^*]+)\*\*/g;
		let lastIndex = 0;
		let match: RegExpExecArray | null;
		while ((match = pattern.exec(text)) !== null) {
			if (match.index > lastIndex) {
				segments.push({ text: text.slice(lastIndex, match.index), strong: false });
			}
			segments.push({ text: match[1], strong: true });
			lastIndex = match.index + match[0].length;
		}
		if (lastIndex < text.length) {
			segments.push({ text: text.slice(lastIndex), strong: false });
		}
		return segments.length ? segments : [{ text, strong: false }];
	}

	function renderMessageBlocks(text: string): RenderBlock[] {
		return text
			.split(/\n{2,}/)
			.map((block) => block.trim())
			.filter(Boolean)
			.map((block) => {
				const lines = block
					.split('\n')
					.map((line) => line.trim())
					.filter(Boolean);
				const items = lines
					.map((line) => line.match(/^(?:[-*]\s+|\d+\.\s+)(.+)$/))
					.filter((match): match is RegExpMatchArray => Boolean(match));
				if (items.length === lines.length) {
					return {
						kind: 'list' as const,
						items: items.map((item) => renderInlineMarkdown(item[1].trim()))
					};
				}
				return {
					kind: 'paragraph' as const,
					segments: renderInlineMarkdown(lines.join(' '))
				};
			});
	}

	function capabilityName(toolName: string | null) {
		switch (toolName) {
			case 'get_collection_context':
				return $t('researchAgent.capability.collection');
			case 'query_published_findings':
				return $t('researchAgent.capability.findings');
			case 'propose_objective_drafts':
				return $t('researchAgent.capability.proposals');
			case 'create_objective_candidate':
				return $t('researchAgent.capability.createObjective');
			default:
				return $t('researchAgent.capability.unknown');
		}
	}

	function resultToolName(message: ChatMessage) {
		if (!message.tool_call_id) return null;
		return (
			messages.find(
				(candidate) =>
					candidate.role === 'assistant' && candidate.tool_call_id === message.tool_call_id
			)?.tool_name ?? null
		);
	}

	function numberValue(data: Record<string, unknown>, key: string) {
		const value = data[key];
		return typeof value === 'number' ? value : 0;
	}

	function resultSummary(message: ChatMessage) {
		const result = message.tool_result;
		if (!result) return '';
		const name = resultToolName(message);
		if (result.status === 'failed') {
			return (
				result.error_message ||
				$t('researchAgent.capability.failed', { name: capabilityName(name) })
			);
		}
		if (result.status === 'queued') {
			return $t('researchAgent.capability.queuedDescription');
		}
		if (name === 'get_collection_context') {
			const collection = result.data.collection;
			const papers =
				collection && typeof collection === 'object' && 'paper_count' in collection
					? Number(collection.paper_count) || 0
					: 0;
			return $t('researchAgent.capability.paperCount', {
				papers,
				objectives: numberValue(result.data, 'objective_count')
			});
		}
		if (name === 'query_published_findings') {
			if (result.data.scientific_absence === true) return $t('researchAgent.capability.absence');
			return $t('researchAgent.capability.findingCount', {
				findings: numberValue(result.data, 'finding_count'),
				evidence: numberValue(result.data, 'evidence_count')
			});
		}
		if (name === 'propose_objective_drafts') {
			return $t('researchAgent.capability.draftCount', {
				count: numberValue(result.data, 'draft_count')
			});
		}
		if (name === 'create_objective_candidate') {
			return $t('researchAgent.capability.objectiveCreated');
		}
		return $t('researchAgent.capability.succeeded', { name: capabilityName(name) });
	}

	function resultTitle(message: ChatMessage) {
		const result = message.tool_result;
		const name = capabilityName(resultToolName(message));
		if (result?.status === 'failed') return $t('researchAgent.capability.failed', { name });
		if (result?.status === 'queued') return $t('researchAgent.capability.queued', { name });
		return $t('researchAgent.capability.succeeded', { name });
	}

	function resultDrafts(message: ChatMessage) {
		const drafts = message.tool_result?.data.drafts;
		return Array.isArray(drafts)
			? drafts.filter((item): item is Record<string, unknown> =>
					Boolean(item && typeof item === 'object')
				)
			: [];
	}

	function draftList(draft: Record<string, unknown>, key: string) {
		const value = draft[key];
		return Array.isArray(value) ? value.map(String).filter(Boolean).join(', ') : '';
	}

	function visibleResources(message: ChatMessage) {
		return (message.tool_result?.resource_refs ?? []).filter(
			(ref): ref is ChatResourceRef & { href: `/collections/${string}` } =>
				typeof ref.href === 'string' && ref.href.startsWith('/collections/')
		);
	}

	function resourceLabel(resourceType: string) {
		switch (resourceType) {
			case 'collection':
				return $t('researchAgent.resource.collection');
			case 'research_objective':
				return $t('researchAgent.resource.objective');
			case 'finding':
				return $t('researchAgent.resource.finding');
			case 'evidence':
				return $t('researchAgent.resource.evidence');
			case 'objective_analysis':
				return $t('researchAgent.resource.analysis');
			default:
				return $t('researchAgent.resource.other');
		}
	}

	function approvalArguments(call: ChatToolCall) {
		return Object.entries(call.arguments);
	}

	function formatValue(value: unknown) {
		if (Array.isArray(value)) return value.map(String).join(', ');
		if (value && typeof value === 'object') return JSON.stringify(value);
		if (value === null || value === undefined || value === '') return '--';
		return String(value);
	}

	function formatTime(value: string) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date);
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
	<aside class="sidebar" aria-label={$t('researchAgent.sidebarLabel')}>
		<div class="brand">
			<span class="brand-mark" aria-hidden="true">L</span>
			<h1>{$t('researchAgent.title')}</h1>
		</div>

		<button
			class="new-session"
			type="button"
			disabled={loading || sending || deciding}
			on:click={startNewSession}
		>
			<span aria-hidden="true">+</span>
			{$t('researchAgent.newSession')}
		</button>

		<section class="history" aria-label={$t('researchAgent.historyTitle')}>
			<h2>{$t('researchAgent.historyTitle')}</h2>
			<div class="history-list">
				{#each history as item (item.session_id)}
					<button
						class="history-item"
						class:active={item.session_id === activeSessionId}
						type="button"
						disabled={loading || sending || deciding}
						on:click={() => switchSession(item.session_id)}
					>
						<span class="history-title">{item.title}</span>
						<time>{formatHistoryTime(item.updated_at)}</time>
					</button>
				{:else}
					<p class="empty-history">{$t('researchAgent.emptyHistory')}</p>
				{/each}
			</div>
		</section>

		<a class="collection-link" href={resolve('/collections/[id]', { id: collectionId })}>
			<span>
				<small>{$t('researchAgent.currentCollection')}</small>
				<strong>{collectionId}</strong>
			</span>
			<span>{$t('researchAgent.openWorkspace')}</span>
		</a>
	</aside>

	<main class="conversation">
		<header class="conversation-header">
			<div>
				<h2>{$t('researchAgent.title')}</h2>
				<p>{$t('researchAgent.headerPrefix')} <strong>{collectionId}</strong></p>
			</div>
			{#if queryObjectiveId}
				<a
					class="objective-link"
					href={resolve('/collections/[id]/objectives/[objective_id]', {
						id: collectionId,
						objective_id: queryObjectiveId
					})}
				>
					{$t('researchAgent.objectiveScope')}
				</a>
			{/if}
		</header>

		{#if error}
			<div class="status status-error" role="alert">{error}</div>
		{/if}
		{#if notice}
			<div class="status status-notice" role="status">{notice}</div>
		{/if}

		<div class="message-scroll" aria-live="polite" aria-busy={loading || sending || deciding}>
			<div class="message-list">
				{#if loading}
					<div class="empty-state" role="status">
						<h3>{$t('researchAgent.loading')}</h3>
					</div>
				{:else if messages.length === 0}
					<div class="empty-state">
						<h3>{$t('researchAgent.emptyTitle')}</h3>
						<p>{$t('researchAgent.emptyBody')}</p>
						<div class="suggestions">
							{#each suggestionKeys as key (key)}
								<button
									type="button"
									disabled={!session || sending}
									on:click={() => askSuggestion(key)}
								>
									{$t(key)}
								</button>
							{/each}
						</div>
					</div>
				{:else}
					{#each messages as message (message.message_id)}
						{#if message.role === 'user'}
							<article class="user-message">
								<div>
									<time>{formatTime(message.created_at)}</time>
									<p>{message.content}</p>
								</div>
							</article>
						{:else if message.role === 'assistant'}
							<article class="assistant-message">
								<div class="assistant-mark" aria-hidden="true">AI</div>
								<div class="assistant-content">
									<time>{formatTime(message.created_at)}</time>
									{#if message.content}
										<div class="assistant-copy">
											{#each renderMessageBlocks(message.content) as block, blockIndex (blockIndex)}
												{#if block.kind === 'list'}
													<ul>
														{#each block.items as item, itemIndex (itemIndex)}
															<li>
																{#each item as segment, segmentIndex (segmentIndex)}
																	{#if segment.strong}<strong>{segment.text}</strong
																		>{:else}{segment.text}{/if}
																{/each}
															</li>
														{/each}
													</ul>
												{:else}
													<p>
														{#each block.segments as segment, segmentIndex (segmentIndex)}
															{#if segment.strong}<strong>{segment.text}</strong
																>{:else}{segment.text}{/if}
														{/each}
													</p>
												{/if}
											{/each}
										</div>
									{/if}
									{#if message.tool_call_id}
										<p class="capability-request">
											{$t('researchAgent.capability.requested', {
												name: capabilityName(message.tool_name)
											})}
										</p>
									{/if}
								</div>
							</article>
						{:else if message.tool_result}
							<section
								class="capability-event"
								aria-label={$t('researchAgent.capability.activity')}
							>
								<header>
									<span
										class:failed={message.tool_result.status === 'failed'}
										class:queued={message.tool_result.status === 'queued'}
									>
										{message.tool_result.status === 'failed'
											? '!'
											: message.tool_result.status === 'queued'
												? '…'
												: '✓'}
									</span>
									<div>
										<strong>{resultTitle(message)}</strong>
										<p>{resultSummary(message)}</p>
									</div>
								</header>

								{#if resultDrafts(message).length}
									<ol class="draft-list">
										{#each resultDrafts(message) as draft, draftIndex (`${String(draft.question ?? '')}-${draftIndex}`)}
											<li>
												<strong>{String(draft.question ?? '')}</strong>
												<p>{draftList(draft, 'variables')} → {draftList(draft, 'outcomes')}</p>
												<small>
													{$t('researchAgent.capability.draftSupport', {
														status: String(draft.support_status ?? 'unknown')
													})}
												</small>
											</li>
										{/each}
									</ol>
								{/if}

								{#if message.tool_result.warnings.length}
									<div class="warnings">
										<strong>{$t('researchAgent.warnings')}</strong>
										<ul>
											{#each message.tool_result.warnings as warning, warningIndex (warningIndex)}<li
												>
													{warning}
												</li>{/each}
										</ul>
									</div>
								{/if}

								{#if visibleResources(message).length}
									<nav class="resource-links" aria-label={$t('researchAgent.resources')}>
										{#each visibleResources(message) as resource (`${resource.resource_type}:${resource.resource_id}`)}
											<a href={resolve(resource.href)}>{resourceLabel(resource.resource_type)}</a>
										{/each}
									</nav>
								{/if}
							</section>
						{/if}
					{/each}
				{/if}

				{#if pendingApproval}
					<section class="approval" aria-labelledby="approval-title">
						<header>
							<div>
								<h3 id="approval-title">{$t('researchAgent.approval.title')}</h3>
								<p>{$t('researchAgent.approval.body')}</p>
							</div>
							<strong>{capabilityName(pendingApproval.name)}</strong>
						</header>
						<h4>{$t('researchAgent.approval.arguments')}</h4>
						<dl>
							{#each approvalArguments(pendingApproval) as [key, value] (key)}
								<div>
									<dt>{key.replaceAll('_', ' ')}</dt>
									<dd>{formatValue(value)}</dd>
								</div>
							{/each}
						</dl>
						<div class="approval-actions">
							<button
								class="reject"
								type="button"
								disabled={deciding}
								on:click={() => decide('rejected')}
							>
								{$t('researchAgent.approval.reject')}
							</button>
							<button
								class="approve"
								type="button"
								disabled={deciding}
								on:click={() => decide('approved')}
							>
								{deciding
									? $t('researchAgent.approval.processing')
									: $t('researchAgent.approval.approve')}
							</button>
						</div>
					</section>
				{/if}
			</div>
		</div>

		<form class="composer" on:submit|preventDefault={() => sendMessage()}>
			<label class="sr-only" for="research-agent-message">{$t('researchAgent.messageLabel')}</label>
			<textarea
				id="research-agent-message"
				rows="2"
				bind:value={input}
				placeholder={$t('researchAgent.messagePlaceholder')}
				disabled={!session || sending || deciding || Boolean(pendingApproval)}
			></textarea>
			<button
				type="submit"
				disabled={!session || sending || deciding || Boolean(pendingApproval) || !input.trim()}
			>
				{sending ? $t('researchAgent.sending') : $t('researchAgent.send')}
			</button>
		</form>
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
		grid-template-columns: 280px minmax(0, 1fr);
		width: 100vw;
		height: 100vh;
		height: 100dvh;
		background: var(--bg-page);
		color: var(--text-primary);
		letter-spacing: 0;
		overflow: hidden;
	}

	.sidebar {
		display: flex;
		min-height: 0;
		flex-direction: column;
		padding: 24px 20px;
		border-right: 1px solid var(--border-default);
		background: var(--bg-subtle);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.brand-mark,
	.assistant-mark {
		display: grid;
		place-items: center;
		background: var(--surface-card);
		border: 1px solid var(--brand-border);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.brand-mark {
		width: 36px;
		height: 36px;
		border-radius: 6px;
	}

	.brand h1 {
		margin: 0;
		font-size: 18px;
		line-height: 24px;
	}

	.new-session {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		min-height: 42px;
		margin-top: 24px;
		border: 1px solid var(--brand-primary);
		border-radius: 6px;
		background: var(--brand-primary);
		color: #fff;
		font-weight: 700;
		cursor: pointer;
	}

	.new-session:hover:not(:disabled),
	.approve:hover:not(:disabled),
	.composer button:hover:not(:disabled) {
		background: var(--brand-primary-hover);
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.history {
		display: flex;
		min-height: 0;
		flex: 1;
		flex-direction: column;
		margin-top: 32px;
	}

	.history h2 {
		margin: 0 0 10px;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		text-transform: uppercase;
	}

	.history-list {
		display: grid;
		gap: 4px;
		overflow-y: auto;
	}

	.history-item {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 8px;
		min-height: 42px;
		padding: 8px 10px;
		border: 1px solid transparent;
		border-radius: 6px;
		background: transparent;
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
	}

	.history-item:hover,
	.history-item.active {
		border-color: var(--brand-border);
		background: var(--surface-card);
	}

	.history-title {
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		font-size: 13px;
	}

	.history-item time,
	.empty-history {
		color: var(--text-tertiary);
		font-size: 11px;
	}

	.collection-link {
		display: grid;
		gap: 10px;
		padding-top: 16px;
		border-top: 1px solid var(--border-default);
		color: var(--brand-primary);
		font-size: 12px;
		font-weight: 700;
		text-decoration: none;
	}

	.collection-link span:first-child {
		display: grid;
		gap: 2px;
		min-width: 0;
	}

	.collection-link small {
		color: var(--text-secondary);
		font-weight: 500;
	}

	.collection-link strong {
		overflow: hidden;
		color: var(--text-primary);
		text-overflow: ellipsis;
	}

	.conversation {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		background: var(--surface-card);
	}

	.conversation-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		min-height: 76px;
		padding: 16px 32px;
		border-bottom: 1px solid var(--border-default);
	}

	.conversation-header h2 {
		margin: 0;
		font-size: 18px;
		line-height: 26px;
	}

	.conversation-header p {
		margin: 3px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.objective-link,
	.resource-links a {
		color: var(--brand-primary);
		font-weight: 700;
		text-decoration: none;
	}

	.objective-link:hover,
	.resource-links a:hover {
		text-decoration: underline;
	}

	.status {
		margin: 12px 32px 0;
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

	.message-scroll {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 28px 32px;
	}

	.message-list {
		width: min(100%, 900px);
		margin: 0 auto;
	}

	.empty-state {
		max-width: 620px;
		margin: 100px auto 0;
		text-align: center;
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

	.user-message {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 24px;
	}

	.user-message > div {
		max-width: min(72%, 620px);
	}

	.user-message time,
	.assistant-content > time {
		display: block;
		margin-bottom: 5px;
		color: var(--text-tertiary);
		font-size: 11px;
	}

	.user-message time {
		text-align: right;
	}

	.user-message p {
		margin: 0;
		padding: 12px 15px;
		border-radius: 8px 8px 2px 8px;
		background: var(--brand-soft);
		font-size: 14px;
		line-height: 22px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.assistant-message {
		display: grid;
		grid-template-columns: 36px minmax(0, 1fr);
		gap: 12px;
		margin-bottom: 18px;
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

	.assistant-copy {
		padding: 14px 16px;
		border: 1px solid var(--border-default);
		border-radius: 8px;
		background: var(--surface-card);
		font-size: 14px;
		line-height: 23px;
		overflow-wrap: anywhere;
	}

	.assistant-copy p,
	.assistant-copy ul {
		margin: 0 0 9px;
	}

	.assistant-copy p:last-child,
	.assistant-copy ul:last-child {
		margin-bottom: 0;
	}

	.capability-request {
		margin: 7px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.capability-event {
		margin: 0 0 22px 48px;
		padding: 14px 16px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--bg-subtle);
	}

	.capability-event > header {
		display: flex;
		align-items: flex-start;
		gap: 10px;
	}

	.capability-event > header > span {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--success-bg);
		color: var(--success-text);
		font-size: 12px;
		font-weight: 800;
	}

	.capability-event > header > span.failed {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.capability-event > header > span.queued {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.capability-event header strong {
		font-size: 13px;
	}

	.capability-event header p {
		margin: 2px 0 0;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.draft-list {
		display: grid;
		gap: 8px;
		margin: 14px 0 0;
		padding: 0;
		list-style: none;
		counter-reset: drafts;
	}

	.draft-list li {
		padding-top: 8px;
		border-top: 1px solid var(--border-default);
		counter-increment: drafts;
	}

	.draft-list li > strong::before {
		content: counter(drafts) '. ';
	}

	.draft-list p,
	.draft-list small {
		margin: 4px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.warnings {
		margin-top: 12px;
		padding: 10px 12px;
		border-left: 3px solid var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
		font-size: 12px;
	}

	.warnings ul {
		margin: 5px 0 0;
		padding-left: 18px;
	}

	.resource-links {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 14px;
		margin-top: 12px;
		font-size: 12px;
	}

	.approval {
		margin: 8px 0 24px 48px;
		padding: 18px;
		border: 1px solid var(--warning-border);
		border-radius: 8px;
		background: var(--warning-bg);
	}

	.approval > header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
	}

	.approval h3,
	.approval h4,
	.approval p {
		margin: 0;
	}

	.approval h3 {
		font-size: 16px;
	}

	.approval h4 {
		margin-top: 18px;
		font-size: 12px;
		text-transform: uppercase;
	}

	.approval header p {
		margin-top: 4px;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.approval > header > strong {
		color: var(--warning-text);
		font-size: 12px;
	}

	.approval dl {
		display: grid;
		gap: 0;
		margin: 8px 0 0;
		border-top: 1px solid var(--warning-border);
	}

	.approval dl div {
		display: grid;
		grid-template-columns: minmax(120px, 0.3fr) minmax(0, 1fr);
		gap: 16px;
		padding: 8px 0;
		border-bottom: 1px solid var(--warning-border);
	}

	.approval dt {
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		text-transform: capitalize;
	}

	.approval dd {
		margin: 0;
		font-size: 13px;
		overflow-wrap: anywhere;
	}

	.approval-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 16px;
	}

	.approval-actions button {
		min-height: 38px;
		padding: 0 14px;
		border-radius: 6px;
		font-weight: 700;
		cursor: pointer;
	}

	.reject {
		border: 1px solid var(--border-strong);
		background: var(--surface-card);
		color: var(--text-primary);
	}

	.approve {
		border: 1px solid var(--brand-primary);
		background: var(--brand-primary);
		color: #fff;
	}

	.composer {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		padding: 16px 32px max(20px, env(safe-area-inset-bottom));
		border-top: 1px solid var(--border-default);
		background: var(--surface-card);
	}

	.composer textarea {
		min-height: 54px;
		max-height: 150px;
		padding: 12px 14px;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		font: inherit;
		line-height: 22px;
		resize: vertical;
	}

	.composer textarea:focus {
		border-color: var(--brand-primary);
		outline: 2px solid var(--brand-border);
		outline-offset: 1px;
	}

	.composer button {
		align-self: end;
		min-width: 92px;
		min-height: 42px;
		border: 1px solid var(--brand-primary);
		border-radius: 6px;
		background: var(--brand-primary);
		color: #fff;
		font-weight: 700;
		cursor: pointer;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	@media (max-width: 820px) {
		.research-agent {
			grid-template-columns: 1fr;
			grid-template-rows: auto minmax(0, 1fr);
		}

		.sidebar {
			display: grid;
			grid-template-columns: minmax(0, 1fr) auto;
			align-items: center;
			gap: 12px;
			padding: 12px 16px;
			border-right: 0;
			border-bottom: 1px solid var(--border-default);
		}

		.new-session {
			margin: 0;
			padding: 0 12px;
		}

		.history,
		.collection-link {
			display: none;
		}

		.conversation-header,
		.message-scroll,
		.composer {
			padding-left: 18px;
			padding-right: 18px;
		}
	}

	@media (max-width: 560px) {
		.conversation-header {
			align-items: flex-start;
			flex-direction: column;
			gap: 6px;
		}

		.suggestions {
			grid-template-columns: 1fr;
		}

		.user-message > div {
			max-width: 90%;
		}

		.capability-event,
		.approval {
			margin-left: 0;
		}

		.approval > header,
		.approval dl div {
			grid-template-columns: 1fr;
			flex-direction: column;
		}

		.composer {
			grid-template-columns: minmax(0, 1fr) auto;
			gap: 8px;
			padding: 12px 12px max(12px, env(safe-area-inset-bottom));
		}

		.composer button {
			align-self: stretch;
			min-width: 76px;
			width: auto;
		}

		.composer textarea {
			min-height: 48px;
			resize: none;
		}
	}
</style>
