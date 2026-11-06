"""Credential-free Wiki version capability shared by chat and retrieval contracts."""

from uuid import UUID

from bioagent.knowledge.models import Record


class WikiSnapshot(Record):
    base_id: UUID
    generation: UUID | None = None
    page_ids: tuple[UUID, ...] = ()
