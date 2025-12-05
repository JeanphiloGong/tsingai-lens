import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)


class DocumentManager:
    def __init__(self, index_file: Path, documents_dir: Path):
        self.index_file = Path(index_file)
        self.documents_dir = Path(documents_dir)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, Dict] = {}
        logger.info("初始化文档管理器，索引文件=%s，文档目录=%s", self.index_file, self.documents_dir)
        self._load()

    def _load(self) -> None:
        if self.index_file.exists():
            try:
                logger.info("加载文档索引文件：%s", self.index_file)
                self.index = json.loads(self.index_file.read_text(encoding="utf-8"))
                logger.info("索引加载完成，文档数量=%s", len(self.index))
            except json.JSONDecodeError:
                logger.warning("索引文件格式错误，重置为空：%s", self.index_file)
                self.index = {}
        else:
            logger.info("未找到索引文件，初始化空索引：%s", self.index_file)

    def _save(self) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info("保存文档索引到：%s，文档数量=%s", self.index_file, len(self.index))
        self.index_file.write_text(json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(
        self,
        original_filename: str,
        stored_filename: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        doc_id = doc_id or str(uuid.uuid4())
        stored = stored_filename or original_filename
        logger.info(
            "注册文档：doc_id=%s，原始文件名=%s，存储文件名=%s，标签数=%s，元数据键数=%s",
            doc_id,
            original_filename,
            stored,
            len(tags or []),
            len((metadata or {}).keys()),
        )
        record = {
            "id": doc_id,
            "filename": stored,
            "original_filename": original_filename,
            "tags": tags or [],
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        self.index[doc_id] = record
        self._save()
        logger.info("文档注册完成：doc_id=%s", doc_id)
        return doc_id

    def get(self, doc_id: str) -> Optional[Dict]:
        record = self.index.get(doc_id)
        if record:
            logger.info("获取文档成功：doc_id=%s", doc_id)
        else:
            logger.warning("获取文档失败，未找到：doc_id=%s", doc_id)
        return record

    def list(self) -> List[Dict]:
        items = list(self.index.values())
        logger.info("列出所有文档，数量=%s", len(items))
        return items

    def path_for(self, doc_id: str) -> Path:
        record = self.index.get(doc_id)
        if not record:
            logger.warning("获取文档路径失败，未找到：doc_id=%s", doc_id)
            raise FileNotFoundError(f"Document {doc_id} not found")
        logger.info("获取文档路径成功：doc_id=%s，路径=%s", doc_id, self.documents_dir / record["filename"])
        return self.documents_dir / record["filename"]
