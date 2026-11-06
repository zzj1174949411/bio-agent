"""Small allowlisted diagnostics; never serialize an exception or response body."""

import re
from typing import Literal

import httpx
from ollama import ResponseError
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ModelDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["preparing", "chat", "retrieving", "generating", "validating", "probe"]
    exception_category: Literal[
        "timeout", "connection", "http", "validation", "protocol", "internal"
    ]
    http_status: int | None = Field(default=None, ge=100, le=599)
    request_id: str | None = Field(default=None, pattern=r"^(?:req_)?[0-9a-f]{32}$")


def http_status(error: Exception) -> int | None:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    if isinstance(error, (APIStatusError, ResponseError)):
        return error.status_code
    return None


def diagnose(
    error: Exception,
    stage: Literal["preparing", "chat", "retrieving", "generating", "validating", "probe"],
) -> ModelDiagnostic:
    category: Literal["timeout", "connection", "http", "validation", "protocol", "internal"] = (
        "internal"
    )
    if isinstance(error, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
        category = "timeout"
    elif isinstance(error, (httpx.NetworkError, APIConnectionError, ConnectionError)):
        category = "connection"
    elif http_status(error) is not None:
        category = "http"
    elif isinstance(error, ValidationError):
        category = "validation"
    elif isinstance(error, NotImplementedError):
        category = "protocol"
    # Only known SDK attributes/headers, and only opaque fixed-format hex IDs.
    value = None
    if isinstance(error, APIStatusError):
        value = error.request_id
    elif isinstance(error, httpx.HTTPStatusError):
        value = error.response.headers.get("x-request-id")
    request_id = (
        value if isinstance(value, str) and re.fullmatch(r"(?:req_)?[0-9a-f]{32}", value) else None
    )
    status = http_status(error)
    return ModelDiagnostic(
        stage=stage,
        exception_category=category,
        http_status=status if status is not None and 100 <= status <= 599 else None,
        request_id=request_id,
    )
