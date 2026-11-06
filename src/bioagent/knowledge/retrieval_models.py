"""Versioned local evidence and public retrieval/answer API contracts."""

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from bioagent.knowledge.models import Location, Record
from bioagent.knowledge.snapshots import WikiSnapshot as WikiSnapshot
from bioagent.models.diagnostics import ModelDiagnostic
from bioagent.models.profiles import ModelSnapshot

KnowledgeMode = Literal["rag", "wiki", "hybrid"]


class WikiNavigation(Record):
    base_id: UUID
    generation: UUID
    page_id: UUID
    title: str
    statements: tuple[str, ...]
    source_chunk_ids: tuple[UUID, ...]
    ai_generated: Literal[True] = True
    human_reviewed: Literal[False] = False
    independent_study: Literal[False] = False


class ContextAudit(Record):
    original_retrieved: int = 0
    wiki_retrieved: int = 0
    linked_original_retrieved: int = 0
    original_sent: int = 0
    wiki_sent: int = 0
    original_bytes: int = 0
    wiki_bytes: int = 0
    context_bytes: int = 0
    sent_chunk_ids: tuple[UUID, ...] = ()
    sent_page_ids: tuple[UUID, ...] = ()
    original_search_sent: int = 0
    linked_only_sent: int = 0
    duplicate_candidates: int = 0
    selection_version: str = "round-robin-topk-v1"


class SourceSpan(Record):
    """An exact slice of one parsed element field, not a claim about entailment."""

    element_id: str
    field: Literal["text", "ocr_text", "captions", "footnotes", "table_cells"]
    field_index: int = Field(default=0, ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    chunk_start: int = Field(ge=0)
    chunk_end: int = Field(gt=0)
    locations: tuple[Location, ...] = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Chunk(Record):
    id: UUID
    element_id: str
    parent_element_id: str | None = None
    kind: str
    section: tuple[str, ...]
    text: str
    context: str = ""
    context_element_ids: tuple[str, ...] = ()
    locations: tuple[Location, ...]
    asset_id: UUID | None = None
    part: int
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    visual_semantics: Literal["not_performed"] = "not_performed"
    # element_id/locations[0] remain a compatible navigation anchor only.
    # Merged excerpts are attributed to ALL exact source slices below.
    sources: tuple[SourceSpan, ...] = ()
    chunking_algorithm: str = "element-char1200-v1"
    token_count: int | None = None
    token_overflow: bool = False


class LocalEvidence(Record):
    schema_version: Literal["local-evidence.v2"] = "local-evidence.v2"
    base_id: UUID
    document_id: UUID
    parse_revision: UUID
    index_revision: UUID
    chunk_id: UUID
    element_id: str
    page: int = Field(ge=1, le=200)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SearchRequest(Record):
    query: str = Field(min_length=1, max_length=4096)
    knowledge_base_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)
    top_k: int = Field(default=6, ge=1, le=20, strict=True)
    mode: KnowledgeMode = "rag"

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query required")
        return value.strip()


class SearchHit(Record):
    reference: LocalEvidence
    chunk: Chunk
    score: float
    dense_score: float | None = None
    keyword_score: float | None = None
    pdf_url: str
    asset_url: str | None = None


class RetrievalInfo(Record):
    method: Literal["bm25+dense-rrf60"]
    model_identity: str
    dimension: int
    index_revisions: tuple[UUID, ...]
    scope: tuple[UUID, ...]
    semantic_truth_verified: Literal[False] = False
    chunking_algorithms: tuple[str, ...] = ()


class SearchResponse(Record):
    code: Literal["OK", "NO_EVIDENCE"]
    items: tuple[SearchHit, ...] = ()
    retrieval: RetrievalInfo
    requested_mode: KnowledgeMode = "rag"
    actual_mode: KnowledgeMode = "rag"
    fallback_reason: str | None = None
    wiki_navigation: tuple[WikiNavigation, ...] = ()
    audit: ContextAudit | None = None


