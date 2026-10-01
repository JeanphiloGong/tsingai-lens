import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_feedback';
const datasetId = 'fdset_sft';
const sampleId = 'sample_1';

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

async function mockTaskDataset(page: Page, startEmpty = false) {
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'zh'));
	const empty = startEmpty;
	let buildingReads = 0;
	let revision = 1;
	let generation = 1;
	let target = '基于图注证据生成的候选正确回答。';
	let status = 'needs_confirmation';
	const actions: Array<{ action: string; key: string | undefined }> = [];

	await page.route('**/*', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(json({ user: { user_id: 'user_feedback', email: 'reviewer@example.com', display_name: 'Reviewer' } }));
		}
		if (path === '/api/v1/collections' && request.method() === 'GET') {
			return route.fulfill(json({ items: [{ collection_id: collectionId, name: 'Feedback fixture', status: 'ready', documents: [] }] }));
		}
		if (path === `/api/v1/collections/${collectionId}` && request.method() === 'GET') {
			return route.fulfill(json({ collection_id: collectionId, name: 'Feedback fixture', status: 'ready', documents: [] }));
		}
		if (path === '/api/v1/feedback-datasets') {
			const items = [
				{ dataset_id: datasetId, collection_id: collectionId, name: '文献问答 SFT', task_type: 'sft', construction_spec: { mode: 'automatic_feedback_workbench' }, spec_version: 1, created_by: 'user_feedback', created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z' },
				{ dataset_id: 'fdset_preference', collection_id: collectionId, name: '回答偏好', task_type: 'preference', construction_spec: { mode: 'automatic_feedback_workbench' }, spec_version: 1, created_by: 'user_feedback', created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z' },
				{ dataset_id: 'fdset_evaluation', collection_id: collectionId, name: '评测', task_type: 'evaluation', construction_spec: { mode: 'automatic_feedback_workbench' }, spec_version: 1, created_by: 'user_feedback', created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z' }
			];
			return route.fulfill(json({ items, limit: 200, offset: 0 }));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}` && request.method() === 'GET') {
			return route.fulfill(json({
				dataset_id: datasetId, collection_id: collectionId, name: '预热条件问答纠错', task_type: 'sft',
				construction_spec: { mode: 'automatic_feedback_workbench' }, spec_version: 1, created_by: 'user_feedback',
				created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z'
			}));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples` && request.method() === 'GET') {
			if (empty) return route.fulfill(json({items: [], total: 0, limit: 200, offset: 0}));
			if (startEmpty && status === 'pending' && ++buildingReads > 1) status = 'needs_confirmation';
			return route.fulfill(json({
				items: [{ sample_id: sampleId, dataset_id: datasetId, source_case_id: 'case_1', status,
					current_revision_id: `revision_${revision}`, confirmed_revision_id: status === 'confirmed' ? `revision_${revision}` : null,
					generation, missing_reasons: [], created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z',
					confirmed_by: status === 'confirmed' ? 'user_feedback' : null, confirmed_at: status === 'confirmed' ? '2026-09-29T01:00:00Z' : null
				}], total: 1, limit: 200, offset: 0
			}));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples/${sampleId}` && request.method() === 'GET') {
			return route.fulfill(json({
				sample: { sample_id: sampleId, dataset_id: datasetId, source_case_id: 'case_1', status,
					current_revision_id: `revision_${revision}`, confirmed_revision_id: status === 'confirmed' ? `revision_${revision}` : null,
					generation, missing_reasons: [], created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z',
					confirmed_by: status === 'confirmed' ? 'user_feedback' : null, confirmed_at: status === 'confirmed' ? '2026-09-29T01:00:00Z' : null
				},
				source_case: { case_id: 'case_1', collection_id: collectionId, session_id: 'session_1', anchor_message_id: 'answer_1',
					status: 'needs_annotation', question: '比较文献 A、B 的预热条件。', answer: '文献 B 没有预热。',
					requested_scope: [], inspected_sources: [{ document_title: '文献 B', source_ref: 'source_b', quote: '图注原文' }],
					omitted_candidates: [], gaps: [], context_snapshot: {}
				},
				current_revision: { revision_id: `revision_${revision}`, sample_id: sampleId, revision_no: revision, author_kind: revision === 1 ? 'worker' : 'human',
					content: { schema_version: 'literature-sft.v1', messages: [{ role: 'user', content: '比较文献 A、B 的预热条件。' }],
						context: [{ document_title: '文献 B', text: '图注原文' }], target, evidence: [{ document_title: '文献 B', text: '图注原文' }] },
					content_digest: 'a'.repeat(64), input_digest: 'b'.repeat(64), construction_spec_version: 1, provenance: {},
					created_at: '2026-09-29T00:00:00Z', created_by: revision === 1 ? null : 'user_feedback', job_id: revision === 1 ? 'job_1' : null },
				confirmed_revision: status === 'confirmed' ? { revision_id: `revision_${revision}`, sample_id: sampleId, revision_no: revision, author_kind: 'human',
					content: { schema_version: 'literature-sft.v1', messages: [{ role: 'user', content: '比较文献 A、B 的预热条件。' }], context: [{ document_title: '文献 B', text: '图注原文' }], target, evidence: [{ document_title: '文献 B', text: '图注原文' }] }, content_digest: 'a'.repeat(64), input_digest: 'b'.repeat(64), construction_spec_version: 1, provenance: {}, created_at: '2026-09-29T00:00:00Z', created_by: 'user_feedback', job_id: null } : null
			}));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples/${sampleId}` && request.method() === 'PATCH') {
			target = String(request.postDataJSON().content.target);
			revision += 1;
			status = 'needs_confirmation';
			return route.fulfill(json({ sample_id: sampleId, dataset_id: datasetId, source_case_id: 'case_1', status, current_revision_id: `revision_${revision}`, confirmed_revision_id: null, generation: 1, missing_reasons: [], created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z', confirmed_by: null, confirmed_at: null }));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples/${sampleId}/confirm` && request.method() === 'POST') {
			status = 'confirmed';
			return route.fulfill(json({ sample_id: sampleId, dataset_id: datasetId, source_case_id: 'case_1', status, current_revision_id: `revision_${revision}`, confirmed_revision_id: `revision_${revision}`, generation: 1, missing_reasons: [], created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z', confirmed_by: 'user_feedback', confirmed_at: '2026-09-29T01:00:00Z' }));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples/${sampleId}/actions` && request.method() === 'POST') {
			const action = String(request.postDataJSON().action);
			actions.push({ action, key: request.headers()['idempotency-key'] });
			generation += 1;
			status = action === 'discard' ? 'discarded' : action === 'restore' ? 'needs_confirmation' : 'pending';
			return route.fulfill(json({ sample_id: sampleId, dataset_id: datasetId, status, generation }));
		}
		return route.fulfill(json({ detail: `unhandled test route: ${request.method()} ${path}` }, 404));
	});
	return { actions, setStatus: (next: string) => { status = next; } };
}

test('open the fixed SFT workbench and receive a Worker candidate', async ({ page }) => {
	await mockTaskDataset(page);
	await page.goto(`/collections/${collectionId}/feedback`);
	await expect(page.getByRole('button', {name: /回答偏好/})).toBeVisible();
	await expect(page.getByRole('button', {name: /评测/})).toBeVisible();
	await page.getByRole('button', {name: /文献问答.*SFT/}).click();
	await expect(page).toHaveURL(new RegExp(`/feedback/datasets/${datasetId}$`));
	await expect(page.getByRole('textbox', {name: '回答内容'})).toHaveValue('基于图注证据生成的候选正确回答。');
	await page.getByRole('button', {name: '确认样本', exact: true}).click();
	await page.getByRole('checkbox', {name: '选择导出此样本'}).check();
});

for (const width of [1440, 390]) {
	test(`SFT sample editor is usable at ${width}px`, async ({ page }, testInfo) => {
		await mockTaskDataset(page);
		await page.setViewportSize({ width, height: 900 });
		await page.goto(`/collections/${collectionId}/feedback/datasets/${datasetId}`);

		await expect(page.getByRole('heading', { name: '文献问答 · SFT' })).toBeVisible();
		await expect(page.getByRole('heading', { name: '正确回答' })).toBeVisible();
		await expect(page.getByRole('textbox', { name: '片段' })).toHaveValue('图注原文');
		const answer = page.getByRole('textbox', { name: '回答内容' });
		await answer.fill('人工核对后的回答。');
		await page.getByRole('button', { name: '保存修改' }).click();
		await expect(page.getByRole('status')).toContainText('修改已保存');
		await page.getByRole('button', { name: '确认样本' }).click();
		await expect(page.getByText('已确认', { exact: true })).toBeVisible();
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
		await page.screenshot({ path: testInfo.outputPath(`task-dataset-${width}.png`), fullPage: true });
	});
}

test('a sample can be rebuilt, discarded, restored, and retried', async ({ page }) => {
	const mock = await mockTaskDataset(page);
	await page.goto(`/collections/${collectionId}/feedback/datasets/${datasetId}`);
	await expect(page.getByRole('heading', { name: '正确回答' })).toBeVisible();
	await page.locator('.sample-options > summary').click();
	await page.getByRole('textbox', { name: '退回意见' }).fill('重新核对文献 B 的图注。');
	await page.getByRole('button', { name: '退回重建' }).click();
	await expect(page.getByText('构建任务已提交。')).toBeVisible();
	await expect(page.getByRole('button', { name: '丢弃样本' })).toBeVisible();
	await page.getByRole('button', { name: '丢弃样本' }).click();
	await expect(page.getByRole('button', { name: '恢复样本' })).toBeVisible();
	await page.getByRole('button', { name: '恢复样本' }).click();
	await expect(page.getByRole('button', { name: '确认样本' })).toBeEnabled();

	mock.setStatus('build_failed');
	await page.getByRole('button', { name: '刷新样本队列' }).click();
	await page.locator('.sample-options > summary').click();
	await expect(page.getByRole('button', { name: '重试构建' })).toBeVisible();
	await page.getByRole('button', { name: '重试构建' }).click();
	await expect(page.getByText('构建任务已提交。')).toBeVisible();
	expect(mock.actions.map(({ action }) => action)).toEqual(['rebuild', 'discard', 'restore', 'retry']);
	expect(mock.actions.every(({ key }) => Boolean(key))).toBe(true);
});
