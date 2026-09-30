import type { DatasetSampleDetail, SftText } from '../../../../../../_shared/feedbackDatasets';

export function initialAnnotationEvidence(sample: DatasetSampleDetail): SftText[] {
	const records = [...sample.source_case.inspected_sources, ...sample.source_case.requested_scope];
	const seen = new Set<string>();
	return records.flatMap(record => {
		const document_title = String(record.document_title ?? record.title ?? '').trim();
		const text = String(record.quote ?? record.text ?? record.content ?? '').trim();
		const key = JSON.stringify([document_title, text]);
		if (!document_title || !text || seen.has(key)) return [];
		seen.add(key);
		return [{ document_title, text }];
	});
}
