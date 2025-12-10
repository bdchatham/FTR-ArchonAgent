"""
Property-based tests for metadata completeness in vector storage.

Feature: archon-rag-system, Property 10: Metadata completeness in vector storage
Validates: Requirements 4.2, 4.3
"""

import os
import sys
from unittest.mock import Mock
from hypothesis import given, strategies as st, settings
from datetime import datetime, timezone


from ingestion.ingestion_pipeline import IngestionPipeline, Document, DocumentChunk


# Strategy for generating valid GitHub URLs
@st.composite
def github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


# Strategy for generating file paths
@st.composite
def file_path(draw):
    """Generate valid file paths."""
    parts = draw(st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-.'),
            min_size=1,
            max_size=20
        ),
        min_size=1,
        max_size=5
    ))
    return '/'.join(parts) + '.md'


# Strategy for generating documents
@st.composite
def document(draw):
    """Generate random Document objects."""
    return Document(
        repo_url=draw(github_url()),
        file_path=draw(file_path()),
        content=draw(st.text(min_size=10, max_size=1000)),
        sha=draw(st.text(alphabet='0123456789abcdef', min_size=40, max_size=40)),
        last_modified=datetime.now(timezone.utc),
        document_type="kiro_doc",
        source_type="github"
    )


# Feature: archon-rag-system, Property 10: Metadata completeness in vector storage
@given(document())
@settings(max_examples=100)
def test_metadata_completeness_in_vector_storage(doc):
    """
    For any document stored in the vector database, the metadata should include 
    repo_url, file_path, and last_modified timestamp.
    
    Validates: Requirements 4.2, 4.3
    """
    # Create mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * 1536)
    
    # Create pipeline
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    # Chunk the document
    chunks = pipeline.chunk_document(doc)
    
    # Generate embeddings for chunks
    embeddings = [[0.1] * 1536 for _ in chunks]
    
    # Create vector documents
    vector_docs = pipeline.create_vector_documents(chunks, embeddings)
    
    # Property: Every vector document must have complete metadata
    for vector_doc in vector_docs:
        # Must have repo_url
        assert 'repo_url' in vector_doc.metadata, \
            "Metadata must include repo_url"
        assert vector_doc.metadata['repo_url'] == doc.repo_url, \
            "repo_url in metadata must match document repo_url"
        
        # Must have file_path
        assert 'file_path' in vector_doc.metadata, \
            "Metadata must include file_path"
        assert vector_doc.metadata['file_path'] == doc.file_path, \
            "file_path in metadata must match document file_path"
        
        # Must have last_modified timestamp
        assert 'last_modified' in vector_doc.metadata, \
            "Metadata must include last_modified timestamp"
        assert vector_doc.metadata['last_modified'] == doc.last_modified.isoformat(), \
            "last_modified in metadata must match document timestamp"
        
        # Must have document_type
        assert 'document_type' in vector_doc.metadata, \
            "Metadata must include document_type"
        assert vector_doc.metadata['document_type'] == doc.document_type, \
            "document_type in metadata must match document"
        
        # Must have source_type
        assert 'source_type' in vector_doc.metadata, \
            "Metadata must include source_type"
        assert vector_doc.metadata['source_type'] == doc.source_type, \
            "source_type in metadata must match document"


@given(st.lists(document(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_metadata_completeness_across_multiple_documents(docs):
    """
    For any list of documents, all vector documents should have complete metadata.
    
    Validates: Requirements 4.2, 4.3
    """
    # Create mock embeddings
    mock_embeddings = Mock()
    mock_embeddings.embed_query = Mock(return_value=[0.1] * 1536)
    
    # Create pipeline
    pipeline = IngestionPipeline(
        embedding_model="amazon.titan-embed-text-v1",
        embeddings=mock_embeddings
    )
    
    all_vector_docs = []
    
    for doc in docs:
        # Chunk the document
        chunks = pipeline.chunk_document(doc)
        
        # Generate embeddings for chunks
        embeddings = [[0.1] * 1536 for _ in chunks]
        
        # Create vector documents
        vector_docs = pipeline.create_vector_documents(chunks, embeddings)
        all_vector_docs.extend(vector_docs)
    
    # Property: All vector documents must have the required metadata fields
    required_fields = ['repo_url', 'file_path', 'last_modified', 'document_type', 'source_type']
    
    for vector_doc in all_vector_docs:
        for field in required_fields:
            assert field in vector_doc.metadata, \
                f"All vector documents must have {field} in metadata"
        
        # Property: Metadata values must be non-empty strings
        assert isinstance(vector_doc.metadata['repo_url'], str) and vector_doc.metadata['repo_url'], \
            "repo_url must be a non-empty string"
        assert isinstance(vector_doc.metadata['file_path'], str) and vector_doc.metadata['file_path'], \
            "file_path must be a non-empty string"
        assert isinstance(vector_doc.metadata['last_modified'], str) and vector_doc.metadata['last_modified'], \
            "last_modified must be a non-empty string"
