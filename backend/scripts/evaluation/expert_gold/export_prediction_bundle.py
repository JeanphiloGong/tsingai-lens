#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = "prediction-bundle-v0.3"
DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(DEFAULT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_BACKEND_ROOT))

from infra.persistence.database import (  # noqa: E402
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.postgres.document_profile_repository import (  # noqa: E402
    PostgresDocumentProfileRepository,
)
from infra.persistence.postgres.objective_repository import (  # noqa: E402
    PostgresObjectiveRepository,
)
from infra.persistence.postgres.source_artifact_repository import (  # noqa: E402
    PostgresSourceArtifactRepository,
)


DEFAULT_OUTPUT_PATH = (
    DEFAULT_BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "local_expert_gold"
    / "generated"
    / "prediction_bundle.json"
)
ARTIFACT_NAMES = (
    "documents",
    "document_profiles",
    "objective_evidence",
    "objective_findings",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export published Objective results for expert-gold evaluation."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--collection-id")
    source.add_argument("--output-dir", type=Path)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    output_path = await export_prediction_bundle(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        output_path=args.output,
    )
    print(output_path)


async def export_prediction_bundle(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    root = Path(backend_root).expanduser().resolve()
    output_dir = _resolve_source_output_dir(
        backend_root=root,
        collection_id=collection_id,
        source_output_dir=source_output_dir,
    )
    resolved_collection_id = collection_id or output_dir.parent.name
    records, missing = await _load_artifacts(resolved_collection_id)
    bundle = build_prediction_bundle(
        collection_id=resolved_collection_id,
        source_output_dir=output_dir,
        records_by_artifact=records,
        missing_artifacts=missing,
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_prediction_bundle(
    *,
    collection_id: str,
    source_output_dir: Path,
    records_by_artifact: dict[str, list[dict[str, Any]]],
    missing_artifacts: list[str],
) -> dict[str, Any]:
    evidence = _raw_records(
        records_by_artifact.get("objective_evidence", []),
        "objective_evidence",
    )
    findings = _raw_records(
        records_by_artifact.get("objective_findings", []),
        "objective_findings",
    )
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "collection_id": collection_id,
            "source_output_dir": str(source_output_dir),
            "fact_source": "published_objectives",
            "artifact_rows": {
                name: len(records_by_artifact.get(name, []))
                for name in ARTIFACT_NAMES
            },
            "missing_artifacts": list(missing_artifacts),
        },
        "papers": _convert_papers(
            records_by_artifact.get("documents", []),
            records_by_artifact.get("document_profiles", []),
        ),
        "samples": [],
        "process_parameters": [],
        "test_conditions": [],
        "measurement_results": [],
        "comparisons": [],
        "observations": [],
        "evidence": evidence,
        "uncertainties": [
            {
                "finding_id": finding.get("finding_id"),
                "synthesis_status": finding.get("synthesis_status"),
                "attribution_scope": finding.get("attribution_scope"),
                "certainty": finding.get("certainty"),
                "limitations": finding.get("limitations", []),
                "source": finding["source"],
            }
            for finding in findings
            if finding.get("synthesis_status") != "agreement"
        ],
        "global_notes": [],
        "objective_evidence": evidence,
        "objective_findings": findings,
    }


async def _load_artifacts(
    collection_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    engine = build_database_engine(DatabaseSettings())
    try:
        sessions = build_session_factory(engine)
        documents = await PostgresSourceArtifactRepository(
            sessions
        ).read_collection_documents(collection_id)
        profiles = await PostgresDocumentProfileRepository(sessions).list_collection(
            collection_id
        )
        objective_repository = PostgresObjectiveRepository(sessions)
        evidence: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for objective in await objective_repository.list_objectives(collection_id):
            version = objective.published_analysis_version
            if version is None:
                continue
            objective_evidence, _ = await objective_repository.list_evidence(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            objective_findings, _ = await objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            evidence.extend(item.to_record() for item in objective_evidence)
            findings.extend(item.to_record() for item in objective_findings)
    finally:
        await engine.dispose()
    records = {
        "documents": [item.to_record() for item in documents],
        "document_profiles": [item.to_record() for item in profiles],
        "objective_evidence": evidence,
        "objective_findings": findings,
    }
    return records, [name for name in ARTIFACT_NAMES if not records[name]]


def _convert_papers(
    documents: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles_by_document_id = {
        str(item.get("document_id") or ""): item for item in profiles
    }
    papers: list[dict[str, Any]] = []
    for row_number, document in enumerate(documents, start=1):
        document_id = str(
            document.get("document_id") or document.get("id") or ""
        ).strip()
        profile = profiles_by_document_id.get(document_id, {})
        metadata = document.get("metadata") or {}
        papers.append(
            {
                "paper_id": document_id,
                "title": profile.get("title") or document.get("title") or "",
                "doi": metadata.get("doi"),
                "source_filename": profile.get("source_filename")
                or metadata.get("source_filename"),
                "document_type": profile.get("doc_type"),
                "source": {"artifact": "documents", "row": row_number},
            }
        )
    return papers


def _raw_records(
    records: list[dict[str, Any]],
    artifact: str,
) -> list[dict[str, Any]]:
    return [
        {**dict(record), "source": {"artifact": artifact, "row": row_number}}
        for row_number, record in enumerate(records, start=1)
    ]


def _resolve_source_output_dir(
    *,
    backend_root: Path,
    collection_id: str | None,
    source_output_dir: str | Path | None,
) -> Path:
    if source_output_dir is not None:
        return Path(source_output_dir).expanduser().resolve()
    if not collection_id:
        raise SystemExit("--collection-id or --output-dir is required")
    return backend_root / "data" / "collections" / collection_id / "output"


if __name__ == "__main__":
    asyncio.run(main_async())
