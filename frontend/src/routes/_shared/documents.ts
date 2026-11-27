import { buildApiUrl, requestJson } from './api';

export type DocumentType = 'experimental' | 'review' | 'mixed' | 'uncertain';

export type DocumentProfile = {
	document_id: string;
	doc_type: DocumentType;
	description: string;
	source_fingerprint: string;
	profile_fingerprint: string;
	profile_version: string;
	generated_at: string;
};

export type DocumentProfilesResponse = {
	workspace_id: string;
	total: number;
	count: number;
	summary: {
		total_documents: number;
		by_doc_type: Partial<Record<DocumentType, number>>;
		technical_failure_count: number;
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
	workspace_id: string;
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
	workspace_id: string;
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

export type DocumentSourceSelection = {
	source_kind: string;
	source_ref: string;
	page: number | null;
	quote: string;
	heading_path: string | null;
};

export type DocumentWorkbenchModel = {
	workspace_id: string;
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
	workspaceId,
	documentId,
	content
}: {
	workspaceId: string;
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
		workspace_id: workspaceId,
		document_id: content?.document_id || documentId,
		title: content?.title || content?.source_filename || documentId,
		source_filename: content?.source_filename || null,
		sourceFileUrl: buildApiUrl(
			`/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(content?.document_id || documentId)}/source`
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
};

export async function fetchDocumentProfiles(
	workspaceId: string,
	options: DocumentProfileListOptions = {}
): Promise<DocumentProfilesResponse> {
	const search = new URLSearchParams();
	if (options.offset !== undefined) search.set('offset', String(options.offset));
	if (options.limit !== undefined) search.set('limit', String(options.limit));
	const query = options.query?.trim();
	if (query) search.set('query', query);
	if (options.docType) search.set('doc_type', options.docType);
	const queryString = search.toString();
	const data = (await requestJson(
		`/workspaces/${encodeURIComponent(workspaceId)}/documents/profiles${queryString ? `?${queryString}` : ''}`,
		{ method: 'GET' }
	)) as DocumentProfilesResponse;
	if (data.workspace_id !== workspaceId) {
		throw new Error('Document profiles response does not match workspace_id.');
	}
	return data;
}

export async function fetchDocumentContent(
	workspaceId: string,
	documentId: string
): Promise<DocumentContentResponse> {
	const data = (await requestJson(
		`/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}/content`,
		{ method: 'GET' }
	)) as DocumentContentResponse;
	if (data.workspace_id !== workspaceId || data.document_id !== documentId) {
		throw new Error('Document content response does not match the requested document.');
	}
	return data;
}

export async function fetchDocumentMarkdown(
	workspaceId: string,
	documentId: string
): Promise<DocumentMarkdownResponse> {
	const data = (await requestJson(
		`/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}/markdown`,
		{ method: 'GET' }
	)) as DocumentMarkdownResponse;
	if (data.workspace_id !== workspaceId || data.document_id !== documentId) {
		throw new Error('Document Markdown response does not match the requested document.');
	}
	return data;
}

export async function fetchDocumentProfile(
	workspaceId: string,
	documentId: string
): Promise<DocumentProfile> {
	const data = (await requestJson(
		`/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}/profile`,
		{ method: 'GET' }
	)) as DocumentProfile;
	if (data.document_id !== documentId) {
		throw new Error('Document profile response does not match the requested document.');
	}
	return data;
}
