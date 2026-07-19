#!/usr/bin/env node
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const DEFAULT_FRONTEND_ORIGIN = 'http://127.0.0.1:5173';
const DEFAULT_COLLECTION_ID = 'col_0cc5013fdb3c';
const DEFAULT_OUTPUT_DIR = '/tmp/lens-goal-evidence-link-check';

function readArgValue(name) {
	const prefix = `${name}=`;
	const inline = process.argv.find((arg) => arg.startsWith(prefix));
	if (inline) return inline.slice(prefix.length);
	const index = process.argv.indexOf(name);
	if (index >= 0) return process.argv[index + 1];
	return undefined;
}

function readListArg(name) {
	const values = [];
	const prefix = `${name}=`;
	for (let index = 0; index < process.argv.length; index += 1) {
		const arg = process.argv[index];
		if (arg.startsWith(prefix)) {
			values.push(...arg.slice(prefix.length).split(','));
		} else if (arg === name && process.argv[index + 1]) {
			values.push(...process.argv[index + 1].split(','));
		}
	}
	return values.map((value) => value.trim()).filter(Boolean);
}

function cleanOrigin(value) {
	return (value || DEFAULT_FRONTEND_ORIGIN).replace(/\/$/, '');
}

function apiPath(collectionId, goalId = '') {
	const encodedCollection = encodeURIComponent(collectionId);
	if (!goalId) return `/api/v1/collections/${encodedCollection}/goals`;
	return `/api/v1/collections/${encodedCollection}/goals/${encodeURIComponent(goalId)}/analysis`;
}

function goalUrl(origin, collectionId, goalId) {
	return `${origin}/collections/${encodeURIComponent(collectionId)}/goals/${encodeURIComponent(goalId)}`;
}

function sourceUrlIsUsable(url, expectedCollectionId) {
	const parsed = new URL(url);
	return (
		parsed.pathname.includes(`/collections/${expectedCollectionId}/documents/`) &&
		parsed.searchParams.get('view') === 'parsed-paper' &&
		Boolean(parsed.searchParams.get('source_ref')) &&
		Boolean(parsed.searchParams.get('quote'))
	);
}

function firstWordsPattern(text, count = 8) {
	const words = text
		.split(/\s+/)
		.map((word) => word.trim())
		.filter(Boolean)
		.slice(0, count)
		.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
	if (!words.length) return null;
	return new RegExp(words.join('\\s+'), 'i');
}

function tableAuditRowText(row) {
	return (row?.cells ?? [])
		.map((cell) => String(cell ?? '').trim())
		.filter(Boolean)
		.join(' | ');
}

