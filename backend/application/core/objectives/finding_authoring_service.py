from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from uuid import uuid4

from application.core.objectives import property_matching
from domain.core import (
    FINDING_ASSERTION_STRENGTHS,
    Finding,
    FindingPaperContribution,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
)
from domain.ports import ObjectiveRepository
from application.source.collection_service import CollectionService


_PAGE_SIZE = 500
_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][-+]?\d+)?"
)
_MEASUREMENT_PATTERN = re.compile(
    r"(?P<number>(?<![A-Za-z0-9])[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"
    r"(?:[eE][-+]?\d+)?)\s*(?P<unit>%|(?:\u00b0\s*)?[A-Za-z\u00b5\u03bc]{1,8}"
    r"(?:[/\u00b7^][A-Za-z0-9\u00b5\u03bc-]{1,8})?)",
)
_LOCATOR_PREFIX_PATTERN = re.compile(
    r"(?:\b(?:pages?|p|tables?|t|figures?|fig|sections?|sec|equations?|eq)"
    r"\s*\.?\s*)$",
    re.IGNORECASE,
)
_CAUSAL_STATEMENT_PATTERN = re.compile(
    r"\b(?:caus(?:e|ed|es|ing)|lead(?:s|ing)?\s+to|led\s+to|"
    r"result(?:ed|s|ing)?\s+in|induc(?:e|ed|es|ing)|produce(?:d|s)?|"
    r"determin(?:e|ed|es|ing))\b",
    re.IGNORECASE,
)
_DIRECTION_TERMS = {
    "increase": frozenset(
        {
            "increase",
            "increased",
            "increases",
            "increasing",
            "higher",
            "greater",
            "larger",
        }
    ),
    "decrease": frozenset(
        {
            "decrease",
            "decreased",
            "decreases",
            "decreasing",
            "lower",
            "reduce",
            "reduced",
            "reduces",
            "reducing",
            "smaller",
        }
    ),
    "improve": frozenset(
        {"improve", "improved", "improves", "improving", "better", "enhanced"}
    ),
    "worsen": frozenset(
        {"worsen", "worsened", "worsens", "worsening", "worse", "degraded"}
    ),
    "no_change": frozenset(
        {"unchanged", "similar", "constant", "same", "no_change"}
    ),
    "changed": frozenset(
        {"change", "changed", "changes", "different", "difference"}
    ),
    "mixed": frozenset(
        {"mixed", "opposing", "inconsistent", "conflicting", "conflict"}
    ),
}


@dataclass(frozen=True)
class FindingAuthoringResult:
    analysis: ObjectiveAnalysis
    finding: Finding | None


