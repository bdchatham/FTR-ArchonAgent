"""
Property-based tests for embedding generation retry with exponential backoff.

Feature: archon-rag-system, Property 12: Embedding generation retry with backoff
Validates: Requirements 4.5
"""

import os
import sys
import time
from unittest.mock import Mock, call
from hypothesis import given, strategies as st, settings


from ingestion.ingestion_pipeline import IngestionPipeline, EmbeddingGenerationError


# Strategy for generating text
@st.composite
def text_content(draw):
    """Generate text content."""
    return draw(st.text(min_size=10, max_size=500))


# Feature: archon-rag-system, Property 12: Embedding generation retry with backoff
@given(text_content())
@settings(max_examples=100)
def test_embedding_retry_with_exponential_backoff(text):
    """
    For any embedding generation failure, the system should retry with 
    exponentially increasing delays and log the failure after exhausting retries.
    
    Validates: Requirements 4.5
    """
    # Create mock embeddings that fails initially
    mock_embeddings = Mock()
    
    # Configure to fail twice, then succeed
    mock_embeddings.embed_query = Mock(
        side_effect=[
            Exception("Temporary failure 1"),
            Exception("Temporary failure 2"),
            [0.1] * 1536  # Success on third try
        ]
    )
    
    # Create pipeline with very short backoff times for testing
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings,
        initial_backoff=0.001,  # 1ms
        max_backoff=0.1
    )
    
    # Generate embedding (should succeed after retries)
    embedding = pipeline.generate_embeddings(text)
    
    # Property: Should eventually succeed after retries
    assert embedding is not None, "Should eventually succeed after retries"
    assert len(embedding) == 1536, "Should return valid embedding"
    
    # Property: Should have called embed_query 3 times (2 failures + 1 success)
    assert mock_embeddings.embed_query.call_count == 3, \
        f"Should retry exactly 2 times before success, got {mock_embeddings.embed_query.call_count - 1} retries"


@given(text_content())
@settings(max_examples=100)
def test_embedding_retry_exhaustion_raises_error(text):
    """
    For any embedding generation that fails all retries, the system should 
    raise an EmbeddingGenerationError.
    
    Validates: Requirements 4.5
    """
    # Create mock embeddings that always fails
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(side_effect=Exception("Persistent failure"))
    
    # Create pipeline with very short backoff times for testing
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings,
        initial_backoff=0.001,  # 1ms
        max_backoff=0.1
    )
    
    # Property: Should raise EmbeddingGenerationError after exhausting retries
    try:
        pipeline.generate_embeddings(text)
        assert False, "Should have raised EmbeddingGenerationError"
    except EmbeddingGenerationError as e:
        # Property: Error message should mention retries
        assert "retries" in str(e).lower(), \
            "Error message should mention retries"
        
        # Property: Should have attempted max_retries times
        assert mock_embeddings.embed_query.call_count == pipeline.max_retries, \
            f"Should retry exactly {pipeline.max_retries} times, got {mock_embeddings.embed_query.call_count}"


@given(st.integers(min_value=1, max_value=2))
@settings(max_examples=50)
def test_embedding_retry_count_property(failure_count):
    """
    For any number of failures less than max_retries, the system should 
    eventually succeed after that many retries.
    
    Validates: Requirements 4.5
    """
    text = "test content"
    
    # Create mock embeddings that fails N times then succeeds
    mock_embeddings = Mock()
    
    # Create side effects: N failures followed by success
    side_effects = [Exception(f"Failure {i}") for i in range(failure_count)]
    side_effects.append([0.1] * 1536)  # Success
    
    mock_embeddings.embed_query = Mock(side_effect=side_effects)
    
    # Create pipeline with very short backoff times for testing
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings,
        initial_backoff=0.001,  # 1ms
        max_backoff=0.1
    )
    
    # Generate embedding
    embedding = pipeline.generate_embeddings(text)
    
    # Property: Should succeed after exactly failure_count retries
    assert embedding is not None, "Should succeed after retries"
    assert mock_embeddings.embed_query.call_count == failure_count + 1, \
        f"Should call embed_query {failure_count + 1} times (failures + success)"


@given(text_content())
@settings(max_examples=100)
def test_embedding_backoff_timing_increases(text):
    """
    For any embedding generation with retries, the delay between retries 
    should increase exponentially.
    
    Validates: Requirements 4.5
    """
    # Create mock embeddings that fails twice then succeeds
    mock_embeddings = Mock()
    
    mock_embeddings.embed_query = Mock(
        side_effect=[
            Exception("Failure 1"),
            Exception("Failure 2"),
            [0.1] * 1536
        ]
    )
    
    # Use specific backoff values to test exponential growth
    initial_backoff = 0.01  # 10ms
    
    # Create pipeline with test backoff times
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings,
        initial_backoff=initial_backoff,
        max_backoff=1.0
    )
    
    # Record timing
    start_time = time.time()
    embedding = pipeline.generate_embeddings(text)
    elapsed = time.time() - start_time
    
    # Property: Should succeed
    assert embedding is not None, "Should succeed after retries"
    
    # Property: Total elapsed time should reflect exponential backoff
    # First retry: initial_backoff * 2^0 = 0.01s
    # Second retry: initial_backoff * 2^1 = 0.02s
    # Total: at least 0.03s
    expected_min_time = initial_backoff * (2**0) + initial_backoff * (2**1)
    assert elapsed >= expected_min_time, \
        f"Elapsed time {elapsed:.4f}s should be at least {expected_min_time:.4f}s for exponential backoff"
