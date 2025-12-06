from dataclasses import dataclass, field


@dataclass
class SourceItem:
    doc_id: str | None = None
    source: str | None = None
    page: int | None = None
    chunk_id: int | None = None
    snippet: str | None = None
    edge_id: str | None = None
    community_id: str | None = None
    head: str | None = None
    tail: str | None = None
    relation: str | None = None
    score: float | None = None


@dataclass
class QueryResult:
    answer: str
    sources: list[SourceItem] = field(default_factory=list)
