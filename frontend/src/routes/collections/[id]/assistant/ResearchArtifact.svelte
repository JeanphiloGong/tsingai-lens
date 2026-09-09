<script lang="ts">
	import { t } from '../../../_shared/i18n';
	import type { ChatMessage } from '../../../_shared/chatSessions';
	import type { ToolActivityOperation } from './conversationPresentation';
	import {
		numberValue,
		formatValue,
		resultTitle,
		resultSummary,
		resultStatusLabel
	} from './capabilityPresentation';
	import ResultResources from './ResultResources.svelte';
	import ResultWarnings from './ResultWarnings.svelte';
	import MessageContent from './MessageContent.svelte';
	type ResearchProcessStep = { step_id: string; status: string };
	export let artifact: ToolActivityOperation;
	function findingStatement(message: ChatMessage) {
		const finding = message.tool_result?.data.finding;
		return finding && typeof finding === 'object' && 'statement' in finding
			? String(finding.statement ?? '').trim()
			: '';
	}

	function resultResearchSteps(message: ChatMessage): ResearchProcessStep[] {
		if (artifact.toolName !== 'inspect_research_process') return [];
		const process = message.tool_result?.data.process;
		if (!process || typeof process !== 'object' || !('steps' in process)) return [];
		return Array.isArray(process.steps)
			? process.steps.filter((step): step is ResearchProcessStep =>
					Boolean(
						step &&
						typeof step === 'object' &&
						'step_id' in step &&
						typeof step.step_id === 'string' &&
						'status' in step &&
						typeof step.status === 'string'
					)
				)
			: [];
	}

	function researchStepName(stepId: string) {
		switch (stepId) {
			case 'source_understanding':
				return $t('researchAgent.researchProcess.sourceUnderstanding');
			case 'paper_classification':
				return $t('researchAgent.researchProcess.paperClassification');
			case 'research_scope_screening':
				return $t('researchAgent.researchProcess.scopeScreening');
			case 'objective_formation':
				return $t('researchAgent.researchProcess.objectiveFormation');
			default:
				return stepId;
		}
	}

	function researchStepStatus(status: string) {
		switch (status) {
			case 'completed':
				return $t('researchAgent.researchProcess.completed');
			case 'running':
				return $t('researchAgent.researchProcess.running');
			case 'failed':
				return $t('researchAgent.researchProcess.failed');
			case 'skipped':
				return $t('researchAgent.researchProcess.skipped');
			default:
				return $t('researchAgent.researchProcess.queued');
		}
	}

	function researchProcessContext(message: ChatMessage) {
		const process = message.tool_result?.data.process;
		if (!process || typeof process !== 'object') return '';
		const active = 'active_document' in process ? process.active_document : null;
		const progress = 'document_progress' in process ? process.document_progress : null;
		const activeTitle =
			active && typeof active === 'object' && 'title' in active && String(active.title).trim()
				? String(active.title).trim()
				: active && typeof active === 'object' && 'document_id' in active
					? String(active.document_id).trim()
					: '';
		if (progress && typeof progress === 'object' && 'current' in progress && 'total' in progress) {
			return $t('researchAgent.researchProcess.documentProgress', {
				document: activeTitle || $t('researchAgent.researchProcess.currentPaper'),
				current: Number(progress.current) || 0,
				total: Number(progress.total) || 0
			});
		}
		return activeTitle;
	}

	function resultDrafts(message: ChatMessage) {
		const drafts = message.tool_result?.data.drafts;
		return Array.isArray(drafts)
			? drafts.filter((item): item is Record<string, unknown> =>
					Boolean(item && typeof item === 'object')
				)
			: [];
	}

	function resultDraft(message: ChatMessage): Record<string, unknown> | null {
		const draft = message.tool_result?.data.draft;
		return draft && typeof draft === 'object' && !Array.isArray(draft)
			? (draft as Record<string, unknown>)
			: null;
	}

	function resultDraftDetails(message: ChatMessage) {
		const draft = resultDraft(message);
		if (!draft) return [];
		const details: Array<{ label: string; value: string }> = [];
		const add = (label: string, value: unknown) => {
			const formatted = formatValue(value);
			if (formatted !== '--') details.push({ label, value: formatted });
		};
		if (draft.source_ref) add($t('researchAgent.capability.sourceReference'), draft.source_ref);
		if (draft.source_kind) add($t('researchAgent.capability.sourceKind'), draft.source_kind);
		if (draft.evidence_role) add($t('researchAgent.capability.evidenceRole'), draft.evidence_role);
		if (draft.statement) add($t('researchAgent.capability.findingStatement'), draft.statement);
		if (draft.assertion_strength)
			add($t('researchAgent.capability.assertionStrength'), draft.assertion_strength);
		if (draft.supporting_evidence_ids)
			add($t('researchAgent.capability.supportingEvidence'), draft.supporting_evidence_ids);
		if (draft.source_excerpt)
			add($t('researchAgent.capability.sourceExcerpt'), draft.source_excerpt);
		if (draft.authoring_note)
			add($t('researchAgent.capability.authoringNote'), draft.authoring_note);
		return details;
	}

	function draftReviewNote(toolName: string | null) {
		switch (toolName) {
			case 'create_evidence_draft':
				return $t('researchAgent.capability.evidenceDraftTransient');
			case 'create_finding_draft':
				return $t('researchAgent.capability.findingDraftTransient');
			default:
				return '';
		}
	}

	function resultPlanData(message: ChatMessage): Record<string, unknown> | null {
		const data = message.tool_result?.data ?? {};
		const plan = data.plan;
		if (plan && typeof plan === 'object' && !Array.isArray(plan)) {
			return plan as Record<string, unknown>;
		}
		return data;
	}

	function resultPlanContent(message: ChatMessage) {
		const toolName = artifact.toolName;
		if (toolName !== 'propose_research_plan' && toolName !== 'create_research_plan') return '';
		const data = resultPlanData(message);
		return data && typeof data.content === 'string' ? data.content.trim() : '';
	}

	function resultPlanTitle(message: ChatMessage) {
		const toolName = artifact.toolName;
		if (toolName !== 'propose_research_plan' && toolName !== 'create_research_plan') return '';
		const data = resultPlanData(message);
		return data && typeof data.title === 'string' ? data.title.trim() : '';
	}

	function resultTableMarkdown(message: ChatMessage) {
		if (artifact.toolName !== 'inspect_table') return '';
		const markdown = message.tool_result?.data.table_markdown;
		return typeof markdown === 'string' ? markdown.trim() : '';
	}

	function resultSourceContent(message: ChatMessage) {
		if (artifact.toolName !== 'read_source') return '';
		const data = message.tool_result?.data ?? {};
		for (const key of ['content', 'source_content', 'source_excerpt', 'text']) {
			const value = data[key];
			if (typeof value === 'string' && value.trim()) return value.trim();
		}
		return '';
	}

	function resultContinuationNote(message: ChatMessage) {
		const name = artifact.toolName;
		const data = message.tool_result?.data ?? {};
		if (
			name === 'read_source' &&
			(data.content_truncated === true ||
				(data.next_offset !== null && data.next_offset !== undefined))
		) {
			return $t('researchAgent.capability.sourceContinuation');
		}
		if (
			name === 'inspect_table' &&
			(data.content_truncated === true ||
				(data.next_row_offset !== null && data.next_row_offset !== undefined))
		) {
			return $t('researchAgent.capability.tableContinuation');
		}
		return '';
	}

	function resultSourceMatches(message: ChatMessage) {
		if (artifact.toolName !== 'search_sources') return [];
		const matches = message.tool_result?.data.matches;
		return Array.isArray(matches)
			? matches.filter((item): item is Record<string, unknown> =>
					Boolean(item && typeof item === 'object' && !Array.isArray(item))
				)
			: [];
	}

	function resultQuality(message: ChatMessage) {
		if (artifact.toolName !== 'assess_objective_quality') return null;
		return message.tool_result?.data ?? null;
	}

	function qualityStatusLabel(value: unknown) {
		switch (String(value ?? '')) {
			case 'finding_available':
				return $t('researchAgent.capability.qualityFindingAvailable');
			case 'finding_available_with_gaps':
				return $t('researchAgent.capability.qualityFindingWithGaps');
			case 'scientific_abstention':
				return $t('researchAgent.capability.qualityScientificAbstention');
			case 'no_grounded_evidence':
				return $t('researchAgent.capability.qualityNoGroundedEvidence');
			default:
				return $t('researchAgent.capability.qualityNotAnalyzed');
		}
	}

	function draftBasisCount(draft: Record<string, unknown>) {
		return Array.isArray(draft.derivation_basis) ? draft.derivation_basis.length : 0;
	}

	function draftBasisRationales(draft: Record<string, unknown>) {
		const basis = draft.derivation_basis;
		if (!Array.isArray(basis)) return [];
		return basis
			.filter((item): item is Record<string, unknown> =>
				Boolean(item && typeof item === 'object' && !Array.isArray(item))
			)
			.map((item) => (typeof item.rationale === 'string' ? item.rationale.trim() : ''))
			.filter(Boolean);
	}

	function draftList(draft: Record<string, unknown>, key: string) {
		const value = draft[key];
		return Array.isArray(value) ? value.map(String).filter(Boolean).join(', ') : '';
	}
