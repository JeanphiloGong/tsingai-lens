import type { Writable } from 'svelte/store';
import type { DocumentProfile } from '../../../_shared/documents';

export const DOCUMENT_AGENT = Symbol('document-agent');

export type DocumentAgentState = {
	open: boolean;
	papers: Pick<DocumentProfile, 'document_id' | 'title'>[];
	sourceVersion: number;
	busy: boolean;
};

export type DocumentAgent = Writable<DocumentAgentState>;
