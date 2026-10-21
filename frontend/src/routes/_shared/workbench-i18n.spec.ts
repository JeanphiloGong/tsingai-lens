import { describe, expect, it } from 'vitest';
import { translateKey } from './i18n';

const sources = import.meta.glob('../collections/[[]id]/feedback/**/*.svelte', {query:'?raw',import:'default',eager:true});
const objectives = import.meta.glob('../collections/[[]id]/objectives/+page.svelte', {query:'?raw',import:'default',eager:true});
describe('workbench translation coverage', () => {
 it('resolves static keys in both languages without changing source or input data', () => {
  const entries = Object.entries({...sources,...objectives});
  expect(entries.length).toBeGreaterThan(4);
  for(const [,source] of entries) {
   expect(String(source)).not.toMatch(/[\u3400-\u9fff]/);
   for(const match of String(source).matchAll(/(?:\$t|translate)\('([^']+)'/g)) {
    for(const lang of ['en','zh'] as const) expect(translateKey(lang,match[1])).not.toBe(match[1]);
    expect(translateKey('en',match[1])).not.toMatch(/[\u3400-\u9fff]/);
   }
  }
 });
});