class FindingAuthoringService:
    """Create one immutable researcher-authored Finding analysis version."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        objective_repository: ObjectiveRepository,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository

    async def create_version(
        self,
        *,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        statement: str | None,
        assertion_strength: str | None,
        supporting_evidence_ids: tuple[str, ...],
        contradicting_evidence_ids: tuple[str, ...],
        context_evidence_ids: tuple[str, ...],
        condition_boundary_evidence_ids: tuple[str, ...],
        limitations: tuple[str, ...],
        parent_finding_id: str | None,
        abstention_reason: str | None,
        created_by_user_id: str,
        created_by_tool_call_id: str | None = None,
    ) -> FindingAuthoringResult:
        await self.collection_service.get_collection_for_user(
            collection_id, created_by_user_id
        )
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.published_analysis_version != source_analysis_version:
            raise ValueError("source analysis version is stale")
        source_analysis = await self.objective_repository.read_analysis(
            collection_id, objective_id, source_analysis_version
        )
        if source_analysis is None or source_analysis.status != "succeeded":
            raise ValueError("source analysis version is not available")
        active = await self.objective_repository.read_analysis(
            collection_id, objective_id, objective.active_analysis_version
        )
        if active is not None and active.analysis_version != source_analysis_version:
            if active.status in {"queued", "running"}:
                raise ValueError("objective analysis is currently running")
        target_version = max(
            source_analysis_version,
            objective.active_analysis_version or source_analysis_version,
        ) + 1

        source_contributions = await self.objective_repository.list_contributions(
            collection_id, objective_id, source_analysis_version
        )
        source_evidence = await self._all_evidence(
            collection_id, objective_id, source_analysis_version
        )
        source_findings = await self._all_findings(
            collection_id, objective_id, source_analysis_version
        )
        now = datetime.now(timezone.utc)
        contributions = tuple(
            replace(item, analysis_version=target_version)
            for item in source_contributions
        )
        evidence_records = tuple(
            replace(item, analysis_version=target_version)
            for item in source_evidence
        )
        findings = tuple(
            replace(
                item,
                analysis_version=target_version,
                source_analysis_version=(
                    item.source_analysis_version or source_analysis_version
                ),
            )
            for item in source_findings
        )

        authored_finding: Finding | None = None
        abstention_note: str | None = None
        if abstention_reason is not None:
            self._validate_abstention(
                statement=statement,
                assertion_strength=assertion_strength,
                selected_ids=(
                    *supporting_evidence_ids,
                    *contradicting_evidence_ids,
                    *context_evidence_ids,
                    *condition_boundary_evidence_ids,
                ),
                parent_finding_id=parent_finding_id,
                limitations=limitations,
            )
            abstention_note = "\n".join(limitations)
        else:
            authored_finding = self._build_finding(
                collection_id=collection_id,
                objective_id=objective_id,
                source_analysis_version=source_analysis_version,
                target_analysis_version=target_version,
                statement=statement,
                assertion_strength=assertion_strength,
                supporting_evidence_ids=supporting_evidence_ids,
                contradicting_evidence_ids=contradicting_evidence_ids,
                context_evidence_ids=context_evidence_ids,
                condition_boundary_evidence_ids=(
                    condition_boundary_evidence_ids
                ),
                limitations=limitations,
                parent_finding_id=parent_finding_id,
                created_by_user_id=created_by_user_id,
                created_by_tool_call_id=created_by_tool_call_id,
                created_at=now,
                evidence_records=evidence_records,
                contributions=contributions,
                source_findings=source_findings,
                display_rank=(
                    max((item.display_rank for item in findings), default=-1) + 1
                ),
            )
            findings = (*findings, authored_finding)

        analysis = ObjectiveAnalysis(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=target_version,
            document_inputs=source_analysis.document_inputs,
            pipeline_version=source_analysis.pipeline_version,
            model_name=source_analysis.model_name,
            prompt_versions=dict(source_analysis.prompt_versions),
            stats=source_analysis.stats,
            status="succeeded",
            phase="completed",
            processed_document_count=len(source_analysis.document_inputs),
            total_document_count=len(source_analysis.document_inputs),
            progress_message=(
                "Researcher-authored evidence decision completed."
                if abstention_reason
                else "Researcher-authored Finding version completed."
            ),
            created_at=now,
            started_at=now,
            completed_at=now,
            diagnostics=source_analysis.diagnostics,
            origin=(
                "hybrid"
                if source_findings
                else (
                    "agent_authored"
                    if created_by_tool_call_id
                    else "human_authored"
                )
            ),
            source_analysis_version=source_analysis_version,
            created_by_user_id=created_by_user_id,
            created_by_tool_call_id=created_by_tool_call_id,
            abstention_reason=abstention_reason,
            abstention_note=abstention_note,
        )
        _objective, published = (
            await self.objective_repository.publish_authored_analysis(
                collection_id,
                objective_id,
                source_analysis_version,
                analysis=analysis,
                contributions=contributions,
                evidence_records=evidence_records,
                findings=findings,
            )
        )
        return FindingAuthoringResult(
            analysis=published,
            finding=authored_finding,
        )

    def _build_finding(
        self,
        *,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        target_analysis_version: int,
        statement: str | None,
        assertion_strength: str | None,
        supporting_evidence_ids: tuple[str, ...],
        contradicting_evidence_ids: tuple[str, ...],
        context_evidence_ids: tuple[str, ...],
        condition_boundary_evidence_ids: tuple[str, ...],
        limitations: tuple[str, ...],
        parent_finding_id: str | None,
        created_by_user_id: str,
        created_by_tool_call_id: str | None,
        created_at: datetime,
        evidence_records: tuple[ObjectiveEvidence, ...],
        contributions: tuple[PaperContribution, ...],
        source_findings: tuple[Finding, ...],
        display_rank: int,
    ) -> Finding:
        statement = (statement or "").strip()
        if not statement:
            raise ValueError("Finding statement is required")
        if assertion_strength not in FINDING_ASSERTION_STRENGTHS:
            raise ValueError("Finding assertion strength is required")
        role_ids = {
            "supporting": self._unique_ids(supporting_evidence_ids),
            "contradicting": self._unique_ids(contradicting_evidence_ids),
            "context": self._unique_ids(context_evidence_ids),
        }
        if not role_ids["supporting"]:
            raise ValueError("Finding requires supporting Evidence")
        if (
            set(role_ids["supporting"]) & set(role_ids["contradicting"])
            or set(role_ids["supporting"]) & set(role_ids["context"])
            or set(role_ids["contradicting"]) & set(role_ids["context"])
        ):
            raise ValueError("Evidence can have only one Finding role")
        boundary_ids = self._unique_ids(condition_boundary_evidence_ids)
        selected_ids = {
            *role_ids["supporting"],
            *role_ids["contradicting"],
            *role_ids["context"],
        }
        if not set(boundary_ids) <= selected_ids:
            raise ValueError("condition-boundary Evidence must have a Finding role")

        evidence_by_id = {item.evidence_id: item for item in evidence_records}
        missing_ids = selected_ids - set(evidence_by_id)
        if missing_ids:
            raise ValueError(
                "Evidence was not found in the source analysis: "
                + ", ".join(sorted(missing_ids))
            )
        ineligible_ids = {
            evidence_id
            for evidence_id in selected_ids
            if not evidence_by_id[evidence_id].supports_finding
        }
        if ineligible_ids:
            raise ValueError(
                "Evidence is not eligible for a Finding: "
                + ", ".join(sorted(ineligible_ids))
            )
        if parent_finding_id is not None and parent_finding_id not in {
            item.finding_id for item in source_findings
        }:
            raise ValueError("parent Finding was not found in the source analysis")

        supporting = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in role_ids["supporting"]
        )
        first = supporting[0]
        if first.reported_result is None:
            raise ValueError("supporting Evidence requires a reported result")
        context = tuple(
            evidence_by_id[evidence_id] for evidence_id in role_ids["context"]
        )
        statement_warnings = self._statement_support_warnings(
            statement=statement,
            assertion_strength=assertion_strength,
            supporting_evidence=supporting,
            contextual_evidence=context,
        )
        factors = tuple(item.name for item in first.changed_variables)
        paper_bindings = tuple(
            FindingPaperContribution(
                document_id=contribution.document_id,
                analysis_status=contribution.analysis_status,
                supporting_evidence_ids=self._for_document(
                    role_ids["supporting"],
                    contribution.document_id,
                    evidence_by_id,
                ),
                contradicting_evidence_ids=self._for_document(
                    role_ids["contradicting"],
                    contribution.document_id,
                    evidence_by_id,
                ),
                context_evidence_ids=self._for_document(
                    role_ids["context"],
                    contribution.document_id,
                    evidence_by_id,
                ),
                condition_boundary_evidence_ids=self._for_document(
                    boundary_ids,
                    contribution.document_id,
                    evidence_by_id,
                ),
            )
            for contribution in contributions
        )
        synthesis_status = Finding.synthesis_status_for(paper_bindings)
        contradicting = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in role_ids["contradicting"]
        )
        finding = Finding(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=target_analysis_version,
            finding_id=f"finding_manual_{uuid4().hex[:16]}",
            statement=statement,
            factors=factors,
            outcome=first.reported_result.outcome,
            direction=first.reported_result.direction,
            assertion_strength=assertion_strength,
            attribution_scope=Finding.attribution_scope_for(factors, supporting),
            synthesis_status=synthesis_status,
            certainty=Finding.certainty_for(
                synthesis_status, supporting + contradicting
            ),
            display_rank=display_rank,
            mechanisms=(),
            scientific_context=Finding.common_scientific_context_for(supporting),
            limitations=self._clean_text(limitations),
            paper_contributions=paper_bindings,
            origin=(
                "hybrid"
                if parent_finding_id
                else (
                    "agent_authored"
                    if created_by_tool_call_id
                    else "human_authored"
                )
            ),
            source_analysis_version=source_analysis_version,
            parent_finding_id=parent_finding_id,
            created_by_user_id=created_by_user_id,
            created_by_tool_call_id=created_by_tool_call_id,
            created_at=created_at,
            warnings=statement_warnings,
        )
        finding.validate_sources(evidence_records, contributions)
        return finding

    @staticmethod
    def _statement_support_warnings(
        *,
        statement: str,
        assertion_strength: str,
        supporting_evidence: tuple[ObjectiveEvidence, ...],
        contextual_evidence: tuple[ObjectiveEvidence, ...],
    ) -> tuple[str, ...]:
        """Report advisory wording mismatches without rejecting authored claims.

        Deep Path authors are allowed to record an interpretation that still
        needs review. The exact Source and structured Evidence bindings are
        enforced elsewhere; these lexical checks only help the reviewer spot
        claims that may exceed those bindings.
        """

        first = supporting_evidence[0]
        result = first.reported_result
        if result is None:
            raise ValueError("supporting Evidence requires a reported result")
        warnings: list[str] = []
        missing_terms = [
            term
            for term in (*tuple(item.name for item in first.changed_variables), result.outcome)
            if not property_matching.source_text_mentions_axis(statement, term)
        ]
        if missing_terms:
            warnings.append(
                "Finding statement does not mention selected Evidence axis "
                "terms: "
                + ", ".join(repr(item) for item in missing_terms)
            )

        statement_numbers = _scientific_numbers(statement)
        if statement_numbers:
            grounded_numbers = frozenset(
                number
                for evidence in (*supporting_evidence, *contextual_evidence)
                for number in _evidence_claim_numbers(evidence)
            )
            unsupported_numbers = statement_numbers - grounded_numbers
            if unsupported_numbers:
                warnings.append(
                    "Finding statement contains numeric values not present in "
                    "selected Evidence: "
                    + ", ".join(str(item) for item in sorted(unsupported_numbers))
                )
        unsupported_measurements = _scientific_measurements(statement) - frozenset(
            measurement
            for evidence in (*supporting_evidence, *contextual_evidence)
            for measurement in _evidence_claim_measurements(evidence)
        )
        if unsupported_measurements:
            warnings.append(
                "Finding statement contains value/unit pairs not present in "
                "selected Evidence: "
                + ", ".join(
                    f"{value} {unit}"
                    for value, unit in sorted(unsupported_measurements)
                )
            )

        observed_direction = _statement_outcome_direction(
            statement,
            outcome=result.outcome,
        )
        if observed_direction is not None and observed_direction != result.direction:
            warnings.append(
                "Finding statement direction "
                f"{observed_direction!r} conflicts with Evidence direction "
                f"{result.direction!r}"
            )
        if assertion_strength != "causal" and _CAUSAL_STATEMENT_PATTERN.search(
            statement
        ):
            warnings.append(
                "Finding statement uses causal wording while assertion strength "
                f"is {assertion_strength!r}"
            )
        return tuple(dict.fromkeys(warnings))

    @staticmethod
    def _validate_abstention(
        *,
        statement: str | None,
        assertion_strength: str | None,
        selected_ids: tuple[str, ...],
        parent_finding_id: str | None,
        limitations: tuple[str, ...],
    ) -> None:
        if statement or assertion_strength or selected_ids or parent_finding_id:
            raise ValueError(
                "an abstention cannot contain a Finding statement or Evidence roles"
            )
        if not FindingAuthoringService._clean_text(limitations):
            raise ValueError("authored abstention requires an explanation")

    async def _all_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Finding, ...]:
        records: list[Finding] = []
        while True:
            page, total = await self.objective_repository.list_findings(
                collection_id,
                objective_id,
                analysis_version,
                offset=len(records),
                limit=_PAGE_SIZE,
            )
            records.extend(page)
            if len(records) >= total:
                return tuple(records)
            if not page:
                raise RuntimeError("Finding pagination ended before total")

    async def _all_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[ObjectiveEvidence, ...]:
        records: list[ObjectiveEvidence] = []
        while True:
            page, total = await self.objective_repository.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                offset=len(records),
                limit=_PAGE_SIZE,
            )
            records.extend(page)
            if len(records) >= total:
                return tuple(records)
            if not page:
                raise RuntimeError("Evidence pagination ended before total")

    @staticmethod
    def _for_document(
        evidence_ids: tuple[str, ...],
        document_id: str,
        evidence_by_id: dict[str, ObjectiveEvidence],
    ) -> tuple[str, ...]:
        return tuple(
            evidence_id
            for evidence_id in evidence_ids
            if evidence_by_id[evidence_id].document_id == document_id
        )

    @staticmethod
    def _unique_ids(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _clean_text(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _scientific_numbers(value: object) -> frozenset[Decimal]:
    result: set[Decimal] = set()
    text = str(value or "").replace("\u2212", "-")
    for match in _NUMBER_PATTERN.finditer(text):
        # Page/table/figure locators are citation metadata, not scientific
        # values. Excluding them keeps advisory wording checks focused on
        # measurements while preserving the original authored statement.
        if _LOCATOR_PREFIX_PATTERN.search(text[: match.start()]):
            continue
        token = match.group(0)
        if "," in token and "." not in token:
            integer, fraction = token.rsplit(",", 1)
            token = (
                f"{integer}.{fraction}"
                if 0 < len(fraction) <= 2
                else token.replace(",", "")
            )
        else:
            token = token.replace(",", "")
        try:
            result.add(Decimal(token).normalize())
        except InvalidOperation:
            continue
    return frozenset(result)


def _evidence_claim_numbers(evidence: ObjectiveEvidence) -> frozenset[Decimal]:
    values: list[object] = []
    for variable in evidence.changed_variables:
        values.extend((variable.baseline_value, variable.target_value))
    if evidence.comparison is not None:
        values.extend(
            (evidence.comparison.baseline_label, evidence.comparison.target_label)
        )
    if evidence.reported_result is not None:
        values.extend(
            (
                evidence.reported_result.value,
                evidence.reported_result.baseline_value,
                evidence.reported_result.target_value,
            )
        )
    for category in ("material", "sample", "process", "test"):
        values.extend(
            attribute.value
            for attribute in getattr(evidence.scientific_context, category)
        )
    return frozenset(
        number for value in values for number in _scientific_numbers(value)
    )


def _scientific_measurements(value: object) -> frozenset[tuple[Decimal, str]]:
    measurements: set[tuple[Decimal, str]] = set()
    for match in _MEASUREMENT_PATTERN.finditer(str(value or "").replace("\u2212", "-")):
        unit = _normalized_unit(match.group("unit"))
        if not _looks_like_unit(match.group("unit")):
            continue
        numbers = _scientific_numbers(match.group("number"))
        if len(numbers) == 1 and unit:
            measurements.add((next(iter(numbers)), unit))
    return frozenset(measurements)


def _evidence_claim_measurements(
    evidence: ObjectiveEvidence,
) -> frozenset[tuple[Decimal, str]]:
    measurements: set[tuple[Decimal, str]] = set()

    def add(value: object, unit: str | None) -> None:
        normalized_unit = _normalized_unit(unit)
        if value is None or not normalized_unit:
            return
        measurements.update(
            (number, normalized_unit) for number in _scientific_numbers(value)
        )

    for variable in evidence.changed_variables:
        add(variable.baseline_value, variable.unit)
        add(variable.target_value, variable.unit)
    if evidence.comparison is not None:
        measurements.update(
            _scientific_measurements(evidence.comparison.baseline_label)
        )
        measurements.update(
            _scientific_measurements(evidence.comparison.target_label)
        )
    if evidence.reported_result is not None:
        add(evidence.reported_result.value, evidence.reported_result.unit)
        add(evidence.reported_result.baseline_value, evidence.reported_result.unit)
        add(evidence.reported_result.target_value, evidence.reported_result.unit)
    for category in ("material", "sample", "process", "test"):
        for attribute in getattr(evidence.scientific_context, category):
            add(attribute.value, attribute.unit)
    return frozenset(measurements)


def _normalized_unit(value: object) -> str:
    return re.sub(
        r"\s+",
        "",
        str(value or "").replace("\u03bc", "u").replace("\u00b5", "u").replace("\u00b0", "").casefold(),
    )


def _looks_like_unit(value: object) -> bool:
    unit = str(value or "").strip()
    normalized = _normalized_unit(unit)
    return bool(
        "%" in unit
        or "\u00b0" in unit
        or "/" in unit
        or "\u00b7" in unit
        or any(character.isupper() for character in unit)
        or normalized
        in {
            "c",
            "k",
            "h",
            "hz",
            "min",
            "rpm",
            "s",
            "um",
            "mm",
            "cm",
            "nm",
            "cycles",
        }
    )


def _statement_outcome_direction(statement: str, *, outcome: str) -> str | None:
    words = re.findall(r"[a-z0-9_]+", statement.casefold().replace("-", "_"))
    outcome_words = re.findall(r"[a-z0-9_]+", outcome.casefold().replace("-", "_"))
    if not words or not outcome_words:
        return None
    positions = [
        index
        for index in range(len(words) - len(outcome_words) + 1)
        if words[index : index + len(outcome_words)] == outcome_words
    ]
    if not positions:
        return None
    position = positions[-1]
    nearby = set(
        words[max(0, position - 4) : position + len(outcome_words) + 4]
    )
    directions = {
        direction
        for direction, terms in _DIRECTION_TERMS.items()
        if nearby & terms
    }
    return next(iter(directions)) if len(directions) == 1 else None


__all__ = ["FindingAuthoringResult", "FindingAuthoringService"]
