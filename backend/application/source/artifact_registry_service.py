from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.ports import (
    BuildRepository,
    SourceArtifactRepository,
)
from domain.source import ArtifactStatusRecord, ArtifactVersionRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_ARTIFACT_FIELDS = (
    ("documents", "documents_generated", "documents_ready", None),
    ("blocks", "blocks_generated", "blocks_ready", None),
    ("figures", "figures_generated", "figures_ready", None),
    ("table_rows", "table_rows_generated", "table_rows_ready", None),
    ("table_cells", "table_cells_generated", "table_cells_ready", None),
)


class ArtifactRegistryService:
    """Track which collection-level artifacts are ready for downstream use."""

    def __init__(
        self,
        repository: BuildRepository,
        source_artifact_repository: SourceArtifactRepository,
    ) -> None:
        self.repository = repository
        self.source_artifact_repository = source_artifact_repository

    def build_registry(
        self,
        collection_id: str,
        output_dir: str | Path,
        *,
        build_id: str | None = None,
    ) -> dict:
        base_dir = Path(output_dir).expanduser().resolve()
        source_documents = (
            self.source_artifact_repository.read_collection_documents(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else self.source_artifact_repository.read_collection_documents(
                collection_id
            )
        )
        source_artifacts_generated = bool(source_documents)
        payload = ArtifactStatusRecord.build(
            collection_id=collection_id,
            output_path=str(base_dir),
            documents_generated=bool(source_documents),
            documents_ready=bool(source_documents),
            blocks_generated=source_artifacts_generated,
            blocks_ready=any(document.blocks for document in source_documents),
            figures_generated=source_artifacts_generated,
            figures_ready=any(document.figures for document in source_documents),
            table_rows_generated=source_artifacts_generated,
            table_rows_ready=any(
                document.table_rows for document in source_documents
            ),
            table_cells_generated=source_artifacts_generated,
            table_cells_ready=any(
                document.table_cells for document in source_documents
            ),
            updated_at=_now_iso(),
        ).to_record()
        return payload

    def register(
        self,
        task_id: str,
        collection_id: str,
        output_dir: str | Path,
        *,
        build_id: str | None = None,
    ) -> dict:
        stage = next(
            (
                item
                for item in self.repository.list_stages(task_id)
                if item.node.name == "artifact_registry"
            ),
            None,
        )
        if stage is None:
            raise RuntimeError(f"artifact_registry stage not found for task: {task_id}")
        payload = self.build_registry(collection_id, output_dir, build_id=build_id)
        records = tuple(
            ArtifactVersionRecord(
                artifact_version_id=f"artifact_{uuid4().hex[:20]}",
                build_stage_id=stage.stage_id,
                artifact_kind=artifact_kind,
                schema_version=1,
                content_version=1,
                status=(
                    "stale"
                    if stale_field is not None and payload[stale_field]
                    else "ready"
                    if payload[ready_field]
                    else "generated"
                ),
                object_id=None,
                details={},
                created_at=payload["updated_at"],
            )
            for artifact_kind, generated_field, ready_field, stale_field in _ARTIFACT_FIELDS
            if payload[generated_field]
        )
        self.repository.add_artifact_versions(task_id, records)
        return payload

    def get_for_task(self, task_id: str) -> dict:
        task = self.repository.read_task(task_id)
        if task is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        versions = self.repository.list_artifact_versions(task_id)
        if not versions:
            raise FileNotFoundError(f"artifact registry not found for task: {task_id}")
        payload: dict = {
            "collection_id": task.collection_id,
            "output_path": task.output_path or "",
            "updated_at": max(version.created_at for version in versions),
        }
        fields_by_kind = {item[0]: item[1:] for item in _ARTIFACT_FIELDS}
        for version in versions:
            fields = fields_by_kind.get(version.artifact_kind)
            if fields is None:
                continue
            generated_field, ready_field, stale_field = fields
            payload[generated_field] = True
            payload[ready_field] = version.status == "ready"
            if stale_field is not None:
                payload[stale_field] = version.status == "stale"
        return ArtifactStatusRecord.from_mapping(
            payload,
            collection_id=task.collection_id,
        ).to_record()