class RetrievalReadiness(Record):
    ready: bool
    code: str
    model_id: str
    revision: str
    dimension: int
    verification: Literal["full_sha256"] = "full_sha256"
    prepare_command: str | None = None


class IndexJob(Record):
    id: UUID
    document_id: UUID
    parse_revision: UUID
    index_revision: UUID
    model_identity: str
    dimension: int
    status: Literal["QUEUED", "INDEXING", "READY", "FAILED", "CANCELLED"]
    progress: int = 0
    error_code: str | None = None
    created_at: str
    updated_at: str
    chunking_algorithm: str = "element-char1200-v1"


class IndexState(Record):
    document_id: UUID
    index_revision: UUID | None
    latest_job: IndexJob | None


class EvaluationSource(Record):
    base_id: UUID
    document_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parse_revision: UUID
    index_revision: UUID


class EvaluationControls(Record):
    sources: tuple[EvaluationSource, ...] = Field(min_length=1, max_length=100)
    model_snapshot: ModelSnapshot
    max_input_tokens: int | None = Field(default=None, ge=1, le=200000, strict=True)
    max_input_bytes: int | None = Field(default=None, ge=1, le=32000, strict=True)
    max_output_tokens: int = Field(ge=1, le=16000, strict=True)
    context_max_bytes: int = Field(ge=1, le=100000, strict=True)
    temperature: Literal[0] = 0
    seed: Literal[42] = 42
    prompt_version: Literal["rag-answer.v1"] = "rag-answer.v1"
    wiki_snapshots: tuple[WikiSnapshot, ...] = ()


class AskRequest(Record):
    question: str = Field(min_length=1, max_length=4096)
    knowledge_base_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)
    model_profile_id: UUID
    evaluation: EvaluationControls | None = None
    mode: KnowledgeMode = "rag"

    @field_validator("question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return SearchRequest.nonblank(value)


class ModelAnswer(Record):
    answer: str = Field(min_length=1, max_length=16000)
    citations: tuple[UUID, ...] = Field(min_length=1, max_length=6)

    @field_validator("answer")
    @classmethod
    def no_model_generated_source_links(cls, value: str) -> str:
        if re.search(r"(?i)https?://|file://|[a-z]:[\\/]|\\\\|\]\([^)]*\)|<a\b", value):
            raise ValueError("source links must be generated by the server from citation IDs")
        return value


class AskTask(Record):
    id: UUID
    status: Literal[
        "QUEUED",
        "RETRIEVING",
        "GENERATING",
        "VALIDATING",
        "COMPLETED",
        "NO_EVIDENCE",
        "FAILED",
        "CANCELLED",
    ]
    model_profile_id: UUID
    snapshot: ModelSnapshot
    evidence: tuple[SearchHit, ...] = ()
    answer: str | None = None
    citations: tuple[LocalEvidence, ...] = ()
    error_code: str | None = None
    diagnostic: ModelDiagnostic | None = None
    usage: dict[str, int] | None = None
    input_token_upper_bound: int | None = None
    input_bytes: int | None = None
    context_bytes: int | None = None
    evaluation: EvaluationControls | None = None
    created_at: str
    updated_at: str
    status_url: str
    events_url: str
    visual_semantics: Literal["not_performed"] = "not_performed"
    fixed_scope: tuple[UUID, ...] = ()
    fixed_revisions: tuple[UUID, ...] | None = None
    requested_mode: KnowledgeMode = "rag"
    actual_mode: KnowledgeMode = "rag"
    fallback_reason: str | None = None
    wiki_snapshot: tuple[WikiSnapshot, ...] = ()
    wiki_navigation: tuple[WikiNavigation, ...] = ()
    audit: ContextAudit | None = None
    source_epochs: dict[str, int] | None = None


class AskEvent(Record):
    sequence: int
    kind: Literal[
        "status", "retrieval.completed", "answer.delta", "completed", "failed", "cancelled"
    ]
    data: dict[str, Any]


class RetrievalErrorResponse(Record):
    detail: dict[str, str]
