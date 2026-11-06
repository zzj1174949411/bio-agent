from __future__ import annotations

import pytest
from pydantic import ValidationError

from bioagent.retrieval.contracts import DatasetSearchQuery
from bioagent.retrieval.knowledge import (
    KnowledgeEvidence,
    KnowledgeQuery,
    KnowledgeRetrievalError,
    NullKnowledgeRetriever,
)
from bioagent.workbench.actions import DatasetSearchAction


def test_knowledge_contracts_are_frozen_and_do_not_accept_catalog_or_action_payloads() -> None:
    query = KnowledgeQuery(text="bulk RNA-seq quality control")
    evidence = KnowledgeEvidence(
        document_id="geo-handbook",
        chunk_id="section-4",
        source_uri="https://example.invalid/geo-handbook#section-4",
        content_sha256="a" * 64,
    )

    assert query.text == "bulk RNA-seq quality control"
    assert evidence.document_id == "geo-handbook"
    with pytest.raises(ValidationError, match="frozen"):
        evidence.chunk_id = "other"
    with pytest.raises(ValidationError):
        KnowledgeQuery.model_validate(DatasetSearchQuery(text="brain"))
    with pytest.raises(ValidationError):
        KnowledgeEvidence.model_validate(
            DatasetSearchAction(kind="dataset_search", text="brain")
        )


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://reader:secret@example.invalid/handbook",
        "https://example.invalid/handbook?access_token=secret",
        "https://example.invalid/handbook?api_key=secret",
        "https://example.invalid/handbook?authorization=Bearer%20secret",
        "https://example.invalid/handbook?X-Amz-Credential=credential",
        "https://example.invalid/handbook?X-Amz-Signature=signature",
        "https://example.invalid/handbook?X-Amz-Security-Token=token",
        "https://example.invalid/handbook?x-api-key=key",
        "https://example.invalid/handbook?client_secret=secret",
        "https://example.invalid/handbook?session_token=token",
        "https://example.invalid/handbook?refresh_token=token",
        "https://example.invalid/handbook?sig=signature",
        "https://example.invalid/handbook#access_token=secret",
        "https://example.invalid/handbook#X-Amz-Signature=signature",
        "http://example.invalid/handbook",
    ),
)
def test_knowledge_evidence_rejects_credential_bearing_or_insecure_uris(source_uri: str) -> None:
    with pytest.raises(ValidationError, match="source URI"):
        KnowledgeEvidence(
            document_id="geo-handbook",
            chunk_id="section-4",
            source_uri=source_uri,
            content_sha256="a" * 64,
        )


def test_knowledge_evidence_allows_benign_https_citation_query() -> None:
    evidence = KnowledgeEvidence(
        document_id="geo-handbook",
        chunk_id="section-4",
        source_uri="https://example.invalid/geo-handbook?section=4#methods",
        content_sha256="a" * 64,
    )

    assert evidence.source_uri == "https://example.invalid/geo-handbook?section=4#methods"


def test_null_knowledge_retriever_never_turns_rag_text_into_a_dataset() -> None:
    retriever = NullKnowledgeRetriever()

    with pytest.raises(KnowledgeRetrievalError, match="^RAG_NOT_CONFIGURED$") as error:
        retriever.retrieve(KnowledgeQuery(text="Alzheimer disease brain tissue"))

    assert error.value.code == "RAG_NOT_CONFIGURED"
