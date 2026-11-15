"""Lens transport for the user-service contract; no local permission cache."""

from __future__ import annotations

import os
from pathlib import Path

import grpc
from lens.user.v1 import auth_pb2, auth_pb2_grpc


SESSION_COOKIE_NAME = "lens_session"

# declares an exception type for a session that is missing or not authenticated
class SessionNotFoundError(RuntimeError):
    pass

# declares a separate exception type for failures to obtain a usable identity
class IdentityUnavailableError(RuntimeError):
    pass


# declares the client class that groups channel setup, clearnup, RPC err translation, and session resolution
class IdentityClient:
    def __init__(self) -> None:
        # builds the TLS credentials used by hte secure channel
        credentials = grpc.ssl_channel_credentials(
            root_certificates=Path(os.environ["USER_RPC_CA"]).read_bytes(),
            private_key=Path(os.environ["USER_RPC_KEY"]).read_bytes(),
            certificate_chain=Path(os.environ["USER_RPC_CERT"]).read_bytes(),
        )

        # creates an asynchronous secure gRPC channel for the identity service and saves it on the instance
        self.channel = grpc.aio.secure_channel(
            os.environ["USER_RPC_TARGET"], credentials
        )

        # creates the identity-service stub using the channel and stores it as `self.stub`
        self.stub = auth_pb2_grpc.IdentityStub(self.channel)

    # defines an asynchoronous cleanup method for an instance
    async def close(self) -> None:
        await self.channel.close()

    # defines a shared asynchronous wrapper for invoking an RPC
    async def _call(self, rpc, message):
        # try
        try:
            # sends `message` through the supplied `rpc`
            return await rpc(message, timeout=1.0)
        # except
        except grpc.aio.AioRpcError as exc:
            if exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                raise SessionNotFoundError("authentication_required") from exc
            raise IdentityUnavailableError("identity_unavailable") from exc

    # defines the public asynchronous operation that turns a session token into selected identity fields
    async def resolve_session(self, token: str | None) -> dict[str, str]:
        if not token:
            raise SessionNotFoundError("authentication_required")

        user = await self._call(
            self.stub.Resolve,
            auth_pb2.ResolveRequest(session_token=token)
        )

        if not user.user_id:
            raise IdentityUnavailableError("invalid_identity_response")

        return {
            "user_id": user.user_id,
            "email": user.email,
            "display_name": user.display_name,
        }

    async def check(self, token: str | None, permission_code: str) -> bool:
        if not token:
            raise SessionNotFoundError("authentication_required")
        result = await self._call(
            self.stub.Check,
            auth_pb2.CheckRequest(session_token=token, permission_code=permission_code),
        )
        return result.allowed


Client: IdentityClient
