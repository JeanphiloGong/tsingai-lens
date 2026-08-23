import { describe, expect, it } from 'vitest';
import svelteConfig from '../svelte.config.js';

describe('SvelteKit content security policy', () => {
	it('blocks untrusted scripts while allowing hashed application startup code', () => {
		expect(svelteConfig.kit?.csp).toEqual({
			mode: 'hash',
			directives: {
				'script-src': ['self']
			}
		});
	});
});
