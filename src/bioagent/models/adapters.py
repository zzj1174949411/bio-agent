"""Provider differences and an explicit, bounded, non-user-data probe."""

import asyncio
from typing import Literal, TypedDict
from uuid import UUID

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from ollama import ResponseError
from openai import APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, ValidationError

from bioagent.models.profiles import ModelError
from bioagent.models.store import ModelProfileStore


def deepseek_body() -> dict[str, object]:
    return {"thinking": {"type": "disabled"}}


def structured_options(provider: str, method: str) -> dict[str, object]:
    if provider == "deepseek":
        return {"method": "function_calling", "extra_body": deepseek_body()}
    if provider == "ollama":
        return {"method": "function_calling"}
    return {"method": method}


class ProbeOK(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: Literal[True]


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ok: bool
    code: str
    capabilities: tuple[str, ...] = ()


def error_code(error: Exception) -> str:
    if isinstance(error, ModelError):
        return (
            error.code
            if error.code in {"MODEL_NOT_CONFIGURED", "SECRET_STORE_UNAVAILABLE"}
            else "MODEL_UNAVAILABLE"
        )
    if isinstance(error, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
        return "MODEL_TIMEOUT"
    if isinstance(error, ValidationError):
        return "MODEL_OUTPUT_INVALID"
    if isinstance(error, NotImplementedError):
        return "MODEL_PROTOCOL_UNSUPPORTED"
    if isinstance(error, (APIStatusError, ResponseError, httpx.HTTPStatusError)):
        status = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else error.status_code
        )
        return {
            401: "MODEL_AUTH_FAILED",
            403: "MODEL_AUTH_FAILED",
            429: "MODEL_RATE_LIMITED",
            400: "MODEL_PROTOCOL_UNSUPPORTED",
            422: "MODEL_PROTOCOL_UNSUPPORTED",
        }.get(status, "MODEL_UNAVAILABLE")
    return "MODEL_UNAVAILABLE"


class _OpenAIOptions(TypedDict, total=False):
    extra_body: dict[str, object]


class ModelAdapter:
    def __init__(self, store: ModelProfileStore) -> None:
        self._store = store

    def create(self, identity: UUID) -> tuple[BaseChatModel, str]:
        profile, secret = self._store.request_config(identity)
        options = structured_options(profile.provider, profile.structured_method)
        if profile.provider == "ollama":
            model: BaseChatModel = ChatOllama(
                base_url=profile.base_url, model=profile.model, client_kwargs={"timeout": 60}
            )
        else:
            extra: _OpenAIOptions = (
                {"extra_body": deepseek_body()} if profile.provider == "deepseek" else {}
            )
            model = ChatOpenAI(
                api_key=secret,
                base_url=profile.base_url,
                model=profile.model,
                timeout=60,
                max_retries=0,
                **extra,
            )
        return model, str(options["method"])

    async def probe(self, identity: UUID) -> ProbeResult:
        try:
            async with asyncio.timeout(60):
                # Keyring/client construction is synchronous and never holds up the event loop.
                model, method = await asyncio.to_thread(self.create, identity)
                structured = model.with_structured_output(ProbeOK, method=method)
                output = await structured.ainvoke(
                    'Return exactly the structured object {"ok":true}.'
                )
                if isinstance(output, BaseModel):
                    output = output.model_dump()
                ProbeOK.model_validate(output)
            return ProbeResult(ok=True, code="OK", capabilities=("structured_output",))
        except Exception as error:
            return ProbeResult(ok=False, code=error_code(error))
