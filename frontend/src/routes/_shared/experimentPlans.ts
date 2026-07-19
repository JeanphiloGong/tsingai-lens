import { requestJson } from './api';
import type { GoalSourceLink } from './goalSessions';

export type ExperimentPlanStatus = 'draft' | 'ready_for_review' | 'archived';

export type ExperimentPlan = {
	plan_id: string;
	collection_id: string;
	goal_id: string;
	title: string;
	content: string;
	status: ExperimentPlanStatus;
	source_message_id: string | null;
	source_links: GoalSourceLink[];
	metadata: Record<string, unknown>;
	created_by: string | null;
	created_at: string;
	updated_at: string;
};

export type ExperimentPlanList = {
	collection_id: string;
	goal_id: string;
	items: ExperimentPlan[];
};

type CreateExperimentPlanOptions = {
	title: string;
	content: string;
	source_message_id?: string | null;
	source_links?: GoalSourceLink[];
	metadata?: Record<string, unknown>;
};

type UpdateExperimentPlanOptions = {
	title: string;
	content: string;
	status: ExperimentPlanStatus;
};

function experimentPlanPath(collectionId: string, goalId: string, planId = '') {
	const base = `/collections/${encodeURIComponent(collectionId)}/goals/${encodeURIComponent(
		goalId
	)}/experiment-plans`;
	return planId ? `${base}/${encodeURIComponent(planId)}` : base;
}

export async function createExperimentPlan(
	collectionId: string,
	goalId: string,
	options: CreateExperimentPlanOptions
) {
	return (await requestJson(experimentPlanPath(collectionId, goalId), {
		method: 'POST',
		body: JSON.stringify({
			title: options.title,
			content: options.content,
			source_message_id: options.source_message_id ?? null,
			source_links: options.source_links ?? [],
			metadata: options.metadata ?? {}
		})
	})) as ExperimentPlan;
}

export async function fetchExperimentPlans(collectionId: string, goalId: string) {
	return (await requestJson(experimentPlanPath(collectionId, goalId), {
		method: 'GET'
	})) as ExperimentPlanList;
}

export async function updateExperimentPlan(
	collectionId: string,
	goalId: string,
	planId: string,
	options: UpdateExperimentPlanOptions
) {
	return (await requestJson(experimentPlanPath(collectionId, goalId, planId), {
		method: 'PATCH',
		body: JSON.stringify(options)
	})) as ExperimentPlan;
}
