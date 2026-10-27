
from dataclasses import replace
from domain.core.comparison_group import ComparisonGroupMember
import pytest

from domain.core.comparison_group import ComparisonGroup


def _group(status: str = "conditional") -> ComparisonGroup:
    return ComparisonGroup(
        group_id='group-1',
        objective_id='obj-1',
        analysis_version=1,
        outcome='elongation',
        comparison_target='measurement',
        comparison_basis=('same material', 'same test outcome'),
        status=status,
        members=(ComparisonGroupMember(selection_id='sel-a', role='included', comparability='comparable' if status == 'comparable' else 'conditional', reason='same reported test definition'), ComparisonGroupMember(selection_id='sel-b', role='context', comparability='unknown', reason='test temperature is not reported')),
    )


def test_group_preserves_members_and_limits_without_measurement_values() -> None:
    group = _group()

    assert [item.selection_id for item in group.members] == ["sel-a", "sel-b"]
    assert "same material" in group.comparison_basis
    assert group.outcome == "elongation"


def test_comparable_group_requires_comparable_included_members() -> None:
    with pytest.raises(ValueError, match="comparable included"):
        replace(_group(), status='comparable')
