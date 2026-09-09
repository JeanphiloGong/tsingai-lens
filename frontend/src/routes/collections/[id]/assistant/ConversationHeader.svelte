<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '../../../_shared/i18n';

	export let collectionId = '';
	export let objectiveId = '';
	export let working = false;
</script>

<header class="conversation-header">
	<div class="conversation-header-inner">
		<div class="conversation-heading">
			<div class="conversation-title-row">
				<h2>{$t('researchAgent.title')}</h2>
				<span class="session-state" class:working>
					<span class="session-state-dot" aria-hidden="true"></span>
					{$t(working ? 'researchAgent.working' : 'researchAgent.ready')}
				</span>
			</div>
			<p>{$t('researchAgent.headerPrefix')} <strong>{collectionId}</strong></p>
		</div>
		{#if objectiveId}
			<a
				class="objective-link"
				href={resolve('/collections/[id]/objectives/[objective_id]', {
					id: collectionId,
					objective_id: objectiveId
				})}
			>
				{$t('researchAgent.objectiveScope')}
			</a>
		{/if}
	</div>
</header>

<style>
	.conversation-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		min-height: 76px;
		padding: 14px 32px;
		border-bottom: 1px solid var(--border-default);
		background: var(--surface-card);
	}

	.conversation-header-inner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		width: min(100%, 900px);
		margin: 0 auto;
	}

	.conversation-heading {
		min-width: 0;
	}

	.conversation-title-row {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
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

	.session-state {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 7px;
		border: 1px solid var(--border-default);
		border-radius: 999px;
		color: var(--text-tertiary);
		font-size: 10px;
		font-weight: 700;
		line-height: 1;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.session-state.working {
		border-color: var(--warning-border);
		color: var(--warning-text);
	}

	.session-state-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--success-text);
	}

	.session-state.working .session-state-dot {
		background: var(--warning-text);
		animation: state-pulse 1.4s ease-in-out infinite;
	}

	.objective-link {
		color: var(--brand-primary);
		font-weight: 700;
		text-decoration: none;
		transition: color 140ms ease;
	}

	.objective-link:hover {
		text-decoration: underline;
	}

	@keyframes state-pulse {
		0%,
		100% {
			opacity: 0.45;
			transform: scale(0.85);
		}
		50% {
			opacity: 1;
			transform: scale(1);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.session-state-dot {
			animation: none;
		}
	}

	@media (max-width: 820px) {
		.conversation-header {
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

		.conversation-header-inner {
			align-items: flex-start;
			flex-direction: column;
			gap: 8px;
		}
	}
</style>
