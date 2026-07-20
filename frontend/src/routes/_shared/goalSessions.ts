import { requestJson } from './api';

export type GoalAnswerMode = 'grounded' | 'hybrid' | 'general';

export type GoalSourceMode =
	| 'collection_grounded'
	| 'collection_limited'
	| 'general_fallback'
	| 'general_only';

export type GoalSourceLink = {
	kind: 'document' | 'evidence';
	label: string;
	href: string;
};

export type GoalSession = {
	session_id: string;
	user_id: string;
	collection_id: string;
	focused_material_id: string | null;
	focused_paper_id: string | null;
	focused_objective_id: string | null;
	goal_text: string | null;
	goal_brief_json: Record<string, unknown>;
	answer_mode: GoalAnswerMode;
	rolling_summary: string;
	last_evidence_ids: string[];
	last_material_ids: string[];
	last_paper_ids: string[];
	collection_data_version: string | null;
	created_at: string;
	updated_at: string;
};

export type GoalSessionMessage = {
	message_id: string;
	session_id: string;
	role: 'user' | 'assistant';
	content?: string;
	answer?: string;
	source_mode?: GoalSourceMode;
	used_evidence_ids?: string[];
	warnings?: string[];
	links?: Record<string, string>;
	source_links?: GoalSourceLink[];
	review_gate?: string | null;
	created_at: string;
};

export type GoalSessionMessageResponse = {
	message_id: string;
	session_id: string;
	role: 'assistant';
	answer: string;
	content: string;
	source_mode: GoalSourceMode;
	used_evidence_ids: string[];
	warnings: string[];
	links: Record<string, string>;
	source_links: GoalSourceLink[];
	review_gate: string | null;
	created_at: string;
};

type CreateGoalSessionOptions = {
	collection_id: string;
	focused_material_id?: string | null;
	focused_paper_id?: string | null;
	focused_objective_id?: string | null;
	goal_text?: string | null;
	goal_brief_json?: Record<string, unknown>;
	answer_mode?: GoalAnswerMode;
};

type UpdateGoalSessionOptions = Partial<CreateGoalSessionOptions>;

function goalSessionPath(sessionId = '') {
	return `/goal-sessions${sessionId ? `/${encodeURIComponent(sessionId)}` : ''}`;
}

export async function createGoalSession(options: CreateGoalSessionOptions) {
	return (await requestJson(goalSessionPath(), {
		method: 'POST',
		body: JSON.stringify({
			collection_id: options.collection_id,
			focused_material_id: options.focused_material_id ?? null,
			focused_paper_id: options.focused_paper_id ?? null,
			focused_objective_id: options.focused_objective_id ?? null,
			goal_text: options.goal_text ?? null,
			goal_brief_json: options.goal_brief_json ?? {},
			answer_mode: options.answer_mode ?? 'hybrid'
		})
	})) as GoalSession;
}

export async function fetchGoalSession(sessionId: string) {
	return (await requestJson(goalSessionPath(sessionId), {
		method: 'GET'
	})) as GoalSession;
}

export async function updateGoalSession(sessionId: string, options: UpdateGoalSessionOptions) {
	return (await requestJson(goalSessionPath(sessionId), {
		method: 'PATCH',
		body: JSON.stringify(options)
	})) as GoalSession;
}

export async function postGoalSessionMessage(
	sessionId: string,
	message: string,
	pageContext: Record<string, unknown> = {}
) {
	return (await requestJson(`${goalSessionPath(sessionId)}/messages`, {
		method: 'POST',
		body: JSON.stringify({
			message,
			page_context: pageContext
		})
	})) as GoalSessionMessageResponse;
}

export async function fetchGoalSessionMessages(sessionId: string) {
	const data = (await requestJson(`${goalSessionPath(sessionId)}/messages`, {
		method: 'GET'
	})) as { session_id: string; items: GoalSessionMessage[] };
	return data.items;
}
