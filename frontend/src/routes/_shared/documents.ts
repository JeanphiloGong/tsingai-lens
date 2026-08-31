import { buildApiUrl, requestJson } from './api';

export type DocumentType = 'experimental' | 'review' | 'mixed' | 'uncertain';

export type DocumentProfile = {
	document_id: string;
	collection_id: string;
	title: string | null;
	source_filename: string | null;
	doc_type: DocumentType;
	parsing_warnings: string[];
	confidence: number | null;
	page_count: number | null;
};

export type DocumentProfilesResponse = {
	collection_id: string;
	total: number;
	count: number;
	summary: {
		total_documents: number;
		doc_type_counts: Record<DocumentType, number>;
		warnings: string[];
	};
	items: DocumentProfile[];
};

export type DocumentContentBlock = {
	block_id: string;
	block_type: string | null;
	heading_path: string | null;
	heading_level: number;
	order: number;
	text: string;
	text_unit_ids: string[];
	page: number | null;
};

export type DocumentContentResponse = {
	collection_id: string;
	document_id: string;
	title: string | null;
	source_filename: string | null;
	content_text: string;
	blocks: DocumentContentBlock[];
	warnings: string[];
};

export type DocumentMarkdownSourceMapItem = {
	markdown_anchor: string;
	artifact_type: string;
	artifact_id: string;
	block_id: string | null;
	table_id: string | null;
	figure_id: string | null;
	block_type: string | null;
	page: number | null;
	heading_path: string | null;
	text_unit_ids: string[];
};

export type DocumentMarkdownResponse = {
	collection_id: string;
	document_id: string;
	title: string | null;
	source_filename: string | null;
	parser: string | null;
	markdown: string;
	source_map: DocumentMarkdownSourceMapItem[];
	warnings: string[];
};

export type SourceTargetPrecision = 'block' | 'page' | 'unavailable';
export type SourceAnchorPrecision = 'block' | 'page' | 'pending';

export type SourceAnchor = {
	pageIndex: number;
	quote?: string;
	section?: string;
	precision?: SourceAnchorPrecision;
};

export type WorkbenchSourceTarget = {
	documentId: string;
	label: string;
	page: number | null;
	sourceKind: string;
	sourceRef: string;
	headingPath: string | null;
	quote: string | null;
	precision: SourceTargetPrecision;
	userMessage: string | null;
	anchor: SourceAnchor;
};

export type WorkbenchSourceSpan = {
	id: string;
	block_id: string | null;
	anchor_id: string | null;
	page: number;
	section: string;
	quote: string;
	evidence_id: string | null;
	target: WorkbenchSourceTarget;
};

export type WorkbenchPdfParagraph = {
	id: string;
	section: string | null;
	text: string;
	source_span_id: string | null;
};

export type WorkbenchPdfPage = {
	page_number: number;
	label: string;
	paragraphs: WorkbenchPdfParagraph[];
	source_span_ids: string[];
};

export type DocumentWorkbenchModel = {
	collection_id: string;
	document_id: string;
	title: string;
	source_filename: string | null;
	sourceFileUrl: string;
	metadata: string[];
	pages: WorkbenchPdfPage[];
	source_spans: WorkbenchSourceSpan[];
	source_targets_by_span_id: Record<string, WorkbenchSourceTarget>;
	source_anchors_by_span_id: Record<string, SourceAnchor>;
};

