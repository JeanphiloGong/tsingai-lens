from __future__ import annotations

from domain.core.research_objective import (
    OBJECTIVE_CONFIRMATION_STATUSES,
    OBJECTIVE_ORIGINS,
    ResearchObjective,
    build_research_objective_id,
    normalize_objective_terms,
)

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.objective_candidate import (
    CreateObjectiveCandidateCapability,
    CreateObjectiveCandidateToolRequest,
)
from application.core.objectives.objective_authoring_service import (
    ObjectiveAuthoringService,
)
from domain.core import ResearchObjective
from repositories.objective_repository import ObjectiveRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _CollectionService:
    async def get_collection_for_user(self, collection_id: str, user_id: str) -> dict:
        assert (collection_id, user_id) == ("col-1", "user-1")
        return {"collection_id": collection_id}

    async def get_document(self, collection_id: str, document_id: str) -> SimpleNamespace:
        assert collection_id == "col-1"
        return SimpleNamespace(document_id=document_id)


class _ObjectiveAuthoringService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_chat_assisted_candidate(self, **kwargs) -> ResearchObjective:
        self.calls.append(kwargs)
        return ResearchObjective(
            collection_id=kwargs.get("collection_id", None) or "",
            objective_id="objective-derived",
            question=kwargs.get("question", None) or "",
            material_scope=normalize_objective_terms(
                kwargs.get('material_scope', ())
            ),
            variables=normalize_objective_terms(kwargs.get('variables', ())),
            outcomes=normalize_objective_terms(kwargs.get('outcomes', ())),
            mechanisms=normalize_objective_terms(kwargs.get('mechanisms', ())),
            constraints=normalize_objective_terms(kwargs.get('constraints', ())),
            requested_comparator=kwargs.get("requested_comparator", None),
            seed_document_ids=normalize_objective_terms(
                kwargs.get('seed_document_ids', ())
            ),
            excluded_document_ids=normalize_objective_terms(
                kwargs.get('excluded_document_ids', ())
            ),
            confidence=0.0,
            reason=kwargs.get("reason", None),
            source_relationship_ids=normalize_objective_terms(
                kwargs.get('source_relationship_ids', ())
            ),
            parent_objective_id=kwargs.get("parent_objective_id", None),
            parent_analysis_version=kwargs.get("parent_analysis_version", None),
            derivation_basis=tuple(kwargs.get("derivation_basis", None) or ()),
            rank=kwargs.get("rank", None),
            confirmation_status=kwargs.get("confirmation_status", None),
            active_analysis_version=kwargs.get("active_analysis_version", None),
            published_analysis_version=kwargs.get("published_analysis_version", None),
            origin="chat_assisted",
            created_by_user_id=kwargs["user_id"],
            created_by_tool_call_id=kwargs["tool_call_id"],
        )


class _ParentObjectiveRepository:
    def __init__(self, published_version: int = 3) -> None:
        self.parent = ResearchObjective(
            collection_id="col-1",
            objective_id="objective-parent",
            question="How does preheating affect elongation?",
            material_scope=(),
            variables=("preheating",),
            outcomes=("elongation",),
            mechanisms=(),
            constraints=(),
            requested_comparator=None,
            seed_document_ids=(),
            excluded_document_ids=(),
            confidence=0.0,
            reason=None,
            confirmation_status="confirmed",
            active_analysis_version=published_version,
            published_analysis_version=published_version,
        )
        self.finding = SimpleNamespace(
            finding_id="finding-1",
            statement=(
                "Canonical Finding: preheating changes elongation under the "
                "tested conditions."
            ),
        )
        self.evidence = SimpleNamespace(
            evidence_id="evidence-gap-1",
            document_id="paper-1",
            source_kind="text_window",
            source_ref="results-1",
            selection_status="extracted",
            evidence_status="needs_context",
            evidence_status_reason=(
                "The Source reports elongation but omits the intermediate range."
            ),
        )
        self.contribution = SimpleNamespace(
            document_id="paper-1",
            analysis_status="analyzed",
            evidence_disposition="no_comparable_evidence",
            evidence_disposition_reason=(
                "The paper reports a result without a directly comparable range."
            ),
        )
        self.created: list[ResearchObjective] = []

    async def read_objective(self, collection_id: str, objective_id: str):
        if (collection_id, objective_id) == ("col-1", "objective-parent"):
            return self.parent
        return None

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective:
        self.created.append(objective)
        return objective

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ):
        if (
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        ) == ("col-1", "objective-parent", 3, self.finding.finding_id):
            return self.finding
        return None

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ):
        records = (
            (self.evidence,)
            if (collection_id, objective_id, analysis_version)
            == ("col-1", "objective-parent", 3)
            else ()
        )
        return records[offset : offset + limit], len(records)

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ):
        if (collection_id, objective_id, analysis_version) == (
            "col-1",
            "objective-parent",
            3,
        ):
            return (self.contribution,)
        return ()


