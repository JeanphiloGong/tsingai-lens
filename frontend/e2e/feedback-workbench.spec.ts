import { expect, test, type Page } from '@playwright/test';

const workspaceId = 'col_feedback';
const datasetId = 'fdset_feedback';
const caseId = 'case_feedback_private';

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify({
			code: status >= 400 ? 200205 : 200,
			message: status >= 400 ? 'Unavailable' : 'success',
			data: body,
			meta: null
		})
	};
}

async function mockTaskEntry(page: Page, withExport = false) {
	await page.addInitScript(() => localStorage.setItem('retrieval.lang', 'zh'));
	await page.route('**/*', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (!path.startsWith('/api/v1/') && !path.startsWith('/user-api/v1/')) return route.continue();
		if (path === '/user-api/v1/me/permissions') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ permission_codes: [] })
			});
		}
		if (path === '/user-api/v1/me') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					user_id: 'user_feedback',
					email: 'reviewer@example.com',
					display_name: 'Reviewer'
				})
			});
		}
		if (path === '/api/v1/workspaces' && request.method() === 'GET') {
			return route.fulfill(
				json({
					items: [
						{
							workspace_id: workspaceId,
							name: 'Feedback fixture',
							status: 'ready',
							documents: []
						}
					]
				})
			);
		}
		if (path === `/api/v1/workspaces/${workspaceId}` && request.method() === 'GET') {
			return route.fulfill(
				json({
					workspace_id: workspaceId,
					name: 'Feedback fixture',
					status: 'ready',
					documents: []
				})
			);
		}
		if (path === '/api/v1/feedback-datasets' && request.method() === 'GET') {
			const items = [
				{
					dataset_id: datasetId,
					workspace_id: workspaceId,
					name: '文献问答 SFT',
					task_type: 'sft',
					construction_spec: { mode: 'automatic_feedback_workbench' },
					spec_version: 1,
					created_by: 'user_feedback',
					created_at: '2026-09-29T00:00:00Z',
					updated_at: '2026-09-29T00:00:00Z'
				},
				{
					dataset_id: 'fdset_feedback_preference',
					workspace_id: workspaceId,
					name: '回答偏好',
					task_type: 'preference',
					construction_spec: { mode: 'automatic_feedback_workbench' },
					spec_version: 1,
					created_by: 'user_feedback',
					created_at: '2026-09-29T00:00:00Z',
					updated_at: '2026-09-29T00:00:00Z'
				},
				{
					dataset_id: 'fdset_feedback_evaluation',
					workspace_id: workspaceId,
					name: '评测',
					task_type: 'evaluation',
					construction_spec: { mode: 'automatic_feedback_workbench' },
					spec_version: 1,
					created_by: 'user_feedback',
					created_at: '2026-09-29T00:00:00Z',
					updated_at: '2026-09-29T00:00:00Z'
				}
			];
			return route.fulfill(json({ items, limit: 200, offset: 0 }));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}` && request.method() === 'GET') {
			return route.fulfill(
				json({
					dataset_id: datasetId,
					workspace_id: workspaceId,
					name: '预热条件问答纠错',
					task_type: 'sft',
					construction_spec: { mode: 'automatic_feedback_workbench' },
					spec_version: 1,
					created_by: 'user_feedback',
					created_at: '2026-09-29T00:00:00Z',
					updated_at: '2026-09-29T00:00:00Z'
				})
			);
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/samples` && request.method() === 'GET') {
			return route.fulfill(json({ items: [], total: 0, limit: 200, offset: 0 }));
		}
		if (path === `/api/v1/feedback-datasets/${datasetId}/exports` && request.method() === 'GET') {
			return route.fulfill(
				json({
					items: withExport
						? [
								{
									export_id: 'export_feedback',
									dataset_id: datasetId,
									export_no: 1,
									schema_version: 'literature-sft.v1',
									row_count: 1,
									content_digest: 'a'.repeat(64),
									provenance_digest: 'b'.repeat(64),
									manifest_digest: 'c'.repeat(64),
									created_at: '2026-09-29T00:00:00Z',
									download_formats: ['jsonl', 'json', 'provenance', 'manifest']
								}
							]
						: [],
					limit: 50,
					offset: 0
				})
			);
		}
		if (
			path === `/api/v1/feedback-datasets/${datasetId}/exports/export_feedback/download` &&
			request.method() === 'GET'
		) {
			return route.fulfill(
				json({ manifest_schema_version: 'feedback-dataset-export-manifest.v1' })
			);
		}
		return route.fulfill(
			json({ detail: `unhandled test route: ${request.method()} ${path}` }, 404)
		);
	});
}

test('the workspace entry uses task datasets and keeps internal IDs out of the reviewer view', async ({
	page
}) => {
	await mockTaskEntry(page);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await page.goto(`/workspaces/${workspaceId}/feedback`);

	await expect(page.getByRole('heading', { name: '反馈任务工作台' })).toBeVisible();
	await expect(page.getByRole('button', { name: /回答偏好/ })).toBeVisible();
	await expect(page.getByRole('button', { name: /评测/ })).toBeVisible();
	await page.getByRole('button', { name: /文献问答.*SFT/ }).click();
	await expect(page).toHaveURL(new RegExp(`/feedback/datasets/${datasetId}$`));
	const body = await page.locator('body').textContent();
	expect(body).not.toContain(caseId);
	expect(body).not.toContain('source_ref');
});

test('the global header keeps personal preferences reachable at tablet width', async ({ page }) => {
	await mockTaskEntry(page);
	await page.setViewportSize({ width: 1024, height: 800 });
	await page.goto(`/workspaces/${workspaceId}/feedback`);

	await page.getByRole('button', { name: /^个人菜单:/ }).click();
	const language = page.getByRole('button', { name: /^语言 / });
	await expect(language).toBeVisible();
	const bounds = await language.boundingBox();
	expect(bounds).not.toBeNull();
	expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(1024);
	await language.click();
	await expect(page.getByRole('button', { name: '简体中文', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024);
});

test('export history exposes the manifest download alongside training files', async ({ page }) => {
	await mockTaskEntry(page, true);
	await page.goto(`/workspaces/${workspaceId}/feedback/datasets/${datasetId}`);
	await page.locator('.export-panel > summary').click();
	await expect(page.getByText('已发布版本')).toBeVisible();
	await expect(page.getByText('Messages SFT', { exact: true })).toBeVisible();
	await expect(page.getByText(/Lens 中间格式 v1/)).toBeVisible();
	await expect(page.getByRole('button', { name: '清单' })).toBeVisible();

	const download = page.waitForEvent('download');
	await page.getByRole('button', { name: '清单' }).click();
	await expect((await download).suggestedFilename()).toContain('manifest.json');
});
