import { expect, test, type Page } from '@playwright/test';

const collectionId = 'col_feedback';
const caseId = 'case_feedback';
const digest = 'a'.repeat(64);

function json(body: unknown, status = 200) {
	return { status, contentType: 'application/json', body: JSON.stringify(body) };
}

type MockFeedbackApisOptions = {
	sourceSignals?: Array<Record<string, unknown>>;
};

async function mockFeedbackApis(page: Page, options: MockFeedbackApisOptions = {}) {
	let status = 'needs_annotation';
	let annotation: Record<string, unknown> | null = null;
	let reviewDecisions: Record<string, unknown>[] = [];
	let reviewAttempts = 0;
	const reviewKeys: string[] = [];
	let datasetMode = false;

	await page.route('**/*', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (!path.startsWith('/api/v1/')) return route.continue();
		if (path === '/api/v1/auth/me') {
			return route.fulfill(
				json({ user: { user_id: 'user_feedback', email: 'reviewer@example.com', display_name: 'Reviewer' } })
			);
		}
		if (path === '/api/v1/collections' && request.method() === 'GET') {
			return route.fulfill(
				json({
					items: [
						{
							collection_id: collectionId,
							name: 'Feedback fixture',
							status: 'ready',
							documents: []
						}
					]
				})
			);
		}
		if (path === `/api/v1/collections/${collectionId}` && request.method() === 'GET') {
			return route.fulfill(
				json({ collection_id: collectionId, name: 'Feedback fixture', status: 'ready', documents: [] })
			);
		}
		if (path === '/api/v1/feedback-cases' && request.method() === 'GET') {
			datasetMode = new URL(request.url()).searchParams.get('status') === 'accepted';
			return route.fulfill(
				json({
					items: [
						{
							case_id: caseId,
							collection_id: collectionId,
							status: datasetMode ? 'accepted' : status,
							anchor_message_id: 'answer_feedback',
							problem_type: 'source_missing',
							confidence: 0.87,
							needs_human_review: true,
							created_at: '2026-09-25T00:00:00Z',
							question_preview: 'Compare Paper A and Paper B',
							answer_preview: 'Paper B has no preheating information.',
							document_titles: ['Paper A', 'Paper B'],
							coverage_status: 'partial'
						}
					],
					limit: 50,
					offset: 0
				})
			);
		}
		if (path === `/api/v1/feedback-cases/${caseId}` && request.method() === 'GET') {
			return route.fulfill(
				json({
					case_id: caseId,
					collection_id: collectionId,
					session_id: 'session_feedback',
					status: datasetMode ? 'accepted' : status,
					source_signals: options.sourceSignals ?? [],
					question: 'Compare Paper A and Paper B.',
					answer: 'Paper B has no preheating information.',
					requested_scope: [{ document_id: 'doc_a', title: 'Paper A' }],
						inspected_sources: [{ source_ref: 'source_b', document_title: 'Paper B', heading_path: 'Figure 3 caption', page: 4, quote: 'Preheating at 200 C.' }],
					omitted_candidates: [],
					claim_support: [],
					gaps: ['Paper B figure caption was omitted.'],
					coverage_status: 'partial',
					analysis: { problem_type: 'source_missing', confidence: 0.87, suggested_target: null, model: 'test', result_id: 'result_feedback', coverage_status: 'partial' },
					annotation,
					current_annotation_digest: annotation ? digest : null,
					review_decisions: reviewDecisions,
					technical_error: null,
					created_at: '2026-09-25T00:00:00Z',
					updated_at: '2026-09-25T00:00:00Z'
				})
			);
		}
		if (path === `/api/v1/feedback-cases/${caseId}/annotation` && request.method() === 'PATCH') {
			annotation = {
				annotation_id: 'annotation_feedback',
				case_id: caseId,
				version: annotation ? 2 : 1,
				problem_type: 'source_missing',
				severity: 'high',
				target: null,
				support_source_refs: [],
				dataset_uses: ['evaluation'],
				reason: 'The figure caption was checked.',
				annotation_digest: digest,
				created_by: 'user_feedback',
				created_at: '2026-09-25T00:00:00Z',
				updated_at: '2026-09-25T00:00:00Z'
			};
			status = 'ready_for_review';
			return route.fulfill(json(annotation));
		}
		if (path === `/api/v1/feedback-cases/${caseId}/review` && request.method() === 'POST') {
			reviewKeys.push(request.headers()['idempotency-key'] ?? '');
			reviewAttempts += 1;
			if (reviewAttempts === 1) return route.fulfill(json({ detail: 'temporary failure' }, 503));
			status = 'rejected';
			const decision = {
				decision_id: 'review_feedback',
				case_id: caseId,
				annotation_digest: digest,
				decision: 'reject',
				reason: 'Needs a clearer source explanation.',
				created_by: 'user_feedback',
				seq: 1,
				created_at: '2026-09-25T00:00:00Z'
			};
			reviewDecisions = [decision];
			return route.fulfill(json(decision));
		}
		if (path === `/api/v1/feedback-cases/${caseId}/review-decisions` && request.method() === 'GET') {
			return route.fulfill(json({ items: reviewDecisions }));
		}
		if (path === '/api/v1/dataset-snapshots' && request.method() === 'GET') {
			return route.fulfill(
				json({
					items: [
						{
							dataset_id: 'dataset_feedback',
							collection_id: collectionId,
							dataset_type: 'evaluation',
							manifest_digest: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
							provenance_digest: 'fedcba1234567890fedcba1234567890fedcba1234567890fedcba1234567890',
							content_digest: '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
							row_count: 1,
							excluded_count: 1,
							is_empty: false,
							created_at: '2026-09-25T00:00:00Z'
						}
					],
					limit: 50,
					offset: 0
				})
			);
		}
		if (path === '/api/v1/dataset-snapshots/dataset_feedback' && request.method() === 'GET') {
			return route.fulfill(
				json({
					dataset_id: 'dataset_feedback',
					collection_id: collectionId,
					dataset_type: 'evaluation',
					rows: [],
					exclusions: [{ case_id: caseId, split: 'eval', reason: 'paper_family_missing', detail: 'paper_family_missing:doc_a' }],
					provenance: {},
					manifest: {},
					manifest_digest: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
					provenance_digest: 'fedcba1234567890fedcba1234567890fedcba1234567890fedcba1234567890',
					content_digest: '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
					row_count: 0,
					excluded_count: 1,
					is_empty: true,
					created_at: '2026-09-25T00:00:00Z'
				})
			);
		}
		return route.fulfill(json({ detail: `unhandled test route: ${request.method()} ${path}` }, 404));
	});

	return {
		getReviewKeys: () => reviewKeys,
		getReviewAttempts: () => reviewAttempts
	};
}