class _ParentExperimentProjection:
    def __init__(self, repository: _ParentObjectiveRepository) -> None:
        self.finding = repository.finding
        self.evidence = repository.evidence
        self.contribution = repository.contribution

    async def read_finding(
        self, collection_id, objective_id, analysis_version, finding_id
    ):
        assert (collection_id, objective_id, analysis_version, finding_id) == (
            "col-1",
            "objective-parent",
            3,
            "finding-1",
        )
        return self.finding

    async def list_evidence(
        self,
        collection_id,
        objective_id,
        analysis_version,
        *,
        finding_id=None,
        offset=0,
        limit=500,
    ):
        assert finding_id is None
        records = (
            (self.evidence,)
            if (collection_id, objective_id, analysis_version)
            == ("col-1", "objective-parent", 3)
            else ()
        )
        return records[offset : offset + limit], len(records)

    async def list_contributions(self, collection_id, objective_id, analysis_version):
        if (collection_id, objective_id, analysis_version) == (
            "col-1",
            "objective-parent",
            3,
        ):
            return (self.contribution,)
        return ()


def _context() -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        session_id="chat-1",
        user_id="user-1",
        collection_id="col-1",
        tool_call_id="call-derived",
    )


def _lineage() -> list[dict]:
    return [
        {
            "kind": "finding",
            "reference_id": "finding-1",
            "rationale": "The published Finding leaves an intermediate condition unresolved.",
            "status": "validated",
            "snapshot": {
                "statement": "Preheating changes elongation under the tested conditions."
            },
        },
        {
            "kind": "evidence_gap",
            "reference_id": "evidence-gap-1",
            "rationale": "The current Evidence does not resolve the intermediate range.",
            "status": "validated",
            "snapshot": {
                "evidence_status": "needs_context",
                "document_id": "paper-1",
            },
        },
    ]


def _all_lineage_with_untrusted_snapshots() -> list[dict]:
    return [
        {
            "kind": "finding",
            "reference_id": "finding-1",
            "rationale": "The result motivates a narrower follow-up question.",
            "status": "caller_claimed_status",
            "snapshot": {"statement": "Invented Finding text."},
        },
        {
            "kind": "evidence_gap",
            "reference_id": "evidence-gap-1",
            "rationale": "The current Evidence leaves one condition unresolved.",
            "status": "caller_claimed_status",
            "snapshot": {"reason": "Invented gap reason."},
        },
        {
            "kind": "paper_contribution",
            "reference_id": "paper-1",
            "rationale": "The paper identifies a useful follow-up boundary.",
            "status": "caller_claimed_status",
            "snapshot": {"reason": "Invented paper disposition."},
        },
    ]


async def test_approved_derived_candidate_keeps_parent_lineage_in_service_call() -> None:
    service = _ObjectiveAuthoringService()
    capability = CreateObjectiveCandidateCapability(
        objective_authoring_service=service,
    )

    result = await capability.execute(
        _context(),
        CreateObjectiveCandidateToolRequest.model_validate(
            {
                "question": "How does intermediate preheating affect fatigue life?",
                "material_scope": ["Ti-6Al-4V"],
                "variables": ["build-plate preheating"],
                "outcomes": ["fatigue life"],
                "parent_objective_id": "objective-parent",
                "parent_analysis_version": 3,
                "derivation_basis": _lineage(),
            }
        ),
    )

    assert result.status.value == "succeeded"
    assert service.calls[0]["parent_objective_id"] == "objective-parent"
    assert service.calls[0]["parent_analysis_version"] == 3
    assert service.calls[0]["derivation_basis"] == _lineage()


