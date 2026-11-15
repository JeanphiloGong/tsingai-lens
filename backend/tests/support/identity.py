"""Synthetic subject fixtures. Real credentials/mTLS are checked by checkpoints/v4."""

from hashlib import sha256
from infra.identity.client import SessionNotFoundError


class IdentitySubjects:
    def __init__(self):
        self.users = {}
        self.tokens = {}

    async def create_subject(self, *, email, display_name=None):
        user = {
            "user_id": "user_" + sha256(email.encode()).hexdigest()[:12],
            "email": email,
            "display_name": display_name,
        }
        self.users[email] = user
        return user

    async def issue_session(self, *, email):
        user = self.users.get(email)
        if user is None:
            user = await self.create_subject(email=email)
        token = "fixture:" + email
        self.tokens[token] = user
        return {"session_id": token, "user": user}

    async def resolve_session(self, token):
        if token in self.tokens:
            return self.tokens[token]
        if not token or not token.startswith("fixture:"):
            raise SessionNotFoundError("authentication_required")
        email = token.removeprefix("fixture:")
        return {
            "user_id": "user_" + sha256(email.encode()).hexdigest()[:12],
            "email": email,
            "display_name": None,
        }

    async def close(self):
        return None


subjects = IdentitySubjects()
