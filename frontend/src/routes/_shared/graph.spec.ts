import { describe, expect, it } from 'vitest';
import { buildCollectionGraphmlUrl, parseGraphNodeId } from './graph';

describe('graph shared helpers', () => {
	it('builds graphml urls with only lean graph query parameters', () => {
		const url = buildCollectionGraphmlUrl('col_123', { maxNodes: 50, minWeight: 0.75 });

		expect(url).toContain('/api/v1/collections/col_123/graphml?');
		expect(url).toContain('max_nodes=50');
		expect(url).toContain('min_weight=0.75');
		expect(url).not.toContain('community_id');
	});

	it('parses canonical node prefixes into resource references', () => {
		expect(parseGraphNodeId('doc:paper-1')).toEqual({
			kind: 'document',
			resourceId: 'paper-1'
		});
		expect(parseGraphNodeId('evi:ev-1')).toEqual({
			kind: 'evidence',
			resourceId: 'ev-1'
		});
		expect(parseGraphNodeId('cmp:row-1')).toEqual({
			kind: 'comparison',
			resourceId: 'row-1'
		});
		expect(parseGraphNodeId('weird')).toEqual({
			kind: 'unknown',
			resourceId: ''
		});
	});
});
