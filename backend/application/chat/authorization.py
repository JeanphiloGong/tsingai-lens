"""Deterministic capability authorization outside the model prompt."""

from __future__ import annotations

from dataclasses import dataclass

from domain.chat import ToolRisk


@dataclass(frozen=True)
class AuthorizationDecision:
    may_execute: bool
    requires_approval: bool = False


def evaluate_authorization(risk: ToolRisk | str) -> AuthorizationDecision:
    normalized = ToolRisk(risk)
    if normalized in {ToolRisk.READ, ToolRisk.DRAFT}:
        return AuthorizationDecision(may_execute=True)
    if normalized is ToolRisk.WRITE:
        return AuthorizationDecision(may_execute=False, requires_approval=True)
    return AuthorizationDecision(may_execute=False)


__all__ = ["AuthorizationDecision", "evaluate_authorization"]
