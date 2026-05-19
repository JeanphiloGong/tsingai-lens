#!/usr/bin/env node
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import playwright from '../frontend/node_modules/playwright/index.js';

const { chromium } = playwright;

const collectionId = process.argv[2];
if (!collectionId) {
	console.error('usage: node scripts/check_semantic_graph_screenshots.mjs <collection_id> [base_url] [output_dir]');
	process.exit(2);
}

const baseUrl = process.argv[3] ?? 'http://localhost:5173';
const outputDir = resolve(process.argv[4] ?? '/tmp/lens-semantic-graph-screenshots');
const viewModes = [
	['objective_chain', 'objective-chain'],
	['material_centric', 'material-hub'],
	['full', 'full-graph']
];

mkdirSync(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const consoleErrors = [];
page.on('console', (message) => {
	if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', (error) => {
	consoleErrors.push(error.message);
});

try {
	const url = `${baseUrl.replace(/\/$/, '')}/collections/${encodeURIComponent(collectionId)}/graph`;
	await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
	await page.waitForSelector('.graph-cytoscape canvas', { timeout: 30000 });
	await page.waitForTimeout(1000);

	const results = [];
	for (const [mode, name] of viewModes) {
		await page.selectOption('#graph-view-mode', mode);
		await page.waitForTimeout(900);
		const title = await page.locator('#graph-canvas-title').innerText();
		const screenshotPath = resolve(outputDir, `${collectionId}-${name}.png`);
		await page.screenshot({ path: screenshotPath, fullPage: true });
		results.push({ mode, title, screenshot: screenshotPath });
	}

	if (consoleErrors.length) {
		console.error(JSON.stringify({ ok: false, consoleErrors, results }, null, 2));
		process.exit(1);
	}

	console.log(JSON.stringify({ ok: true, results }, null, 2));
} finally {
	await browser.close();
}