</script>

{#if artifact.resultMessage?.tool_result}<section
		class="research-artifact"
		class:failed={artifact.resultMessage.tool_result.status === 'failed'}
		class:queued={artifact.resultMessage.tool_result.status === 'queued'}
		aria-labelledby={`artifact-${artifact.toolCallId}`}
		data-testid="research-artifact"
	>
		<header>
			<div>
				<p class="artifact-eyebrow">{$t('researchAgent.capability.artifact')}</p>
				<h3 id={`artifact-${artifact.toolCallId}`}>
					{resultTitle(artifact.resultMessage, artifact.toolName, $t)}
				</h3>
				<p>{resultSummary(artifact.resultMessage, artifact.toolName, $t)}</p>
			</div>
			<span
				class="capability-status"
				class:failed={artifact.resultMessage.tool_result.status === 'failed'}
				class:queued={artifact.resultMessage.tool_result.status === 'queued'}
			>
				{resultStatusLabel(artifact.resultMessage, $t)}
			</span>
		</header>

		{#if findingStatement(artifact.resultMessage)}
			<blockquote>{findingStatement(artifact.resultMessage)}</blockquote>
		{/if}

		{#if resultDrafts(artifact.resultMessage).length}
			<ol class="draft-list">
				{#each resultDrafts(artifact.resultMessage) as draft, draftIndex (`${String(draft.question ?? '')}-${draftIndex}`)}
					<li>
						<strong>{String(draft.question ?? '')}</strong>
						<p>{draftList(draft, 'variables')} → {draftList(draft, 'outcomes')}</p>
						<small>
							{$t('researchAgent.capability.draftSupport', {
								status: String(draft.support_status ?? 'unknown')
							})}
						</small>
						{#each draftBasisRationales(draft) as rationale (rationale)}
							<small class="draft-basis">{rationale}</small>
						{/each}
					</li>
				{/each}
			</ol>
		{/if}

		{#if resultDraftDetails(artifact.resultMessage).length}
			<dl class="artifact-details">
				{#each resultDraftDetails(artifact.resultMessage) as detail (detail.label)}
					<div>
						<dt>{detail.label}</dt>
						<dd
							class:artifact-detail-quote={detail.label ===
								$t('researchAgent.capability.sourceExcerpt')}
						>
							{detail.value}
						</dd>
					</div>
				{/each}
			</dl>
		{/if}
		{#if draftReviewNote(artifact.toolName)}
			<p class="artifact-note">{draftReviewNote(artifact.toolName)}</p>
		{/if}

		{#if resultDrafts(artifact.resultMessage).length && artifact.toolName === 'derive_objective'}
			<p class="artifact-note">
				{$t('researchAgent.capability.derivationBasisShown', {
					count: resultDrafts(artifact.resultMessage).reduce(
						(total, draft) => total + draftBasisCount(draft),
						0
					)
				})}
			</p>
		{/if}

		{#if resultPlanContent(artifact.resultMessage)}
			<div class="plan-preview">
				{#if resultPlanTitle(artifact.resultMessage)}
					<strong>{resultPlanTitle(artifact.resultMessage)}</strong>
				{/if}
				<pre>{resultPlanContent(artifact.resultMessage)}</pre>
			</div>
		{/if}

		{#if resultTableMarkdown(artifact.resultMessage)}
			<div class="table-preview">
				<strong>{$t('researchAgent.capability.tablePreview')}</strong>
				<MessageContent content={resultTableMarkdown(artifact.resultMessage)} />
			</div>
		{/if}

		{#if resultSourceContent(artifact.resultMessage)}
			<div class="source-preview">
				<strong>{$t('researchAgent.capability.sourcePreview')}</strong>
				<blockquote>{resultSourceContent(artifact.resultMessage)}</blockquote>
			</div>
		{/if}
		{#if resultContinuationNote(artifact.resultMessage)}
			<p class="artifact-note">{resultContinuationNote(artifact.resultMessage)}</p>
		{/if}

		{#if resultSourceMatches(artifact.resultMessage).length}
			<ul class="source-match-list">
				{#each resultSourceMatches(artifact.resultMessage) as match, matchIndex (String(match.source_ref ?? matchIndex))}
					<li>
						<strong>{String(match.source_ref ?? '')}</strong>
						{#if match.content}<span>{String(match.content)}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}

		{#if resultQuality(artifact.resultMessage)}
			{@const quality = resultQuality(artifact.resultMessage)}
			<div class="quality-preview">
				<strong>{qualityStatusLabel(quality?.quality_status)}</strong>
				<span>
					{$t('researchAgent.capability.qualityDetails', {
						findings: numberValue(quality ?? {}, 'finding_count'),
						evidence: numberValue(quality ?? {}, 'total_evidence_count'),
						gaps: numberValue(quality ?? {}, 'scientific_gap_count'),
						failures: numberValue(quality ?? {}, 'technical_failure_count')
					})}
				</span>
				{#if quality?.runtime_state === 'previous_published_result_available'}
					<small>{$t('researchAgent.capability.previousResultRetained')}</small>
				{/if}
			</div>
		{/if}

		{#if resultResearchSteps(artifact.resultMessage).length}
			<div class="research-process">
				{#if researchProcessContext(artifact.resultMessage)}
					<p>{researchProcessContext(artifact.resultMessage)}</p>
				{/if}
				<ol aria-label={$t('researchAgent.researchProcess.label')}>
					{#each resultResearchSteps(artifact.resultMessage) as step (step.step_id)}
						<li class:active={step.status === 'running'} class:failed={step.status === 'failed'}>
							<span aria-hidden="true"></span>
							<strong>{researchStepName(step.step_id)}</strong>
							<small>{researchStepStatus(step.status)}</small>
						</li>
					{/each}
				</ol>
			</div>
		{/if}

		{#if artifact.resultMessage.tool_result.warnings.length}
			<ResultWarnings warnings={artifact.resultMessage.tool_result.warnings} />
		{/if}

		{#if artifact.resultMessage.tool_result.resource_refs.length}
			<ResultResources message={artifact.resultMessage} />
		{/if}
	</section>{/if}

<style>
	.research-artifact {
		margin: 0 0 22px 48px;
		padding: 16px;
		border: 1px solid var(--border-default);
		border-left: 3px solid var(--brand-primary);
		border-radius: 6px;
		background: var(--surface-card);
		animation: message-enter 200ms ease both;
	}

	.research-artifact.failed {
		border-color: var(--danger-border);
		border-left-color: var(--danger-text);
	}

	.research-artifact.queued {
		border-color: var(--warning-border);
		border-left-color: var(--warning-text);
	}

	.research-artifact > header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
	}

	.research-artifact > header > div {
		min-width: 0;
	}

	.research-artifact h3,
	.research-artifact header p {
		margin: 0;
	}

	.research-artifact h3 {
		font-size: 14px;
		line-height: 20px;
	}

	.research-artifact header p:not(.artifact-eyebrow) {
		margin-top: 3px;
		color: var(--text-secondary);
		font-size: 13px;
	}

	.research-artifact .artifact-eyebrow {
		margin-bottom: 3px;
		color: var(--brand-primary);
		font-size: 10px;
		font-weight: 800;
		text-transform: uppercase;
	}

	.research-artifact blockquote {
		margin: 14px 0 0;
		padding: 10px 12px;
		border-left: 2px solid var(--border-strong);
		background: var(--bg-subtle);
		font-size: 13px;
		line-height: 20px;
	}

	.capability-status {
		flex: 0 0 auto;
		padding: 4px 7px;
		border: 1px solid var(--success-border);
		border-radius: 999px;
		background: var(--success-bg);
		color: var(--success-text);
		font-size: 10px;
		font-weight: 800;
		line-height: 1.2;
		white-space: nowrap;
	}

	.capability-status.queued {
		border-color: var(--warning-border);
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.capability-status.failed {
		border-color: var(--danger-border);
		background: var(--danger-bg);
		color: var(--danger-text);
	}

	.draft-list {
		display: grid;
		gap: 8px;
		margin: 14px 0 0;
		padding: 0;
		list-style: none;
		counter-reset: drafts;
	}

	.draft-list li {
		padding-top: 8px;
		border-top: 1px solid var(--border-default);
		counter-increment: drafts;
	}

	.draft-list li > strong::before {
		content: counter(drafts) '. ';
	}

	.draft-list p,
	.draft-list small {
		margin: 4px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.draft-list .draft-basis {
		display: block;
		color: var(--text-tertiary);
		font-style: italic;
	}

	.artifact-details {
		display: grid;
		gap: 8px;
		margin: 14px 0 0;
		padding-top: 12px;
		border-top: 1px solid var(--border-default);
	}

	.artifact-details > div {
		display: grid;
		grid-template-columns: minmax(110px, 0.25fr) minmax(0, 1fr);
		gap: 10px;
		align-items: start;
	}

	.artifact-details dt {
		color: var(--text-secondary);
		font-size: 11px;
		font-weight: 700;
	}

	.artifact-details dd {
		margin: 0;
		font-size: 12px;
		line-height: 18px;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.artifact-detail-quote {
		max-height: 150px;
		overflow: auto;
		padding: 8px 10px;
		border-left: 2px solid var(--border-strong);
		background: var(--bg-subtle);
	}

	.artifact-note {
		margin: 10px 0 0;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.plan-preview,
	.table-preview,
	.source-preview,
	.quality-preview {
		margin-top: 14px;
		padding-top: 12px;
		border-top: 1px solid var(--border-default);
	}

	.plan-preview strong,
	.table-preview strong,
	.source-preview strong,
	.quality-preview strong {
		display: block;
		font-size: 12px;
	}

	.table-preview :global(.assistant-copy) {
		margin-top: 8px;
		max-height: 320px;
		overflow-y: auto;
	}

	.plan-preview pre {
		max-height: 260px;
		margin: 8px 0 0;
		padding: 10px;
		overflow: auto;
		border: 1px solid var(--border-default);
		border-radius: 4px;
		background: var(--bg-subtle);
		font: inherit;
		font-size: 12px;
		line-height: 18px;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.source-preview blockquote {
		max-height: 260px;
		overflow: auto;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.source-match-list {
		display: grid;
		gap: 8px;
		margin: 14px 0 0;
		padding: 12px 0 0 18px;
		border-top: 1px solid var(--border-default);
	}

	.source-match-list li {
		padding-left: 2px;
		font-size: 12px;
		line-height: 18px;
	}

	.source-match-list strong,
	.source-match-list span {
		display: block;
	}

	.source-match-list span {
		margin-top: 2px;
		max-height: 120px;
		overflow: auto;
		color: var(--text-secondary);
		white-space: pre-wrap;
	}

	.quality-preview {
		display: grid;
		gap: 5px;
	}

	.quality-preview span,
	.quality-preview small {
		color: var(--text-secondary);
		font-size: 12px;
	}

	.research-process {
		margin-top: 14px;
		padding-top: 12px;
		border-top: 1px solid var(--border-default);
	}

	.research-process > p {
		margin: 0 0 10px;
		color: var(--text-secondary);
		font-size: 12px;
	}

	.research-process ol {
		display: grid;
		gap: 9px;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.research-process li {
		display: grid;
		grid-template-columns: 10px minmax(0, 1fr) auto;
		align-items: center;
		gap: 9px;
		min-height: 22px;
	}

	.research-process li > span {
		width: 8px;
		height: 8px;
		border: 1px solid var(--border-strong);
		border-radius: 50%;
		background: var(--surface-card);
	}

	.research-process li.active > span {
		border-color: var(--brand-primary);
		background: var(--brand-primary);
	}

	.research-process li.failed > span {
		border-color: var(--danger-text);
		background: var(--danger-text);
	}

	.research-process li strong,
	.research-process li small {
		font-size: 12px;
	}

	.research-process li small {
		color: var(--text-secondary);
	}

	@media (max-width: 560px) {
		.research-artifact {
			margin-left: 0;
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
