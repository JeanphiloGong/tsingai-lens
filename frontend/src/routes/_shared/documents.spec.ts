import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({ requestJson: vi.fn() }));

vi.mock('./api', async (importActual) => ({
	...(await importActual<typeof import('./api')>()),
	requestJson
}));

const { buildDocumentWorkbenchModel, fetchDocumentMarkdown, fetchDocumentProfiles } = await import(
	'./documents'
);

describe('documents shared helpers', () => {
	beforeEach(() => requestJson.mockReset());

	it('normalizes the maintained document profile contract', async () => {
		requestJson.mockResolvedValue({
			collection_id: 'col_123',
			total: 1,
			count: 1,
			summary: {
				total_documents: 1,
				by_doc_type: { experimental: 1 },
				warnings: []
			},
			items: [
				{
					document_id: 'doc_1',
					collection_id: 'col_123',
					title: 'Paper A',
					source_filename: 'paper-a.pdf',
					doc_type: 'experimental',
					parsing_warnings: [],
					confidence: 0.9
				}
			]
		});

		const response = await fetchDocumentProfiles('col_123');

		expect(response.summary.doc_type_counts.experimental).toBe(1);
		expect(response.items[0]).toMatchObject({
			document_id: 'doc_1',
			doc_type: 'experimental',
			confidence: 0.9
		});
	});

	it('normalizes Markdown source mappings and rejects entries without stable anchors', async () => {
		requestJson.mockResolvedValue({
			collection_id: 'col_123',
			document_id: 'doc_1',
			title: 'Paper A',
			source_filename: 'paper-a.pdf',
			parser: 'docling',
			markdown: '  # Paper A\n\nText.  ',
			source_map: [
				{
					markdown_anchor: 'block-abstract',
					artifact_type: 'block',
					artifact_id: 'abstract',
					block_id: 'abstract',
					page: 1,
					heading_path: 'Abstract',
					text_unit_ids: ['tu-1']
				},
				{ markdown_anchor: '', artifact_type: 'block', artifact_id: 'invalid' }
			],
			warnings: ['layout_warning']
		});

		const response = await fetchDocumentMarkdown('col_123', 'doc_1');

		expect(response.markdown).toBe('# Paper A\n\nText.');
		expect(response.source_map).toHaveLength(1);
		expect(response.source_map[0]).toMatchObject({
			artifact_id: 'abstract',
			block_id: 'abstract',
			page: 1,
			heading_path: 'Abstract'
		});
	});

	it('builds source navigation only from parsed Source blocks', () => {
		const model = buildDocumentWorkbenchModel({
			collectionId: 'col_123',
			documentId: 'doc_1',
			content: {
				collection_id: 'col_123',
				document_id: 'doc_1',
				title: 'Paper A',
				source_filename: 'paper-a.pdf',
				content_text: 'Methods text. Results text.',
				warnings: [],
				blocks: [
					{
						block_id: 'methods-1',
						block_type: 'paragraph',
						heading_path: 'Methods',
						heading_level: 2,
						order: 1,
						text: 'Methods text.',
						text_unit_ids: ['tu-1'],
						page: 2
					},
					{
						block_id: 'results-1',
						block_type: 'paragraph',
						heading_path: 'Results',
						heading_level: 2,
						order: 2,
						text: 'Results text.',
						text_unit_ids: ['tu-2'],
						page: 3
					}
				]
			}
		});

		expect(model.source_spans.map((span) => span.block_id)).toEqual([
			'methods-1',
			'results-1'
		]);
		expect(model.pages.map((page) => page.page_number)).toEqual([2, 3]);
		expect(model.source_anchors_by_span_id['source:results-1']).toMatchObject({
			pageIndex: 2,
			section: 'Results',
			precision: 'block'
		});
		expect(model).not.toHaveProperty('result_rows');
		expect(model).not.toHaveProperty('evidence_cards');
	});
});
