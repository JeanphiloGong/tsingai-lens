import { defineConfig } from '@playwright/test';
export default defineConfig({
	testDir: 'e2e',
	testMatch: 'model-administration-live.spec.ts',
	use: { baseURL: process.env.MODEL_ADMIN_LIVE_ORIGIN || 'http://127.0.0.1:14173' }
});
