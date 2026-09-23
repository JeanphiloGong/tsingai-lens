<script lang="ts">
	import { BookOpen, ChevronDown, Check, CircleAlert, LoaderCircle } from '@lucide/svelte';
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';
	import { capabilityName } from './capabilityPresentation';
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
	$: historyEntries = progressHistory.length ? progressHistory : [progress];
	$: actionNames = Array.from(
		new Set((progress.selected_capability_names ?? []).map((name) => capabilityName(name, $t)))
	);
	$: actionSummary = actionNames.join(' · ');
	$: actionCounts = getChatProgressActions(progress);
	$: activePlanStep = progress.research_plan?.steps.find((step) => step.status === 'in_progress');
	function progressLabel(value: ChatProgress) {
		return $t(`researchAgent.progress.${value.phase}`, { cycle: value.cycle_index ?? 0 });
	}
	function planStepLabel(id: string) {
		return $t(`researchAgent.progress.plan.steps.${id}`);
	}
</script>

<div class="assistant-progress" data-testid="research-progress">
	<button
		class="progress-current"
		type="button"
		aria-expanded={progressHistoryExpanded}
		aria-label={$t('researchAgent.progress.toggleHistory')}
		on:click={() => (progressHistoryExpanded = !progressHistoryExpanded)}
	>
		<span class="progress-main"
			><span class="progress-dot" aria-hidden="true"></span><span role="status"
				>{progressLabel(progress)}</span
			></span
		>
		<span class="progress-meta"
			>{formatChatElapsed(progress.elapsed_ms)}<ChevronDown size={14} /></span
		>
	</button>
	{#if actionSummary || actionCounts || activePlanStep}
		<div class="progress-details" aria-label={$t('researchAgent.progress.detailsLabel')}>
			{#if actionSummary}<span class="progress-action"
					>{$t('researchAgent.progress.currentAction', { action: actionSummary })}</span
				>{/if}
			{#if actionCounts}<span>{$t('researchAgent.progress.actions', actionCounts)}</span>{/if}
			{#if activePlanStep}<span class="progress-plan">{planStepLabel(activePlanStep.id)}</span>{/if}
		</div>
	{/if}
	{#each readings as reading (reading.toolCallId)}
		<div
			class="reading-current"
			class:failed={reading.status === 'failed'}
			data-testid="current-reading"
		>
			<div class="reading-location">
				{#if reading.status === 'failed'}<CircleAlert size={15} />{:else}<BookOpen size={15} />{/if}
				<span>{$t(`researchAgent.progress.sourceState.${reading.status}`)}</span>
				{#if reading.page}<span
						>{$t('researchAgent.progress.sourcePage', { page: reading.page })}</span
					>{/if}
				{#if reading.heading}<span class="reading-heading">{reading.heading}</span>{/if}
			</div>
			<p class="reading-title">{reading.title || $t('researchAgent.progress.currentPaper')}</p>
			{#if reading.query}<p class="reading-query">
					{$t('researchAgent.progress.searchQuery', { query: reading.query })}
				</p>{/if}
			{#if reading.href}<a
					class="reading-link"
					href={resolve(reading.href as `/collections/${string}`)}
					>{$t('researchAgent.progress.openSource')}</a
				>{/if}
			{#if reading.excerpt}
				<details class="passage">
					<summary>{$t('agentReview.passage')}</summary>
					<blockquote>{reading.excerpt}</blockquote>
				</details>
			{/if}
		</div>
	{/each}
	{#if progressHistoryExpanded}
		<ol class="progress-trail" aria-label={$t('researchAgent.progress.historyLabel')}>
			{#each historyEntries as entry, index (index)}
				{@const current = index === historyEntries.length - 1}
				<li class:current aria-current={current ? 'step' : undefined}>
					{#if current}<LoaderCircle size={12} />{:else}<Check size={12} />{/if}
					<span>{progressLabel(entry)}</span><small>{formatChatElapsed(entry.elapsed_ms)}</small>
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.assistant-progress {
		margin: 0 0 16px;
		color: var(--text-secondary);
		font-size: 12px;
		min-width: 0;
	}
	.progress-current {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		padding: 7px 0;
		border: 0;
		background: transparent;
		color: inherit;
		text-align: left;
		cursor: pointer;
		font: inherit;
	}
	.progress-main,
	.progress-meta {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.progress-meta {
		flex-shrink: 0;
		color: var(--text-tertiary);
		font-variant-numeric: tabular-nums;
	}
	.progress-details {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		margin: 0 0 4px 14px;
		color: var(--text-secondary);
		line-height: 18px;
	}
	.progress-action {
		color: var(--text-primary);
		font-weight: 600;
	}
	.progress-plan {
		color: var(--brand-primary);
	}
	.progress-dot {
		width: 6px;
		height: 6px;
		flex-shrink: 0;
		border-radius: 50%;
		background: var(--brand-primary);
	}
	button:focus-visible,
	summary:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 3px;
	}
	.reading-current {
		padding: 8px 0 8px 14px;
		margin: 4px 0 4px 2px;
		border-left: 2px solid var(--border-default);
		overflow-wrap: anywhere;
	}
	.reading-current.failed {
		border-color: var(--danger-border);
	}
	.reading-current.failed .reading-location {
		color: var(--danger-text);
	}
	.reading-location {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}
	.reading-location :global(svg) {
		flex-shrink: 0;
	}
	.reading-title {
		color: var(--text-primary);
		font-weight: 500;
		font-size: 13px;
		margin: 6px 0;
		line-height: 1.5;
	}
	.reading-query {
		margin: 6px 0;
	}
	.reading-heading {
		color: var(--text-tertiary);
	}
	.reading-link {
		display: inline-flex;
		margin-top: 2px;
		color: var(--brand-primary);
		font-size: 11px;
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.passage summary {
		cursor: pointer;
		color: var(--text-secondary);
		width: fit-content;
	}
	blockquote {
		margin: 8px 0 0;
		line-height: 1.7;
		max-height: 180px;
		overflow: auto;
		white-space: pre-wrap;
	}
	.progress-trail {
		list-style: none;
		margin: 8px 0 0;
		padding: 0 0 0 14px;
		border-left: 1px solid var(--border-default);
	}
	.progress-trail li {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 5px 0;
	}
	.progress-trail li.current {
		color: var(--brand-primary);
	}
	.progress-trail li.current :global(svg) {
		animation: progress-spin 1.2s linear infinite;
	}
	.progress-trail small {
		margin-left: auto;
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
	}
	@media (prefers-reduced-motion: reduce) {
		.progress-trail li.current :global(svg) {
			animation: none;
		}
	}
	@keyframes progress-spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
