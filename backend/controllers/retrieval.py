"""API endpoints to trigger the standard GraphRAG indexing pipeline and manage configs."""

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from xml.etree.ElementTree import Element, SubElement, tostring

from config import CONFIG_DIR
from controllers.schemas import (
    ConfigCreateRequest,
    ConfigDetailResponse,
    ConfigListResponse,
    ConfigUploadResponse,
    IndexRequest,
    IndexResponse,
)
from retrieval.api.index import build_index
from retrieval.config.enums import IndexingMethod
from retrieval.config.load_config import load_config
from retrieval.utils.api import create_storage_from_config

router = APIRouter(prefix="/retrieval", tags=["retrieval"])
logger = logging.getLogger(__name__)


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


def _resolve_output_dir(output_path: str | None) -> Path:
    """Resolve the output directory from query or default config."""
    if output_path:
        base_dir = Path(output_path).expanduser().resolve()
    else:
        default_config = CONFIG_DIR / "default.yaml"
        if not default_config.is_file():
            raise HTTPException(
                status_code=400, detail="未提供 output_path，且默认配置不存在"
            )
        try:
            config = load_config(default_config.parent, config_filepath=default_config)
        except Exception as exc:
            logger.exception("Failed to load default GraphRAG config for graph view")
            raise HTTPException(
                status_code=400, detail=f"默认配置加载失败: {exc}"
            ) from exc
        base_dir = Path(getattr(config.output, "base_dir", default_config.parent))
        if not base_dir.is_absolute():
            base_dir = (default_config.parent / base_dir).resolve()

    if not base_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"输出目录不存在: {base_dir}")
    return base_dir


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, str | None]:
    """Load and filter graph data, returning nodes and edges payloads."""
    entities = _read_parquet_or_error(base_dir / "entities.parquet", "实体数据")
    relationships = _read_parquet_or_error(
        base_dir / "relationships.parquet", "关系数据"
    )

    community_label = None
    if community_id:
        communities = _read_parquet_or_error(
            base_dir / "communities.parquet", "社区数据"
        )
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

    return nodes_payload, edges_payload, truncated, community_label


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
        ("weight", "edge", "double"),
    ]
    for name, domain, attr_type in key_defs:
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
        for key in ["label", "type", "description", "degree", "frequency", "x", "y"]:
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
    logger.info(
        "Received indexing request config_path=%s method=%s is_update_run=%s verbose=%s",
        request.config_path,
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
        config_path = Path(request.config_path).expanduser().resolve()
        config = load_config(config_path.parent, config_filepath=config_path)
        logger.info("Loaded GraphRAG config from %s", config_path)
    except Exception as exc:
        logger.exception("Failed to load GraphRAG config")
        raise HTTPException(status_code=400, detail=f"配置加载失败: {exc}") from exc

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
    "/configs/upload",
    response_model=ConfigUploadResponse,
    summary="上传配置文件",
)
async def upload_config(file: UploadFile = File(...)) -> ConfigUploadResponse:
    """Upload a config file to the configs directory."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    filename = file.filename
    logger.info("Uploading config file filename=%s", filename)
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    dest = CONFIG_DIR / filename
    content = await file.read()
    dest.write_bytes(content)
    logger.info(
        "Config file saved filename=%s path=%s size_bytes=%s",
        filename,
        dest,
        len(content),
    )
    return ConfigUploadResponse(filename=filename, path=str(dest))


@router.post(
    "/configs",
    response_model=ConfigUploadResponse,
    summary="新增配置文件（文本）",
)
async def create_config(payload: ConfigCreateRequest) -> ConfigUploadResponse:
    """Create a new config file from raw text content."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Creating config file filename=%s", payload.filename)
    dest = CONFIG_DIR / payload.filename
    dest.write_text(payload.content, encoding="utf-8")
    logger.info(
        "Config file created filename=%s path=%s size_bytes=%s",
        payload.filename,
        dest,
        len(payload.content.encode("utf-8")),
    )
    return ConfigUploadResponse(filename=payload.filename, path=str(dest))


@router.get(
    "/configs",
    response_model=ConfigListResponse,
    summary="列出可用配置文件",
)
async def list_configs() -> ConfigListResponse:
    """List available configs under the configs directory."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug("Listing config files under %s", CONFIG_DIR)
    items = []
    for path in sorted(CONFIG_DIR.glob("*")):
        if path.is_file():
            stat = path.stat()
            items.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "modified_at": stat.st_mtime,
                }
            )
    logger.info("Configs listed count=%s", len(items))
    return ConfigListResponse(items=items)


@router.get(
    "/configs/{filename}",
    response_model=ConfigDetailResponse,
    summary="查看配置文件内容",
)
async def get_config(filename: str) -> ConfigDetailResponse:
    """Return the content of a config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / filename
    if not path.is_file():
        logger.warning("Requested config missing filename=%s path=%s", filename, path)
        raise HTTPException(status_code=404, detail="配置文件不存在")
    content = path.read_text(encoding="utf-8")
    logger.info(
        "Returning config filename=%s path=%s size_bytes=%s",
        filename,
        path,
        len(content.encode("utf-8")),
    )
    return ConfigDetailResponse(filename=filename, content=content)


@router.post(
    "/index/upload",
    response_model=IndexResponse,
    summary="上传文件并启动标准索引流程（使用默认配置）",
)
async def upload_and_index(
    file: UploadFile = File(...),
    method: IndexingMethod | str = Form(IndexingMethod.Standard),
    is_update_run: bool = Form(False),
    verbose: bool = Form(False),
) -> IndexResponse:
    """Upload a document to the configured input storage and run the pipeline."""
    logger.info(
        "Received upload for indexing filename=%s method=%s is_update_run=%s verbose=%s",
        file.filename if file else None,
        method,
        is_update_run,
        verbose,
    )
    # loading the default config file
    default_config = CONFIG_DIR / "default.yaml"
    if not default_config.is_file():
        logger.error("Default config missing at %s", default_config)
        raise HTTPException(
            status_code=500,
            detail="默认配置不存在，请在 backend/data/configs 下提供 default.yaml",
        )

    try:
        config = load_config(default_config.parent, config_filepath=default_config)
        logger.info("Loaded default GraphRAG config from %s", default_config)
    except Exception as exc:
        logger.exception("Failed to load default GraphRAG config")
        raise HTTPException(status_code=400, detail=f"配置加载失败: {exc}") from exc

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


@router.get(
    "/graphml",
    summary="导出知识图谱 GraphML 格式",
)
async def export_graphml(
    output_path: str | None = None,
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
) -> Response:
    """
    Export the knowledge graph as GraphML for tools like Gephi.

    It supports filtering options for output_path, max_nodes, min_weight, and
    community_id. If output_path is omitted, the default config output is used.
    """
    base_dir = _resolve_output_dir(output_path)
    (
        nodes_payload,
        edges_payload,
        truncated,
        community_label,
    ) = _load_graph_payload(base_dir, max_nodes, min_weight, community_id)

    graphml_bytes = _to_graphml(nodes_payload, edges_payload)
    filename = "graph"
    if community_label:
        filename += f"_{community_label}"
    filename += ".graphml"

    logger.info(
        "Served GraphML base_dir=%s nodes=%s edges=%s truncated=%s community=%s min_weight=%s",
        base_dir,
        len(nodes_payload),
        len(edges_payload),
        truncated,
        community_label,
        min_weight,
    )

    return Response(
        content=graphml_bytes,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
