"""API endpoints to trigger retrieval pipelines and manage collections."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz
import pandas as pd
import yaml
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from xml.etree.ElementTree import Element, SubElement, tostring

from config import CONFIG_DIR
from controllers.schemas import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionRecord,
    InputUploadResponse,
    IndexRequest,
    IndexResponse,
    QueryRequest,
    QueryResponse,
)
from retrieval.api import query as query_api
from retrieval.api.index import build_index
from retrieval.config.enums import IndexingMethod, SearchMethod
from retrieval.config.load_config import load_config
from retrieval.utils.api import create_storage_from_config, reformat_context_data
from retrieval.utils.storage import load_table_from_storage, storage_has_table

router = APIRouter(prefix="/retrieval", tags=["retrieval"])
logger = logging.getLogger(__name__)

COLLECTIONS_DIR = CONFIG_DIR.parent / "collections"
DEFAULT_COLLECTION_ID = "default"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default.yaml"


def _format_context_excerpt(value: Any, limit: int = 200) -> str:
    """Return a short, log-friendly representation of arbitrary data."""
    try:
        text = str(value)
    except Exception:
        return f"<unserializable:{type(value).__name__}>"
    if len(text) > limit:
        return f"{text[:limit]}... (truncated, len={len(text)})"
    return text


def _pdf_to_text(content: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF (fitz)."""
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            texts = []
            for page in doc:
                texts.append(page.get_text("text"))
        return "\n".join(texts)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF解析失败: {exc}") from exc


def _collection_dir(collection_id: str) -> Path:
    return COLLECTIONS_DIR / collection_id


def _collection_config_path(collection_id: str) -> Path:
    return _collection_dir(collection_id) / "config.yaml"


def _collection_meta_path(collection_id: str) -> Path:
    return _collection_dir(collection_id) / "meta.json"


def _write_collection_meta(collection_id: str, name: str | None) -> None:
    meta = {
        "id": collection_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _collection_meta_path(collection_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _create_collection_dirs(collection_dir: Path) -> None:
    for subdir in ["input", "output", "update_output", "cache", "logs", "vector_store"]:
        (collection_dir / subdir).mkdir(parents=True, exist_ok=True)


def _create_collection_config(collection_dir: Path, template_path: Path) -> None:
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail=f"配置模板不存在: {template_path}")
    config_data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    config_data["root_dir"] = str(collection_dir.resolve())
    config_data.setdefault("input", {}).setdefault("storage", {})[
        "base_dir"
    ] = "input"
    config_data.setdefault("output", {})["base_dir"] = "output"
    config_data.setdefault("update_index_output", {})["base_dir"] = "update_output"
    config_data.setdefault("cache", {})["base_dir"] = "cache"
    config_data.setdefault("reporting", {})["base_dir"] = "logs"
    vector_store = config_data.setdefault("vector_store", {})
    default_store = vector_store.setdefault("default_vector_store", {})
    default_store.setdefault("type", "lancedb")
    default_store["db_uri"] = "vector_store/lancedb"
    config_path = collection_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _read_collection_meta(collection_dir: Path) -> dict[str, Any]:
    meta_path = collection_dir / "meta.json"
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Collection meta invalid: %s", meta_path)
    stat = collection_dir.stat()
    created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return {"id": collection_dir.name, "name": None, "created_at": created_at}


def _ensure_default_collection() -> None:
    if not _collection_dir(DEFAULT_COLLECTION_ID).is_dir():
        COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        default_dir = _collection_dir(DEFAULT_COLLECTION_ID)
        default_dir.mkdir(parents=True, exist_ok=True)
        _create_collection_dirs(default_dir)
        _create_collection_config(default_dir, DEFAULT_CONFIG_PATH)
        _write_collection_meta(DEFAULT_COLLECTION_ID, "default")


def _ensure_collection_exists(collection_id: str) -> Path:
    collection_dir = _collection_dir(collection_id)
    if not collection_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"集合不存在: {collection_id}")
    if not _collection_config_path(collection_id).is_file():
        raise HTTPException(status_code=404, detail=f"集合配置缺失: {collection_id}")
    return collection_dir


