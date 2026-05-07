<script lang="ts">
	import { browser } from '$app/environment';
	import { page } from '$app/stores';
	import { errorMessage } from '../../../_shared/api';
	import {
		createGoalSession,
		fetchGoalSession,
		fetchGoalSessionMessages,
		postGoalSessionMessage,
		updateGoalSession,
		type GoalAnswerMode,
		type GoalSession,
		type GoalSessionMessage
	} from '../../../_shared/goalSessions';
	import { t } from '../../../_shared/i18n';

	let session: GoalSession | null = null;
	let messages: GoalSessionMessage[] = [];
	let loading = false;
	let saving = false;
	let sending = false;
	let error = '';
	let status = '';
	let input = '';
	let goalText = '';
	let focusedMaterialId = '';
	let focusedPaperId = '';
	let answerMode: GoalAnswerMode = 'hybrid';
	let loadedKey = '';

	$: collectionId = $page.params.id ?? '';
	$: queryMaterialId = $page.url.searchParams.get('material_id') ?? '';
	$: queryPaperId = $page.url.searchParams.get('paper_id') ?? '';
	$: loadKey = `${collectionId}:${queryMaterialId}:${queryPaperId}`;
	$: if (collectionId && loadKey !== loadedKey) {
		loadedKey = loadKey;
		void loadSession();
	}

	function sessionStorageKey() {
		return `lens.goalSession.${collectionId}`;
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

	function syncDraftFields(nextSession: GoalSession) {
		goalText = nextSession.goal_text ?? '';
		focusedMaterialId = nextSession.focused_material_id ?? '';
		focusedPaperId = nextSession.focused_paper_id ?? '';
		answerMode = nextSession.answer_mode;
	}

	async function loadSession() {
		loading = true;
		error = '';
		status = '';
		try {
			const storedSessionId = readStoredSessionId();
			if (storedSessionId) {
				try {
					session = await fetchGoalSession(storedSessionId);
				} catch {
					clearStoredSessionId();
					session = null;
				}
			}

			if (!session || session.collection_id !== collectionId) {
				session = await createGoalSession({
					collection_id: collectionId,
					focused_material_id: queryMaterialId || null,
					focused_paper_id: queryPaperId || null,
					answer_mode: 'hybrid'
				});
				storeSessionId(session.session_id);
			} else if (
				(queryMaterialId && queryMaterialId !== session.focused_material_id) ||
				(queryPaperId && queryPaperId !== session.focused_paper_id)
			) {
				session = await updateGoalSession(session.session_id, {
					focused_material_id: queryMaterialId || session.focused_material_id,
					focused_paper_id: queryPaperId || session.focused_paper_id
				});
			}

			syncDraftFields(session);
			messages = await fetchGoalSessionMessages(session.session_id);
		} catch (err) {
			error = errorMessage(err);
			session = null;
			messages = [];
		} finally {
			loading = false;
		}
	}

	async function saveContext() {
		if (!session) return;
		saving = true;
		error = '';
		status = '';
		try {
			session = await updateGoalSession(session.session_id, {
				goal_text: goalText.trim() || null,
				focused_material_id: focusedMaterialId.trim() || null,
				focused_paper_id: focusedPaperId.trim() || null,
				answer_mode: answerMode
			});
			syncDraftFields(session);
			status = $t('goalCopilot.contextSaved');
		} catch (err) {
			error = errorMessage(err);
		} finally {
			saving = false;
		}
	}

	async function startNewSession() {
		loading = true;
		error = '';
		status = '';
		try {
			session = await createGoalSession({
				collection_id: collectionId,
				focused_material_id: focusedMaterialId.trim() || queryMaterialId || null,
				focused_paper_id: focusedPaperId.trim() || queryPaperId || null,
				goal_text: goalText.trim() || null,
				answer_mode: answerMode
			});
			storeSessionId(session.session_id);
			syncDraftFields(session);
			messages = [];
			status = $t('goalCopilot.newSessionReady');
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function sendMessage() {
		const text = input.trim();
		if (!session || !text) return;
		sending = true;
		error = '';
		status = '';
		const userMessage: GoalSessionMessage = {
			message_id: `local-${Date.now()}`,
			session_id: session.session_id,
			role: 'user',
			content: text,
			created_at: new Date().toISOString()
		};
		messages = [...messages, userMessage];
		input = '';
		try {
			const response = await postGoalSessionMessage(session.session_id, text, {
				route: 'collection_assistant',
				material_id: focusedMaterialId.trim() || queryMaterialId || null,
				paper_id: focusedPaperId.trim() || queryPaperId || null
			});
			messages = [...messages, response];
			session = await fetchGoalSession(session.session_id);
			syncDraftFields(session);
		} catch (err) {
			error = errorMessage(err);
		} finally {
			sending = false;
		}
	}

	function sourceModeLabel(mode?: string) {
		if (!mode) return '';
		const key = `goalCopilot.sourceMode.${mode}`;
		const value = $t(key);
		return value === key ? mode : value;
	}

	function sourceModeTone(mode?: string) {
		if (mode === 'collection_grounded') return 'grounded';
		if (mode === 'general_fallback' || mode === 'general_only') return 'general';
		return 'limited';
	}
</script>

<svelte:head>
	<title>{$t('goalCopilot.title')}</title>
</svelte:head>

<section class="goal-copilot-page fade-up">
	<div class="goal-copilot-layout">
		<aside class="goal-context-panel" aria-label={$t('goalCopilot.contextLabel')}>
			<div>
				<p class="eyebrow">{$t('goalCopilot.eyebrow')}</p>
				<h2>{$t('goalCopilot.title')}</h2>
				<p>{$t('goalCopilot.subtitle')}</p>
			</div>

			<div class="context-field">
				<span>{$t('goalCopilot.collection')}</span>
				<strong>{collectionId}</strong>
			</div>

			<label class="context-field">
				<span>{$t('goalCopilot.goal')}</span>
				<textarea rows="3" bind:value={goalText} placeholder={$t('goalCopilot.goalPlaceholder')}></textarea>
			</label>

			<label class="context-field">
				<span>{$t('goalCopilot.focusedMaterial')}</span>
				<input bind:value={focusedMaterialId} placeholder={$t('goalCopilot.focusedMaterialPlaceholder')} />
			</label>

			<label class="context-field">
				<span>{$t('goalCopilot.focusedPaper')}</span>
				<input bind:value={focusedPaperId} placeholder={$t('goalCopilot.focusedPaperPlaceholder')} />
			</label>

			<label class="context-field">
				<span>{$t('goalCopilot.mode')}</span>
				<select bind:value={answerMode}>
					<option value="hybrid">{$t('goalCopilot.modes.hybrid')}</option>
					<option value="grounded">{$t('goalCopilot.modes.grounded')}</option>
					<option value="general">{$t('goalCopilot.modes.general')}</option>
				</select>
			</label>

			<div class="context-actions">
				<button class="btn btn--primary btn--small" type="button" disabled={saving} on:click={saveContext}>
					{saving ? $t('goalCopilot.saving') : $t('goalCopilot.saveContext')}
				</button>
				<button class="btn btn--ghost btn--small" type="button" disabled={loading} on:click={startNewSession}>
					{$t('goalCopilot.newSession')}
				</button>
			</div>

			<div class="command-help">
				<h3>{$t('goalCopilot.commandsTitle')}</h3>
				<code>$mode grounded</code>
				<code>$mode hybrid</code>
				<code>$material 316L stainless steel</code>
				<code>$goal compare strength and elongation</code>
			</div>
		</aside>

		<main class="goal-chat-panel" aria-label={$t('goalCopilot.chatLabel')}>
			<div class="chat-header">
				<div>
					<h3>{$t('goalCopilot.chatTitle')}</h3>
					<p>
						{#if session}
							{$t('goalCopilot.sessionMeta', {
								mode: $t(`goalCopilot.modes.${session.answer_mode}`),
								id: session.session_id
							})}
						{:else}
							{$t('goalCopilot.loading')}
						{/if}
					</p>
				</div>
				<a class="btn btn--ghost btn--small" href={`/collections/${collectionId}`}>
					{$t('goalCopilot.openWorkspace')}
				</a>
			</div>

			{#if error}
				<div class="status status--error" role="alert">{error}</div>
			{/if}
			{#if status}
				<div class="status" role="status">{status}</div>
			{/if}

			<div class="message-list" aria-live="polite" aria-busy={loading || sending}>
				{#if loading}
					<div class="empty-chat">{$t('goalCopilot.loading')}</div>
				{:else if !messages.length}
					<div class="empty-chat">
						<h3>{$t('goalCopilot.emptyTitle')}</h3>
						<p>{$t('goalCopilot.emptyBody')}</p>
					</div>
				{:else}
					{#each messages as message}
						<article class={`message-card message-card--${message.role}`}>
							<div class="message-card__meta">
								<strong>
									{message.role === 'user' ? $t('goalCopilot.userRole') : $t('goalCopilot.assistantRole')}
								</strong>
								{#if message.source_mode}
									<span class={`source-badge source-badge--${sourceModeTone(message.source_mode)}`}>
										{sourceModeLabel(message.source_mode)}
									</span>
								{/if}
							</div>
							<p>{message.answer ?? message.content}</p>
							{#if message.used_evidence_ids?.length}
								<div class="evidence-chip-row" aria-label={$t('goalCopilot.evidenceLabel')}>
									{#each message.used_evidence_ids as evidenceId}
										<a href={`/collections/${collectionId}/evidence`}>{evidenceId}</a>
									{/each}
								</div>
							{/if}
							{#if message.warnings?.length}
								<ul class="warning-list">
									{#each message.warnings as warning}
										<li>{warning}</li>
									{/each}
								</ul>
							{/if}
						</article>
					{/each}
				{/if}
			</div>

			<form class="chat-composer" on:submit|preventDefault={sendMessage}>
				<label for="goal-message">{$t('goalCopilot.messageLabel')}</label>
				<div>
					<textarea
						id="goal-message"
						rows="3"
						bind:value={input}
						placeholder={$t('goalCopilot.messagePlaceholder')}
						disabled={!session || sending}
					></textarea>
					<button class="btn btn--primary" type="submit" disabled={!session || sending || !input.trim()}>
						{sending ? $t('goalCopilot.sending') : $t('goalCopilot.send')}
					</button>
				</div>
			</form>
		</main>
	</div>
</section>

<style>
	.goal-copilot-page {
		padding: 0;
	}

	.goal-copilot-layout {
		display: grid;
		grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
		gap: 20px;
		align-items: start;
	}

	.goal-context-panel,
	.goal-chat-panel {
		border: 1px solid var(--color-line);
		border-radius: 12px;
		background: var(--color-card);
		box-shadow: var(--shadow-tight);
	}

	.goal-context-panel {
		display: grid;
		gap: 16px;
		padding: 18px;
		position: sticky;
		top: 16px;
	}

	.eyebrow {
		margin: 0 0 6px;
		color: var(--color-muted);
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
	}

	.goal-context-panel h2,
	.goal-context-panel p,
	.goal-chat-panel h3,
	.goal-chat-panel p {
		margin: 0;
	}

	.goal-context-panel h2 {
		font-size: 22px;
	}

	.goal-context-panel p,
	.chat-header p,
	.empty-chat p {
		color: var(--color-muted);
		line-height: 1.55;
	}

	.context-field {
		display: grid;
		gap: 7px;
		font-size: 13px;
		color: var(--color-muted);
	}

	.context-field strong {
		color: var(--color-ink);
		word-break: break-word;
	}

	.context-field input,
	.context-field textarea,
	.context-field select,
	.chat-composer textarea {
		width: 100%;
		border: 1px solid var(--color-line);
		border-radius: 8px;
		background: var(--color-card);
		color: var(--color-ink);
		font: inherit;
		padding: 10px 12px;
	}

	.context-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.command-help {
		display: grid;
		gap: 8px;
		border-top: 1px solid var(--color-line);
		padding-top: 14px;
	}

	.command-help h3 {
		margin: 0;
		font-size: 13px;
	}

	.command-help code {
		display: block;
		border: 1px solid var(--color-line);
		border-radius: 6px;
		background: var(--bg-subtle);
		color: var(--color-muted);
		font-size: 12px;
		padding: 7px 8px;
		white-space: normal;
	}

	.goal-chat-panel {
		min-height: 680px;
		display: grid;
		grid-template-rows: auto 1fr auto;
	}

	.chat-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
		border-bottom: 1px solid var(--color-line);
		padding: 18px;
	}

	.message-list {
		display: grid;
		align-content: start;
		gap: 12px;
		min-height: 420px;
		padding: 18px;
	}

	.empty-chat {
		border: 1px dashed var(--color-line);
		border-radius: 10px;
		background: var(--bg-subtle);
		padding: 28px;
		text-align: center;
	}

	.empty-chat h3 {
		margin-bottom: 8px;
	}

	.message-card {
		display: grid;
		gap: 10px;
		max-width: 860px;
		border: 1px solid var(--color-line);
		border-radius: 10px;
		padding: 14px;
	}

	.message-card--user {
		justify-self: end;
		width: min(760px, 86%);
		background: var(--brand-soft);
		border-color: var(--brand-border);
	}

	.message-card--assistant {
		justify-self: start;
		width: min(860px, 92%);
		background: var(--color-card);
	}

	.message-card p {
		white-space: pre-wrap;
		line-height: 1.6;
	}

	.message-card__meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		color: var(--color-muted);
	}

	.source-badge {
		border-radius: 999px;
		border: 1px solid var(--color-line);
		padding: 3px 8px;
		font-weight: 700;
	}

	.source-badge--grounded {
		background: #eff6ff;
		border-color: #bfdbfe;
		color: #2563eb;
	}

	.source-badge--general {
		background: #fffbeb;
		border-color: #fde68a;
		color: #92400e;
	}

	.source-badge--limited {
		background: var(--bg-subtle);
		color: var(--color-muted);
	}

	.evidence-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.evidence-chip-row a {
		border-radius: 999px;
		background: #eff6ff;
		color: #2563eb;
		font-size: 12px;
		font-weight: 700;
		padding: 4px 8px;
		text-decoration: none;
	}

	.warning-list {
		margin: 0;
		padding-left: 18px;
		color: #92400e;
		font-size: 12px;
	}

	.chat-composer {
		display: grid;
		gap: 8px;
		border-top: 1px solid var(--color-line);
		padding: 18px;
	}

	.chat-composer label {
		color: var(--color-muted);
		font-size: 13px;
		font-weight: 700;
	}

	.chat-composer div {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		align-items: end;
	}

	.chat-composer button {
		min-width: 108px;
	}

	@media (max-width: 960px) {
		.goal-copilot-layout {
			grid-template-columns: 1fr;
		}

		.goal-context-panel {
			position: static;
		}

		.chat-composer div {
			grid-template-columns: 1fr;
		}

		.message-card--user,
		.message-card--assistant {
			width: 100%;
		}
	}
</style>
