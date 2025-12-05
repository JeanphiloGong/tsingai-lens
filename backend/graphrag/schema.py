from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Source:
    doc_id: str
    source: str
    page: Optional[int] = None
    chunk_id: Optional[int] = None
    snippet: Optional[str] = None
    score: Optional[float] = None


@dataclass
class Node:
    id: str
    name: str
    type: str
    attrs: Dict = field(default_factory=dict)


@dataclass
class Edge:
    id: str
    head: str
    tail: str
    relation: str
    attrs: Dict = field(default_factory=dict)
