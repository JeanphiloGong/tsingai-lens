import type { DatasetSampleDetail, SftMessage, SftText } from '../../../../../../_shared/feedbackDatasets';

export function initialAnnotationMessages(sample: DatasetSampleDetail): SftMessage[] {
	const raw = sample.source_case.context_snapshot.messages;
	const messages: SftMessage[] = Array.isArray(raw) ? raw.filter(item =>
		item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string' && item.content.trim()
	).map(item => ({ role: item.role, content: item.content })) : [];
	const last = messages.at(-1);
	return last?.role === 'user' && last.content === sample.source_case.question
		? messages : [{ role: 'user', content: sample.source_case.question }];
}

export function initialAnnotationEvidence(sample: DatasetSampleDetail): SftText[] {
	const records = [...sample.source_case.inspected_sources, ...sample.source_case.requested_scope];
	const seen = new Set<string>();
	return records.flatMap(record => {
		const document_title = record.document_title as string | null;
		const text = record.quote as string | null;
		const key = JSON.stringify([document_title, text]);
		if (!document_title || !text || seen.has(key)) return [];
		seen.add(key);
		return [{ document_title, text }];
	});
}
