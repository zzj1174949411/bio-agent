"""Local browser request boundary, including credential request redaction."""

from secrets import compare_digest
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def is_workbench_path(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in ("/api/v1/model-profiles", "/api/v1/workbench", "/api/v1/geo")
    )


class LocalAccessMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: tuple[str, ...],
        dev_origin: str | None,
        csrf_token: str,
    ) -> None:
        self._app = app
        self._hosts = allowed_hosts
        self._dev_origin = dev_origin
        self._csrf = csrf_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)
        protected = is_workbench_path(scope.get("path", ""))
        # Preserve existing non-browser HTTP clients. All new endpoints and
        # browser-origin requests pass the local Host/Origin boundary below.
        if not protected and b"origin" not in headers:
            await self._app(scope, receive, send)
            return

        def one(key: bytes) -> str:
            values = headers.get(key, [])
            return values[0].decode("latin-1") if len(values) == 1 else ""

        async def reject(code: str, status: int = 403) -> None:
            await JSONResponse({"detail": {"code": code}}, status_code=status)(scope, receive, send)

        host = one(b"host")
        try:
            url = urlsplit("//" + host)
            if (
                not host
                or url.hostname not in self._hosts
                or url.username is not None
                or url.path
                or url.query
                or url.fragment
                or any(c.isspace() for c in host)
            ):
                raise ValueError
            _ = url.port
        except ValueError:
            await reject("LOCAL_HOST_REJECTED")
            return
        origin = one(b"origin")
        same_origin = f"{scope.get('scheme', 'http')}://{host}"
        if b"origin" in headers and (not origin or origin not in {same_origin, self._dev_origin}):
            await reject("LOCAL_ORIGIN_REJECTED")
            return
        if not is_workbench_path(scope.get("path", "")):
            await self._app(scope, receive, send)
            return
        if one(b"sec-fetch-site") == "cross-site":
            await reject("LOCAL_ORIGIN_REJECTED")
            return
        if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
            token = one(b"x-csrf-token")
            if not compare_digest(token.encode(), self._csrf.encode()):
                await reject("CSRF_TOKEN_REQUIRED")
                return
            # Bound the actual body, including chunked requests. Never log it.
            body = bytearray()
            path = scope.get("path", "")
            body_limit = (
                2 * 1024 * 1024
                if path == "/api/v1/geo" or path.startswith("/api/v1/geo/")
                else 32 * 1024
            )
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > body_limit:
                    await reject("REQUEST_TOO_LARGE", 413)
                    return
                if not message.get("more_body", False):
                    break
            consumed = False

            async def bounded_receive() -> Message:
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self._app(scope, bounded_receive, send)
            return
        await self._app(scope, receive, send)
