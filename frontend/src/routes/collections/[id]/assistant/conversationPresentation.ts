import type { ChatMessage, ChatProgress } from '../../../_shared/chatSessions';

export type ChatSessionActivity = 'running' | 'approval' | 'recovering' | 'idle' | 'unavailable';

export function getChatSessionActivity(
	messages: ChatMessage[],
	running: boolean,
	pendingApprovalId: string | null
): ChatSessionActivity {
	if (pendingApprovalId) return 'approval';
	if (running) return 'running';
	const completed = new Set(messages.map((message) => message.tool_result?.tool_call_id));
	return messages.some((message) =>
		message.tool_calls.some((call) => !completed.has(call.tool_call_id))
	)
		? 'recovering'
		: 'idle';
}

export function getRecoveredChatProgress(messages: ChatMessage[], now: number): ChatProgress {
	const questionIndex = messages.map((message) => message.role).lastIndexOf('user');
	const currentTurn = questionIndex < 0 ? [] : messages.slice(questionIndex);
	const calls = currentTurn.flatMap((message) => message.tool_calls);
	const completed = new Set(currentTurn.map((message) => message.tool_result?.tool_call_id));
	const started = Date.parse(currentTurn[0]?.created_at ?? '');
	return {
		phase: 'recovering',
		requested_tool_count: calls.length,
		executed_tool_count: calls.filter((call) => completed.has(call.tool_call_id)).length,
		...(Number.isFinite(started) ? { elapsed_ms: Math.max(0, now - started) } : {})
	};
}

export type CurrentReading = {
	toolCallId: string;
	kind: 'passage' | 'table' | 'search' | 'outline';
	status: 'reading' | 'received' | 'failed';
	title: string;
	page: string;
	heading: string;
	excerpt: string;
	query: string;
};

export function getCurrentReadings(messages: ChatMessage[]): CurrentReading[] {
	const questionIndex = messages.map((message) => message.role).lastIndexOf('user');
	if (questionIndex < 0) return [];
	const kinds = {
		read_source: 'passage',
		inspect_table: 'table',
		search_sources: 'search',
		inspect_document_sources: 'outline'
	} as const;
	const operations = operationsFrom(messages.slice(questionIndex)).filter(
		(operation) => operation.toolName && operation.toolName in kinds
	);
	const pending = operations.filter((operation) => !operation.resultMessage);
	const current = pending.length ? pending : operations.slice(-1);
	const records: Record<string, unknown>[] = [];
	for (const message of messages) {
		for (const source of message.source_contexts) records.push(source);
		const data = message.tool_result?.data;
		if (!data || message.tool_result?.status !== 'succeeded') continue;
		const document =
			data.document && typeof data.document === 'object'
				? (data.document as Record<string, unknown>)
				: {};
		records.push({ ...document, ...data });
		for (const key of ['sources', 'matches', 'papers', 'evidence']) {
			if (!Array.isArray(data[key])) continue;
			for (const item of data[key]) {
				if (item && typeof item === 'object') records.push({ ...document, ...item });
			}
		}
	}
	return current.map((operation) => {
		const request =
			operation.requestMessage?.tool_calls.find(
				(call) => call.tool_call_id === operation.toolCallId
			)?.arguments ?? {};
		const result = operation.resultMessage?.tool_result;
		const data = result?.status === 'succeeded' ? result.data : {};
		const documentId =
			request.document_id ??
			(Array.isArray(request.document_ids) && request.document_ids.length === 1
				? request.document_ids[0]
				: null);
		const sourceRef = request.source_ref ?? request.table_ref;
		const paperRecords = documentId
			? records.filter((item) => item.document_id === documentId)
			: [];
		const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '');
		const sectionSources = Array.isArray(data.sources)
			? data.sources.filter(
					(item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object'
				)
			: [];
		const sectionSource =
			sectionSources.find(
				(item) => text(item.content) && text(item.content) !== text(item.heading_path)
			) ?? sectionSources[0];
		const source = sourceRef
			? (Object.assign(
					{},
					...paperRecords.filter((item) => (item.source_ref ?? item.table_ref) === sourceRef)
				) as Record<string, unknown>)
			: sectionSource;
		const title =
			(paperRecords
				.map((item) => text(item.filename) || text(item.original_filename))
				.find(Boolean) ||
				paperRecords
					.map(
						(item) => text(item.document_title) || text(item.title) || text(item.original_filename)
					)
					.find(Boolean)) ??
			'';
		const page = data.page ?? source?.page ?? request.page;
		return {
			toolCallId: operation.toolCallId,
			kind: kinds[operation.toolName as keyof typeof kinds],
			status: !result ? 'reading' : result.status === 'failed' ? 'failed' : 'received',
			title,
			page: typeof page === 'number' || typeof page === 'string' ? String(page) : '',
			heading: text(data.heading_path ?? source?.heading_path ?? request.heading_path),
			excerpt:
				result?.status === 'failed'
					? ''
					: text(
							data.content ??
								data.table_markdown ??
								source?.content ??
								source?.source_excerpt ??
								source?.excerpt
						).slice(0, 420),
			query: text(request.query)
		};
	});
}

