import type { ChatMessage } from '$lib/conversation/api';

export type ChatResourceRef = {
	resource_type: string;
	resource_id: string;
	href: string | null;
};

export type ChatSourceContext = {
	resource_ref: ChatResourceRef;
	workspace_id: string;
	document_id: string;
	document_title: string;
	source_kind: string;
	source_ref: string;
	page: number | null;
	quote: string;
	heading_path: string | null;
	quote_truncated: boolean;
	source_digest?: string | null;
};

function sourceContextStorageKey(userId: string, workspaceId: string) {
	return `lens.chatSourceContext.${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}`;
}

export const MAX_CHAT_SOURCE_CONTEXTS = 12;

export function storePendingChatSourceContexts(
	userId: string,
	workspaceId: string,
	contexts: ChatSourceContext[],
	submission?: { session_id: string; content: string; after_message_id: string | null }
) {
	if (typeof window === 'undefined') return;
	if (!contexts.length) {
		clearPendingChatSourceContexts(userId, workspaceId);
		return;
	}
	window.sessionStorage.setItem(
		sourceContextStorageKey(userId, workspaceId),
		JSON.stringify({ contexts, submission })
	);
}

export function readPendingChatSourceContexts(
	userId: string,
	workspaceId: string,
	persisted?: { sessionId: string; messages: ChatMessage[] }
): ChatSourceContext[] {
	if (typeof window === 'undefined') return [];
	try {
		const raw = window.sessionStorage.getItem(sourceContextStorageKey(userId, workspaceId));
		const value = raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
		const contexts = value?.contexts as ChatSourceContext[] | undefined;
		if (
			!Array.isArray(contexts) ||
			contexts.length > MAX_CHAT_SOURCE_CONTEXTS ||
			contexts.some(
				(item) =>
					!item ||
					item.workspace_id !== workspaceId ||
					item.resource_ref?.resource_type !== 'source' ||
					typeof item.resource_ref.resource_id !== 'string' ||
					typeof item.document_id !== 'string' ||
					typeof item.document_title !== 'string' ||
					typeof item.source_kind !== 'string' ||
					typeof item.source_ref !== 'string' ||
					typeof item.quote !== 'string'
			)
		) {
			clearPendingChatSourceContexts(userId, workspaceId);
			return [];
		}
		const submission = value?.submission as Record<string, unknown> | undefined;
		if (submission && (!persisted || submission.session_id !== persisted.sessionId)) return [];
		if (persisted && submission?.session_id === persisted.sessionId) {
			const afterIndex =
				submission.after_message_id === null
					? -1
					: persisted.messages.findIndex(
							(message) => message.message_id === submission.after_message_id
						);
			const hasAnchor = submission.after_message_id === null || afterIndex >= 0;
			const sent =
				hasAnchor &&
				persisted.messages
					.slice(afterIndex + 1)
					.some(
						(message) =>
							message.role === 'user' &&
							message.content === submission.content &&
							contexts.every((context) =>
								message.source_contexts.some(
									(source) =>
										source.workspace_id === workspaceId &&
										source.document_id === context.document_id &&
										source.source_kind === context.source_kind &&
										source.source_ref === context.source_ref
								)
							)
					);
			if (sent) {
				clearPendingChatSourceContexts(userId, workspaceId);
				return [];
			}
		}
		return contexts.map((value) => ({
			resource_ref: {
				resource_type: 'source',
				resource_id: value.resource_ref.resource_id,
				href: typeof value.resource_ref.href === 'string' ? value.resource_ref.href : null
			},
			workspace_id: workspaceId,
			document_id: value.document_id,
			document_title: value.document_title,
			source_kind: value.source_kind,
			source_ref: value.source_ref,
			page: typeof value.page === 'number' && value.page >= 1 ? value.page : null,
			quote: value.quote,
			heading_path: typeof value.heading_path === 'string' ? value.heading_path : null,
			quote_truncated: value.quote_truncated === true
		}));
	} catch {
		clearPendingChatSourceContexts(userId, workspaceId);
		return [];
	}
}

export function clearPendingChatSourceContexts(userId: string, workspaceId: string) {
	if (typeof window === 'undefined') return;
	window.sessionStorage.removeItem(sourceContextStorageKey(userId, workspaceId));
}
