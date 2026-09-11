from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from time import monotonic
from typing import Any

from application.core.objectives.discovery.signal_reconciliation import (
    PaperSignalReconciler,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
)
from application.core.objectives.paper_map_aggregation import (
    PaperMapAggregator,
    PaperMapSignalInput,
    notify_progress,
)
from application.core.objectives.paper_map_extraction import (
    PaperMapExtractionBudget,
    PaperMapExtractionService,
)
from application.core.objectives.paper_map_sources import PaperMapSourceSelector
from domain.core import (
    PaperResearchMap,
)
from domain.source import SourceDocument, SourceDocumentTree

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

# Research-scope limits for the bounded pre-Objective reading rounds.
_PAPER_MAP_EXPANSION_SOURCE_LIMIT = 8
_PAPER_MAP_EXPANSION_SOURCE_BUDGET = 24


class PaperResearchMapService:
    """Build a bounded Source-linked map of each paper's stated research scope."""

    def __init__(self) -> None:
        self._paper_map_aggregator = PaperMapAggregator()
        self._paper_map_extraction = PaperMapExtractionService()
        self._paper_map_sources = PaperMapSourceSelector(
            fit_payload=self._paper_map_extraction.fit_payload_to_prompt_limit,
        )

    def build_document_paper_map(
        self,
        collection_id: str,
        *,
        document: SourceDocument,
        profile: Any,
        document_tree: SourceDocumentTree | None,
        paper_map_extractor: PaperResearchMapExtractor,
        signal_reconciler: PaperSignalReconciler,
        progress_callback: ProgressCallback | None = None,
    ) -> PaperResearchMap:
        return self.build_collection_paper_maps(
            collection_id,
            documents=(document,),
            profiles_by_document_id={document.document_id: profile},
            document_trees_by_document_id={document.document_id: document_tree},
            paper_map_extractor=paper_map_extractor,
            signal_reconciler=signal_reconciler,
            progress_callback=progress_callback,
        )[0]

    def build_collection_paper_maps(
        self,
        collection_id: str,
        *,
        documents: tuple[SourceDocument, ...],
        profiles_by_document_id: Mapping[str, Any],
        document_trees_by_document_id: Mapping[
            str,
            SourceDocumentTree | None,
        ],
        paper_map_extractor: PaperResearchMapExtractor,
        signal_reconciler: PaperSignalReconciler,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        logger.info(
            "Research objective paper map started collection_id=%s document_count=%s",
            collection_id,
            len(documents),
        )
        paper_maps: list[PaperResearchMap] = []

        document_count = len(documents)
        for document_position, document in enumerate(documents, start=1):
            source_filename = self._resolve_source_filename(document)
            document_blocks = list(document.blocks)
            document_tables = list(document.tables)
            document_table_rows = list(document.table_rows)
            document_figures = list(document.figures)
            logger.info(
                "Research objective paper map document started collection_id=%s document_id=%s document_position=%s document_count=%s block_count=%s table_count=%s figure_count=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(document_blocks),
                len(document_tables),
                len(document_figures),
            )
            payloads = self._paper_map_sources.build_payloads(
                collection_id=collection_id,
                document=document,
                profile=profiles_by_document_id.get(document.document_id),
                blocks=document_blocks,
                tables=document_tables,
                table_rows=document_table_rows,
                figures=document_figures,
                document_tree=document_trees_by_document_id.get(document.document_id),
                paper_map_extractor=paper_map_extractor,
            )
            window_maps: list[PaperResearchMap] = []
            paper_signals: list[PaperMapSignalInput] = []
            window_count = len(payloads)
            selected_source_unit_count = sum(
                len(payload.get("source_units") or ()) for payload in payloads
            )
            recovery_call_budget = self._paper_map_extraction.document_recovery_call_budget(
                window_count,
                selected_source_unit_count=selected_source_unit_count,
            )
            extraction_budget = PaperMapExtractionBudget(
                deadline=monotonic() + self._paper_map_extraction.document_time_budget_seconds(),
                max_calls=window_count + recovery_call_budget,
                max_recovery_calls=recovery_call_budget,
            )
            for window_position, payload in enumerate(payloads, start=1):
                notify_progress(
                    progress_callback,
                    phase="paper_research_map_started",
                    current=document_position,
                    total=document_count,
                    unit="documents",
                    message="Mapping paper scope for candidate research objectives.",
                    active_document_id=document.document_id,
                    active_document_title=getattr(document, "title", None),
                    active_source_filename=source_filename,
                    active_window_position=window_position,
                    active_window_count=window_count,
                    active_window_role=payload["window_role"],
                )
            for batch_maps, batch_signals in self._paper_map_extraction.extract_window_payloads(
                collection_id=collection_id,
                document_id=document.document_id,
                payloads=payloads,
                paper_map_extractor=paper_map_extractor,
                extraction_budget=extraction_budget,
            ):
                window_maps.extend(batch_maps)
                paper_signals.extend(batch_signals)
            paper_map = self._paper_map_aggregator.consolidate_window_maps(
                document.document_id,
                window_maps,
                profile=profiles_by_document_id.get(document.document_id),
            )
            paper_map = self._paper_map_aggregator.drop_signals_resolved_by_relationships(paper_map)
            assessment = self._paper_map_aggregator.assess(
                paper_map,
                signals=tuple(item.signal for item in paper_signals),
                final=False,
            )
            expansion_round = 0
            remaining_expansion_sources = _PAPER_MAP_EXPANSION_SOURCE_BUDGET
            while (
                assessment.expansion_focus is not None
                and remaining_expansion_sources > 0
            ):
                expansion_focus = assessment.expansion_focus
                if expansion_round and expansion_focus == "outcome_specificity":
                    expansion_focus = "missing_scope"
                before_fact_count = (
                    sum(
                        len(study.relationships)
                        for study in paper_map.studies
                    )
                    + len(paper_map.unresolved_signals)
                    + len(paper_signals)
                )
                selected_source_keys = frozenset(
                    (
                        str(unit.get("source_kind") or ""),
                        str(unit.get("source_ref") or ""),
                    )
                    for payload in payloads
                    for unit in payload.get("source_units") or ()
                    if isinstance(unit, Mapping)
                )
                expansion_payloads = self._paper_map_sources.build_payloads(
                    collection_id=collection_id,
                    document=document,
                    profile=profiles_by_document_id.get(document.document_id),
                    blocks=document_blocks,
                    tables=document_tables,
                    table_rows=document_table_rows,
                    figures=document_figures,
                    document_tree=document_trees_by_document_id.get(
                        document.document_id
                    ),
                    paper_map_extractor=paper_map_extractor,
                    selection_focus=expansion_focus,
                    expansion_search_terms=self._paper_map_sources.expansion_search_terms(
                        paper_map,
                        paper_signals,
                    ),
                    expansion_source_limit=min(
                        _PAPER_MAP_EXPANSION_SOURCE_LIMIT,
                        remaining_expansion_sources,
                    ),
                    reading_round=expansion_round + 2,
                    excluded_source_keys=selected_source_keys,
                )
                if not expansion_payloads:
                    break
                remaining_expansion_sources -= sum(
                    len(payload.get("source_units") or ())
                    for payload in expansion_payloads
                )
                extraction_budget.add_capacity(len(expansion_payloads))
                for expansion_position, payload in enumerate(
                    expansion_payloads,
                    start=1,
                ):
                    notify_progress(
                        progress_callback,
                        phase="paper_research_map_started",
                        current=document_position,
                        total=document_count,
                        unit="documents",
                        message=(
                            "Expanding the paper map for unresolved scientific "
                            "scope."
                        ),
                        active_document_id=document.document_id,
                        active_document_title=getattr(document, "title", None),
                        active_source_filename=source_filename,
                        active_window_position=expansion_position,
                        active_window_count=len(expansion_payloads),
                        active_window_role=(
                            f"targeted_{expansion_focus}"
                        ),
                    )
                for batch_maps, batch_signals in self._paper_map_extraction.extract_window_payloads(
                    collection_id=collection_id,
                    document_id=document.document_id,
                    payloads=expansion_payloads,
                    paper_map_extractor=paper_map_extractor,
                    extraction_budget=extraction_budget,
                ):
                    window_maps.extend(batch_maps)
                    paper_signals.extend(batch_signals)
                payloads.extend(expansion_payloads)
                paper_map = self._paper_map_aggregator.consolidate_window_maps(
                    document.document_id,
                    window_maps,
                    profile=profiles_by_document_id.get(document.document_id),
                )
                paper_map = self._paper_map_aggregator.drop_signals_resolved_by_relationships(paper_map)
                expansion_round += 1
                after_fact_count = (
                    sum(
                        len(study.relationships)
                        for study in paper_map.studies
                    )
                    + len(paper_map.unresolved_signals)
                    + len(paper_signals)
                )
                if after_fact_count <= before_fact_count:
                    break
                assessment = self._paper_map_aggregator.assess(
                    paper_map,
                    signals=tuple(item.signal for item in paper_signals),
                    final=False,
                )
            paper_map = self._paper_map_aggregator.reconcile_signals(
                paper_map,
                paper_signals,
                signal_reconciler=signal_reconciler,
                extraction_budget=extraction_budget,
                progress_callback=progress_callback,
                document_position=document_position,
                document_count=document_count,
                document_title=getattr(document, "title", None),
                source_filename=source_filename,
            )
            paper_map = self._paper_map_aggregator.drop_signals_resolved_by_relationships(paper_map)
            final_assessment = self._paper_map_aggregator.assess(
                paper_map,
                signals=paper_map.unresolved_signals,
                final=True,
            )
            paper_map = replace(
                paper_map,
                map_status=final_assessment.status,
                map_limitations=final_assessment.limitations,
            )
            paper_maps.append(paper_map)
            logger.info(
                "Research objective paper map document finished collection_id=%s document_id=%s document_position=%s document_count=%s window_count=%s doc_role=%s study_count=%s relationship_count=%s unresolved_signal_count=%s completed_documents=%s remaining_documents=%s",
                collection_id,
                document.document_id,
                document_position,
                document_count,
                len(payloads),
                paper_map.doc_role,
                len(paper_map.studies),
                sum(len(study.relationships) for study in paper_map.studies),
                len(paper_map.unresolved_signals),
                document_position,
                max(document_count - document_position, 0),
            )
        return tuple(paper_maps)


    @staticmethod
    def _resolve_source_filename(document: Any) -> str | None:
        metadata = getattr(document, "metadata", {}) or {}
        for key in ("source_filename", "original_filename", "stored_filename"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
        return None


__all__ = ["PaperResearchMapService"]
