<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import { createExperimentPlan } from '../../../_shared/experimentPlans';
	import {
		createGoalSession,
		fetchGoalSession,
		fetchGoalSessionMessages,
		postGoalSessionMessage,
		type GoalSession,
		type GoalSessionMessage,
		type GoalSourceLink
	} from '../../../_shared/goalSessions';
	import { t } from '../../../_shared/i18n';

	type StoredGoalSession = {
		session_id: string;
		title: string;
		created_at: string;
		updated_at: string;
	};

	type InlineSegment = {
		text: string;
		strong: boolean;
	};

	type ParagraphBlock = {
		kind: 'paragraph';
		segments: InlineSegment[];
	};

	type ListBlock = {
		kind: 'list';
		items: InlineSegment[][];
	};

	type RenderBlock = ParagraphBlock | ListBlock;

	const suggestionKeys = [
		'goalCopilot.suggestions.summary',
		'goalCopilot.suggestions.lpbf',
		'goalCopilot.suggestions.elongation',
		'goalCopilot.suggestions.samples'
	];

	let session: GoalSession | null = null;
	let messages: GoalSessionMessage[] = [];
	let history: StoredGoalSession[] = [];
	let loading = false;
	let sending = false;
	let savingPlanMessageId = '';
	let savedPlanMessageIds: Record<string, string> = {};
	let error = '';
	let input = '';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: queryMaterialId = $page.url.searchParams.get('material_id') ?? '';
	$: queryPaperId = $page.url.searchParams.get('paper_id') ?? '';
	$: queryObjectiveId = $page.url.searchParams.get('objective_id') ?? '';
	$: queryGoalId = $page.url.searchParams.get('goal_id') ?? '';
	$: loadKey = `${collectionId}:${queryMaterialId}:${queryPaperId}:${queryObjectiveId}:${queryGoalId}`;
	$: activeSessionId = session?.session_id ?? '';
	$: if (collectionId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadSession();
	}

	function sessionStorageKey() {
		return `lens.goalSession.${collectionId}`;
	}

	function historyStorageKey() {
		return `lens.goalSessionHistory.${collectionId}`;
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

	function readHistory() {
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
							: $t('goalCopilot.untitledSession'),
					created_at:
						typeof item.created_at === 'string' ? item.created_at : new Date().toISOString(),
					updated_at:
						typeof item.updated_at === 'string' ? item.updated_at : new Date().toISOString()
				})) as StoredGoalSession[];
		} catch {
			return [];
		}
	}

	function writeHistory(nextHistory: StoredGoalSession[]) {
		history = nextHistory.slice(0, 12);
		if (!browser) return;
		window.localStorage.setItem(historyStorageKey(), JSON.stringify(history));
	}

	function titleFromMessages(nextMessages: GoalSessionMessage[]) {
		const firstUserMessage = nextMessages.find((message) => message.role === 'user');
		const text = (firstUserMessage?.content ?? firstUserMessage?.answer ?? '').trim();
		if (!text) return $t('goalCopilot.untitledSession');
		return text.length > 34 ? `${text.slice(0, 34)}...` : text;
	}

	function upsertHistory(nextSession: GoalSession, title = '') {
		const nextTitle = title || titleFromMessages(messages);
		const existing = history.filter((item) => item.session_id !== nextSession.session_id);
		writeHistory([
			{
				session_id: nextSession.session_id,
				title: nextTitle,
				created_at: nextSession.created_at,
				updated_at: nextSession.updated_at
			},
			...existing
		]);
	}

	async function loadSession(sessionId = '') {
		loading = true;
		error = '';
		history = readHistory();
		try {
			const storedSessionId = sessionId || readStoredSessionId();
			if (storedSessionId) {
				try {
					session = await fetchGoalSession(storedSessionId);
					if (!sessionMatchesCurrentFocus(session)) session = null;
				} catch {
					if (!sessionId) clearStoredSessionId();
					session = null;
				}
			}

			if (!session || session.collection_id !== collectionId) {
				session = await createGoalSession({
					collection_id: collectionId,
					focused_material_id: queryMaterialId || null,
					focused_paper_id: queryPaperId || null,
					focused_objective_id: queryObjectiveId || null,
					focused_goal_id: queryGoalId || null,
					answer_mode: 'hybrid'
				});
				messages = [];
				storeSessionId(session.session_id);
				upsertHistory(session, $t('goalCopilot.untitledSession'));
			} else {
				messages = await fetchGoalSessionMessages(session.session_id);
				storeSessionId(session.session_id);
				upsertHistory(session);
			}
		} catch (err) {
			error = errorMessage(err);
			session = null;
			messages = [];
		} finally {
			loading = false;
		}
	}

	function sessionMatchesCurrentFocus(nextSession: GoalSession | null) {
		if (!nextSession || nextSession.collection_id !== collectionId) return false;
		return (
			(nextSession.focused_material_id ?? '') === queryMaterialId &&
			(nextSession.focused_paper_id ?? '') === queryPaperId &&
			(nextSession.focused_objective_id ?? '') === queryObjectiveId &&
			(nextSession.focused_goal_id ?? '') === queryGoalId
		);
	}

	async function startNewSession() {
		loading = true;
		error = '';
		input = '';
		try {
			session = await createGoalSession({
				collection_id: collectionId,
				focused_material_id: queryMaterialId || null,
				focused_paper_id: queryPaperId || null,
				focused_objective_id: queryObjectiveId || null,
				focused_goal_id: queryGoalId || null,
				answer_mode: 'hybrid'
			});
			messages = [];
			storeSessionId(session.session_id);
			upsertHistory(session, $t('goalCopilot.untitledSession'));
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function switchSession(sessionId: string) {
		if (sessionId === activeSessionId || loading) return;
		session = null;
		messages = [];
		await loadSession(sessionId);
	}

	async function sendMessage(nextText = input.trim()) {
		const text = nextText.trim();
		if (!session || !text || sending) return;
		sending = true;
		error = '';
		const userMessage: GoalSessionMessage = {
			message_id: `local-${Date.now()}`,
			session_id: session.session_id,
			role: 'user',
			content: text,
			created_at: new Date().toISOString()
		};
		messages = [...messages, userMessage];
		input = '';
		upsertHistory(session, titleFromMessages(messages));
		try {
			const response = await postGoalSessionMessage(session.session_id, text, {
				route: 'collection_assistant',
				material_id: queryMaterialId || null,
				paper_id: queryPaperId || null,
				objective_id: queryObjectiveId || null,
				goal_id: queryGoalId || null
			});
			messages = [...messages, response];
			session = await fetchGoalSession(session.session_id);
			upsertHistory(session, titleFromMessages(messages));
		} catch (err) {
			error = errorMessage(err);
		} finally {
			sending = false;
		}
	}

	function askSuggestion(key: string) {
		const text = $t(key);
		void sendMessage(text);
	}

	function messageText(message: GoalSessionMessage) {
		return message.answer ?? message.content ?? '';
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
				const listItems = lines
					.map((line) => line.match(/^(?:[-*]\s+|\d+\.\s+)(.+)$/))
					.filter((match): match is RegExpMatchArray => Boolean(match));
				if (lines.length > 0 && listItems.length === lines.length) {
					const listBlock: ListBlock = {
						kind: 'list',
						items: listItems.map((match) => renderInlineMarkdown(match[1].trim()))
					};
					return listBlock;
				}
				const paragraphBlock: ParagraphBlock = {
					kind: 'paragraph',
					segments: renderInlineMarkdown(lines.join(' '))
				};
				return paragraphBlock;
			});
	}

	function visibleSourceLinks(message: GoalSessionMessage) {
		return (message.source_links ?? [])
			.filter((link) => link.href.startsWith('/collections/'))
			.slice(0, 12);
	}

	function needsCuratedFindings(message: GoalSessionMessage) {
		return (message.warnings ?? []).includes('curated_research_findings_empty');
	}

	function missingSourceCitation(message: GoalSessionMessage) {
		return (message.warnings ?? []).includes('goal_copilot_missing_source_citation');
	}

	function hasEvidenceCitations(message: GoalSessionMessage) {
		return (message.used_evidence_ids ?? []).length > 0;
	}

	function citesVisibleSourceLabel(message: GoalSessionMessage) {
		const text = messageText(message);
		return visibleSourceLinks(message).some((link) => text.includes(link.label));
	}

	function sourceLinksMatchEvidenceCitations(message: GoalSessionMessage) {
		const usedEvidenceIds = new Set(message.used_evidence_ids ?? []);
		const linkedEvidenceIds = visibleSourceLinks(message)
			.map((link) => new URL(link.href, 'http://localhost').searchParams.get('evidence_id') ?? '')
			.filter(Boolean);
		return linkedEvidenceIds.every((evidenceId) => usedEvidenceIds.has(evidenceId));
	}

	function sourceLinkLabel(link: GoalSourceLink, index: number) {
		const key =
			link.kind === 'document'
				? 'goalCopilot.sourceLinks.document'
				: 'goalCopilot.sourceLinks.evidence';
		return $t(key, { number: index + 1 });
	}

	function formatTime(value?: string) {
		if (!value) return '';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function formatHistoryTime(value?: string) {
		if (!value) return '';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		const now = new Date();
		const isToday = date.toDateString() === now.toDateString();
		if (isToday) return formatTime(value);
		return date.toLocaleDateString([], { month: 'numeric', day: 'numeric' });
	}

	function copyMessage(text: string) {
		if (!browser || !text) return;
		void navigator.clipboard?.writeText(text);
	}

	function canSaveExperimentPlan(message: GoalSessionMessage) {
		return Boolean(
			queryGoalId &&
				message.role === 'assistant' &&
				message.source_mode === 'collection_grounded' &&
				messageText(message).trim() &&
				visibleSourceLinks(message).length > 0 &&
				hasEvidenceCitations(message) &&
				citesVisibleSourceLabel(message) &&
				sourceLinksMatchEvidenceCitations(message) &&
				!needsCuratedFindings(message)
		);
	}

	function experimentPlanTitle(text: string) {
		const firstLine = text
			.split('\n')
			.map((line) => line.trim())
			.find(Boolean);
		if (!firstLine) return $t('goalCopilot.experimentPlan.defaultTitle');
		const cleaned = firstLine.replace(/^#+\s*/, '').replace(/^\d+\.\s*/, '');
		return cleaned.length > 80 ? `${cleaned.slice(0, 80)}...` : cleaned;
	}

	function experimentPlanHref(planId: string) {
		const anchor = planId ? `?plan_id=${encodeURIComponent(planId)}` : '';
		return `/collections/${encodeURIComponent(collectionId)}/goals/${encodeURIComponent(
			queryGoalId
		)}${anchor}#experiment-plans-title`;
	}

	async function saveExperimentPlan(message: GoalSessionMessage) {
		const content = messageText(message).trim();
		if (!queryGoalId || !content || savingPlanMessageId) return;
		savingPlanMessageId = message.message_id;
		error = '';
		try {
			const plan = await createExperimentPlan(collectionId, queryGoalId, {
				title: experimentPlanTitle(content),
				content,
				source_message_id: message.message_id,
				source_links: visibleSourceLinks(message),
				metadata: {
					source: 'goal_copilot',
					source_mode: message.source_mode
				}
			});
			savedPlanMessageIds = {
				...savedPlanMessageIds,
				[message.message_id]: plan.plan_id
			};
		} catch (err) {
			error = errorMessage(err);
		} finally {
			savingPlanMessageId = '';
		}
	}
</script>

<svelte:head>
	<title>{$t('goalCopilot.title')}</title>
</svelte:head>

<section class="research-chat-page" aria-label={$t('goalCopilot.chatLabel')}>
	<aside class="sidebar" aria-label={$t('goalCopilot.sidebarLabel')}>
		<div class="brand-row">
			<div class="logo" aria-hidden="true">
				<span>AI</span>
			</div>
			<h1>{$t('goalCopilot.title')}</h1>
			<span class="beta-tag">{$t('goalCopilot.beta')}</span>
		</div>

		<button class="new-chat-button" type="button" disabled={loading} on:click={startNewSession}>
			<span aria-hidden="true">+</span>
			{$t('goalCopilot.newSession')}
		</button>

		<section class="history-section" aria-label={$t('goalCopilot.historyTitle')}>
			<h2>{$t('goalCopilot.historyTitle')}</h2>
			<div class="history-list">
				{#each history as item}
					<button
						class="chat-item"
						class:active={item.session_id === activeSessionId}
						type="button"
						on:click={() => switchSession(item.session_id)}
					>
						<span class="chat-icon" aria-hidden="true"></span>
						<span class="chat-title">{item.title}</span>
						<span class="chat-time">{formatHistoryTime(item.updated_at)}</span>
					</button>
				{:else}
					<div class="empty-history">{$t('goalCopilot.emptyHistory')}</div>
				{/each}
			</div>
		</section>

		<a
			class="knowledge-card"
			href={`/collections/${collectionId}`}
			aria-label={$t('goalCopilot.knowledgeCardLabel')}
		>
			<span>
				<small>{$t('goalCopilot.currentKnowledge')}</small>
				<strong>{collectionId}</strong>
			</span>
			<span class="knowledge-chevron" aria-hidden="true">›</span>
		</a>
	</aside>

	<main class="main">
		<header class="chat-header">
			<div>
				<h2>{$t('goalCopilot.title')}</h2>
				<p>
					{$t('goalCopilot.headerPrefix')}
					<span>{collectionId}</span>
					<i aria-hidden="true">i</i>
				</p>
			</div>
			<button class="more-button" type="button">
				{$t('goalCopilot.more')}
				<span aria-hidden="true">⋮</span>
			</button>
		</header>

		{#if error}
			<div class="status-message" role="alert">{error}</div>
		{/if}

		<div class="messages" aria-live="polite" aria-busy={loading || sending}>
			<div class="messages-inner">
				{#if loading}
					<div class="empty-state">
						<h3>{$t('goalCopilot.loading')}</h3>
					</div>
				{:else if !messages.length}
					<div class="empty-state">
						<h3>{$t('goalCopilot.emptyTitle')}</h3>
						<p>{$t('goalCopilot.emptyBody')}</p>
						<div class="suggestion-grid">
							{#each suggestionKeys as key}
								<button
									class="suggestion-card"
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
					{#each messages as message}
						{#if message.role === 'user'}
							<article class="user-message">
								<div>
									<time>{formatTime(message.created_at)}</time>
									<div class="user-bubble">{messageText(message)}</div>
								</div>
							</article>
						{:else}
							<article class="assistant-message">
								<div class="assistant-avatar" aria-hidden="true">
									<span>AI</span>
								</div>
								<div class="assistant-content">
									<time>{formatTime(message.created_at)}</time>
									<div class="assistant-bubble">
										{#each renderMessageBlocks(messageText(message)) as block}
											{#if block.kind === 'list'}
												<ul>
													{#each block.items as item}
														<li>
															{#each item as segment}
																{#if segment.strong}
																	<strong>{segment.text}</strong>
																{:else}
																	{segment.text}
																{/if}
															{/each}
														</li>
													{/each}
												</ul>
											{:else}
												<p>
													{#each block.segments as segment}
														{#if segment.strong}
															<strong>{segment.text}</strong>
														{:else}
															{segment.text}
														{/if}
													{/each}
												</p>
											{/if}
										{/each}
									</div>
									{#if visibleSourceLinks(message).length}
										<nav class="source-links" aria-label={$t('goalCopilot.sourceLinks.label')}>
											{#each visibleSourceLinks(message) as link, index}
												<a class="source-link" href={link.href}>
													{sourceLinkLabel(link, index)}
												</a>
											{/each}
										</nav>
									{/if}
									{#if needsCuratedFindings(message)}
										<p class="review-required-note">
											{$t('goalCopilot.experimentPlan.reviewRequired')}
										</p>
									{:else if missingSourceCitation(message)}
										<p class="review-required-note">
											{$t('goalCopilot.experimentPlan.sourceTraceRequired')}
										</p>
									{:else if message.role === 'assistant' &&
										message.source_mode === 'collection_grounded' &&
										visibleSourceLinks(message).length &&
										!hasEvidenceCitations(message)}
										<p class="review-required-note">
											{$t('goalCopilot.experimentPlan.evidenceRequired')}
										</p>
									{:else if message.role === 'assistant' &&
										message.source_mode === 'collection_grounded' &&
										visibleSourceLinks(message).length &&
										hasEvidenceCitations(message) &&
										!citesVisibleSourceLabel(message)}
										<p class="review-required-note">
											{$t('goalCopilot.experimentPlan.sourceCitationRequired')}
										</p>
									{:else if message.role === 'assistant' &&
										message.source_mode === 'collection_grounded' &&
										visibleSourceLinks(message).length &&
										hasEvidenceCitations(message) &&
										citesVisibleSourceLabel(message) &&
										!sourceLinksMatchEvidenceCitations(message)}
										<p class="review-required-note">
											{$t('goalCopilot.experimentPlan.evidenceLinkMismatch')}
										</p>
									{/if}
									<div class="message-actions">
										<button
											class="action-button"
											type="button"
											aria-label={$t('goalCopilot.actions.copy')}
											on:click={() => copyMessage(messageText(message))}
										>
											<span aria-hidden="true">⧉</span>
										</button>
										{#if canSaveExperimentPlan(message)}
											{#if savedPlanMessageIds[message.message_id]}
												<a
													class="action-button action-button--text"
													href={experimentPlanHref(savedPlanMessageIds[message.message_id])}
												>
													{$t('goalCopilot.experimentPlan.open')}
												</a>
											{:else}
												<button
													class="action-button action-button--text"
													type="button"
													disabled={savingPlanMessageId === message.message_id}
													on:click={() => saveExperimentPlan(message)}
												>
													{#if savingPlanMessageId === message.message_id}
														{$t('goalCopilot.experimentPlan.saving')}
													{:else}
														{$t('goalCopilot.experimentPlan.save')}
													{/if}
												</button>
											{/if}
										{/if}
									</div>
								</div>
							</article>
						{/if}
					{/each}
				{/if}
			</div>
		</div>

		<form class="input-area" on:submit|preventDefault={() => sendMessage()}>
			<div class="input-inner">
				<div class="chat-input-box">
					<label class="sr-only" for="goal-message">{$t('goalCopilot.messageLabel')}</label>
					<textarea
						id="goal-message"
						class="chat-textarea"
						rows="2"
						bind:value={input}
						placeholder={$t('goalCopilot.messagePlaceholder')}
						disabled={!session || sending}
					></textarea>
					<button
						class="send-button"
						type="submit"
						disabled={!session || sending || !input.trim()}
						aria-label={$t('goalCopilot.send')}
					>
						<span aria-hidden="true">➤</span>
					</button>
				</div>
				<p class="input-hint">{$t('goalCopilot.inputHint')}</p>
			</div>
		</form>
	</main>
</section>

<style>
	:global(.app-shell:has(.research-chat-page)) {
		padding: 0;
		overflow: hidden;
		background: #f6f8fc;
	}

	:global(.app-shell:has(.research-chat-page) .site-header),
	:global(.app-shell:has(.research-chat-page) .site-footer) {
		display: none;
	}

	:global(.app-shell:has(.research-chat-page) .page) {
		width: 100vw;
		max-width: none;
		margin: 0;
	}

	:global(.app-shell:has(.research-chat-page) .bg-grid),
	:global(.collection-header:has(+ .collection-tabs + .collection-panel .research-chat-page)),
	:global(.collection-tabs:has(+ .collection-panel .research-chat-page)) {
		display: none;
	}

	:global(.collection-panel:has(.research-chat-page)) {
		gap: 0;
	}

	.research-chat-page {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: flex;
		width: 100vw;
		height: 100vh;
		background: #f6f8fc;
		color: #111827;
		font-family:
			Inter,
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			'PingFang SC',
			'Hiragino Sans GB',
			'Microsoft YaHei',
			sans-serif;
		letter-spacing: 0;
		overflow: hidden;
	}

	.sidebar {
		width: 300px;
		height: 100vh;
		background: #f8faff;
		border-right: 1px solid #e5eaf2;
		padding: 24px;
		display: flex;
		flex-direction: column;
		flex: 0 0 300px;
	}

	.brand-row {
		height: 48px;
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
	}

	.logo {
		width: 40px;
		height: 40px;
		border-radius: 12px;
		background: #eef4ff;
		border: 1px solid #dbe7ff;
		display: grid;
		place-items: center;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		flex: 0 0 auto;
	}

	.brand-row h1 {
		margin: 0;
		font-size: 22px;
		line-height: 32px;
		font-weight: 700;
		color: #111827;
		white-space: nowrap;
	}

	.beta-tag {
		height: 24px;
		padding: 0 10px;
		border-radius: 8px;
		background: #eef2f7;
		color: #64748b;
		font-size: 12px;
		line-height: 24px;
		font-weight: 500;
	}

	.new-chat-button {
		width: 100%;
		height: 44px;
		border-radius: 10px;
		background: #2563eb;
		color: #fff;
		font-size: 15px;
		line-height: 20px;
		font-weight: 600;
		border: none;
		margin-top: 28px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		cursor: pointer;
	}

	.new-chat-button:hover {
		background: #1d4ed8;
	}

	.new-chat-button:disabled {
		background: #94a3b8;
		cursor: not-allowed;
	}

	.history-section {
		margin-top: 40px;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

	.history-section h2 {
		margin: 0 0 14px;
		color: #64748b;
		font-size: 14px;
		line-height: 20px;
		font-weight: 600;
	}

	.history-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		overflow-y: auto;
		min-height: 0;
	}

	.chat-item {
		height: 48px;
		border-radius: 10px;
		padding: 0 12px;
		display: flex;
		align-items: center;
		gap: 10px;
		color: #334155;
		background: transparent;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.chat-item.active {
		background: #eaf2ff;
		color: #1e3a8a;
	}

	.chat-item:hover {
		background: #f1f5f9;
	}

	.chat-icon {
		width: 16px;
		height: 16px;
		border: 1.8px solid currentColor;
		border-radius: 50%;
		position: relative;
		flex: 0 0 auto;
		opacity: 0.82;
	}

	.chat-icon::after {
		content: '';
		position: absolute;
		left: 3px;
		bottom: -3px;
		width: 6px;
		height: 5px;
		border-left: 1.8px solid currentColor;
		border-bottom: 1.8px solid currentColor;
		transform: rotate(-22deg);
		background: inherit;
	}

	.chat-title {
		flex: 1;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		font-size: 14px;
		line-height: 20px;
	}

	.chat-time {
		color: #64748b;
		font-size: 12px;
		line-height: 18px;
		flex: 0 0 auto;
	}

	.empty-history {
		color: #94a3b8;
		font-size: 13px;
		line-height: 20px;
		padding: 8px 2px;
	}

	.knowledge-card {
		margin-top: auto;
		height: 70px;
		border-radius: 12px;
		border: 1px solid #d8e0ec;
		background: #fff;
		padding: 14px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		color: inherit;
	}

	.knowledge-card small {
		display: block;
		font-size: 12px;
		line-height: 18px;
		color: #64748b;
	}

	.knowledge-card strong {
		display: block;
		max-width: 210px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 14px;
		line-height: 20px;
		font-weight: 600;
		color: #111827;
	}

	.knowledge-chevron {
		color: #64748b;
		font-size: 28px;
		line-height: 1;
	}

	.main {
		flex: 1;
		min-width: 0;
		height: 100vh;
		background: #fff;
		display: flex;
		flex-direction: column;
	}

	.chat-header {
		height: 88px;
		padding: 24px 36px 18px;
		border-bottom: 1px solid #e5eaf2;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 24px;
		flex: 0 0 88px;
	}

	.chat-header h2 {
		margin: 0;
		font-size: 22px;
		line-height: 32px;
		font-weight: 700;
		color: #111827;
	}

	.chat-header p {
		margin: 4px 0 0;
		font-size: 14px;
		line-height: 20px;
		color: #64748b;
	}

	.chat-header p span {
		color: #111827;
		font-weight: 600;
	}

	.chat-header i {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		margin-left: 8px;
		border-radius: 50%;
		border: 1px solid #94a3b8;
		color: #64748b;
		font-size: 11px;
		font-style: normal;
		font-weight: 700;
		vertical-align: -1px;
	}

	.more-button {
		height: 40px;
		padding: 0 16px;
		border-radius: 10px;
		border: 1px solid #d8e0ec;
		background: #fff;
		color: #111827;
		font-size: 14px;
		line-height: 20px;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		cursor: pointer;
	}

	.more-button:hover {
		background: #f8fafc;
	}

	.status-message {
		margin: 12px 40px 0;
		padding: 10px 12px;
		border-radius: 10px;
		border: 1px solid #fecaca;
		background: #fef2f2;
		color: #b91c1c;
		font-size: 13px;
		line-height: 20px;
	}

	.messages {
		flex: 1;
		overflow-y: auto;
		padding: 32px 40px 24px;
	}

	.messages-inner {
		max-width: 960px;
		margin: 0 auto;
	}

	.empty-state {
		max-width: 640px;
		margin: 120px auto 0;
		text-align: center;
	}

	.empty-state h3 {
		margin: 0;
		font-size: 22px;
		line-height: 32px;
		font-weight: 700;
		color: #111827;
	}

	.empty-state p {
		margin: 8px 0 0;
		font-size: 14px;
		line-height: 22px;
		color: #64748b;
	}

	.suggestion-grid {
		margin-top: 24px;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}

	.suggestion-card {
		min-height: 48px;
		padding: 12px 14px;
		border-radius: 12px;
		border: 1px solid #d8e0ec;
		background: #fff;
		text-align: left;
		font-size: 14px;
		line-height: 20px;
		color: #334155;
		cursor: pointer;
	}

	.suggestion-card:hover {
		border-color: #2563eb;
		background: #f8fbff;
	}

	.suggestion-card:disabled {
		cursor: not-allowed;
		color: #94a3b8;
	}

	.user-message {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 28px;
	}

	.user-message > div {
		max-width: 560px;
	}

	.user-message time {
		display: block;
		margin-bottom: 6px;
		text-align: right;
		font-size: 12px;
		line-height: 18px;
		color: #94a3b8;
	}

	.user-bubble {
		max-width: 560px;
		padding: 14px 18px;
		border-radius: 14px 14px 4px 14px;
		background: #eaf2ff;
		color: #111827;
		font-size: 15px;
		line-height: 26px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.assistant-message {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		margin-bottom: 28px;
	}

	.assistant-avatar {
		width: 42px;
		height: 42px;
		border-radius: 50%;
		background: #eef4ff;
		border: 1px solid #e5eaf2;
		display: grid;
		place-items: center;
		color: #2563eb;
		font-size: 12px;
		font-weight: 800;
		flex-shrink: 0;
		margin-top: 24px;
	}

	.assistant-content {
		max-width: 760px;
		min-width: 0;
	}

	.assistant-content time {
		display: block;
		margin-bottom: 6px;
		font-size: 12px;
		line-height: 18px;
		color: #94a3b8;
	}

	.assistant-bubble {
		max-width: 760px;
		padding: 18px 20px;
		border-radius: 14px;
		background: #fff;
		border: 1px solid #d8e0ec;
		box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
		font-size: 15px;
		line-height: 26px;
		color: #111827;
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.assistant-bubble p {
		margin: 0 0 10px;
	}

	.assistant-bubble p:last-child,
	.assistant-bubble ul:last-child {
		margin-bottom: 0;
	}

	.assistant-bubble ul {
		margin: 8px 0;
		padding-left: 20px;
	}

	.assistant-bubble li {
		margin-bottom: 6px;
	}

	.source-links {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 10px;
	}

	.source-link {
		display: inline-flex;
		align-items: center;
		min-height: 30px;
		padding: 5px 10px;
		border-radius: 8px;
		border: 1px solid #d8e0ec;
		background: #fff;
		color: #2563eb;
		font-size: 13px;
		line-height: 18px;
		font-weight: 500;
		text-decoration: none;
	}

	.source-link:hover {
		border-color: #2563eb;
		background: #f8fbff;
	}

	.review-required-note {
		margin: 10px 0 0;
		padding: 9px 11px;
		border-radius: 8px;
		border: 1px solid #fde68a;
		background: #fffbeb;
		color: #92400e;
		font-size: 13px;
		line-height: 19px;
	}

	.message-actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
		margin-top: -12px;
		padding-right: 8px;
	}

	.source-links + .message-actions {
		margin-top: 8px;
	}

	.action-button {
		width: 28px;
		height: 28px;
		border-radius: 8px;
		border: 1px solid #e5eaf2;
		background: #fff;
		color: #64748b;
		display: inline-grid;
		place-items: center;
		cursor: pointer;
	}

	.action-button:hover {
		background: #f8fafc;
		color: #2563eb;
	}

	.action-button--text {
		width: auto;
		min-width: 92px;
		padding: 0 10px;
		font-size: 12px;
		font-weight: 700;
		letter-spacing: 0;
		white-space: nowrap;
	}

	.action-button:disabled {
		cursor: not-allowed;
		opacity: 0.65;
	}

	.input-area {
		min-height: 120px;
		padding: 16px 40px 20px;
		border-top: 1px solid #e5eaf2;
		background: #fff;
		flex: 0 0 auto;
	}

	.input-inner {
		max-width: 960px;
		margin: 0 auto;
	}

	.chat-input-box {
		position: relative;
		min-height: 72px;
		border-radius: 12px;
		border: 1px solid #d8e0ec;
		background: #fff;
		display: flex;
		align-items: flex-start;
		padding: 14px 56px 14px 16px;
	}

	.chat-textarea {
		width: 100%;
		min-height: 44px;
		max-height: 160px;
		border: none;
		outline: none;
		resize: none;
		font-size: 15px;
		line-height: 24px;
		color: #111827;
		background: transparent;
	}

	.chat-textarea::placeholder {
		color: #94a3b8;
	}

	.send-button {
		position: absolute;
		right: 12px;
		bottom: 12px;
		width: 40px;
		height: 40px;
		border-radius: 10px;
		border: none;
		background: #2563eb;
		color: #fff;
		display: grid;
		place-items: center;
		cursor: pointer;
	}

	.send-button:hover {
		background: #1d4ed8;
	}

	.send-button:disabled {
		background: #cbd5e1;
		cursor: not-allowed;
	}

	.input-hint {
		margin: 8px 0 0;
		text-align: center;
		font-size: 12px;
		line-height: 18px;
		color: #94a3b8;
	}

	@media (max-width: 900px) {
		.research-chat-page {
			position: fixed;
			display: grid;
			grid-template-columns: 1fr;
			grid-template-rows: auto minmax(0, 1fr);
		}

		.sidebar {
			width: 100%;
			height: auto;
			max-height: 260px;
			flex-basis: auto;
			border-right: none;
			border-bottom: 1px solid #e5eaf2;
		}

		.history-section {
			margin-top: 18px;
		}

		.knowledge-card {
			display: none;
		}

		.main {
			height: auto;
			min-height: 0;
		}
	}

	@media (max-width: 640px) {
		.sidebar {
			padding: 16px;
		}

		.chat-header,
		.messages,
		.input-area {
			padding-left: 18px;
			padding-right: 18px;
		}

		.suggestion-grid {
			grid-template-columns: 1fr;
		}

		.assistant-content,
		.assistant-bubble,
		.user-message > div,
		.user-bubble {
			max-width: 100%;
		}
	}
</style>
