import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type Page, type Route } from '@playwright/test';

const collectionId = 'col_123';
const documentId = 'doc_1';
const objectiveId = 'obj_1';
const sessionId = 'chat_1';
const screenshotDir = process.env.PAGE_AUDIT_SCREENSHOT_DIR ?? '';

if (screenshotDir) {
	mkdirSync(screenshotDir, { recursive: true });
}

const routes = [
	['/', 'Lens Workbench'],
	['/docs', 'Using Lens'],
	['/system', 'System'],
	[`/collections/${collectionId}`, 'Collection is ready'],
	[`/collections/${collectionId}/documents`, 'Papers'],
	[`/collections/${collectionId}/documents/${documentId}?view=parsed-paper`, 'Paper A'],
	[`/collections/${collectionId}/objectives`, '研究目标'],
	[`/collections/${collectionId}/objectives/${objectiveId}`, 'Findings'],
	[`/collections/${collectionId}/comparisons`, 'Cross-paper findings'],
	[`/collections/${collectionId}/graph`, 'Objective evidence map'],
	[`/collections/${collectionId}/assistant`, 'Research Agent']
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

	test('home ready collection next step opens research objectives', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/');

		await expect(page.getByRole('link', { name: 'Enter objectives' })).toHaveAttribute(
			'href',
			`/collections/${collectionId}/objectives`
		);
		await expect(page.getByRole('link', { name: 'Enter comparison' })).toHaveCount(0);
	});

	test('evidence map distinguishes scientific relations from failed paper coverage', async ({
		page
	}) => {
		await page.goto(`/collections/${collectionId}/graph`);

		await expect(page.getByText('Supports')).toBeVisible();
		await expect(page.getByText('Contradicts')).toBeVisible();
		await expect(page.getByText('1 failed paper')).toBeVisible();
		await expect(page.getByText('Paper C extraction gap')).toBeVisible();

		const sourceLink = page.getByRole('link', { name: 'Table · table-7' });
		await expect(sourceLink).toHaveAttribute(
			'href',
			new RegExp(
				`^/collections/${collectionId}/documents/${documentId}\\?view=parsed-paper&source_ref=table-7`
			)
		);
		await sourceLink.click();
		await page.waitForURL(`**/documents/${documentId}?view=parsed-paper&source_ref=table-7**`);
		await expect(page.getByRole('heading', { name: 'Paper A' }).first()).toBeVisible();
		await page.waitForLoadState('networkidle');
	});

	test('global Research Agent entry asks for a collection workspace', async ({ page }) => {
		const consoleErrors: string[] = [];
		page.on('console', (message) => {
			if (message.type() === 'error' || message.type() === 'warning') {
				consoleErrors.push(message.text());
			}
		});
		page.on('pageerror', (error) => consoleErrors.push(error.message));

		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/');
		await page.getByRole('button', { name: 'Research Agent' }).click();

		const picker = page.getByRole('dialog', { name: 'Choose a research workspace' });
		await expect(picker).toBeVisible();
		await expect(picker.getByRole('link', { name: /316L LPBF evidence set/ })).toHaveAttribute(
			'href',
			`/collections/${collectionId}/assistant`
		);
		expect(await visibleElementsFitViewport(page, '.workspace-picker')).toBe(true);
		expect(consoleErrors).toEqual([]);

		if (screenshotDir) {
			await page.screenshot({
				path: join(screenshotDir, 'research-agent-workspace-picker-desktop.png'),
				fullPage: true
			});
		}

		await page.setViewportSize({ width: 390, height: 844 });
		expect(await visibleElementsFitViewport(page, '.workspace-picker')).toBe(true);
		if (screenshotDir) {
			await page.screenshot({
				path: join(screenshotDir, 'research-agent-workspace-picker-mobile.png'),
				fullPage: true
			});
		}
	});

	test('research agent completes conversation, capability, draft, and approved write states', async ({
		page
	}) => {
		const consoleErrors: string[] = [];
		const decisions: Array<Record<string, unknown>> = [];
		let trajectory: Array<Record<string, unknown>> = [];
		let pendingApproval: Record<string, unknown> | null = null;
		let messageSequence = 0;

		page.on('console', (message) => {
			if (message.type() === 'error' || message.type() === 'warning') {
				consoleErrors.push(message.text());
			}
		});
		page.on('pageerror', (error) => consoleErrors.push(error.message));

		const handleChatRoute = async (route: Route) => {
			const request = route.request();
			const url = new URL(request.url());
			const path = url.pathname;
			if (path === '/api/v1/chat-sessions' && request.method() === 'POST') {
				return route.fulfill(json(chatSession(), 201));
			}
			if (path === `/api/v1/chat-sessions/${sessionId}` && request.method() === 'GET') {
				return route.fulfill(json(chatSession()));
			}
			if (path === `/api/v1/chat-sessions/${sessionId}/messages` && request.method() === 'GET') {
				return route.fulfill(json({ items: trajectory, pending_approval: pendingApproval }));
			}
			if (path === `/api/v1/chat-sessions/${sessionId}/messages` && request.method() === 'POST') {
				const prompt = String(request.postDataJSON().message ?? '');
				messageSequence += 1;
				const turn = agentTurn(prompt, messageSequence);
				trajectory = [...trajectory, ...turn.messages];
				pendingApproval = turn.pending_approval;
				return route.fulfill(json(turn));
			}
			if (/\/tool-calls\/call_write_[12]\/decision$/.test(path) && request.method() === 'POST') {
				const decision = request.postDataJSON() as Record<string, unknown>;
				const approvedCallId = String(pendingApproval?.tool_call_id ?? '');
				decisions.push(decision);
				pendingApproval = null;
				if (decision.decision === 'rejected') {
					return route.fulfill(
						json({
							status: 'rejected',
							messages: [],
							pending_approval: null,
							error_code: null
						})
					);
				}
				const completed = approvedAgentTurn(approvedCallId);
				trajectory = [...trajectory, ...completed.messages];
				return route.fulfill(json(completed));
			}
			return route.fallback();
		};

		await page.route('**/api/v1/chat-sessions', handleChatRoute);
		await page.route('**/api/v1/chat-sessions/**', handleChatRoute);
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(`/collections/${collectionId}/assistant`);

		await sendAgentMessage(page, 'Hello');
		await expect(page.getByText('Hello. I can help you work with this collection.')).toBeVisible();
		await expect(page.getByLabel('Research activity')).toHaveCount(0);

		await sendAgentMessage(page, 'What published findings are available?');
		await expect(page.getByText('Published findings completed')).toBeVisible();
		await expect(page.getByText('1 findings · 3 evidence records')).toBeVisible();
		await expect(page.getByText('One paper used a different heat treatment.')).toBeVisible();
		await expect(page.getByRole('link', { name: 'Open finding' })).toHaveAttribute(
			'href',
			`/collections/${collectionId}/objectives/${objectiveId}?finding_id=finding-1`
		);

		await sendAgentMessage(page, 'Suggest a focused objective');
		await expect(page.getByText('How does energy input affect grain morphology?')).toBeVisible();
		await expect(page.getByText('Proposal context: collection_supported')).toBeVisible();

		await sendAgentMessage(page, 'Create that objective');
		await expect(page.getByRole('heading', { name: 'Approval required' })).toBeVisible();
		await expect(page.getByLabel('Message')).toBeDisabled();
		await page.getByRole('button', { name: 'Reject' }).click();
		await expect(page.getByText('The proposed write was rejected.')).toBeVisible();

		await sendAgentMessage(page, 'Create that objective');
		await expect(page.getByRole('heading', { name: 'Approval required' })).toBeVisible();
		await page.setViewportSize({ width: 390, height: 844 });
		await page.reload();
		await expect(page.getByRole('heading', { name: 'Approval required' })).toBeVisible();
		await expect(page.getByLabel('Message')).toBeDisabled();
		expect(await visibleElementsFitViewport(page, '.approval')).toBe(true);
		await page.getByRole('button', { name: 'Approve and create' }).click();

		await expect(
			page.getByText('The objective candidate was created for your review.')
		).toBeVisible();
		await expect(page.getByRole('link', { name: 'Open research objective' })).toHaveAttribute(
			'href',
			`/collections/${collectionId}/objectives/obj_agent_1`
		);
		expect(decisions).toEqual([
			{ decision: 'rejected', arguments_digest: 'digest_exact_1' },
			{ decision: 'approved', arguments_digest: 'digest_exact_1' }
		]);
		expect(consoleErrors).toEqual([]);
		await expectNoHorizontalOverflow(page);

		if (screenshotDir) {
			await page.screenshot({
				path: join(screenshotDir, 'research-agent-approved-mobile.png'),
				fullPage: true
			});
		}
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

	test('unprocessed collections still allow Research Agent conversation', async ({ page }) => {
		const consoleErrors: string[] = [];
		page.on('console', (message) => {
			if (message.type() === 'error' || message.type() === 'warning') {
				consoleErrors.push(message.text());
			}
		});
		page.on('pageerror', (error) => consoleErrors.push(error.message));

		await page.goto(`/collections/${collectionId}/assistant?audit_state=uploaded`);

		await expect(page.getByRole('heading', { level: 1, name: 'Research Agent' })).toBeVisible();
		await expect(page.getByLabel('Message')).toBeEnabled();
		await expect(page.getByRole('heading', { name: 'Processing required' })).toHaveCount(0);
		expect(consoleErrors).toEqual([]);
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

	test('mobile document reader exposes Source modes without clipping', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/collections/${collectionId}/documents/${documentId}?view=parsed-paper`);

		await expect(page.getByText('Paper A').first()).toBeVisible();
		expect(await visibleElementsFitViewport(page, '.reader-header')).toBe(true);
		expect(await visibleElementsFitViewport(page, '.reader-mode-tabs')).toBe(true);
		await expect(page.getByRole('tab', { name: 'Parsed Paper' })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'PDF Preview' })).toBeVisible();
	});

	test('published Finding comparison remains readable on mobile', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(`/collections/${collectionId}/comparisons`);

		await expect(page.getByRole('heading', { name: 'Cross-paper findings' })).toBeVisible();
		await expect(
			page.getByText('Annealing was associated with higher tensile strength.')
		).toBeVisible();
		await expect(page.getByRole('link', { name: 'Review finding evidence' })).toBeVisible();
		expect(await visibleElementsFitViewport(page, '.finding-item')).toBe(true);
	});
});

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

async function waitForVisualReady(page: Page, _path: string) {
	await page.waitForLoadState('networkidle');
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
		if (path === `/api/v1/collections/${collectionId}/documents/${documentId}/source`) {
			return route.fulfill({ status: 204, body: '' });
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
		if (
			path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/findings/finding-1`
		) {
			return route.fulfill(
				json({
					collection_id: collectionId,
					objective_id: objectiveId,
					analysis_version: 1,
					finding: objectiveFinding()
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
		if (path === `/api/v1/collections/${collectionId}/objectives/${objectiveId}/evidence-map`) {
			return route.fulfill(json(objectiveEvidenceMap()));
		}
		if (path === '/api/v1/chat-sessions') return route.fulfill(json(chatSession(), 201));
		if (path === `/api/v1/chat-sessions/${sessionId}`) return route.fulfill(json(chatSession()));
		if (path === `/api/v1/chat-sessions/${sessionId}/messages`) {
			return route.fulfill(json({ items: [], pending_approval: null }));
		}

		return route.fulfill(json({ detail: `unhandled audit route: ${path}` }, 404));
	});
}

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

async function sendAgentMessage(page: Page, text: string) {
	await page.getByLabel('Message').fill(text);
	await page.getByRole('button', { name: 'Send' }).click();
}

function agentMessage(
	messageId: string,
	role: 'user' | 'assistant' | 'tool',
	content: string,
	overrides: Record<string, unknown> = {}
) {
	return {
		message_id: messageId,
		session_id: sessionId,
		role,
		content,
		created_at: now(),
		tool_call_id: null,
		tool_name: null,
		tool_arguments: null,
		tool_result: null,
		...overrides
	};
}

function agentTurn(prompt: string, sequence: number) {
	const user = agentMessage(`msg_user_${sequence}`, 'user', prompt);
	if (prompt === 'Hello') {
		return {
			status: 'completed',
			messages: [
				user,
				agentMessage(
					`msg_assistant_${sequence}`,
					'assistant',
					'Hello. I can help you work with this collection.'
				)
			],
			pending_approval: null,
			error_code: null
		};
	}

	if (prompt === 'What published findings are available?') {
		const callId = `call_read_${sequence}`;
		return {
			status: 'completed',
			messages: [
				user,
				agentMessage(`msg_call_${sequence}`, 'assistant', '', {
					tool_call_id: callId,
					tool_name: 'query_published_findings',
					tool_arguments: { query: 'energy input' }
				}),
				agentMessage(`msg_result_${sequence}`, 'tool', '', {
					tool_call_id: callId,
					tool_result: {
						tool_call_id: callId,
						status: 'succeeded',
						data: { finding_count: 1, evidence_count: 3 },
						resource_refs: [
							{
								resource_type: 'finding',
								resource_id: 'finding-1',
								href: `/collections/${collectionId}/objectives/${objectiveId}?finding_id=finding-1`
							}
						],
						warnings: ['One paper used a different heat treatment.'],
						error_code: null,
						error_message: null
					}
				}),
				agentMessage(
					`msg_assistant_${sequence}`,
					'assistant',
					'One published finding is available for expert review.'
				)
			],
			pending_approval: null,
			error_code: null
		};
	}

	if (prompt === 'Suggest a focused objective') {
		const callId = `call_draft_${sequence}`;
		return {
			status: 'completed',
			messages: [
				user,
				agentMessage(`msg_call_${sequence}`, 'assistant', '', {
					tool_call_id: callId,
					tool_name: 'propose_objective_drafts',
					tool_arguments: { question: 'energy input effects' }
				}),
				agentMessage(`msg_result_${sequence}`, 'tool', '', {
					tool_call_id: callId,
					tool_result: {
						tool_call_id: callId,
						status: 'succeeded',
						data: {
							draft_count: 1,
							drafts: [
								{
									question: 'How does energy input affect grain morphology?',
									variables: ['energy input'],
									outcomes: ['grain morphology'],
									support_status: 'collection_supported'
								}
							]
						},
						resource_refs: [],
						warnings: [],
						error_code: null,
						error_message: null
					}
				}),
				agentMessage(
					`msg_assistant_${sequence}`,
					'assistant',
					'I drafted one focused, single-outcome question.'
				)
			],
			pending_approval: null,
			error_code: null
		};
	}

	const callId = `call_write_${sequence - 3}`;
	const arguments_ = {
		question: 'How does energy input affect grain morphology?',
		variables: ['energy input'],
		outcomes: ['grain morphology']
	};
	const approval = {
		tool_call_id: callId,
		session_id: sessionId,
		assistant_message_id: `msg_call_${sequence}`,
		name: 'create_objective_candidate',
		arguments: arguments_,
		arguments_digest: 'digest_exact_1',
		risk: 'write',
		status: 'approval_required',
		started_at: null,
		finished_at: null,
		error_code: null,
		decision_user_id: null,
		decision_arguments_digest: null,
		decided_at: null
	};
	return {
		status: 'approval_required',
		messages: [
			user,
			agentMessage(`msg_call_${sequence}`, 'assistant', '', {
				tool_call_id: callId,
				tool_name: 'create_objective_candidate',
				tool_arguments: arguments_
			})
		],
		pending_approval: approval,
		error_code: null
	};
}

function approvedAgentTurn(callId: string) {
	return {
		status: 'completed',
		messages: [
			agentMessage('msg_result_approved', 'tool', '', {
				tool_call_id: callId,
				tool_result: {
					tool_call_id: callId,
					status: 'succeeded',
					data: { objective_id: 'obj_agent_1' },
					resource_refs: [
						{
							resource_type: 'research_objective',
							resource_id: 'obj_agent_1',
							href: `/collections/${collectionId}/objectives/obj_agent_1`
						}
					],
					warnings: [],
					error_code: null,
					error_message: null
				}
			}),
			agentMessage(
				'msg_assistant_approved',
				'assistant',
				'The objective candidate was created for your review.'
			)
		],
		pending_approval: null,
		error_code: null
	};
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
					documents: { status: 'not_started', detail: 'Document profiling is pending.' },
					objectives: { status: 'not_started', detail: 'Objective discovery is pending.' }
				}
			: {
					documents: { status: 'ready', detail: 'Document profiles are available.' },
					objectives: { status: 'ready', detail: 'Objective discovery is complete.' }
				},
		document_summary: {
			total_documents: 2,
			by_doc_type: { experimental: 2, review: 0, mixed: 0, uncertain: 0 }
		},
		warnings: [],
		artifacts: {
			source_documents_ready: !unprocessed,
			document_profiles_ready: !unprocessed,
			objective_candidates_ready: !unprocessed,
			updated_at: now()
		},
		latest_task: null,
		recent_tasks: [],
		capabilities: {
			can_view_documents: !unprocessed,
			can_view_objectives: !unprocessed,
			can_view_comparisons: !unprocessed
		},
		links: {
			workspace: `/collections/${collectionId}`,
			documents: `/collections/${collectionId}/documents`,
			objectives: `/collections/${collectionId}/objectives`,
			comparisons: `/collections/${collectionId}/comparisons`
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
				text_unit_ids: [],
				page: 1
			},
			{
				block_id: 'results',
				block_type: 'results',
				heading_path: 'Results',
				heading_level: 1,
				order: 2,
				text: 'Conductivity improved to 12 mS/cm under EIS.',
				text_unit_ids: [],
				page: 3
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

function objectives() {
	return {
		collection_id: collectionId,
		objectives: [
			{
				collection_id: collectionId,
				objective_id: objectiveId,
				question: 'How does heat treatment affect LPBF 316L tensile strength?',
				material_scope: ['316L stainless steel'],
				variables: ['heat treatment'],
				outcomes: ['yield strength'],
				mechanisms: ['precipitate evolution'],
				constraints: ['LPBF 316L'],
				requested_comparator: 'Compare as-built and heat-treated LPBF 316L.',
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
		statement: 'Annealing was associated with higher tensile strength.',
		factors: ['heat treatment'],
		outcome: 'tensile strength',
		direction: 'increase',
		assertion_strength: 'associative',
		attribution_scope: 'isolated_effect',
		synthesis_status: 'insufficient_confirmation',
		certainty: 0.88,
		display_rank: 0,
		mechanisms: [
			{
				source_term: 'annealing',
				relation_type: 'associated_with',
				target_term: 'tensile strength',
				direction: 'increase',
				assertion_strength: 'associative',
				supporting_evidence_ids: ['evidence-1']
			}
		],
		scientific_context: {
			material: [{ name: 'alloy', value: '316L', unit: null }],
			sample: [{ name: 'state', value: 'annealed', unit: null }],
			process: [{ name: 'process', value: 'LPBF', unit: null }],
			test: [{ name: 'method', value: 'tensile test', unit: null }]
		},
		limitations: ['Single paper only.'],
		paper_contributions: [
			{
				document_id: documentId,
				analysis_status: 'analyzed',
				supporting_evidence_ids: ['evidence-1'],
				contradicting_evidence_ids: [],
				context_evidence_ids: [],
				condition_boundary_evidence_ids: []
			}
		]
	};
}

function objectiveEvidenceMap() {
	return {
		collection_id: collectionId,
		objective_id: objectiveId,
		analysis_version: 1,
		projection_version: 'objective-evidence-map.v1',
		complete: true,
		coverage: {
			total_document_count: 3,
			analyzed_document_count: 2,
			excluded_document_count: 0,
			failed_document_count: 1,
			direct_evidence_document_count: 2,
			finding_count: 1,
			evidence_count: 2,
			source_count: 2,
			unlinked_evidence_count: 0
		},
		nodes: [
			{
				id: `objective:${objectiveId}`,
				type: 'objective',
				label: 'How does heat treatment affect LPBF 316L tensile strength?',
				objective_id: objectiveId,
				question: 'How does heat treatment affect LPBF 316L tensile strength?',
				material_scope: ['316L stainless steel'],
				variables: ['heat treatment'],
				outcomes: ['tensile strength']
			},
			{
				id: 'finding:finding-1',
				type: 'finding',
				label: 'Annealing was associated with higher tensile strength.',
				finding_id: 'finding-1',
				statement: 'Annealing was associated with higher tensile strength.',
				factors: ['heat treatment'],
				outcome: 'tensile strength',
				direction: 'increase',
				assertion_strength: 'associative',
				synthesis_status: 'conflict',
				certainty: 0.62,
				limitations: ['One paper reported the opposing direction.']
			},
			{
				id: 'evidence:evidence-1',
				type: 'evidence',
				label: 'Annealing increased tensile strength to 620 MPa.',
				evidence_id: 'evidence-1',
				document_id: documentId,
				evidence_role: 'direct_result',
				attribution_scope: 'isolated_effect',
				confidence: 0.88,
				direction: 'increase',
				outcome: 'tensile strength',
				source_excerpt: 'After annealing, tensile strength increased to 620 MPa.'
			},
			{
				id: 'evidence:evidence-2',
				type: 'evidence',
				label: 'A second treatment decreased tensile strength.',
				evidence_id: 'evidence-2',
				document_id: 'doc_2',
				evidence_role: 'contradictory_result',
				attribution_scope: 'association_only',
				confidence: 0.76,
				direction: 'decrease',
				outcome: 'tensile strength',
				source_excerpt: 'The treated condition showed lower tensile strength.'
			},
			{
				id: 'source:source-1',
				type: 'source',
				label: 'Table · table-7',
				document_id: documentId,
				source_kind: 'table',
				source_ref: 'table-7',
				source_excerpt: 'After annealing, tensile strength increased to 620 MPa.',
				page_numbers: [7],
				evidence_ids: ['evidence-1']
			},
			{
				id: 'source:source-2',
				type: 'source',
				label: 'Results · result-2',
				document_id: 'doc_2',
				source_kind: 'block',
				source_ref: 'result-2',
				source_excerpt: 'The treated condition showed lower tensile strength.',
				page_numbers: [5],
				evidence_ids: ['evidence-2']
			},
			{
				id: `document:${documentId}`,
				type: 'document',
				label: 'Paper A',
				document_id: documentId,
				analysis_status: 'analyzed',
				evidence_disposition: 'comparable_evidence',
				evidence_disposition_reason: null
			},
			{
				id: 'document:doc_2',
				type: 'document',
				label: 'Paper B',
				document_id: 'doc_2',
				analysis_status: 'analyzed',
				evidence_disposition: 'comparable_evidence',
				evidence_disposition_reason: null
			},
			{
				id: 'document:doc_3',
				type: 'document',
				label: 'Paper C extraction gap',
				document_id: 'doc_3',
				analysis_status: 'failed',
				evidence_disposition: 'extraction_failed',
				evidence_disposition_reason: 'Provider timeout during source extraction.'
			}
		],
		edges: [
			{
				id: 'edge-1',
				source: `objective:${objectiveId}`,
				target: 'finding:finding-1',
				relation: 'has_finding',
				condition_boundary: false
			},
			{
				id: 'edge-2',
				source: 'finding:finding-1',
				target: 'evidence:evidence-1',
				relation: 'supports',
				condition_boundary: false
			},
			{
				id: 'edge-3',
				source: 'finding:finding-1',
				target: 'evidence:evidence-2',
				relation: 'contradicts',
				condition_boundary: true
			},
			{
				id: 'edge-4',
				source: 'evidence:evidence-1',
				target: 'source:source-1',
				relation: 'extracted_from',
				condition_boundary: false
			},
			{
				id: 'edge-5',
				source: 'evidence:evidence-2',
				target: 'source:source-2',
				relation: 'extracted_from',
				condition_boundary: false
			},
			{
				id: 'edge-6',
				source: 'source:source-1',
				target: `document:${documentId}`,
				relation: 'reported_in',
				condition_boundary: false
			},
			{
				id: 'edge-7',
				source: 'source:source-2',
				target: 'document:doc_2',
				relation: 'reported_in',
				condition_boundary: false
			},
			{
				id: 'edge-8',
				source: `objective:${objectiveId}`,
				target: 'document:doc_3',
				relation: 'includes_document',
				condition_boundary: false
			}
		]
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
		changed_variables: [
			{
				name: 'heat treatment',
				baseline_value: 'as-built',
				target_value: 'annealed',
				unit: null
			}
		],
		comparison: {
			baseline_label: 'as-built',
			target_label: 'annealed',
			axis_names: ['heat treatment'],
			comparable: true,
			incomparability_reasons: []
		},
		reported_result: {
			outcome: 'tensile strength',
			value: 620,
			unit: 'MPa',
			direction: 'increase',
			result_text: 'After annealing, tensile strength increased to 620 MPa.'
		},
		attribution_scope: 'isolated_effect',
		scientific_context: {
			material: [{ name: 'alloy', value: '316L', unit: null }],
			sample: [{ name: 'state', value: 'annealed', unit: null }],
			process: [{ name: 'process', value: 'LPBF', unit: null }],
			test: [{ name: 'method', value: 'tensile test', unit: null }]
		},
		anchor_ids: [],
		resolution_status: 'resolved',
		failure_reason: null,
		confidence: 0.92
	};
}

function chatSession() {
	return {
		session_id: sessionId,
		user_id: 'user_1',
		collection_id: collectionId,
		created_at: now(),
		updated_at: now()
	};
}
