<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import type { ChatPresentationItem, ToolActivityOperation } from './conversationPresentation';
	import {
		capabilityName,
		capabilityRequestLabel,
		resultTitle,
		resultSummary
	} from './capabilityPresentation';
	import ResultResources from './ResultResources.svelte';
	import ResultWarnings from './ResultWarnings.svelte';
	type ActivityItem = Extract<ChatPresentationItem, { kind: 'activity' }>;
	export let item: ActivityItem;
	function activityOperations(activity: ActivityItem) {
		return activity.operations.filter((operation) => !activity.artifacts.includes(operation));
	}

	function activitySummary(activity: ActivityItem) {
		const count = activityOperations(activity).length;
		const baseKey =
			activity.status === 'failed'
				? 'researchAgent.capability.activityFailed'
				: activity.status === 'in_progress'
					? 'researchAgent.capability.activityInProgress'
					: activity.status === 'pending'
						? 'researchAgent.capability.activityPending'
						: 'researchAgent.capability.activityCompleted';
		return $t(`${baseKey}${count === 1 ? 'One' : 'Many'}`, { count });
	}

	function activityCapabilityNames(activity: ActivityItem) {
		return Array.from(
			new Set(
				activityOperations(activity).map((operation) => capabilityName(operation.toolName, $t))
			)
		).join(' · ');
	}

	function activityHasWarnings(activity: ActivityItem) {
		return activityOperations(activity).some(
			(operation) => (operation.resultMessage?.tool_result?.warnings.length ?? 0) > 0
		);
	}

	function activityIsOpen(activity: ActivityItem) {
		return activity.status === 'failed' || activityHasWarnings(activity);
	}

	function initializeActivityDisclosure(node: HTMLDetailsElement, initiallyOpen: boolean) {
		node.open = initiallyOpen;
		let previousAutomaticOpen = initiallyOpen;
		return {
			update(automaticOpen: boolean) {
				if (!previousAutomaticOpen && automaticOpen) node.open = true;
				previousAutomaticOpen = automaticOpen;
			}
		};
	}

	function activityStatusLabel(activity: ActivityItem) {
		if (activity.status === 'failed') return $t('researchAgent.capability.statusFailed');
		if (activity.status === 'in_progress') return $t('researchAgent.capability.statusQueued');
		if (activity.status === 'pending') return $t('researchAgent.capability.statusPending');
		return $t('researchAgent.capability.statusSucceeded');
	}

	function operationTitle(operation: ToolActivityOperation) {
		return operation.resultMessage
			? resultTitle(operation.resultMessage, operation.toolName, $t)
			: capabilityRequestLabel(operation.toolName, $t);
	}

	function operationSummary(operation: ToolActivityOperation) {
		return operation.resultMessage
			? resultSummary(operation.resultMessage, operation.toolName, $t)
			: '';
	}
</script>

{#if activityOperations(item).length}<details
		class="research-activity"
		class:failed={item.status === 'failed'}
		class:active={item.status === 'in_progress' || item.status === 'pending'}
		use:initializeActivityDisclosure={activityIsOpen(item)}
		data-testid="research-activity"
	>
		<summary>
			<span class="activity-icon" aria-hidden="true">
				{item.status === 'failed' ? '!' : item.status === 'completed' ? '✓' : '…'}
			</span>
			<span class="activity-heading">
				<strong>{activitySummary(item)}</strong>
				<small>{activityCapabilityNames(item)}</small>
			</span>
			<span class="activity-status">{activityStatusLabel(item)}</span>
			<span class="activity-toggle" aria-hidden="true"></span>
		</summary>
		<div class="activity-operations">
			{#each activityOperations(item) as operation (operation.toolCallId)}
				<div class="activity-operation">
					<span class="operation-mark" aria-hidden="true"></span>
					<div>
						<strong>{operationTitle(operation)}</strong>
						{#if operationSummary(operation)}
							<p>{operationSummary(operation)}</p>
						{/if}
						{#if operation.resultMessage?.tool_result?.warnings.length}
							<ResultWarnings warnings={operation.resultMessage.tool_result.warnings} />
						{/if}
						{#if operation.resultMessage && operation.resultMessage.tool_result?.resource_refs.length}
							<ResultResources message={operation.resultMessage} />
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</details>{/if}

<style>
	.research-activity {
		margin: 0 0 18px 48px;
		border: 1px solid var(--border-default);
		border-radius: 6px;
		background: var(--surface-card);
		color: var(--text-primary);
		animation: message-enter 180ms ease both;
	}

	.research-activity.failed {
		border-color: var(--danger-border);
	}

	.research-activity.active {
		border-color: var(--warning-border);
	}

	.research-activity summary {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr) auto 12px;
		align-items: center;
		gap: 10px;
		min-height: 52px;
		padding: 8px 12px;
		cursor: pointer;
		list-style: none;
		transition: background-color 140ms ease;
	}

	.research-activity summary:hover {
		background: var(--bg-subtle);
	}

	.research-activity summary::-webkit-details-marker {
		display: none;
	}

	.research-activity summary:focus-visible {
		outline: 2px solid var(--brand-primary);
		outline-offset: 2px;
	}

	.activity-icon {
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

	.research-activity.failed .activity-icon {
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.research-activity.active .activity-icon {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.activity-heading {
		display: grid;
		min-width: 0;
		gap: 1px;
	}

	.activity-heading strong {
		font-size: 13px;
	}

	.activity-heading small {
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.activity-status {
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
		white-space: nowrap;
	}

	.activity-toggle {
		width: 8px;
		height: 8px;
		border-right: 1.5px solid currentColor;
		border-bottom: 1.5px solid currentColor;
		color: var(--text-tertiary);
		transform: rotate(45deg) translate(-2px, -2px);
		transition: transform 140ms ease;
	}

	.research-activity[open] .activity-toggle {
		transform: rotate(225deg) translate(-1px, -1px);
	}

	.activity-operations {
		padding: 0 12px 10px 46px;
		border-top: 1px solid var(--border-default);
	}

	.activity-operation {
		display: grid;
		grid-template-columns: 8px minmax(0, 1fr);
		gap: 10px;
		padding: 10px 0 0;
	}

	.operation-mark {
		width: 6px;
		height: 6px;
		margin-top: 6px;
		border-radius: 50%;
		background: var(--border-strong);
	}

	.activity-operation strong {
		font-size: 12px;
	}

	.activity-operation p {
		margin: 2px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
	}

	@media (max-width: 560px) {
		.research-activity {
			margin-left: 0;
		}

		.research-activity summary {
			grid-template-columns: 24px minmax(0, 1fr) 12px;
		}

		.activity-status {
			display: none;
		}
	}

	@keyframes message-enter {
		from {
			opacity: 0;
			transform: translateY(6px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
