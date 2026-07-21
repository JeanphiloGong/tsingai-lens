import { describe, expect, it, vi } from 'vitest';
import viteConfig from '../vite.config';

describe('vite dev proxy config', () => {
	it('defaults the local dev proxy to the standard backend port', () => {
		vi.unstubAllEnvs();

		const config = resolveConfig();
		const apiProxy = config.server?.proxy?.['/api'];

		expect(apiProxy).toMatchObject({
			target: 'http://localhost:8000',
			changeOrigin: true
		});
	});

	it('does not let PUBLIC_API_BASE_URL change the dev proxy target', () => {
		vi.unstubAllEnvs();
		vi.stubEnv('PUBLIC_API_BASE_URL', 'http://127.0.0.1:8010');

		const config = resolveConfig();
		const apiProxy = config.server?.proxy?.['/api'];

		expect(apiProxy).toMatchObject({
			target: 'http://localhost:8000',
			changeOrigin: true
		});
	});

	it('lets BACKEND_ORIGIN override the local backend target', () => {
		vi.stubEnv('BACKEND_ORIGIN', 'http://127.0.0.1:5245');
		vi.stubEnv('PUBLIC_API_BASE_URL', 'http://127.0.0.1:8010');

		const config = resolveConfig();
		const apiProxy = config.server?.proxy?.['/api'];

		expect(apiProxy).toMatchObject({
			target: 'http://127.0.0.1:5245',
			changeOrigin: true
		});
	});
});

function resolveConfig() {
	if (typeof viteConfig !== 'function') {
		throw new Error('expected vite config factory');
	}
	return viteConfig({ command: 'serve', mode: 'test' });
}
