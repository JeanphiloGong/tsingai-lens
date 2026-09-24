import { requestJson } from './api';

export type FeedbackCaseSummary = {
	case_id: string;
	collection_id: string;
	status: string;
	anchor_message_id: string;
	problem_type: string | null;
	confidence: number | null;
	needs_human_review: boolean;
	created_at: string;
	question_preview: string;
	answer_preview: string;
	document_titles: string[];
	coverage_status: string;
};

export type FeedbackCaseDetail = FeedbackCaseSummary & {
	session_id: string;
	source_signals: Array<{
		feedback_id: string;
		rating: string;
		reason: string | null;
		comment: string | null;
		created_at: string;
	}>;
	question: string;
	answer: string;
	requested_scope: Array<Record<string, unknown>>;
	inspected_sources: Array<Record<string, unknown>>;
	omitted_candidates: Array<Record<string, unknown>>;
	claim_support: Array<Record<string, unknown>>;
	gaps: string[];
	coverage_status: string;
	analysis: {
		problem_type: string;
		confidence: number;
		suggested_target: string | null;
		model: string;
		result_id: string;
		coverage_status: string;
	} | null;
	annotation: Record<string, unknown> | null;
	current_annotation_digest: string | null;
	technical_error: string | null;
	updated_at: string;
};

type FeedbackCaseList = {
	items: FeedbackCaseSummary[];
	limit: number;
	offset: number;
};

function path(collectionId: string, caseId = '') {
	const suffix = caseId ? `/${encodeURIComponent(caseId)}` : '';
	return `/feedback-cases${suffix}?collection_id=${encodeURIComponent(collectionId)}`;
}

export async function fetchFeedbackCases(
	collectionId: string,
	options: {
		status?: string;
		problemType?: string;
		needsHumanReview?: boolean;
		limit?: number;
		offset?: number;
	} = {}
) {
	const params = new URLSearchParams({ collection_id: collectionId });
	if (options.status) params.set('status', options.status);
	if (options.problemType) params.set('problem_type', options.problemType);
	if (options.needsHumanReview !== undefined) {
		params.set('needs_human_review', String(options.needsHumanReview));
	}
	params.set('limit', String(options.limit ?? 50));
	params.set('offset', String(options.offset ?? 0));
	return (await requestJson(`/feedback-cases?${params.toString()}`, { method: 'GET' })) as FeedbackCaseList;
}

export async function fetchFeedbackCase(collectionId: string, caseId: string) {
	return (await requestJson(path(collectionId, caseId), { method: 'GET' })) as FeedbackCaseDetail;
}
