import type { ChatMessage } from '../../../_shared/chatSessions';
type Translate = (key: string, vars?: Record<string, string | number>) => string;

export function capabilityName(toolName: string | null, translate: Translate) {
	switch (toolName) {
		case 'get_collection_context':
			return translate('researchAgent.capability.collection');
		case 'search_sources':
			return translate('researchAgent.capability.searchSources');
		case 'read_source':
			return translate('researchAgent.capability.readSource');
		case 'inspect_table':
			return translate('researchAgent.capability.inspectTable');
		case 'inspect_document_sources':
			return translate('researchAgent.capability.documentSources');
		case 'inspect_research_process':
			return translate('researchAgent.capability.researchProcess');
		case 'start_research_process':
			return translate('researchAgent.capability.startResearchProcess');
		case 'query_published_findings':
			return translate('researchAgent.capability.findings');
		case 'inspect_published_finding':
			return translate('researchAgent.capability.findingReview');
		case 'record_finding_feedback':
			return translate('researchAgent.capability.findingFeedback');
		case 'curate_finding':
			return translate('researchAgent.capability.findingCuration');
		case 'create_finding_draft':
			return translate('researchAgent.capability.findingDraft');
		case 'create_finding_version':
			return translate('researchAgent.capability.findingAuthoring');
		case 'create_evidence_draft':
			return translate('researchAgent.capability.evidenceDraft');
		case 'create_evidence_version':
			return translate('researchAgent.capability.evidenceAuthoring');
		case 'publish_agent_objective_analysis':
			return translate('researchAgent.capability.agentObjectiveAnalysis');
		case 'propose_objective_drafts':
			return translate('researchAgent.capability.proposals');
		case 'create_objective_candidate':
			return translate('researchAgent.capability.createObjective');
		case 'confirm_objective':
			return translate('researchAgent.capability.confirmObjective');
		case 'derive_objective':
			return translate('researchAgent.capability.deriveObjective');
		case 'preview_research_scope':
			return translate('researchAgent.capability.previewResearchScope');
		case 'propose_research_plan':
			return translate('researchAgent.capability.researchPlanDraft');
		case 'create_research_plan':
			return translate('researchAgent.capability.researchPlanAuthoring');
		case 'start_objective_analysis':
			return translate('researchAgent.capability.startObjectiveAnalysis');
		case 'inspect_objective_analysis':
			return translate('researchAgent.capability.inspectObjectiveAnalysis');
		case 'assess_objective_quality':
			return translate('researchAgent.capability.objectiveQuality');
		default:
			return translate('researchAgent.capability.unknown');
	}
}
export function capabilityRequestLabel(toolName: string | null, translate: Translate) {
	if (toolName === 'inspect_research_process') {
		return translate('researchAgent.capability.researchProcessRequested');
	}
	return translate('researchAgent.capability.requested', {
		name: capabilityName(toolName, translate)
	});
}
export function numberValue(data: Record<string, unknown>, key: string) {
	const value = data[key];
	return typeof value === 'number' ? value : 0;
}
export function resultSummary(message: ChatMessage, toolName: string | null, translate: Translate) {
	const result = message.tool_result;
	if (!result) return '';
	const name = toolName;
	if (result.status === 'failed') {
		return translate('researchAgent.capability.failed', { name: capabilityName(name, translate) });
	}
	if (result.status === 'queued') {
		return translate('researchAgent.capability.queuedDescription');
	}
	if (name === 'get_collection_context') {
		const collection = result.data.collection;
		const papers =
			collection && typeof collection === 'object' && 'paper_count' in collection
				? Number(collection.paper_count) || 0
				: 0;
		return translate('researchAgent.capability.paperCount', {
			papers,
			objectives: numberValue(result.data, 'objective_count')
		});
	}
	if (name === 'inspect_document_sources') {
		return translate('researchAgent.capability.documentSourceCount', {
			count: numberValue(result.data, 'match_total')
		});
	}
	if (name === 'search_sources') {
		return translate('researchAgent.capability.documentSourceCount', {
			count: numberValue(result.data, 'match_total')
		});
	}
	if (name === 'read_source') {
		const sourceRef = result.data.source_ref;
		return translate('researchAgent.capability.sourceReadSummary', {
			source: typeof sourceRef === 'string' && sourceRef.trim() ? sourceRef : '--'
		});
	}
	if (name === 'inspect_table') {
		return translate('researchAgent.capability.tableSummary', {
			rows: numberValue(result.data, 'data_row_count'),
			columns: numberValue(result.data, 'column_count')
		});
	}
	if (name === 'inspect_research_process') {
		const process = result.data.process;
		if (!process || typeof process !== 'object' || !('status' in process)) {
			return translate('researchAgent.capability.researchProcessUnavailable');
		}
		switch (String(process.status)) {
			case 'not_started':
				return translate('researchAgent.researchProcess.notStartedSummary');
			case 'queued':
				return translate('researchAgent.researchProcess.queuedSummary');
			case 'running':
				return translate('researchAgent.researchProcess.runningSummary');
			case 'completed':
				return translate('researchAgent.researchProcess.completedSummary');
			case 'partial_success':
				return translate('researchAgent.researchProcess.partialSummary');
			case 'failed':
				return translate('researchAgent.researchProcess.failedSummary');
			default:
				return translate('researchAgent.capability.researchProcessUnavailable');
		}
	}
	if (name === 'query_published_findings') {
		if (result.data.scientific_absence === true)
			return translate('researchAgent.capability.absence');
		return translate('researchAgent.capability.findingCount', {
			findings: numberValue(result.data, 'finding_count'),
			evidence: numberValue(result.data, 'evidence_count')
		});
	}
	if (name === 'inspect_published_finding') {
		return translate('researchAgent.capability.findingEvidenceCount', {
			count: numberValue(result.data, 'evidence_total')
		});
	}
	if (name === 'record_finding_feedback') {
		return translate('researchAgent.capability.feedbackRecorded');
	}
	if (name === 'curate_finding') {
		return translate('researchAgent.capability.curationRecorded');
	}
	if (name === 'create_finding_version') {
		return result.data.finding
			? translate('researchAgent.capability.findingPublished')
			: translate('researchAgent.capability.findingAbstentionPublished');
	}
	if (name === 'create_finding_draft') {
		return translate('researchAgent.capability.findingDraftReady');
	}
	if (name === 'create_evidence_draft') {
		return translate('researchAgent.capability.evidenceDraftReady');
	}
	if (name === 'create_evidence_version') {
		return translate('researchAgent.capability.evidencePublished');
	}
	if (name === 'publish_agent_objective_analysis') {
		return translate('researchAgent.capability.agentAnalysisPublished', {
			count: numberValue(result.data, 'evidence_count')
		});
	}
	if (name === 'propose_objective_drafts') {
		return translate('researchAgent.capability.draftCount', {
			count: numberValue(result.data, 'draft_count')
		});
	}
	if (name === 'create_objective_candidate') {
		return translate('researchAgent.capability.objectiveCreated');
	}
	if (name === 'confirm_objective') {
		return translate('researchAgent.capability.objectiveConfirmed');
	}
	if (name === 'derive_objective') {
		return translate('researchAgent.capability.derivedDraftCount', {
			count: numberValue(result.data, 'draft_count')
		});
	}
	if (name === 'propose_research_plan') {
		return translate('researchAgent.capability.researchPlanDraftReady');
	}
	if (name === 'create_research_plan') {
		return translate('researchAgent.capability.researchPlanSaved');
	}
	if (name === 'assess_objective_quality') {
		return translate('researchAgent.capability.qualitySummary', {
			findings: numberValue(result.data, 'finding_count'),
			evidence: numberValue(result.data, 'total_evidence_count'),
			gaps: numberValue(result.data, 'scientific_gap_count'),
			failures: numberValue(result.data, 'technical_failure_count')
		});
	}
	if (name === 'preview_research_scope') {
		const counts = result.data.scope_counts;
		return translate('researchAgent.capability.scopeCount', {
			likely:
				counts && typeof counts === 'object' && 'likely_relevant' in counts
					? Number(counts.likely_relevant) || 0
					: 0,
			review:
				counts && typeof counts === 'object' && 'needs_inspection' in counts
					? Number(counts.needs_inspection) || 0
					: 0,
			excluded:
				counts && typeof counts === 'object' && 'confidently_out_of_scope' in counts
					? Number(counts.confidently_out_of_scope) || 0
					: 0
		});
	}
	if (name === 'inspect_objective_analysis' || name === 'start_objective_analysis') {
		return objectiveAnalysisSummary(result.data, translate);
	}
	return translate('researchAgent.capability.succeeded', { name: capabilityName(name, translate) });
}
export function resultTitle(message: ChatMessage, toolName: string | null, translate: Translate) {
	const result = message.tool_result;
	if (toolName === 'inspect_research_process' && result?.status === 'succeeded') {
		return translate('researchAgent.capability.researchProcessStatus');
	}
	const name = capabilityName(toolName, translate);
	if (result?.status === 'failed') return translate('researchAgent.capability.failed', { name });
	if (result?.status === 'queued') return translate('researchAgent.capability.queued', { name });
	return translate('researchAgent.capability.succeeded', { name });
}
export function resultStatusLabel(message: ChatMessage, translate: Translate) {
	switch (message.tool_result?.status) {
		case 'queued':
			return translate('researchAgent.capability.statusQueued');
		case 'failed':
			return translate('researchAgent.capability.statusFailed');
		default:
			return translate('researchAgent.capability.statusSucceeded');
	}
}
function objectiveAnalysisSummary(data: Record<string, unknown>, translate: Translate) {
	const analysis = data.analysis;
	if (!analysis || typeof analysis !== 'object' || !('status' in analysis)) {
		return translate('researchAgent.capability.analysisNotStarted');
	}
	switch (String(analysis.status)) {
		case 'queued':
			return translate('researchAgent.capability.analysisQueued');
		case 'running': {
			const progress = 'document_progress' in analysis ? analysis.document_progress : null;
			return translate('researchAgent.capability.analysisRunning', {
				current:
					progress && typeof progress === 'object' && 'current' in progress
						? Number(progress.current) || 0
						: 0,
				total:
					progress && typeof progress === 'object' && 'total' in progress
						? Number(progress.total) || 0
						: 0
			});
		}
		case 'succeeded':
			return translate('researchAgent.capability.analysisSucceeded');
		case 'failed':
			return translate('researchAgent.capability.analysisFailed');
		default:
			return translate('researchAgent.capability.analysisNotStarted');
	}
}
export function formatValue(value: unknown) {
	if (Array.isArray(value)) return value.map(String).join(', ');
	if (value && typeof value === 'object') return JSON.stringify(value);
	if (value === null || value === undefined || value === '') return '--';
	return String(value);
}
