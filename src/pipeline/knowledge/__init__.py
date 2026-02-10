"""Two-layer knowledge provider for context retrieval.

This module implements the knowledge provider interface that combines:
- Vector store (Qdrant) for semantic search
- Code graph (PostgreSQL/GraphQL) for structural traversal

The combined query pattern: semantic search → extract ARNs → graph traversal
provides rich context for issue understanding and implementation.

Requirements:
- 12.1: Knowledge provider interface for two-layer retrieval
- 12.2: Semantic search against vector store
- 12.3: Graph traversal for code relationships
- 12.4: ARN resolution to file locations
"""

from src.pipeline.knowledge.graph import CodeGraphClient, CodeGraphError
from src.pipeline.knowledge.provider import (
    CodeSymbol,
    DefaultKnowledgeProvider,
    GraphTraversalResult,
    KnowledgeProvider,
    ResolvedARN,
    SemanticSearchResult,
)
from src.pipeline.knowledge.vector import VectorStoreClient, VectorStoreError

__all__ = [
    "CodeGraphClient",
    "CodeGraphError",
    "CodeSymbol",
    "DefaultKnowledgeProvider",
    "GraphTraversalResult",
    "KnowledgeProvider",
    "ResolvedARN",
    "SemanticSearchResult",
    "VectorStoreClient",
    "VectorStoreError",
]