const DOCUMENT_TYPES = new Set<DocumentType>(['experimental', 'review', 'mixed', 'uncertain']);

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function optionalText(value: unknown) {
	return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function stringList(value: unknown) {
	return Array.isArray(value)
		? value
				.map(String)
				.map((item) => item.trim())
				.filter(Boolean)
		: [];
}

function finiteNumber(value: unknown, fallback = 0) {
	const parsed = Number(value ?? fallback);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function nullableNumber(value: unknown) {
	if (value === null || value === undefined || value === '') return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function normalizeProfile(value: unknown, collectionId: string): DocumentProfile | null {
	const record = asRecord(value);
	const documentId = String(record?.document_id ?? '').trim();
	if (!record || !documentId) return null;
	const rawType = String(record.doc_type ?? 'uncertain') as DocumentType;
	return {
		document_id: documentId,
		collection_id: String(record.collection_id ?? collectionId),
		title: optionalText(record.title),
		source_filename: optionalText(record.source_filename),
		doc_type: DOCUMENT_TYPES.has(rawType) ? rawType : 'uncertain',
		parsing_warnings: stringList(record.parsing_warnings),
		confidence: nullableNumber(record.confidence),
		page_count: nullableNumber(record.page_count)
	};
}

function normalizeContentBlock(value: unknown): DocumentContentBlock | null {
	const record = asRecord(value);
	const blockId = String(record?.block_id ?? '').trim();
	if (!record || !blockId) return null;
	return {
		block_id: blockId,
		block_type: optionalText(record.block_type),
		heading_path: optionalText(record.heading_path),
		heading_level: finiteNumber(record.heading_level),
		order: finiteNumber(record.order),
		text: String(record.text ?? ''),
		text_unit_ids: stringList(record.text_unit_ids),
		page: nullableNumber(record.page)
	};
}

function normalizeDocumentContent(
	value: unknown,
	collectionId: string,
	documentId: string
): DocumentContentResponse {
	const record = asRecord(value);
	if (!record || String(record.document_id ?? '').trim() !== documentId) {
		throw new Error('Document content response is invalid.');
	}
	return {
		collection_id: String(record.collection_id ?? collectionId),
		document_id: documentId,
		title: optionalText(record.title),
		source_filename: optionalText(record.source_filename),
		content_text: String(record.content_text ?? ''),
		blocks: Array.isArray(record.blocks)
			? record.blocks
					.map(normalizeContentBlock)
					.filter((block): block is DocumentContentBlock => block !== null)
			: [],
		warnings: stringList(record.warnings)
	};
}

function normalizeSourceMapItem(value: unknown): DocumentMarkdownSourceMapItem | null {
	const record = asRecord(value);
	const markdownAnchor = String(record?.markdown_anchor ?? '').trim();
	const artifactId = String(record?.artifact_id ?? '').trim();
	if (!record || !markdownAnchor || !artifactId) return null;
	return {
		markdown_anchor: markdownAnchor,
		artifact_type: String(record.artifact_type ?? ''),
		artifact_id: artifactId,
		block_id: optionalText(record.block_id),
		table_id: optionalText(record.table_id),
		figure_id: optionalText(record.figure_id),
		block_type: optionalText(record.block_type),
		page: nullableNumber(record.page),
		heading_path: optionalText(record.heading_path),
		text_unit_ids: stringList(record.text_unit_ids)
	};
}

export function normalizeDocumentMarkdown(
	value: unknown,
	collectionId: string,
	documentId: string
): DocumentMarkdownResponse {
	const record = asRecord(value);
	if (!record || String(record.document_id ?? '').trim() !== documentId) {
		throw new Error('Document Markdown response is invalid.');
	}
	return {
		collection_id: String(record.collection_id ?? collectionId),
		document_id: documentId,
		title: optionalText(record.title),
		source_filename: optionalText(record.source_filename),
		parser: optionalText(record.parser),
		markdown: String(record.markdown ?? '').trim(),
		source_map: Array.isArray(record.source_map)
			? record.source_map
					.map(normalizeSourceMapItem)
					.filter((item): item is DocumentMarkdownSourceMapItem => item !== null)
			: [],
		warnings: stringList(record.warnings)
	};
}

function sourceSpan(documentId: string, block: DocumentContentBlock): WorkbenchSourceSpan {
	const page = block.page && block.page > 0 ? Math.trunc(block.page) : 1;
	const section = block.heading_path || block.block_type || 'Document text';
	const id = `source:${block.block_id}`;
	const anchor: SourceAnchor = {
		pageIndex: page - 1,
		quote: block.text || undefined,
		section,
		precision: 'block'
	};
	return {
		id,
		block_id: block.block_id,
		anchor_id: null,
		page,
		section,
		quote: block.text,
		evidence_id: null,
		target: {
			documentId,
			label: section,
			page,
			sourceKind: 'block',
			sourceRef: block.block_id,
			headingPath: block.heading_path,
			quote: block.text || null,
			precision: 'block',
			userMessage: null,
			anchor
		}
	};
}

export function buildDocumentWorkbenchModel({
	collectionId,
	documentId,
	content
}: {
	collectionId: string;
	documentId: string;
	content: DocumentContentResponse | null;
}): DocumentWorkbenchModel {
	const blocks = [...(content?.blocks ?? [])].sort((left, right) => left.order - right.order);
	const sourceSpans = blocks.map((block) => sourceSpan(content?.document_id || documentId, block));
	const spanByBlockId = new Map(sourceSpans.map((span) => [span.block_id, span]));
	const pageNumbers = new Set(sourceSpans.map((span) => span.page));
	if (!pageNumbers.size) pageNumbers.add(1);
	const pages = Array.from(pageNumbers)
		.sort((left, right) => left - right)
		.map((pageNumber): WorkbenchPdfPage => {
			const pageBlocks = blocks.filter(
				(block) => (block.page && block.page > 0 ? block.page : 1) === pageNumber
			);
			return {
				page_number: pageNumber,
				label: `Page ${pageNumber}`,
				paragraphs: pageBlocks.map((block) => ({
					id: block.block_id,
					section: block.heading_path,
					text: block.text,
					source_span_id: spanByBlockId.get(block.block_id)?.id ?? null
				})),
				source_span_ids: pageBlocks
					.map((block) => spanByBlockId.get(block.block_id)?.id)
					.filter((id): id is string => Boolean(id))
			};
		});
	return {
		collection_id: collectionId,
		document_id: content?.document_id || documentId,
		title: content?.title || content?.source_filename || documentId,
		source_filename: content?.source_filename || null,
		sourceFileUrl: buildApiUrl(
			`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(content?.document_id || documentId)}/source`
		),
		metadata: [],
		pages,
		source_spans: sourceSpans,
		source_targets_by_span_id: Object.fromEntries(
			sourceSpans.map((span) => [span.id, span.target])
		),
		source_anchors_by_span_id: Object.fromEntries(
			sourceSpans.map((span) => [span.id, span.target.anchor])
		)
	};
}

export type DocumentProfileListOptions = {
	offset?: number;
	limit?: number;
	query?: string;
	docType?: DocumentType;
	hasWarnings?: boolean;
};

export async function fetchDocumentProfiles(
	collectionId: string,
	options: DocumentProfileListOptions = {}
): Promise<DocumentProfilesResponse> {
	const search = new URLSearchParams();
	if (options.offset !== undefined) search.set('offset', String(options.offset));
	if (options.limit !== undefined) search.set('limit', String(options.limit));
	const query = options.query?.trim();
	if (query) search.set('query', query);
	if (options.docType) search.set('doc_type', options.docType);
	if (options.hasWarnings !== undefined) {
		search.set('has_warnings', String(options.hasWarnings));
	}
	const queryString = search.toString();
	const data = (await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/profiles${queryString ? `?${queryString}` : ''}`,
		{ method: 'GET' }
	)) as Record<string, unknown>;
	const items = Array.isArray(data.items)
		? data.items
				.map((item) => normalizeProfile(item, collectionId))
				.filter((item): item is DocumentProfile => item !== null)
		: [];
	const summary = asRecord(data.summary);
	const counts = asRecord(summary?.by_doc_type);
	return {
		collection_id: String(data.collection_id ?? collectionId),
		total: finiteNumber(data.total, items.length),
		count: finiteNumber(data.count, items.length),
		summary: {
			total_documents: finiteNumber(summary?.total_documents, items.length),
			doc_type_counts: {
				experimental: finiteNumber(counts?.experimental),
				review: finiteNumber(counts?.review),
				mixed: finiteNumber(counts?.mixed),
				uncertain: finiteNumber(counts?.uncertain)
			},
			warnings: stringList(summary?.warnings)
		},
		items
	};
}

export async function fetchDocumentContent(
	collectionId: string,
	documentId: string
): Promise<DocumentContentResponse> {
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/content`,
		{ method: 'GET' }
	);
	return normalizeDocumentContent(data, collectionId, documentId);
}

export async function fetchDocumentMarkdown(
	collectionId: string,
	documentId: string
): Promise<DocumentMarkdownResponse> {
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/markdown`,
		{ method: 'GET' }
	);
	return normalizeDocumentMarkdown(data, collectionId, documentId);
}

export async function fetchDocumentProfile(
	collectionId: string,
	documentId: string
): Promise<DocumentProfile> {
	const data = await requestJson(
		`/collections/${encodeURIComponent(collectionId)}/documents/${encodeURIComponent(documentId)}/profile`,
		{ method: 'GET' }
	);
	const profile = normalizeProfile(data, collectionId);
	if (!profile) throw new Error('Document profile response is invalid.');
	return profile;
}
