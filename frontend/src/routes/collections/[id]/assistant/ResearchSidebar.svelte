<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';

	type SessionSummary = {
		session_id: string;
		title: string;
		updated_at: string;
	};

	export let collectionId = '';
	export let history: SessionSummary[] = [];
	export let activeSessionId = '';
	export let loading = false;
	export let sending = false;
	export let deciding = false;
	export let onNewSession: () => void = () => {};
	export let onSwitchSession: (sessionId: string) => void = () => {};
	export let formatHistoryTime: (value: string) => string = () => '';
</script>

<aside class="sidebar" aria-label={$t('researchAgent.sidebarLabel')}>
	<div class="sidebar-top">
		<a class="back-workspace" href={resolve('/collections/[id]', { id: collectionId })}>
			<span aria-hidden="true">←</span>
			{$t('researchAgent.backToWorkspace')}
		</a>
		<div class="brand">
			<span class="brand-mark" aria-hidden="true">L</span>
			<h1>{$t('researchAgent.title')}</h1>
		</div>
	</div>

	<button
		class="new-session"
		type="button"
		disabled={loading || sending || deciding}
		on:click={onNewSession}
	>
		<span class="new-session-icon" aria-hidden="true">+</span>
		<span>{$t('researchAgent.newSession')}</span>
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
					on:click={() => onSwitchSession(item.session_id)}
				>
					<span class="history-title">{item.title}</span>
					<time>{formatHistoryTime(item.updated_at)}</time>
				</button>
			{:else}
				<p class="empty-history">{$t('researchAgent.emptyHistory')}</p>
			{/each}
		</div>
	</section>

	<div class="collection-context">
		<span>
			<small>{$t('researchAgent.currentCollection')}</small>
			<strong>{collectionId}</strong>
		</span>
	</div>
</aside>

<style>
	.sidebar {
		display: flex;
		min-height: 0;
		flex-direction: column;
		padding: 12px;
		border-right: 1px solid var(--border-default);
		background: var(--bg-subtle);
	}

	.sidebar-top {
		display: grid;
		gap: 8px;
	}

	.back-workspace {
		display: inline-flex;
		align-items: center;
		align-self: flex-start;
		gap: 7px;
		min-height: 32px;
		padding: 0 8px;
		border-radius: 8px;
		color: var(--text-secondary);
		font-size: 12px;
		font-weight: 700;
		text-decoration: none;
		transition:
			background-color 140ms ease,
			color 140ms ease;
	}

	.back-workspace span {
		font-size: 18px;
		line-height: 1;
	}

	.back-workspace:hover {
		background: var(--surface-card);
		color: var(--brand-primary);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 8px 12px;
		border-bottom: 1px solid var(--border-default);
	}

	.brand-mark {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border: 1px solid var(--brand-border);
		border-radius: 9px;
		background: var(--surface-card);
		color: var(--brand-primary);
		font-weight: 800;
	}

	.brand h1 {
		margin: 0;
		font-size: 15px;
		line-height: 20px;
	}

	.new-session {
		display: inline-flex;
		align-items: center;
		justify-content: flex-start;
		gap: 9px;
		min-height: 40px;
		margin-top: 12px;
		padding: 0 10px;
		border: 1px solid transparent;
		border-radius: 10px;
		background: var(--surface-card);
		color: var(--text-primary);
		font-weight: 700;
		cursor: pointer;
		transition:
			background-color 140ms ease,
			border-color 140ms ease,
			transform 140ms ease;
	}

	.new-session-icon {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border-radius: 7px;
		background: var(--brand-soft);
		color: var(--brand-primary);
		font-size: 18px;
		font-weight: 400;
		line-height: 1;
	}

	.new-session:hover:not(:disabled) {
		border-color: var(--brand-border);
		background: var(--brand-soft);
		color: var(--brand-primary);
		transform: translateY(-1px);
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
		margin-top: 22px;
	}

	.history h2 {
		margin: 0 8px 8px;
		color: var(--text-secondary);
		font-size: 10px;
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
		min-height: 38px;
		padding: 7px 9px;
		border: 1px solid transparent;
		border-radius: 9px;
		background: transparent;
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
		transition:
			background-color 140ms ease,
			border-color 140ms ease;
	}

	.history-item:hover,
	.history-item.active {
		border-color: var(--brand-border);
		background: var(--brand-soft);
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

	.collection-context {
		display: grid;
		gap: 10px;
		padding: 16px 8px 2px;
		border-top: 1px solid var(--border-default);
		font-size: 12px;
		font-weight: 700;
	}

	.collection-context span {
		display: grid;
		gap: 2px;
		min-width: 0;
	}

	.collection-context small {
		color: var(--text-secondary);
		font-weight: 500;
	}

	.collection-context strong {
		overflow: hidden;
		color: var(--text-primary);
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	@media (max-width: 820px) {
		.sidebar {
			display: grid;
			grid-template-columns: minmax(0, 1fr) auto;
			grid-template-rows: auto auto;
			align-items: center;
			gap: 12px;
			padding: 12px 16px;
			border-right: 0;
			border-bottom: 1px solid var(--border-default);
		}

		.sidebar-top {
			grid-column: 1;
			grid-row: 1 / span 2;
		}

		.back-workspace {
			grid-column: 1;
			grid-row: 1;
		}

		.brand {
			grid-column: 1;
			grid-row: 2;
			padding-bottom: 0;
			border-bottom: 0;
		}

		.new-session {
			grid-column: 2;
			grid-row: 1 / span 2;
			margin: 0;
			padding: 0 12px;
		}

		.history,
		.collection-context {
			display: none;
		}
	}
</style>
