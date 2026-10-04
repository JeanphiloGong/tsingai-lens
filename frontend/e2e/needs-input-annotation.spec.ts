import { expect, test } from '@playwright/test';

for (const taskType of ['sft', 'preference', 'evaluation'] as const) {
	for (const width of [1440, 390]) {
	test(`${taskType} missing candidate can be completed, saved and confirmed at ${width}px`, async ({ page }, testInfo) => {
		await page.setViewportSize({ width, height: 900 });
		await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'zh'));
		const collectionId = 'col_input';
		const datasetId = `fdset_${taskType}`;
		const dataset = { dataset_id: datasetId, collection_id: collectionId, name: `预热条件 ${taskType}`,
			task_type: taskType, construction_spec: {}, spec_version: 1 };
		let status = 'needs_input';
		let content: Record<string, unknown> | null = null;
		const sample = () => ({ sample_id: 'sample_input', dataset_id: datasetId, source_case_id: 'case_input', status,
			current_revision_id: content ? 'revision_human' : null, confirmed_revision_id: status === 'confirmed' ? 'revision_human' : null,
			generation: 1, missing_reasons: content ? [] : ['readable_evidence_missing'], created_at: '2026-09-30T00:00:00Z', updated_at: '2026-09-30T00:00:00Z' });
		await page.route('**/api/v1/**', async route => {
			const request = route.request();
			const path = new URL(request.url()).pathname;
			let body: unknown = {};
			if (path.endsWith('/auth/me')) body = { user: { user_id: 'user_input', email: 'input@example.test' } };
			else if (path === `/api/v1/collections/${collectionId}`) body = { collection_id: collectionId, name: '预热文献', documents: [], status: 'ready' };
			else if (path === `/api/v1/feedback-datasets/${datasetId}`) body = dataset;
			else if (path.endsWith('/samples')) body = { items: [sample()], total: 1, limit: 200, offset: 0 };
			else if (path.endsWith('/exports')) body = { items: [], limit: 50, offset: 0 };
			else if (path.endsWith('/samples/sample_input') && request.method() === 'PATCH') {
				const payload = request.postDataJSON();
				expect(payload.expected_revision_id).toBeNull();
				expect(payload.expected_generation).toBe(1);
				expect(payload.content.context).toEqual([{ document_title: '文献 B', text: '预热温度为 200 C。' }]);
				if (taskType === 'evaluation') expect(payload.content.criteria).toEqual(['必须给出 200 C。', '不能外推到其他预热条件。']);
				content = payload.content;
				status = 'needs_confirmation';
				body = sample();
			} else if (path.endsWith('/samples/sample_input/confirm')) {
				expect(request.postDataJSON().expected_revision_id).toBe('revision_human');
				status = 'confirmed';
				body = sample();
			} else if (path.endsWith('/samples/sample_input')) body = {
				sample: sample(), source_case: { case_id: 'case_input', question: '文献 B 的预热温度是什么？', answer: '没有预热。',
					status: 'needs_annotation', requested_scope: [], inspected_sources: [], omitted_candidates: [], gaps: [], context_snapshot: {} },
				current_revision: content ? { revision_id: 'revision_human', revision_no: 1, content, provenance: {}, author_kind: 'human' } : null,
				confirmed_revision: null
			};
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
		});
		await page.goto(`/collections/${collectionId}/feedback/datasets/${datasetId}`);
		await expect(page.getByText('待补充', { exact: true }).last()).toBeVisible();
		await page.getByRole('button', { name: '添加证据片段' }).click();
		await page.getByRole('textbox', { name: '文献标题', exact: true }).fill('文献 B');
		await page.getByRole('textbox', { name: '片段', exact: true }).fill('预热温度为 200 C。');
		if (taskType === 'sft') await page.getByRole('textbox', { name: '回答内容' }).fill('文献 B 的预热温度为 200 C。');
		if (taskType === 'preference') {
			await page.getByRole('textbox', { name: '回答 A', exact: true }).fill('没有预热。');
			await page.getByRole('textbox', { name: '回答 B', exact: true }).fill('预热温度为 200 C。');
			await page.getByRole('radio', { name: 'B 更好' }).check();
		}
		if (taskType === 'evaluation') {
			await page.getByRole('textbox', { name: '参考答案' }).fill('预热温度为 200 C。');
			await page.getByRole('textbox', { name: '评分标准', exact: true }).fill('待删除的标准。');
			await page.getByRole('button', { name: '添加标准', exact: true }).click();
			await expect(page.getByRole('button', { name: '保存修改', exact: true })).toBeDisabled();
			await page.getByRole('textbox', { name: '评分标准 2', exact: true }).fill('必须给出 200 C。');
			await page.getByRole('button', { name: '删除评分标准 1', exact: true }).click();
			await expect(page.getByRole('textbox', { name: '评分标准', exact: true })).toHaveValue('必须给出 200 C。');
			await page.getByRole('button', { name: '添加标准', exact: true }).click();
			await page.getByRole('textbox', { name: '评分标准 2', exact: true }).fill('不能外推到其他预热条件。');
		}
		await page.getByRole('button', { name: '保存修改', exact: true }).click();
		await expect(page.getByRole('status')).toContainText('修改已保存');
		if (taskType === 'evaluation') {
			await page.reload();
			await expect(page.locator('.criterion-row textarea')).toHaveCount(2);
			await expect(page.getByRole('textbox', { name: '评分标准', exact: true })).toHaveValue('必须给出 200 C。');
			await expect(page.getByRole('textbox', { name: '评分标准 2', exact: true })).toHaveValue('不能外推到其他预热条件。');
		}
		await page.getByRole('button', { name: '确认样本', exact: true }).click();
		await expect(page.getByRole('region', { name: '样本编辑器' }).getByText('已确认', { exact: true })).toBeVisible();
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
		expect(overflow).toBe(false);
		await page.screenshot({ path: testInfo.outputPath(`${taskType}-confirmed-${width}.png`), fullPage: true });
	});
	}
}
