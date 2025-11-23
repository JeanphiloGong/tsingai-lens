import json
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.graph.keywords import extract_keywords
from backend.graph.knowledge_graph import build_graph, to_graph_data
from backend.graph.mindmap import graph_to_mindmap
from backend.ingest.chunker import chunk_text
from backend.ingest.loader import load_file
from backend.qna.rag import answer_question
from backend.services.document_manager import DocumentManager
from backend.services.llm_client import LLMClient
from backend.services.vector_service import VectorService, dump_sources
from backend.config.settings import Settings


settings = Settings()

app = FastAPI(title="TsingAI-Lens API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

doc_manager = DocumentManager(settings.index_file, settings.documents_dir)
vector_service = VectorService(
    settings.vector_store_dir,
    settings.embedding_model,
    embedding_base_url=settings.embedding_base_url,
    embedding_api_key=settings.embedding_api_key,
)
llm_client = LLMClient(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    max_tokens=settings.llm_max_tokens,
)


def meta_path(doc_id: str) -> Path:
    return settings.documents_dir / f"{doc_id}_meta.json"


def write_meta(doc_id: str, data: Dict) -> None:
    path = meta_path(doc_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_meta(doc_id: str) -> Dict:
    path = meta_path(doc_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


@app.get("/health")
def health() -> Dict:
    return {"status": "ok"}


@app.get("/documents")
def list_documents() -> Dict:
    return {"items": doc_manager.list()}


@app.post("/documents")
async def upload_document(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(default=None),
    metadata: Optional[str] = Form(default=None),
) -> Dict:
    doc_id = str(uuid4())
    stored_filename = f"{doc_id}_{file.filename}"
    dest_path = settings.documents_dir / stored_filename
    settings.documents_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    dest_path.write_bytes(content)

    try:
        text, images = load_file(dest_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_tags = [t.strip() for t in tags.split(",")] if tags else []
    extra_metadata = json.loads(metadata) if metadata else {}

    record_id = doc_manager.register(
        original_filename=file.filename,
        stored_filename=stored_filename,
        tags=doc_tags,
        metadata=extra_metadata,
        doc_id=doc_id,
    )

    chunks = chunk_text(text)
    metadatas = [{"doc_id": doc_id, "source": file.filename, "chunk": idx} for idx, _ in enumerate(chunks)]
    vector_service.add_texts(chunks, metadatas)

    keywords = extract_keywords(text)
    graph_data = to_graph_data(build_graph(text))
    mindmap = graph_to_mindmap(graph_data)
    summary = llm_client.summarize(text[:3000]) if text else ""

    write_meta(
        doc_id,
        {
            "keywords": keywords,
            "graph": graph_data,
            "mindmap": mindmap,
            "images": images,
            "summary": summary,
        },
    )

    return {"id": record_id, "keywords": keywords, "graph": graph_data, "mindmap": mindmap, "summary": summary}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str) -> Dict:
    record = doc_manager.get(doc_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    meta = read_meta(doc_id)
    return {"record": record, "meta": meta}


@app.get("/documents/{doc_id}/keywords")
def get_keywords(doc_id: str) -> Dict:
    meta = read_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Document metadata not found")
    return {"keywords": meta.get("keywords", [])}


@app.get("/documents/{doc_id}/graph")
def get_graph(doc_id: str) -> Dict:
    meta = read_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Document metadata not found")
    return {"graph": meta.get("graph", {}), "mindmap": meta.get("mindmap", {})}


@app.post("/query")
async def query_documents(payload: Dict) -> Dict:
    query = payload.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="Missing query")
    top_k = int(payload.get("top_k", 4))
    docs = vector_service.similarity_search(query, k=top_k)
    qa = answer_question(query, docs, llm_client)
    return {"answer": qa["answer"], "sources": dump_sources(docs)}
