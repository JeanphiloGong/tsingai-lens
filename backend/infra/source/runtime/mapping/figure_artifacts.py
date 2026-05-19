from __future__ import annotations

import hashlib
from io import BytesIO
import logging
import re
from typing import Any

import pandas as pd

from domain.source import (
    SourceBoundingBox,
    SourceFigure,
    build_figure_caption_blocks,
    build_heading_blocks,
    find_nearest_caption_block,
    normalize_optional_text,
    resolve_heading_path_for_target,
)
from infra.source.contracts.artifact_schemas import FIGURES_FINAL_COLUMNS
from infra.source.runtime.hashing import gen_sha512_hash
from infra.source.runtime.mapping.layout_binding import (
    first_bbox,
    first_page,
    normalize_label,
)

logger = logging.getLogger(__name__)


def build_pdf_figures(
    *,
    document_id: str,
    document: Any,
    blocks: pd.DataFrame,
    text_items: list[dict[str, Any]],
    payload: bytes,
) -> tuple[pd.DataFrame, dict[str, bytes]]:
    pictures = getattr(document, "pictures", []) or []
    if not pictures:
        return pd.DataFrame(columns=FIGURES_FINAL_COLUMNS), {}

    block_records = blocks.to_dict(orient="records") if blocks is not None else []
    heading_blocks = build_heading_blocks(block_records)
    text_item_by_ref = {
        str(item.get("ref")): item
        for item in text_items
        if str(item.get("ref") or "").strip()
    }
    figure_caption_blocks = build_figure_caption_blocks(block_records)
    used_caption_block_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    figure_assets: dict[str, bytes] = {}
    pdf_document: Any | None = None

    try:
        for figure_order, picture in enumerate(pictures, start=1):
            page = first_page(getattr(picture, "prov", None))
            bbox_obj = first_bbox(getattr(picture, "prov", None))
            bbox = SourceBoundingBox.from_value(bbox_obj)
            caption_text, caption_ref, linkage_method = _extract_picture_caption(
                picture=picture,
                document=document,
            )
            caption_block_id = None
            if caption_ref is not None:
                caption_item = text_item_by_ref.get(caption_ref)
                if caption_item is not None:
                    caption_block_id = normalize_optional_text(caption_item.get("block_id"))
            if caption_block_id is None:
                fallback_block = find_nearest_caption_block(
                    page=page,
                    target_bbox=bbox,
                    caption_blocks=figure_caption_blocks,
                    used_block_ids=used_caption_block_ids,
                )
                if fallback_block is not None:
                    caption_block_id = str(fallback_block.block_id)
                    caption_text = caption_text or normalize_optional_text(
                        fallback_block.text
                    )
                    linkage_method = "same_page_nearest_caption"
            if caption_block_id is not None:
                used_caption_block_ids.add(caption_block_id)

            (
                image_bytes,
                image_width,
                image_height,
                image_mime_type,
                asset_sha256,
                asset_source,
                pdf_document,
            ) = _extract_picture_asset(
                picture=picture,
                document=document,
                payload=payload,
                pdf_document=pdf_document,
            )

            figure_id = gen_sha512_hash(
                {
                    "document_id": document_id,
                    "figure_order": figure_order,
                    "page": page,
                    "bbox": bbox.to_json() if bbox else None,
                    "caption_text": caption_text,
                },
                ["document_id", "figure_order", "page", "bbox", "caption_text"],
            )
            image_path = None
            if image_bytes is not None:
                image_path = f"image_assets/{figure_id}.png"
                figure_assets[image_path] = image_bytes

            rows.append(
                SourceFigure(
                    figure_id=figure_id,
                    document_id=document_id,
                    figure_order=figure_order,
                    figure_label=_extract_figure_label(caption_text),
                    caption_text=caption_text,
                    caption_block_id=caption_block_id,
                    page=page,
                    bbox=bbox,
                    heading_path=resolve_heading_path_for_target(
                        page=page,
                        target_bbox=bbox,
                        heading_blocks=heading_blocks,
                    ),
                    image_path=image_path,
                    image_mime_type=image_mime_type,
                    image_width=image_width,
                    image_height=image_height,
                    asset_sha256=asset_sha256,
                    metadata={
                        "docling_ref": f"#/pictures/{figure_order - 1}",
                        "picture_label": normalize_label(getattr(picture, "label", None)),
                        "caption_linkage_method": linkage_method,
                        "asset_source": asset_source,
                    },
                ).to_record()
            )
    finally:
        if pdf_document is not None:
            pdf_document.close()

    return pd.DataFrame(rows, columns=FIGURES_FINAL_COLUMNS), figure_assets