function normalizeMatchText(text) {
	return String(text ?? '')
		.toLowerCase()
		.replace(/[^0-9a-z%°.+\-/]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

function dedupe(values) {
	const seen = new Set();
	const result = [];
	for (const value of values) {
		const text = String(value ?? '').trim();
		if (!text || seen.has(text)) continue;
		seen.add(text);
		result.push(text);
	}
	return result;
}

function statementNumericEndpoints(statement) {
	const text = String(statement ?? '');
	const endpoints = [];
	const fromPattern = /\bfrom\s+([-+]?\d+(?:\.\d+)?)/gi;
	let match;
	while ((match = fromPattern.exec(text)) !== null) {
		const trailing = text.slice(match.index + match[0].length, match.index + match[0].length + 120);
		const observed = /\bto\s+([-+]?\d+(?:\.\d+)?)/i.exec(trailing);
		if (!observed) continue;
		endpoints.push(match[1], observed[1]);
	}
	return dedupe(endpoints);
}

function numericEndpointMatchTerms(value) {
	const number = String(value ?? '').trim();
	if (!number) return [];
	const terms = [number];
	if (number.includes('.')) {
		terms.push(number.replace(/0+$/, '').replace(/\.$/, ''));
	} else {
		terms.push(`${number}.0`);
	}
	return dedupe(terms);
}

function numericEndpointPresent(text, endpoint) {
	const normalized = normalizeMatchText(text);
	if (
		numericEndpointMatchTerms(endpoint).some((term) =>
			new RegExp(`(?<!\\d)${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?!\\d)`).test(
				normalized
			)
		)
	) {
		return true;
	}
	const endpointNumber = Number(endpoint);
	if (!Number.isFinite(endpointNumber)) return false;
	const candidates = normalized.match(/[-+]?\d+(?:\.\d+)?/g) ?? [];
	return candidates.some((candidate) => Number(candidate) === endpointNumber);
}

async function apiJson(page, origin, pathName) {
	const targetUrl = new URL(pathName, origin).toString();
	const response = await page.context().request.get(targetUrl);
	const body = await response.text();
	if (!response.ok()) {
		throw new Error(`${pathName} failed: ${response.status()} ${response.statusText()} ${body}`);
	}
	return body ? JSON.parse(body) : {};
}

async function loginIfConfigured(page, origin) {
	const email = process.env.LENS_CHECK_EMAIL;
	const password = process.env.LENS_CHECK_PASSWORD;
	if (!email && !password) return;
	if (!email || !password) {
		throw new Error('set both LENS_CHECK_EMAIL and LENS_CHECK_PASSWORD for authenticated checks');
	}
	const response = await page.context().request.post(`${origin}/api/v1/auth/login`, {
		data: { email, password }
	});
	if (!response.ok()) {
		throw new Error(`POST /api/v1/auth/login failed: ${response.status()} ${await response.text()}`);
	}
}

async function readGoalIds(page, origin, collectionId, requestedGoalIds) {
	if (requestedGoalIds.length) return requestedGoalIds;
	const response = await apiJson(page, origin, apiPath(collectionId));
	return (response.goals ?? []).map((goal) => goal.goal_id).filter(Boolean);
}

async function findingLabels(page, origin, collectionId, goalId) {
	const response = await apiJson(page, origin, apiPath(collectionId, goalId));
	const presentation = response?.understanding?.presentation ?? {};
	const evidenceById = new Map(
		(presentation.evidence_items ?? [])
			.filter((item) => item?.evidence_ref_id)
			.map((item) => [String(item.evidence_ref_id), item])
	);
	const findingGroups = [
		['primary', presentation.primary_findings ?? []],
		['review_queue', presentation.review_queue_findings ?? []]
	];
	return findingGroups
		.flatMap(([findingType, findings]) =>
			findings.map((finding, findingIndex) => ({
				finding_id: finding.finding_id,
				finding_index: findingIndex,
				finding_type: findingType,
				statement: String(finding.statement || finding.title || '').trim(),
				direct_result_count: finding?.evidence_bundle?.direct_result?.length ?? 0,
				table_evidence_audits: (finding?.evidence_bundle?.direct_result ?? [])
					.map((evidenceId) => evidenceById.get(String(evidenceId)))
					.filter((item) => item?.source_kind === 'table')
					.map((item) => ({
						evidence_ref_id: String(item.evidence_ref_id),
						href: String(item.href ?? ''),
						columns: (item.table_audit?.columns ?? []).map((column) => String(column)),
						has_audit: Boolean(item.table_audit),
						rows: (item.table_audit?.relevant_rows ?? []).map((row) => ({
							row_index: row?.row_index,
							text: tableAuditRowText(row)
						}))
					}))
			}))
		)
		.filter((finding) => finding.finding_id && finding.direct_result_count > 0);
}

async function verifyFindingEvidenceLinks(page, origin, collectionId, goalId, finding) {
	await page.goto(goalUrl(origin, collectionId, goalId), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle').catch(() => undefined);
	await page.getByRole('heading', { name: 'Research understanding' }).waitFor({ timeout: 30_000 });
	await showFindingType(page, finding.finding_type);

	const findingPattern = firstWordsPattern(finding.statement);
	const findingButton = findingPattern
		? page.getByRole('button', { name: findingPattern }).first()
		: page.getByRole('button', { name: 'Review evidence' }).nth(finding.finding_index);
	if ((await findingButton.count()) < 1) {
		throw new Error(
			`${goalId} ${finding.finding_type} ${finding.finding_id}: expected finding row button for ${finding.statement}`
		);
	}
	await findingButton.click();
	const detailPanel = page.getByLabel('Finding detail');
	await detailPanel.waitFor({ timeout: 10_000 });

	const directSection = page.locator('section').filter({
		has: page.getByRole('heading', { name: 'Direct result evidence' })
	});
	const sourceLinks = directSection.getByRole('link', { name: 'Open source' });
	const linkCount = await sourceLinks.count();
	const checks = [];
	if (linkCount !== finding.direct_result_count) {
		checks.push({
			status: 'fail',
			reason: 'direct evidence link count mismatch',
			expected_direct_result_count: finding.direct_result_count,
			checked_links: linkCount
		});
	}
	for (const tableAudit of finding.table_evidence_audits ?? []) {
		if (!tableAudit.has_audit) {
			checks.push({
				status: 'fail',
				reason: 'table evidence audit is missing',
				evidence_ref_id: tableAudit.evidence_ref_id
			});
			continue;
		}
		const rowTexts = tableAudit.rows.map((row) => row.text).filter(Boolean);
		const detailText = await detailPanel.innerText({ timeout: 10_000 }).catch(() => '');
		const missingColumns = tableAudit.columns.filter((column) => column && !detailText.includes(column));
		const missingRows = rowTexts.filter((rowText) => rowText && !detailText.includes(rowText));
		checks.push({
			status:
				rowTexts.length > 0 &&
				detailText.includes('Relevant table rows') &&
				missingColumns.length === 0 &&
				missingRows.length === 0
					? 'pass'
					: 'fail',
			reason: 'table evidence audit is rendered',
			evidence_ref_id: tableAudit.evidence_ref_id,
			has_relevant_table_rows_label: detailText.includes('Relevant table rows'),
			expected_row_count: rowTexts.length,
			missing_columns: missingColumns,
			missing_rows: missingRows
		});
	}
	const endpointTerms = statementNumericEndpoints(finding.statement);
	const tableRowText = (finding.table_evidence_audits ?? [])
		.flatMap((tableAudit) => tableAudit.rows ?? [])
		.map((row) => row.text)
		.filter(Boolean)
		.join(' ');
	if (endpointTerms.length && tableRowText) {
		const missingEndpoints = endpointTerms.filter(
			(endpoint) => !numericEndpointPresent(tableRowText, endpoint)
		);
		checks.push({
			status: missingEndpoints.length ? 'fail' : 'pass',
			reason: 'table evidence rows cover statement numeric endpoints',
			endpoints: endpointTerms,
			missing_endpoints: missingEndpoints
		});
	}
	for (let index = 0; index < linkCount; index += 1) {
		const link = sourceLinks.nth(index);
		const href = await link.getAttribute('href');
		if (!href) {
			checks.push({ status: 'fail', reason: 'missing href', index });
			continue;
		}
		const absoluteHref = new URL(href, origin).toString();
		const sourcePage = await page.context().newPage();
		await sourcePage.goto(absoluteHref, { waitUntil: 'domcontentloaded' });
		await sourcePage.waitForLoadState('domcontentloaded').catch(() => undefined);
		await sourcePage.waitForLoadState('networkidle').catch(() => undefined);
		const currentUrl = sourcePage.url();
		const bodyText = await sourcePage.locator('body').innerText({ timeout: 10_000 }).catch(() => '');
		const selectedQuotePanelCount = await sourcePage
			.getByTestId('markdown-selected-evidence-quote')
			.count()
			.catch(() => 0);
		const parsedUrl = new URL(currentUrl);
		const quote = parsedUrl.searchParams.get('quote') ?? '';
		const quotePreview = quote.slice(0, Math.min(80, quote.length));
		checks.push({
			status:
				sourceUrlIsUsable(currentUrl, collectionId) &&
				bodyText.includes('Parsed Paper') &&
				selectedQuotePanelCount > 0 &&
				quote &&
				bodyText.includes(quotePreview)
					? 'pass'
					: 'fail',
			index,
			expected_href: absoluteHref,
			actual_url: currentUrl,
			has_parsed_paper: bodyText.includes('Parsed Paper'),
			has_selected_quote_panel: selectedQuotePanelCount > 0,
			has_quote_preview: Boolean(quote && bodyText.includes(quotePreview)),
			source_ref: parsedUrl.searchParams.get('source_ref'),
			quote_length: quote.length
		});
		await sourcePage.close();
	}
	return {
		goal_id: goalId,
		finding_id: finding.finding_id,
		finding_type: finding.finding_type,
		statement: finding.statement,
		expected_direct_result_count: finding.direct_result_count,
		checked_links: linkCount,
		checks
	};
}

async function showFindingType(page, findingType) {
	const reviewQueueButton = page.getByRole('button', { name: /Review candidates \d+/ }).first();
	if ((await reviewQueueButton.count()) < 1) return;
	const isPressed = (await reviewQueueButton.getAttribute('aria-pressed')) === 'true';
	if (findingType === 'review_queue' && !isPressed) {
		await reviewQueueButton.click();
	} else if (findingType !== 'review_queue' && isPressed) {
		await reviewQueueButton.click();
	}
}

async function main() {
	const origin = cleanOrigin(readArgValue('--frontend-origin') ?? process.env.LENS_FRONTEND_ORIGIN);
	const collectionId =
		readArgValue('--collection-id') ?? process.env.LENS_COLLECTION_ID ?? DEFAULT_COLLECTION_ID;
	const outputDir = readArgValue('--output') ?? process.env.LENS_LINK_CHECK_OUTPUT ?? DEFAULT_OUTPUT_DIR;
	const requestedGoalIds = readListArg('--goal-id');
	const assertClean = process.argv.includes('--assert-clean');

	await mkdir(outputDir, { recursive: true });
	const browser = await chromium.launch();
	const context = await browser.newContext();
	const page = await context.newPage();
	const consoleMessages = [];
	const pageErrors = [];
	page.on('console', (message) => {
		if (['warning', 'error'].includes(message.type())) {
			consoleMessages.push({ type: message.type(), text: message.text() });
		}
	});
	page.on('pageerror', (error) => {
		pageErrors.push({ name: error.name, message: error.message });
	});

	try {
		await loginIfConfigured(page, origin);
		if (!process.env.LENS_CHECK_EMAIL) {
			await page.goto(origin, { waitUntil: 'domcontentloaded' });
		}
		const goalIds = await readGoalIds(page, origin, collectionId, requestedGoalIds);
		if (!goalIds.length) {
			throw new Error(`no goals found for collection ${collectionId}`);
		}
		const results = [];
		for (const goalId of goalIds) {
			const findings = await findingLabels(page, origin, collectionId, goalId);
			for (const finding of findings) {
				results.push(await verifyFindingEvidenceLinks(page, origin, collectionId, goalId, finding));
			}
		}
		const goalCoverage = goalIds.map((goalId) => {
			const goalResults = results.filter((result) => result.goal_id === goalId);
			return {
				goal_id: goalId,
				checked_finding_count: goalResults.length,
				checked_link_count: goalResults.reduce((count, result) => count + result.checked_links, 0)
			};
		});
		const failedChecks = results.flatMap((result) =>
			result.checks
				.filter((check) => check.status !== 'pass')
				.map((check) => ({ goal_id: result.goal_id, finding_id: result.finding_id, ...check }))
		);
		const checkedLinkCount = results.reduce((count, result) => count + result.checked_links, 0);
		if (!results.length) {
			failedChecks.push({
				status: 'fail',
				reason: 'no findings with direct evidence were available to check',
				goal_count: goalIds.length
			});
		}
		if (!checkedLinkCount) {
			failedChecks.push({
				status: 'fail',
				reason: 'no evidence links were checked',
				goal_count: goalIds.length
			});
		}
		for (const coverage of goalCoverage) {
			if (!coverage.checked_finding_count || !coverage.checked_link_count) {
				failedChecks.push({
					status: 'fail',
					reason: 'goal has no checked findings or evidence links',
					...coverage
				});
			}
		}
		const summary = {
			status: failedChecks.length || consoleMessages.length || pageErrors.length ? 'fail' : 'pass',
			origin,
			collection_id: collectionId,
			goal_count: goalIds.length,
			checked_finding_count: results.length,
			checked_link_count: checkedLinkCount,
			goal_coverage: goalCoverage,
			results,
			failed_checks: failedChecks,
			consoleMessages,
			pageErrors,
			capturedAt: new Date().toISOString()
		};
		const summaryPath = path.join(outputDir, 'summary.json');
		await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
		console.log(JSON.stringify(summary, null, 2));
		if (assertClean && summary.status !== 'pass') process.exitCode = 1;
	} finally {
		await browser.close();
	}
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
