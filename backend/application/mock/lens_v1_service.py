from __future__ import annotations

import os
from copy import deepcopy
from typing import Any


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _slice_items(items: list[dict[str, Any]], offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    return deepcopy(items[offset : offset + limit])


class LensV1MockService:
    """Serve stable dev-only fixtures over the formal API paths."""

    def __init__(self) -> None:
        self._collections = self._build_collections()

    def is_enabled(self) -> bool:
        return _is_truthy(os.getenv("LENS_ENABLE_MOCK_API"))

    def is_mock_collection(self, collection_id: str) -> bool:
        return collection_id in self._collections

    def is_mock_task(self, task_id: str) -> bool:
        return any(task["task_id"] == task_id for payload in self._collections.values() for task in payload["tasks"])

    def list_collections(self) -> list[dict[str, Any]]:
        return [deepcopy(payload["collection"]) for payload in self._collections.values()]

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        return deepcopy(payload["collection"])

    def list_files(self, collection_id: str) -> list[dict[str, Any]]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        return deepcopy(payload["files"])

    def list_tasks(
        self,
        collection_id: str,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        items = payload["tasks"]
        if status:
            items = [item for item in items if item.get("status") == status]
        return _slice_items(items, offset=offset, limit=limit)

    def get_task(self, task_id: str) -> dict[str, Any]:
        for payload in self._collections.values():
            for task in payload["tasks"]:
                if task["task_id"] == task_id:
                    return deepcopy(task)
        raise FileNotFoundError(f"mock task not found: {task_id}")

    def get_task_artifacts(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        payload = self._collections[task["collection_id"]]
        return {"task_id": task_id, **deepcopy(payload["workspace"]["artifacts"])}

    def create_index_task(self, collection_id: str) -> dict[str, Any]:
        tasks = self.list_tasks(collection_id, limit=1)
        if tasks:
            return tasks[0]
        raise FileNotFoundError(f"mock collection not found: {collection_id}")

    def get_workspace(self, collection_id: str) -> dict[str, Any]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        return deepcopy(payload["workspace"])

    def list_document_profiles(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        items = payload["document_profiles"]["items"]
        sliced = _slice_items(items, offset=offset, limit=limit)
        return {
            "collection_id": collection_id,
            "total": len(items),
            "count": len(sliced),
            "summary": deepcopy(payload["document_profiles"]["summary"]),
            "items": sliced,
        }

    def list_evidence_cards(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        items = payload["evidence_cards"]
        sliced = _slice_items(items, offset=offset, limit=limit)
        return {
            "collection_id": collection_id,
            "total": len(items),
            "count": len(sliced),
            "items": sliced,
        }

    def list_comparisons(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        payload = self._collections.get(collection_id)
        if payload is None:
            raise FileNotFoundError(f"mock collection not found: {collection_id}")
        items = payload["comparisons"]
        sliced = _slice_items(items, offset=offset, limit=limit)
        return {
            "collection_id": collection_id,
            "total": len(items),
            "count": len(sliced),
            "items": sliced,
        }

    def _build_collections(self) -> dict[str, dict[str, Any]]:
        return {
            "col_mock_empty": self._build_empty_collection(),
            "col_mock_processing": self._build_processing_collection(),
            "col_mock_ready": self._build_ready_collection(),
            "col_mock_limited": self._build_limited_collection(),
        }

    def _build_empty_collection(self) -> dict[str, Any]:
        collection_id = "col_mock_empty"
        workspace = self._build_workspace(
            collection_id=collection_id,
            name="Mock Empty Collection",
            description="No uploaded papers yet.",
            status="idle",
            paper_count=0,
            file_count=0,
            status_summary="empty",
            artifacts={
                "output_path": f"/mock/{collection_id}/output",
                "documents_generated": False,
                "documents_ready": False,
                "document_profiles_generated": False,
                "document_profiles_ready": False,
                "evidence_cards_generated": False,
                "evidence_cards_ready": False,
                "comparison_rows_generated": False,
                "comparison_rows_ready": False,
                "graph_generated": False,
                "graph_ready": False,
                "sections_generated": False,
                "sections_ready": False,
                "procedure_blocks_generated": False,
                "procedure_blocks_ready": False,
                "protocol_steps_generated": False,
                "protocol_steps_ready": False,
                "graphml_generated": False,
                "graphml_ready": False,
                "updated_at": "2026-04-11T09:00:00+00:00",
            },
            workflow={
                "documents": {"status": "not_started", "detail": "No files uploaded."},
                "evidence": {"status": "not_started", "detail": "No document profiles yet."},
                "comparisons": {"status": "not_started", "detail": "No evidence cards yet."},
                "protocol": {"status": "not_applicable", "detail": "Protocol branch not available before indexing."},
            },
            document_summary={
                "total_documents": 0,
                "by_doc_type": {},
                "by_protocol_extractable": {},
            },
            warnings=[
                {
                    "code": "empty_collection",
                    "severity": "info",
                    "message": "The collection has no uploaded papers yet.",
                }
            ],
            latest_task=None,
            recent_tasks=[],
            capabilities={
                "can_view_graph": False,
                "can_download_graphml": False,
                "can_view_protocol_steps": False,
                "can_search_protocol": False,
                "can_generate_sop": False,
            },
        )
        return {
            "collection": workspace["collection"],
            "files": [],
            "tasks": [],
            "workspace": workspace,
            "document_profiles": {
                "summary": {
                    "total_documents": 0,
                    "by_doc_type": {},
                    "by_protocol_extractable": {},
                    "warnings": ["No papers uploaded yet."],
                },
                "items": [],
            },
            "evidence_cards": [],
            "comparisons": [],
        }

    def _build_processing_collection(self) -> dict[str, Any]:
        collection_id = "col_mock_processing"
        task = {
            "task_id": "task_mock_processing_index",
            "collection_id": collection_id,
            "task_type": "index",
            "status": "running",
            "current_stage": "graphrag_index_started",
            "progress_percent": 45,
            "output_path": f"/mock/{collection_id}/output",
            "errors": [],
            "warnings": [],
            "created_at": "2026-04-11T09:10:00+00:00",
            "updated_at": "2026-04-11T09:18:00+00:00",
            "started_at": "2026-04-11T09:10:05+00:00",
            "finished_at": None,
        }
        workspace = self._build_workspace(
            collection_id=collection_id,
            name="Mock Processing Collection",
            description="Indexing is still running.",
            status="running",
            paper_count=8,
            file_count=8,
            status_summary="processing",
            artifacts={
                "output_path": f"/mock/{collection_id}/output",
                "documents_generated": False,
                "documents_ready": False,
                "document_profiles_generated": False,
                "document_profiles_ready": False,
                "evidence_cards_generated": False,
                "evidence_cards_ready": False,
                "comparison_rows_generated": False,
                "comparison_rows_ready": False,
                "graph_generated": False,
                "graph_ready": False,
                "sections_generated": False,
                "sections_ready": False,
                "procedure_blocks_generated": False,
                "procedure_blocks_ready": False,
                "protocol_steps_generated": False,
                "protocol_steps_ready": False,
                "graphml_generated": False,
                "graphml_ready": False,
                "updated_at": "2026-04-11T09:18:00+00:00",
            },
            workflow={
                "documents": {"status": "processing", "detail": "Document parsing is still in progress."},
                "evidence": {"status": "not_started", "detail": "Evidence extraction will begin after indexing."},
                "comparisons": {"status": "not_started", "detail": "Comparison rows are not generated yet."},
                "protocol": {"status": "not_started", "detail": "Protocol branch has not started yet."},
            },
            document_summary={
                "total_documents": 0,
                "by_doc_type": {},
                "by_protocol_extractable": {},
            },
            warnings=[
                {
                    "code": "indexing_in_progress",
                    "severity": "info",
                    "message": "Indexing is still running. Downstream resources are not ready yet.",
                }
            ],
            latest_task=task,
            recent_tasks=[task],
            capabilities={
                "can_view_graph": False,
                "can_download_graphml": False,
                "can_view_protocol_steps": False,
                "can_search_protocol": False,
                "can_generate_sop": False,
            },
        )
        files = [
            self._build_file_record(collection_id, index=i + 1, name=f"processing-paper-{i + 1}.pdf")
            for i in range(8)
        ]
        return {
            "collection": workspace["collection"],
            "files": files,
            "tasks": [task],
            "workspace": workspace,
            "document_profiles": {
                "summary": {
                    "total_documents": 0,
                    "by_doc_type": {},
                    "by_protocol_extractable": {},
                    "warnings": ["Indexing in progress."],
                },
                "items": [],
            },
            "evidence_cards": [],
            "comparisons": [],
        }

    def _build_ready_collection(self) -> dict[str, Any]:
        collection_id = "col_mock_ready"
        task = {
            "task_id": "task_mock_ready_index",
            "collection_id": collection_id,
            "task_type": "index",
            "status": "completed",
            "current_stage": "artifacts_ready",
            "progress_percent": 100,
            "output_path": f"/mock/{collection_id}/output",
            "errors": [],
            "warnings": [],
            "created_at": "2026-04-11T08:00:00+00:00",
            "updated_at": "2026-04-11T08:07:00+00:00",
            "started_at": "2026-04-11T08:00:03+00:00",
            "finished_at": "2026-04-11T08:07:00+00:00",
        }
        document_items = [
            {
                "document_id": "doc_mock_ready_1",
                "collection_id": collection_id,
                "title": "High-Rate Performance of Layered Oxide Cathodes",
                "source_filename": "ready-paper-1.pdf",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [
                    "high methods density",
                    "clear procedural continuity",
                    "complete temperature and duration parameters",
                ],
                "parsing_warnings": [],
                "confidence": 0.96,
            },
            {
                "document_id": "doc_mock_ready_2",
                "collection_id": collection_id,
                "title": "Interfacial Densification During 600 C Annealing",
                "source_filename": "ready-paper-2.pdf",
                "doc_type": "experimental",
                "protocol_extractable": "partial",
                "protocol_extractability_signals": [
                    "procedural language present",
                    "one critical atmosphere parameter missing",
                ],
                "parsing_warnings": ["Atmosphere is missing in one annealing step."],
                "confidence": 0.88,
            },
            {
                "document_id": "doc_mock_ready_3",
                "collection_id": collection_id,
                "title": "A Review of Filler Dispersion in Epoxy Systems",
                "source_filename": "ready-review-1.pdf",
                "doc_type": "review",
                "protocol_extractable": "no",
                "protocol_extractability_signals": [
                    "review contamination",
                    "insufficient step continuity",
                ],
                "parsing_warnings": ["Review sections should not be treated as final protocol sources."],
                "confidence": 0.91,
            },
        ]
        evidence_cards = [
            {
                "evidence_id": "ev_mock_ready_1",
                "document_id": "doc_mock_ready_1",
                "collection_id": collection_id,
                "claim_text": "Hot-press curing at 180 C improves flexural strength relative to the untreated baseline.",
                "claim_type": "property",
                "evidence_source_type": "figure",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor_mock_ready_1",
                        "source_type": "figure",
                        "section_id": "sec_results",
                        "block_id": "blk_fig_3",
                        "snippet_id": None,
                        "figure_or_table": "Figure 3",
                        "quote_span": "Flexural strength increased from 82 MPa to 97 MPa after hot-press curing.",
                    }
                ],
                "material_system": {
                    "family": "epoxy/SiO2 composite",
                    "composition": "epoxy + 5 wt% SiO2",
                },
                "condition_context": {
                    "process": {"curing_temperature_c": 180, "curing_time_min": 90},
                    "baseline": {"control": "untreated composite"},
                    "test": {"method": "three-point bending", "temperature_c": 25},
                },
                "confidence": 0.94,
                "traceability_status": "direct",
            },
            {
                "evidence_id": "ev_mock_ready_2",
                "document_id": "doc_mock_ready_2",
                "collection_id": collection_id,
                "claim_text": "Annealing at 600 C produces a denser interfacial microstructure.",
                "claim_type": "microstructure",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor_mock_ready_2",
                        "source_type": "text",
                        "section_id": "sec_discussion",
                        "block_id": "blk_txt_2",
                        "snippet_id": "snip_21",
                        "figure_or_table": None,
                        "quote_span": "SEM images show reduced porosity after 600 C annealing.",
                    }
                ],
                "material_system": {
                    "family": "epoxy/SiO2 composite",
                    "composition": "epoxy + 5 wt% SiO2",
                },
                "condition_context": {
                    "process": {"annealing_temperature_c": 600, "annealing_time_h": 2},
                    "baseline": {"control": "80 C dried sample"},
                    "test": {"method": "SEM"},
                },
                "confidence": 0.89,
                "traceability_status": "direct",
            },
            {
                "evidence_id": "ev_mock_ready_3",
                "document_id": "doc_mock_ready_1",
                "collection_id": collection_id,
                "claim_text": "The modulus increase may be linked to improved filler dispersion.",
                "claim_type": "mechanism",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor_mock_ready_3",
                        "source_type": "text",
                        "section_id": "sec_discussion",
                        "block_id": "blk_txt_4",
                        "snippet_id": "snip_33",
                        "figure_or_table": None,
                        "quote_span": "Improved dispersion is proposed as the cause of the higher modulus.",
                    }
                ],
                "material_system": {
                    "family": "epoxy/SiO2 composite",
                    "composition": "epoxy + 5 wt% SiO2",
                },
                "condition_context": {
                    "process": {"mixing": "ethanol-assisted dispersion"},
                    "baseline": {"control": "untreated composite"},
                    "test": {"method": "mechanical test"},
                },
                "confidence": 0.71,
                "traceability_status": "partial",
            },
        ]
        comparisons = [
            {
                "row_id": "cmp_mock_ready_1",
                "collection_id": collection_id,
                "source_document_id": "doc_mock_ready_1",
                "supporting_evidence_ids": ["ev_mock_ready_1"],
                "material_system_normalized": "epoxy/SiO2 composite (5 wt%)",
                "process_normalized": "hot-press cure at 180 C for 90 min",
                "property_normalized": "flexural_strength",
                "baseline_normalized": "untreated composite",
                "test_condition_normalized": "three-point bending at 25 C",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": 97.0,
                "unit": "MPa",
            },
            {
                "row_id": "cmp_mock_ready_2",
                "collection_id": collection_id,
                "source_document_id": "doc_mock_ready_2",
                "supporting_evidence_ids": ["ev_mock_ready_2"],
                "material_system_normalized": "epoxy/SiO2 composite (5 wt%)",
                "process_normalized": "anneal at 600 C for 2 h",
                "property_normalized": "interfacial_density",
                "baseline_normalized": "80 C dried sample",
                "test_condition_normalized": "SEM",
                "comparability_status": "limited",
                "comparability_warnings": ["Microstructure comparison is qualitative rather than numeric."],
                "value": None,
                "unit": None,
            },
        ]
        workspace = self._build_workspace(
            collection_id=collection_id,
            name="Mock Ready Collection",
            description="Evidence-first artifacts are ready for inspection.",
            status="ready",
            paper_count=3,
            file_count=3,
            status_summary="ready",
            artifacts={
                "output_path": f"/mock/{collection_id}/output",
                "documents_generated": True,
                "documents_ready": True,
                "document_profiles_generated": True,
                "document_profiles_ready": True,
                "evidence_cards_generated": True,
                "evidence_cards_ready": True,
                "comparison_rows_generated": True,
                "comparison_rows_ready": True,
                "graph_generated": True,
                "graph_ready": True,
                "sections_generated": True,
                "sections_ready": True,
                "procedure_blocks_generated": True,
                "procedure_blocks_ready": True,
                "protocol_steps_generated": True,
                "protocol_steps_ready": True,
                "graphml_generated": True,
                "graphml_ready": True,
                "updated_at": "2026-04-11T08:07:00+00:00",
            },
            workflow={
                "documents": {"status": "ready", "detail": "Document profiles are available."},
                "evidence": {"status": "ready", "detail": "Evidence cards are available."},
                "comparisons": {"status": "ready", "detail": "Comparison rows are available."},
                "protocol": {"status": "ready", "detail": "Protocol steps are available for methods-heavy papers."},
            },
            document_summary={
                "total_documents": 3,
                "by_doc_type": {"experimental": 2, "review": 1},
                "by_protocol_extractable": {"yes": 1, "partial": 1, "no": 1},
            },
            warnings=[],
            latest_task=task,
            recent_tasks=[task],
            capabilities={
                "can_view_graph": True,
                "can_download_graphml": True,
                "can_view_protocol_steps": True,
                "can_search_protocol": True,
                "can_generate_sop": True,
            },
        )
        files = [
            self._build_file_record(collection_id, index=1, name="ready-paper-1.pdf"),
            self._build_file_record(collection_id, index=2, name="ready-paper-2.pdf"),
            self._build_file_record(collection_id, index=3, name="ready-review-1.pdf"),
        ]
        return {
            "collection": workspace["collection"],
            "files": files,
            "tasks": [task],
            "workspace": workspace,
            "document_profiles": {
                "summary": {
                    "total_documents": 3,
                    "by_doc_type": {"experimental": 2, "review": 1},
                    "by_protocol_extractable": {"yes": 1, "partial": 1, "no": 1},
                    "warnings": [],
                },
                "items": document_items,
            },
            "evidence_cards": evidence_cards,
            "comparisons": comparisons,
        }

    def _build_limited_collection(self) -> dict[str, Any]:
        collection_id = "col_mock_limited"
        task = {
            "task_id": "task_mock_limited_index",
            "collection_id": collection_id,
            "task_type": "index",
            "status": "partial_success",
            "current_stage": "artifacts_ready",
            "progress_percent": 100,
            "output_path": f"/mock/{collection_id}/output",
            "errors": [],
            "warnings": ["Review-heavy corpus reduced protocol fidelity."],
            "created_at": "2026-04-11T07:30:00+00:00",
            "updated_at": "2026-04-11T07:39:00+00:00",
            "started_at": "2026-04-11T07:30:04+00:00",
            "finished_at": "2026-04-11T07:39:00+00:00",
        }
        document_items = [
            {
                "document_id": "doc_mock_limited_1",
                "collection_id": collection_id,
                "title": "Perspective on Fatigue Failure in Carbon Fiber Laminates",
                "source_filename": "limited-review-1.pdf",
                "doc_type": "review",
                "protocol_extractable": "no",
                "protocol_extractability_signals": ["review contamination", "missing procedural continuity"],
                "parsing_warnings": ["Review article content is not suitable for final protocol extraction."],
                "confidence": 0.95,
            },
            {
                "document_id": "doc_mock_limited_2",
                "collection_id": collection_id,
                "title": None,
                "source_filename": "limited-mixed-1.pdf",
                "doc_type": "mixed",
                "protocol_extractable": "partial",
                "protocol_extractability_signals": ["partial methods density", "missing critical parameters"],
                "parsing_warnings": ["Some reported gains lack a directly comparable baseline."],
                "confidence": 0.84,
            },
            {
                "document_id": "doc_mock_limited_3",
                "collection_id": collection_id,
                "title": None,
                "source_filename": None,
                "doc_type": "experimental",
                "protocol_extractable": "uncertain",
                "protocol_extractability_signals": ["procedural signal present", "step continuity uncertain"],
                "parsing_warnings": ["Measurement temperature is missing for one key result."],
                "confidence": 0.69,
            },
        ]
        evidence_cards = [
            {
                "evidence_id": "ev_mock_limited_1",
                "document_id": "doc_mock_limited_2",
                "collection_id": collection_id,
                "claim_text": "A surface treatment appears to improve fatigue resistance.",
                "claim_type": "property",
                "evidence_source_type": "table",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor_mock_limited_1",
                        "source_type": "table",
                        "section_id": "sec_results",
                        "block_id": "blk_tbl_2",
                        "snippet_id": None,
                        "figure_or_table": "Table 2",
                        "quote_span": "Treated sample showed higher fatigue life than the reference sample.",
                    }
                ],
                "material_system": {
                    "family": "carbon fiber composite",
                    "composition": "epoxy + carbon fiber",
                },
                "condition_context": {
                    "process": {"surface_treatment": "oxygen plasma"},
                    "baseline": {"control": "reference sample", "missing_definition": True},
                    "test": {"method": "fatigue", "temperature_c": None},
                },
                "confidence": 0.74,
                "traceability_status": "partial",
            },
            {
                "evidence_id": "ev_mock_limited_2",
                "document_id": "doc_mock_limited_3",
                "collection_id": collection_id,
                "claim_text": "The observed improvement may depend on unreported humidity conditions.",
                "claim_type": "qualitative",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor_mock_limited_2",
                        "source_type": "text",
                        "section_id": "sec_discussion",
                        "block_id": "blk_txt_9",
                        "snippet_id": "snip_71",
                        "figure_or_table": None,
                        "quote_span": "Humidity conditions were not recorded during testing.",
                    }
                ],
                "material_system": {
                    "family": "carbon fiber composite",
                    "composition": "epoxy + carbon fiber",
                },
                "condition_context": {
                    "process": {"surface_treatment": "oxygen plasma"},
                    "baseline": {"control": "untreated laminate"},
                    "test": {"method": "fatigue", "humidity": "missing"},
                },
                "confidence": 0.66,
                "traceability_status": "direct",
            },
        ]
        comparisons = [
            {
                "row_id": "cmp_mock_limited_1",
                "collection_id": collection_id,
                "source_document_id": "doc_mock_limited_2",
                "supporting_evidence_ids": ["ev_mock_limited_1"],
                "material_system_normalized": "carbon fiber composite",
                "process_normalized": "oxygen plasma surface treatment",
                "property_normalized": "fatigue_life",
                "baseline_normalized": "reference sample",
                "test_condition_normalized": "fatigue test (temperature missing)",
                "comparability_status": "limited",
                "comparability_warnings": [
                    "Baseline definition is ambiguous.",
                    "Testing temperature is missing.",
                ],
                "value": None,
                "unit": None,
            },
            {
                "row_id": "cmp_mock_limited_2",
                "collection_id": collection_id,
                "source_document_id": "doc_mock_limited_3",
                "supporting_evidence_ids": ["ev_mock_limited_2"],
                "material_system_normalized": "carbon fiber composite",
                "process_normalized": "oxygen plasma surface treatment",
                "property_normalized": "fatigue_life",
                "baseline_normalized": "untreated laminate",
                "test_condition_normalized": "fatigue test (humidity missing)",
                "comparability_status": "not_comparable",
                "comparability_warnings": [
                    "Humidity conditions are missing.",
                    "Reported gain should not be treated as directly comparable.",
                ],
                "value": None,
                "unit": None,
            },
        ]
        workspace = self._build_workspace(
            collection_id=collection_id,
            name="Mock Limited Collection",
            description="Evidence is available, but comparability is constrained.",
            status="partial_ready",
            paper_count=3,
            file_count=3,
            status_summary="partial_ready",
            artifacts={
                "output_path": f"/mock/{collection_id}/output",
                "documents_generated": True,
                "documents_ready": True,
                "document_profiles_generated": True,
                "document_profiles_ready": True,
                "evidence_cards_generated": True,
                "evidence_cards_ready": True,
                "comparison_rows_generated": True,
                "comparison_rows_ready": True,
                "graph_generated": True,
                "graph_ready": True,
                "sections_generated": True,
                "sections_ready": True,
                "procedure_blocks_generated": True,
                "procedure_blocks_ready": True,
                "protocol_steps_generated": False,
                "protocol_steps_ready": False,
                "graphml_generated": True,
                "graphml_ready": True,
                "updated_at": "2026-04-11T07:39:00+00:00",
            },
            workflow={
                "documents": {"status": "ready", "detail": "Document profiles are available."},
                "evidence": {"status": "ready", "detail": "Evidence cards are available."},
                "comparisons": {"status": "limited", "detail": "Comparison rows exist but carry strong caveats."},
                "protocol": {"status": "not_applicable", "detail": "The corpus is not reliable for final protocol steps."},
            },
            document_summary={
                "total_documents": 3,
                "by_doc_type": {"review": 1, "mixed": 1, "experimental": 1},
                "by_protocol_extractable": {"no": 1, "partial": 1, "uncertain": 1},
            },
            warnings=[
                {
                    "code": "review_heavy",
                    "severity": "warning",
                    "message": "The collection includes review-heavy material and should not default to protocol output.",
                },
                {
                    "code": "comparison_limited",
                    "severity": "warning",
                    "message": "Some surfaced gains are not directly comparable because baseline or test conditions are incomplete.",
                },
            ],
            latest_task=task,
            recent_tasks=[task],
            capabilities={
                "can_view_graph": True,
                "can_download_graphml": True,
                "can_view_protocol_steps": False,
                "can_search_protocol": False,
                "can_generate_sop": False,
            },
        )
        files = [
            self._build_file_record(collection_id, index=1, name="limited-review.pdf"),
            self._build_file_record(collection_id, index=2, name="limited-mixed.pdf"),
            self._build_file_record(collection_id, index=3, name="limited-experimental.pdf"),
        ]
        return {
            "collection": workspace["collection"],
            "files": files,
            "tasks": [task],
            "workspace": workspace,
            "document_profiles": {
                "summary": {
                    "total_documents": 3,
                    "by_doc_type": {"review": 1, "mixed": 1, "experimental": 1},
                    "by_protocol_extractable": {"no": 1, "partial": 1, "uncertain": 1},
                    "warnings": [
                        "Review-heavy corpus.",
                        "Protocol branch is not applicable for final steps.",
                    ],
                },
                "items": document_items,
            },
            "evidence_cards": evidence_cards,
            "comparisons": comparisons,
        }

    def _build_workspace(
        self,
        *,
        collection_id: str,
        name: str,
        description: str,
        status: str,
        paper_count: int,
        file_count: int,
        status_summary: str,
        artifacts: dict[str, Any],
        workflow: dict[str, Any],
        document_summary: dict[str, Any],
        warnings: list[dict[str, Any]],
        latest_task: dict[str, Any] | None,
        recent_tasks: list[dict[str, Any]],
        capabilities: dict[str, Any],
    ) -> dict[str, Any]:
        collection = {
            "collection_id": collection_id,
            "name": name,
            "description": description,
            "status": status,
            "default_method": "standard",
            "paper_count": paper_count,
            "created_at": "2026-04-10T12:00:00+00:00",
            "updated_at": artifacts["updated_at"],
        }
        links = {
            "documents_profiles": f"/api/v1/collections/{collection_id}/documents/profiles",
            "evidence_cards": f"/api/v1/collections/{collection_id}/evidence/cards",
            "comparisons": f"/api/v1/collections/{collection_id}/comparisons",
            "protocol_steps": (
                f"/api/v1/collections/{collection_id}/protocol/steps"
                if capabilities.get("can_view_protocol_steps")
                else None
            ),
        }
        return {
            "collection": collection,
            "file_count": file_count,
            "status_summary": status_summary,
            "artifacts": deepcopy(artifacts),
            "workflow": deepcopy(workflow),
            "document_summary": deepcopy(document_summary),
            "warnings": deepcopy(warnings),
            "latest_task": deepcopy(latest_task),
            "recent_tasks": deepcopy(recent_tasks),
            "capabilities": deepcopy(capabilities),
            "links": links,
        }

    def _build_file_record(self, collection_id: str, index: int, name: str) -> dict[str, Any]:
        return {
            "file_id": f"file_mock_{collection_id}_{index}",
            "collection_id": collection_id,
            "original_filename": name,
            "stored_filename": f"mock_{index}_{name}",
            "stored_path": f"/mock/{collection_id}/input/mock_{index}_{name}",
            "media_type": "application/pdf",
            "status": "stored",
            "size_bytes": 2048 + index,
            "created_at": "2026-04-10T12:10:00+00:00",
        }


lens_v1_mock_service = LensV1MockService()
