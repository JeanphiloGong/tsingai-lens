type GraphmlNode = {
  id: string;
  label: string;
  community?: string;
  type?: string;
  description?: string;
  degree?: number;
  frequency?: number;
  x?: number;
  y?: number;
  node_text_unit_ids?: string;
  node_text_unit_count?: number;
  node_document_ids?: string;
  node_document_titles?: string;
  node_document_count?: number;
};

type GraphmlEdge = {
  id: string;
  source: string;
  target: string;
  weight: number;
  edge_description?: string;
  edge_text_unit_ids?: string;
  edge_text_unit_count?: number;
  edge_document_ids?: string;
  edge_document_titles?: string;
  edge_document_count?: number;
};

export type GraphmlParseResult = {
  nodes: GraphmlNode[];
  edges: GraphmlEdge[];
  edgeDefault: 'directed' | 'undirected';
};

function parseNumber(value: string | null, fallback = 1) {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseOptionalNumber(value: string | null) {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function normalizeText(value: string | null) {
  return value ? value.trim() : '';
}

function parseKeyMap(doc: Document) {
  const map = new Map<string, string>();
  doc.querySelectorAll('key').forEach((key) => {
    const id = key.getAttribute('id');
    const name = key.getAttribute('attr.name');
    if (id && name) {
      map.set(id, name);
    }
  });
  return map;
}

function extractData(element: Element, keyMap: Map<string, string>) {
  const data: Record<string, string> = {};
  element.querySelectorAll('data').forEach((entry) => {
    const key = entry.getAttribute('key');
    if (!key) return;
    const name = keyMap.get(key) ?? key;
    const value = normalizeText(entry.textContent);
    data[name] = value;
  });
  return data;
}

export function parseGraphml(xml: string): GraphmlParseResult {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const parserError = doc.querySelector('parsererror');
  if (parserError) {
    throw new Error('GraphML parse error.');
  }

  const keyMap = parseKeyMap(doc);
  const graphElement = doc.querySelector('graph');
  const edgeDefault =
    graphElement?.getAttribute('edgedefault') === 'directed' ? 'directed' : 'undirected';

  const nodes: GraphmlNode[] = [];
  const edges: GraphmlEdge[] = [];

  doc.querySelectorAll('node').forEach((node) => {
    const id = node.getAttribute('id');
    if (!id) return;
    const data = extractData(node, keyMap);
    const label =
      data.label ||
      data.name ||
      data.title ||
      data.id ||
      id;
    const community = data.community || data.cluster || data.group || undefined;
    nodes.push({
      id,
      label,
      community,
      type: data.type || data.node_type || undefined,
      description: data.description || data.node_description || undefined,
      degree: parseOptionalNumber(data.degree),
      frequency: parseOptionalNumber(data.frequency),
      x: parseOptionalNumber(data.x),
      y: parseOptionalNumber(data.y),
      node_text_unit_ids: data.node_text_unit_ids || data.text_unit_ids || undefined,
      node_text_unit_count: parseOptionalNumber(data.node_text_unit_count || data.text_unit_count),
      node_document_ids: data.node_document_ids || data.document_ids || undefined,
      node_document_titles: data.node_document_titles || data.document_titles || undefined,
      node_document_count: parseOptionalNumber(data.node_document_count || data.document_count)
    });
  });

  doc.querySelectorAll('edge').forEach((edge, index) => {
    const source = edge.getAttribute('source');
    const target = edge.getAttribute('target');
    if (!source || !target) return;
    const data = extractData(edge, keyMap);
    const weight =
      parseNumber(data.weight) ||
      parseNumber(data.value) ||
      parseNumber(data.score) ||
      1;
    const id = edge.getAttribute('id') ?? `e-${index}`;
    edges.push({
      id,
      source,
      target,
      weight,
      edge_description: data.edge_description || data.description || undefined,
      edge_text_unit_ids: data.edge_text_unit_ids || data.text_unit_ids || undefined,
      edge_text_unit_count: parseOptionalNumber(data.edge_text_unit_count || data.text_unit_count),
      edge_document_ids: data.edge_document_ids || data.document_ids || undefined,
      edge_document_titles: data.edge_document_titles || data.document_titles || undefined,
      edge_document_count: parseOptionalNumber(data.edge_document_count || data.document_count)
    });
  });

  return { nodes, edges, edgeDefault };
}