def _extract_picture_caption(*, picture: Any, document: Any) -> tuple[str | None, str | None, str]:
    caption_text = None
    if hasattr(picture, "caption_text"):
        caption_text = normalize_optional_text(picture.caption_text(document))
    caption_ref = None
    for ref in getattr(picture, "captions", []) or []:
        caption_ref = normalize_optional_text(getattr(ref, "cref", None))
        if caption_ref is None:
            continue
        if caption_text is not None:
            return caption_text, caption_ref, "docling_caption_ref"
        try:
            caption_text = normalize_optional_text(ref.resolve(document).text)
        except Exception:  # noqa: BLE001
            caption_text = None
        return caption_text, caption_ref, "docling_caption_ref"
    return caption_text, caption_ref, "none"


def _extract_picture_asset(
    *,
    picture: Any,
    document: Any,
    payload: bytes,
    pdf_document: Any | None,
) -> tuple[bytes | None, int | None, int | None, str | None, str | None, str, Any | None]:
    image = None
    asset_source = "missing"
    try:
        if hasattr(picture, "get_image"):
            image = picture.get_image(document)
            if image is not None:
                asset_source = "docling_crop"
    except Exception:  # noqa: BLE001
        logger.warning("Docling figure crop failed; falling back to PDF crop", exc_info=True)

    if image is None:
        try:
            pdf_document = pdf_document or _open_pdf_document(payload)
            image = _crop_picture_from_pdf(pdf_document=pdf_document, picture=picture)
            if image is not None:
                asset_source = "pymupdf_crop"
        except Exception:  # noqa: BLE001
            logger.warning("PDF figure crop failed", exc_info=True)

    if image is None:
        return None, None, None, None, None, asset_source, pdf_document

    asset_bytes = _serialize_png_image(image)
    return (
        asset_bytes,
        int(getattr(image, "width", 0) or 0),
        int(getattr(image, "height", 0) or 0),
        "image/png",
        hashlib.sha256(asset_bytes).hexdigest(),
        asset_source,
        pdf_document,
    )


def _open_pdf_document(payload: bytes) -> Any:
    import fitz

    return fitz.open(stream=payload, filetype="pdf")


def _crop_picture_from_pdf(*, pdf_document: Any, picture: Any) -> Any | None:
    from PIL import Image
    import fitz

    page_number = first_page(getattr(picture, "prov", None))
    bbox = first_bbox(getattr(picture, "prov", None))
    if page_number is None or bbox is None:
        return None
    page_index = page_number - 1
    if page_index < 0 or page_index >= len(pdf_document):
        return None
    page = pdf_document.load_page(page_index)
    clip_bbox = bbox
    if hasattr(bbox, "to_top_left_origin"):
        clip_bbox = bbox.to_top_left_origin(page_height=float(page.rect.height))
    clip = fitz.Rect(*clip_bbox.as_tuple())
    if clip.width <= 0 or clip.height <= 0:
        return None
    pixmap = page.get_pixmap(clip=clip, alpha=False)
    mode = "RGBA" if getattr(pixmap, "alpha", 0) else "RGB"
    return Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)


def _serialize_png_image(image: Any) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _extract_figure_label(caption_text: str | None) -> str | None:
    normalized = normalize_optional_text(caption_text)
    if normalized is None:
        return None
    match = re.match(r"^\s*((?:fig(?:ure)?\.?)\s*\d+[a-z]?)\b", normalized, re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).strip()
