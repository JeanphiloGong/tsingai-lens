from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MemoryAuthRepository:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.user_ids_by_email: dict[str, str] = {}
        self.sessions_by_token_hash: dict[str, dict[str, Any]] = {}

    async def read_user_by_email(self, email: str) -> dict[str, Any] | None:
        user_id = self.user_ids_by_email.get(email.strip().lower())
        return dict(self.users[user_id]) if user_id is not None else None

    async def read_user(self, user_id: str) -> dict[str, Any] | None:
        user = self.users.get(user_id)
        return dict(user) if user is not None else None

    async def add_user(self, payload: Mapping[str, Any]) -> None:
        user = dict(payload)
        email = str(user["email"]).strip().lower()
        if email in self.user_ids_by_email:
            raise ValueError("user email already exists")
        user_id = str(user["user_id"])
        self.users[user_id] = user
        self.user_ids_by_email[email] = user_id

    async def read_session_by_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        session = self.sessions_by_token_hash.get(token_hash)
        return dict(session) if session is not None else None

    async def add_session(self, payload: Mapping[str, Any]) -> None:
        session = dict(payload)
        token_hash = str(session["token_hash"])
        self.sessions_by_token_hash[token_hash] = session

    async def revoke_session_by_token_hash(
        self,
        token_hash: str,
        revoked_at: str,
    ) -> None:
        session = self.sessions_by_token_hash.get(token_hash)
        if session is not None:
            session["revoked_at"] = revoked_at


@pytest.fixture(autouse=True)
def _patch_domain_model_extractors(monkeypatch):
    from application.core.document_profiles import (
        service as document_profile_service,
    )
    from application.core.objectives import research_objective_service
    from application.core.paper_facts import service as paper_facts_service
    from tests.support.fake_domain_model_extractor import FakeDomainModelExtractor

    fake = FakeDomainModelExtractor()
    monkeypatch.setattr(
        document_profile_service,
        "build_default_document_profile_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        paper_facts_service,
        "build_default_paper_facts_extractor",
        lambda: fake,
    )
    monkeypatch.setattr(
        research_objective_service,
        "build_default_structured_response_client",
        lambda: fake,
    )


@pytest.fixture
def auth_session_service(tmp_path):
    from application.auth import AuthSessionService

    return AuthSessionService(MemoryAuthRepository())


@pytest.fixture
def collection_service(tmp_path, auth_session_service):
    from application.source.collection_service import CollectionService
    from infra.persistence.file import FileCollectionWorkspace
    from infra.persistence.memory import MemoryCollectionRepository

    return CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(tmp_path / "collections"),
    )
