<script lang="ts">
	import { Check, CircleAlert, LoaderCircle } from '@lucide/svelte';
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

	function operationArguments(operation: ToolActivityOperation) {
		return (
			operation.requestMessage?.tool_calls.find(
				(call) => call.tool_call_id === operation.toolCallId
			)?.arguments ?? {}
		);
	}

	function resultData(operation: ToolActivityOperation) {
		return operation.resultMessage?.tool_result?.data ?? {};
	}

	function textValue(value: unknown) {
		return typeof value === 'string' && value.trim() ? value.trim() : '';
	}

	function operationContext(operation: ToolActivityOperation) {
		const args = operationArguments(operation);
		const data = resultData(operation);
		const document =
			data.document && typeof data.document === 'object'
				? (data.document as Record<string, unknown>)
				: {};
		const title =
			textValue(data.document_title) ||
			textValue(data.title) ||
			textValue(document.title) ||
			textValue(document.filename) ||
			textValue(args.document_title) ||
			(textValue(args.document_id) ? $t('researchAgent.progress.currentPaper') : '');
		const source =
			textValue(data.heading_path) ||
			textValue(data.source_ref) ||
			textValue(args.heading_path) ||
			textValue(args.source_ref) ||
			textValue(args.table_ref);
		const page = data.page ?? args.page;
		const location = [
			source,
			page !== undefined && page !== null
				? $t('researchAgent.progress.sourcePage', { page: String(page) })
				: ''
		]
			.filter(Boolean)
			.join(' · ');
		const query = textValue(args.query);
		return [title, location, query ? $t('researchAgent.progress.searchQuery', { query }) : '']
			.filter(Boolean)
			.join(' · ');
	}

	function operationExcerpt(operation: ToolActivityOperation) {
		const data = resultData(operation);
		return (
			textValue(data.content) ||
			textValue(data.table_markdown) ||
			textValue(data.source_excerpt) ||
			textValue(data.excerpt)
		).slice(0, 520);
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
				{#if item.status === 'failed'}<CircleAlert
						size={15}
					/>{:else if item.status === 'completed'}<Check size={15} />{:else}<LoaderCircle
						size={15}
					/>{/if}
			</span>
			<span class="activity-heading">
				<strong>{activitySummary(item)}</strong>
				<small>{activityCapabilityNames(item)}</small>
				{#if activityOperations(item).length === 1 && operationContext(activityOperations(item)[0])}
					<span class="activity-context">{operationContext(activityOperations(item)[0])}</span>
				{/if}
			</span>
			<span class="activity-toggle" aria-hidden="true"></span>
		</summary>
		<div class="activity-operations">
			{#each activityOperations(item) as operation (operation.toolCallId)}
				<div class="activity-operation">
					<span class="operation-mark" aria-hidden="true"></span>
					<div>
						<strong>{operationTitle(operation)}</strong>
						{#if operationContext(operation)}
							<p class="operation-context">{operationContext(operation)}</p>
						{/if}
						{#if operationSummary(operation)}
							<p>{operationSummary(operation)}</p>
						{/if}
						{#if operationExcerpt(operation)}
							<details class="operation-excerpt">
								<summary>{$t('agentReview.passage')}</summary>
								<blockquote>{operationExcerpt(operation)}</blockquote>
							</details>
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
		margin: 0 0 12px 48px;
		border: 0;
		border-radius: 6px;
		background: transparent;
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
		grid-template-columns: 20px minmax(0, 1fr) 12px;
		align-items: center;
		gap: 10px;
		min-height: 38px;
		padding: 6px 0;
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
		background: transparent;
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
		font-size: 12px;
		font-weight: 500;
	}

	.activity-heading small {
		overflow: hidden;
		color: var(--text-secondary);
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.activity-context {
		overflow: hidden;
		color: var(--text-primary);
		font-size: 12px;
		line-height: 17px;
		text-overflow: ellipsis;
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
		padding: 0 12px 10px 30px;
		border-left: 1px solid var(--border-default);
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

	.activity-operation .operation-context {
		color: var(--text-primary);
		font-weight: 500;
	}

	.operation-excerpt {
		margin-top: 7px;
	}

	.operation-excerpt summary {
		width: fit-content;
		color: var(--text-secondary);
		font-size: 11px;
		cursor: pointer;
	}

	.operation-excerpt blockquote {
		max-height: 160px;
		margin: 7px 0 0;
		padding: 8px 10px;
		border-left: 2px solid var(--border-default);
		background: var(--bg-subtle);
		color: var(--text-secondary);
		font-size: 12px;
		line-height: 18px;
		overflow: auto;
		white-space: pre-wrap;
	}

	@media (max-width: 560px) {
		.research-activity {
			margin-left: 0;
		}

		.research-activity summary {
			grid-template-columns: 24px minmax(0, 1fr) 12px;
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
