import { beforeEach, describe, expect, it } from 'vitest';
import {
	readPendingChatSourceContext,
	storePendingChatSourceContext,
	type ChatMessage,
	type ChatSourceContext
} from './chatSessions';

const source: ChatSourceContext = {
	resource_ref: { resource_type: 'source', resource_id: 'doc_1:results', href: null },
	collection_id: 'col_123',
	document_id: 'doc_1',
	document_title: 'LPBF study',
	source_kind: 'text_window',
	source_ref: 'results',
	page: 3,
	quote: 'The grain size decreased after heat treatment.',
	heading_path: 'Results',
	quote_truncated: false
};
const question: ChatMessage = {
	message_id: 'old_question',
	session_id: 'chat_1',
	role: 'user',
	content: 'Explain this grain-size result',
	created_at: '2026-09-09T08:00:00Z',
	tool_call_id: null,
	tool_calls: [],
	tool_result: null,
	source_contexts: [source]
};
const answer: ChatMessage = {
	...question,
	message_id: 'old_answer',
	role: 'assistant',
	content: 'Prior answer',
	source_contexts: []
};

describe('pending Source recovery', () => {
	beforeEach(() => sessionStorage.clear());

	it('retains a deliberately reselected Source even if the same source and question were previously sent', () => {
		storePendingChatSourceContext('user_1', source, {
			session_id: 'chat_1',
			content: question.content,
			after_message_id: null
		});
		storePendingChatSourceContext('user_1', source);
		expect(
			readPendingChatSourceContext('user_1', 'col_123', {
				sessionId: 'chat_1',
				messages: [question, answer]
			})
		).toEqual(source);
	});

	it('only consumes the current submission after its preceding message, including after reload', () => {
		storePendingChatSourceContext('user_1', source, {
			session_id: 'chat_1',
			content: question.content,
			after_message_id: answer.message_id
		});
		expect(
			readPendingChatSourceContext('user_1', 'col_123', {
				sessionId: 'chat_1',
				messages: [question, answer]
			})
		).toEqual(source);
		expect(
			readPendingChatSourceContext('user_1', 'col_123', {
				sessionId: 'chat_1',
				messages: [question, answer, { ...question, message_id: 'new_question' }]
			})
		).toBeNull();
		expect(readPendingChatSourceContext('user_1', 'col_123')).toBeNull();
	});

	it('does not consume a submission using another conversation trajectory', () => {
		storePendingChatSourceContext('user_1', source, {
			session_id: 'chat_1',
			content: question.content,
			after_message_id: null
		});
		expect(
			readPendingChatSourceContext('user_1', 'col_123', {
				sessionId: 'chat_2',
				messages: [{ ...question, session_id: 'chat_2' }]
			})
		).toEqual(source);
	});
});
