# domain/document.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class DocumentData:
    status: str = "pending"
    status_message: str = ""

@dataclass
class MetaInfo:
    type: str = ""
    size: int = 0
    filename: str = ""

@dataclass
class DocumentMeta:
    keywords: list[str] = field(default_factory=list)
    graph: dict[str, Any] = field(default_factory=dict)
    mindmap: dict[str, Any] = field(default_factory=dict)
    images: list[dict[str, Any]] = field(default_factory=list)
    info: MetaInfo = field(default_factory=MetaInfo)


@dataclass
class Document:
    id: str
    filename: str
    data: DocumentData = field(default_factory=DocumentData)
    meta: DocumentMeta = field(default_factory=DocumentMeta)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def update_status(self, status: str, message: str = ""):
        self.data.status = status
        self.data.status_message = message
        self.updated_at = datetime.utcnow()
    
    def update_meta(self, meta: DocumentMeta):
        self.meta = meta
        self.updated_at = datetime.utcnow()