test('feedback workbench carries a retry key and keeps the reviewer out of technical IDs', async ({ page }) => {
	const api = await mockFeedbackApis(page);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await page.goto(`/collections/${collectionId}/feedback`);

	await expect(page.getByRole('heading', { name: 'Feedback workbench' })).toBeVisible();
	await page.getByRole('button', { name: /Compare Paper A and Paper B/ }).click();
	await expect(page.getByRole('heading', { name: 'Human annotation' })).toBeVisible();

	const annotationReason = page.locator('.annotation-panel textarea').last();
	await annotationReason.fill('The figure caption was checked.');
	await page.getByRole('button', { name: 'Save annotation' }).click();
	await expect(page.getByRole('heading', { name: 'Review decision' })).toBeVisible();

	const reviewReason = page.locator('.review-panel textarea');
	await reviewReason.fill('Needs a clearer source explanation.');
	await page.getByRole('button', { name: 'Reject' }).click();
	await expect(page.getByRole('alert')).toContainText('request could not be completed');
	await page.getByRole('button', { name: 'Reject' }).click();
	await expect(page.getByText(/Rejected/i).last()).toBeVisible();

	const keys = api.getReviewKeys();
	expect(api.getReviewAttempts()).toBe(2);
	expect(keys[0]).toBeTruthy();
	expect(keys[1]).toBe(keys[0]);
	expect(await page.locator('body').textContent()).not.toContain(caseId);
	expect(await page.locator('body').textContent()).not.toContain('source_b');
	expect(await page.locator('body').textContent()).toContain('Figure 3 caption');
});

test('dataset history uses case context instead of internal identifiers', async ({ page }) => {
	await mockFeedbackApis(page);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(`/collections/${collectionId}/feedback/datasets`);

	await expect(page.getByRole('heading', { name: 'Dataset snapshots' })).toBeVisible();
	await page.locator(`#case-${caseId}`).check();
	await page.getByRole('button', { name: 'View exclusions' }).click();
	await expect(page.getByText('Paper family is missing')).toBeVisible();

	const body = await page.locator('body').textContent();
	expect(body).toContain('Compare Paper A and Paper B');
	expect(body).not.toContain(caseId);
	expect(body).not.toContain('dataset_feedback');
	expect(body).not.toContain('abcdef123456');
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('feedback workbench presents each source signal with its own meaning', async ({ page }) => {
	await mockFeedbackApis(page, {
		sourceSignals: [
			{
				signal_type: 'chat_message_feedback',
				feedback_id: 'feedback_private',
				rating: 'not_helpful',
				reason: 'source_missing',
				comment: 'Paper B was not checked.',
				created_at: '2026-09-25T00:00:00Z'
			},
			{
				signal_type: 'natural_language_correction',
				signal_id: 'signal_correction_private',
				anchor_message_id: 'answer_feedback',
				trigger_message_id: 'challenge_private',
				content: 'You did not inspect Figure 3 in Paper B.',
				problem_type: 'source_missing',
				confidence: 0.91,
				suggested_target: null,
				resolution: 'unresolved_candidate',
				created_at: '2026-09-25T00:01:00Z'
			},
			{
				signal_type: 'tool_failure',
				signal_id: 'signal_tool_private',
				tool_call_id: 'tool_call_private',
				assistant_message_id: 'assistant_private',
				result_message_id: 'result_private',
				tool_name: 'inspect_document_sources',
				error_code: 'source_unavailable',
				problem_type: 'tool_failure',
				confidence: 1,
				suggested_target: null,
				resolution: 'unresolved_candidate',
				created_at: '2026-09-25T00:02:00Z'
			}
		]
	});

	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(`/collections/${collectionId}/feedback`);
	await page.getByRole('button', { name: /Compare Paper A and Paper B/ }).click();

	const correction = page.locator('[data-signal-type="natural_language_correction"]');
	await expect(correction).toContainText('User correction');
	await expect(correction).toContainText('You did not inspect Figure 3 in Paper B.');

	const failure = page.locator('[data-signal-type="tool_failure"]');
	await expect(failure).toContainText('Tool failure');
	await expect(failure).toContainText('inspect document sources');
	await expect(failure).toContainText('source unavailable');

	const body = await page.locator('body').textContent();
	expect(body).not.toContain('signal_correction_private');
	expect(body).not.toContain('tool_call_private');
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
