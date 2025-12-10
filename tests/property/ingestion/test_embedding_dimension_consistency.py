"""
Property-based tests for embedding dimension consistency.

Feature: archon-rag-system, Property 9: Embedding dimension consistency
Validates: Requirements 4.1
"""

import os
import sys
from unittest.mock import Mock, MagicMock
from hypothesis import given, strategies as st, settings


from ingestion.ingestion_pipeline import IngestionPipeline, Document
from datetime import datetime, timezone


# Strategy for generating document text
@st.composite
def document_text(draw):
    """Generate various document text samples."""
    # Generate text of varying lengths
    text = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'P', 'Z')),
        min_size=10,
        max_size=5000
    ))
    return text


# Feature: archon-rag-system, Property 9: Embedding dimension consistency
@given(document_text())
@settings(max_examples=100)
def test_embedding_dimension_consistency(text):
    """
    For any document text, generated embeddings should have the configured 
    dimension size (1536 for Titan).
    
    Validates: Requirements 4.1
    """
    # Expected dimension for Titan embeddings
    EXPECTED_DIMENSION = 1536
    
    # Create mock Bedrock embeddings that return consistent dimensions
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * EXPECTED_DIMENSION)
    
    # Create pipeline with mocked embeddings
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    # Generate embedding
    embedding = pipeline.generate_embeddings(text)
    
    # Property: Embedding dimension must match expected dimension
    assert len(embedding) == EXPECTED_DIMENSION, \
        f"Expected embedding dimension {EXPECTED_DIMENSION}, got {len(embedding)}"
    
    # Property: All embedding values should be floats
    assert all(isinstance(val, (int, float)) for val in embedding), \
        "All embedding values must be numeric"


@given(st.lists(document_text(), min_size=1, max_size=10))
@settings(max_examples=100)
def test_embedding_dimension_consistency_across_multiple_texts(texts):
    """
    For any list of document texts, all generated embeddings should have 
    the same dimension size.
    
    Validates: Requirements 4.1
    """
    EXPECTED_DIMENSION = 1536
    
    # Create mock Bedrock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * EXPECTED_DIMENSION)
    
    # Create pipeline with mocked embeddings
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    # Generate embeddings for all texts
    embeddings = [pipeline.generate_embeddings(text) for text in texts]
    
    # Property: All embeddings must have the same dimension
    dimensions = [len(emb) for emb in embeddings]
    assert all(dim == EXPECTED_DIMENSION for dim in dimensions), \
        f"All embeddings must have dimension {EXPECTED_DIMENSION}, got {dimensions}"
    
    # Property: Dimension consistency across all embeddings
    assert len(set(dimensions)) == 1, \
        f"All embeddings must have the same dimension, got {set(dimensions)}"
