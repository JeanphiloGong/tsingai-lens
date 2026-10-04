import { expect, test, type Page } from '@playwright/test';

const datasetId = 'fdset_preference_review';
const path = `/collections/col_preference_review/feedback/datasets/${datasetId}`;
const rationale = '回答 B 的 200 C 与文献 B 的图注一致；回答 A 将未报告条件误写成没有预热。';

async function mockPreference(page: Page, choice: string | null = 'b', failure: 'save' | 'confirm' | null = null) {
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'zh'));
	let revision = 1;
	let status = 'needs_confirmation';
	let failed = false;
	let content = {
		schema_version: 'literature-preference.v1', messages: [{ role: 'user', content: '文献 B 的预热温度是什么？' }],
		context: [{ document_title: '文献 B', text: 'Specimens were preheated at 200 C.' }],
		evidence: [{ document_title: '文献 B', text: 'Specimens were preheated at 200 C.' }],
		response_a: '文献 B 没有预热。', response_b: '文献 B 预热至 200 C。',
		suggested_preference: choice, rationale: choice ? rationale : '', human_preference: null as string | null
	};
	const requests: Array<{ method: string; payload: { expected_revision_id: string; expected_generation?: number; content?: typeof content } }> = [];
	const sample = () => ({ sample_id: 'sample_preference', dataset_id: datasetId, source_case_id: 'case_preference',
		status, current_revision_id: `revision_${revision}`, confirmed_revision_id: status === 'confirmed' ? `revision_${revision}` : null,
		generation: 1, missing_reasons: [], created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:00Z' });
	await page.route('**/api/v1/**', async route => {
		const request = route.request();
		const urlPath = new URL(request.url()).pathname;
		let body: unknown = {};
		if (urlPath.endsWith('/auth/me')) body = { user: { user_id: 'reviewer', email: 'reviewer@example.test' } };
		else if (urlPath === '/api/v1/collections/col_preference_review') body = { collection_id: 'col_preference_review', name: '预热条件核查', documents: [], status: 'ready' };
		else if (urlPath === `/api/v1/feedback-datasets/${datasetId}`) body = { dataset_id: datasetId, collection_id: 'col_preference_review', task_type: 'preference', construction_spec: {}, spec_version: 1 };
		else if (urlPath.endsWith('/samples')) body = { items: [sample()], total: 1 };
		else if (urlPath.endsWith('/exports')) body = { items: [] };
		else if (urlPath.endsWith('/samples/sample_preference') && request.method() === 'PATCH') {
			const payload = request.postDataJSON();
			requests.push({ method: 'PATCH', payload });
			if (failure === 'save' && !failed) {
				failed = true;
				return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'sample_revision_stale' }) });
			}
			expect(payload.expected_revision_id).toBe(`revision_${revision}`);
			expect(payload.expected_generation).toBe(1);
			content = payload.content;
			revision += 1;
			body = sample();
		} else if (urlPath.endsWith('/samples/sample_preference/confirm')) {
			const payload = request.postDataJSON();
			requests.push({ method: 'POST', payload });
			expect(payload.expected_revision_id).toBe(`revision_${revision}`);
			expect(content.human_preference).not.toBeNull();
			if (failure === 'confirm' && !failed) {
				failed = true;
				return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporarily_unavailable' }) });
			}
			status = 'confirmed';
			body = sample();
		} else if (urlPath.endsWith('/samples/sample_preference')) body = {
			sample: sample(), source_case: { case_id: 'case_preference', question: content.messages[0].content, answer: content.response_a,
				status: 'needs_annotation', requested_scope: [], inspected_sources: [], omitted_candidates: [], gaps: [], context_snapshot: {} },
			current_revision: { revision_id: `revision_${revision}`, revision_no: revision, author_kind: revision === 1 ? 'worker' : 'human', content, provenance: {} },
			confirmed_revision: null
		};
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
	});
	return requests;
}

for (const [choice, label] of [['a', 'A 更好'], ['b', 'B 更好'], ['tie', '相当'], ['unclear', '无法判断']]) {
	test(`a reviewer can accept the ${choice} recommendation and confirm its saved revision`, async ({ page }) => {
		const requests = await mockPreference(page, choice);
		await page.goto(path);
		const recommendation = page.getByRole('region', { name: 'Worker 建议' });
		await expect(recommendation.getByText(label, { exact: true })).toBeVisible();
		await expect(recommendation.getByText(rationale, { exact: true })).toBeVisible();
		await expect(page.getByRole('radio', { name: label, exact: true })).not.toBeChecked();
		await expect(page.getByRole('button', { name: '确认样本', exact: true })).toBeDisabled();
		await page.getByRole('button', { name: '采用建议', exact: true }).click();
		await expect(page.getByRole('radio', { name: label, exact: true })).toBeChecked();
		await page.getByRole('button', { name: '确认样本', exact: true }).click();
		await expect(page.locator('.editor-column .status')).toHaveText('已确认');
		expect(requests.map(request => request.method)).toEqual(['PATCH', 'POST']);
		expect(requests[0].payload.content?.human_preference).toBe(choice);
		expect(requests[0].payload.content?.suggested_preference).toBe(choice);
		expect(requests[1].payload.expected_revision_id).toBe('revision_2');
	});
}

test('a mobile reviewer can override the worker without changing its recorded opinion', async ({ page }, testInfo) => {
	const requests = await mockPreference(page);
	await page.setViewportSize({ width: 390, height: 900 });
	await page.goto(path);
	await expect(page.getByRole('region', { name: 'Worker 建议' })).toContainText(rationale);
	await page.getByRole('radio', { name: 'A 更好' }).check();
	await page.getByRole('button', { name: '确认并下一条', exact: true }).click();
	await expect(page.locator('.editor-column .status')).toHaveText('已确认');
	expect(requests[0].payload.content?.human_preference).toBe('a');
	expect(requests[0].payload.content?.suggested_preference).toBe('b');
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
	await page.screenshot({ path: testInfo.outputPath('preference-reviewed-mobile.png'), fullPage: true });
});

test('legacy candidates with no recommendation still allow an explicit human decision', async ({ page }) => {
	await mockPreference(page, null);
	await page.goto(path);
	await expect(page.getByRole('region', { name: 'Worker 建议' })).toContainText('尚无建议');
	await expect(page.getByRole('button', { name: '采用建议', exact: true })).toHaveCount(0);
	await page.getByRole('radio', { name: 'B 更好' }).check();
	await page.getByRole('button', { name: '确认样本', exact: true }).click();
	await expect(page.locator('.editor-column .status')).toHaveText('已确认');
});

for (const failure of ['save', 'confirm'] as const) {
	test(`a failed ${failure} preserves the choice and retries without confirming an old revision`, async ({ page }) => {
		const requests = await mockPreference(page, 'b', failure);
		await page.goto(path);
		await page.getByRole('button', { name: '采用建议', exact: true }).click();
		await page.getByRole('button', { name: '确认样本', exact: true }).click();
		await expect(page.locator('.editor-column [role="alert"]')).toBeVisible();
		await expect(page.getByRole('radio', { name: 'B 更好' })).toBeChecked();
		if (failure === 'save') expect(requests.map(request => request.method)).toEqual(['PATCH']);
		await page.getByRole('button', { name: '确认样本', exact: true }).click();
		await expect(page.locator('.editor-column .status')).toHaveText('已确认');
		expect(requests.map(request => request.method)).toEqual(failure === 'save' ? ['PATCH', 'PATCH', 'POST'] : ['PATCH', 'POST', 'POST']);
	});
}
