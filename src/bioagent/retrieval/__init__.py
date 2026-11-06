"""Stable, non-executable retrieval contracts."""

from bioagent.retrieval.contracts import (
    AnalysisReadiness,
    DatasetCatalogProvider,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchQuery,
    EvidenceRef,
)
from bioagent.retrieval.knowledge import (
    KnowledgeEvidence,
    KnowledgeQuery,
    KnowledgeRetrievalError,
    KnowledgeRetriever,
    NullKnowledgeRetriever,
)

__all__ = [
    "AnalysisReadiness",
    "DatasetCatalogProvider",
    "DatasetSearchHit",
    "DatasetSearchPage",
    "DatasetSearchQuery",
    "EvidenceRef",
    "KnowledgeEvidence",
    "KnowledgeQuery",
    "KnowledgeRetrievalError",
    "KnowledgeRetriever",
    "NullKnowledgeRetriever",
]