async def test_derived_candidate_lineage_round_trips_through_postgres_repository(*, postgres_session_factory) -> None:
    repository = ObjectiveRepository()
    objective = ResearchObjective(
        collection_id="col-1",
        objective_id="objective-derived",
        question="How does intermediate preheating affect fatigue life?",
        material_scope=("Ti-6Al-4V",),
        variables=("build-plate preheating",),
        outcomes=("fatigue life",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        parent_objective_id="objective-parent",
        parent_analysis_version=3,
        derivation_basis=tuple(_lineage() or ()),
        origin="chat_assisted",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-derived",
    )

    await repository.create_authored_candidate(
        objective,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-derived",
    )
    restored = await repository.read_objective("col-1", "objective-derived")

    assert restored is not None
    assert restored.parent_objective_id == "objective-parent"
    assert restored.parent_analysis_version == 3
    assert restored.derivation_basis == tuple(_lineage())


async def test_authored_candidate_retry_cannot_silently_drop_new_lineage(*, postgres_session_factory) -> None:
    repository = ObjectiveRepository()
    first = ResearchObjective(
        collection_id="col-1",
        objective_id="objective-derived",
        question="How does intermediate preheating affect fatigue life?",
        material_scope=("Ti-6Al-4V",),
        variables=("build-plate preheating",),
        outcomes=("fatigue life",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        origin="chat_assisted",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-retry",
    )
    second = replace(
        first,
        parent_objective_id="objective-parent",
        parent_analysis_version=3,
        derivation_basis=tuple(_lineage()),
    )

    await repository.create_authored_candidate(
        first,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-retry",
    )
    with pytest.raises(ValueError, match="already created a different objective"):
        await repository.create_authored_candidate(
            second,
            created_by_user_id="user-1",
            created_by_tool_call_id="call-retry",
        )


async def test_authored_candidate_retry_with_same_lineage_remains_idempotent(*, postgres_session_factory) -> None:
    repository = ObjectiveRepository()
    first = ResearchObjective(
        collection_id="col-1",
        objective_id="objective-derived",
        question="How does intermediate preheating affect fatigue life?",
        material_scope=("Ti-6Al-4V",),
        variables=("build-plate preheating",),
        outcomes=("fatigue life",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        parent_objective_id="objective-parent",
        parent_analysis_version=3,
        derivation_basis=tuple(_lineage() or ()),
        origin="chat_assisted",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-idempotent",
    )
    await repository.create_authored_candidate(
        first,
        created_by_user_id="user-1",
        created_by_tool_call_id="call-idempotent",
    )

    retried = await repository.create_authored_candidate(
        replace(first, rank=None),
        created_by_user_id="user-1",
        created_by_tool_call_id="call-idempotent",
    )

    assert retried.rank == 1


def _service(*, repository: ObjectiveRepository) -> ObjectiveAuthoringService:
    return ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
    )


def _published_parent() -> ResearchObjective:
    return ResearchObjective(
        collection_id="col-1",
        objective_id="objective-parent",
        question="How does preheating affect elongation?",
        material_scope=("Ti-6Al-4V",),
        variables=("preheating",),
        outcomes=("elongation",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
        confirmation_status="confirmed",
        active_analysis_version=3,
        published_analysis_version=3,
        origin="chat_assisted",
        created_by_user_id="user-1",
        created_by_tool_call_id="call-parent",
    )


async def test_service_rejects_derived_candidate_when_parent_analysis_is_not_published(*, postgres_session_factory) -> None:
    repository = ObjectiveRepository()
    await repository.create_authored_candidate(
        _published_parent(),
        created_by_user_id="user-1",
        created_by_tool_call_id="call-parent",
    )
    service = _service(repository=repository)

    with pytest.raises(ValueError, match="analysis version is no longer published"):
        await service.create_chat_assisted_candidate(
            collection_id="col-1",
            user_id="user-1",
            tool_call_id="call-derived",
            question="How does intermediate preheating affect fatigue life?",
            material_scope=["Ti-6Al-4V"],
            variables=["preheating"],
            outcomes=["fatigue life"],
            mechanisms=[],
            constraints=[],
            requested_comparator=None,
            seed_document_ids=[],
            excluded_document_ids=[],
            parent_objective_id="objective-parent",
            parent_analysis_version=2,
            derivation_basis=_lineage(),
        )


async def test_service_persists_derived_candidate_against_published_parent() -> None:
    repository = _ParentObjectiveRepository()
    service = _service(repository=repository)

    created = await service.create_chat_assisted_candidate(
        collection_id="col-1",
        user_id="user-1",
        tool_call_id="call-derived",
        question="How does intermediate preheating affect fatigue life?",
        material_scope=["Ti-6Al-4V"],
        variables=["preheating"],
        outcomes=["fatigue life"],
        mechanisms=[],
        constraints=[],
        requested_comparator=None,
        seed_document_ids=[],
        excluded_document_ids=[],
        parent_objective_id="objective-parent",
        parent_analysis_version=3,
        derivation_basis=_all_lineage_with_untrusted_snapshots(),
    )

    assert created.parent_objective_id == "objective-parent"
    assert created.parent_analysis_version == 3
    assert created.derivation_basis == (
        {
            "kind": "finding",
            "reference_id": "finding-1",
            "rationale": "The result motivates a narrower follow-up question.",
            "status": "validated",
            "snapshot": {"statement": repository.finding.statement},
        },
        {
            "kind": "evidence_gap",
            "reference_id": "evidence-gap-1",
            "rationale": "The current Evidence leaves one condition unresolved.",
            "status": "validated",
            "snapshot": {
                "evidence_status": "needs_context",
                "reason": repository.evidence.evidence_status_reason,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": "results-1",
            },
        },
        {
            "kind": "paper_contribution",
            "reference_id": "paper-1",
            "rationale": "The paper identifies a useful follow-up boundary.",
            "status": "validated",
            "snapshot": {
                "document_id": "paper-1",
                "evidence_disposition": "no_comparable_evidence",
                "reason": repository.contribution.evidence_disposition_reason,
            },
        },
    )


async def test_derived_objective_reads_parent_basis_from_experiment_projection() -> None:
    repository = _ParentObjectiveRepository()
    projection = _ParentExperimentProjection(repository)

    async def reject_legacy_read(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("legacy scientific-fact repository was read")

    repository.read_finding = reject_legacy_read
    repository.list_evidence = reject_legacy_read
    repository.list_contributions = reject_legacy_read
    service = ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
        experiment_projection=projection,
    )

    created = await service.create_chat_assisted_candidate(
        collection_id="col-1",
        user_id="user-1",
        tool_call_id="call-experiment-derived",
        question="How does intermediate preheating affect fatigue life?",
        material_scope=["Ti-6Al-4V"],
        variables=["preheating"],
        outcomes=["fatigue life"],
        mechanisms=[],
        constraints=[],
        requested_comparator=None,
        seed_document_ids=[],
        excluded_document_ids=[],
        parent_objective_id="objective-parent",
        parent_analysis_version=3,
        derivation_basis=_all_lineage_with_untrusted_snapshots(),
    )

    assert created.derivation_basis[0]["snapshot"]["statement"].startswith(
        "Canonical Finding"
    )


@pytest.mark.parametrize(
    ("basis", "repository_change", "expected_error"),
    (
        (
            {
                "kind": "finding",
                "reference_id": "unknown-finding",
                "rationale": "A fabricated Finding must not create lineage.",
            },
            None,
            "Finding is not part of the published parent analysis",
        ),
        (
            {
                "kind": "evidence_gap",
                "reference_id": "unknown-evidence",
                "rationale": "A fabricated Evidence gap must not create lineage.",
            },
            None,
            "Evidence gap is not part of the published parent analysis",
        ),
        (
            {
                "kind": "evidence_gap",
                "reference_id": "evidence-gap-1",
                "rationale": "A technical failure is not a scientific gap.",
            },
            {
                "selection_status": "failed",
                "evidence_status": "extraction_failed",
                "evidence_status_reason": "The model request timed out.",
            },
            "technical extraction failure cannot derive an Objective",
        ),
        (
            {
                "kind": "evidence_gap",
                "reference_id": "evidence-gap-1",
                "rationale": "Rejected Evidence is not an accepted scientific gap.",
            },
            {"selection_status": "rejected"},
            "rejected Evidence cannot derive an Objective",
        ),
        (
            {
                "kind": "paper_contribution",
                "reference_id": "unknown-paper",
                "rationale": "A fabricated paper contribution must not create lineage.",
            },
            None,
            "paper contribution is not part of the published parent analysis",
        ),
        (
            {
                "kind": "paper_contribution",
                "reference_id": "paper-1",
                "rationale": "An excluded paper cannot support a follow-up question.",
            },
            {
                "analysis_status": "excluded",
                "evidence_disposition": "excluded",
            },
            "excluded or failed paper cannot derive an Objective",
        ),
        (
            {
                "kind": "paper_contribution",
                "reference_id": "paper-1",
                "rationale": "A failed paper cannot support a follow-up question.",
            },
            {
                "analysis_status": "failed",
                "evidence_disposition": "extraction_failed",
            },
            "excluded or failed paper cannot derive an Objective",
        ),
    ),
)
async def test_service_rejects_noncanonical_derivation_basis_before_persistence(
    basis: dict,
    repository_change: dict | None,
    expected_error: str,
) -> None:
    repository = _ParentObjectiveRepository()
    if repository_change:
        if basis["kind"] == "evidence_gap":
            repository.evidence = SimpleNamespace(
                **{**vars(repository.evidence), **repository_change}
            )
        else:
            repository.contribution = SimpleNamespace(
                **{**vars(repository.contribution), **repository_change}
            )
    service = _service(repository=repository)

    with pytest.raises(ValueError, match=expected_error):
        await service.create_chat_assisted_candidate(
            collection_id="col-1",
            user_id="user-1",
            tool_call_id="call-derived-invalid",
            question="How does intermediate preheating affect fatigue life?",
            material_scope=["Ti-6Al-4V"],
            variables=["preheating"],
            outcomes=["fatigue life"],
            mechanisms=[],
            constraints=[],
            requested_comparator=None,
            seed_document_ids=[],
            excluded_document_ids=[],
            parent_objective_id="objective-parent",
            parent_analysis_version=3,
            derivation_basis=[basis],
        )

    assert repository.created == []


async def test_derived_candidate_requires_the_current_published_parent_version() -> None:
    repository = _ParentObjectiveRepository(published_version=3)
    service = ObjectiveAuthoringService(
        collection_service=_CollectionService(),
        objective_repository=repository,
    )
    kwargs = {
        "collection_id": "col-1",
        "user_id": "user-1",
        "tool_call_id": "call-derived",
        "question": "How does intermediate preheating affect fatigue life?",
        "material_scope": ["Ti-6Al-4V"],
        "variables": ["preheating"],
        "outcomes": ["fatigue life"],
        "mechanisms": [],
        "constraints": [],
        "requested_comparator": None,
        "seed_document_ids": [],
        "excluded_document_ids": [],
        "parent_objective_id": "objective-parent",
        "parent_analysis_version": 3,
        "derivation_basis": _lineage(),
    }

    created = await service.create_chat_assisted_candidate(**kwargs)
    assert created.parent_objective_id == "objective-parent"
    assert repository.created

    with pytest.raises(ValueError, match="no longer published"):
        await service.create_chat_assisted_candidate(
            **{**kwargs, "tool_call_id": "call-stale", "parent_analysis_version": 2}
        )


def test_derived_objective_identity_includes_parent_analysis_lineage() -> None:
    common = {
        "collection_id": "col-1",
        "question": "How does intermediate preheating affect fatigue life?",
        "material_scope": ["Ti-6Al-4V"],
        "variables": ["build-plate preheating"],
        "outcomes": ["fatigue life"],
        "origin": "chat_assisted",
        "created_by_user_id": "user-1",
        "created_by_tool_call_id": "call-derived",
        "parent_analysis_version": 3,
        "derivation_basis": _lineage(),
    }
    first = ResearchObjective(
        collection_id=common.get("collection_id", None) or "",
        objective_id=common.get("objective_id", None)
        or build_research_objective_id(
            question=common.get("question", None) or "",
            material_scope=normalize_objective_terms(
                common.get('material_scope', ())
            ),
            variables=normalize_objective_terms(common.get('variables', ())),
            outcomes=normalize_objective_terms(common.get('outcomes', ())),
            mechanisms=normalize_objective_terms(common.get('mechanisms', ())),
            constraints=normalize_objective_terms(common.get('constraints', ())),
            requested_comparator=common.get("requested_comparator", None),
            parent_objective_id="objective-parent-a",
            parent_analysis_version=common.get("parent_analysis_version", None),
        ),
        question=common.get("question", None) or "",
        material_scope=normalize_objective_terms(common.get('material_scope', ())),
        variables=normalize_objective_terms(common.get('variables', ())),
        outcomes=normalize_objective_terms(common.get('outcomes', ())),
        mechanisms=normalize_objective_terms(common.get('mechanisms', ())),
        constraints=normalize_objective_terms(common.get('constraints', ())),
        requested_comparator=common.get("requested_comparator", None),
        seed_document_ids=normalize_objective_terms(
            common.get('seed_document_ids', ())
        ),
        excluded_document_ids=normalize_objective_terms(
            common.get('excluded_document_ids', ())
        ),
        confidence=common.get('confidence', 0.0),
        reason=common.get("reason", None),
        source_relationship_ids=normalize_objective_terms(
            common.get('source_relationship_ids', ())
        ),
        parent_objective_id="objective-parent-a",
        parent_analysis_version=common.get("parent_analysis_version", None),
        derivation_basis=tuple(common.get("derivation_basis", None) or ()),
        rank=common.get("rank", None),
        confirmation_status=common.get("confirmation_status", None),
        active_analysis_version=common.get("active_analysis_version", None),
        published_analysis_version=common.get("published_analysis_version", None),
        origin=common.get("origin", None),
        created_by_user_id=common.get("created_by_user_id", None),
        created_by_tool_call_id=common.get("created_by_tool_call_id", None),
    )
    second = ResearchObjective(
        collection_id=common.get("collection_id", None) or "",
        objective_id=common.get("objective_id", None)
        or build_research_objective_id(
            question=common.get("question", None) or "",
            material_scope=normalize_objective_terms(
                common.get('material_scope', ())
            ),
            variables=normalize_objective_terms(common.get('variables', ())),
            outcomes=normalize_objective_terms(common.get('outcomes', ())),
            mechanisms=normalize_objective_terms(common.get('mechanisms', ())),
            constraints=normalize_objective_terms(common.get('constraints', ())),
            requested_comparator=common.get("requested_comparator", None),
            parent_objective_id="objective-parent-b",
            parent_analysis_version=common.get("parent_analysis_version", None),
        ),
        question=common.get("question", None) or "",
        material_scope=normalize_objective_terms(common.get('material_scope', ())),
        variables=normalize_objective_terms(common.get('variables', ())),
        outcomes=normalize_objective_terms(common.get('outcomes', ())),
        mechanisms=normalize_objective_terms(common.get('mechanisms', ())),
        constraints=normalize_objective_terms(common.get('constraints', ())),
        requested_comparator=common.get("requested_comparator", None),
        seed_document_ids=normalize_objective_terms(
            common.get('seed_document_ids', ())
        ),
        excluded_document_ids=normalize_objective_terms(
            common.get('excluded_document_ids', ())
        ),
        confidence=common.get('confidence', 0.0),
        reason=common.get("reason", None),
        source_relationship_ids=normalize_objective_terms(
            common.get('source_relationship_ids', ())
        ),
        parent_objective_id="objective-parent-b",
        parent_analysis_version=common.get("parent_analysis_version", None),
        derivation_basis=tuple(common.get("derivation_basis", None) or ()),
        rank=common.get("rank", None),
        confirmation_status=common.get("confirmation_status", None),
        active_analysis_version=common.get("active_analysis_version", None),
        published_analysis_version=common.get("published_analysis_version", None),
        origin=common.get("origin", None),
        created_by_user_id=common.get("created_by_user_id", None),
        created_by_tool_call_id=common.get("created_by_tool_call_id", None),
    )

    assert first.objective_id != second.objective_id


@pytest.fixture(autouse=True)
async def research_records(postgres_session_factory, anyio_backend):
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col-1")
