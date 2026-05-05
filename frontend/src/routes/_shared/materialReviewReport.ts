import { buildApiUrl, requestJson } from './api';
import type { Language } from './i18n';

export type MaterialReviewReportStatus =
	| 'generating'
	| 'ready'
	| 'ready_with_warnings'
	| 'failed';

export type MaterialReviewReadiness = 'strong' | 'usable' | 'preliminary' | 'insufficient';

export type MaterialReviewReport = {
	report_id: string;
	collection_id: string;
	material_id: string;
	status: MaterialReviewReportStatus;
	message: string;
	title: string | null;
	language: string;
	report_type: string;
	include_appendix: boolean;
	readiness: MaterialReviewReadiness;
	readiness_reason: string;
	data_version: string;
	warnings: string[];
	created_at: string;
	updated_at: string;
	generated_at: string | null;
	pdf_url: string | null;
	markdown_url: string | null;
};

type CreateMaterialReviewReportOptions = {
	language?: Language;
	report_type?: 'review_draft';
	include_appendix?: boolean;
	force_regenerate?: boolean;
};

function materialReviewReportPath(collectionId: string, materialId: string, suffix = '') {
	return `/collections/${encodeURIComponent(collectionId)}/materials/${encodeURIComponent(
		materialId
	)}/review-report${suffix}`;
}

export async function fetchMaterialReviewReport(collectionId: string, materialId: string) {
	return (await requestJson(materialReviewReportPath(collectionId, materialId), {
		method: 'GET'
	})) as MaterialReviewReport;
}

export async function createMaterialReviewReport(
	collectionId: string,
	materialId: string,
	options: CreateMaterialReviewReportOptions = {}
) {
	return (await requestJson(materialReviewReportPath(collectionId, materialId), {
		method: 'POST',
		body: JSON.stringify({
			language: options.language ?? 'zh',
			report_type: options.report_type ?? 'review_draft',
			include_appendix: options.include_appendix ?? true,
			force_regenerate: options.force_regenerate ?? false
		})
	})) as MaterialReviewReport;
}

export function buildMaterialReviewMarkdownUrl(collectionId: string, materialId: string) {
	return buildApiUrl(materialReviewReportPath(collectionId, materialId, '.md'));
}

export function buildMaterialReviewPdfUrl(collectionId: string, materialId: string) {
	return buildApiUrl(materialReviewReportPath(collectionId, materialId, '.pdf'));
}
