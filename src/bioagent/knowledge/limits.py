"""One admission contract shared by storage, parser, HTTP boundary and browser."""

from pydantic import BaseModel, ConfigDict

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_REQUEST = 4
MAX_FILES_PER_SELECTION = 100
MAX_REQUEST_BYTES = MAX_FILES_PER_REQUEST * MAX_PDF_BYTES + 1024 * 1024


class UploadLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_pdf_bytes: int = MAX_PDF_BYTES
    max_files_per_request: int = MAX_FILES_PER_REQUEST
    max_files_per_selection: int = MAX_FILES_PER_SELECTION
    max_request_bytes: int = MAX_REQUEST_BYTES
