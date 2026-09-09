<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import {
		formatChatElapsed,
		getChatProgressActions,
		type ChatProgress
	} from '../../../_shared/chatSessions';
	export let progress: ChatProgress;
	export let progressHistory: ChatProgress[] = [];
	let progressHistoryExpanded = false;
	$: progressActions = getChatProgressActions(progress);
	function progressLabel(value: ChatProgress | null) {
		if (!value) return '';
		const phase = value.phase;
		const key = `researchAgent.progress.${phase}`;
		return $t(key, { cycle: value.cycle_index ?? 0 });
	}
</script>

<div class="assistant-progress" role="status" data-testid="research-progress">
	<button
		class="progress-current"
		type="button"
		aria-expanded={progressHistoryExpanded}
		aria-label={$t('researchAgent.progress.toggleHistory')}
		on:click={() => (progressHistoryExpanded = !progressHistoryExpanded)}
	>
		<div class="progress-main">
			<span class="progress-dot" aria-hidden="true"></span>
			<strong>{progressLabel(progress)}</strong>
		</div>
		<div class="progress-metrics" aria-label={$t('researchAgent.progress.detailsLabel')}>
			{#if progress.cycle_index && progress.cycle_index > 0}
				<span class="progress-metric"
					>{$t('researchAgent.progress.cycle', {
						cycle: progress.cycle_index
					})}</span
				>
			{/if}
			{#if progressActions}
				<span class="progress-metric">
					{$t('researchAgent.progress.actions', {
						completed: progressActions.completed,
						total: progressActions.total
					})}
				</span>
			{/if}
			{#if progress.elapsed_ms !== undefined}
				<span class="progress-metric progress-time">{formatChatElapsed(progress.elapsed_ms)}</span>
			{/if}
		</div>
		{#if progressHistory.length > 1}
			<span class="progress-chevron" aria-hidden="true"></span>
		{/if}
	</button>
	{#if progressHistoryExpanded && progressHistory.length > 1}
		<ol class="progress-trail" aria-label={$t('researchAgent.progress.historyLabel')}>
			{#each progressHistory.slice(0, -1) as entry, index (index)}
				{@const entryActions = getChatProgressActions(entry)}
				<li>
					<span class="progress-history-mark" aria-hidden="true">✓</span>
					<span>{progressLabel(entry)}</span>
					{#if entryActions}
						<small
							>{$t('researchAgent.progress.actions', {
								completed: entryActions.completed,
								total: entryActions.total
							})}</small
						>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.assistant-progress {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 0;
		margin-bottom: 8px;
		color: var(--text-secondary);
	}

	.progress-current {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		width: 100%;
		padding: 4px 0;
		border: 0;
		background: transparent;
		color: inherit;
		text-align: left;
		cursor: pointer;
		transition: color 140ms ease;
	}

	.progress-current:hover {
		color: var(--brand-primary);
	}

	.progress-current:focus-visible {
		outline: 2px solid var(--brand-border);
		outline-offset: 3px;
	}

	.progress-main {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
		color: var(--text-primary);
	}

	.progress-main strong {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.progress-metrics {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		flex-wrap: wrap;
		margin-left: auto;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.progress-metric {
		padding: 3px 7px;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		background: var(--bg-subtle);
		white-space: nowrap;
	}

	.progress-time {
		min-width: 42px;
		text-align: right;
		color: var(--text-tertiary);
		font-variant-numeric: tabular-nums;
	}

	.progress-chevron {
		width: 7px;
		height: 7px;
		flex: 0 0 auto;
		border-right: 1px solid var(--text-tertiary);
		border-bottom: 1px solid var(--text-tertiary);
		transform: rotate(45deg) translateY(-2px);
		transition: transform 120ms ease;
	}

	.progress-current[aria-expanded='true'] .progress-chevron {
		transform: rotate(225deg) translate(-1px, -1px);
	}

	.progress-trail {
		display: grid;
		gap: 4px;
		margin: 2px 0 0 3px;
		padding: 5px 0 1px 16px;
		border-left: 1px solid var(--border-default);
		color: var(--text-tertiary);
		font-size: 12px;
		list-style: none;
		animation: disclosure-in 160ms ease both;
	}

	.progress-trail li {
		display: flex;
		align-items: baseline;
		gap: 7px;
		min-width: 0;
	}

	.progress-trail small {
		color: var(--text-tertiary);
	}

	.progress-history-mark {
		color: var(--brand-primary);
		font-size: 11px;
	}

	.progress-dot {
		width: 8px;
		height: 8px;
		flex: 0 0 auto;
		border-radius: 50%;
		background: var(--brand-primary);
		animation: stream-cursor 0.9s steps(1) infinite;
	}

	@media (max-width: 560px) {
		.progress-current {
			align-items: flex-start;
			flex-wrap: wrap;
			gap: 6px;
		}

		.progress-main {
			flex: 1 1 calc(100% - 18px);
		}

		.progress-metrics {
			justify-content: flex-start;
			margin-left: 17px;
		}
	}

	@keyframes stream-cursor {
		50% {
			opacity: 0;
		}
	}

	@keyframes disclosure-in {
		from {
			opacity: 0;
			transform: translateY(-3px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
