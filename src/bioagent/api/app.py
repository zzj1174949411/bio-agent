from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from bioagent.api.dependencies import build_dependencies
from bioagent.api.routes import router
from bioagent.config import Settings


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/datasets"
        ):
            headers = dict(scope.get("headers", []))
            raw_length = headers.get(b"content-length")
            try:
                content_length = int(raw_length) if raw_length is not None else None
            except ValueError:
                content_length = -1
            if content_length is None:
                await self._reject(scope, receive, send, 411, "CONTENT_LENGTH_REQUIRED")
                return
            if content_length < 0:
                await self._reject(scope, receive, send, 400, "INVALID_CONTENT_LENGTH")
                return
            if content_length > self._max_bytes:
                await self._reject(scope, receive, send, 413, "UPLOAD_TOO_LARGE")
                return
        await self._app(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
    ) -> None:
        body = json.dumps({"detail": {"code": code}}, separators=(",", ":")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_app(
    settings: Settings | None = None,
    overrides: Mapping[str, object] | None = None,
) -> FastAPI:
    configured_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with ExitStack() as stack:
            app.state.dependencies = build_dependencies(
                configured_settings,
                overrides=overrides,
                stack=stack,
            )
            yield

    app = FastAPI(title="Bio-Agent API", version="0.1.0", lifespan=lifespan)
    max_upload_bytes = _positive_override(
        overrides,
        "max_upload_bytes",
        10 * 1024 * 1024,
    )
    max_request_bytes = _positive_override(
        overrides,
        "max_request_bytes",
        2 * max_upload_bytes + 64 * 1024,
    )
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_request_bytes)
    app.include_router(router)
    return app


def _positive_override(
    overrides: Mapping[str, object] | None,
    name: str,
    default: int,
) -> int:
    value = dict(overrides or {}).get(name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
