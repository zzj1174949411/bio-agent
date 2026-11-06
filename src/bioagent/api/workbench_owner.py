"""Opaque browser ownership for searches initiated from a workbench conversation."""

import re
from hashlib import sha256
from secrets import token_urlsafe

from fastapi import Request, Response

_WORKBENCH_OWNER_COOKIE = "bioagent_workbench_owner"
_OWNER_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def ensure_workbench_owner(request: Request, response: Response) -> str:
    token = _workbench_owner(request)
    if token is None:
        token = token_urlsafe(32)
        response.set_cookie(
            _WORKBENCH_OWNER_COOKIE,
            token,
            httponly=True,
            samesite="strict",
        )
    return _owner_hash(token)


def workbench_owner_hash(request: Request) -> str | None:
    token = _workbench_owner(request)
    return _owner_hash(token) if token is not None else None


def _owner_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _workbench_owner(request: Request) -> str | None:
    token = request.cookies.get(_WORKBENCH_OWNER_COOKIE)
    if not isinstance(token, str) or _OWNER_TOKEN.fullmatch(token) is None:
        return None
    return token
