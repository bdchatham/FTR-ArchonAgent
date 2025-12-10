"""
Property-based tests for similarity search ordering.

Feature: archon-rag-system, Property 16: Similarity search ordering
Validates: Requirements 6.2
"""

import os
import sys
from unittest.mock import Mock, MagicMock
from hypothesis import given, strategies as st, settings, assume, HealthCheck

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.vector_store_manager import VectorStoreManager, VectorDocument


# Strategy for generating vectors (using smaller dimension for testing)
@st.composite
def vector_with_dimension(draw, dimension=128):
    """Generate a vector with specified dimension (smaller for testing)."""
    return [draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)) 
            for _ in range(dimension)]


# Strategy for generating search results with scores
@st.composite
def search_results(draw, min_results=1, max_results=10):
    """Generate mock search results with scores."""
    num_results = draw(st.integers(min_value=min_results, max_value=max_results))
    
    results = []
    for i in range(num_results):
        score = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
        results.append({
            'id': f'doc_{i}',
            'score': score,
            'text': f'Document {i}',
            'metadata': {
                'repo_url': 'https://github.com/test/repo',
                'file_path': f'file_{i}.md',
                'chunk_index': i
            },
            'vector': [0.1] * 128
        })
    
    return results


# Feature: archon-rag-system, Property 16: Similarity search ordering
@given(vector_with_dimension(), st.integers(min_value=1, max_value=20), search_results())
@settings(max_examples=100)
def test_similarity_search_results_ordered_by_score(query_vector, k, mock_results):
    """
    For any query embedding, similarity search results should be ordered 
    by relevance score in descending order.
    
    Validates: Requirements 6.2
    """
    # Assume we have at least one result
    assume(len(mock_results) > 0)
    
    # Create mock OpenSearch client
    mock_client = Mock()
    
    # Sort mock results by score descending (simulating OpenSearch behavior)
    sorted_results = sorted(mock_results, key=lambda x: x['score'], reverse=True)
    
    # Take only k results
    limited_results = sorted_results[:k]
    
    # Mock the search response
    mock_response = {
        'hits': {
            'hits': [
                {
                    '_id': result['id'],
                    '_score': result['score'],
                    '_source': {
                        'text': result['text'],
                        'metadata': result['metadata'],
                        'vector': result['vector']
                    }
                }
                for result in limited_results
            ]
        }
    }
    
    mock_client.search = Mock(return_value=mock_response)
    mock_client.indices.exists = Mock(return_value=True)
    
    # Create mock embeddings
    mock_embeddings = Mock()
    
    # Create vector store manager with mocked client and embeddings
    manager = VectorStoreManager(
        opensearch_endpoint="test.endpoint.com",
        index_name="test-index",
        opensearch_client=mock_client,
        embeddings=mock_embeddings
    )
    
    # Perform similarity search
    results = manager.similarity_search(query_vector, k=k)
    
    # Property 1: Results should be ordered by score in descending order
    scores = [result['score'] for result in results]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], \
            f"Results not ordered by score: {scores[i]} < {scores[i + 1]} at position {i}"
    
    # Property 2: Number of results should not exceed k
    assert len(results) <= k, \
        f"Expected at most {k} results, got {len(results)}"
    
    # Property 3: All results should have a score
    assert all('score' in result for result in results), \
        "All results must have a score field"
    
    # Property 4: All scores should be non-negative
    assert all(result['score'] >= 0 for result in results), \
        "All scores must be non-negative"


@given(vector_with_dimension(), st.integers(min_value=1, max_value=5))
@settings(max_examples=100)
def test_similarity_search_with_empty_results(query_vector, k):
    """
    For any query embedding, when no results are found, the search should 
    return an empty list (which is trivially ordered).
    
    Validates: Requirements 6.2
    """
    # Create mock OpenSearch client with empty results
    mock_client = Mock()
    mock_response = {
        'hits': {
            'hits': []
        }
    }
    
    mock_client.search = Mock(return_value=mock_response)
    mock_client.indices.exists = Mock(return_value=True)
    
    # Create mock embeddings
    mock_embeddings = Mock()
    
    # Create vector store manager with mocked client and embeddings
    manager = VectorStoreManager(
        opensearch_endpoint="test.endpoint.com",
        index_name="test-index",
        opensearch_client=mock_client,
        embeddings=mock_embeddings
    )
    
    # Perform similarity search
    results = manager.similarity_search(query_vector, k=k)
    
    # Property: Empty results should be returned as empty list
    assert results == [], \
        f"Expected empty list for no results, got {results}"


@given(vector_with_dimension(), st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_similarity_search_with_single_result(query_vector, k):
    """
    For any query embedding, when only one result is found, it should be 
    returned (trivially ordered).
    
    Validates: Requirements 6.2
    """
    # Create mock OpenSearch client with single result
    mock_client = Mock()
    mock_response = {
        'hits': {
            'hits': [
                {
                    '_id': 'doc_1',
                    '_score': 0.95,
                    '_source': {
                        'text': 'Single document',
                        'metadata': {
                            'repo_url': 'https://github.com/test/repo',
                            'file_path': 'file.md',
                            'chunk_index': 0
                        },
                        'vector': [0.1] * 128
                    }
                }
            ]
        }
    }
    
    mock_client.search = Mock(return_value=mock_response)
    mock_client.indices.exists = Mock(return_value=True)
    
    # Create mock embeddings
    mock_embeddings = Mock()
    
    # Create vector store manager with mocked client and embeddings
    manager = VectorStoreManager(
        opensearch_endpoint="test.endpoint.com",
        index_name="test-index",
        opensearch_client=mock_client,
        embeddings=mock_embeddings
    )
    
    # Perform similarity search
    results = manager.similarity_search(query_vector, k=k)
    
    # Property: Single result should be returned
    assert len(results) == 1, \
        f"Expected 1 result, got {len(results)}"
    
    # Property: Result should have expected structure
    assert 'score' in results[0], \
        "Result must have a score field"
    assert 'text' in results[0], \
        "Result must have a text field"
    assert 'metadata' in results[0], \
        "Result must have a metadata field"
