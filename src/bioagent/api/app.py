from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from bioagent.api.dependencies import build_dependencies
from bioagent.api.local_access import LocalAccessMiddleware, is_workbench_path
from bioagent.api.model_routes import router as model_router
from bioagent.api.routes import router
from bioagent.api.workbench_routes import router as workbench_router
from bioagent.config import Settings
from bioagent.models.profiles import ModelError


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


class FrontendStaticFiles(StaticFiles):
    """Serve the built SPA with cache policy that cannot retain an old index."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404 or "." in Path(path).name:
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("text/html"):
                response.headers["Cache-Control"] = "no-store"
            elif re.search(r"-[0-9a-f]{6,}\.", path, flags=re.IGNORECASE):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-store"
        return response


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
            await app.state.dependencies.turn_service.start()
            try:
                yield
            finally:
                await app.state.dependencies.turn_service.close()

    app = FastAPI(title="Bio-Agent API", version="0.1.0", lifespan=lifespan)
    app.state.csrf_token = token_urlsafe(32)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        if is_workbench_path(request.url.path):
            # Pydantic errors include raw inputs by default, including malformed keys.
            return JSONResponse({"detail": {"code": "REQUEST_INVALID"}}, status_code=422)
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(ValidationError)
    async def profile_validation_error(request: Request, error: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": {"code": "PROFILE_INVALID"}}, status_code=422)

    @app.exception_handler(ModelError)
    async def model_error(request: Request, error: ModelError) -> JSONResponse:
        codes = {
            "PROFILE_READ_ONLY": 409,
            "PROFILE_REVISION_CONFLICT": 409,
            "PROFILE_INVALID": 422,
            "INVALID_LIMIT": 422,
            "INVALID_CURSOR": 422,
            "CREDENTIAL_INVALID": 422,
            "MODEL_NOT_CONFIGURED": 404,
            "SECRET_STORE_UNAVAILABLE": 503,
        }
        code = error.code if error.code in codes else "MODEL_UNAVAILABLE"
        return JSONResponse({"detail": {"code": code}}, status_code=codes.get(code, 503))

    @app.exception_handler(ValueError)
    async def workbench_error(request: Request, error: ValueError) -> JSONResponse:
        if not request.url.path.startswith("/api/v1/workbench/"):
            raise error
        codes = {
            "TURN_BUSY": 409,
            "REQUEST_ID_CONFLICT": 409,
            "INPUT_RESPONSE_CONFLICT": 409,
            "TURN_QUEUE_FULL": 429,
            "TURN_SERVICE_UNAVAILABLE": 503,
            "MODEL_NOT_CONFIGURED": 409,
            "TURN_NOT_FOUND": 404,
            "CONVERSATION_NOT_FOUND": 404,
            "PROJECT_NOT_FOUND": 404,
            "DATASET_NOT_FOUND": 404,
            "INVALID_CURSOR": 422,
            "INVALID_LIMIT": 422,
            "MESSAGE_REQUIRED": 422,
            "MESSAGE_TOO_LARGE": 422,
        }
        code = error.args[0] if error.args and isinstance(error.args[0], str) else "REQUEST_INVALID"
        code = code if code in codes else "REQUEST_INVALID"
        return JSONResponse({"detail": {"code": code}}, status_code=codes.get(code, 422))

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
    app.add_middleware(
        LocalAccessMiddleware,
        allowed_hosts=configured_settings.local_allowed_hosts,
        dev_origin=configured_settings.local_dev_origin,
        csrf_token=app.state.csrf_token,
    )
    app.include_router(router)
    app.include_router(model_router)
    app.include_router(workbench_router)

    @app.api_route(
        "/api",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    async def unknown_api_path() -> JSONResponse:
        return JSONResponse({"detail": {"code": "NOT_FOUND"}}, status_code=404)

    static_value = dict(overrides or {}).get("static_dir")
    project_root = Path(__file__).resolve().parents[3]
    static_dir = (
        Path(static_value)
        if isinstance(static_value, (str, Path))
        else project_root / "frontend" / "dist"
    )
    if static_dir.is_dir():
        app.mount("/", FrontendStaticFiles(directory=static_dir, html=True), name="frontend")
    else:

        @app.get("/{path:path}", include_in_schema=False)
        async def missing_frontend(path: str) -> HTMLResponse:
            return HTMLResponse(
                "<h1>Frontend build is missing</h1>"
                "<p>Run <code>npm run build</code> in frontend.</p>",
                status_code=503,
            )

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
