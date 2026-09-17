<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import type { CurrentReading } from './conversationPresentation';
	import {
		formatChatElapsed,
		getChatProgressActions,
		type ChatProgress
	} from '../../../_shared/chatSessions';
	export let progress: ChatProgress;
	export let progressHistory: ChatProgress[] = [];
	export let readings: CurrentReading[] = [];
	let progressHistoryExpanded = false;
	$: progressActions = getChatProgressActions(progress);
	$: researchPlan = progress.research_plan?.steps ?? [];
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
	{#if researchPlan.length}
		<section class="research-plan" aria-label={$t('researchAgent.progress.plan.title')}>
			<strong class="research-plan-title">{$t('researchAgent.progress.plan.title')}</strong>
			<ol>
				{#each researchPlan as step (step.id)}
					<li class:active={step.status === 'in_progress'} class:done={step.status === 'completed'}>
						<span class="plan-mark" aria-hidden="true">{step.status === 'completed' ? '✓' : step.status === 'in_progress' ? '·' : '○'}</span>
						<span class="plan-label">{$t(`researchAgent.progress.plan.steps.${step.id}`)}</span>
						<small>{$t(`researchAgent.progress.plan.status.${step.status}`)}</small>
					</li>
				{/each}
			</ol>
		</section>
	{/if}
	{#each readings as reading (reading.toolCallId)}
		<div
			class="reading-current"
			data-testid="current-reading"
			class:failed={reading.status === 'failed'}
		>
			<div class="reading-location">
				<strong>{$t(`researchAgent.progress.sourceState.${reading.status}`)}</strong>
				<span>{$t(`researchAgent.progress.sourceKind.${reading.kind}`)}</span>
				{#if reading.page}<span
						>{$t('researchAgent.progress.sourcePage', { page: reading.page })}</span
					>{/if}
			</div>
			<p class="reading-title">{reading.title || $t('researchAgent.progress.currentPaper')}</p>
			{#if reading.heading}<p class="reading-heading">{reading.heading}</p>{/if}
			{#if reading.query}<p class="reading-heading">
					{$t('researchAgent.progress.searchQuery', { query: reading.query })}
				</p>{/if}
			{#if reading.excerpt}<blockquote>{reading.excerpt}</blockquote>{/if}
		</div>
	{/each}
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
	.reading-current {
		min-width: 0;
		margin: 6px 0 8px 3px;
		padding: 4px 0 4px 13px;
		border-left: 2px solid var(--brand-primary);
		overflow-wrap: anywhere;
		font-size: 12px;
	}
	.research-plan {
		margin: 4px 0 8px 3px;
		padding: 6px 0 6px 13px;
		border-left: 2px solid var(--border-default);
		font-size: 12px;
	}
	.research-plan-title {
		display: block;
		margin-bottom: 5px;
		color: var(--text-primary);
	}
	.research-plan ol {
		display: grid;
		gap: 3px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.research-plan li {
		display: grid;
		grid-template-columns: 14px minmax(0, 1fr) auto;
		align-items: baseline;
		gap: 6px;
		color: var(--text-tertiary);
	}
	.research-plan li.active {
		color: var(--text-primary);
	}
	.research-plan li.done {
		color: var(--text-secondary);
	}
	.plan-mark {
		color: var(--brand-primary);
		text-align: center;
	}
	.plan-label {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.research-plan small {
		color: var(--text-tertiary);
		white-space: nowrap;
	}
	.reading-current.failed {
		border-color: var(--danger-border);
	}
	.reading-location {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 10px;
	}
	.reading-current p {
		margin: 4px 0;
	}
	.reading-title {
		color: var(--text-primary);
		font-weight: 500;
	}
	.reading-heading {
		color: var(--text-secondary);
	}
	.reading-current blockquote {
		margin: 6px 0 0;
		color: var(--text-secondary);
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
		line-height: 1.5;
	}
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
