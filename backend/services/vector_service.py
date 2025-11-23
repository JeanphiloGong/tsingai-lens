from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings


class VectorService:
    def __init__(
        self,
        store_dir: Path,
        embedding_model: str,
        embedding_base_url: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
    ):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model_name = embedding_model
        self.embedding_base_url = embedding_base_url
        self.embedding_api_key = embedding_api_key

        self.embedding = self._init_embedding()
        self.vs: Optional[FAISS] = None
        self._load()

    def _init_embedding(self):
        if self.embedding_base_url:
            return OpenAIEmbeddings(
                model=self.embedding_model_name,
                base_url=self.embedding_base_url,
                api_key=self.embedding_api_key or "EMPTY",
            )
        # Fallback to local HF embedding if没有提供 API
        return HuggingFaceEmbeddings(model_name=self.embedding_model_name)

    def _load(self) -> None:
        if (self.store_dir / "index.faiss").exists():
            self.vs = FAISS.load_local(
                str(self.store_dir), self.embedding, allow_dangerous_deserialization=True
            )

    def add_texts(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> None:
        metadatas = metadatas or [{} for _ in texts]
        docs = [Document(page_content=t, metadata=m) for t, m in zip(texts, metadatas)]
        if self.vs is None:
            self.vs = FAISS.from_documents(docs, self.embedding)
        else:
            self.vs.add_documents(docs)
        self.persist()

    def persist(self) -> None:
        if self.vs:
            self.vs.save_local(str(self.store_dir))

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        if not self.vs:
            return []
        return self.vs.similarity_search(query, k=k)


def dump_sources(docs: List[Document]) -> List[Dict]:
    return [
        {
            "content": d.page_content,
            "metadata": d.metadata,
        }
        for d in docs
    ]