const reviewableResultTools = new Set([
	'create_evidence_draft',
	'create_evidence_version',
	'create_finding_draft',
	'create_finding_version',
	'create_objective_candidate',
	'confirm_objective',
	'create_research_plan',
	'derive_objective',
	'assess_objective_quality',
	'inspect_table',
	'inspect_objective_analysis',
	'inspect_published_finding',
	'inspect_research_process',
	'preview_research_scope',
	'propose_objective_drafts',
	'propose_research_plan',
	'publish_agent_objective_analysis',
	'read_source',
	'search_sources',
	'start_objective_analysis',
	'start_research_process'
]);

export type ToolActivityOperation = {
	toolCallId: string;
	toolName: string | null;
	requestMessage: ChatMessage | null;
	resultMessage: ChatMessage | null;
};

export type ChatPresentationItem =
	| {
			kind: 'message';
			id: string;
			message: ChatMessage;
	  }
	| {
			kind: 'activity';
			id: string;
			operations: ToolActivityOperation[];
			artifacts: ToolActivityOperation[];
			status: 'completed' | 'in_progress' | 'pending' | 'failed';
	  };

function isToolActivity(message: ChatMessage) {
	return Boolean(message.tool_calls.length || message.tool_result);
}

function operationsFrom(messages: ChatMessage[]) {
	const operations: ToolActivityOperation[] = [];

	for (const message of messages) {
		for (const request of message.tool_calls) {
			operations.push({
				toolCallId: request.tool_call_id,
				toolName: request.name,
				requestMessage: message,
				resultMessage: null
			});
		}
		const toolCallId = message.tool_result?.tool_call_id ?? message.tool_call_id;
		if (!toolCallId) continue;
		let operation = operations.find((candidate) => candidate.toolCallId === toolCallId);
		if (!operation) {
			operation = {
				toolCallId,
				toolName: null,
				requestMessage: null,
				resultMessage: null
			};
			operations.push(operation);
		}
		if (message.tool_result) operation.resultMessage = message;
	}

	return operations;
}

function activityStatus(operations: ToolActivityOperation[]) {
	if (operations.some((operation) => operation.resultMessage?.tool_result?.status === 'failed')) {
		return 'failed' as const;
	}
	if (operations.some((operation) => operation.resultMessage?.tool_result?.status === 'queued')) {
		return 'in_progress' as const;
	}
	if (operations.some((operation) => operation.resultMessage === null)) {
		return operations.some((operation) => operation.resultMessage !== null)
			? 'in_progress'
			: 'pending';
	}
	return 'completed' as const;
}

export function buildChatPresentation(
	messages: ChatMessage[],
	pendingApprovalToolCallId: string | null = null
): ChatPresentationItem[] {
	const items: ChatPresentationItem[] = [];
	let activityMessages: ChatMessage[] = [];

	const flushActivity = () => {
		if (!activityMessages.length) return;
		const operations = operationsFrom(activityMessages).filter(
			(operation) => operation.toolCallId !== pendingApprovalToolCallId
		);
		if (!operations.length) {
			activityMessages = [];
			return;
		}
		const artifacts = operations.filter(
			(operation) =>
				operation.resultMessage !== null &&
				operation.toolName !== null &&
				reviewableResultTools.has(operation.toolName)
		);
		items.push({
			kind: 'activity',
			id: `activity-${activityMessages[0].message_id}`,
			operations,
			artifacts,
			status: activityStatus(operations.filter((operation) => !artifacts.includes(operation)))
		});
		activityMessages = [];
	};

	for (const message of messages) {
		if (isToolActivity(message)) {
			if (message.role === 'assistant' && message.content.trim()) {
				flushActivity();
				items.push({ kind: 'message', id: `message-${message.message_id}`, message });
			}
			activityMessages.push(message);
			continue;
		}

		flushActivity();
		items.push({ kind: 'message', id: `message-${message.message_id}`, message });
	}

	flushActivity();
	return items;
}

export function formatTime(value: string) {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return '';
	return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date);
}
