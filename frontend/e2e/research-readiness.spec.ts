import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify(body)
	};
}

async function mockComparisonApis(page: Page) {
	await page.route('**/*', async (route) => {
		const path = new URL(route.request().url()).pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_1', email: 'reader@example.com', display_name: 'Reader' } })
			);
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					name: 'Objective-first comparison fixture',
					status: 'ready',
					paper_count: 2
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(
				json({
					collection: { collection_id: collectionId, name: 'Objective-first comparison fixture' },
					file_count: 2,
					status_summary: 'ready',
					workflow: {
						documents: { status: 'ready', detail: 'Document profiles are available.' },
						objectives: { status: 'ready', detail: 'Objective discovery is complete.' }
					},
					document_summary: { total_documents: 2, by_doc_type: { experimental: 2 } },
					warnings: [],
					artifacts: {
						source_documents_ready: true,
						document_profiles_ready: true,
						objective_candidates_ready: true,
						updated_at: '2026-08-20T00:00:00Z'
					},
					latest_task: null,
					recent_tasks: [],
					capabilities: {
						can_view_documents: true,
						can_view_objectives: true,
						can_view_comparisons: true
					},
					links: {
						workspace: `/collections/${collectionId}`,
						documents: `/collections/${collectionId}/documents`,
						objectives: `/collections/${collectionId}/objectives`,
						comparisons: `/collections/${collectionId}/comparisons`
					}
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives`) {
			return route.fulfill(json({ collection_id: collectionId, objectives: [] }));
		}
		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

test('comparison page explains that only published Objective Findings appear', async ({ page }) => {
	await mockComparisonApis(page);
	await page.setViewportSize({ width: 1440, height: 900 });

	await page.goto(`/collections/${collectionId}/comparisons`);

	await expect(page.getByRole('heading', { name: 'No published findings yet' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Open research objectives' })).toHaveAttribute(
		'href',
		`/collections/${collectionId}/objectives`
	);
});
