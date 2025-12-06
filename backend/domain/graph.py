from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageAsset:
    url: str
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None

@dataclass
class GraphSnapshot:
    nodes: list[Any] = field(default_factory=list)
    edges: list[Any] = field(default_factory=list)


@dataclass
class DocumentMeta:
    keywords: list[str] = field(default_factory=list)
    graph: GraphSnapshot = field(default_factory=GraphSnapshot)
    mindmap: dict[str, Any] = field(default_factory=dict)
    images: list[ImageAsset] = field(default_factory=list)
    summary: str = ""
