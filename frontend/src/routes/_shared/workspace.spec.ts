import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson } = vi.hoisted(() => ({
  requestJson: vi.fn()
}));

vi.mock('./api', () => ({
  requestJson
}));

const {
  fetchWorkspaceOverview,
  getCollectionWorkspaceState,
  getWorkspaceSurfaceState
} = await import('./workspace');

function buildWorkspacePayload(
  overrides: {
    workflow?: Record<string, unknown>;
    artifacts?: Record<string, unknown>;
    capabilities?: Record<string, unknown>;
  } = {}
) {
  return {
    collection: {
      collection_id: 'col_123',
      name: 'Semantic rollout test'
    },
    file_count: 2,
    status_summary: 'ready',
    warnings: [],
    workflow: {
      documents: 'ready',
      results: 'ready',
      evidence: 'ready',
      comparisons: 'ready',
      protocol: 'not_started',
      ...overrides.workflow
    },
    artifacts: {
      output_path: '/tmp/col_123',
      documents_generated: true,
      documents_ready: true,
      document_profiles_generated: true,
      document_profiles_ready: true,
      evidence_cards_generated: true,
      evidence_cards_ready: true,
      comparable_results_generated: false,
      comparable_results_ready: false,
      collection_comparable_results_generated: false,
      collection_comparable_results_ready: false,
      collection_comparable_results_stale: false,
      comparison_rows_generated: false,
      comparison_rows_ready: false,
      comparison_rows_stale: false,
      graph_generated: false,
      graph_ready: false,
      graph_stale: false,
      procedure_blocks_generated: false,
      procedure_blocks_ready: false,
      protocol_steps_generated: false,
      protocol_steps_ready: false,
      updated_at: '2026-04-22T00:00:00Z',
      ...overrides.artifacts
    },
    capabilities: {
      can_view_documents: true,
      can_view_results: true,
      can_view_evidence: true,
      can_view_comparisons: true,
      can_view_graph: false,
      can_download_graphml: false,
      can_view_protocol_steps: false,
      can_search_protocol: false,
      can_generate_sop: false,
      ...overrides.capabilities
    },
    recent_tasks: []
  };
}

describe('workspace shared helpers', () => {
  beforeEach(() => {
    requestJson.mockReset();
  });

  it('preserves semantic comparison artifact fields from the backend payload', async () => {
    requestJson.mockResolvedValue(
      buildWorkspacePayload({
        artifacts: {
          comparable_results_generated: true,
          comparable_results_ready: true,
          collection_comparable_results_generated: true,
          collection_comparable_results_ready: true,
          collection_comparable_results_stale: true,
          comparison_rows_generated: false,
          comparison_rows_ready: false,
          comparison_rows_stale: true,
          graph_generated: true,
          graph_ready: false,
          graph_stale: true
        }
      })
    );

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(workspace.artifacts).toMatchObject({
      comparable_results_generated: true,
      comparable_results_ready: true,
      collection_comparable_results_generated: true,
      collection_comparable_results_ready: true,
      collection_comparable_results_stale: true,
      comparison_rows_generated: false,
      comparison_rows_ready: false,
      comparison_rows_stale: true,
      graph_generated: true,
      graph_ready: false,
      graph_stale: true
    });
  });

  it('normalizes workspace results workflow, capability, and link fields', async () => {
    requestJson.mockResolvedValue({
      ...buildWorkspacePayload(),
      links: {
        results: '/api/v1/collections/col_123/results',
        comparisons: '/api/v1/collections/col_123/comparisons',
        documents: '/api/v1/collections/col_123/documents/profiles',
        evidence: '/api/v1/collections/col_123/evidence/cards'
      }
    });

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(workspace.workflow.results).toBe('ready');
    expect(workspace.capabilities.can_view_results).toBe(true);
    expect(workspace.links.results).toBe('/collections/col_123/results');
    expect(workspace.links.evidence).toBe('/collections/col_123/evidence');
  });

  it('treats stale comparison artifacts as limited in legacy workflow fallback', async () => {
    requestJson.mockResolvedValue({
      ...buildWorkspacePayload({
        artifacts: {
          comparable_results_generated: true,
          comparable_results_ready: true,
          collection_comparable_results_generated: true,
          collection_comparable_results_ready: false,
          collection_comparable_results_stale: true,
          comparison_rows_generated: false,
          comparison_rows_ready: false,
          comparison_rows_stale: false
        }
      }),
      workflow: null
    });

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(workspace.artifacts.collection_comparable_results_stale).toBe(true);
    expect(getWorkspaceSurfaceState(workspace, 'results')).toBe('limited');
    expect(getWorkspaceSurfaceState(workspace, 'comparisons')).toBe('limited');
    expect(getCollectionWorkspaceState(workspace)).toBe('ready_with_limits');
  });

  it('keeps the graph surface ready when graph artifacts are ready but row cache is not', async () => {
    requestJson.mockResolvedValue(
      buildWorkspacePayload({
        artifacts: {
          comparable_results_generated: true,
          comparable_results_ready: true,
          collection_comparable_results_generated: true,
          collection_comparable_results_ready: true,
          comparison_rows_generated: false,
          comparison_rows_ready: false,
          graph_generated: true,
          graph_ready: true
        }
      })
    );

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(workspace.artifacts.comparison_rows_ready).toBe(false);
    expect(workspace.artifacts.graph_ready).toBe(true);
    expect(getWorkspaceSurfaceState(workspace, 'graph')).toBe('ready');
  });

  it('treats stale graph artifacts as limited instead of not_applicable', async () => {
    requestJson.mockResolvedValue(
      buildWorkspacePayload({
        artifacts: {
          comparable_results_generated: true,
          comparable_results_ready: true,
          collection_comparable_results_generated: true,
          collection_comparable_results_ready: false,
          collection_comparable_results_stale: true,
          graph_generated: true,
          graph_ready: false,
          graph_stale: true
        }
      })
    );

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(workspace.artifacts.graph_stale).toBe(true);
    expect(getWorkspaceSurfaceState(workspace, 'graph')).toBe('limited');
  });

  it('does not regress the collection workspace state when semantic artifact fields are present', async () => {
    requestJson.mockResolvedValue(
      buildWorkspacePayload({
        artifacts: {
          comparable_results_generated: true,
          comparable_results_ready: true,
          collection_comparable_results_generated: true,
          collection_comparable_results_ready: true,
          comparison_rows_generated: true,
          comparison_rows_ready: true,
          graph_generated: true,
          graph_ready: true
        }
      })
    );

    const workspace = await fetchWorkspaceOverview('col_123');

    expect(getCollectionWorkspaceState(workspace)).toBe('ready');
  });
});
