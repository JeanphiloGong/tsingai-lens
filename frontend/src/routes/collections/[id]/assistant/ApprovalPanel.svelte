<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import type { ChatToolCall } from '../../../_shared/chatSessions';
	import { capabilityName, formatValue } from './capabilityPresentation';
	export let call: ChatToolCall;
	export let deciding = false;
	export let onDecide: (decision: 'approved' | 'rejected') => void;
	function approvalArguments(call: ChatToolCall) {
		return Object.entries(call.arguments);
	}

	function approvalBody(call: ChatToolCall) {
		if (call.name === 'start_research_process') {
			return $t('researchAgent.approval.startResearchBody');
		}
		if (call.name === 'start_objective_analysis') {
			return $t('researchAgent.approval.objectiveAnalysisBody');
		}
		if (call.name === 'confirm_objective') {
			return $t('researchAgent.approval.objectiveConfirmationBody');
		}
		if (call.name === 'record_finding_feedback') {
			return $t('researchAgent.approval.findingFeedbackBody');
		}
		if (call.name === 'curate_finding') {
			return $t('researchAgent.approval.findingCurationBody');
		}
		if (call.name === 'create_finding_version') {
			return typeof call.arguments.abstention_reason === 'string'
				? $t('researchAgent.approval.findingAbstentionBody')
				: $t('researchAgent.approval.findingAuthoringBody');
		}
		if (call.name === 'create_evidence_version') {
			return $t('researchAgent.approval.evidenceAuthoringBody');
		}
		if (call.name === 'create_research_plan') {
			return $t('researchAgent.approval.researchPlanBody');
		}
		if (call.name === 'publish_agent_objective_analysis') {
			return $t('researchAgent.approval.agentObjectiveAnalysisBody');
		}
		return $t('researchAgent.approval.body');
	}

	function approvalAction(call: ChatToolCall) {
		if (call.name === 'start_research_process') {
			return $t('researchAgent.approval.startResearch');
		}
		if (call.name === 'start_objective_analysis') {
			return $t('researchAgent.approval.analyzeObjective');
		}
		if (call.name === 'confirm_objective') {
			return $t('researchAgent.approval.confirmObjective');
		}
		if (call.name === 'record_finding_feedback') {
			return $t('researchAgent.approval.recordFeedback');
		}
		if (call.name === 'curate_finding') {
			return $t('researchAgent.approval.saveCuration');
		}
		if (call.name === 'create_finding_version') {
			return typeof call.arguments.abstention_reason === 'string'
				? $t('researchAgent.approval.publishAbstention')
				: $t('researchAgent.approval.publishFinding');
		}
		if (call.name === 'create_evidence_version') {
			return $t('researchAgent.approval.publishEvidence');
		}
		if (call.name === 'create_research_plan') {
			return $t('researchAgent.approval.publishResearchPlan');
		}
		if (call.name === 'publish_agent_objective_analysis') {
			return $t('researchAgent.approval.publishAgentAnalysis');
		}
		return $t('researchAgent.approval.approve');
	}
</script>

<section class="approval" aria-labelledby="approval-title">
	<header>
		<div>
			<h3 id="approval-title">{$t('researchAgent.approval.title')}</h3>
			<p>{approvalBody(call)}</p>
		</div>
		<div class="approval-header-meta">
			<span class="approval-status">{$t('researchAgent.approval.status')}</span>
			<strong>{capabilityName(call.name, $t)}</strong>
		</div>
	</header>
	{#if approvalArguments(call).length}
		<h4>{$t('researchAgent.approval.arguments')}</h4>
		<dl>
			{#each approvalArguments(call) as [key, value] (key)}
				<div>
					<dt>{key.replaceAll('_', ' ')}</dt>
					<dd>{formatValue(value)}</dd>
				</div>
			{/each}
		</dl>
	{/if}
	<div class="approval-actions">
		<button class="reject" type="button" disabled={deciding} on:click={() => onDecide('rejected')}>
			{$t('researchAgent.approval.reject')}
		</button>
		<button class="approve" type="button" disabled={deciding} on:click={() => onDecide('approved')}>
			{deciding ? $t('researchAgent.approval.processing') : approvalAction(call)}
		</button>
	</div>
</section>

<style>
	.approve:hover:not(:disabled) {
		border-color: var(--brand-primary-hover);
		background: var(--brand-primary-hover);
		color: #fff;
		transform: translateY(-1px);
	}

	.approve:active:not(:disabled) {
		transform: translateY(0);
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
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

	.approval-header-meta > strong {
		color: var(--warning-text);
		font-size: 12px;
	}

	.approval-header-meta {
		display: grid;
		justify-items: end;
		gap: 6px;
		flex: 0 0 auto;
	}

	.approval-status {
		padding: 4px 7px;
		border: 1px solid var(--warning-border);
		border-radius: 999px;
		background: var(--surface-card);
		color: var(--warning-text);
		font-size: 10px;
		font-weight: 800;
		line-height: 1.2;
		white-space: nowrap;
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

	@media (max-width: 560px) {
		.approval {
			margin-left: 0;
		}

		.approval > header,
		.approval dl div {
			grid-template-columns: 1fr;
			flex-direction: column;
		}
	}
</style>
