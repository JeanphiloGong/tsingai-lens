import { requestJson } from './api';

export type ReportCommunitySummary = {
  community_id?: number | null;
  human_readable_id?: number | null;
  parent?: number | null;
  children?: number[] | null;
  title?: string | null;
  summary?: string | null;
  findings?: unknown;
  rating?: number | null;
  size?: number | null;
};

export type ReportCommunityListResponse = {
  collection_id: string;
  level?: number | null;
  total: number;
  count: number;
  items: ReportCommunitySummary[];
};

export type ReportCommunityDetailResponse = ReportCommunitySummary & {
  collection_id: string;
  level?: number | null;
  document_count?: number | null;
  text_unit_count?: number | null;
  entities: Array<Record<string, unknown>>;
  relationships: Array<Record<string, unknown>>;
  documents: Array<Record<string, unknown>>;
};

export type ReportPatternItem = {
  community_id?: number | null;
  title?: string | null;
  summary?: string | null;
  findings?: unknown;
  rating?: number | null;
  size?: number | null;
  level?: number | null;
};

export type ReportPatternsResponse = {
  collection_id: string;
  level?: number | null;
  total_communities: number;
  total_entities?: number | null;
  total_relationships?: number | null;
  total_documents?: number | null;
  count: number;
  items: ReportPatternItem[];
};

export async function listCommunityReports(
  collectionId: string,
  options: { level?: number; limit?: number; offset?: number; minSize?: number; sort?: string } = {}
) {
  const params = new URLSearchParams({
    level: String(options.level ?? 2),
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
    min_size: String(options.minSize ?? 0),
    sort: options.sort ?? 'rating'
  });

  return (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/reports/communities?${params.toString()}`,
    { method: 'GET' }
  )) as ReportCommunityListResponse;
}

export async function getCommunityReportDetail(
  collectionId: string,
  communityId: string,
  options: { level?: number; entityLimit?: number; relationshipLimit?: number; documentLimit?: number } = {}
) {
  const params = new URLSearchParams();
  if (typeof options.level === 'number') params.set('level', String(options.level));
  params.set('entity_limit', String(options.entityLimit ?? 12));
  params.set('relationship_limit', String(options.relationshipLimit ?? 12));
  params.set('document_limit', String(options.documentLimit ?? 12));

  return (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/reports/communities/${encodeURIComponent(
      communityId
    )}?${params.toString()}`,
    { method: 'GET' }
  )) as ReportCommunityDetailResponse;
}

export async function listReportPatterns(
  collectionId: string,
  options: { level?: number; limit?: number; sort?: string } = {}
) {
  const params = new URLSearchParams({
    level: String(options.level ?? 2),
    limit: String(options.limit ?? 6),
    sort: options.sort ?? 'rating'
  });

  return (await requestJson(
    `/collections/${encodeURIComponent(collectionId)}/reports/patterns?${params.toString()}`,
    { method: 'GET' }
  )) as ReportPatternsResponse;
}
