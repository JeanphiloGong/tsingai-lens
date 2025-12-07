import { apiBase, handle } from './http';
import type { QueryResponse } from './types/chat';

export async function runQuery(params: {
  query: string;
  mode?: 'optimize' | 'precision' | 'recall';
  top_k_cards?: number;
  max_edges?: number;
}) {
  const { query, mode = 'optimize', top_k_cards = 5, max_edges = 80 } = params;
  return handle<QueryResponse>(
    await fetch(`${apiBase}/chat/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode, top_k_cards, max_edges })
    })
  );
}
