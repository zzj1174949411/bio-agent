"""Parser-independent, versioned local document contracts."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class Location(Record):
    page: int = Field(ge=1, le=200)
    bbox: tuple[float, float, float, float]
    origin: str


class Element(Record):
    id: str
    kind: str
    order: int = Field(ge=0)
    section: tuple[str, ...] = ()
    text: str = ""
    locations: tuple[Location, ...] = ()
    captions: tuple[str, ...] = ()
    footnotes: tuple[str, ...] = ()
    # Full cell/header/span data; numeric values remain paper text, not computed facts.
    table: dict[str, Any] | None = None
    asset_id: UUID | None = None
    ocr_text: str = ""
    visual_semantics: Literal["not_performed"] = "not_performed"


class Asset(Record):
    id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["image/png"] = "image/png"


class ParsedDocument(Record):
    schema_version: Literal["parsed.v1"] = "parsed.v1"
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str
    settings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    models_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1, le=200)
    elements: tuple[Element, ...] = Field(max_length=100000)
    assets: tuple[Asset, ...] = Field(default=(), max_length=2000)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Raw page extraction cells preserve from_ocr/confidence/rect without inventing
    # text origins when layout assembly merges OCR and digital text.
    page_text_cells: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    software_versions: dict[str, str] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def references(self) -> "ParsedDocument":
        ids = {asset.id for asset in self.assets}
        if len(ids) != len(self.assets):
            raise ValueError("duplicate assets")
        if len({item.id for item in self.elements}) != len(self.elements):
            raise ValueError("duplicate elements")
        for index, item in enumerate(self.elements):
            if item.order != index or (item.asset_id is not None and item.asset_id not in ids):
                raise ValueError("invalid order or asset reference")
            if any(location.page > self.page_count for location in item.locations):
                raise ValueError("invalid page reference")
        return self


class LocalReference(Record):
    """Task 39 may add chunks; never masquerades as an HTTPS KnowledgeEvidence."""

    schema_version: Literal["local-reference.v1"] = "local-reference.v1"
    base_id: UUID
    document_id: UUID
    revision_id: UUID
    element_id: str
    page: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


Status = Literal["QUEUED", "PARSING", "PARSED", "INDEXING", "READY", "FAILED", "CANCELLED"]


class BaseRecord(Record):
    id: UUID
    name: str
    created_at: str


class JobRecord(Record):
    id: UUID
    document_id: UUID
    revision_id: UUID
    revision: int
    source_sha256: str
    status: Status
    stage: str
    progress: int
    error_code: str | None
    created_at: str
    updated_at: str


class DocumentRecord(Record):
    id: UUID
    base_id: UUID
    filename: str
    source_sha256: str
    created_at: str
    status: Status
    current_revision: UUID
    published_revision: UUID | None
    index_revision: UUID | None
    job: JobRecord
    warnings: tuple[str, ...] = ()


class ImportRecord(Record):
    document: DocumentRecord
    duplicate: bool


class BasePage(Record):
    items: tuple[BaseRecord, ...]


class DocumentPage(Record):
    items: tuple[DocumentRecord, ...]


class ImportPage(Record):
    items: tuple[ImportRecord, ...]


class ParsedResponse(ParsedDocument):
    document_id: UUID
    base_id: UUID
    revision_id: UUID
    parsed_sha256: str


class ReadinessRecord(Record):
    ready: bool
    code: Literal[
        "OK",
        "KNOWLEDGE_DEPENDENCY_MISSING",
        "KNOWLEDGE_DEPENDENCY_VERSION",
        "KNOWLEDGE_MODELS_MISSING",
        "KNOWLEDGE_MODELS_INVALID",
    ]
    parser_version: str | None = None
    verification: Literal["full_sha256", "presence_only"] | None = None
    prepare_command: str | None = None


class ErrorDetail(Record):
    code: Literal[
        "LOCAL_HOST_REJECTED",
        "LOCAL_ORIGIN_REJECTED",
        "CSRF_TOKEN_REQUIRED",
        "BASE_NOT_FOUND",
        "DOCUMENT_NOT_FOUND",
        "JOB_NOT_FOUND",
        "ASSET_NOT_FOUND",
        "REVISION_NOT_PUBLISHED",
        "JOB_CONFLICT",
        "PDF_TOO_LARGE",
        "REQUEST_TOO_LARGE",
        "PDF_INVALID",
        "PDF_BATCH_LIMIT",
        "BASE_NAME_INVALID",
        "INVALID_ID",
        "REQUEST_INVALID",
        "RESOURCE_INTEGRITY_FAILED",
        "PARSE_OUTPUT_INVALID",
        "KNOWLEDGE_UNAVAILABLE",
    ]


class ErrorResponse(Record):
    detail: ErrorDetail
