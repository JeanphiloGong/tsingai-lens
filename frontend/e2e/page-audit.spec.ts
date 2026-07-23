import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';
const materialId = 'mat_316l';
const objectiveId = 'obj_1';
const resultId = 'cres_1';
const sessionId = 'gs_1';
const screenshotDir = process.env.PAGE_AUDIT_SCREENSHOT_DIR ?? '';

if (screenshotDir) {
	mkdirSync(screenshotDir, { recursive: true });
}

const routes = [
	['/', 'Lens Workbench'],
	['/docs', 'Using Lens'],
	['/system', 'System'],
	[`/collections/${collectionId}`, 'Research overview'],
	[`/collections/${collectionId}/documents`, 'Paper review list'],
	[`/collections/${collectionId}/documents/${documentId}?page=2`, 'Source view is ready'],
	[`/collections/${collectionId}/materials`, 'Canonical materials detected'],
	[`/collections/${collectionId}/materials/${materialId}`, '316L stainless steel'],
	[`/collections/${collectionId}/objectives`, '研究目标'],
	[`/collections/${collectionId}/objectives/${objectiveId}`, 'Findings'],
	[`/collections/${collectionId}/results`, 'Extracted Results'],
	[`/collections/${collectionId}/results/${resultId}`, 'Evidence chain'],
	[`/collections/${collectionId}/evidence`, 'Evidence Review'],
	[`/collections/${collectionId}/comparisons`, 'Comparable groups'],
	[`/collections/${collectionId}/graph`, 'Collection Knowledge Map'],
	[`/collections/${collectionId}/assistant`, 'Research Copilot']
] as const;

