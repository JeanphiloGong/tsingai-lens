type GraphmlNode = {
  id: string;
  label: string;
  community?: string;
};

type GraphmlEdge = {
  id: string;
  source: string;
  target: string;
  weight: number;
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
    nodes.push({ id, label, community });
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
    edges.push({ id, source, target, weight });
  });

  return { nodes, edges, edgeDefault };
}