def _load_collection_config(collection_id: str | None) -> tuple[Any, str]:
    resolved_id = collection_id or DEFAULT_COLLECTION_ID
    if resolved_id == DEFAULT_COLLECTION_ID:
        _ensure_default_collection()
    else:
        _ensure_collection_exists(resolved_id)
    config_path = _collection_config_path(resolved_id)
    try:
        config = load_config(config_path.parent, config_filepath=config_path)
    except Exception as exc:
        logger.exception("Failed to load GraphRAG config for collection")
        raise HTTPException(status_code=400, detail=f"配置加载失败: {exc}") from exc
    return config, resolved_id


def _read_parquet_or_error(path: Path, label: str) -> pd.DataFrame:
    """Read a parquet file and raise a friendly HTTP error if missing or broken."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} 不存在: {path}")
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        logger.exception("Failed to read %s from %s", label, path)
        raise HTTPException(status_code=500, detail=f"{label} 读取失败: {exc}") from exc


def _safe_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _load_graph_payload(
    base_dir: Path,
    max_nodes: int,
    min_weight: float,
    community_id: str | None,
    include_community: bool,
) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], bool, str | None, int | None
]:
    """Load and filter graph data, returning nodes and edges payloads."""
    entities = _read_parquet_or_error(base_dir / "entities.parquet", "实体数据")
    relationships = _read_parquet_or_error(
        base_dir / "relationships.parquet", "关系数据"
    )

    communities = None
    community_level = None
    communities_path = base_dir / "communities.parquet"
    if community_id or include_community:
        if communities_path.is_file():
            communities = _read_parquet_or_error(communities_path, "社区数据")
        elif community_id:
            raise HTTPException(status_code=404, detail="社区数据不存在，无法筛选")
        elif include_community:
            logger.warning("社区数据不存在，跳过 community 字段输出")

    community_label = None
    community_row = None
    if community_id:
        if communities is None:
            raise HTTPException(status_code=404, detail="社区数据不存在，无法筛选")
        matched = communities[
            (communities["id"].astype(str) == community_id)
            | (communities["human_readable_id"].astype(str) == community_id)
            | (communities["community"].astype(str) == community_id)
        ]
        if matched.empty:
            raise HTTPException(status_code=404, detail="未找到指定社区")
        community_row = matched.iloc[0]
        entity_allowlist = set(str(e) for e in (community_row.get("entity_ids") or []))
        entities = entities[entities["id"].astype(str).isin(entity_allowlist)]
        community_label = (
            str(community_row.get("title"))
            if community_row.get("title") is not None
            else str(community_id)
        )

    if min_weight > 0:
        relationships = relationships[
            relationships["weight"].fillna(0) >= float(min_weight)
        ]

    truncated = False
    if len(entities) > max_nodes:
        entities = (
            entities.sort_values(by=["degree", "frequency"], ascending=False)
            .head(max_nodes)
            .copy()
        )
        truncated = True

    selected_ids = set(entities["id"].astype(str))
    community_map: dict[str, int | None] = {}
    if include_community and selected_ids:
        if community_row is not None:
            community_value = _safe_int(community_row.get("community"))
            community_level = _safe_int(community_row.get("level"))
            for entity_id in selected_ids:
                community_map[entity_id] = community_value
        elif communities is not None:
            if "level" in communities.columns:
                level_series = communities["level"].dropna()
                if not level_series.empty:
                    community_level = _safe_int(level_series.max())
            if community_level is not None and "level" in communities.columns:
                communities = communities[communities["level"] == community_level]
            community_join = communities.explode("entity_ids").loc[
                :, ["community", "entity_ids"]
            ]
            for _, row in community_join.iterrows():
                entity_id = row.get("entity_ids")
                if pd.isna(entity_id):
                    continue
                entity_id_str = str(entity_id)
                if (
                    entity_id_str in selected_ids
                    and entity_id_str not in community_map
                ):
                    community_map[entity_id_str] = _safe_int(row.get("community"))

    title_to_id = {
        str(row.title): str(row.id)
        for _, row in entities[["title", "id"]].dropna().iterrows()
    }

    def map_entity(value: Any) -> str:
        text = str(value)
        return title_to_id.get(text, text)

    def edge_in_subset(row: pd.Series) -> bool:
        source_id = map_entity(row["source"])
        target_id = map_entity(row["target"])
        return source_id in selected_ids and target_id in selected_ids

    relationships = relationships[relationships.apply(edge_in_subset, axis=1)]

    nodes_payload = [
        {
            "id": str(row.id),
            "label": str(row.title),
            "type": row.type if not pd.isna(row.type) else None,
            "description": row.description if not pd.isna(row.description) else None,
            "degree": _safe_int(row.degree),
            "frequency": _safe_int(row.frequency),
            "x": _safe_float(row.x),
            "y": _safe_float(row.y),
            "community": community_map.get(str(row.id)),
        }
        for _, row in entities.iterrows()
    ]

    edges_payload = [
        {
            "id": str(row.id),
            "source": map_entity(row.source),
            "target": map_entity(row.target),
            "weight": _safe_float(row.weight),
            "description": row.description if not pd.isna(row.description) else None,
        }
        for _, row in relationships.iterrows()
    ]

    return nodes_payload, edges_payload, truncated, community_label, community_level


def _to_graphml(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bytes:
    """Serialize nodes/edges into GraphML format."""
    gml = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

    key_defs = [
        ("label", "node", "string"),
        ("type", "node", "string"),
        ("description", "node", "string"),
        ("degree", "node", "int"),
        ("frequency", "node", "int"),
        ("x", "node", "double"),
        ("y", "node", "double"),
        ("community", "node", "int"),
        ("weight", "edge", "double"),
    ]
    has_community = any(node.get("community") is not None for node in nodes)
    for name, domain, attr_type in key_defs:
        if name == "community" and not has_community:
            continue
        SubElement(
            gml,
            "key",
            id=name,
            attr_name=name,
            attr_type=attr_type,
            **{"for": domain},
        )

    graph = SubElement(gml, "graph", id="G", edgedefault="undirected")

    def add_data(el: Element, key: str, value: Any) -> None:
        if value is None:
            return
        SubElement(el, "data", key=key).text = str(value)

    for node in nodes:
        n = SubElement(graph, "node", id=node["id"])
        for key in [
            "label",
            "type",
            "description",
            "degree",
            "frequency",
            "x",
            "y",
            "community",
        ]:
            add_data(n, key, node.get(key))

    for edge in edges:
        e = SubElement(
            graph,
            "edge",
            id=edge["id"],
            source=edge["source"],
            target=edge["target"],
        )
        for key in ["weight", "description"]:
            add_data(e, key, edge.get(key))

    return tostring(gml, encoding="utf-8", xml_declaration=True)


@router.post("/index", response_model=IndexResponse, summary="启动标准索引流程")
async def start_indexing(request: IndexRequest) -> IndexResponse:
    """Load config and run the standard indexing pipeline."""
    config, collection_id = _load_collection_config(request.collection_id)
    logger.info(
        "Received indexing request collection_id=%s method=%s is_update_run=%s verbose=%s",
        collection_id,
        request.method or IndexingMethod.Standard,
        request.is_update_run,
        request.verbose,
    )
    if request.additional_context is not None:
        logger.debug(
            "Indexing additional_context=%s",
            _format_context_excerpt(request.additional_context),
        )

    try:
        logger.info(
            "Starting indexing pipeline method=%s is_update_run=%s",
            request.method or IndexingMethod.Standard,
            request.is_update_run,
        )
        outputs = await build_index(
            config=config,
            method=request.method or IndexingMethod.Standard,
            is_update_run=request.is_update_run,
            additional_context=request.additional_context,
            verbose=request.verbose,
        )
    except Exception as exc:
        logger.exception("Indexing pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"流程执行失败: {exc}") from exc

    errors = [err for o in outputs for err in (o.errors or [])]
    status = "ok" if not errors else "error"
    logger.info(
        "Indexing finished status=%s workflows=%s error_count=%s",
        status,
        [o.workflow for o in outputs],
        len(errors),
    )
    if errors:
        logger.warning("Indexing completed with errors: %s", [str(e) for e in errors])

    return IndexResponse(
        status=status,
        workflows=[o.workflow for o in outputs],
        errors=[str(e) for e in errors] or None,
        output_path=str(getattr(config.output, "base_dir", "") or ""),
        stored_input_path=None,
    )


@router.post(
    "/collections",
    response_model=CollectionRecord,
    summary="创建集合",
)
async def create_collection(payload: CollectionCreateRequest) -> CollectionRecord:
    """Create a new collection with its own config and storage folders."""
    if not DEFAULT_CONFIG_PATH.is_file():
        raise HTTPException(
            status_code=500, detail="默认配置不存在，请在 backend/data/configs 下提供 default.yaml"
        )
    COLLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    collection_id = str(uuid4())
    collection_dir = _collection_dir(collection_id)
    collection_dir.mkdir(parents=True, exist_ok=True)
    _create_collection_dirs(collection_dir)
    _create_collection_config(collection_dir, DEFAULT_CONFIG_PATH)
    _write_collection_meta(collection_id, payload.name)
    return CollectionRecord(
        id=collection_id,
        name=payload.name,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/collections",
    response_model=CollectionListResponse,
    summary="列出集合",
)
async def list_collections() -> CollectionListResponse:
    """List available collections."""
    _ensure_default_collection()
    items: list[CollectionRecord] = []
    for path in sorted(COLLECTIONS_DIR.iterdir()):
        if not path.is_dir():
            continue
        meta = _read_collection_meta(path)
        items.append(
            CollectionRecord(
                id=meta.get("id", path.name),
                name=meta.get("name"),
                created_at=meta.get("created_at", ""),
            )
        )
    return CollectionListResponse(items=items)


@router.post(
    "/index/upload",
    response_model=IndexResponse,
    summary="上传文件并启动标准索引流程",
)
async def upload_and_index(
    file: UploadFile = File(...),
    collection_id: str | None = Form(None),
    method: IndexingMethod | str = Form(IndexingMethod.Standard),
    is_update_run: bool = Form(False),
    verbose: bool = Form(False),
) -> IndexResponse:
    """Upload a document to the configured input storage and run the pipeline."""
    config, resolved_collection_id = _load_collection_config(collection_id)
    logger.info(
        "Received upload for indexing collection_id=%s filename=%s method=%s is_update_run=%s verbose=%s",
        resolved_collection_id,
        file.filename if file else None,
        method,
        is_update_run,
        verbose,
    )

    # Save upload into input storage defined by config
    try:
        input_storage = create_storage_from_config(config.input.storage)
        raw_bytes = await file.read()
        suffix = (file.filename or "").lower()
        if suffix.endswith(".pdf"):
            logger.info("PDF detected; extracting text before indexing")
            text = _pdf_to_text(raw_bytes)
            stored_name = f"uploads/{uuid4()}_{file.filename}.txt"
            payload = text.encode("utf-8")
        else:
            stored_name = f"uploads/{uuid4()}_{file.filename}"
            payload = raw_bytes

        logger.info(
            "[controller.retrieval] Storing uploaded file filename=%s target_key=%s size_bytes=%s",
            file.filename,
            stored_name,
            len(payload),
        )
        await input_storage.set(stored_name, payload)
        stored_path = (
            Path(config.input.storage.base_dir) / stored_name
            if getattr(config.input.storage, "base_dir", None)
            else stored_name
        )
        logger.debug(
            "Upload stored base_dir=%s stored_path=%s",
            getattr(config.input.storage, "base_dir", None),
            stored_path,
        )
    except Exception as exc:
        logger.exception("Failed to store uploaded file into input storage")
        raise HTTPException(status_code=500, detail=f"文件保存失败: {exc}") from exc

    # Run indexing
    try:
        logger.info(
            "Starting indexing pipeline for uploaded file method=%s is_update_run=%s",
            method or IndexingMethod.Standard,
            is_update_run,
        )
        outputs = await build_index(
            config=config,
            method=method or IndexingMethod.Standard,
            is_update_run=is_update_run,
            additional_context=None,
            verbose=verbose,
        )
    except Exception as exc:
        logger.exception("Indexing pipeline execution failed")
        raise HTTPException(status_code=500, detail=f"流程执行失败: {exc}") from exc

    errors = [err for o in outputs for err in (o.errors or [])]
    status = "ok" if not errors else "error"
    logger.info(
        "Indexing finished for upload status=%s workflows=%s error_count=%s stored_input_path=%s",
        status,
        [o.workflow for o in outputs],
        len(errors),
        stored_path,
    )
    if errors:
        logger.warning("Indexing completed with errors: %s", [str(e) for e in errors])

    return IndexResponse(
        status=status,
        workflows=[o.workflow for o in outputs],
        errors=[str(e) for e in errors] or None,
        output_path=str(getattr(config.output, "base_dir", "") or ""),
        stored_input_path=str(stored_path),
    )


@router.post(
    "/input/upload",
    response_model=InputUploadResponse,
    summary="批量上传文件到输入存储（不触发索引）",
)
async def upload_inputs(
    collection_id: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> InputUploadResponse:
    """Upload files into input storage without running the indexing pipeline."""
    if not files:
        raise HTTPException(status_code=400, detail="文件不能为空")

    config, resolved_collection_id = _load_collection_config(collection_id)
    logger.info("Uploading input files collection_id=%s", resolved_collection_id)

    try:
        input_storage = create_storage_from_config(config.input.storage)
    except Exception as exc:
        logger.exception("Failed to create input storage")
        raise HTTPException(status_code=500, detail=f"存储初始化失败: {exc}") from exc

    base_dir = getattr(config.input.storage, "base_dir", None)
    items: list[dict[str, Any]] = []
    for file in files:
        filename = file.filename
        if not filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        raw_bytes = await file.read()
        suffix = filename.lower()
        converted_to_text = False
        if suffix.endswith(".pdf"):
            logger.info("PDF detected; extracting text before storing filename=%s", filename)
            text = _pdf_to_text(raw_bytes)
            stored_name = f"uploads/{uuid4()}_{filename}.txt"
            payload = text.encode("utf-8")
            converted_to_text = True
        elif suffix.endswith(".txt"):
            stored_name = f"uploads/{uuid4()}_{filename}"
            payload = raw_bytes
        else:
            raise HTTPException(status_code=400, detail="仅支持 PDF 或 TXT 文件")

        logger.info(
            "[controller.retrieval] Storing uploaded file filename=%s target_key=%s size_bytes=%s",
            filename,
            stored_name,
            len(payload),
        )
        await input_storage.set(stored_name, payload)
        stored_path = Path(base_dir) / stored_name if base_dir else stored_name
        items.append(
            {
                "original_filename": filename,
                "stored_name": stored_name,
                "stored_path": str(stored_path),
                "converted_to_text": converted_to_text,
                "size_bytes": len(payload),
            }
        )

    logger.info("Uploaded input files count=%s", len(items))
    return InputUploadResponse(count=len(items), items=items)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="基于索引结果进行检索问答",
)
async def query_index(payload: QueryRequest) -> QueryResponse:
    """Query indexed outputs and return an answer with optional context data."""
    if not payload.query:
        raise HTTPException(status_code=400, detail="query 不能为空")

    config, collection_id = _load_collection_config(payload.collection_id)
    base_dir = Path(getattr(config.output, "base_dir", config.root_dir))
    output_storage = create_storage_from_config(config.output)

    try:
        method = (
            SearchMethod(payload.method)
            if isinstance(payload.method, str)
            else payload.method
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="不支持的检索方法") from exc
    community_level = payload.community_level if payload.community_level is not None else 2

    try:
        if method == SearchMethod.GLOBAL:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            response, context_data = await query_api.global_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                community_level=payload.community_level,
                dynamic_community_selection=payload.dynamic_community_selection,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.LOCAL:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            text_units = await load_table_from_storage("text_units", output_storage)
            relationships = await load_table_from_storage(
                "relationships", output_storage
            )
            covariates = None
            if await storage_has_table("covariates", output_storage):
                covariates = await load_table_from_storage("covariates", output_storage)
            response, context_data = await query_api.local_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                covariates=covariates,
                community_level=community_level,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.DRIFT:
            entities = await load_table_from_storage("entities", output_storage)
            communities = await load_table_from_storage("communities", output_storage)
            community_reports = await load_table_from_storage(
                "community_reports", output_storage
            )
            text_units = await load_table_from_storage("text_units", output_storage)
            relationships = await load_table_from_storage(
                "relationships", output_storage
            )
            response, context_data = await query_api.drift_search(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                community_level=community_level,
                response_type=payload.response_type,
                query=payload.query,
                verbose=payload.verbose,
            )
        elif method == SearchMethod.BASIC:
            text_units = await load_table_from_storage("text_units", output_storage)
            response, context_data = await query_api.basic_search(
                config=config,
                text_units=text_units,
                query=payload.query,
                verbose=payload.verbose,
            )
        else:
            raise HTTPException(status_code=400, detail="不支持的检索方法")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Query execution failed")
        raise HTTPException(status_code=500, detail=f"查询执行失败: {exc}") from exc

    context_payload = None
    if payload.include_context:
        if isinstance(context_data, dict):
            context_payload = reformat_context_data(context_data)
        else:
            context_payload = context_data  # type: ignore[assignment]

    return QueryResponse(
        answer=response,
        method=str(method),
        collection_id=collection_id,
        output_path=str(base_dir),
        context_data=context_payload,
    )


@router.get(
    "/graphml",
    summary="导出知识图谱 GraphML 格式",
)
async def export_graphml(
    collection_id: str | None = Query(default=None, description="集合 ID"),
    max_nodes: int = Query(
        default=200, ge=1, le=2000, description="限制返回的最大节点数以避免过大响应"
    ),
    min_weight: float = Query(
        default=0.0, ge=0.0, description="按关系权重过滤（包含阈值）"
    ),
    community_id: str | None = Query(
        default=None,
        description="社区过滤（可传 id 或 human_readable_id / community 数值）",
    ),
    include_community: bool = Query(
        default=True,
        description="是否在 GraphML 节点上包含 community 字段（用于 Gephi 分组着色）",
    ),
) -> Response:
    """
    Export the knowledge graph as GraphML for tools like Gephi.

    It supports filtering options for max_nodes, min_weight, and community_id.
    Use include_community to attach community IDs to nodes for Gephi coloring.
    """
    config, resolved_collection_id = _load_collection_config(collection_id)
    base_dir = Path(getattr(config.output, "base_dir", config.root_dir))
    if not base_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"输出目录不存在: {base_dir}")
    (
        nodes_payload,
        edges_payload,
        truncated,
        community_label,
        community_level,
    ) = _load_graph_payload(
        base_dir,
        max_nodes,
        min_weight,
        community_id,
        include_community,
    )

    graphml_bytes = _to_graphml(nodes_payload, edges_payload)
    filename = "graph"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"

    logger.info(
        "Served GraphML collection_id=%s base_dir=%s nodes=%s edges=%s truncated=%s community=%s community_level=%s include_community=%s min_weight=%s",
        resolved_collection_id,
        base_dir,
        len(nodes_payload),
        len(edges_payload),
        truncated,
        community_label,
        community_level,
        include_community,
        min_weight,
    )

    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
