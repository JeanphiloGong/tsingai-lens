import { describe, expect, it } from 'vitest';
import {
	buildEvidenceQualitySummary,
	filterEvidenceItems,
	formatConfidence,
	getComparabilityStatus,
	getEvidenceActions,
	getEvidenceQuote,
	getEvidenceSourceLocation,
	getEvidenceTypeBadge,
	getTraceabilityBadge,
	sortEvidenceItems,
	type EvidenceCard,
	type EvidenceFilters
} from './evidence';

function card(overrides: Partial<EvidenceCard>): EvidenceCard {
	return {
		evidence_id: 'ev_1',
		document_id: 'doc_1',
		collection_id: 'col_1',
		claim_text: 'Auxiliary magnetic field reduced porosity in metallic AM.',
		claim_type: 'process',
		evidence_source_type: 'text',
		evidence_anchors: [
			{
				anchor_id: 'a1',
				document_id: 'doc_1',
				locator_type: 'section',
				locator_confidence: 'medium',
				source_type: 'text',
				section_id: '3.2',
				char_range: null,
				bbox: null,
				page: 8,
				quote: 'Auxiliary MF has shown feasibility to reduce porosity.',
				deep_link: '/collections/col_1/documents/doc_1?evidence_id=ev_1&anchor_id=a1',
				block_id: null,
				snippet_id: null,
				figure_or_table: null,
				quote_span: 'Auxiliary MF has shown feasibility to reduce porosity.',
				anchor_type: 'text',
				label: 'Section 3.2'
			}
		],
		material_system: 'Al alloy',
		condition_context: {
			process: ['Auxiliary MF'],
			baseline: ['No magnetic field'],
			test: ['Porosity measurement']
		},
		confidence: 0.9,
		traceability_status: 'direct',
		source_document_title: 'AI alloys',
		materials: [],
		parameters: ['porosity', 'AM'],
		tags: ['porosity'],
		comparable: true,
		comparison_status: null,
		review_status: null,
		extracted_at: '2026-04-25T04:00:00.000Z',
		updated_at: '2026-04-25T04:10:00.000Z',
		...overrides
	};
}

const emptyFilters: EvidenceFilters = {
	search: '',
	type: '',
	traceability: '',
	source: '',
	confidence: '',
	comparability: ''
};

describe('evidence shared helpers', () => {
	it('builds review quality summary from traceability, confidence, and comparability', () => {
		const items = [
			card({ evidence_id: 'joinable' }),
			card({
				evidence_id: 'needs_context',
				traceability_status: 'partial',
				confidence: 0.72,
				comparison_status: 'needs_context'
			}),
			card({
				evidence_id: 'unusable',
				traceability_status: 'missing',
				confidence: 0.42,
				evidence_anchors: []
			})
		];

		expect(items.map(getComparabilityStatus)).toEqual([
			'joinable',
			'needs_context',
			'not_recommended'
		]);
		expect(buildEvidenceQualitySummary(items)).toMatchObject([
			{ key: 'total', value: 3, percent: null },
			{ key: 'traceable', value: 2, percent: 67 },
			{ key: 'needs_review', value: 2, percent: 67 },
			{ key: 'comparable', value: 1, percent: 33 },
			{ key: 'unusable', value: 1, percent: 33 }
		]);
	});

	it('filters evidence by search text, traceability, confidence, and comparison status', () => {
		const items = [
			card({ evidence_id: 'ev_process', claim_type: 'process', confidence: 0.91 }),
			card({
				evidence_id: 'ev_table',
				claim_type: 'result',
				evidence_source_type: 'table',
				traceability_status: 'partial',
				confidence: 0.7,
				comparison_status: 'needs_context',
				claim_text: 'UTS reached 420 MPa.'
			})
		];

		expect(
			filterEvidenceItems(items, {
				...emptyFilters,
				search: '420',
				source: 'table',
				confidence: 'medium',
				comparability: 'needs_context'
			}).map((item) => item.evidence_id)
		).toEqual(['ev_table']);
		expect(
			filterEvidenceItems(items, { ...emptyFilters, type: 'process', traceability: 'direct' }).map(
				(item) => item.evidence_id
			)
		).toEqual(['ev_process']);
	});

	it('formats badge, quote, location, action, and sort metadata for the review page', () => {
		const direct = card({ evidence_id: 'direct', confidence: 0.9 });
		const low = card({
			evidence_id: 'low',
			confidence: 0.4,
			traceability_status: 'missing',
			updated_at: '2026-04-25T04:01:00.000Z'
		});

		expect(getEvidenceTypeBadge('process')).toMatchObject({ label: 'Process', tone: 'brand' });
		expect(getTraceabilityBadge('partial')).toMatchObject({
			labelKey: 'evidence.traceability.indirect',
			tone: 'warning'
		});
		expect(formatConfidence(0.9)).toBe('90%');
		expect(getEvidenceQuote(direct)).toMatchObject({
			text: 'Auxiliary MF has shown feasibility to reduce porosity.',
			citation: 'AI alloys, Page 8, Section 3.2'
		});
		expect(getEvidenceSourceLocation(direct)).toMatchObject({
			documentLabel: 'AI alloys',
			location: 'Page 8, Section 3.2',
			materials: ['Al alloy']
		});
		expect(getEvidenceActions(low).map((action) => action.key)).toEqual([
			'view_source',
			'view_reason',
			'mark_issue'
		]);
		expect(
			sortEvidenceItems([low, direct], 'confidence_desc').map((item) => item.evidence_id)
		).toEqual(['direct', 'low']);
	});
});
