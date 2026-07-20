import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
	createExperimentPlan,
	fetchExperimentPlans,
	updateExperimentPlan
} from './experimentPlans';

const fetchMock = vi.fn();

beforeEach(() => {
	fetchMock.mockReset();
	globalThis.fetch = fetchMock as typeof fetch;
});

function jsonResponse(body: unknown, init: ResponseInit = {}) {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' },
		...init
	});
}

describe('experimentPlans api helper', () => {
	it('creates objective-scoped experiment plans through the same-origin contract', async () => {
		fetchMock.mockResolvedValueOnce(
			jsonResponse({
				plan_id: 'exp_1',
				collection_id: 'col_1',
				objective_id: 'obj_1',
				title: 'Preheating matrix',
				content: 'Compare 25 C and 150 C builds.',
				status: 'draft',
				source_message_id: 'msg_1',
				source_links: [],
				metadata: {},
				created_by: 'expert-a',
				created_at: '2026-07-13T00:00:00+00:00',
				updated_at: '2026-07-13T00:00:00+00:00'
			})
		);

		const plan = await createExperimentPlan('col_1', 'obj_1', {
			title: 'Preheating matrix',
			content: 'Compare 25 C and 150 C builds.',
			source_message_id: 'msg_1',
			source_links: [
				{
					kind: 'evidence',
					label: 'Source 1',
					href: '/collections/col_1/documents/paper-a?evidence_id=ev_1'
				}
			],
			metadata: { source: 'chat' }
		});
		const [path, init] = fetchMock.mock.calls[0];

		expect(path).toBe('/api/v1/collections/col_1/objectives/obj_1/experiment-plans');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body as string)).toMatchObject({
			title: 'Preheating matrix',
			source_message_id: 'msg_1',
			metadata: { source: 'chat' }
		});
		expect(plan.plan_id).toBe('exp_1');
	});

	it('lists and updates objective-scoped experiment plans', async () => {
		fetchMock
			.mockResolvedValueOnce(jsonResponse({ collection_id: 'col_1', objective_id: 'obj_1', items: [] }))
			.mockResolvedValueOnce(
				jsonResponse({
					plan_id: 'exp_1',
					collection_id: 'col_1',
					objective_id: 'obj_1',
					title: 'Edited plan',
					content: 'Add controls.',
					status: 'ready_for_review',
					source_message_id: null,
					source_links: [],
					metadata: {},
					created_by: 'expert-a',
					created_at: '2026-07-13T00:00:00+00:00',
					updated_at: '2026-07-13T01:00:00+00:00'
				})
			);

		await fetchExperimentPlans('col_1', 'obj_1');
		const updated = await updateExperimentPlan('col_1', 'obj_1', 'exp_1', {
			title: 'Edited plan',
			content: 'Add controls.',
			status: 'ready_for_review'
		});

		expect(fetchMock.mock.calls[0][0]).toBe(
			'/api/v1/collections/col_1/objectives/obj_1/experiment-plans'
		);
		expect(fetchMock.mock.calls[1][0]).toBe(
			'/api/v1/collections/col_1/objectives/obj_1/experiment-plans/exp_1'
		);
		expect(fetchMock.mock.calls[1][1].method).toBe('PATCH');
		expect(updated.status).toBe('ready_for_review');
	});
});
