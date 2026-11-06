"""Independent, non-executable contracts for a future knowledge retriever."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bioagent.knowledge.retrieval_models import SearchResponse

_CREDENTIAL_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "key",
        "password",
        "secret",
        "signature",
        "sig",
        "token",
        "refresh_token",
        "session_token",
        "client_secret",
        "x_api_key",
        "x_amz_credential",
        "x_amz_security_token",
        "x_amz_signature",
    }
)


class _KnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class KnowledgeQuery(_KnowledgeRecord):
    """Text-only RAG input; it is not a catalog query or workflow action."""

    text: str = Field(min_length=2, max_length=4096, strict=True)


class KnowledgeEvidence(_KnowledgeRecord):
    """A cited document fragment, never a Dataset or executable instruction."""

    document_id: str = Field(min_length=1, max_length=512, strict=True)
    chunk_id: str = Field(min_length=1, max_length=512, strict=True)
    source_uri: str = Field(min_length=1, max_length=4096, strict=True)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)

    @field_validator("source_uri")
    @classmethod
    def source_uri_must_be_secure_and_credential_free(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            query_names = {
                name.casefold().replace("-", "_")
                for value in (parsed.query, parsed.fragment)
                for name, _ in parse_qsl(value, keep_blank_values=True)
            }
        except ValueError as error:
            raise ValueError("source URI must be a valid credential-free HTTPS URI") from error
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or _CREDENTIAL_FIELD_NAMES.intersection(query_names)
        ):
            raise ValueError("source URI must be a credential-free HTTPS URI")
        return value


class KnowledgeRetriever(Protocol):
    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]: ...


class LocalKnowledgeRetriever(Protocol):
    """Explicit scoped v2 extension; never coerces local references into HTTPS evidence."""

    def search(self, query: str, base_ids: list[str], top_k: int = 6) -> SearchResponse: ...


class KnowledgeRetrievalError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class NullKnowledgeRetriever:
    """Explicit default until a separately configured RAG implementation exists."""

    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]:
        del query
        raise KnowledgeRetrievalError("RAG_NOT_CONFIGURED")


__all__ = [
    "KnowledgeEvidence",
    "KnowledgeQuery",
    "KnowledgeRetrievalError",
    "KnowledgeRetriever",
    "LocalKnowledgeRetriever",
    "NullKnowledgeRetriever",
]
