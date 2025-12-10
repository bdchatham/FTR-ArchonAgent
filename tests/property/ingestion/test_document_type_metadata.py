"""
Property-based tests for document type metadata presence.

Feature: archon-rag-system, Property 23: Document type metadata presence
Validates: Requirements 10.3
"""

import os
import sys
from unittest.mock import Mock
from hypothesis import given, strategies as st, settings
from datetime import datetime, timezone


from ingestion.ingestion_pipeline import IngestionPipeline, Document


# Strategy for generating documents with various types
@st.composite
def document_with_type(draw):
    """Generate documents with different document types and source types."""
    doc_type = draw(st.sampled_from(['kiro_doc', 'code', 'readme', 'config']))
    source_type = draw(st.sampled_from(['github', 'gitlab', 'local', 's3']))
    
    return Document(
        repo_url="https://github.com/test/repo",
        file_path=draw(st.text(min_size=5, max_size=50)),
        content=draw(st.text(min_size=10, max_size=500)),
        sha=draw(st.text(alphabet='0123456789abcdef', min_size=40, max_size=40)),
        last_modified=datetime.now(timezone.utc),
        document_type=doc_type,
        source_type=source_type
    )


# Feature: archon-rag-system, Property 23: Document type metadata presence
@given(document_with_type())
@settings(max_examples=100)
def test_document_type_metadata_presence(doc):
    """
    For any document stored in the knowledge base, the metadata should include 
    both document_type and source_type fields.
    
    Validates: Requirements 10.3
    """
    # Create mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * 1536)
    
    # Create pipeline
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    # Chunk document
    chunks = pipeline.chunk_document(doc)
    
    # Generate embeddings
    embeddings = [[0.1] * 1536 for _ in chunks]
    
    # Create vector documents
    vector_docs = pipeline.create_vector_documents(chunks, embeddings)
    
    # Property: Every vector document must have document_type in metadata
    for vector_doc in vector_docs:
        assert 'document_type' in vector_doc.metadata, \
            "Metadata must include document_type field"
        assert vector_doc.metadata['document_type'] == doc.document_type, \
            f"document_type must match original: expected {doc.document_type}, got {vector_doc.metadata['document_type']}"
    
    # Property: Every vector document must have source_type in metadata
    for vector_doc in vector_docs:
        assert 'source_type' in vector_doc.metadata, \
            "Metadata must include source_type field"
        assert vector_doc.metadata['source_type'] == doc.source_type, \
            f"source_type must match original: expected {doc.source_type}, got {vector_doc.metadata['source_type']}"


@given(st.lists(document_with_type(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_document_type_metadata_across_multiple_documents(docs):
    """
    For any list of documents with different types, all vector documents 
    should preserve their respective document_type and source_type.
    
    Validates: Requirements 10.3
    """
    # Create mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * 1536)
    
    # Create pipeline
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    for doc in docs:
        # Chunk document
        chunks = pipeline.chunk_document(doc)
        
        # Generate embeddings
        embeddings = [[0.1] * 1536 for _ in chunks]
        
        # Create vector documents
        vector_docs = pipeline.create_vector_documents(chunks, embeddings)
        
        # Property: All vector documents from this doc must have both type fields
        for vector_doc in vector_docs:
            assert 'document_type' in vector_doc.metadata, \
                "All vector documents must have document_type"
            assert 'source_type' in vector_doc.metadata, \
                "All vector documents must have source_type"
            
            # Property: Types must match the original document
            assert vector_doc.metadata['document_type'] == doc.document_type, \
                f"document_type mismatch: expected {doc.document_type}, got {vector_doc.metadata['document_type']}"
            assert vector_doc.metadata['source_type'] == doc.source_type, \
                f"source_type mismatch: expected {doc.source_type}, got {vector_doc.metadata['source_type']}"


@given(document_with_type())
@settings(max_examples=100)
def test_document_type_fields_are_strings(doc):
    """
    For any document, the document_type and source_type fields should be 
    non-empty strings.
    
    Validates: Requirements 10.3
    """
    # Create mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * 1536)
    
    # Create pipeline
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    # Chunk document
    chunks = pipeline.chunk_document(doc)
    
    # Generate embeddings
    embeddings = [[0.1] * 1536 for _ in chunks]
    
    # Create vector documents
    vector_docs = pipeline.create_vector_documents(chunks, embeddings)
    
    # Property: document_type and source_type must be non-empty strings
    for vector_doc in vector_docs:
        assert isinstance(vector_doc.metadata['document_type'], str), \
            "document_type must be a string"
        assert len(vector_doc.metadata['document_type']) > 0, \
            "document_type must not be empty"
        
        assert isinstance(vector_doc.metadata['source_type'], str), \
            "source_type must be a string"
        assert len(vector_doc.metadata['source_type']) > 0, \
            "source_type must not be empty"
