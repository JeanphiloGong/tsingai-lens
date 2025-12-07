from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class DocumentRecord(BaseModel):
    id: str
    filename: str
    original_filename: str
    tags: List[str] = Field(default_factory=list)
    metadata: Dict = Field(default_factory=dict)
    created_at: str
    status: str = "pending"
    status_message: str = ""
    updated_at: Optional[str] = None


class DocumentListResponse(BaseModel):
    items: List[DocumentRecord] = Field(default_factory=list)

class ImageItem(BaseModel):
    url: str
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

class DocumentMeta(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    graph: Dict = Field(default_factory=dict)
    mindmap: Dict = Field(default_factory=dict)
    images: List[ImageItem] = Field(default_factory=list)
    summary: str = ""


class DocumentDetailResponse(BaseModel):
    record: DocumentRecord
    meta: DocumentMeta


class DocumentKeywordsResponse(BaseModel):
    keywords: List[str] = Field(default_factory=list)


class DocumentGraphResponse(BaseModel):
    graph: Dict = Field(default_factory=dict)
    mindmap: Dict = Field(default_factory=dict)


class SourceItem(BaseModel):
    doc_id: Optional[str] = None
    source: Optional[str] = None
    page: Optional[int] = None
    chunk_id: Optional[int] = None
    snippet: Optional[str] = None
    edge_id: Optional[str] = None
    community_id: Optional[str] = None
    head: Optional[str] = None
    tail: Optional[str] = None
    relation: Optional[str] = None
    score: Optional[float] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceItem] = Field(default_factory=list)