test.describe('page interaction audit', () => {
	test.beforeEach(async ({ page }) => {
		await page.emulateMedia({ reducedMotion: 'reduce' });
		await mockApis(page);
	});

	for (const [path, readyText] of routes) {
		test(`${path} renders usable desktop and mobile viewports`, async ({ page }) => {
			const consoleErrors: string[] = [];
			page.on('console', (message) => {
				if (message.type() === 'error') consoleErrors.push(message.text());
			});
			page.on('pageerror', (error) => consoleErrors.push(error.message));

			await checkViewport(page, path, readyText, { width: 1440, height: 900 });
			await checkViewport(page, path, readyText, { width: 390, height: 844 });

			expect(consoleErrors, `console errors on ${path}`).toEqual([]);
		});
	}

	test('collection navigation keeps Materials under More', async ({ page }) => {
		await checkMaterialsMoreNavigation(page, { width: 1440, height: 900 }, 'desktop');
		await checkMaterialsMoreNavigation(page, { width: 390, height: 844 }, 'mobile');
	});

	test('home collection row More menu stays fully visible', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/');

		await page.getByRole('button', { name: 'More actions for 316L LPBF evidence set' }).click();

		const menu = page.locator('.row-menu__panel');
		await expect(menu).toBeVisible();
		await expect(page.getByRole('button', { name: 'Retry processing' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Export' })).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
		expect(await isElementBottomExposed(page, '.row-menu__panel')).toBe(true);

		if (screenshotDir) {
			await page.screenshot({
				path: join(screenshotDir, 'home-row-more-menu-open-desktop.png'),
				fullPage: true
			});
		}
	});

	test('graph page keeps GraphML download under graph export', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(`/collections/${collectionId}/graph`);

		await page.getByRole('button', { name: 'Export graph' }).click();

		await expect(page.getByRole('menuitem', { name: 'Export PNG' })).toBeVisible();
		await expect(page.getByRole('menuitem', { name: 'Download GraphML' })).toBeVisible();
		await expect(page.getByRole('menuitem', { name: 'Copy current view' })).toBeVisible();
	});

	test('home ready collection next step opens research objectives', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/');

		await expect(page.getByRole('link', { name: 'Enter objectives' })).toHaveAttribute(
			'href',
			`/collections/${collectionId}/objectives`
		);
		await expect(page.getByRole('link', { name: 'Enter comparison' })).toHaveCount(0);
	});

	test('unprocessed collections lock direct research route access', async ({ page }) => {
		const objectiveRequests: string[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname === `/api/v1/collections/${collectionId}/objectives`) {
				objectiveRequests.push(url.pathname);
			}
		});

		await page.goto(`/collections/${collectionId}/objectives?audit_state=uploaded`);

		await expect(page.getByRole('heading', { name: 'Processing required' })).toBeVisible();
		await expect(
			page.getByText('Process this collection before opening research objectives')
		).toBeVisible();
		await expect(page.getByRole('link', { name: 'Back to workspace' })).toHaveAttribute(
			'href',
			`/collections/${collectionId}`
		);
		expect(objectiveRequests).toEqual([]);
	});

	test('mobile app chrome keeps controls inside the viewport', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto('/');

		await expect(page.getByRole('banner')).toBeVisible();
		expect(await visibleElementsFitViewport(page, 'header.site-header')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.global-search')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.header-actions')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.header-actions button')).toBe(true);
	});

	test('mobile document reader exposes app and PDF controls without clipping', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/collections/${collectionId}/documents/${documentId}?page=2`);

		await expect(page.getByText('Source view is ready')).toBeVisible();
		expect(await visibleElementsFitViewport(page, '.workbench-appbar')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.top-actions')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.top-actions button')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.pdf-toolbar')).toBe(true);
		await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
		await expect(page.getByLabel('Zoom', { exact: true })).toBeVisible();
	});

	test('comparison matrix is readable and horizontally scrollable on mobile', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/collections/${collectionId}/comparisons`);

		await expect(
			page.getByRole('heading', { name: 'Anneal temperature vs conductivity' })
		).toBeVisible();
		const wrapper = page.locator('.research-matrix-table-wrapper');
		await expect(wrapper).toBeVisible();
		const scrollInfo = await wrapper.evaluate((element) => ({
			clientWidth: element.clientWidth,
			scrollWidth: element.scrollWidth,
			overflowX: getComputedStyle(element).overflowX
		}));
		expect(scrollInfo.scrollWidth).toBeGreaterThan(scrollInfo.clientWidth);
		expect(['auto', 'scroll']).toContain(scrollInfo.overflowX);
		expect(await visibleElementsFitViewport(page, '.research-matrix-panel')).toBe(true);
	});

	test('mobile graph fit keeps nodes inside the visible canvas', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/collections/${collectionId}/graph`);

		await expect(page.getByText('Graph built').first()).toBeVisible();
		const graphBounds = await page.locator('.graph-cytoscape').evaluate((element) => {
			const canvases = Array.from(element.querySelectorAll<HTMLCanvasElement>('canvas'));
			let left = Number.POSITIVE_INFINITY;
			let right = Number.NEGATIVE_INFINITY;
			let coloredPixels = 0;
			for (const canvas of canvases) {
				const context = canvas.getContext('2d', { willReadFrequently: true });
				if (!context) continue;
				const { width, height } = canvas;
				const data = context.getImageData(0, 0, width, height).data;
				for (let y = 0; y < height; y += 2) {
					for (let x = 0; x < width; x += 2) {
						const index = (y * width + x) * 4;
						const red = data[index];
						const green = data[index + 1];
						const blue = data[index + 2];
						const alpha = data[index + 3];
						const isStrongNodeColor =
							alpha > 120 &&
							((blue > 150 && red < 120 && green < 180) || (red > 90 && blue > 150 && green < 150));
						if (!isStrongNodeColor) continue;
						coloredPixels += 1;
						left = Math.min(left, x);
						right = Math.max(right, x);
					}
				}
			}
			return {
				width: element.getBoundingClientRect().width,
				coloredPixels,
				left,
				right
			};
		});
		expect(graphBounds.coloredPixels).toBeGreaterThan(0);
		expect(graphBounds.left).toBeGreaterThanOrEqual(12);
		expect(graphBounds.right).toBeLessThanOrEqual(graphBounds.width - 12);
	});
});

async function checkMaterialsMoreNavigation(
	page: Page,
	viewport: { width: number; height: number },
	label: string
) {
	await page.setViewportSize(viewport);
	await page.goto(`/collections/${collectionId}`);

	const nav = page.getByRole('navigation', { name: 'Collection navigation' });

	await expect(nav.getByRole('link', { name: 'Materials' })).toBeHidden();
	await nav.getByText('More').click();
	await expect(nav.getByRole('link', { name: 'Materials' })).toBeVisible();
	await expect(nav.locator('.collection-tabs__menu')).toBeVisible();
	expect(await isElementCenterExposed(page, '.collection-tabs__menu')).toBe(true);
	expect(await isElementBottomExposed(page, '.collection-tabs__menu')).toBe(true);

	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, `collection-navigation-more-materials-open-${label}.png`),
			fullPage: true
		});
	}
}

async function isElementCenterExposed(page: Page, selector: string) {
	return page.evaluate((targetSelector) => {
		const target = document.querySelector(targetSelector);
		if (!(target instanceof HTMLElement)) return false;
		const rect = target.getBoundingClientRect();
		const x = rect.left + rect.width / 2;
		const y = rect.top + Math.min(24, rect.height / 2);
		const hit = document.elementFromPoint(x, y);
		return Boolean(hit && target.contains(hit));
	}, selector);
}

async function isElementBottomExposed(page: Page, selector: string) {
	return page.evaluate((targetSelector) => {
		const target = document.querySelector(targetSelector);
		if (!(target instanceof HTMLElement)) return false;
		const rect = target.getBoundingClientRect();
		const x = rect.left + rect.width / 2;
		const y = rect.bottom - Math.min(12, rect.height / 3);
		const hit = document.elementFromPoint(x, y);
		return Boolean(hit && target.contains(hit));
	}, selector);
}

async function visibleElementsFitViewport(page: Page, selector: string) {
	return page.evaluate((targetSelector) => {
		const viewportWidth = window.innerWidth;
		return Array.from(document.querySelectorAll<HTMLElement>(targetSelector))
			.filter((element) => {
				const rect = element.getBoundingClientRect();
				const style = getComputedStyle(element);
				return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
			})
			.every((element) => {
				const rect = element.getBoundingClientRect();
				return rect.left >= -1 && rect.right <= viewportWidth + 1;
			});
	}, selector);
}

async function checkViewport(
	page: Page,
	path: string,
	readyText: string,
	viewport: { width: number; height: number }
) {
	await page.setViewportSize(viewport);
	await page.goto(path);
	const heading = page.getByRole('heading', { name: readyText }).first();
	if ((await heading.count()) > 0) {
		await expect(heading).toBeVisible();
	} else {
		await expect(page.getByText(readyText).first()).toBeVisible();
	}
	await waitForVisualReady(page, path);
	await expectVisibleInteractionsHaveNames(page);
	await expectNoHorizontalOverflow(page);
	if (screenshotDir) {
		await page.screenshot({
			path: join(screenshotDir, `${routeScreenshotName(path)}-${viewport.width}.png`),
			fullPage: true
		});
	}
}

async function waitForVisualReady(page: Page, path: string) {
	await page.waitForLoadState('networkidle');
	if (path.endsWith('/graph')) {
		await expect(page.getByText('Graph built').first()).toBeVisible();
	}
}

function routeScreenshotName(path: string) {
	return path
		.replace(/^\//, 'root/')
		.replace(/[^a-z0-9]+/gi, '-')
		.replace(/^-|-$/g, '')
		.toLowerCase();
}

async function expectNoHorizontalOverflow(page: Page) {
	const overflow = await page.evaluate(() => {
		const root = document.querySelector('.document-workbench-root');
		const rootWidth = root instanceof HTMLElement ? root.scrollWidth : 0;
		const width = Math.max(
			document.documentElement.scrollWidth,
			document.body.scrollWidth,
			rootWidth
		);
		return { width, innerWidth: window.innerWidth, overflowing: width > window.innerWidth + 1 };
	});
	expect(overflow.overflowing, `page width ${overflow.width} exceeds ${overflow.innerWidth}`).toBe(
		false
	);
}

async function expectVisibleInteractionsHaveNames(page: Page) {
	const unnamed = await page.evaluate(() => {
		const selector = [
			'a[href]',
			'button:not([disabled])',
			'input:not([disabled])',
			'select:not([disabled])',
			'textarea:not([disabled])',
			'summary'
		].join(',');
		return Array.from(document.querySelectorAll<HTMLElement>(selector))
			.filter((element) => {
				const rect = element.getBoundingClientRect();
				const style = window.getComputedStyle(element);
				return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
			})
			.filter((element) => {
				const id = element.id;
				const labelledBy = element.getAttribute('aria-labelledby');
				const label =
					(id && document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent?.trim()) ||
					element.closest('label')?.textContent?.trim() ||
					(labelledBy && document.getElementById(labelledBy)?.textContent?.trim()) ||
					element.getAttribute('aria-label')?.trim() ||
					element.getAttribute('title')?.trim() ||
					element.getAttribute('placeholder')?.trim() ||
					element.textContent?.trim();
				return !label;
			})
			.map((element) => element.outerHTML.slice(0, 160));
	});
	expect(unnamed).toEqual([]);
}

async function mockApis(page: Page) {
	await page.route('**/*', async (route) => {
		const url = new URL(route.request().url());
		const path = url.pathname;
		const method = route.request().method();
		const referer = route.request().headers().referer;
		const auditState = readAuditState(url, referer);

		if (!path.startsWith('/api/v1/')) return route.continue();

		if (path === '/api/v1/auth/me') {
			return route.fulfill(json(authPayload()));
		}
		if (path === '/api/v1/collections') {
			if (method === 'POST') return route.fulfill(json(collection(auditState)));
			return route.fulfill(json({ items: [collection(auditState)] }));
		}
		if (path === `/api/v1/collections/${collectionId}`)
			return route.fulfill(json(collection(auditState)));
		if (path === `/api/v1/collections/${collectionId}/workspace`)
			return route.fulfill(json(workspace(auditState)));
		if (path === `/api/v1/collections/${collectionId}/files`) {
			return route.fulfill(json({ count: 1, items: [uploadedFile()] }));
		}
		if (path === `/api/v1/collections/${collectionId}/tasks/build`) {
			return route.fulfill(json(task()));
		}
		if (path === `/api/v1/collections/${collectionId}/research-view`) {
			return route.fulfill(json(collectionResearchView()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/profiles`) {
			return route.fulfill(json(documentProfiles()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/profile`) {
			return route.fulfill(json(documentProfile()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/content`) {
			return route.fulfill(json(documentContent()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/markdown`) {
			return route.fulfill(json(documentMarkdown()));
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/research-view`) {
			return route.fulfill(json(documentResearchView()));
		}
		if (
			path === `/api/v1/collections/${collectionId}/documents/${documentId}/comparison-semantics`
		) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					document_id: documentId,
					total: 1,
					count: 1,
					items: [],
					variant_dossiers: [variantDossier()]
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/source`) {
			return route.fulfill({ status: 204, body: '' });
		}
		if (path === `/api/v1/collections/${collectionId}/materials`) {
			return route.fulfill(json({ items: [materialSummary()] }));
		}
		if (path === `/api/v1/collections/${collectionId}/materials/${materialId}/research-view`) {
			return route.fulfill(json(materialProfile()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives`) {
			return route.fulfill(json(objectives()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}`) {
			return route.fulfill(json(objectiveView()));
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/findings`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					objective_id: objectiveId,
					analysis_version: 1,
					items: [objectiveFinding()],
					offset: 0,
					limit: 50,
					total: 1
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/evidence`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					objective_id: objectiveId,
					analysis_version: 1,
					finding_id: 'finding-1',
					items: [objectiveEvidence()],
					offset: 0,
					limit: 100,
					total: 1
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/results`)
			return route.fulfill(json(results()));
		if (path === `/api/v1/collections/${collectionId}/results/${resultId}`) {
			return route.fulfill(json(resultDetail()));
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/cards`) {
			return route.fulfill(
				json({ collection_id: collectionId, total: 1, count: 1, items: [evidence()] })
			);
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/ev_1`) {
			return route.fulfill(json(evidence()));
		}
		if (path === `/api/v1/collections/${collectionId}/evidence/ev_1/traceback`) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					evidence_id: 'ev_1',
					traceback_status: 'ready',
					anchors: evidence().evidence_anchors
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}/comparisons`) {
			return route.fulfill(json({ collection_id: collectionId, total: 0, count: 0, items: [] }));
		}
		if (path === `/api/v1/collections/${collectionId}/comparisons/cmp_1`) {
			return route.fulfill(json({ row_id: 'cmp_1', collection_id: collectionId }));
		}
		if (path === `/api/v1/collections/${collectionId}/graph`) return route.fulfill(json(graph()));
		if (path.startsWith(`/api/v1/collections/${collectionId}/graph/nodes/`)) {
			return route.fulfill(json(graph()));
		}
		if (path === `/api/v1/collections/${collectionId}/graphml`) {
			return route.fulfill({
				status: 200,
				contentType: 'application/graphml+xml',
				body: '<graphml />'
			});
		}
		if (path === '/api/v1/goal-sessions') return route.fulfill(json(goalSession(), 201));
		if (path === `/api/v1/goal-sessions/${sessionId}`) return route.fulfill(json(goalSession()));
		if (path === `/api/v1/goal-sessions/${sessionId}/messages`) {
			return route.fulfill(json({ session_id: sessionId, items: [] }));
		}

		return route.fulfill(json({ detail: `unhandled audit route: ${path}` }, 404));
	});
}

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

function now() {
	return '2026-05-14T00:00:00Z';
}

function authPayload() {
	return {
		user: {
			user_id: 'user_1',
			email: 'reader@example.com',
			display_name: 'Reader'
		}
	};
}

function readAuditState(url: URL, referer?: string) {
	if (url.searchParams.has('audit_state')) return url.searchParams.get('audit_state');
	if (!referer) return null;
	try {
		return new URL(referer).searchParams.get('audit_state');
	} catch {
		return null;
	}
}

function collection(auditState?: string | null) {
	return {
		collection_id: collectionId,
		id: collectionId,
		name: '316L LPBF evidence set',
		description: 'Interaction audit fixture',
		status: auditState === 'uploaded' ? 'uploaded' : 'ready',
		paper_count: 2,
		created_at: now(),
		updated_at: now()
	};
}

function workspace(auditState?: string | null) {
	const unprocessed = auditState === 'uploaded';
	return {
		collection: collection(auditState),
		file_count: 2,
		status_summary: unprocessed ? 'ready_to_process' : 'ready',
		workflow: unprocessed
			? {
					documents: 'not_started',
					results: 'not_started',
					evidence: 'not_started',
					comparisons: 'not_started'
				}
			: { documents: 'ready', results: 'ready', evidence: 'ready', comparisons: 'ready' },
		document_summary: {
			total_documents: 2,
			doc_type_counts: { experimental: 2, review: 0, mixed: 0, uncertain: 0 },
			warnings: []
		},
		warnings: [],
		artifacts: {
			documents_ready: !unprocessed,
			document_profiles_ready: !unprocessed,
			evidence_cards_ready: !unprocessed,
			comparable_results_ready: !unprocessed,
			collection_comparable_results_ready: !unprocessed,
			comparison_rows_ready: !unprocessed,
			graph_ready: !unprocessed,
			graph_stale: false,
			updated_at: now()
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: !unprocessed,
			can_view_results: !unprocessed,
			can_view_evidence: !unprocessed,
			can_view_comparisons: !unprocessed,
			can_view_graph: !unprocessed,
			can_download_graphml: !unprocessed
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

function uploadedFile() {
	return {
		file_id: 'file_1',
		collection_id: collectionId,
		original_filename: 'paper-a.pdf',
		stored_filename: 'paper-a.pdf',
		stored_path: '/tmp/paper-a.pdf',
		media_type: 'application/pdf',
		status: 'uploaded',
		size_bytes: 2048,
		created_at: now()
	};
}

function task() {
	return {
		task_id: 'task_1',
		collection_id: collectionId,
		task_type: 'build_collection',
		status: 'queued',
		current_stage: 'queued',
		progress_percent: 5,
		output_path: null,
		errors: [],
		warnings: [],
		created_at: now(),
		updated_at: now(),
		started_at: null,
		finished_at: null
	};
}

function evidenceRef() {
	return {
		evidence_ref_id: 'ev_1',
		fact_ids: [],
		anchor_ids: ['anc_1'],
		document_id: documentId,
		source_kind: 'table',
		locator: 'Table 2',
		confidence: 0.95,
		traceability_status: 'direct'
	};
}

function value(displayValue: string) {
	return {
		display_value: displayValue,
		value: null,
		unit: null,
		normalized_value: null,
		normalized_unit: null,
		status: 'observed',
		confidence: 0.95,
		evidence_refs: [evidenceRef()],
		duplicate_count: 0,
		conflict_status: null,
		warnings: []
	};
}

function collectionResearchView() {
	return {
		collection_id: collectionId,
		state: 'ready',
		overview: {
			document_count: 2,
			sample_count: 2,
			measurement_count: 2,
			evidence_count: 1,
			material_systems: ['oxide cathode'],
			process_families: ['annealing'],
			variable_axes: ['temperature'],
			measured_properties: ['conductivity'],
			coverage_quality: 'ready'
		},
		materials: [materialSummary()],
		paper_coverage: [
			{
				document_id: documentId,
				title: 'Paper A',
				state: 'ready',
				sample_count: 2,
				process_param_count: 3,
				measurement_count: 4,
				condition_count: 1,
				evidence_count: 5,
				issue_count: 0,
				primary_warnings: [],
				links: {}
			}
		],
		comparable_groups: [
			{
				group_id: 'grp_1',
				title: 'Anneal temperature vs conductivity',
				material_system: 'oxide cathode',
				process_family: 'annealing',
				variable_axis: 'temperature',
				fixed_conditions: { atmosphere: 'air' },
				properties: ['conductivity'],
				documents: [documentId],
				samples: ['S1'],
				comparability_status: 'comparable',
				matrix: {
					matrix_id: 'matrix_1',
					group_id: 'grp_1',
					columns: [],
					rows: [
						{
							row_id: 'mx_row_1',
							document_id: documentId,
							sample_id: 'S1',
							sample_label: 'Sample A',
							material: 'oxide cathode',
							process_context: { process: 'annealing' },
							variable_value: '700 C',
							test_condition: 'EIS',
							property: 'conductivity',
							result: value('12 mS/cm'),
							evidence_refs: [evidenceRef()],
							warnings: []
						}
					],
					warnings: []
				},
				evidence_refs: [evidenceRef()],
				warnings: []
			}
		],
		cross_paper_matrices: [],
		trend_series: [],
		evidence_links: {},
		debug_links: {},
		warnings: []
	};
}

function materialSummary() {
	return {
		material_id: materialId,
		canonical_name: '316L stainless steel',
		aliases: ['316L'],
		paper_count: 2,
		sample_count: 6,
		process_families: ['LPBF'],
		measured_properties: ['density', 'hardness'],
		comparison_count: 3,
		evidence_coverage: 0.75,
		state: 'ready',
		links: {},
		warnings: []
	};
}

function materialProfile() {
	return {
		collection_id: collectionId,
		material_id: materialId,
		canonical_name: '316L stainless steel',
		aliases: ['316L'],
		state: 'ready',
		overview: {
			paper_count: 1,
			sample_count: 1,
			comparison_count: 1,
			evidence_count: 3,
			process_families: ['LPBF'],
			measured_properties: ['hardness'],
			variable_axes: ['scan strategy']
		},
		papers: [
			{
				document_id: documentId,
				title: 'Paper A',
				source_filename: 'paper-a.pdf',
				state: 'ready',
				sample_count: 1,
				process_families: ['LPBF'],
				measured_properties: ['hardness'],
				evidence_count: 3
			}
		],
		sample_matrix: {
			columns: [{ value_key: 'hardness', label: 'Hardness', unit: 'HV' }],
			rows: [
				{
					row_id: 'row_1',
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: '316L stainless steel',
					process_context: { scan_strategy: 'alternating' },
					values: { hardness: value('215 HV') },
					evidence_refs: [evidenceRef()],
					warnings: []
				}
			]
		},
		comparable_groups: [],
		evidence_links: {},
		warnings: []
	};
}

function documentProfiles() {
	return {
		collection_id: collectionId,
		total: 1,
		count: 1,
		summary: {
			total_documents: 1,
			doc_type_counts: {
				experimental: 1,
				review: 0,
				method: 0,
				computational: 0,
				mixed: 0,
				uncertain: 0
			},
			warnings: []
		},
		items: [documentProfile()]
	};
}

function documentProfile() {
	return {
		document_id: documentId,
		collection_id: collectionId,
		title: 'Paper A',
		source_filename: 'paper-a.txt',
		doc_type: 'experimental',
		parsing_warnings: [],
		confidence: 0.9,
		page_count: 3,
		updated_at: now(),
		processing_status: 'completed'
	};
}

function documentContent() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'Paper A',
		source_filename: 'paper-a.txt',
		content_text:
			'Abstract\nConductivity improved to 12 mS/cm.\nResults\nConductivity improved to 12 mS/cm under EIS.',
		blocks: [
			{
				block_id: 'abstract',
				block_type: 'abstract',
				heading_path: 'Abstract',
				heading_level: 1,
				order: 1,
				text: 'Conductivity improved to 12 mS/cm.',
				start_offset: 9,
				end_offset: 43,
				text_unit_ids: [],
				page: 1,
				bbox: null
			},
			{
				block_id: 'results',
				block_type: 'results',
				heading_path: 'Results',
				heading_level: 1,
				order: 2,
				text: 'Conductivity improved to 12 mS/cm under EIS.',
				start_offset: 52,
				end_offset: 97,
				text_unit_ids: [],
				page: 3,
				bbox: null
			}
		],
		warnings: []
	};
}

function documentMarkdown() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		title: 'Paper A',
		source_filename: 'paper-a.pdf',
		parser: 'docling',
		markdown:
			'# Paper A\n\n## Abstract\n\nConductivity improved to 12 mS/cm.\n\n## Results\n\nConductivity improved to 12 mS/cm under EIS.',
		source_map: [
			{
				markdown_anchor: 'block-abstract',
				artifact_type: 'block',
				artifact_id: 'abstract',
				block_id: 'abstract',
				block_type: 'paragraph',
				page: 1,
				heading_path: 'Abstract',
				text_unit_ids: []
			}
		],
		warnings: []
	};
}

function documentResearchView() {
	return {
		collection_id: collectionId,
		document_id: documentId,
		state: 'ready',
		paper_title: 'Paper A',
		overview: {
			material_systems: ['oxide cathode'],
			sample_variant_count: 1,
			main_process_variables: ['anneal temperature'],
			measured_properties: ['conductivity']
		},
		materials: [
			{
				material_id: 'oxide_cathode',
				canonical_name: 'oxide cathode',
				aliases: [],
				sample_count: 1,
				process_families: ['annealing'],
				measured_properties: ['conductivity'],
				comparison_count: 1,
				warnings: []
			}
		],
		sample_matrix: {
			matrix_id: 'sample_matrix',
			document_id: documentId,
			state: 'ready',
			columns: [{ column_id: 'conductivity', key: 'conductivity', label: 'Conductivity' }],
			rows: [
				{
					row_id: 'row_1',
					document_id: documentId,
					sample_id: 'S1',
					sample_label: 'Sample A',
					material: 'oxide cathode',
					process_context: { anneal: '700 C' },
					variable_axis: null,
					variable_value: null,
					values: { conductivity: value('12 mS/cm') },
					evidence_refs: [evidenceRef()],
					warnings: []
				}
			],
			warnings: []
		},
		condition_series: []
	};
}

function variantDossier() {
	return {
		variant_id: 'var_1',
		variant_label: 'optimized VED + HIP',
		material: { label: 'oxide cathode', composition: 'LiNiO2', host_material_system: null },
		shared_process_state: { anneal_temperature_c: 700 },
		shared_missingness: [],
		series: []
	};
}

function resultItem(id = resultId, material = 'oxide cathode') {
	return {
		result_id: id,
		document_id: documentId,
		document_title: 'Paper A',
		material_label: material,
		variant_label: 'Sample A',
		property: 'conductivity',
		value: 12,
		unit: 'mS/cm',
		summary: '12 mS/cm',
		baseline: 'as-prepared',
		test_condition: 'EIS',
		process: '700 C',
		traceability_status: 'direct',
		comparability_status: 'comparable',
		requires_expert_review: false,
		confidence: 0.9,
		result_type: 'scalar',
		source_evidence_quote: 'conductivity is reported for oxide cathode.',
		source_type: 'table',
		source_section: 'Results',
		source_location: 'Table 2',
		evidence_ids: ['ev_1'],
		anchor_ids: ['anc_1'],
		missing_context: [],
		warnings: [],
		created_at: now(),
		updated_at: now()
	};
}

function results() {
	return {
		collection_id: collectionId,
		total: 2,
		count: 2,
		items: [resultItem(), resultItem('cres_2', 'layered oxide')]
	};
}

function resultDetail() {
	return {
		result_id: resultId,
		document: { document_id: documentId, title: 'Paper A', source_filename: 'paper-a.txt' },
		material: { label: 'oxide cathode', variant_id: 'var_1', variant_label: 'Sample A' },
		measurement: {
			property: 'conductivity',
			value: 12,
			unit: 'mS/cm',
			result_type: 'scalar',
			summary: '12 mS/cm',
			statistic_type: null,
			uncertainty: null
		},
		context: {
			process: '700 C',
			baseline: 'as-prepared',
			baseline_reference: 'same-paper control',
			test_condition: 'EIS',
			axis_name: null,
			axis_value: null,
			axis_unit: null
		},
		assessment: {
			comparability_status: 'comparable',
			warnings: [],
			basis: [],
			missing_context: [],
			requires_expert_review: false,
			assessment_epistemic_status: 'grounded'
		},
		evidence: [
			{
				evidence_id: 'ev_1',
				traceability_status: 'direct',
				source_type: 'text',
				anchor_ids: ['anc_1']
			}
		],
		actions: {
			open_document: `/collections/${collectionId}/documents/${documentId}`,
			open_comparisons: `/collections/${collectionId}/comparisons?property_normalized=conductivity`,
			open_evidence: null
		},
		variant_dossier: variantDossier(),
		test_condition_detail: { test_method: 'EIS', test_temperature_c: 25, environment: 'air' },
		baseline_detail: {
			label: 'as-prepared',
			reference: 'same-paper control',
			baseline_type: 'same_document',
			resolved: true,
			baseline_scope: 'same material'
		},
		structure_support: [
			{
				support_id: 'sf_1',
				support_type: 'phase',
				summary: 'Layered phase retained after annealing.',
				condition: { method: 'XRD' }
			}
		],
		value_provenance: {
			value_origin: 'reported',
			source_value_text: '12',
			source_unit_text: 'mS/cm'
		},
		series_navigation: {
			series_key: 'conductivity:test_temperature_c',
			varying_axis: { axis_name: 'test_temperature_c', axis_unit: 'C' },
			siblings: []
		}
	};
}

function evidence() {
	return {
		evidence_id: 'ev_1',
		document_id: documentId,
		collection_id: collectionId,
		claim_text: 'conductivity is reported for oxide cathode.',
		claim_type: 'result',
		evidence_source_type: 'table',
		evidence_anchors: [
			{
				anchor_id: 'anc_1',
				document_id: documentId,
				locator_type: 'section',
				locator_confidence: 'medium',
				source_type: 'table',
				section_id: 'results',
				char_range: null,
				bbox: null,
				page: 3,
				quote: 'Conductivity improved to 12 mS/cm under EIS.',
				deep_link: null,
				block_id: 'results',
				snippet_id: null,
				figure_or_table: 'Table 2',
				quote_span: null,
				anchor_type: 'direct',
				label: 'Table 2'
			}
		],
		material_system: 'oxide cathode',
		condition_context: { process: ['700 C'], baseline: ['as-prepared'], test: ['EIS'] },
		confidence: 0.94,
		traceability_status: 'direct',
		source_document_title: 'Paper A',
		materials: ['oxide cathode'],
		parameters: ['700 C'],
		tags: ['conductivity'],
		comparable: true,
		comparison_status: 'joinable',
		review_status: null,
		extracted_at: now(),
		updated_at: now()
	};
}

function objectives() {
	return {
		collection_id: collectionId,
		objectives: [
			{
				collection_id: collectionId,
				objective_id: objectiveId,
				question: 'How does heat treatment affect LPBF 316L tensile strength?',
				material_scope: ['316L stainless steel'],
				process_axes: ['heat treatment'],
				property_axes: ['yield strength'],
				comparison_intent: 'Compare as-built and heat-treated LPBF 316L.',
				seed_document_ids: [documentId],
				excluded_document_ids: [],
				confidence: 0.91,
				reason: null,
				confirmation_status: 'confirmed',
				active_analysis_version: 1,
				published_analysis_version: 1,
				created_at: now(),
				updated_at: now()
			}
		]
	};
}

function objectiveView() {
	const objective = objectives().objectives[0];
	return {
		collection_id: collectionId,
		objective,
		active_analysis: objectiveAnalysis(),
		published_analysis: objectiveAnalysis(),
		warnings: []
	};
}

function objectiveAnalysis() {
	return {
		collection_id: collectionId,
		objective_id: objectiveId,
		analysis_version: 1,
		source_build_id: 'build-1',
		pipeline_version: 'objective-analysis.v2',
		model_name: 'model-1',
		prompt_versions: {},
		status: 'succeeded',
		phase: 'succeeded',
		processed_document_count: 1,
		total_document_count: 1,
		current_document_id: null,
		progress_message: null,
		error_code: null,
		error_message: null,
		created_at: now(),
		started_at: now(),
		completed_at: now()
	};
}

function objectiveFinding() {
	return {
		collection_id: collectionId,
		objective_id: objectiveId,
		analysis_version: 1,
		finding_id: 'finding-1',
		finding_level: 'paper',
		statement: 'Annealing was associated with higher tensile strength.',
		variables: ['heat treatment'],
		mediators: [],
		outcomes: ['tensile strength'],
		direction: 'increase',
		scope_summary: 'LPBF 316L under the reported tensile-test condition.',
		evidence_strength: 'moderate',
		generalization_status: 'paper_level_only',
		paper_count: 1,
		confidence: 0.88,
		display_rank: 0,
		relations: [
			{
				relation_order: 0,
				source_term: 'annealing',
				relation_type: 'associated_with',
				target_term: 'tensile strength',
				direction: 'increase',
				assertion_strength: 'associative',
				supporting_evidence_ids: ['evidence-1']
			}
		],
		context: {
			material_system: { name: '316L' },
			process_conditions: [{ state: 'annealed' }],
			sample_state: {},
			test_conditions: [{ method: 'tensile test' }],
			comparison_baseline: { state: 'as-built' },
			limitations: ['Single paper only.'],
			supporting_evidence_ids: ['evidence-1']
		},
		derivation: {
			synthesis_mode: 'paper',
			comparison_status: 'insufficient_confirmation',
			contributing_document_ids: [documentId],
			supporting_evidence_ids: ['evidence-1'],
			contradicting_evidence_ids: [],
			rationale: 'One direct result supports this paper-level Finding.'
		}
	};
}

function objectiveEvidence() {
	return {
		collection_id: collectionId,
		objective_id: objectiveId,
		analysis_version: 1,
		evidence_id: 'evidence-1',
		document_id: documentId,
		source_kind: 'text_window',
		source_ref: 'results',
		source_excerpt: 'After annealing, tensile strength increased to 620 MPa.',
		page_numbers: [3],
		related_source_refs: [],
		evidence_role: 'direct_result',
		selection_status: 'extracted',
		selection_reason: 'Direct result.',
		evidence_kind: 'measurement',
		property_normalized: 'tensile strength',
		material_system: { name: '316L' },
		sample_context: {},
		process_context: {},
		test_condition: {},
		resolved_condition: {},
		value_payload: { value: 620 },
		unit: 'MPa',
		baseline_context: {},
		interpretation: null,
		join_keys: {},
		anchor_ids: [],
		resolution_status: 'resolved',
		failure_reason: null,
		confidence: 0.92
	};
}

function graph() {
	return {
		collection_id: collectionId,
		nodes: [
			{ id: `doc:${documentId}`, label: 'Paper A', type: 'document', degree: 2 },
			{ id: 'mat:oxide cathode', label: 'oxide cathode', type: 'material', degree: 2 }
		],
		edges: [
			{
				id: 'edge_1',
				source: `doc:${documentId}`,
				target: 'mat:oxide cathode',
				weight: 0.9,
				edge_description: 'overview_document_material'
			}
		],
		truncated: false
	};
}

function goalSession() {
	return {
		session_id: sessionId,
		user_id: 'user_1',
		collection_id: collectionId,
		focused_material_id: null,
		focused_paper_id: null,
		goal_text: null,
		goal_brief_json: {},
		answer_mode: 'hybrid',
		rolling_summary: '',
		last_evidence_ids: [],
		last_material_ids: [],
		last_paper_ids: [],
		collection_data_version: null,
		created_at: now(),
		updated_at: now()
	};
}
