"""Bounded, source-backed Wiki contracts; no model-authored URLs or paths."""

import re
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from bioagent.knowledge.models import Record
from bioagent.knowledge.retrieval_models import EvaluationSource, LocalEvidence
from bioagent.models.diagnostics import ModelDiagnostic
from bioagent.models.profiles import ModelSnapshot


class BuildRequest(Record):
    model_profile_id: UUID
    max_calls: int = Field(default=32, ge=1, le=256, strict=True)
    input_max_bytes: int = Field(default=24000, ge=4000, le=64000, strict=True)
    output_max_bytes: int = Field(default=24000, ge=1000, le=64000, strict=True)
    output_token_limit: int = Field(default=2048, ge=128, le=8192, strict=True)
    max_segments_per_document: int = Field(default=8, ge=1, le=32, strict=True)
    min_context_chars: int = Field(default=0, ge=0, le=512, strict=True)
    preflight_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Coverage(Record):
    document_id: UUID
    total_chunks: int
    included_chunks: int
    filtered_short_chunks: int = Field(default=0, ge=0)
    total_text_bytes: int
    included_text_bytes: int
    total_pages: int
    included_pages: tuple[int, ...]
    segments: int
    truncated: bool


class Preflight(Record):
    base_id: UUID
    base_name: str
    document_count: int
    ready_count: int
    model_snapshot: ModelSnapshot
    profile: BuildRequest
    coverage: tuple[Coverage, ...]
    synthesis_chunks: int
    synthesis_total_chunks: int
    source_epochs: dict[str, int]
    required_calls: int
    preflight_sha256: str
    unchanged: bool
    protocol_limits_verified: Literal[False] = False
    limitations: str = (
        "Only calls and application input/output bytes are hard-limited. Provider output-token "
        "parameters have not been verified for this profile; token/cost bounds are unknown. "
        "Missing usage is unknown, never zero. No automatic retries or model fallback."
    )


class Quote(Record):
    chunk_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote: str = Field(min_length=1, max_length=4000)


class Citation(Quote):
    reference: LocalEvidence
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Claim(Record):
    text: str = Field(min_length=1, max_length=4000)
    conditions: str = Field(min_length=1, max_length=2000)
    candidate_disagreement: bool = False
    citations: tuple[Quote, ...] = Field(min_length=1, max_length=8)

    @field_validator("text", "conditions")
    @classmethod
    def plain_text(cls, value: str) -> str:
        if re.search(r"(?:https?://|file:|javascript:|<[^>]*>|[A-Za-z]:[\\/])", value, re.I):
            raise ValueError("WIKI_TEXT_INVALID")
        if not value.strip():
            raise ValueError("WIKI_TEXT_INVALID")
        return value


class Statement(Claim):
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=8)


class DraftPage(Record):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9:-]*$")
    kind: Literal["paper", "concept", "topic"]
    title: str = Field(min_length=1, max_length=200)
    statements: tuple[Claim, ...] = Field(min_length=1, max_length=32)
    links: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("title")
    @classmethod
    def plain_title(cls, value: str) -> str:
        return Claim.plain_text(value)


class Draft(Record):
    pages: tuple[DraftPage, ...] = Field(min_length=1, max_length=8)


class WikiPage(Record):
    id: UUID
    generation: UUID
    base_id: UUID
    key: str
    kind: Literal["paper", "concept", "topic"]
    title: str
    statements: tuple[Statement, ...]
    links: tuple[str, ...]
    coverage: tuple[Coverage, ...]
    status: Literal["CURRENT", "STALE"] = "CURRENT"
    ai_generated: Literal[True] = True
    human_reviewed: Literal[False] = False
    semantic_entailment_verified: Literal[False] = False
    visual_semantics: Literal["not_performed"] = "not_performed"
    generated_by: ModelSnapshot
    prompt_version: Literal["wiki-build.v1"] = "wiki-build.v1"
    schema_version: Literal["literature-wiki.v1"] = "literature-wiki.v1"


class PageList(Record):
    base_id: UUID
    generation: UUID | None = None
    items: tuple[WikiPage, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    pending_update: bool = False
    document_count: int = 0
    covered_document_count: int = 0
    synthesis_chunks: int = 0
    synthesis_total_chunks: int = 0


class WikiJob(Record):
    id: UUID
    base_id: UUID
    generation: UUID
    status: Literal["QUEUED", "BUILDING", "COMPLETED", "FAILED", "CANCELLED", "SKIPPED"]
    stage: str = "queued"
    request: BuildRequest
    snapshot: ModelSnapshot
    sources: tuple[EvaluationSource, ...]
    corpus_document_ids: tuple[UUID, ...]
    coverage: tuple[Coverage, ...]
    fingerprint: str
    input_sha256: str
    prompt_sha256: str
    schema_sha256: str
    synthesis_chunks: int
    synthesis_total_chunks: int
    source_epochs: dict[str, int]
    calls: int = 0
    discarded_navigation_links: int = Field(default=0, ge=0)
    usage: dict[str, int] | None = None
    usage_complete: bool = True
    error_code: str | None = None
    diagnostic: ModelDiagnostic | None = None
    created_at: str
    updated_at: str
