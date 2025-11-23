from collections import Counter
from typing import Dict, List, Tuple

import networkx as nx

try:
    import spacy
except ImportError:  # pragma: no cover - handled at runtime
    spacy = None


def _load_spacy():
    if not spacy:
        return None
    try:
        return spacy.load("zh_core_web_sm")
    except OSError:
        # Model not present; caller can decide to install later.
        return None


def build_graph(text: str) -> nx.Graph:
    """Create a lightweight entity co-occurrence graph."""
    nlp = _load_spacy()
    graph = nx.Graph()

    if nlp:
        doc = nlp(text)
        entities = [ent.text for ent in doc.ents if ent.label_ not in {"CARDINAL"}]
    else:
        # Fallback: use high-frequency tokens as pseudo-entities
        tokens = [t for t in text.split() if len(t) > 1]
        common = Counter(tokens).most_common(30)
        entities = [t for t, _ in common]

    for ent in entities:
        if ent not in graph:
            graph.add_node(ent, label=ent)

    # Simple co-occurrence edges within a sliding window
    window_size = 3
    for i in range(len(entities) - window_size + 1):
        window = entities[i : i + window_size]
        for a in window:
            for b in window:
                if a == b:
                    continue
                weight = graph[a][b]["weight"] + 1 if graph.has_edge(a, b) else 1
                graph.add_edge(a, b, weight=weight)

    return graph


def to_graph_data(graph: nx.Graph) -> Dict:
    nodes = [{"id": n, "label": graph.nodes[n].get("label", n)} for n in graph.nodes]
    edges = [
        {"source": u, "target": v, "weight": graph[u][v].get("weight", 1)}
        for u, v in graph.edges
    ]
    return {"nodes": nodes, "edges": edges}
