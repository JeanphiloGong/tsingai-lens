#!/usr/bin/env node
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const DEFAULT_URL = 'http://127.0.0.1:5173/collections/col_0e54529f9c68/graph';
const DEFAULT_OUTPUT_DIR = '/tmp/lens-graph-page-check';

function readArgValue(name) {
	const prefix = `${name}=`;
	const inline = process.argv.find((arg) => arg.startsWith(prefix));
	if (inline) return inline.slice(prefix.length);
	const index = process.argv.indexOf(name);
	if (index >= 0) return process.argv[index + 1];
	return undefined;
}

const positionalUrl = process.argv.slice(2).find((arg) => !arg.startsWith('--'));
const pageUrl = positionalUrl ?? process.env.GRAPH_PAGE_URL ?? DEFAULT_URL;
const outputDir = readArgValue('--output') ?? process.env.GRAPH_CHECK_OUTPUT ?? DEFAULT_OUTPUT_DIR;
const assertClean = process.argv.includes('--assert-clean');

const consoleMessages = [];
const pageErrors = [];

async function capture(page, name, viewport, options = {}) {
	await page.setViewportSize(viewport);
	await page.goto(pageUrl, { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle').catch(() => undefined);
	await page
		.waitForSelector('.graph-page-shell, .graph-empty-state', { timeout: 20_000 })
		.catch(() => undefined);
	await page.waitForTimeout(1_500);

	if (options.selectOverviewNode) {
		const overviewButtons = page.locator('.graph-overview-lists button');
		if ((await overviewButtons.count()) > 0) {
			await overviewButtons.first().click();
			await page.waitForTimeout(700);
		}
	}

	const screenshotPath = path.join(outputDir, `${name}.png`);
	await page.screenshot({ path: screenshotPath, fullPage: true });

	const metrics = await page.evaluate(() => {
		const bodyText = document.body.innerText || '';
		const documentElement = document.documentElement;
		const horizontalOverflow = documentElement.scrollWidth > window.innerWidth + 1;
		const hasLoading = bodyText.includes('Loading graph...');
		const hasLoaded = bodyText.includes('Graph loaded');
		const hasNaN = /\bNaN\b/.test(bodyText);
		return {
			hasNaN,
			loadingLoadedConflict: hasLoading && hasLoaded,
			horizontalOverflow,
			scrollWidth: documentElement.scrollWidth,
			viewportWidth: window.innerWidth,
			hasGraphCanvas: Boolean(document.querySelector('.graph-canvas-shell')),
			hasDetailPanel: Boolean(document.querySelector('.graph-detail-card')),
			hasLinkedPanel: Boolean(document.querySelector('.graph-linked-records'))
		};
	});

	return { name, viewport, screenshotPath, metrics };
}

async function main() {
	await mkdir(outputDir, { recursive: true });
	const browser = await chromium.launch();
	const page = await browser.newPage();

	page.on('console', (message) => {
		const type = message.type();
		if (type === 'warning' || type === 'error') {
			consoleMessages.push({ type, text: message.text() });
		}
	});
	page.on('pageerror', (error) => {
		pageErrors.push({ name: error.name, message: error.message });
	});

	const captures = [
		await capture(page, 'desktop', { width: 1440, height: 1000 }),
		await capture(page, 'selected-desktop', { width: 1440, height: 1000 }, { selectOverviewNode: true }),
		await capture(page, 'mobile', { width: 390, height: 844 })
	];

	await browser.close();

	const checks = {
		hasNaN: captures.some((entry) => entry.metrics.hasNaN),
		loadingLoadedConflict: captures.some((entry) => entry.metrics.loadingLoadedConflict),
		mobileHorizontalOverflow: captures.some(
			(entry) => entry.name === 'mobile' && entry.metrics.horizontalOverflow
		),
		consoleWarnings: consoleMessages.length,
		pageErrors: pageErrors.length
	};
	const summary = {
		url: pageUrl,
		outputDir,
		capturedAt: new Date().toISOString(),
		checks,
		captures,
		consoleMessages,
		pageErrors
	};
	const summaryPath = path.join(outputDir, 'summary.json');
	await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);

	console.log(`Graph page screenshots written to ${outputDir}`);
	console.log(JSON.stringify(checks, null, 2));

	if (assertClean) {
		const failed = Object.entries(checks).filter(([, value]) => value !== false && value !== 0);
		if (failed.length > 0) {
			process.exitCode = 1;
		}
	}
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
