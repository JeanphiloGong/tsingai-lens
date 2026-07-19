from __future__ import annotations

from domain.core import ResearchUnderstanding
from infra.persistence.sqlite import SqliteResearchUnderstandingRepository


def test_sqlite_research_understanding_repository_owns_only_understandings(tmp_path):
    repository = SqliteResearchUnderstandingRepository(tmp_path / "lens.sqlite")

    assert not hasattr(repository, "read_confirmed_goal")
    assert not hasattr(repository, "replace_collection_facts")
    assert not hasattr(repository, "read_collection_facts")


def test_sqlite_research_understanding_repository_round_trips_understandings(tmp_path):
    repository = SqliteResearchUnderstandingRepository(tmp_path / "lens.sqlite")
    objective_understanding = ResearchUnderstanding.from_mapping(
        {
            "state": "ready",
            "scope": {
                "scope_type": "objective",
                "collection_id": "col_test",
                "objective_id": "obj_strength",
                "title": "How does heat treatment affect strength?",
            },
            "claims": [
                {
                    "claim_id": "claim_strength",
                    "claim_type": "finding",
                    "statement": "Heat treatment improves strength.",
                    "status": "supported",
                    "evidence_ref_ids": ["ev_strength"],
                }
            ],
            "evidence_refs": [
                {
                    "evidence_ref_id": "ev_strength",
                    "source_kind": "table",
                    "document_id": "doc-1",
                    "label": "P001 Table 1",
                    "locator": {"source_ref": "Table 1"},
                    "fact_ids": ["oeu-strength"],
                    "traceability_status": "resolved",
                }
            ],
        }
    )
    material_understanding = ResearchUnderstanding.from_mapping(
        {
            "state": "limited",
            "scope": {
                "scope_type": "material",
                "collection_id": "col_test",
                "material_id": "mat-316l",
                "title": "316L stainless steel",
            },
            "claims": [
                {
                    "claim_id": "claim_density",
                    "claim_type": "measurement",
                    "statement": "Density is reported as 99%.",
                    "status": "limited",
                }
            ],
        }
    )

    repository.upsert_research_understanding("col_test", objective_understanding)
    repository.upsert_research_understanding("col_test", material_understanding)

    restored = repository.read_research_understanding(
        "col_test",
        "objective",
        "obj_strength",
    )
    listed = repository.list_research_understandings("col_test", "material")

    assert restored is not None
    assert restored.scope.objective_id == "obj_strength"
    assert restored.claims[0].statement == "Heat treatment improves strength."
    assert restored.evidence_refs[0].locator == {"source_ref": "Table 1"}
    assert [item.scope.material_id for item in listed] == ["mat-316l"]

    repository.replace_collection_research_understandings(
        "col_test",
        (material_understanding,),
    )

    assert (
        repository.read_research_understanding("col_test", "objective", "obj_strength")
        is None
    )
    assert len(repository.list_research_understandings("col_test")) == 1
