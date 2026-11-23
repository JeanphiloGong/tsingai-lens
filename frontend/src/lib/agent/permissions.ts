import { requestJson } from '../../routes/_shared/api';

export type AgentPermission = {
	mode: 'read_only' | 'confirm' | 'auto';
	actions: string[];
	expires_at: string | null;
	revision: number;
};

export const AGENT_WRITE_ACTIONS = [
	'start_research_process',
	'create_objective_candidate',
	'confirm_objective',
	'start_objective_analysis',
	'create_paper_experiment_revision',
	'create_finding_version',
	'record_finding_feedback',
	'curate_finding',
	'create_research_plan',
	'revise_research_plan'
] as const;

export type ChatPermission = AgentPermission;

function permissionPath(sessionId: string) {
	return `/conversations/${encodeURIComponent(sessionId)}/permissions`;
}

export async function fetchChatPermission(sessionId: string) {
	return (await requestJson(permissionPath(sessionId))) as ChatPermission;
}

export async function updateChatPermission(
	sessionId: string,
	permission: ChatPermission,
	options: { allActions?: boolean } = {}
) {
	return (await requestJson(permissionPath(sessionId), {
		method: 'PUT',
		body: JSON.stringify({
			mode: permission.mode,
			actions: permission.actions,
			all_actions: options.allActions ?? false,
			expires_at: permission.expires_at,
			expected_revision: permission.revision
		})
	})) as ChatPermission;
}
