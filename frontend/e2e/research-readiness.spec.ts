import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';

function json(body: unknown, status = 200) {
	return {
		status,
		contentType: 'application/json',
		body: JSON.stringify(body)
	};
}

function collectionPayload() {
	return {
		collection_id: collectionId,
		id: collectionId,
		name: 'Partial research extraction',
		description: 'Comparison readiness fixture',
		status: 'ready',
		paper_count: 2,
		updated_at: '2026-05-14T00:00:00Z'
	};
}

function workspacePayload() {
	return {
		collection: collectionPayload(),
		file_count: 2,
		status_summary: 'ready',
		workflow: {
			documents: 'ready',
			results: 'not_started',
			evidence: 'not_started',
			comparisons: 'not_started'
		},
		document_summary: {
			total_documents: 2,
			doc_type_counts: { experimental: 2, review: 0, mixed: 0, uncertain: 0 },
			warnings: []
		},
		artifacts: {
			documents_ready: true,
			document_profiles_ready: true,
			evidence_cards_ready: false,
			comparable_results_ready: false,
			collection_comparable_results_ready: false,
			comparison_rows_ready: false,
			graph_ready: false,
			updated_at: '2026-05-14T00:00:00Z'
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: true,
			can_view_results: false,
			can_view_evidence: false,
			can_view_comparisons: false,
			can_view_graph: false,
			can_download_graphml: false
		},
		links: {
			workspace: `/collections/${collectionId}`,
			documents: `/collections/${collectionId}/documents`,
			results: `/collections/${collectionId}/results`,
			evidence: `/collections/${collectionId}/evidence`,
			comparisons: `/collections/${collectionId}/comparisons`,
			graph: `/collections/${collectionId}/graph`
		}
	};
}

function researchViewPayload() {
	return {
		collection_id: collectionId,
		state: 'empty',
		overview: {
			document_count: 2,
			sample_count: 0,
			measurement_count: 0,
			evidence_count: 0,
			material_systems: [],
			process_families: [],
			variable_axes: [],
			measured_properties: []
		},
		paper_coverage: [
			{
				document_id: 'doc_1',
				title: 'Paper A',
				state: 'empty',
				sample_count: 0,
				process_param_count: 0,
				measurement_count: 0,
				condition_count: 0,
				evidence_count: 0,
				issue_count: 2
			}
		],
		comparable_groups: [],
		warnings: [
			{
				warning_id: 'warning:comparison_projection_unavailable',
				code: 'comparison_projection_unavailable',
				severity: 'info',
				scope: 'collection',
				message:
					'Paper coverage is available, but comparable groups are not available until comparison artifacts are generated.',
				related_object_ids: []
			}
		]
	};
}

async function mockResearchApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;

		if (!path.startsWith('/api/v1/')) {
			return route.continue();
		}

		if (path === '/api/v1/collections') {
			return route.fulfill(json({ items: [collectionPayload()] }));
		}
		if (path === `/api/v1/collections/${collectionId}`) {
			return route.fulfill(json(collectionPayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/workspace`) {
			return route.fulfill(json(workspacePayload()));
		}
		if (path === `/api/v1/collections/${collectionId}/research-view`) {
			return route.fulfill(json(researchViewPayload()));
		}

		return route.fulfill(json({ detail: `unhandled test route: ${path}` }, 404));
	});
}

test('comparison page blocks comparison review until artifacts are generated', async ({ page }) => {
	await mockResearchApis(page);
	await page.setViewportSize({ width: 1440, height: 900 });

	await page.goto(`/collections/${collectionId}/comparisons`);

	await expect(page.getByRole('heading', { name: 'Comparison artifacts are not ready' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Open collection overview' })).toHaveAttribute(
		'href',
		`/collections/${collectionId}`
	);
	await expect(page.getByText('No comparable groups')).toHaveCount(0);
	await expect(page.getByText(/comparable groups are not available until/)).toHaveCount(0);
});
